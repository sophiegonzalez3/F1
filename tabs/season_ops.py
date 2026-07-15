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
    theme(fig, 380, f"Interruptions per round – {season}")
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
    theme(fig, max(340, 26 * len(g) + 120),
          f"Pit-stop league – {season} (stationary time)")
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
    theme(fig, max(380, 18 * len(g) + 120),
          f"Average positions gained on lap 1 – {season}")
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
# Points by power-unit maker
# ─────────────────────────────────────────────────────────────

def pu_points_card(season: int) -> html.Div | None:
    if season < 2026:          # facilities.csv maps the current PU era only
        return None
    try:
        from f1lib.standings import HIST_STANDINGS
        from tabs.infrastructure import facilities_df
    except Exception:
        return None
    st = HIST_STANDINGS
    fac = facilities_df()
    if st.empty or fac.empty or "pu_maker" not in fac.columns:
        return None
    s = st[st["season"] == season]
    if s.empty:
        return None
    last = (s.sort_values("round_number").groupby("TeamName")
            .agg(points=("cumulative_points", "last")).reset_index())
    pu_map = {str(r.team): str(r.pu_maker) for r in fac.itertuples()}
    last["pu"] = last["TeamName"].map(pu_map)
    last = last.dropna(subset=["pu"])
    if last.empty:
        return None
    g = (last.groupby("pu")
         .agg(points=("points", "sum"),
              teams=("TeamName", lambda t: ", ".join(abbr(x) for x in t)))
         .sort_values("points", ascending=True).reset_index())

    fig = go.Figure(go.Bar(
        y=g["pu"], x=g["points"], orientation="h",
        marker=dict(color=ACCENT, line=dict(color="#000", width=0.5)),
        text=[f"{p:.0f}" for p in g["points"]], textposition="outside",
        textfont=dict(size=10),
        customdata=g["teams"],
        hovertemplate=("<b>%{y}</b><br>%{x:.0f} pts<br>Teams: %{customdata}"
                       "<extra></extra>"),
    ))
    theme(fig, max(300, 40 * len(g) + 120),
          f"Constructor points by PU manufacturer – {season}")
    fig.update_xaxes(title_text="Combined constructor points",
                     range=[0, float(g["points"].max()) * 1.25])
    fig.update_yaxes(title_text=None, tickfont=dict(size=11))
    fig.update_layout(margin=dict(l=150, r=40, t=50, b=44), showlegend=False,
                      bargap=0.35)

    return card(
        "The Engine Championship",
        dcc.Graph(figure=fig, config=GFX),
        info=("Data: each customer team's constructor points summed by its "
              "power-unit supplier (facilities.csv), for the loaded season "
              "(2026+ only — the supplier map describes the current PU "
              "era). Why: 2026's all-new power units made the engine the "
              "biggest single differentiator — this shows which supplier's "
              "camp is winning the era, beyond any one team's chassis."),
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
    theme(fig, max(340, 26 * len(s) + 120),
          f"Pre-season testing mileage – {season}")
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
    theme(fig, max(340, 24 * len(d) + 130),
          f"Track-type affinity – {season} (qualifying gap)")
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
