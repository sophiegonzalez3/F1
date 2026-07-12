"""Backfill practice-session LAPS (no telemetry) -> data/sessions_lite/.

The pace-prediction model (pace_features.py / pace_model.py) needs practice
laps from past seasons to train and validate on, but the app's full session
cache (laps + 2M-row telemetry) is far too heavy to backfill for whole
seasons. This script fetches ONLY laps + weather for every practice session
of the requested seasons and stores them under data/sessions_lite/ with the
same key naming and column mapping as data/sessions/, so processing.py's
enrichment pipeline works on them unchanged.

data/sessions_lite/ is deliberately separate from data/sessions/: the app
loader treats "laps present but telemetry missing/empty" as a stale cache and
would re-fetch the full session. Nothing in the app reads sessions_lite; only
the model pipeline does (via pace_features.load_practice_laps, which prefers
the full cache when an event is already there).

Usage
-----
    python fetch_practice_laps.py                      # 2024 + 2025
    python fetch_practice_laps.py --seasons 2025       # one season
    python fetch_practice_laps.py --dry-run            # list what would fetch
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd

import fastf1

import data_loader as dl
from config import SESSIONS_LITE_DIR, SESSIONS_DIR, FASTF1_CACHE_DIR

LITE = Path(SESSIONS_LITE_DIR)
FULL = Path(SESSIONS_DIR)

# Practice sessions only: quali/race targets come from the historical results
# archive, and race laps for race-pace targets come from the full cache.
_WANTED = ("Practice 1", "Practice 2", "Practice 3")


def _lite_paths(key: str) -> dict[str, Path]:
    return {"laps": LITE / f"{key}__laps.parquet",
            "weather": LITE / f"{key}__weather.parquet"}


def already_have(season: int, meeting: str, session: str) -> str | None:
    """'full' / 'lite' if the laps are already cached somewhere, else None."""
    key = dl._session_key(str(season), meeting, session)
    if (FULL / f"{key}__laps.parquet").exists():
        return "full"
    if _lite_paths(key)["laps"].exists():
        return "lite"
    return None


def fetch_one(season: int, meeting: str, session: str) -> bool:
    key = dl._session_key(str(season), meeting, session)
    sess_name = dl._session_name(str(season), meeting, session)
    paths = _lite_paths(key)

    ff1_sess = fastf1.get_session(season, meeting, dl._ff1_session_id(session))
    ff1_sess.load(laps=True, telemetry=False, weather=True, messages=False)

    laps = dl._map_laps(ff1_sess.laps)
    if laps.empty:
        print(f"  [empty]  {key} — no laps returned, skipped", flush=True)
        return False
    weather = dl._safe_attr(ff1_sess, "weather_data")

    dl._tag(laps, session, str(season), meeting, sess_name)
    if not weather.empty:
        dl._tag(weather, session, str(season), meeting, sess_name)

    dl._save_df(laps, paths["laps"])
    if not weather.empty:
        dl._save_df(weather, paths["weather"])
    print(f"  [saved]  {key} — {len(laps):,} laps"
          f"{'' if weather.empty else f', {len(weather):,} weather rows'}",
          flush=True)
    return True


def season_plan(season: int) -> list[tuple[str, str]]:
    """(meeting, session) pairs for every practice session already run."""
    sched = fastf1.get_event_schedule(season, include_testing=False)
    now = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
    plan: list[tuple[str, str]] = []
    for _, ev in sched.iterrows():
        meeting = str(ev["EventName"])
        for i in range(1, 6):
            name = str(ev.get(f"Session{i}", "") or "")
            if name not in _WANTED:
                continue
            date = ev.get(f"Session{i}DateUtc")
            if pd.notna(date) and pd.Timestamp(date) > now:
                continue                     # hasn't happened yet
            plan.append((meeting, name))
    return plan


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", nargs="+", type=int, default=[2024, 2025])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    LITE.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(Path(FASTF1_CACHE_DIR)))
    fastf1.set_log_level("WARNING")

    n_ok = n_skip = n_fail = 0
    for season in args.seasons:
        plan = season_plan(season)
        print(f"\n[{season}] {len(plan)} practice sessions on the calendar",
              flush=True)
        for meeting, session in plan:
            where = already_have(season, meeting, session)
            if where:
                n_skip += 1
                continue
            if args.dry_run:
                print(f"  would fetch: {season} {meeting} — {session}")
                continue
            # FastF1 enforces 500 API calls/h. When we hit it, sleep and
            # resume instead of burning the rest of the plan as failures.
            for attempt in range(6):
                try:
                    if fetch_one(season, meeting, session):
                        n_ok += 1
                    else:
                        n_fail += 1
                    break
                except Exception as exc:
                    if "500 calls" in str(exc) or "RateLimit" in type(exc).__name__:
                        print(f"  [rate-limited] sleeping 15 min "
                              f"(attempt {attempt + 1}/6)…", flush=True)
                        time.sleep(900)
                        continue
                    n_fail += 1
                    print(f"  [FAIL]   {season} {meeting} {session}: {exc}",
                          flush=True)
                    break
            else:
                n_fail += 1
                print(f"  [FAIL]   {season} {meeting} {session}: "
                      "rate limit never cleared", flush=True)
            time.sleep(1.0)                  # be polite to the API

    print(f"\nDone: {n_ok} fetched, {n_skip} already cached, {n_fail} failed",
          flush=True)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
