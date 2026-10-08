"""Season-long operations cards for the SEASON FORM section — everything a
team does besides building a fast car, measured from the race archive:

  chaos_timeline_card   – SC / VSC / red flags per round (+ wet-race markers)
  pit_league_card       – each team's median & best stationary pit-stop time
  lap1_league_card      – average positions gained on lap 1, per driver
  pu_points_card        – constructor points grouped by power-unit maker
  section_profile_card  – car character by driving phase (low-speed cornering, traction, top speed)
  testing_card          – pre-season testing mileage per team (curated,
                          data/testing_mileage.csv)
  penalties_card        – the stewarding ledger: major penalties, DSQs and
                          fines per season (curated, data/team_penalties.csv)

Data: data/race_stats.csv + data/pit_league.csv + data/lap1_league.csv
(scripts/compute_race_stats.py), the standings archive, facilities.csv (PU
maker) and circuit_characteristics.csv (track typing).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, dash_table, callback, Input, Output
import dash_bootstrap_components as dbc

from f1lib.components import card, theme, GFX, abbr
from f1lib.config import (
    TEAM_COLORS, team_color, CARD_BG, ACCENT,
    TEXT_MAIN, TEXT_DIM, GRID_CLR,
)
from tabs.pace_data import (
    team_pace_df, event_short, filter_teams, filter_drivers,
)
from tabs.race_stats_data import race_stats_df, lap1_df, pits_df


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
    labels = [event_short(m, season) for m in s["meeting"]]

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
              "strategy and points — a swing on the Form Guide above "
              "often lines up with a chaotic round here, and teams whose "
              "results lean on chaos read differently from teams with pace."),
    )


# ─────────────────────────────────────────────────────────────
# Pit-stop league — team stationary times
# ─────────────────────────────────────────────────────────────

def pit_league_card(season: int, teams=None) -> html.Div | None:
    df = pits_df()
    if df.empty:
        return None
    s = filter_teams(df[(df["season"] == season) & (df["team"] != "")],
                     teams).copy()
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
        marker=dict(color=[team_color(t, season) for t in g["team"]],
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

def lap1_league_card(season: int, min_races: int = 3,
                     drivers=None) -> html.Div | None:
    """`drivers` is the season driver scope (pace_data.season_scope): a
    per-driver card keeps every start of a driver in scope, including the ones
    in another team's car."""
    df = lap1_df()
    if df.empty:
        return None
    s = filter_drivers(df[df["season"] == season], drivers)
    if s.empty:
        return None
    # ONE bar per driver. Grouping by (driver, team) gave a mid-season seat
    # change two bars on the same y label — Lawson's Racing Bulls and Red Bull
    # starts drawn on top of each other as "LAW".
    g = (s.groupby("driver")["gain"]
         .agg(mean="mean", n="count").reset_index())
    seats = s.groupby(["driver", "team"]).size().rename("k").reset_index()
    main = (seats.sort_values("k", ascending=False)
            .drop_duplicates("driver").set_index("driver")["team"])
    label = {
        d: ", ".join(f"{t} ({k})" if len(x) > 1 else t
                     for t, k in zip(x["team"], x["k"]))
        for d, x in seats.sort_values("k", ascending=False).groupby("driver")}
    g["team"] = g["driver"].map(main)          # colour = his main seat
    g["seats"] = g["driver"].map(label)
    g = g[g["n"] >= min_races]
    if g.empty:
        return None
    g = g.sort_values("mean")

    fig = go.Figure(go.Bar(
        y=g["driver"], x=g["mean"], orientation="h",
        marker=dict(color=[team_color(t, season) for t in g["team"]],
                    line=dict(color="#000", width=0.5)),
        text=[f"{m:+.1f}" for m in g["mean"]], textposition="outside",
        textfont=dict(size=9),
        customdata=np.stack([g["seats"], g["n"]], axis=-1),
        hovertemplate=("<b>%{y}</b> (%{customdata[0]})<br>"
                       "Avg lap-1 gain: %{x:>+.2f} places over "
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
#
# THIS IS THE CARD'S ONLY USE OF HUE. Panels B and C used to re-spend the fill
# on an ordinal reading (pool depth / above-or-below the field) with hand-picked
# hexes, and measured against the palette rules in f1lib/config.py those hexes
# were livery colours: #e66767 is CIEDE2000 9.3 from Audi's #F2836B and 13.2
# from Ferrari, #3987e5 is 13.5 from Ford — all inside the ΔE 15 that reads as
# "the same colour". So Mercedes' attrition bar was painted Audi peach two
# inches from a panel teaching the reader that peach means Audi. The reserved
# STATUS_* ramp does not rescue it either (STATUS_BAD is ΔE 11.4 from Audi,
# 10.5 from Ferrari) — green/amber/red is structurally occupied by liveries.
#
# Neither ordinal reading needed re-encoding elsewhere, which is the part worth
# remembering. Panel C's was pure redundancy (a diverging axis already shows
# sign by which side of zero a bar sits on) and panel B's has its own dedicated
# card directly above this one. Both panels are simply one variable now.
_PU_COLORS = {
    "Mercedes": "#00D2BE",
    "Ferrari":  "#E8002D",
    "Ford":     "#2D63C8",   # Red Bull Powertrains–Ford
    "Honda":    "#8A94A6",
    "Audi":     "#F2836B",   # matches the Audi team livery colour
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
    across the three engine-championship charts.

    Each panel carries ONE variable: bar length is the measurement, `colors` is
    the manufacturer identity (see _PU_COLORS), and that is the whole grammar.
    A panel that looks like it needs a second visual channel usually means the
    second reading wants a card of its own — see the attrition panel.
    """
    fig = go.Figure(go.Bar(
        y=makers, x=values, orientation="h",
        marker=dict(color=colors, line=dict(color="#000", width=0.5)),
        text=text, textposition="outside", textfont=dict(size=10),
        cliponaxis=False,                  # value labels must not be cut off
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


_GRID_PEN_PATH = Path("data/grid_penalties.csv")


def _pu_penalty_ledger(season: int) -> pd.DataFrame:
    """Every PU-element grid drop and pit-lane start of the season, one row per
    car per event (scripts/fetch_grid_penalties.py, from the FIA's final
    starting grids). Cumulative by construction — unlike pu_penalties.csv,
    which keeps only each driver's LATEST penalty and, summed, forgot 70 of
    2026's 310 places by round 16."""
    if not _GRID_PEN_PATH.exists():
        return pd.DataFrame()
    try:
        g = pd.read_csv(_GRID_PEN_PATH)
    except Exception:
        return pd.DataFrame()
    g = g[(g["season"] == season)
          & g["pu"].astype(str).str.lower().eq("true")].copy()
    g["pit_lane"] = g["pit_lane"].astype(str).str.lower().eq("true")
    return g


def _pu_failures(season: int) -> pd.DataFrame:
    """Every race the power unit ended — retirements AND did-not-starts whose
    resolved cause names the PU (f1lib.dnf_causes.is_pu_failure). One row per
    car-race: round, event, driver, team at that race.

    Read through resolve_cause, so it inherits both layers: race control's
    collisions are never counted, and a curated override (Russell, Canada
    2026 — a no-action brush with Antonelli three laps before a battery
    failure) is. A retirement nobody has researched yet is NOT counted: the
    bar is a floor, and says so."""
    from f1lib.config import HISTORICAL_DIR
    from f1lib.dnf_causes import resolve_cause, is_pu_failure

    cols = ["round", "event", "driver", "team", "dns"]
    p = Path(HISTORICAL_DIR) / "race_results_all.parquet"
    if not p.exists():
        return pd.DataFrame(columns=cols)
    try:
        r = pd.read_parquet(p)
    except Exception:
        return pd.DataFrame(columns=cols)
    st = r["Status"].astype(str)
    r = r[(r["season"] == season)
          & ~st.isin(["Finished", "Lapped"]) & ~st.str.startswith("+")]
    rows = []
    for x in r.itertuples():
        got = resolve_cause(season, str(x.event_name), x.Abbreviation, x.Laps)
        if is_pu_failure(got):
            rows.append({"round": int(x.round_number), "event": x.event_name,
                         "driver": x.Abbreviation, "team": x.TeamName,
                         "dns": str(x.Status) == "Did not start"})
    return pd.DataFrame(rows, columns=cols)


# Plain championship points for a finishing position (2026 table). The PU
# cost panel reads grid slots through it AS IF they were finishing places —
# the owner's choice, deliberately simple: a car's race is not guaranteed to
# end where it started, but neither is the counterfactual of any other model.
_RACE_POINTS = (25, 18, 15, 12, 10, 8, 6, 4, 2, 1)


def _pts(pos) -> float:
    try:
        p = int(pos)
    except (TypeError, ValueError):
        return 0.0
    return float(_RACE_POINTS[p - 1]) if 1 <= p <= len(_RACE_POINTS) else 0.0


def _pu_points_cost(season: int) -> pd.DataFrame:
    """Every way the power unit cost a car this season, one row per car-race
    and kind, in two currencies — championship POINTS on the plain points
    table, and PLACES:

      grid     a PU-element grid penalty or pit-lane start.
               points: points of the qualifying position minus points of the
                       grid slot actually started.
               places: the NOMINAL penalty the stewards handed out (owner's
                       choice: the points view already measures the real
                       effect, so this view gives the perspective of how hard
                       the PU was hit — Honda's 2026 drops read 130 here and 0
                       in points). A pit-lane start, which has no nominal
                       figure, counts from its qualifying slot to the back.
      failure  a PU retirement or did-not-start, from the grid slot it started
               (for a DNS, the slot it would have taken) — not the running
               position at the stop, since a car limping for laps has already
               shed places to the same fault.
               points: points of that slot.
               places: that slot to the back of the field.

    Additive by construction: a car penalised AND failing in one race costs
    exactly what its qualifying position was worth, never more.
    """
    from f1lib.config import HISTORICAL_DIR
    hist = Path(HISTORICAL_DIR)
    cols = ["kind", "round", "event", "driver", "team", "from_pos", "to_pos",
            "points", "places"]
    try:
        race = pd.read_parquet(hist / "race_results_all.parquet")
        quali = pd.read_parquet(hist / "quali_results_all.parquet")
    except Exception:
        return pd.DataFrame(columns=cols)
    race = race[race["season"] == season]
    quali = quali[quali["season"] == season]
    grid_of = {(int(r.round_number), r.Abbreviation): r.GridPosition
               for r in race.itertuples()}
    q_of = {(int(r.round_number), r.Abbreviation): r.Position
            for r in quali.itertuples()}
    field = race.groupby("round_number").size().to_dict()

    def _num(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return None if v != v else v

    rows = []

    led = _pu_penalty_ledger(season)
    for (rnd, drv), g in led.groupby(["round", "driver"]):
        k = (int(rnd), drv)
        q, grid = q_of.get(k), grid_of.get(k)
        pit = bool(g["pit_lane"].any())
        # GridPosition 0 = started from the pit lane: no points from there
        start = 0 if pit or (grid is not None and grid == 0) else grid
        n = field.get(int(rnd), 22)
        qn = _num(q)
        back = n if not start else _num(start)
        nominal = float(g["places"].sum())
        if not nominal and pit:
            nominal = max(back - qn, 0.0) if qn is not None else 0.0
        rows.append({"kind": "grid", "round": int(rnd),
                     "event": g["event"].iloc[0], "driver": drv,
                     "team": g["team"].iloc[0],
                     "from_pos": q, "to_pos": "pit lane" if not start else start,
                     "points": max(_pts(q) - _pts(start), 0.0),
                     "places": nominal})

    for f in _pu_failures(season).itertuples():
        k = (int(f.round), f.driver)
        grid = grid_of.get(k)
        start = q_of.get(k) if f.dns or not grid else grid
        sn = _num(start)
        rows.append({"kind": "failure", "round": int(f.round),
                     "event": f.event, "driver": f.driver, "team": f.team,
                     "from_pos": start, "to_pos": "DNS" if f.dns else "DNF",
                     "points": _pts(start),
                     "places": (max(field.get(int(f.round), 22) - sn, 0.0)
                                if sn is not None else 0.0)})
    return pd.DataFrame(rows, columns=cols)


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

    # ── Panel B · what the power unit COST, in championship points ──
    #
    # One panel, two causes stacked, because both are the same currency now:
    #   grid     PU-element grid penalties / pit-lane starts — points of the
    #            qualifying slot minus points of the slot actually started
    #   failure  PU retirements and DNS — points of the starting slot
    # priced on the plain points table (see _pu_points_cost for why plain).
    # Per car supplied, like the points panel, so an eight-car and a two-car
    # maker compare. Hue stays the maker's (the card's only use of hue); the
    # grid-penalty segment is hatched to tell the two causes apart.
    #
    # Replaces two panels (grid places served; races lost). Grid places
    # weighed a backmarker's 30-place drop from P21 the same as a front-
    # runner's 10 from P3, which cost the second car 15 points and the first
    # none; a race count treated a DNF from pole like one from P20.
    cars = pts.set_index("maker")["cars"]
    cost = _pu_points_cost(season)
    cost = cost.assign(maker=cost["team"].map(team2maker))
    fig_rel, rel_note = None, ""
    fig_fail, fail_note = None, ""

    def _cost_fig(metric: str, unit: str, title: str, xtitle: str):
        def _who(kind: str) -> pd.Series:
            d = cost[cost["kind"] == kind].sort_values(metric, ascending=False)
            out = {}
            for m, g in d.groupby("maker"):
                bits = []
                for r in g.itertuples():
                    fp = "?" if pd.isna(r.from_pos) else f"P{int(r.from_pos)}"
                    tp = (r.to_pos if isinstance(r.to_pos, str)
                          else f"P{int(r.to_pos)}")
                    bits.append(f"{r.driver} {event_short(r.event, season)} "
                                f"{fp}→{tp}: {getattr(r, metric):.0f} {unit}")
                out[m] = "<br>".join(bits)
            return pd.Series(out, dtype=object)

        tot = (cost.groupby(["maker", "kind"])[metric].sum()
               .unstack(fill_value=0).reindex(order).fillna(0))
        for k in ("grid", "failure"):
            if k not in tot.columns:
                tot[k] = 0.0
        n = cars.reindex(order).clip(lower=1)
        per = tot.div(n, axis=0)
        fig = go.Figure()
        for kind, label, hatch in (("failure", "PU failures (DNF/DNS)", ""),
                                   ("grid", "PU grid penalties", "/")):
            who = _who(kind).reindex(order).fillna("none")
            fig.add_trace(go.Bar(
                y=order, x=per[kind], orientation="h", name=label,
                marker=dict(color=[_PU_COLORS.get(m, ACCENT) for m in order],
                            line=dict(color="#000", width=0.5),
                            pattern=dict(shape=hatch, fgcolor="rgba(0,0,0,0.55)",
                                         size=6, solidity=0.4)),
                customdata=np.stack([tot[kind], n, who], axis=-1),
                hovertemplate=(f"<b>%{{y}}</b> · {label}<br>"
                               f"%{{x:.1f}} {unit} per car (%{{customdata[0]:.0f}} "
                               "over %{customdata[1]:.0f} cars)<br>"
                               "%{customdata[2]}<extra></extra>"),
                showlegend=False,
            ))
            # Legend key in a NEUTRAL grey: the real traces are coloured per
            # maker, so their own swatch would show the first maker's colour
            # and read as "this legend is about Mercedes".
            fig.add_trace(go.Bar(
                y=[None], x=[None], orientation="h", name=label,
                marker=dict(color=TEXT_DIM, line=dict(color="#000", width=0.5),
                            pattern=dict(shape=hatch,
                                         fgcolor="rgba(0,0,0,0.55)",
                                         size=6, solidity=0.4)),
                hoverinfo="skip"))
        total = per.sum(axis=1)
        fig.add_trace(go.Scatter(
            y=order, x=total, mode="text", showlegend=False, hoverinfo="skip",
            text=[f"  {v:.1f}" if v > 0 else "  0" for v in total],
            textposition="middle right", textfont=dict(size=10),
            cliponaxis=False))
        theme(fig, max(300, 46 * len(order) + 170), title)
        fig.update_xaxes(title_text=xtitle,
                         range=[0, max(float(total.max()), 1.0) * 1.3])
        fig.update_yaxes(title_text=None, tickfont=dict(size=11),
                         autorange="reversed")
        # Legend BELOW the plot: above it, it sat on top of the title.
        fig.update_layout(barmode="stack", bargap=0.32,
                          margin=dict(l=78, r=50, t=50, b=96),
                          legend=dict(orientation="h", yanchor="top",
                                      y=-0.22, xanchor="left", x=0,
                                      font=dict(size=10)))
        return fig

    if not cost.empty or _GRID_PEN_PATH.exists():
        # Points and places are complementary, and the gap between them is
        # the story: a backmarker's PU trouble costs many PLACES and no
        # POINTS (Aston Martin-Honda, 2026), a front-runner's few places and a
        # lot of points.
        fig_rel = _cost_fig("points", "pts", "PU cost — points per car",
                            "Points lost per car (plain points table)")
        fig_fail = _cost_fig("places", "places",
                             "PU cost — places per car",
                             "Places per car (nominal penalty · failure: "
                             "slot → back)")
        rel_note = (
            " What the PU cost: championship points lost to the power unit, "
            "per car supplied, priced on the plain points table (P1 25 … P10 "
            "1). Grid penalties (hatched): points of the qualifying position "
            "minus points of the grid slot actually started, from the FIA "
            "final starting grids (data/grid_penalties.csv) — a pit-lane "
            "start for new elements counts as starting from nowhere. PU "
            "failures (solid): retirements and did-not-starts whose cause "
            "names the power unit (data/dnf_causes.csv, race control first), "
            "priced at the points of the STARTING slot — not the running "
            "position at the stop, because a car that limps for laps has "
            "already shed places to the same fault. Both are deliberately "
            "simple: no car is guaranteed to finish where it starts. A "
            "failure nobody has researched yet is not counted, so the bar is "
            "a floor. The PLACES twin counts the same events in positions: "
            "the NOMINAL grid penalty the stewards handed out (a pit-lane "
            "start, which has none, counts from its qualifying slot to the "
            "back), and starting slot to the back of the field for a failure. "
            "Read the two together: a backmarker's PU trouble costs many "
            "places and no points, a front-runner's the opposite.")

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
            # Manufacturer colours, not a red/blue sign split: this is a
            # DIVERGING axis, so which side of the zero line a bar falls on
            # already says quicker-or-slower. The old split spent hue on that
            # redundancy and landed ΔE 13.5 from Ford and 9.3 from Audi.
            fig_spd = _eng_hbar(
                order, sb["idx"].tolist(),
                [_PU_COLORS.get(m, ACCENT) for m in order],
                [f"{v:+.1f}" for v in sb["idx"]],
                "Straight-line speed index",
                "km/h vs the field at the speed trap (quali)  ·  right of zero = quicker",
                ("<b>%{y}</b><br>%{x:>+.1f} km/h vs field average<br>"
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
    # A 2x2 grid, not four in a row: at a quarter of the card each panel's
    # title, legend and axis label collided with its neighbours. The two PU
    # cost views share the second row so points and places read side by side.
    figs = [f for f in (fig_pts, fig_spd, fig_rel, fig_fail) if f is not None]
    cols = [dbc.Col(dcc.Graph(figure=f, config=GFX), lg=6, md=12)
            for f in figs]

    leader = order[0]
    intro = html.P(
        ["A power unit isn't one team's story — in 2026 five manufacturers "
         "supply the grid in very different numbers (Mercedes power eight cars, "
         "Honda just two), so a raw points total flatters the big suppliers. "
         "This reads the engine race fairer ways: championship points ",
         html.Strong("per car"), " supplied, what the power unit has ",
         html.Strong("cost in points"), " — grid penalties and failures — "
         "and a computed ",
         html.Strong("straight-line speed"), " index. On points per car, ",
         html.Strong(leader), " lead the field. Colour means the same thing in "
         "every panel — which manufacturer the bar is."],
        style={"color": TEXT_DIM, "fontSize": "0.78rem", "marginBottom": "10px"})

    return card(
        "The Engine Championship",
        html.Div([intro, dbc.Row(cols, className="g-2")]),
        info=("Data: three views of the power-unit battle for the loaded "
              "season (2026+, the current PU era). (1) Points per car — each "
              "team's constructor points (standings archive) grouped by its "
              "supplier (facilities.csv) and divided by the number of cars that "
              "supplier fields, so an eight-car and a two-car maker compare "
              "fairly." + rel_note + fail_note + spd_note +
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


def testing_card(season: int, teams=None) -> html.Div | None:
    df = testing_df()
    if df.empty:
        return None
    s = filter_teams(df[df["season"] == season], teams).copy()
    if s.empty:
        return None
    s["laps"] = pd.to_numeric(s["laps"], errors="coerce")
    s = s.dropna(subset=["laps"]).sort_values("laps", ascending=True)

    fig = go.Figure(go.Bar(
        y=[abbr(t) for t in s["team"]], x=s["laps"], orientation="h",
        marker=dict(color=[team_color(t, season) for t in s["team"]],
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


def penalties_card(season: int, teams=None) -> html.Div | None:
    df = penalties_df()
    if df.empty:
        return None
    d = filter_teams(df[df["season"] == season], teams).copy()
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
         "color": team_color(tm, season), "fontWeight": "700"}
        for tm in TEAM_COLORS]
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
# Car character — low-speed cornering · traction · top speed
# ─────────────────────────────────────────────────────────────
#
# Successor of "Track-Type Affinity" (whole circuits by average speed: Suzuka
# classed with Monza, ranking failed split-half) and of the short-lived corner-
# class version (apex speed slow/medium/fast: passed in 2026, collapsed to
# -0.03…0.50 in 2025). Data: scripts/compute_section_profile.py, which cuts
# every lap into slices classed by DRIVING PHASE from the reference car's own
# telemetry. Only three phases carry a team trait that holds across tracks,
# across seasons AND in race pace (mean split-half r over 300 random track
# halves, 2026 Q / 2025 Q / 2026 R):
#     low-speed cornering  .84 / .63 / .68      traction  .70 / .64 / .67
#     top speed            .82 / .73 / .80
# High-speed cornering (≥ 200 km/h under load) is computed but NOT a column:
# its team gaps follow overall lap pace at r ≈ 0.99 — mid/high-speed aero IS
# the pace, so after removing pace there is nothing distinctive left to show.
#
# Every cell is PACE-ADJUSTED: the team's deficit in that phase minus what a
# car of its overall lap pace typically loses there (a field-wide fit).

_SECTION_PATH = Path("data/section_profile.csv")
_TRAITS = (("low_speed", "Low-speed cornering", "under load below 200 km/h"),
           ("traction", "Traction", "accelerating below 200 km/h"),
           ("top_speed", "Top speed", "full throttle ≥ 270 km/h"))
_CONTEXT = "high_speed"
_RELIABILITY_BAR = 0.6
_SKY, _AMBER, _MID = "#2F7FA3", "#A8781E", "#24243A"
_SECTION_CACHE: dict = {}


def _phase_residuals(d: pd.DataFrame):
    """(residual pp team×phase, lap deficit % per team, raw phase %)."""
    g = d.groupby(["team", "section"])[["team_s", "median_s"]].sum()
    raw = ((g["team_s"] / g["median_s"] - 1) * 100).unstack()
    lap = (d.groupby("team")[["team_s", "median_s"]].sum())
    lap = (lap["team_s"] / lap["median_s"] - 1) * 100
    res = pd.DataFrame(index=raw.index)
    for k in raw.columns:
        ok = raw[k].notna() & lap.reindex(raw.index).notna()
        if ok.sum() < 6:
            continue
        b = np.polyfit(lap[raw.index[ok]], raw[k][ok], 1)
        res[k] = raw[k] - np.polyval(b, lap.reindex(raw.index))
    return res, lap, raw


def _character_stats(d: pd.DataFrame, key) -> dict:
    """Residuals, cross-track reliability (mean r over random track halves)
    and bootstrap SE — cached on the CSV's mtime."""
    if key in _SECTION_CACHE:
        return _SECTION_CACHE[key]
    res, lap, raw = _phase_residuals(d)
    rng = np.random.default_rng(0)
    rounds = np.array(sorted(d["round"].unique()))
    rs = {c: [] for c in res.columns}
    # 120 splits / 100 bootstraps: the reliability figure is stable to ±0.01
    # by then (checked against 300), and the first render stays ~3 s
    for _ in range(120):
        perm = rng.permutation(rounds)
        h = len(rounds) // 2
        ra = _phase_residuals(d[d["round"].isin(perm[:h])])[0]
        rb = _phase_residuals(d[d["round"].isin(perm[h:])])[0]
        for c in rs:
            if c in ra and c in rb:
                j = ra[c].dropna().index.intersection(rb[c].dropna().index)
                if len(j) >= 6:
                    rs[c].append(np.corrcoef(ra.loc[j, c], rb.loc[j, c])[0, 1])
    rel = {c: float(np.nanmean(v)) if v else float("nan") for c, v in rs.items()}
    boots = [_phase_residuals(pd.concat(
        [d[d["round"] == r] for r in rng.choice(rounds, len(rounds))]))[0]
        for _ in range(100)]
    se = pd.concat(boots).groupby(level=0).std()
    share = (d.drop_duplicates(["round", "section"])
             .groupby("section")["lap_share"].mean())
    pace_r = (float(np.corrcoef(lap.reindex(raw.index), raw[_CONTEXT])[0, 1])
              if _CONTEXT in raw and raw[_CONTEXT].notna().all() else float("nan"))
    out = {"res": res, "raw": raw, "lap": lap, "rel": rel, "se": se,
           "share": share, "rounds": len(rounds), "pace_r": pace_r}
    _SECTION_CACHE[key] = out
    return out


def _character_fig(st: dict, order: list) -> go.Figure:
    keys = [k for k, _, _ in _TRAITS]
    r = st["res"].reindex(index=order, columns=keys)
    e = st["se"].reindex(index=order, columns=keys)
    ok_col = [st["rel"].get(k, 0) >= _RELIABILITY_BAR for k in keys]
    lim = float(np.nanmax(np.abs(r.to_numpy()))) if r.notna().any().any() else 1.0
    z = r.to_numpy()
    z = np.where(np.abs(z) >= 2 * e.to_numpy(), z, z * 0.3)   # fade noise
    zc = z.copy(); zc[:, [not o for o in ok_col]] = np.nan
    zg = np.full_like(z, np.nan); zg[:, [not o for o in ok_col]] = 0.0
    xlab = [f"{lbl}<br><span style='font-size:10px'>{desc} · "
            f"{st['share'].get(k, 0):.0%} of lap · r {st['rel'].get(k, float('nan')):+.2f}</span>"
            for k, lbl, desc in _TRAITS]
    text = [["—" if v != v else f"{v:+.2f}" for v in row] for row in r.to_numpy()]
    # the TRUE value rides in customdata: z is faded toward 0 for noise cells
    custom = np.dstack([st["raw"].reindex(index=order, columns=keys).to_numpy(),
                        e.to_numpy(), r.to_numpy()])
    hover = ("<b>%{y}</b> · %{x}<br>%{customdata[2]:>+.2f} pp vs a car of the "
             "same lap pace<br>raw: %{customdata[0]:>+.2f}% vs field median · "
             "±%{customdata[1]:.2f} SE<extra></extra>")
    ylab = [abbr(t) for t in order]
    fig = go.Figure(go.Heatmap(
        z=zc, x=xlab, y=ylab, text=text, texttemplate="%{text}",
        textfont=dict(size=12, color=TEXT_MAIN), customdata=custom,
        hovertemplate=hover, colorscale=[[0, _SKY], [0.5, _MID], [1, _AMBER]],
        zmin=-lim, zmax=lim, zmid=0, xgap=3, ygap=3,
        colorbar=dict(title=dict(text="pp", side="right"), thickness=10,
                      len=0.75, tickvals=[-lim * 0.8, 0, lim * 0.8],
                      ticktext=["stronger", "as expected", "weaker"])))
    if not all(ok_col):
        fig.add_trace(go.Heatmap(
            z=zg, x=xlab, y=ylab, text=text, texttemplate="%{text}",
            textfont=dict(size=12, color=TEXT_DIM), customdata=custom,
            hovertemplate=hover.replace(
                "<extra>", "<br><i>below the reliability bar</i><extra>"),
            colorscale=[[0, "#2E2E3E"], [1, "#2E2E3E"]], showscale=False,
            xgap=3, ygap=3))
    theme(fig, max(360, 30 * len(order) + 150))
    fig.update_yaxes(autorange="reversed", title_text=None,
                     tickfont=dict(size=11), showgrid=False)
    fig.update_xaxes(side="top", title_text=None, tickfont=dict(size=11),
                     showgrid=False)
    fig.update_layout(margin=dict(l=60, r=20, t=80, b=20))
    return fig


def _character_plain(st: dict, order: list) -> str:
    bits = []
    for k, lbl, _ in _TRAITS:
        if st["rel"].get(k, 0) < _RELIABILITY_BAR or k not in st["res"]:
            continue
        col = st["res"].loc[order, k]
        sig = col[np.abs(col) >= 2 * st["se"].reindex(order)[k]]
        if sig.empty:
            continue
        best, worst = sig.idxmin(), sig.idxmax()
        part = []
        if sig[best] < 0:
            part.append(f"{abbr(best)} strongest")
        if sig[worst] > 0 and worst != best:
            part.append(f"{abbr(worst)} weakest")
        if part:
            bits.append(f"{lbl.lower()}: " + ", ".join(part))
    return ("Each car's character once its overall pace is accounted for — "
            "where it gains or loses more than a car that quick normally would. "
            + ("; ".join(bits) + "." if bits else
               "No team stands out beyond the noise yet."))


def section_profile_card(season: int, teams=None) -> html.Div | None:
    if not _SECTION_PATH.exists():
        return None
    try:
        d = pd.read_csv(_SECTION_PATH)
    except Exception:
        return None
    if "session" not in d.columns:
        return None
    d = d[d["season"] == season]
    mt = _SECTION_PATH.stat().st_mtime
    stats = {}
    for sess in ("Qualifying", "Race"):
        ds = d[d["session"] == sess]
        if ds["round"].nunique() >= 6:
            stats[sess] = _character_stats(ds, (season, sess, mt))
    if "Qualifying" not in stats:
        return None
    q = stats["Qualifying"]["res"]
    order = [t for t in (q["top_speed"] - q["low_speed"]).sort_values().index]
    order = [t for t in order if teams is None or not filter_teams(
        pd.DataFrame({"team": [t]}), teams).empty]
    if not order:
        return None

    def block(sess):
        st = stats[sess]
        note = html.P(
            [html.B("Not a column: high-speed cornering. "),
             f"Above 200 km/h under load ({st['share'].get(_CONTEXT, 0):.0%} of "
             f"the lap) the gaps between teams follow overall lap pace at "
             f"r = {st['pace_r']:.2f} — fast-corner aero IS the pace, so once "
             "pace is removed there is no separate trait to show. "
             f"{st['rounds']} rounds."],
            style={"color": TEXT_DIM, "fontSize": "0.74rem", "marginTop": "4px",
                   "marginBottom": 0})
        return html.Div([
            html.P(_character_plain(st, order),
                   style={"color": TEXT_MAIN, "fontSize": "0.82rem",
                          "marginBottom": "6px"}),
            dcc.Graph(figure=_character_fig(st, order), config=GFX), note])

    sessions = [s for s in ("Qualifying", "Race") if s in stats]
    body = html.Div([
        dcc.RadioItems(
            id="char-session",
            options=[{"label": "Qualifying (one lap)" if s == "Qualifying"
                      else "Race pace", "value": s} for s in sessions],
            value="Qualifying", inline=True,
            inputStyle={"marginRight": "6px", "accentColor": ACCENT},
            labelStyle={"marginRight": "18px", "fontSize": "0.8rem",
                        "color": TEXT_MAIN},
            style={"marginBottom": "8px"}),
        *[html.Div(block(s), id=f"char-{s.lower()}",
                   style={} if s == "Qualifying" else {"display": "none"})
          for s in sessions],
    ])
    return card(
        "Car Character — Low-Speed Cornering · Traction · Top Speed",
        body,
        measure=("one-lap", "race"),
        info=("Data: every lap of the season cut into 1,000 slices, each classed "
              "by what the reference car is doing there — cornering under load "
              "(≥ 1.5 g) below 200 km/h, accelerating below 200 km/h, full "
              "throttle at ≥ 270 km/h, braking, high-speed cornering — from its "
              "own speed, throttle, brake and lateral-load telemetry "
              "(scripts/compute_section_profile.py). Qualifying uses each "
              "team's best clean lap; race pace the fastest quarter of each "
              "driver's clean green-flag laps. Laps are aligned to a clean "
              "reference lap and rejected on telemetry dropouts. Each cell is "
              "PACE-ADJUSTED: the team's time deficit in that phase minus what a "
              "car of its overall lap pace typically loses there, in percentage "
              "points; blue = stronger than its pace predicts, amber = weaker. "
              "Faded cells sit inside two standard errors (bootstrapped by "
              "round). Header: share of lap time and cross-track reliability — "
              "the mean correlation between profiles built on two random halves "
              "of the tracks, 120 splits; the bar is 0.6. Why these three: in a "
              "test of track classifications they were the only phases whose "
              "team profile held across tracks, across seasons (2025 and 2026) "
              "and in both qualifying and race pace. Classifying corners by "
              "apex speed collapsed in 2025; speed bands flipped between "
              "seasons; high-speed cornering simply tracks overall pace."),
    )


@callback(Output("char-qualifying", "style"),
          Output("char-race", "style"),
          Input("char-session", "value"),
          prevent_initial_call=True)
def _toggle_character(sess):
    show, hide = {}, {"display": "none"}
    return (show, hide) if sess == "Qualifying" else (hide, show)


# ─────────────────────────────────────────────────────────────
# Session-by-session weather
# ─────────────────────────────────────────────────────────────

_SESSION_WEATHER_PATH = Path("data/session_weather.csv")

# dry is deliberately the quiet colour: most rows are dry and the eye should
# land on the ones that were not.
_CONDITION_COLORS = {
    "dry":     "#7A7A7A",
    "drizzle": "#00B4D8",
    "rain":    "#4A7BE0",
}

_SESSION_ORDER = ["Practice 1", "Practice 2", "Practice 3",
                  "Sprint Qualifying", "Sprint Shootout", "Sprint",
                  "Qualifying", "Race"]


def session_weather_df() -> pd.DataFrame:
    if not _SESSION_WEATHER_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(_SESSION_WEATHER_PATH)
    except Exception:
        return pd.DataFrame()


def session_weather_card(season: int) -> html.Div | None:
    """Every session of the season, and whether it was actually wet.

    The distinction this exists to draw is drizzle vs rain. `race_stats.csv`
    calls a race wet if a single weather sample reports rain, and measured
    against tyres 7 of its 13 "wet" races (2023-2026) never ran an
    intermediate — Austria 2024 is flagged wet at a track temperature of 46 C.
    Classifying from what the teams FITTED instead of from the rain sensor
    separates a damp patch from a session that changed the racing, and doing
    it per session rather than per race is what makes practice and qualifying
    legible at all: nothing recorded those before.
    """
    d = session_weather_df()
    if d.empty:
        return None
    d = d[d["season"] == season].copy()
    if d.empty:
        return None

    d["_o"] = d["session"].apply(
        lambda s: _SESSION_ORDER.index(s) if s in _SESSION_ORDER else 99)
    d = d.sort_values(["round", "_o"])
    d["ev"] = d["event"].map(event_short)
    d["rnd"] = d["round"].apply(lambda r: f"R{int(r)}" if pd.notna(r) else "—")

    def _pct(v):
        if pd.isna(v):
            return "—"
        return "0" if float(v) == 0 else f"{100 * float(v):.0f}%"

    d["rain_pct"] = d["rain_share"].apply(_pct)
    d["inter_pct"] = d["inter_share"].apply(_pct)
    d["wet_pct"] = d["wet_share"].apply(_pct)
    d["air"] = d["air_c"].apply(lambda v: "—" if pd.isna(v) else f"{v:.0f}")
    d["track"] = [
        "—" if pd.isna(t) else f"{t:.0f}  ({lo:.0f}–{hi:.0f})"
        for t, lo, hi in zip(d["track_c"], d["track_min"], d["track_max"])]
    d["cond"] = d["condition"].str.upper()

    cols = [
        {"name": "", "id": "rnd"},
        {"name": "Event", "id": "ev"},
        {"name": "Session", "id": "session"},
        {"name": "Rain", "id": "rain_pct"},
        {"name": "Inter", "id": "inter_pct"},
        {"name": "Wet", "id": "wet_pct"},
        {"name": "Air °C", "id": "air"},
        {"name": "Track °C  (min–max)", "id": "track"},
        {"name": "Condition", "id": "cond"},
    ]
    cond_styles = [
        {"if": {"filter_query": f'{{cond}} = "{k.upper()}"',
                "column_id": "cond"},
         "color": c, "fontWeight": "800"}
        for k, c in _CONDITION_COLORS.items()]
    # a non-zero wet-tyre share is the fact the whole table turns on
    tyre_styles = [
        {"if": {"filter_query": '{inter_pct} != "0" && {inter_pct} != "—"',
                "column_id": "inter_pct"},
         "color": _CONDITION_COLORS["rain"], "fontWeight": "700"},
        {"if": {"filter_query": '{wet_pct} != "0" && {wet_pct} != "—"',
                "column_id": "wet_pct"},
         "color": ACCENT, "fontWeight": "700"},
    ]
    table = dash_table.DataTable(
        data=d.to_dict("records"), columns=cols,
        sort_action="native", filter_action="native", page_size=15,
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": CARD_BG, "color": TEXT_MAIN,
                    "border": f"1px solid {GRID_CLR}", "fontSize": "12px",
                    "padding": "5px 9px", "textAlign": "left",
                    "whiteSpace": "nowrap"},
        style_header={"backgroundColor": "#09091A", "fontWeight": "bold",
                      "color": ACCENT, "border": f"1px solid {GRID_CLR}"},
        style_cell_conditional=[
            {"if": {"column_id": c}, "textAlign": "right", "maxWidth": "62px"}
            for c in ("rain_pct", "inter_pct", "wet_pct", "air")
        ] + [
            {"if": {"column_id": "rnd"}, "color": TEXT_DIM, "maxWidth": "44px"},
            {"if": {"column_id": "track"}, "textAlign": "right"},
            {"if": {"column_id": "cond"}, "textAlign": "center"},
        ],
        style_data_conditional=([{"if": {"row_index": "odd"},
                                  "backgroundColor": "#0d0d1a"}]
                               + cond_styles + tyre_styles),
    )
    n = len(d)
    tally = d["condition"].value_counts()
    intro = html.P(
        [f"All {n} cached sessions of {season}. ",
         html.Span("Rain", style={"color": TEXT_MAIN, "fontWeight": "700"}),
         " is the share of weather samples reporting precipitation; ",
         html.Span("Inter", style={"color": _CONDITION_COLORS["rain"],
                                   "fontWeight": "700"}),
         " and ",
         html.Span("Wet", style={"color": ACCENT, "fontWeight": "700"}),
         " are the share of laps on those tyres. The verdict comes from the "
         "TYRES, not the rain sensor — ",
         html.Span("DRIZZLE", style={"color": _CONDITION_COLORS["drizzle"],
                                     "fontWeight": "800"}),
         " means rain fell and the field stayed on slicks anyway; ",
         html.Span("RAIN", style={"color": _CONDITION_COLORS["rain"],
                                  "fontWeight": "800"}),
         " means somebody actually fitted intermediates.  "
         + " · ".join(f"{k} {v}" for k, v in tally.items()) + "."],
        style={"color": TEXT_DIM, "fontSize": "0.75rem",
               "marginBottom": "10px", "lineHeight": "1.6"})
    return card(
        "Session Weather — Dry, Drizzle or Actually Wet",
        html.Div([intro, table]),
        measure="measured",
        info=("Data: scripts/compute_session_weather.py → "
              "data/session_weather.csv, one row per cached session (practice "
              "and qualifying included, which nothing recorded before). Why "
              "the tyres decide the verdict: race_stats.csv marks a race wet "
              "on Rainfall.any(), so a single damp sample flags the whole "
              "session — 7 of the 13 races that flag trips on since 2023 "
              "never ran an intermediate, Austria 2024 among them at a 46 °C "
              "track. INTERMEDIATE is the tyre that matters: across the "
              "archive it is run about ten times as often as the full wet. A "
              "session is RAIN when at least 1% of laps were on inters or "
              "wets, DRIZZLE when rain was recorded but nobody left slicks, "
              "and DRY otherwise."),
    )
