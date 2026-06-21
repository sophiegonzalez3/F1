"""
fetch_historical_results.py
============================
Iterates over a fixed list of historical seasons plus the current calendar
year and, for every round in each season, fetches:

  • Race results       (session identifier "R")
  • Qualifying results (session identifier "Q")
  • Sprint results     (session identifier "S", sprint-format weekends only)

Each result is the official classification table exposed by FastF1 via
session.results — one row per driver, including finishing/qualifying
position, driver info, team, points, grid, status, lap times, etc.

Output layout
-------------
All files are written under:

    data/historical_results/
    ├── race/
    │   └── {year}_{round:02d}_{event_slug}.parquet
    ├── quali/
    │   └── {year}_{round:02d}_{event_slug}.parquet
    └── sprint/
        └── {year}_{round:02d}_{event_slug}.parquet   (sprint weekends only)

A consolidated summary file is also written for each type:

    data/historical_results/race_results_all.parquet
    data/historical_results/quali_results_all.parquet
    data/historical_results/sprint_results_all.parquet   (if any sprints fetched)

These contain all rounds from all seasons stacked, with added columns:
    season       int   – calendar year
    round_number int   – round number within the season
    event_name   str   – official event name (e.g. "British Grand Prix")
    circuit_key  str   – URL-safe slug derived from event_name
    session_type str   – "Race", "Qualifying" or "Sprint"

Finally, a per-round constructor championship table is derived from the race
*and sprint* points and written to:

    data/historical_results/constructor_standings_all.parquet

with columns season, round_number, event_name, circuit_key, TeamName,
round_points, cumulative_points and position. The dashboard reads this to show
season-aware standings that update automatically as new rounds are fetched.

Usage
-----
    python fetch_historical_results.py

Optional flags:
    --force-reload   Ignore existing parquet files and re-fetch everything
    --seasons 2021 2022 2024    Override the default season list
    --out-dir path/to/dir       Override the default output directory

Dependencies: fastf1, pandas, pyarrow
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import HISTORICAL_DIR, FASTF1_CACHE_DIR

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch_historical")

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
FIXED_SEASONS = [2021, 2022, 2024, 2025]
FASTF1_CACHE  = Path(FASTF1_CACHE_DIR)        # reuse the project's FF1 cache
DEFAULT_OUT   = Path(HISTORICAL_DIR)

# Seconds to wait between API calls to stay polite
INTER_SESSION_SLEEP = 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert event name to a filesystem-safe lowercase slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text.strip("_")


def _safe_df(session) -> pd.DataFrame:
    """Return session.results as a plain DataFrame, or empty if unavailable."""
    try:
        res = session.results
        if res is None or (hasattr(res, "empty") and res.empty):
            return pd.DataFrame()
        return pd.DataFrame(res).copy()
    except Exception as exc:
        log.warning("    session.results unavailable: %s", exc)
        return pd.DataFrame()


def _normalise_results(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce awkward column types so the frame can be written as Parquet.

    FastF1 results may contain:
    - timedelta columns (Q1, Q2, Q3, FastestLap, FastestLapTime, …)
    - timezone-aware datetime columns
    - mixed-type object columns
    """
    import numpy as np
    import pyarrow as pa

    df = df.copy()

    # timedelta → float seconds
    for col in df.select_dtypes(include=["timedelta64[ns]"]).columns:
        df[col] = df[col].dt.total_seconds()

    # tz-aware datetime → tz-naive
    for col in df.select_dtypes(include=["datetimetz"]).columns:
        df[col] = df[col].dt.tz_localize(None)

    # object columns with non-primitive values → str
    for col in df.select_dtypes(include=["object"]).columns:
        try:
            pa.array(df[col], from_pandas=True)
        except (pa.lib.ArrowInvalid, pa.lib.ArrowTypeError):
            df[col] = df[col].astype(str)

    return df


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine="pyarrow")
    log.info("    saved  %s  (%d rows)", path.name, len(df))


def _build_standings(results_df: pd.DataFrame, entity_col: str,
                     team_col: str | None = None) -> pd.DataFrame:
    """
    Generic per-round cumulative championship table, grouped by *entity_col*
    (e.g. "TeamName" for constructors, "Abbreviation" for drivers).

    Pass the Race results — and, for full accuracy, the Sprint results stacked on
    top (both carry Points/round_number, so sprint points fold into the same round
    total automatically). All of an entity's points in a round are summed,
    accumulated across rounds within each season, and the entities ranked at every
    round, so any (season, round) lookup gives the standings *after* that event.

    When *team_col* is given (driver standings) it is carried through for colour
    coding. Returned columns: season, round_number, event_name, circuit_key,
    <entity_col>, [<team_col>,] round_points, cumulative_points, position.
    """
    if (results_df is None or results_df.empty
            or "Points" not in results_df.columns or entity_col not in results_df.columns):
        log.warning("  Cannot build standings — missing Points/%s.", entity_col)
        return pd.DataFrame()

    df = results_df.copy()
    df["Points"] = pd.to_numeric(df["Points"], errors="coerce").fillna(0.0)
    df[entity_col] = df[entity_col].astype(str).str.strip()

    key = [c for c in ["season", "round_number", "event_name", "circuit_key", entity_col]
           if c in df.columns]
    if team_col and team_col != entity_col and team_col in df.columns:
        df[team_col] = df[team_col].astype(str).str.strip()
        key = key + [team_col]

    per = (
        df.groupby(key)["Points"].sum().reset_index()
          .rename(columns={"Points": "round_points"})
    )
    per = per.sort_values(["season", "round_number"])
    per["cumulative_points"] = per.groupby(["season", entity_col])["round_points"].cumsum()
    per["position"] = (
        per.groupby(["season", "round_number"])["cumulative_points"]
           .rank(method="min", ascending=False).astype(int)
    )
    return per.sort_values(["season", "round_number", "position"]).reset_index(drop=True)


def build_constructor_standings(results_df: pd.DataFrame) -> pd.DataFrame:
    """Per-round cumulative constructor (team) standings. See _build_standings."""
    return _build_standings(results_df, entity_col="TeamName")


def build_driver_standings(results_df: pd.DataFrame) -> pd.DataFrame:
    """Per-round cumulative drivers' standings (keyed by Abbreviation, carrying
    TeamName for colour). See _build_standings."""
    return _build_standings(results_df, entity_col="Abbreviation", team_col="TeamName")


# ─────────────────────────────────────────────────────────────────────────────
# Core fetcher
# ─────────────────────────────────────────────────────────────────────────────

# FastF1 session id → (output sub-dir, session_type label)
_SESSION_LABELS = {"R": "Race", "Q": "Qualifying", "S": "Sprint"}


def fetch_season(
    year: int,
    out_dir: Path,
    force_reload: bool = False,
) -> tuple[list[pd.DataFrame], list[pd.DataFrame], list[pd.DataFrame]]:
    """
    Fetch Race, Qualifying and Sprint results for every round in *year*.

    The Sprint race ("S") is only attempted on sprint-format weekends (detected
    from the schedule's EventFormat), since its points count toward the
    constructors' championship. Sprint Qualifying / Shootout award no points and
    are skipped.

    Returns (race_frames, quali_frames, sprint_frames) – one DataFrame per round
    for rounds that had data available.
    """
    import fastf1

    fastf1.Cache.enable_cache(str(FASTF1_CACHE))

    log.info("=" * 66)
    log.info("Season %d", year)
    log.info("=" * 66)

    # Get the event schedule for the season
    try:
        schedule = fastf1.get_event_schedule(year, include_testing=False)
    except Exception as exc:
        log.error("  Cannot fetch schedule for %d: %s", year, exc)
        return [], [], []

    if schedule.empty:
        log.warning("  Empty schedule for %d", year)
        return [], [], []

    log.info("  %d rounds found", len(schedule))

    race_frames: list[pd.DataFrame] = []
    quali_frames: list[pd.DataFrame] = []
    sprint_frames: list[pd.DataFrame] = []

    for _, event in schedule.iterrows():
        round_num  = int(event.get("RoundNumber", 0))
        event_name = str(event.get("EventName", f"Round_{round_num}")).strip()
        slug       = _slugify(event_name)

        # Skip rounds in the future (no results yet)
        event_date = pd.to_datetime(event.get("EventDate", pd.NaT), errors="coerce")
        if pd.notna(event_date) and event_date.date() > datetime.now().date():
            log.info("  Round %2d  %-40s  [future – skip]", round_num, event_name)
            continue

        is_sprint = "sprint" in str(event.get("EventFormat", "")).lower()
        log.info("  Round %2d  %s%s", round_num, event_name,
                 "  [sprint weekend]" if is_sprint else "")

        # Race + Qualifying every weekend; Sprint only on sprint-format weekends.
        sessions = [
            ("R", "race",  race_frames),
            ("Q", "quali", quali_frames),
        ]
        if is_sprint:
            sessions.append(("S", "sprint", sprint_frames))

        for session_type, sub_dir, frame_list in sessions:
            out_path = out_dir / sub_dir / f"{year}_{round_num:02d}_{slug}.parquet"

            # Skip if already fetched and not force-reloading
            if not force_reload and out_path.exists():
                try:
                    cached = pd.read_parquet(out_path)
                    frame_list.append(cached)
                    log.info("    [%s] cache hit – %d rows", session_type, len(cached))
                    continue
                except Exception:
                    log.warning("    [%s] corrupt cache – will re-fetch", session_type)

            # Fetch from FastF1
            try:
                sess = fastf1.get_session(year, round_num, session_type)
                # Load only results (no laps/telemetry/weather needed here)
                sess.load(
                    laps=False,
                    telemetry=False,
                    weather=False,
                    messages=False,
                )
            except Exception as exc:
                log.warning("    [%s] load failed: %s", session_type, exc)
                time.sleep(INTER_SESSION_SLEEP)
                continue

            res_df = _safe_df(sess)
            if res_df.empty:
                log.warning("    [%s] no results returned", session_type)
                time.sleep(INTER_SESSION_SLEEP)
                continue

            # Add context columns
            res_df["season"]       = year
            res_df["round_number"] = round_num
            res_df["event_name"]   = event_name
            res_df["circuit_key"]  = slug
            res_df["session_type"] = _SESSION_LABELS.get(session_type, session_type)

            res_df = _normalise_results(res_df)
            _write_parquet(res_df, out_path)
            frame_list.append(res_df)

            time.sleep(INTER_SESSION_SLEEP)

    return race_frames, quali_frames, sprint_frames


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Fetch F1 race & qualifying results for multiple seasons."
    )
    parser.add_argument(
        "--seasons", nargs="+", type=int, default=None,
        help="Override the season list (e.g. --seasons 2021 2022 2024)",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT,
        help=f"Output directory (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--force-reload", action="store_true",
        help="Re-fetch even when a cached parquet already exists",
    )
    args = parser.parse_args(argv)

    try:
        import fastf1
    except ImportError:
        log.error("fastf1 is not installed.  Run: pip install fastf1")
        sys.exit(1)

    # Build season list: fixed seasons + current calendar year (deduplicated)
    current_year = datetime.now().year
    base_seasons  = args.seasons if args.seasons else FIXED_SEASONS
    seasons       = sorted(set(base_seasons) | {current_year})

    log.info("Seasons to process: %s", seasons)
    log.info("Output directory  : %s", args.out_dir.resolve())
    log.info("Force reload      : %s", args.force_reload)

    FASTF1_CACHE.mkdir(parents=True, exist_ok=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    all_race   = []
    all_quali  = []
    all_sprint = []

    for year in seasons:
        race_frames, quali_frames, sprint_frames = fetch_season(
            year, args.out_dir, force_reload=args.force_reload
        )
        all_race.extend(race_frames)
        all_quali.extend(quali_frames)
        all_sprint.extend(sprint_frames)

    # ── Write consolidated summaries ──────────────────────────
    log.info("")
    log.info("Writing consolidated summary files…")

    race_combined:   pd.DataFrame | None = None
    sprint_combined: pd.DataFrame | None = None
    for frames, name in [
        (all_race,   "race_results_all"),
        (all_quali,  "quali_results_all"),
        (all_sprint, "sprint_results_all"),
    ]:
        if not frames:
            if name != "sprint_results_all":   # sprints are optional
                log.warning("No data collected for %s", name)
            continue
        try:
            combined = pd.concat(frames, ignore_index=True)
            # Sort for predictable ordering
            sort_cols = [c for c in ("season", "round_number", "Position")
                         if c in combined.columns]
            if sort_cols:
                combined = combined.sort_values(sort_cols).reset_index(drop=True)
            out_path = args.out_dir / f"{name}.parquet"
            _write_parquet(combined, out_path)
            log.info("  %s: %d total rows across %d seasons",
                     name, len(combined), combined["season"].nunique()
                     if "season" in combined.columns else "?")
            if name == "race_results_all":
                race_combined = combined
            elif name == "sprint_results_all":
                sprint_combined = combined
        except Exception as exc:
            log.error("  Failed to write %s: %s", name, exc)

    # ── Constructor championship standings (race + sprint points) ──
    if race_combined is not None and not race_combined.empty:
        try:
            points_source = race_combined
            if sprint_combined is not None and not sprint_combined.empty:
                # Stack sprint rows so their points fold into the same round total
                shared = [c for c in points_source.columns if c in sprint_combined.columns]
                points_source = pd.concat(
                    [points_source[shared], sprint_combined[shared]], ignore_index=True
                )
                log.info("  standings include sprint points (%d sprint rows)",
                         len(sprint_combined))
            standings = build_constructor_standings(points_source)
            if not standings.empty:
                _write_parquet(standings, args.out_dir / "constructor_standings_all.parquet")
                log.info("  constructor_standings_all: %d rows across %d seasons",
                         len(standings), standings["season"].nunique())

            drv_standings = build_driver_standings(points_source)
            if not drv_standings.empty:
                _write_parquet(drv_standings, args.out_dir / "driver_standings_all.parquet")
                log.info("  driver_standings_all: %d rows across %d seasons",
                         len(drv_standings), drv_standings["season"].nunique())
        except Exception as exc:
            log.error("  Failed to build standings: %s", exc)

    log.info("")
    log.info("Done.")


if __name__ == "__main__":
    main()