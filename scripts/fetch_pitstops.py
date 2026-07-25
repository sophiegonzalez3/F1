"""Fetch real per-stop pit data for cached races → data/pitstops/.

The app fetches this lazily, the first time you open the RACE tab for a race.
That is fine when you browse every race, but `compute_race_stats.py` reads the
parquet files directly — a race whose RACE tab was never opened silently drops
out of the pit league and out of the pit columns of the measured TRACK card.
This script closes that hole: it walks the cached session archive and fetches
whatever is missing, so the post-race chain can depend on it.

Sources (see f1lib/pitstops_loader.py): the live-timing PitStopSeries feed —
true stationary times — with a Jolpica/Ergast fallback that only knows
pit-lane durations. Older races usually only have the fallback.

Usage
-----
    python scripts/fetch_pitstops.py                       # every cached race missing data
    python scripts/fetch_pitstops.py --season 2026         # one season
    python scripts/fetch_pitstops.py 2026 "Belgian Grand Prix"
    python scripts/fetch_pitstops.py --dry-run             # list what would be fetched
    python scripts/fetch_pitstops.py --force --season 2026 # re-fetch even if cached
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import logging
import time
import warnings

warnings.filterwarnings("ignore")

import f1lib.data_loader as dl
from f1lib.pitstops_loader import load_pitstops, pitstops_cached

INTER_MEETING_SLEEP = 1.0        # be polite to the live-timing / Jolpica APIs


def cached_races() -> list[tuple[int, str]]:
    """(season, meeting) for every Race session in data/sessions/, by season."""
    out = {
        (int(s["season"]), str(s["meeting"]))
        for s in dl.list_cached_sessions()
        if str(s.get("session")) == "Race" and str(s.get("season", "")).isdigit()
    }
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("season", nargs="?", type=int, help="single season")
    ap.add_argument("meeting", nargs="?", help='single meeting, e.g. "Belgian Grand Prix"')
    ap.add_argument("--season", dest="season_flag", type=int, help="restrict to one season")
    ap.add_argument("--force", action="store_true", help="re-fetch already-cached meetings")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")

    if args.season and args.meeting:
        targets = [(args.season, args.meeting)]
    else:
        season = args.season_flag or args.season
        targets = [t for t in cached_races() if season is None or t[0] == season]

    todo = [t for t in targets if args.force or not pitstops_cached(*t)]
    if not todo:
        print(f"Pit stops already cached for all {len(targets)} cached race(s).")
        return 0

    print(f"{len(todo)} of {len(targets)} cached race(s) need pit-stop data.")
    if args.dry_run:
        for season, meeting in todo:
            print(f"  would fetch  {season} {meeting}")
        return 0

    ok = empty = failed = 0
    for i, (season, meeting) in enumerate(todo, 1):
        try:
            df = load_pitstops(season, meeting, force=args.force)
        except Exception as exc:                 # one bad meeting mustn't sink the run
            print(f"  [fail]  {season} {meeting} - {type(exc).__name__}: {exc}", flush=True)
            failed += 1
        else:
            if df.empty:
                # Race not run yet, or neither feed knows this meeting name.
                print(f"  [none]  {season} {meeting} - no data from either source", flush=True)
                empty += 1
            else:
                src = df["source"].iloc[0]
                print(f"  [ok]    {season} {meeting} - {len(df)} stops (source={src})",
                      flush=True)
                ok += 1
        if i < len(todo):
            time.sleep(INTER_MEETING_SLEEP)

    print(f"\nDone: {ok} fetched, {empty} with no data, {failed} failed.")
    # "no data" is a normal outcome upstream, not an error — only hard failures
    # should stop a chain like after_race.py.
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
