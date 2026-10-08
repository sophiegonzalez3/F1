"""Shared loader for data/team_pace_by_event.csv (built by
compute_team_pace.py). Used by the SEASON tab and the Upgrade Impact
analysis. Re-reads automatically when the CSV changes on disk."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_PATH = Path("data/team_pace_by_event.csv")
_CACHE: dict = {"mtime": None, "df": pd.DataFrame()}

# Two families, and they are not interchangeable — see compute_team_pace.py.
#
#   RESULT   quali_result_gap_pct   where the car finished up on Saturday
#            race_pace_gap_pct      race pace, but baselined on the fastest
#                                   team rather than the field median
#   SPEED /  onelap_speed_pct       one flat-out lap, session-normalised
#   PACE     race_pace_pct          sustained race laps
#            …both vs the FIELD MEDIAN, which is what the season charts read.
#
# Note race_pace_gap_pct keeps "pace": it IS a race-pace measure, only its
# baseline differs. quali_result_gap_pct does not, because it mixes car speed
# with how far through qualifying the team got.
_COLS = ["season", "round", "event", "team",
         "quali_result_gap_pct", "onelap_speed_pct",
         "race_pace_gap_pct", "race_pace_pct", "race_pace_missing",
         "points", "cum_points"]

# Legacy header handling lives in config so f1lib/pace_model.py — which reads
# the same CSV directly, without going through this module — applies exactly
# the same map. Two copies of a compatibility shim is one copy too many.
from f1lib.config import apply_pace_legacy_columns as _apply_legacy_names

_CAL_PATH = Path("data/season_calendar.csv")
_CAL_CACHE: dict = {"mtime": None, "df": pd.DataFrame()}

_CAL_COLS = ["season", "round", "event", "country",
             "location", "event_date", "sprint"]


def team_pace_df() -> pd.DataFrame:
    """The per-event team pace table; empty frame (with columns) when the
    CSV hasn't been generated yet (run compute_team_pace.py)."""
    try:
        mtime = _PATH.stat().st_mtime if _PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _CACHE["mtime"]:
        if mtime is None:
            _CACHE["df"] = pd.DataFrame(columns=_COLS)
        else:
            try:
                _CACHE["df"] = _apply_legacy_names(pd.read_csv(_PATH))
            except Exception:
                _CACHE["df"] = pd.DataFrame(columns=_COLS)
        _CACHE["mtime"] = mtime
    return _CACHE["df"]


def season_calendar_df() -> pd.DataFrame:
    """Per-event schedule (round, event, country, location, date, sprint flag),
    built by scripts/fetch_calendar.py. Empty frame (with columns) when the CSV
    hasn't been generated yet. Re-reads automatically when the file changes."""
    try:
        mtime = _CAL_PATH.stat().st_mtime if _CAL_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _CAL_CACHE["mtime"]:
        if mtime is None:
            _CAL_CACHE["df"] = pd.DataFrame(columns=_CAL_COLS)
        else:
            try:
                _CAL_CACHE["df"] = pd.read_csv(_CAL_PATH)
            except Exception:
                _CAL_CACHE["df"] = pd.DataFrame(columns=_CAL_COLS)
        _CAL_CACHE["mtime"] = mtime
    return _CAL_CACHE["df"]


def seasons() -> list[int]:
    df = team_pace_df()
    return sorted(int(s) for s in df["season"].unique()) if not df.empty else []


# Short venue for a race that kept its name but moved, keyed by circuit_id.
_MOVED_VENUE = {"madring": "Madrid", "sepang": "Sepang"}


def event_short(name: str, season: int | None = None) -> str:
    """'Austrian Grand Prix' -> 'Austrian' (compact x-axis labels).

    Pass the season: a relocated race gets its venue appended
    ('Spanish (Madrid)', 'Bahrain (Sepang)'), since the bare name reads as the
    circuit it USED to run on — and the 2026 Barcelona GP sits beside it."""
    short = str(name).replace(" Grand Prix", "").strip()
    if season is not None:
        from f1lib.circuits import circuit_id
        cid = circuit_id(name, season)
        if cid != circuit_id(name) and cid in _MOVED_VENUE:
            return f"{short} ({_MOVED_VENUE[cid]})"
    return short


# ── Sidebar team filter ──────────────────────────────────────
# The sidebar's TEAMS selection holds the LOADED event's team names, while the
# SEASON cards can show any archived year — and the archives disagree on what
# a team is called ('Kick Sauber' in the results archive, 'Sauber' in the pace
# table, 'RB' vs 'Racing Bulls'). Matching on one lineage identity lets a
# 2026 selection still pick out the right rows of 2024. Mirrors
# f1lib.pace_features.TEAM_CANON, without importing the model layer.
_TEAM_LINEAGE = {
    "RB": "Racing Bulls", "AlphaTauri": "Racing Bulls",
    "Kick Sauber": "Sauber", "Alfa Romeo": "Sauber",
    "Alfa Romeo Racing": "Sauber", "Audi": "Sauber",
}


def _lineage(team) -> str:
    t = str(team).strip()
    return _TEAM_LINEAGE.get(t, t)


def team_mask(teams: pd.Series, selected) -> pd.Series:
    """Boolean mask: which rows of `teams` belong to the selection.
    `selected` None means the full field — everything is kept; an EMPTY list
    keeps nothing (a driver filter whose drivers didn't race that season)."""
    if selected is None:
        return pd.Series(True, index=teams.index)
    keep = {_lineage(t) for t in selected}
    return teams.map(_lineage).isin(keep)


def filter_teams(df: pd.DataFrame, selected, col: str = "team") -> pd.DataFrame:
    """`df` narrowed to the team selection (None = untouched)."""
    if selected is None or df.empty or col not in df.columns:
        return df
    return df[team_mask(df[col], selected)]


# ── Sidebar driver filter + driver↔team scope ────────────────
# The SEASON tab has two kinds of card, and a driver who changed seats
# mid-season (Lawson: Racing Bulls, then Red Bull for rounds 12-14 of 2026)
# needs a rule for each:
#   TEAM cards   keep the selected teams' CARS, whoever was driving them. A
#                driver filter narrows them to the teams those drivers raced
#                for this season.
#   DRIVER cards keep a driver who raced for ANY selected team at any point of
#                the season — with his whole season's data, since the card is
#                about the driver — and who passes the driver filter.
_DRIVE_CACHE: dict = {}


def drove_for(season: int) -> dict[str, set[str]]:
    """Driver code → the team LINEAGES he raced for in `season` (race results
    archive). Empty when the archive is missing."""
    if season in _DRIVE_CACHE:
        return _DRIVE_CACHE[season]
    out: dict[str, set[str]] = {}
    try:
        from f1lib.config import HISTORICAL_DIR
        r = pd.read_parquet(Path(HISTORICAL_DIR) / "race_results_all.parquet",
                            columns=["season", "Abbreviation", "TeamName"])
        r = r[r["season"] == season].dropna()
        for d, t in zip(r["Abbreviation"].astype(str), r["TeamName"]):
            out.setdefault(d, set()).add(_lineage(t))
    except Exception:
        pass
    _DRIVE_CACHE[season] = out
    return out


def season_scope(season: int, teams=None, drivers=None):
    """(team scope, driver scope) for one season from the sidebar selections.

    Each is None when it doesn't narrow anything. `teams` / `drivers` must
    already be None when the sidebar has everything selected (see
    active_selection) — an all-selected list is not a filter."""
    if not teams and not drivers:
        return None, None
    dt = drove_for(season)
    team_scope = {_lineage(t) for t in teams} if teams else None
    if drivers:
        theirs = set().union(*(dt.get(d, set()) for d in drivers))
        team_scope = theirs if team_scope is None else team_scope & theirs
    driver_scope = set(drivers) if drivers else None
    if teams:
        keep = {_lineage(t) for t in teams}
        by_team = {d for d, ts in dt.items() if ts & keep}
        driver_scope = by_team if driver_scope is None else driver_scope & by_team
    return (sorted(team_scope) if team_scope is not None else None,
            driver_scope)


def filter_drivers(df: pd.DataFrame, drivers, col: str = "driver") -> pd.DataFrame:
    """`df` narrowed to a driver scope from season_scope (None = untouched)."""
    if drivers is None or df.empty or col not in df.columns:
        return df
    return df[df[col].astype(str).isin(drivers)]


def active_selection(selected, universe):
    """The sidebar value as a filter: None when it selects everything (or
    nothing — the app reads an empty box as the full field)."""
    if not selected:
        return None
    if universe and set(universe) <= set(selected):
        return None
    return list(selected)
