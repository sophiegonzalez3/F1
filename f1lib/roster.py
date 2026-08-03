"""Who is actually racing this season.

F1 mandates rookie FP1 outings — two per car per season from 2025, which in
2026 puts up to SIX non-race drivers on track at once (Austria and Barcelona
both had six). They are not slower in an interesting way: they are slower in a
way that moves every field-relative measurement in the dashboard.

The damage is easy to underestimate because it is not "one team gets a bad
number". Practice measurements are expressed against the session's own median
(`pace_features._onelap_measurements`), so a handful of tester laps drag that
reference and shift EVERY team's figure at once — a whole-field bias, which is
exactly the kind that never looks wrong on screen.

Source of truth is data/driver_info.csv, the curated per-season roster, rather
than the championship standings: standings only list a driver once results
exist, so a standings-based filter silently deletes the whole grid in
pre-season and at round 1.

FAIL OPEN. `race_drivers()` returns None for a season with no roster row, and
every caller must read that as "don't filter" rather than "nobody raced".
driver_info.csv currently covers 2026 only; loading a 2023 event must show
that event's drivers, not an empty dashboard.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DRIVER_INFO_PATH = Path("data/driver_info.csv")

_CACHE: dict = {"mtime": None, "by_season": {}}


def _load() -> dict[int, frozenset[str]]:
    """{season: {driver codes}}, re-read when the CSV changes on disk."""
    try:
        mtime = DRIVER_INFO_PATH.stat().st_mtime if DRIVER_INFO_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _CACHE["mtime"]:
        by_season: dict[int, frozenset[str]] = {}
        if mtime is not None:
            try:
                df = pd.read_csv(DRIVER_INFO_PATH, encoding="utf-8-sig")
                if {"season", "driver"}.issubset(df.columns):
                    df = df.dropna(subset=["season", "driver"])
                    df["season"] = pd.to_numeric(df["season"], errors="coerce")
                    df = df.dropna(subset=["season"])
                    for season, g in df.groupby(df["season"].astype(int)):
                        codes = {str(d).strip().upper()
                                 for d in g["driver"] if str(d).strip()}
                        if codes:
                            by_season[int(season)] = frozenset(codes)
            except Exception as exc:            # never break a data load over this
                print(f"Driver roster           : failed to read ({exc})")
        _CACHE["by_season"] = by_season
        _CACHE["mtime"] = mtime
    return _CACHE["by_season"]


def race_drivers(season) -> frozenset[str] | None:
    """The season's race drivers as three-letter codes, or None if unknown.

    None means "no roster on file" — callers MUST treat that as no filtering.
    """
    try:
        season = int(season)
    except (TypeError, ValueError):
        return None
    return _load().get(season)


def known_seasons() -> list[int]:
    return sorted(_load())


def is_race_driver(driver, season) -> bool:
    """True when the driver raced that season, or when the roster is unknown."""
    roster = race_drivers(season)
    if roster is None:
        return True
    return str(driver).strip().upper() in roster


def flag_race_drivers(df: pd.DataFrame,
                      driver_col: str = "Driver_Short",
                      season_col: str = "season") -> pd.Series:
    """Boolean Series aligned to `df`: is this lap's driver a race driver?

    True wherever the season has no roster on file, so an un-rostered season
    behaves exactly as it did before this module existed.
    """
    if df.empty or driver_col not in df.columns:
        return pd.Series(True, index=df.index, dtype=bool)
    if season_col not in df.columns:
        return pd.Series(True, index=df.index, dtype=bool)

    codes = df[driver_col].astype(str).str.strip().str.upper()
    out = pd.Series(True, index=df.index, dtype=bool)
    seasons = pd.to_numeric(df[season_col], errors="coerce")
    for season in seasons.dropna().unique():
        roster = race_drivers(int(season))
        if roster is None:
            continue                        # fail open for this season
        m = seasons == season
        out.loc[m] = codes[m].isin(roster)
    return out


def non_race_drivers_in(df: pd.DataFrame,
                        driver_col: str = "Driver_Short",
                        season_col: str = "season") -> list[str]:
    """Sorted driver codes present in `df` that are NOT on the season roster."""
    if df.empty or driver_col not in df.columns:
        return []
    mask = ~flag_race_drivers(df, driver_col, season_col)
    return sorted(df.loc[mask, driver_col].dropna().astype(str).unique())
