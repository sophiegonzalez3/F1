"""
QUALI tab — qualifying-specific analysis for the loaded meeting.

Practice, stints, and the race all have dedicated deep-dives; qualifying was
only covered indirectly. This tab reads the loaded Qualifying session from
`state.laps` (sector times, speed traps, session results Q1/Q2/Q3 are all
already enriched onto it) and answers four questions:

  1. How did each driver progress through Q1 → Q2 → Q3?
  2. Who left time on the table (theoretical best vs actual best)?
  3. Who set their lap early on an improving track (and was under-rewarded)?
  4. Whose headline lap leaned on a tow / low-drag run? (speed-trap proxy)
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc

import f1lib.state as state
from f1lib.components import theme, card, kpi, tip, GFX
from f1lib.glossary import gloss
from f1lib.config import TEAM_COLORS, TEXT_DIM, TEXT_MAIN, GRID_CLR, ACCENT
from f1lib.processing import format_lap_time
from tabs.quali_replay import quali3d_card

_SECTORS = ["Sector1Time", "Sector2Time", "Sector3Time"]


def _quali_laps() -> tuple[pd.DataFrame, str | None]:
    """Laps of the loaded meeting's qualifying session (prefers Qualifying
    over Sprint Qualifying when both are loaded)."""
    laps = state.laps
    if laps is None or laps.empty or "session" not in laps.columns:
        return pd.DataFrame(), None
    for sess in ("Qualifying", "Sprint Qualifying"):
        ql = laps[laps["session"] == sess]
        if not ql.empty:
            return ql.copy(), sess
    return pd.DataFrame(), None


def _driver_color(ql: pd.DataFrame) -> dict[str, str]:
    m = (ql.dropna(subset=["Driver_Short", "Team"])
         .drop_duplicates("Driver_Short").set_index("Driver_Short")["Team"])
    return {d: TEAM_COLORS.get(t, "#808080") for d, t in m.items()}


def _teammate_dash(ql: pd.DataFrame) -> dict[str, str]:
    """Second driver of each team (alphabetical) gets a dashed line."""
    dash = {}
    for _, g in (ql.drop_duplicates("Driver_Short")
                 .dropna(subset=["Team"]).groupby("Team")):
        for i, d in enumerate(sorted(g["Driver_Short"])):
            dash[d] = "solid" if i == 0 else "dash"
    return dash


# ── 1. Q1 → Q2 → Q3 progression ─────────────────────────────

def _progression_fig(ql: pd.DataFrame) -> go.Figure:
    per = (ql.dropna(subset=["Driver_Short"])
           .drop_duplicates("Driver_Short")
           .set_index("Driver_Short")[["Q1_s", "Q2_s", "Q3_s"]])
    per = per.dropna(how="all")
    fig = go.Figure()
    if per.empty:
        theme(fig, 460, "")
        fig.add_annotation(text="No Q1/Q2/Q3 times in the session results.",
                           xref="paper", yref="paper", x=0.5, y=0.5,
                           showarrow=False, font=dict(color=TEXT_DIM))
        return fig
    best = per.min()                       # segment benchmarks
    colors, dashes = _driver_color(ql), _teammate_dash(ql)
    # order legend by final position: Q3 time, then Q2, then Q1
    order = per.sort_values(["Q3_s", "Q2_s", "Q1_s"]).index
    segs = ["Q1", "Q2", "Q3"]
    for drv in order:
        gaps, hover = [], []
        for seg in segs:
            t = per.loc[drv, f"{seg}_s"]
            if pd.notna(t) and pd.notna(best[f"{seg}_s"]):
                gaps.append((t / best[f"{seg}_s"] - 1) * 100)
                hover.append(f"{seg}: {format_lap_time(t)} "
                             f"(+{t - best[f'{seg}_s']:.3f}s)")
            else:
                gaps.append(None); hover.append(f"{seg}: —")
        fig.add_trace(go.Scatter(
            x=segs, y=gaps, mode="lines+markers", name=drv,
            line=dict(color=colors.get(drv, "#808080"), width=2,
                      dash=dashes.get(drv, "solid")),
            marker=dict(size=7),
            customdata=np.array(hover, dtype=object),
            hovertemplate=f"<b>{drv}</b> · %{{customdata}}<extra></extra>",
        ))
    theme(fig, 520)
    fig.update_yaxes(title_text="Gap to segment best (%)")
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0, font=dict(size=10)))
    return fig


# ── 2. Theoretical best vs actual ────────────────────────────

def _ideal_lap_table(ql: pd.DataFrame) -> pd.DataFrame:
    ok = ql[~ql["IsDeleted"].fillna(False).astype(bool)]
    rows = []
    for drv, g in ok.groupby("Driver_Short"):
        secs = [pd.to_numeric(g[c], errors="coerce").min() for c in _SECTORS]
        actual = pd.to_numeric(g["LapTime_s"], errors="coerce").min()
        if any(pd.isna(s) for s in secs) or pd.isna(actual):
            continue
        ideal = float(sum(secs))
        rows.append({"driver": drv, "team": g["Team"].iloc[0],
                     "actual": actual, "ideal": ideal,
                     "left": round(actual - ideal, 3),
                     "s1": secs[0], "s2": secs[1], "s3": secs[2]})
    return pd.DataFrame(rows).sort_values("left", ascending=False)


def _ideal_fig(t: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Bar(
        y=t["driver"], x=t["left"], orientation="h",
        marker_color=[TEAM_COLORS.get(x, "#808080") for x in t["team"]],
        customdata=np.stack([t["actual"].map(format_lap_time),
                             t["ideal"].map(format_lap_time)], axis=-1),
        hovertemplate=("<b>%{y}</b><br>Best real lap: %{customdata[0]}<br>"
                       "Theoretical best: %{customdata[1]}<br>"
                       "Left on the table: %{x:.3f}s<extra></extra>"),
        text=[f"{v:.3f}s" for v in t["left"]], textposition="outside",
        textfont=dict(size=10),
    ))
    theme(fig, max(340, 24 * len(t) + 110))
    fig.update_xaxes(title_text="Best lap − theoretical best (s)",
                     range=[0, float(t["left"].max()) * 1.2 if len(t) else 1])
    fig.update_layout(showlegend=False, bargap=0.3)
    return fig


# ── 3. Track evolution / when the lap was set ────────────────

def _evolution_fig(ql: pd.DataFrame) -> go.Figure:
    ok = ql[~ql["IsDeleted"].fillna(False).astype(bool)].copy()
    ok["t"] = pd.to_numeric(ok["LapStartTime"], errors="coerce")
    ok["lt"] = pd.to_numeric(ok["LapTime_s"], errors="coerce")
    ok = ok.dropna(subset=["t", "lt"])
    # flying laps only: within 110% of the session best
    ok = ok[ok["lt"] <= ok["lt"].min() * 1.10]
    fig = go.Figure()
    if ok.empty:
        theme(fig, 460, "")
        return fig
    t0 = ok["t"].min()
    ok["min_in"] = (ok["t"] - t0) / 60.0

    fig.add_trace(go.Scatter(
        x=ok["min_in"], y=ok["lt"], mode="markers", name="all flying laps",
        marker=dict(size=5, color="#666", opacity=0.5),
        customdata=np.stack([ok["Driver_Short"],
                             ok["lt"].map(format_lap_time)], axis=-1),
        hovertemplate="%{customdata[0]} · %{customdata[1]}<extra></extra>"))
    run = ok.sort_values("min_in")
    run["best_so_far"] = run["lt"].cummin()
    fig.add_trace(go.Scatter(
        x=run["min_in"], y=run["best_so_far"], mode="lines",
        name="session best so far",
        line=dict(color="#39B54A", width=2, shape="hv"),
        hovertemplate="best so far: %{y:.3f}s<extra></extra>"))

    colors = _driver_color(ql)
    bests = ok.loc[ok.groupby("Driver_Short")["lt"].idxmin()]
    fig.add_trace(go.Scatter(
        x=bests["min_in"], y=bests["lt"], mode="markers+text",
        text=bests["Driver_Short"], textposition="top center",
        textfont=dict(size=9),
        marker=dict(size=9,
                    color=[colors.get(d, "#808080")
                           for d in bests["Driver_Short"]],
                    line=dict(width=1, color="#000")),
        name="driver's best lap",
        customdata=np.stack([bests["Driver_Short"],
                             bests["lt"].map(format_lap_time)], axis=-1),
        hovertemplate=("<b>%{customdata[0]}</b> best: %{customdata[1]} "
                       "at %{x:.0f} min<extra></extra>")))
    theme(fig, 500)
    fig.update_xaxes(title_text="Minutes into qualifying")
    fig.update_yaxes(title_text="Lap time (s)")
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0))
    return fig


# ── 4. Tow / low-drag proxy from the speed trap ──────────────

def _tow_fig(ql: pd.DataFrame) -> go.Figure:
    ok = ql[~ql["IsDeleted"].fillna(False).astype(bool)].copy()
    ok["lt"] = pd.to_numeric(ok["LapTime_s"], errors="coerce")
    ok["st"] = pd.to_numeric(ok["Speed_ST"], errors="coerce")
    ok = ok.dropna(subset=["lt", "st"])
    # flying laps only: out-/in-/cool-down laps carry much lower trap
    # speeds and would drag every driver's median down, faking a "tow"
    # on the best lap
    for c in ("PitOut", "PitIn"):
        if c in ok.columns:
            ok = ok[~ok[c].fillna(False).astype(bool)]
    ok = ok[ok["lt"] <= ok.groupby("Driver_Short")["lt"].transform("min") * 1.10]
    rows = []
    for drv, g in ok.groupby("Driver_Short"):
        if len(g) < 3:
            continue
        best = g.loc[g["lt"].idxmin()]
        others = g.drop(best.name)["st"]
        rows.append({"driver": drv, "team": g["Team"].iloc[0],
                     "delta": round(float(best["st"] - others.median()), 1),
                     "best_st": float(best["st"]),
                     "med_st": float(others.median())})
    t = pd.DataFrame(rows).sort_values("delta")
    fig = go.Figure()
    if t.empty:
        theme(fig, 420, "")
        return fig
    fig.add_trace(go.Bar(
        y=t["driver"], x=t["delta"], orientation="h",
        marker_color=[TEAM_COLORS.get(x, "#808080") for x in t["team"]],
        customdata=np.stack([t["best_st"], t["med_st"]], axis=-1),
        hovertemplate=("<b>%{y}</b><br>Speed trap on best lap: "
                       "%{customdata[0]:.0f} km/h<br>Median other laps: "
                       "%{customdata[1]:.0f} km/h<br>Δ %{x:+.1f} km/h"
                       "<extra></extra>"),
        text=[f"{v:+.1f}" for v in t["delta"]], textposition="outside",
        textfont=dict(size=10)))
    fig.add_vline(x=0, line=dict(color="white", width=1, dash="dash"))
    theme(fig, max(340, 24 * len(t) + 110))
    span = float(t["delta"].abs().max()) or 1.0
    fig.update_xaxes(title_text="Best-lap speed trap vs own median (km/h)",
                     range=[-span * 1.35, span * 1.35])
    fig.update_layout(showlegend=False, bargap=0.3)
    return fig


# ── 5. Starting grid (quali classification + curated penalties) ──

_PU_CSV = Path("data/pu_penalties.csv")
_PEN_CSV = Path("data/team_penalties.csv")
_BOG_OVER = 15   # FIA: more than 15 cumulative grid places → back of the grid


def _grid_penalties(season: int, meeting: str) -> dict[str, dict]:
    """Curated grid drops for this meeting, keyed by driver short code:
    {driver: {"places": int, "bog": bool, "reasons": [str]}}.
    Sources: data/pu_penalties.csv (PU-pool penalties, matched on the event
    named in its penalty_event column) and data/team_penalties.csv (sporting
    'Grid penalty' rows for the event, cancelled ones excluded)."""
    out: dict[str, dict] = {}

    def add(drv, places, reason):
        e = out.setdefault(str(drv), {"places": 0, "reasons": []})
        e["places"] += int(places)
        e["reasons"].append(reason)

    m = str(meeting).strip().lower()
    if _PU_CSV.exists():
        pu = pd.read_csv(_PU_CSV)
        pu["penalties_places"] = pd.to_numeric(pu["penalties_places"],
                                               errors="coerce").fillna(0)
        pu = pu[(pu["season"] == int(season)) & (pu["penalties_places"] > 0)]
        for _, r in pu.iterrows():
            # penalty_event names the race the drops were served at; as_of only
            # says how fresh the file is, and the two diverge whenever the pool
            # is refreshed from a later event's cumulative table. Fall back to
            # as_of for files written before the columns were split.
            ev = str(r.get("penalty_event") or r.get("as_of", ""))
            ev = re.sub(r"^\s*R\d+\s*", "", ev).strip().lower()
            if ev and (ev in m or m in ev):
                add(r["driver"], r["penalties_places"],
                    f"PU pool: {int(r['penalties_places'])} places over allocation")
    if _PEN_CSV.exists():
        tp = pd.read_csv(_PEN_CSV)
        tp = tp[(tp["season"] == int(season))
                & (tp["event"].astype(str).str.strip().str.lower() == m)
                & tp["type"].astype(str).str.startswith("Grid penalty")
                & ~tp["type"].astype(str).str.contains("cancel", case=False)]
        for _, r in tp.iterrows():
            n = re.search(r"(\d+)", str(r["penalty"]))
            if n:
                add(r["driver"], int(n.group(1)), str(r["reason"]))
    for e in out.values():
        e["bog"] = e["places"] > _BOG_OVER
    return out


def _quali_classification(ql: pd.DataFrame) -> pd.DataFrame:
    """One row per driver: (driver, team, quali_pos). Drivers missing an
    official classification are appended at the back by best lap time."""
    per = (ql.dropna(subset=["Driver_Short"])
             .drop_duplicates("Driver_Short")[["Driver_Short", "Team",
                                               "Classified_Position"]]
             .rename(columns={"Driver_Short": "driver", "Team": "team",
                              "Classified_Position": "quali_pos"}))
    per["quali_pos"] = pd.to_numeric(per["quali_pos"], errors="coerce")
    if per["quali_pos"].isna().any():
        best = (pd.to_numeric(ql["LapTime_s"], errors="coerce")
                  .groupby(ql["Driver_Short"]).min())
        start = int(per["quali_pos"].max()) if per["quali_pos"].notna().any() else 0
        missing = per[per["quali_pos"].isna()]["driver"]
        for i, d in enumerate(best.reindex(missing).sort_values().index, 1):
            per.loc[per["driver"] == d, "quali_pos"] = start + i
    return per.sort_values("quali_pos").reset_index(drop=True)


def _official_grid() -> pd.DataFrame | None:
    """Official starting grid from the loaded Race session, if available.
    Pit-lane starts (Grid_Position 0) become NaN and sort last."""
    laps = state.laps
    if laps is None or laps.empty or "session" not in laps.columns:
        return None
    rc = laps[laps["session"] == "Race"]
    if rc.empty or "Grid_Position" not in rc.columns:
        return None
    g = (rc.dropna(subset=["Driver_Short"])
           .drop_duplicates("Driver_Short")[["Driver_Short", "Grid_Position"]]
           .rename(columns={"Driver_Short": "driver",
                            "Grid_Position": "grid_pos"}))
    g["grid_pos"] = pd.to_numeric(g["grid_pos"], errors="coerce")
    g.loc[g["grid_pos"] < 1, "grid_pos"] = np.nan
    return g if g["grid_pos"].notna().sum() >= 2 else None


def _project_grid(per: pd.DataFrame, pens: dict) -> pd.DataFrame:
    """Standard grid-penalty approximation: penalised drivers target
    (quali position + drop) and slot in behind the unpenalised driver
    already there; back-of-grid drivers line up last in quali order."""
    per, n = per.copy(), len(per)
    keys = []
    for _, r in per.iterrows():
        p = pens.get(r["driver"])
        if p is None:
            keys.append(float(r["quali_pos"]))
        elif p["bog"]:
            keys.append(1000.0 + float(r["quali_pos"]))
        else:
            keys.append(min(float(r["quali_pos"]) + p["places"], n) + 0.5)
    per["_k"] = keys
    per = per.sort_values(["_k", "quali_pos"]).reset_index(drop=True)
    per["grid_pos"] = np.arange(1, n + 1, dtype=float)
    return per.drop(columns="_k")


def _grid_children(ql: pd.DataFrame, sess: str, apply_pens: bool = True):
    """(note, grid html) for the Starting Grid card. `apply_pens=False`
    shows the raw qualifying order (penalty badges stay visible)."""
    meeting, season = ql["meeting"].iloc[0], int(ql["season"].iloc[0])
    per = _quali_classification(ql)
    if per.empty:
        return None
    is_gp_quali = sess == "Qualifying"
    pens = _grid_penalties(season, meeting) if is_gp_quali else {}
    official = _official_grid() if is_gp_quali else None
    if not apply_pens:
        g = per.copy()
        g["grid_pos"] = g["quali_pos"]
        mode = "qualifying order, grid penalties NOT applied"
    elif official is not None:
        g = (per.merge(official, on="driver", how="left")
                .sort_values("grid_pos", na_position="last")
                .reset_index(drop=True))
        mode = "official (from the race classification)"
    else:
        g = _project_grid(per, pens)
        mode = ("projected from quali + curated penalties" if is_gp_quali
                else "sprint grid — quali order, penalties not applied")

    def box(r):
        pos = r["grid_pos"]
        pos_txt = "PIT" if pd.isna(pos) else f"P{int(pos)}"
        colr = TEAM_COLORS.get(r["team"], "#808080")
        parts = [
            html.Span(pos_txt, style={"color": TEXT_DIM, "fontSize": "0.7rem",
                                      "fontWeight": "700", "width": "30px",
                                      "display": "inline-block"}),
            html.Span(r["driver"], style={"color": TEXT_MAIN,
                                          "fontWeight": "800"}),
        ]
        if pd.notna(r["quali_pos"]):
            d = 0 if pd.isna(pos) else int(r["quali_pos"]) - int(pos)
            parts.append(html.Span(
                f"Q{int(r['quali_pos'])}",
                style={"color": TEXT_DIM, "fontSize": "0.68rem",
                       "marginLeft": "7px"}))
            if d:
                parts.append(html.Span(
                    f"{'▲' if d > 0 else '▼'}{abs(d)}",
                    style={"color": "#39B54A" if d > 0 else "#E10600",
                           "fontSize": "0.68rem", "marginLeft": "5px",
                           "fontWeight": "700"}))
        p = pens.get(r["driver"])
        if p:
            parts += tip("BOG" if p["bog"] else f"+{p['places']}",
                         " · ".join(p["reasons"]), style={
                             "background": "#E10600", "color": "#fff",
                             "borderRadius": "4px", "padding": "1px 6px",
                             "fontSize": "0.65rem", "fontWeight": "800",
                             "marginLeft": "7px", "cursor": "help"})
        return html.Div(parts, style={
            "borderLeft": f"4px solid {colr}",
            "border": f"1px solid {GRID_CLR}", "borderLeftWidth": "4px",
            "borderLeftColor": colr, "borderRadius": "6px",
            "padding": "6px 10px", "marginBottom": "7px",
            "background": "#151528", "whiteSpace": "nowrap"})

    rows = [r for _, r in g.iterrows()]
    left = html.Div([box(r) for r in rows[0::2]], style={"flex": "1"})
    right = html.Div([box(r) for r in rows[1::2]],
                     style={"flex": "1", "marginTop": "20px"})
    note = html.P(f"Grid: {mode}.", style={
        "color": TEXT_DIM, "fontSize": "0.72rem", "marginBottom": "10px"})
    grid = html.Div([left, right], style={"display": "flex", "gap": "18px"})
    return [note, grid]


def _grid_plain(ql: pd.DataFrame):
    """Beginner reading of the grid: who took pole and who's on the front row."""
    per = _quali_classification(ql)
    if per.empty or "quali_pos" not in per.columns:
        return None
    per = per.dropna(subset=["quali_pos"])
    p1 = per[per["quali_pos"] == 1]
    if p1.empty:
        return None
    pole = p1.iloc[0]["driver"]
    line = (f"{pole} set the fastest lap in qualifying to take pole position — "
            "the number-one spot at the front of the grid.")
    p2 = per[per["quali_pos"] == 2]
    if not p2.empty:
        line += (f" {p2.iloc[0]['driver']} lines up alongside on the front row. "
                 "Starting near the front is a big advantage: clean air ahead "
                 "and no traffic to fight past.")
    return line


def _grid_card(ql: pd.DataFrame, sess: str):
    body = _grid_children(ql, sess, apply_pens=True)
    if body is None:
        return None
    toggle = html.Div(
        dbc.Switch(id="quali-grid-pen-toggle", value=True,
                   label="Apply grid penalties",
                   style={"display": "inline-block"}),
        style={"marginBottom": "4px"})
    return card(
        ["Starting ", *gloss("grid", "Grid")],
        [toggle, html.Div(body, id="quali-grid-body")],
        info=("Data: the official qualifying classification, with curated "
              "grid penalties applied on top — PU-pool drops from "
              "data/pu_penalties.csv (when its penalty_event names this "
              "event) and "
              "sporting 'Grid penalty' rows from data/team_penalties.csv. "
              "Penalised drivers slot in behind the car already holding "
              "their target slot; more than 15 places (or an explicit "
              "back-of-grid sanction) sends them to the back in quali "
              "order. Once the Race session is loaded, the measured "
              "Grid_Position replaces the projection; the toggle switches "
              "back to the raw qualifying order (penalty badges stay "
              "visible either way). Why: at penalty-heavy weekends the "
              "quali screen and the actual grid can look very different — "
              "this shows the field as it will actually line up, with ▲▼ "
              "deltas vs the quali result."),
        plain=_grid_plain(ql),
        measure="result",
    )


@callback(Output("quali-grid-body", "children"),
          Input("quali-grid-pen-toggle", "value"),
          prevent_initial_call=True)
def _update_grid_body(apply_pens):
    ql, sess = _quali_laps()
    if ql.empty:
        return html.P("No qualifying session loaded.",
                      style={"color": TEXT_DIM})
    return _grid_children(ql, sess, apply_pens=bool(apply_pens)) or []


# ── Tab layout ───────────────────────────────────────────────

def tab_quali() -> html.Div:
    ql, sess = _quali_laps()
    if ql.empty:
        return html.Div(dbc.Alert(
            "No qualifying session loaded — add the meeting's Qualifying in "
            "the DATA & QUALITY tab.", color="secondary",
            style={"background": "#1A1A2E", "border": f"1px solid {GRID_CLR}",
                   "color": TEXT_DIM}))

    meeting = ql["meeting"].iloc[0]
    season = ql["season"].iloc[0]
    ideal = _ideal_lap_table(ql)
    grid_card = _grid_card(ql, sess)

    ok = ql[~ql["IsDeleted"].fillna(False).astype(bool)]
    pole_t = pd.to_numeric(ok["LapTime_s"], errors="coerce").min()
    pole_row = ok.loc[pd.to_numeric(ok["LapTime_s"], errors="coerce").idxmin()]
    n_deleted = int(ql["IsDeleted"].fillna(False).astype(bool).sum())
    kpis = dbc.Row([
        kpi("POLE", f"{format_lap_time(pole_t)} · {pole_row['Driver_Short']}",
            "#00D2BE", tooltip="Fastest non-deleted lap of the session."),
        kpi("THEORETICAL POLE",
            format_lap_time(float(ideal["ideal"].min())) if len(ideal) else "—",
            tooltip="Fastest driver's sum of best sectors — the lap nobody "
                    "quite drove."),
        kpi("DELETED LAPS", str(n_deleted), "#FF8700",
            tooltip="Laps deleted (track limits etc.) during this session."),
        kpi("SESSION", sess, "#808080",
            tooltip="Which qualifying session of the loaded meeting is "
                    "analysed here."),
    ])

    return html.Div([
        html.H3(f"{meeting} {season} — {sess}",
                style={"color": TEXT_MAIN, "fontWeight": "800",
                       "letterSpacing": "1px", "fontSize": "1.1rem",
                       "marginBottom": "12px"}),
        kpis,
        quali3d_card(int(season), meeting),
        dbc.Row([
            dbc.Col(card(
                "Q1 → Q2 → Q3 Progression",
                dcc.Graph(figure=_progression_fig(ql), config=GFX),
                info=("Data: each driver's best lap per qualifying segment "
                      "(from the official session results), shown as % gap "
                      "to that segment's benchmark; teammates split "
                      "solid/dashed and a line that stops early = "
                      "eliminated. Why: who found pace when it mattered, "
                      "who peaked in Q1 and faded, and who only cleared "
                      "each cut by nothing."),
                measure="result",
            ), lg=7 if grid_card is not None else 12),
            *([dbc.Col(grid_card, lg=5)] if grid_card is not None else []),
        ]),
        card(
            "Time Left on the Table",
            dcc.Graph(figure=_ideal_fig(ideal), config=GFX)
            if len(ideal) else
            html.P("No sector times available.", style={"color": TEXT_DIM}),
            info=("Data: per driver, the best single lap actually driven vs "
                  "the 'theoretical best' — the sum of their three best "
                  "sector times from any non-deleted lap of the session. "
                  "Why: a big gap means the driver never hooked the lap up "
                  "(or the track kept evolving under them) — classic "
                  "post-quali talking point, now quantified."),
        ),
        card(
            "Track Evolution — Timing the Lap",
            dcc.Graph(figure=_evolution_fig(ql), config=GFX),
            info=("Data: every flying lap (within 110% of the session best) "
                  "against session time; the green staircase is the session "
                  "best-so-far, coloured markers are each driver's personal "
                  "best. Why: on an evolving track, a lap set early is worth "
                  "more than the same time set late — drivers whose marker "
                  "sits left of the pack banked their lap on a slower track "
                  "(under-rewarded), and late markers rode the grip."),
        ),
        card(
            "Tow Detector (speed-trap proxy)",
            dcc.Graph(figure=_tow_fig(ql), config=GFX),
            info=("Data: each driver's speed-trap reading on their BEST lap "
                  "minus their own median over their other flying laps — "
                  "within 110% of their best, pit-in/out laps excluded "
                  "(needs ≥3 flying laps). Why: a clearly positive spike "
                  "suggests the "
                  "headline lap leaned on a tow or a low-fuel/low-drag "
                  "engine-mode run — context when comparing raw quali gaps. "
                  "It is a proxy, not proof: wind, DRS timing and engine "
                  "modes move the trap speed too."),
        ),
    ])
