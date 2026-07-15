"""Shared loaders for the measured race-operations tables built by
scripts/compute_race_stats.py:

  data/race_stats.csv    per-race SC/VSC/red counts, overtakes, lap-1 swing,
                         weather, pit loss, deleted laps, winner strategy
  data/track_limits.csv  per-race per-corner deleted-lap counts
  data/lap1_league.csv   per-race per-driver lap-1 gain vs grid
  data/pit_league.csv    one row per pit stop (team attached)

Used by the TRACK tab (measured circuit stats) and the SEASON tab (chaos
timeline, pit-stop league, lap-1 league). Each table re-reads automatically
when its CSV changes on disk — same pattern as tabs/pace_data.py.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_FILES = {
    "race_stats":   Path("data/race_stats.csv"),
    "track_limits": Path("data/track_limits.csv"),
    "lap1":         Path("data/lap1_league.csv"),
    "pits":         Path("data/pit_league.csv"),
}
_CACHE: dict = {k: {"mtime": None, "df": pd.DataFrame()} for k in _FILES}


def _load(name: str) -> pd.DataFrame:
    path = _FILES[name]
    cache = _CACHE[name]
    try:
        mtime = path.stat().st_mtime if path.exists() else None
    except OSError:
        mtime = None
    if mtime != cache["mtime"]:
        try:
            cache["df"] = pd.read_csv(path) if mtime else pd.DataFrame()
        except Exception:
            cache["df"] = pd.DataFrame()
        cache["mtime"] = mtime
    return cache["df"]


def race_stats_df() -> pd.DataFrame:
    return _load("race_stats")


def track_limits_df() -> pd.DataFrame:
    return _load("track_limits")


def lap1_df() -> pd.DataFrame:
    return _load("lap1")


def pits_df() -> pd.DataFrame:
    return _load("pits")
