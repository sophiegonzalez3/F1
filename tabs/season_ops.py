"""Season-long operations cards for the SEASON FORM section — everything a
team does besides building a fast car, measured from the race archive:

  chaos_timeline_card   – SC / VSC / red flags per round (+ wet-race markers)
  pit_league_card       – each team's median & best stationary pit-stop time
  lap1_league_card      – average positions gained on lap 1, per driver
  pu_points_card        – constructor points grouped by power-unit maker
  affinity_card         – power-track vs technical-track pace character
  testing_card          – pre-season testing mileage per team (curated,
                          data/testing_mileage.csv)
  penalties_card        – the stewarding ledger: major penalties, DSQs and
                          fines per season (curated, data/team_penalties.csv)

Data: data/race_stats.csv + data/pit_league.csv + data/lap1_league.csv
(scripts/compute_race_stats.py), the standings archive, facilities.csv (PU
maker) and circuit_characteristics.csv (track typing).
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc

from f1lib.components import card, theme, GFX, abbr
from f1lib.config import (
    HIST_CIRCUIT_KEY_MAP, TEAM_COLORS, CARD_BG, ACCENT,
    TEXT_MAIN, TEXT_DIM, GRID_CLR,
)
from tabs.pace_data import team_pace_df, event_short
from tabs.race_stats_data import race_stats_df, lap1_df, pits_df


def _slugify(name) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


_EVENT_TO_CIRCUIT = {
    _slugify(hist): fr
    for fr, hists in HIST_CIRCUIT_KEY_MAP.items() for hist in hists
}


# ─────────────────────────────────────────────────────────────
# Chaos timeline — SC / VSC / red flags per round
# ─────────────────────────────────────────────────────────────

def chaos_timeline_card(season: int) -> html.Div | None:
    df = race_stats_df()
    if df.empty:
        return None
    s = df[(df["season"] == season) & df["round"].notna()].sort_values("round")
    if s.empty:
        return None
    labels = [event_short(m) for m in s["meeting"]]

    fig = go.Figure()
    for col, name, clr in [("sc_count", "Safety Car", "#FFD700"),
                           ("vsc_count", "Virtual SC", "#00B4D8"),
                           ("red_flags", "Red Flag", "#E10600")]:
        fig.add_trace(go.Bar(
            x=labels, y=s[col], name=name, marker_color=clr,
            hovertemplate=f"<b>%{{x}}</b><br>{name}: %{{y}}<extra></extra>",
        ))
    # wet-race markers along the top (string compare: the CSV column turns
    # object-typed as soon as one race lacks weather data)
    wet = s["rain"].astype(str).eq("True")
    if wet.any():
        ymax = (s["sc_count"] + s["vsc_count"] + s["red_flags"]).max()
        fig.add_trace(go.Scatter(
            x=[l for l, w in zip(labels, wet) if w],
            y=[ymax + 0.6] * int(wet.sum()),
            mode="text", text=["🌧"] * int(wet.sum()),
            textfont=dict(size=13), name="Wet race",
            hovertemplate="<b>%{x}</b><br>Rain fell during the race"
                          "<extra></extra>",
        ))
    theme(fig, 380)
    fig.update_layout(barmode="stack",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0))
    fig.update_xaxes(tickangle=-40)
    fig.update_yaxes(title_text="Deployments", dtick=1)

    return card(
        "Chaos Timeline — Safety Cars, VSC & Red Flags",
        dcc.Graph(figure=fig, config=GFX),
        info=("Data: SC / VSC deployments and red flags per round, counted "
              "from each race's track-status feed (compute_race_stats.py); "
              "🌧 marks races where rain fell. Why: interruptions reshuffle "
              "strategy and points — a swing on the points-race chart above "
              "often lines up with a chaotic round here, and teams whose "
              "results lean on chaos read differently from teams with pace."),
    )


# ─────────────────────────────────────────────────────────────
# Pit-stop league — team stationary times
# ─────────────────────────────────────────────────────────────

def pit_league_card(season: int) -> html.Div | None:
    df = pits_df()
    if df.empty:
        return None
    s = df[(df["season"] == season) & (df["team"] != "")].copy()
    s["stationary_s"] = pd.to_numeric(s["stationary_s"], errors="coerce")
    s = s.dropna(subset=["stationary_s"])
    # a jammed wheel gun (20 s+) is a story, not crew pace — cap the tail so
    # the median stays honest but keep it out of "best"
    if s.empty:
        return None
    g = (s.groupby("team")["stationary_s"]
         .agg(median="median", best="min", n="count")
         .sort_values("median", ascending=False).reset_index())
    if g.empty:
        return None

    fig = go.Figure(go.Bar(
        y=[abbr(t) for t in g["team"]], x=g["median"], orientation="h",
        marker=dict(color=[TEAM_COLORS.get(t, "#808080") for t in g["team"]],
                    line=dict(color="#000", width=0.5)),
        text=[f"{m:.2f}s  (best {b:.2f})" for m, b in
              zip(g["median"], g["best"])],
        textposition="outside", textfont=dict(size=10),
        customdata=np.stack([g["team"], g["n"]], axis=-1),
        hovertemplate=("<b>%{customdata[0]}</b><br>Median stop: %{x:.2f}s"
                       "<br>Stops timed: %{customdata[1]}<extra></extra>"),
    ))
    theme(fig, max(340, 26 * len(g) + 120))
    fig.update_xaxes(title_text="Median stationary time (s)",
                     range=[0, float(g["median"].max()) * 1.35])
    fig.update_yaxes(title_text=None, tickfont=dict(size=10))
    fig.update_layout(margin=dict(l=60, r=40, t=50, b=44), showlegend=False,
                      bargap=0.3)

    return card(
        "Pit-Stop League",
        dcc.Graph(figure=fig, config=GFX),
        info=("Data: every timed pit stop this season (livetiming pit-lane "
              "feed, data/pit_league.csv) — the median wheels-stopped time "
              "per team, with each team's single best stop. Why: pit crews "
              "are a repeatable, trainable performance lever worth ~a "
              "second a race; the median (not the average) keeps one jammed "
              "wheel gun from hiding a fast crew."),
    )


# ─────────────────────────────────────────────────────────────
# Lap-1 league — positions gained at the start
# ─────────────────────────────────────────────────────────────

def lap1_league_card(season: int, min_races: int = 3) -> html.Div | None:
    df = lap1_df()
    if df.empty:
        return None
    s = df[df["season"] == season]
    if s.empty:
        return None
    g = (s.groupby(["driver", "team"])["gain"]
         .agg(mean="mean", n="count").reset_index())
    g = g[g["n"] >= min_races]
    if g.empty:
        return None
    # a driver who switched teams keeps his latest team colour
    g = g.sort_values("mean")

    fig = go.Figure(go.Bar(
        y=g["driver"], x=g["mean"], orientation="h",
        marker=dict(color=[TEAM_COLORS.get(t, "#808080") for t in g["team"]],
                    line=dict(color="#000", width=0.5)),
        text=[f"{m:+.1f}" for m in g["mean"]], textposition="outside",
        textfont=dict(size=9),
        customdata=np.stack([g["team"], g["n"]], axis=-1),
        hovertemplate=("<b>%{y}</b> (%{customdata[0]})<br>"
                       "Avg lap-1 gain: %{x:+.2f} places over "
                       "%{customdata[1]} starts<extra></extra>"),
    ))
    theme(fig, max(380, 18 * len(g) + 120))
    lim = float(g["mean"].abs().max()) * 1.35 or 1
    fig.update_xaxes(title_text="Places gained (+) / lost (−) vs grid",
                     range=[-lim, lim])
    fig.update_yaxes(title_text=None, tickfont=dict(size=9))
    fig.update_layout(margin=dict(l=48, r=30, t=50, b=44), showlegend=False,
                      bargap=0.25)

    return card(
        "Lap-1 League — Starters & Sinkers",
        dcc.Graph(figure=fig, config=GFX),
        info=("Data: each driver's average position change from the grid to "
              "the end of lap 1, every archived race of the season "
              "(pit-lane starters excluded; minimum "
              f"{min_races} starts). Why: the start is the single biggest "
              "overtaking opportunity of a race weekend — consistent "
              "gainers are banking places car pace doesn't explain, and "
              "consistent sinkers give back what qualifying earned."),
    )


# ─────────────────────────────────────────────────────────────
# The engine championship — points, reliability & straight-line
# speed grouped by power-unit manufacturer (2026+ PU era)
# ─────────────────────────────────────────────────────────────
# One visual identity per manufacturer, reused across all three panels so a
# maker keeps the same colour wherever it appears. Distinct hues, legible on
# the dark #1A1A2E card surface.
_PU_COLORS = {
    "Mercedes": "#00D2BE",
    "Ferrari":  "#E8002D",
    "Ford":     "#2D63C8",   # Red Bull Powertrains–Ford
    "Honda":    "#8A94A6",
    "Audi":     "#E8A020",
}


def _pu_short(name) -> str:
    """Collapse a facilities.csv pu_maker string to the short supplier label
    (matches data/pu_penalties.csv's pu_supplier and data/pu_topspeed.csv)."""
    n = str(name)
    for k in ("Ford", "Mercedes", "Ferrari", "Honda", "Audi"):
        if k in n:
            return k
    if "Red Bull Powertrains" in n:
        return "Ford"
    return n.strip()


_TOPSPEED_PATH = Path("data/pu_topspeed.csv")
_TOPSPEED_CACHE: dict = {"mtime": None, "df": pd.DataFrame()}


def topspeed_df() -> pd.DataFrame:
    """Per-team straight-line-speed index (scripts/compute_pu_topspeed.py),
    re-read when the CSV's mtime changes."""
    try:
        mtime = _TOPSPEED_PATH.stat().st_mtime if _TOPSPEED_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _TOPSPEED_CACHE["mtime"]:
        try:
            _TOPSPEED_CACHE["df"] = (pd.read_csv(_TOPSPEED_PATH)
                                     if mtime else pd.DataFrame())
        except Exception:
            _TOPSPEED_CACHE["df"] = pd.DataFrame()
        _TOPSPEED_CACHE["mtime"] = mtime
    return _TOPSPEED_CACHE["df"]


def _eng_hbar(makers: list[str], values: list[float], colors: list[str],
              text: list[str], title: str, xtitle: str, hovertmpl: str,
              customdata=None, diverging: bool = False,
              xpad: float = 1.25) -> go.Figure:
    """A horizontal bar panel with a fixed maker order (best at top) shared
    across the three engine-championship charts."""
    fig = go.Figure(go.Bar(
        y=makers, x=values, orientation="h",
        marker=dict(color=colors, line=dict(color="#000", width=0.5)),
        text=text, textposition="outside", textfont=dict(size=10),
        customdata=customdata,
        hovertemplate=hovertmpl,
    ))
    theme(fig, max(260, 46 * len(makers) + 120), title)
    vmax = max((abs(v) for v in values if v == v), default=1) or 1
    if diverging:
        fig.update_xaxes(title_text=xtitle, range=[-vmax * xpad, vmax * xpad],
                         zeroline=True, zerolinecolor=TEXT_DIM, zerolinewidth=1)
    else:
        fig.update_xaxes(title_text=xtitle, range=[0, vmax * xpad])
    fig.update_yaxes(title_text=None, tickfont=dict(size=11),
                     autorange="reversed")          # first list item on top
    fig.update_layout(margin=dict(l=78, r=44, t=50, b=44), showlegend=False,
                      bargap=0.32)
    return fig


def engine_championship_card(season: int) -> html.Div | None:
    """The engine championship, three ways: points normalised by how many cars
    each manufacturer supplies, power-unit reliability (element consumption +
    grid penalties), and a computed straight-line-speed index. 2026+ only —
    facilities.csv describes the current PU era. None if the data is missing."""
    if season < 2026:
        return None
    try:
        from f1lib.standings import HIST_STANDINGS
        from tabs.infrastructure import facilities_df
        from tabs.pu_pool import pu_df
    except Exception:
        return None
    st, fac = HIST_STANDINGS, facilities_df()
    if st.empty or fac.empty or "pu_maker" not in fac.columns:
        return None
    s = st[st["season"] == season]
    if s.empty:
        return None

    team2maker = {str(r.team): _pu_short(r.pu_maker) for r in fac.itertuples()}

    # ── Panel A · points per car (fleet-size normalised) ──────────
    last = (s.sort_values("round_number").groupby("TeamName")
            .agg(points=("cumulative_points", "last")).reset_index())
    last["maker"] = last["TeamName"].map(team2maker)
    last = last.dropna(subset=["maker"])
    if last.empty:
        return None
    pts = (last.groupby("maker")
           .agg(points=("points", "sum"),
                n_teams=("TeamName", "nunique"),
                teams=("TeamName", lambda t: ", ".join(abbr(x) for x in sorted(t))))
           .reset_index())
    pts["cars"] = pts["n_teams"] * 2
    pts["ppc"] = pts["points"] / pts["cars"]
    pts = pts.sort_values("ppc", ascending=False)
    order = pts["maker"].tolist()                  # master order for all panels

    def _reindex(df: pd.DataFrame, key: str) -> pd.DataFrame:
        return df.set_index(key).reindex(order)

    pa = _reindex(pts, "maker")
    colors = [_PU_COLORS.get(m, ACCENT) for m in order]
    fig_pts = _eng_hbar(
        order, pa["ppc"].tolist(), colors,
        [f"{v:.0f}" if v >= 10 else f"{v:.1f}" for v in pa["ppc"]],
        "Championship points per car",
        "Constructor points ÷ cars supplied",
        ("<b>%{y}</b><br>%{x:.0f} pts per car<br>"
         "%{customdata[0]:.0f} total pts · %{customdata[1]:.0f} cars"
         "<br>Teams: %{customdata[2]}<extra></extra>"),
        customdata=np.stack([pa["points"], pa["cars"], pa["teams"]], axis=-1),
    )

    # ── Panel B · PU reliability — element consumption + penalties ─
    pu = pu_df(season)
    fig_rel, rel_note = None, ""
    ecols = ["ice", "tc", "mguk", "es", "ce", "ex"]
    if not pu.empty and set(ecols).issubset(pu.columns):
        pu = pu.copy()
        pu["maker"] = pu["pu_supplier"].map(_pu_short)
        pu["elems"] = pu[ecols].sum(axis=1)
        rel = (pu.groupby("maker")
               .agg(elems_car=("elems", "mean"), ice_car=("ice", "mean"),
                    penalties=("penalties_places", "sum"),
                    cars=("driver", "nunique")).reset_index())
        rb = _reindex(rel, "maker")
        # Colour ramps amber→red with the ICE units burned per car (allowance
        # is 4 ICE for the whole 2026 season): more engines = rougher campaign.
        def _relclr(ice):
            if ice != ice:
                return "#3a3a4a"
            if ice >= 4.5:
                return "#e66767"
            if ice >= 3.5:
                return "#fab219"
            return "#0ca30c"
        fig_rel = _eng_hbar(
            order, rb["elems_car"].tolist(),
            [_relclr(v) for v in rb["ice_car"]],
            [f"{int(p)} pl" if p == p and p > 0 else "" for p in rb["penalties"]],
            "PU reliability — parts burned",
            "Total PU elements used per car",
            ("<b>%{y}</b><br>%{x:.1f} PU elements per car<br>"
             "avg %{customdata[0]:.1f} engines (ICE) per car · "
             "%{customdata[1]:.0f} cars<br>"
             "%{customdata[2]:.0f} grid-penalty places taken<extra></extra>"),
            customdata=np.stack([rb["ice_car"], rb["cars"], rb["penalties"]],
                                axis=-1),
        )
        rel_note = (" The 2026 results archive only records a generic "
                    "retirement status, so specific PU failures can't be split "
                    "out of it — the reliability panel instead reads the FIA "
                    "component audit (data/pu_penalties.csv): a maker whose "
                    "cars have burned through more power-unit elements, and "
                    "taken more grid-penalty places, has had the rougher "
                    "reliability campaign.")

    # ── Panel C · computed straight-line-speed index ──────────────
    ts = topspeed_df()
    fig_spd, spd_note = None, ""
    if not ts.empty and "quali_idx" in ts.columns:
        t = ts[ts["season"] == season].copy()
        if not t.empty:
            t["maker"] = t["pu_maker"].map(_pu_short).fillna(t["pu_maker"])
            spd = (t.groupby("maker")
                   .agg(idx=("quali_idx", "mean"), qraw=("quali_raw", "mean"),
                        rraw=("race_raw", "mean"),
                        teams=("team", lambda x: ", ".join(abbr(v) for v in sorted(x))))
                   .reset_index())
            sb = _reindex(spd, "maker")
            fig_spd = _eng_hbar(
                order, sb["idx"].tolist(),
                ["#3987e5" if v == v and v >= 0 else "#e66767" for v in sb["idx"]],
                [f"{v:+.1f}" for v in sb["idx"]],
                "Straight-line speed index",
                "km/h vs the field at the speed trap (quali)",
                ("<b>%{y}</b><br>%{x:+.1f} km/h vs field average<br>"
                 "avg quali trap %{customdata[0]:.0f} km/h · "
                 "race %{customdata[1]:.0f} km/h<br>Teams: %{customdata[2]}"
                 "<extra></extra>"),
                customdata=np.stack([sb["qraw"], sb["rraw"], sb["teams"]], axis=-1),
                diverging=True, xpad=1.3,
            )
            spd_note = (" The straight-line index is computed from every car's "
                        "speed-trap reading (Speed_ST) each qualifying session, "
                        "centred on the field so circuit differences cancel — a "
                        "tentative proxy for deployed power that also reflects a "
                        "car's drag level, not the engine alone.")

    # ── Assemble ──────────────────────────────────────────────────
    cols = [dbc.Col(dcc.Graph(figure=fig_pts, config=GFX), lg=4, md=6)]
    if fig_rel is not None:
        cols.append(dbc.Col(dcc.Graph(figure=fig_rel, config=GFX), lg=4, md=6))
    if fig_spd is not None:
        cols.append(dbc.Col(dcc.Graph(figure=fig_spd, config=GFX), lg=4, md=12))

    leader = order[0]
    intro = html.P(
        ["A power unit isn't one team's story — in 2026 five manufacturers "
         "supply the grid in very different numbers (Mercedes power eight cars, "
         "Honda just two), so a raw points total flatters the big suppliers. "
         "This reads the engine race three fairer ways: championship points ",
         html.Strong("per car"), " supplied, power-unit ",
         html.Strong("reliability"), ", and a computed ",
         html.Strong("straight-line speed"), " index. On points per car, ",
         html.Strong(leader), " lead the field."],
        style={"color": TEXT_DIM, "fontSize": "0.78rem", "marginBottom": "10px"})

    return card(
        "The Engine Championship",
        html.Div([intro, dbc.Row(cols, className="g-2")]),
        info=("Data: three views of the power-unit battle for the loaded "
              "season (2026+, the current PU era). (1) Points per car — each "
              "team's constructor points (standings archive) grouped by its "
              "supplier (facilities.csv) and divided by the number of cars that "
              "supplier fields, so an eight-car and a two-car maker compare "
              "fairly." + rel_note + spd_note +
              " Why: the raw 'sum the points by engine' table rewards whoever "
              "supplies the most teams; normalising by fleet size, and adding "
              "reliability and measured straight-line pace, shows which power "
              "unit is actually best."),
    )


# ─────────────────────────────────────────────────────────────
# Pre-season testing mileage
# ─────────────────────────────────────────────────────────────

_TEST_PATH = Path("data/testing_mileage.csv")
_TEST_CACHE: dict = {"mtime": None, "df": pd.DataFrame()}


def testing_df() -> pd.DataFrame:
    try:
        mtime = _TEST_PATH.stat().st_mtime if _TEST_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _TEST_CACHE["mtime"]:
        try:
            _TEST_CACHE["df"] = (pd.read_csv(_TEST_PATH).fillna("")
                                 if mtime else pd.DataFrame())
        except Exception:
            _TEST_CACHE["df"] = pd.DataFrame()
        _TEST_CACHE["mtime"] = mtime
    return _TEST_CACHE["df"]


def testing_card(season: int) -> html.Div | None:
    df = testing_df()
    if df.empty:
        return None
    s = df[df["season"] == season].copy()
    if s.empty:
        return None
    s["laps"] = pd.to_numeric(s["laps"], errors="coerce")
    s = s.dropna(subset=["laps"]).sort_values("laps", ascending=True)

    fig = go.Figure(go.Bar(
        y=[abbr(t) for t in s["team"]], x=s["laps"], orientation="h",
        marker=dict(color=[TEAM_COLORS.get(t, "#808080") for t in s["team"]],
                    line=dict(color="#000", width=0.5)),
        text=[f"{int(v):,}" for v in s["laps"]], textposition="outside",
        textfont=dict(size=10),
        customdata=np.stack([s["team"], s["notes"]], axis=-1),
        hovertemplate=("<b>%{customdata[0]}</b><br>%{x:,} laps"
                       "<br>%{customdata[1]}<extra></extra>"),
    ))
    theme(fig, max(340, 26 * len(s) + 120))
    fig.update_xaxes(title_text="Laps completed (all pre-season tests)",
                     range=[0, float(s["laps"].max()) * 1.18])
    fig.update_yaxes(title_text=None, tickfont=dict(size=10))
    fig.update_layout(margin=dict(l=60, r=40, t=50, b=44), showlegend=False,
                      bargap=0.3)

    return card(
        "Pre-Season Testing Mileage",
        dcc.Graph(figure=fig, config=GFX),
        info=("Data: curated data/testing_mileage.csv — total laps each team "
              "completed across the season's pre-season tests, with a note "
              "per team (hover) and press sources in the CSV. Why: testing "
              "mileage is the classic leading indicator of early-season "
              "readiness — a team that couldn't run in February usually "
              "spends spring firefighting reliability instead of developing "
              "(compare with the reliability card and the points race)."),
    )


# ─────────────────────────────────────────────────────────────
# Stewarding ledger — major penalties, DSQs, fines
# ─────────────────────────────────────────────────────────────

_PEN_PATH = Path("data/team_penalties.csv")
_PEN_CACHE: dict = {"mtime": None, "df": pd.DataFrame()}

_PEN_TYPE_COLORS = {
    "Disqualification": "#E10600",
    "Time penalty": "#fab219",
    "Grid penalty": "#ec835a",
    "Grid penalty (cancelled)": "#7A7A7A",
    "Fine": "#00B4D8",
}


def penalties_df() -> pd.DataFrame:
    try:
        mtime = _PEN_PATH.stat().st_mtime if _PEN_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _PEN_CACHE["mtime"]:
        try:
            _PEN_CACHE["df"] = (pd.read_csv(_PEN_PATH).fillna("")
                                if mtime else pd.DataFrame())
        except Exception:
            _PEN_CACHE["df"] = pd.DataFrame()
        _PEN_CACHE["mtime"] = mtime
    return _PEN_CACHE["df"]


def penalties_card(season: int) -> html.Div | None:
    df = penalties_df()
    if df.empty:
        return None
    d = df[df["season"] == season].copy()
    if d.empty:
        return None
    d = d.sort_values("date", ascending=False)
    d["event"] = d["event"].map(event_short)
    d["src_md"] = d["source"].apply(lambda u: f"[↗]({u})" if u else "")
    cols = [
        {"name": "Date", "id": "date"},
        {"name": "Event", "id": "event"},
        {"name": "Team", "id": "team"},
        {"name": "Driver", "id": "driver"},
        {"name": "Type", "id": "type"},
        {"name": "Penalty", "id": "penalty"},
        {"name": "What happened", "id": "reason"},
        {"name": "Src", "id": "src_md", "presentation": "markdown"},
    ]
    team_styles = [
        {"if": {"filter_query": f'{{team}} = "{tm}"', "column_id": "team"},
         "color": c, "fontWeight": "700"} for tm, c in TEAM_COLORS.items()]
    type_styles = [
        {"if": {"filter_query": f'{{type}} = "{t}"', "column_id": "type"},
         "color": c, "fontWeight": "700"}
        for t, c in _PEN_TYPE_COLORS.items()]
    table = dash_table.DataTable(
        data=d.to_dict("records"), columns=cols,
        sort_action="native", filter_action="native", page_size=12,
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": CARD_BG, "color": TEXT_MAIN,
                    "border": f"1px solid {GRID_CLR}", "fontSize": "12px",
                    "padding": "6px 9px", "textAlign": "left",
                    "whiteSpace": "normal", "height": "auto",
                    "maxWidth": "320px"},
        style_header={"backgroundColor": "#09091A", "fontWeight": "bold",
                      "color": ACCENT, "border": f"1px solid {GRID_CLR}"},
        style_cell_conditional=[
            {"if": {"column_id": "reason"}, "color": TEXT_DIM,
             "fontSize": "11px", "maxWidth": "400px"},
            {"if": {"column_id": "src_md"}, "textAlign": "center",
             "maxWidth": "44px"},
            {"if": {"column_id": "date"}, "maxWidth": "88px"}],
        style_data_conditional=([{"if": {"row_index": "odd"},
                                  "backgroundColor": "#0d0d1a"}]
                                + team_styles + type_styles),
        markdown_options={"link_target": "_blank"},
    )
    intro_extra = (
        " Note: the FIA's 2026 penalty guidelines reserve penalty points for "
        "dangerous or deliberate acts, so sporting penalties are rarer this "
        "season — and unserved grid penalties now expire after 12 months."
        if season >= 2026 else "")
    intro = html.P(
        ["The season's stewarding ledger — the disqualifications, time and "
         "grid penalties that moved real points (routine 5-second lap-1 "
         "taps are left out)." + intro_extra],
        style={"color": TEXT_DIM, "fontSize": "0.75rem", "marginBottom": "10px"})
    return card(
        "Stewards' Ledger — Penalties That Mattered",
        html.Div([intro, table]),
        info=("Data: curated data/team_penalties.csv — the major, "
              "points-affecting stewards' decisions of the season "
              "(disqualifications, time/grid penalties, fines), each with "
              "what happened and a source link. Why: penalties are the "
              "hidden line in the championship arithmetic — a DSQ or 10-"
              "second sanction can move more points than an upgrade "
              "package; the type column shows technical DSQs vs on-track "
              "sanctions. Deliberately selective: refresh after notable "
              "stewards' calls, not every round."),
    )


# ─────────────────────────────────────────────────────────────
# Circuit-type affinity — power vs technical tracks
# ─────────────────────────────────────────────────────────────

def affinity_card(season: int, min_events: int = 2) -> html.Div | None:
    pace = team_pace_df()
    if pace.empty:
        return None
    s = pace[(pace["season"] == season) & pace["quali_gap_pct"].notna()].copy()
    if s.empty:
        return None
    try:
        chars = pd.read_csv("data/circuit_characteristics.csv")
    except Exception:
        return None
    speed = {str(r.circuit_key): int(r.avg_speed_score)
             for r in chars.itertuples()}
    s["circuit"] = s["event"].map(lambda e: _EVENT_TO_CIRCUIT.get(_slugify(e)))
    s["kind"] = s["circuit"].map(
        lambda c: "power" if speed.get(c, 0) >= 3
        else ("technical" if speed.get(c) else None))
    s = s.dropna(subset=["kind"])

    rows = []
    for team, g in s.groupby("team"):
        p = g[g["kind"] == "power"]["quali_gap_pct"]
        t = g[g["kind"] == "technical"]["quali_gap_pct"]
        if len(p) < min_events or len(t) < min_events:
            continue
        rows.append({"team": team, "delta": float(t.mean() - p.mean()),
                     "np": len(p), "nt": len(t)})
    if len(rows) < 3:
        return None
    d = pd.DataFrame(rows).sort_values("delta")

    fig = go.Figure(go.Bar(
        y=[abbr(t) for t in d["team"]], x=d["delta"], orientation="h",
        marker=dict(color=[TEAM_COLORS.get(t, "#808080") for t in d["team"]],
                    line=dict(color="#000", width=0.5)),
        text=[f"{v:+.2f}%" for v in d["delta"]], textposition="outside",
        textfont=dict(size=9),
        customdata=np.stack([d["team"], d["np"], d["nt"]], axis=-1),
        hovertemplate=("<b>%{customdata[0]}</b><br>"
                       "Technical-track gap minus power-track gap: "
                       "%{x:+.2f}%<br>(%{customdata[1]} power / "
                       "%{customdata[2]} technical events)<extra></extra>"),
    ))
    theme(fig, max(340, 24 * len(d) + 130))
    lim = float(d["delta"].abs().max()) * 1.4 or 0.5
    fig.update_xaxes(
        title_text="← relatively faster on technical tracks   ·   "
                   "relatively faster on power tracks →",
        range=[-lim, lim])
    fig.add_vline(x=0, line=dict(color=TEXT_DIM, width=1, dash="dot"))
    fig.update_yaxes(title_text=None, tickfont=dict(size=10))
    fig.update_layout(margin=dict(l=60, r=40, t=50, b=60), showlegend=False,
                      bargap=0.3)

    return card(
        "Track-Type Affinity — Power vs Technical",
        dcc.Graph(figure=fig, config=GFX),
        info=("Data: each team's average qualifying gap on high-speed "
              "'power' circuits (avg-speed score ≥ 3 in "
              "circuit_characteristics.csv) minus its average gap on slower "
              "technical circuits, this season (min. "
              f"{min_events} events per bucket). Why: a car concept has a "
              "shape — drag-efficient cars gain on power tracks, "
              "high-downforce cars on technical ones — so this hints at "
              "who should be strong at the type of circuits still to come."),
    )
