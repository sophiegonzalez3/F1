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

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc
import dash_bootstrap_components as dbc

import f1lib.state as state
from f1lib.components import theme, card, kpi, GFX
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
    theme(fig, 520, "Q1 → Q2 → Q3 · gap to each segment's benchmark")
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
    theme(fig, max(340, 24 * len(t) + 110),
          "Time left on the table — best lap vs sum of best sectors")
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
    theme(fig, 500, "Track evolution — when each driver's best lap was set")
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
    rows = []
    for drv, g in ok.groupby("Driver_Short"):
        if len(g) < 4:
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
    theme(fig, max(340, 24 * len(t) + 110),
          "Speed-trap anomaly on the best lap — tow / low-drag proxy")
    span = float(t["delta"].abs().max()) or 1.0
    fig.update_xaxes(title_text="Best-lap speed trap vs own median (km/h)",
                     range=[-span * 1.35, span * 1.35])
    fig.update_layout(showlegend=False, bargap=0.3)
    return fig


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
        card(
            "Q1 → Q2 → Q3 Progression",
            dcc.Graph(figure=_progression_fig(ql), config=GFX),
            info=("Data: each driver's best lap per qualifying segment (from "
                  "the official session results), shown as % gap to that "
                  "segment's benchmark; teammates split solid/dashed and a "
                  "line that stops early = eliminated. Why: who found pace "
                  "when it mattered, who peaked in Q1 and faded, and who "
                  "only cleared each cut by nothing."),
        ),
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
                  "minus their own median over all other flying laps (needs "
                  "≥4 laps). Why: a clearly positive spike suggests the "
                  "headline lap leaned on a tow or a low-fuel/low-drag "
                  "engine-mode run — context when comparing raw quali gaps. "
                  "It is a proxy, not proof: wind, DRS timing and engine "
                  "modes move the trap speed too."),
        ),
    ])
