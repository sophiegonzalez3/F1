"""
F1 Dashboard – historical archive & championship standings
==========================================================
Owns the historical-results archive (data/historical_results/*, built by
fetch_historical_results.py) and everything championship-standings related:
season/round resolution for the loaded meeting, points/rank lookups, the
leaderboard table body, and the drivers'/constructors' widgets shown on the
SEASON tab. Extracted from app.py so tab modules can import these without
touching the monolith.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from dash import html
import dash_bootstrap_components as dbc

import state
from components import card
from config import (
    HISTORICAL_DIR, HIST_CIRCUIT_KEY_MAP, TEAM_COLORS,
    ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
)

# Mirror the mutable data-state names (LOADED_SESSION_INFO, laps, …) into this
# module, now and after every session reload — same pattern app.py uses.
state.register(globals())

# ── Historical results (race + quali) ────────────────────────
_HIST_BASE = Path(HISTORICAL_DIR)
def _load_hist(filename):
    p = _HIST_BASE / filename
    if p.exists():
        try:
            return pd.read_parquet(p, engine="pyarrow")
        except Exception:
            try:
                return pd.read_csv(p)
            except Exception:
                pass
    return pd.DataFrame()

HIST_RACE  = _load_hist("race_results_all.parquet")
HIST_QUALI = _load_hist("quali_results_all.parquet")
print(f"Historical race results : {len(HIST_RACE):,} rows")
print(f"Historical quali results: {len(HIST_QUALI):,} rows")

# Sprint race results (sprint-format weekends only; may be absent).
HIST_SPRINT = _load_hist("sprint_results_all.parquet")

# Per-round constructor championship standings (season-aware). Prefer the file
# written by fetch_historical_results.py; if it isn't there yet, derive it from
# the race (+ sprint) results we already have so the standings widget still works.
HIST_STANDINGS = _load_hist("constructor_standings_all.parquet")
if HIST_STANDINGS.empty and not HIST_RACE.empty:
    try:
        from fetch_historical_results import build_constructor_standings
        _pts_src = HIST_RACE
        if not HIST_SPRINT.empty:
            _shared = [c for c in HIST_RACE.columns if c in HIST_SPRINT.columns]
            _pts_src = pd.concat([HIST_RACE[_shared], HIST_SPRINT[_shared]],
                                 ignore_index=True)
        HIST_STANDINGS = build_constructor_standings(_pts_src)
        print("Constructor standings   : derived from race"
              f"{'+sprint' if not HIST_SPRINT.empty else ''} results "
              "(run fetch_historical_results.py to cache them)")
    except Exception as _exc:
        print(f"Constructor standings   : unavailable ({_exc})")
print(f"Constructor standings   : {len(HIST_STANDINGS):,} rows")

# Per-round drivers' championship standings (same source, keyed by driver).
HIST_DRIVER_STANDINGS = _load_hist("driver_standings_all.parquet")
if HIST_DRIVER_STANDINGS.empty and not HIST_RACE.empty:
    try:
        from fetch_historical_results import build_driver_standings
        _dpts_src = HIST_RACE
        if not HIST_SPRINT.empty:
            _dshared = [c for c in HIST_RACE.columns if c in HIST_SPRINT.columns]
            _dpts_src = pd.concat([HIST_RACE[_dshared], HIST_SPRINT[_dshared]],
                                  ignore_index=True)
        HIST_DRIVER_STANDINGS = build_driver_standings(_dpts_src)
    except Exception as _exc:
        print(f"Driver standings        : unavailable ({_exc})")
print(f"Driver standings        : {len(HIST_DRIVER_STANDINGS):,} rows")

# ── Constructor standings helpers (season-aware, data-driven) ─
def _loaded_meeting_season_round() -> tuple[int | None, int | None, str | None]:
    """
    Infer (season, round_number, event_name) for the meeting currently loaded in
    the Data tab. Uses LOADED_SESSION_INFO for the season + event name, then looks
    the round number up in HIST_RACE. When several meetings are loaded, the most
    advanced round (latest in the season) is used. Returns Nones if unresolved.
    """
    if not LOADED_SESSION_INFO:
        return None, None, None
    best = (None, None, None)   # (season, round, event)
    for info in LOADED_SESSION_INFO:
        try:
            season = int(info.get("SEASON"))
        except (TypeError, ValueError):
            continue
        event = str(info.get("MEETING", "")).strip()
        rnd = None
        if not HIST_STANDINGS.empty:
            sub = HIST_STANDINGS[
                (HIST_STANDINGS["season"] == season)
                & (HIST_STANDINGS["event_name"].astype(str).str.strip() == event)
            ]
            if not sub.empty:
                rnd = int(sub["round_number"].iloc[0])
        if best[0] is None or season > best[0] or (
            season == best[0] and (rnd or 0) > (best[1] or 0)
        ):
            best = (season, rnd, event)
    return best

def _standings_after_round(season: int, rnd: int | None) -> dict[str, float]:
    """Constructor points (team → cumulative) standing AFTER the given round.
    rnd=None or an unknown round falls back to the latest available round."""
    if HIST_STANDINGS.empty or season is None:
        return {}
    sub = HIST_STANDINGS[HIST_STANDINGS["season"] == season]
    if sub.empty:
        return {}
    rounds = sorted(int(r) for r in sub["round_number"].unique())
    if rnd is None or rnd not in rounds:
        rnd = max(rounds)
    row = sub[sub["round_number"] == rnd]
    return {str(t): float(p) for t, p in zip(row["TeamName"], row["cumulative_points"])}


def _round_points_for(season: int, rnd: int | None) -> dict[str, float]:
    """Points each team scored IN the given round (team → round_points)."""
    if HIST_STANDINGS.empty or season is None or rnd is None:
        return {}
    row = HIST_STANDINGS[
        (HIST_STANDINGS["season"] == season) & (HIST_STANDINGS["round_number"] == rnd)
    ]
    return {str(t): float(p) for t, p in zip(row["TeamName"], row["round_points"])}


def _prev_round(season: int, rnd: int | None) -> int | None:
    """The round immediately before *rnd* that exists for the season, else None."""
    if HIST_STANDINGS.empty or season is None or rnd is None:
        return None
    sub = HIST_STANDINGS[HIST_STANDINGS["season"] == season]
    earlier = sorted(int(r) for r in sub["round_number"].unique() if int(r) < rnd)
    return earlier[-1] if earlier else None


def _team_champ_rank() -> dict[str, int]:
    """team → constructor championship position (1 = leader) for the season and
    round currently loaded in the Data tab. Empty dict if no standings exist."""
    season, rnd, _ = _loaded_meeting_season_round()
    after = _standings_after_round(season, rnd)
    if not after:
        return {}
    ordered = sorted(after.items(), key=lambda kv: -kv[1])
    rank, prev, pr = {}, None, 0
    for i, (t, p) in enumerate(ordered):
        if p != prev:
            pr = i + 1
        rank[t] = pr
        prev = p
    return rank


def _order_teams_by_champ(teams) -> list[str]:
    """Default ordering for team-categorical charts: by current championship
    standing (leader first), with any team not in the standings kept after the
    ranked ones in stable alphabetical order. Charts that are themselves a value
    ranking (gap-to-leader bars, pace order) keep their own ordering instead."""
    rank = _team_champ_rank()
    _BIG = 10 ** 6
    return sorted(set(map(str, teams)), key=lambda t: (rank.get(t, _BIG), t))


def _dense_rank_by_pts(pts: dict) -> dict:
    """Dense rank (1 = most points); ties share a rank."""
    ordered = sorted(pts.items(), key=lambda x: -x[1])
    rank, prev, pr = {}, None, 0
    for i, (k, p) in enumerate(ordered):
        if p != prev:
            pr = i + 1
        rank[k] = pr
        prev = p
    return rank


def _driver_standings_after_round(season, rnd) -> dict:
    """driver → {'pts': float, 'team': str} cumulative AFTER the given round.
    rnd=None or an unknown round falls back to the latest available round."""
    if HIST_DRIVER_STANDINGS.empty or season is None:
        return {}
    sub = HIST_DRIVER_STANDINGS[HIST_DRIVER_STANDINGS["season"] == season]
    if sub.empty:
        return {}
    rounds = sorted(int(r) for r in sub["round_number"].unique())
    if rnd is None or rnd not in rounds:
        rnd = max(rounds)
    row = sub[sub["round_number"] == rnd]
    return {str(d): {"pts": float(p), "team": str(t)}
            for d, p, t in zip(row["Abbreviation"], row["cumulative_points"], row["TeamName"])}


def _driver_round_points(season, rnd) -> dict:
    """Points each driver scored IN the given round (driver → round_points)."""
    if HIST_DRIVER_STANDINGS.empty or season is None or rnd is None:
        return {}
    row = HIST_DRIVER_STANDINGS[
        (HIST_DRIVER_STANDINGS["season"] == season)
        & (HIST_DRIVER_STANDINGS["round_number"] == rnd)
    ]
    return {str(d): float(p) for d, p in zip(row["Abbreviation"], row["round_points"])}


def _standings_leaderboard_body(entities_sorted, rank_after, rank_before,
                                after_pts, round_pts, color_of, primary_of,
                                secondary_of=None, entity_header="CONSTRUCTOR",
                                all_before_zero=False, delta_note=""):
    """Shared championship-leaderboard body (header + ranked rows + delta note),
    used by both the constructor and driver standings widgets so they render
    identically. The ``*_of`` arguments are callables: entity → value."""
    def _arrow(delta):
        if all_before_zero:
            return html.Span("—", style={"color": TEXT_DIM, "fontSize": "0.75rem"})
        if delta > 0:
            return html.Span(f"▲{delta}", style={"color": "#00C04B",
                             "fontWeight": "700", "fontSize": "0.78rem"})
        if delta < 0:
            return html.Span(f"▼{abs(delta)}", style={"color": "#FF4444",
                             "fontWeight": "700", "fontSize": "0.78rem"})
        return html.Span("=", style={"color": TEXT_DIM, "fontSize": "0.78rem"})

    _hcell = {"color": TEXT_DIM, "fontSize": "0.65rem", "fontWeight": "700",
              "letterSpacing": "1px"}
    header = html.Div([
        html.Span("POS", style={"width": "38px", "display": "inline-block", **_hcell}),
        html.Span("Δ",   style={"width": "42px", "display": "inline-block",
                                "textAlign": "center", **_hcell}),
        html.Span(entity_header, style={"flex": "1", **_hcell}),
        html.Span("THIS EVENT", style={"width": "80px", "textAlign": "right", **_hcell}),
        html.Span("TOTAL PTS",  style={"width": "80px", "textAlign": "right", **_hcell}),
    ], style={"display": "flex", "alignItems": "center",
              "padding": "4px 10px 6px 10px",
              "borderBottom": f"1px solid {GRID_CLR}", "marginBottom": "4px"})

    leader_pts = (max(after_pts.values()) if after_pts else 1) or 1
    rows = []
    for e in entities_sorted:
        clr     = color_of(e)
        rank_a  = rank_after.get(e, 99)
        delta   = rank_before.get(e, 99) - rank_a       # positive = moved UP
        pts_now = int(after_pts.get(e, 0))
        pts_evt = int(round_pts.get(e, 0))
        evt_str = f"+{pts_evt}" if pts_evt > 0 else ("—" if pts_evt == 0 else str(pts_evt))
        bar_pct = pts_now / leader_pts * 100

        name_children = [
            html.Span("● ", style={"color": clr, "fontSize": "0.75rem"}),
            html.Span(primary_of(e), style={"color": TEXT_MAIN,
                      "fontWeight": "700" if secondary_of else "600",
                      "fontSize": "0.82rem"}),
        ]
        sec = secondary_of(e) if secondary_of else None
        if sec:
            name_children.append(html.Span(f"  {sec}",
                style={"color": TEXT_DIM, "fontSize": "0.72rem"}))
        name_children.append(html.Div(
            html.Div(style={"width": f"{bar_pct:.1f}%", "height": "4px",
                            "background": clr, "borderRadius": "2px", "opacity": "0.6"}),
            style={"width": "100%", "height": "4px", "background": GRID_CLR,
                   "borderRadius": "2px", "marginTop": "4px"}))

        rows.append(html.Div([
            html.Span(f"P{rank_a}", style={"width": "38px", "display": "inline-block",
                      "color": clr, "fontWeight": "800", "fontSize": "0.88rem"}),
            html.Span(_arrow(delta), style={"width": "42px", "display": "inline-block",
                      "textAlign": "center"}),
            html.Div(name_children, style={"flex": "1", "paddingRight": "8px"}),
            html.Span(evt_str, style={"width": "80px", "textAlign": "right",
                      "color": "#00C04B" if pts_evt > 0 else TEXT_DIM,
                      "fontWeight": "700" if pts_evt > 0 else "400", "fontSize": "0.82rem"}),
            html.Span(f"{pts_now} pts", style={"width": "80px", "textAlign": "right",
                      "color": TEXT_MAIN, "fontWeight": "700", "fontSize": "0.88rem"}),
        ], style={"display": "flex", "alignItems": "center", "padding": "6px 10px",
                  "borderRadius": "6px", "marginBottom": "3px",
                  "background": f"linear-gradient(90deg, {clr}14 0%, transparent 60%)",
                  "border": f"1px solid {clr}28"}))

    return html.Div([
        header,
        html.Div(rows),
        html.P(delta_note, style={"color": TEXT_DIM, "fontSize": "0.65rem",
                                  "marginTop": "10px", "fontStyle": "italic"}),
    ])


def _driver_standings_widget(fl):
    """Drivers' Championship leaderboard for the season/round loaded in the Data
    tab — same look as the Constructor Championship widget. Falls back to points
    from the loaded race laps if the meeting isn't in the historical archive."""
    season, rnd, event = _loaded_meeting_season_round()
    after_src  = _driver_standings_after_round(season, rnd)
    prev_rnd   = _prev_round(season, rnd)
    before_src = _driver_standings_after_round(season, prev_rnd) if prev_rnd else {}
    round_src  = _driver_round_points(season, rnd)
    from_archive = rnd is not None

    if not after_src:
        race_sess = [s for s in fl["session_name"].unique()
                     if (str(s).startswith("Race") or str(s).startswith("Sprint"))
                     and "Qualifying" not in str(s) and "Shootout" not in str(s)]
        if race_sess and "Race_Points" in fl.columns:
            pr = (fl[fl["session_name"].isin(race_sess)]
                  .groupby(["session_name", "Driver_Short", "Team"])["Race_Points"]
                  .first().reset_index())
            pr["Race_Points"] = pd.to_numeric(pr["Race_Points"], errors="coerce").fillna(0)
            agg = pr.groupby(["Driver_Short", "Team"])["Race_Points"].sum().reset_index()
            round_src  = {str(d): float(p) for d, p in zip(agg["Driver_Short"], agg["Race_Points"])}
            after_src  = {str(d): {"pts": float(p), "team": str(t)}
                          for d, p, t in zip(agg["Driver_Short"], agg["Race_Points"], agg["Team"])}
            before_src = {}

    drivers = sorted(set(after_src) | set(before_src) | set(round_src))
    team_of = {}
    for d in drivers:
        if d in after_src:
            team_of[d] = after_src[d]["team"]
        elif d in before_src:
            team_of[d] = before_src[d]["team"]
        else:
            team_of[d] = ""
    after_pts  = {d: (after_src[d]["pts"] if d in after_src else 0) for d in drivers}
    before_pts = {
        d: (before_src[d]["pts"] if d in before_src
            else max(0, after_pts[d] - round_src.get(d, 0)))
        for d in drivers
    }
    round_pts = {d: round_src.get(d, 0) for d in drivers}

    rank_after  = _dense_rank_by_pts(after_pts)
    rank_before = _dense_rank_by_pts(before_pts)
    all_before_zero = all(v == 0 for v in before_pts.values())
    entities_sorted = sorted(
        drivers, key=lambda d: (rank_after.get(d, 99), -after_pts.get(d, 0)))

    season_lbl = str(season) if season else "current"
    if from_archive and event:
        subtitle = f"  ·  standings after {event} (round {rnd})"
    elif from_archive:
        subtitle = f"  ·  standings after round {rnd}"
    else:
        subtitle = "  ·  points from loaded race sessions (not yet in archive)"
    delta_note = (
        "↕ rank change caused by this event  ·  —  = season opener / no prior round"
        if all_before_zero else
        "↕ driver rank change vs the standings before this event"
    )
    info = ("Data: cumulative drivers' championship points for the loaded season, "
            "summed from every race's (and sprint's) points in the historical "
            "archive (driver_standings_all.parquet, built by "
            "fetch_historical_results.py). 'After' = standings through the loaded "
            "meeting's round; 'before' = the previous round; the arrow is the rank "
            "change from this event. Re-run the fetch for new rounds, or load "
            "another season to see its table.")

    body = (
        _standings_leaderboard_body(
            entities_sorted, rank_after, rank_before, after_pts, round_pts,
            color_of=lambda d: TEAM_COLORS.get(team_of.get(d, ""), "#808080"),
            primary_of=lambda d: d,
            secondary_of=lambda d: team_of.get(d, ""),
            entity_header="DRIVER",
            all_before_zero=all_before_zero, delta_note=delta_note,
        )
        if drivers else
        html.P("No driver standings available for the loaded season. "
               "Run fetch_historical_results.py to populate the archive.",
               style={"color": TEXT_DIM, "fontStyle": "italic", "fontSize": "0.8rem"})
    )
    return card(
        html.Span([
            "Drivers' Championship  ",
            html.Span(f"{season_lbl} season", style={"color": ACCENT, "fontWeight": "800"}),
            html.Span(subtitle, style={"color": TEXT_DIM, "fontWeight": "400",
                                       "fontSize": "0.72rem", "marginLeft": "6px"}),
        ]),
        body,
        info=info,
    )

def _constructor_standings_widget(fl):
    """Constructor Championship leaderboard for the loaded season/round —
    the constructor twin of _driver_standings_widget. Standings come from
    the historical archive; falls back to points scored in the loaded race
    laps when the meeting isn't archived yet."""
    sess_names = fl["session_name"].unique().tolist()
    race_sess  = [s for s in sess_names
                  if (s.startswith("Race") or s.startswith("Sprint"))
                  and "Qualifying" not in s and "Shootout" not in s]
    has_race   = bool(race_sess)
    # ═════════════════════════════════════════════════════════
    # CONSTRUCTOR CHAMPIONSHIP STANDINGS WIDGET
    # Data-driven & season-aware. Standings come from the historical
    # constructor table (HIST_STANDINGS — built by fetch_historical_results.py
    # from race points), looked up for the season + round of the meeting loaded
    # in the Data tab:
    #   "after"  = cumulative standings through that round,
    #   "before" = standings through the previous round,
    #   delta    = rank change caused by this event.
    # It updates automatically as new rounds are fetched or another season loads.
    # Falls back to points scored in the loaded race laps if the meeting isn't in
    # the historical archive yet (e.g. fresh live data).
    # ═════════════════════════════════════════════════════════
    _champ_season, _champ_round, _champ_event = _loaded_meeting_season_round()

    _after_pts_src  = _standings_after_round(_champ_season, _champ_round)
    _prev_rnd       = _prev_round(_champ_season, _champ_round)
    _before_pts_src = _standings_after_round(_champ_season, _prev_rnd) if _prev_rnd else {}
    _round_pts_src  = _round_points_for(_champ_season, _champ_round)

    # Fallback: meeting not in the historical archive → derive "this event" points
    # from the loaded race laps so the widget still shows something useful.
    if not _after_pts_src and has_race and "Race_Points" in fl.columns:
        _pts_raw = (
            fl[fl["session_name"].isin(race_sess)]
            .groupby(["session_name", "Driver_Short", "Team"])["Race_Points"]
            .first().reset_index()
        )
        _pts_raw["Race_Points"] = pd.to_numeric(_pts_raw["Race_Points"], errors="coerce").fillna(0)
        _round_pts_src  = _pts_raw.groupby("Team")["Race_Points"].sum().to_dict()
        _after_pts_src  = dict(_round_pts_src)
        _before_pts_src = {}

    _session_team_pts = _round_pts_src

    _all_champ_teams = sorted(
        set(_after_pts_src) | set(_before_pts_src) | set(_session_team_pts)
    )

    def _rank_by_pts(pts_dict):
        """Dense rank (1 = most pts). Ties get the same rank."""
        ordered = sorted(pts_dict.items(), key=lambda x: -x[1])
        rank, prev_pts, prev_rank = {}, None, 0
        for i, (t, p) in enumerate(ordered):
            if p != prev_pts:
                prev_rank = i + 1
            rank[t] = prev_rank
            prev_pts = p
        return rank

    _after_pts  = {t: _after_pts_src.get(t, 0) for t in _all_champ_teams}
    # Prefer the real previous-round standings; otherwise reconstruct as
    # after − this-event points (keeps round-1 / fallback behaviour identical).
    _before_pts = {
        t: (_before_pts_src.get(t, 0) if _before_pts_src
            else max(0, _after_pts[t] - _session_team_pts.get(t, 0)))
        for t in _all_champ_teams
    }

    _rank_after  = _rank_by_pts(_after_pts)
    _rank_before = _rank_by_pts(_before_pts)

    _all_before_zero = all(v == 0 for v in _before_pts.values())

    # Rows sorted by current rank
    _champ_rows_sorted = sorted(
        _all_champ_teams,
        key=lambda t: (_rank_after.get(t, 99), -_after_pts.get(t, 0)),
    )

    _champ_from_archive = _champ_round is not None
    _season_lbl = str(_champ_season) if _champ_season else "current"
    if _champ_from_archive and _champ_event:
        _subtitle_txt = f"  ·  standings after {_champ_event} (round {_champ_round})"
    elif _champ_from_archive:
        _subtitle_txt = f"  ·  standings after round {_champ_round}"
    else:
        _subtitle_txt = "  ·  points from loaded race sessions (not yet in archive)"

    _delta_note = (
        "↕ rank change caused by this event  ·  —  = season opener / no prior round"
        if _all_before_zero else
        "↕ constructor rank change vs the standings before this event"
    )

    _champ_info = (
        "Data: cumulative constructor points for the loaded season, summed from "
        "every race's (and sprint's) points in the historical archive "
        "(constructor_standings_all.parquet, built by fetch_historical_results.py). "
        "'After' = standings through the loaded meeting's round; 'before' = the "
        "previous round; the arrow is the rank change from this event. Re-run the "
        "fetch to pull in newly completed rounds, or load another season to see its "
        "table."
    )

    _champ_body = (
        _standings_leaderboard_body(
            _champ_rows_sorted, _rank_after, _rank_before, _after_pts, _session_team_pts,
            color_of=lambda t: TEAM_COLORS.get(t, "#808080"),
            primary_of=lambda t: t,
            secondary_of=None,
            entity_header="CONSTRUCTOR",
            all_before_zero=_all_before_zero, delta_note=_delta_note,
        )
        if _all_champ_teams else
        html.P(
            "No constructor standings available for the loaded season. "
            "Run fetch_historical_results.py to populate the archive.",
            style={"color": TEXT_DIM, "fontStyle": "italic", "fontSize": "0.8rem"},
        )
    )

    return card(
        html.Span([
            "Constructor Championship  ",
            html.Span(f"{_season_lbl} season", style={"color": ACCENT, "fontWeight": "800"}),
            html.Span(_subtitle_txt,
                      style={"color": TEXT_DIM, "fontWeight": "400",
                             "fontSize": "0.72rem", "marginLeft": "6px"}),
        ]),
        _champ_body,
        info=_champ_info,
    )


def _season_standings_row(fl):
    """Both championship leaderboards side by side — the head of the
    SEASON tab (drivers left, constructors right)."""
    return dbc.Row([
        dbc.Col(_driver_standings_widget(fl), lg=6),
        dbc.Col(_constructor_standings_widget(fl), lg=6),
    ], className="g-3")


def _championship_rank(season) -> dict[str, int]:
    """Driver code → championship rank (0 = leader) for the season's latest
    round. Empty when standings are unavailable."""
    try:
        st = _driver_standings_after_round(int(season), None)
    except Exception:
        st = {}
    if not st:
        return {}
    ordered = sorted(st.items(), key=lambda kv: -kv[1].get("pts", 0))
    return {str(code): i for i, (code, _) in enumerate(ordered)}


def _order_by_champ(codes, season) -> list[str]:
    """Order driver codes by championship points (leader first); unknowns last,
    then alphabetical for stability."""
    rank = _championship_rank(season)
    return sorted(codes, key=lambda c: (rank.get(c, 10_000), c))


# ── Track-Info ↔ loaded-meeting bridge ───────────────────────
# Reverse of HIST_CIRCUIT_KEY_MAP: historical slug → Track-Info (French) slug.
_HIST_TO_FR_KEY: dict[str, str] = {
    hk: fr for fr, hks in HIST_CIRCUIT_KEY_MAP.items() for hk in hks
}


def _slugify_event(name) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def _loaded_event() -> tuple[int | None, str | None]:
    """(season, meeting) of the currently loaded meeting, robust to standings
    gaps — falls back to LOADED_SESSION_INFO when round lookup fails."""
    season, _rnd, meeting = _loaded_meeting_season_round()
    if (season is None or not meeting) and LOADED_SESSION_INFO:
        info = LOADED_SESSION_INFO[0]
        meeting = str(info.get("MEETING", "")).strip() or meeting
        try:
            season = int(info.get("SEASON"))
        except (TypeError, ValueError):
            pass
    return season, meeting


def _loaded_circuit_key() -> str | None:
    """Track-Info circuit slug (CIRCUIT_CHARS key) for the loaded meeting, or
    None when it can't be mapped (e.g. circuit absent from the reference CSV).
    Reads CIRCUIT_CHARS lazily off the `app` module to avoid an import cycle."""
    season, event = _loaded_event()
    if not event:
        return None
    # Prefer the historical circuit_key for this exact event (accent-safe),
    # then translate it to the Track-Info French slug.
    hist_ck = None
    for src in (HIST_RACE, HIST_QUALI):
        if src.empty or "circuit_key" not in src.columns:
            continue
        m = src[src["event_name"].astype(str).str.strip() == str(event).strip()]
        if not m.empty:
            hist_ck = str(m["circuit_key"].iloc[0])
            break
    if hist_ck is None:
        hist_ck = _slugify_event(event)
    fr = _HIST_TO_FR_KEY.get(hist_ck)
    try:
        import app
        cc = getattr(app, "CIRCUIT_CHARS", pd.DataFrame())
    except Exception:
        cc = pd.DataFrame()
    if fr is None and not cc.empty and (cc["circuit_key"] == hist_ck).any():
        fr = hist_ck            # already a Track-Info slug
    if fr and not cc.empty and (cc["circuit_key"] == fr).any():
        return fr
    return None


def _track_avail_years() -> list[int]:
    """Seasons present in the historical archive, newest first."""
    return sorted(set(
        list(HIST_RACE["season"].unique() if "season" in HIST_RACE.columns else []) +
        list(HIST_QUALI["season"].unique() if "season" in HIST_QUALI.columns else [])
    ), reverse=True)


def _circuit_race_years(circuit_key) -> list[int]:
    """Seasons for which the archive holds a race result for *circuit_key*."""
    keys = HIST_CIRCUIT_KEY_MAP.get(circuit_key, [circuit_key])
    if HIST_RACE.empty or "circuit_key" not in HIST_RACE.columns:
        return []
    return sorted(int(y) for y in
                  HIST_RACE[HIST_RACE["circuit_key"].isin(keys)]["season"].unique())


def _circuit_display_season(circuit_key, avail_years: list[int] | None = None) -> int | None:
    """Season the whole Track-Info page should display for *circuit_key*: the
    current season when that Grand Prix has already run (a race result exists),
    otherwise the previous season (N-1). Clamped to what the archive holds."""
    avail_years = avail_years if avail_years is not None else _track_avail_years()
    if not avail_years:
        return None
    cur = max(avail_years)
    cyears = _circuit_race_years(circuit_key)
    if cur in cyears:                       # this GP has run in the current season
        return cur
    target = cur - 1                        # N-1 otherwise
    if target in avail_years:
        return target
    le = [y for y in avail_years if y <= target]
    return max(le) if le else (max(cyears) if cyears else cur)
