"""Shared loader for data/team_pace_by_event.csv (built by
compute_team_pace.py). Used by the SEASON tab and the Upgrade Impact
analysis. Re-reads automatically when the CSV changes on disk."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_PATH = Path("data/team_pace_by_event.csv")
_CACHE: dict = {"mtime": None, "df": pd.DataFrame()}

_COLS = ["season", "round", "event", "team",
         "quali_gap_pct", "race_pace_gap_pct", "points", "cum_points"]


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
                _CACHE["df"] = pd.read_csv(_PATH)
            except Exception:
                _CACHE["df"] = pd.DataFrame(columns=_COLS)
        _CACHE["mtime"] = mtime
    return _CACHE["df"]


def seasons() -> list[int]:
    df = team_pace_df()
    return sorted(int(s) for s in df["season"].unique()) if not df.empty else []


def event_short(name: str) -> str:
    """'Austrian Grand Prix' -> 'Austrian' (compact x-axis labels)."""
    return str(name).replace(" Grand Prix", "").strip()
