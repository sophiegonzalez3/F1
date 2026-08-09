"""Run the whole post-race data refresh in one go.

Prerequisite: the race weekend's sessions are cached under data/sessions/
(run `scripts/during_weekend.py`, or load the event in the app's Data tab —
this script computes from the cache, it does not fetch sessions).

Steps, in dependency order (except the first, which jumps the queue because
its source data expires — see the note on `odds` in STEPS):

  0. scripts/fetch_odds.py             market-implied probabilities for the
                                       weekend just run, hourly, before Kalshi
                                       prunes them (~2 months)
  1. scripts/fetch_pitstops.py         real pit stops (race stats needs them)
  2. f1lib.fetch_historical_results    results/quali/sprint archive + standings
  3. scripts/compute_incidents.py      race-control incident register (DNF
                                       causes + the decomposition's labels)
  4. scripts/compute_team_pace.py      per-event team pace table (needs the archive)
  5. f1lib.driver_ratings              per-event DRIVER pace table (BRIEF/DUEL)
  6. scripts/compute_race_stats.py     SC rates, overtakes, pit league, ...
  7. scripts/compute_atr.py            ATR sliding scale (needs standings)
  8. scripts/compute_pu_topspeed.py    straight-line-speed / PU index (sessions)
  9. scripts/compute_car_profile.py    car-concept axes for the STINTS tab
                                       (telemetry, ~1 min per event)
 10. scripts/backtest_pace_model.py    replays every weekend and re-scores the
                                       pace model — feeds the BRIEF tab's
                                       track-record card, so skipping it
                                       silently leaves that card stale
 11. scripts/compute_weekend_decomp.py 'where the points went' table for the
                                       RACE tab (needs pace, stats, incidents)
 12. scripts/compute_upgrade_study.py  panel event study on declared upgrades
                                       (needs the pace table + upgrades.csv)
 13. compute_mistakes.py               micro-mistake archive (telemetry, slow)

Stops at the first failing step; every step is idempotent, so fix and re-run.
Not covered here (needs a human or a browser): the `radio-review` skill, the
hand-curated CSVs, and `build_quali_scenes.py <season> "<Meeting>"` — the
closing checklist lists them.

Usage
-----
    .venv/Scripts/python scripts/after_race.py
    .venv/Scripts/python scripts/after_race.py --skip-mistakes   # fast pass
    .venv/Scripts/python scripts/after_race.py --skip pitstops --skip mistakes
    .venv/Scripts/python scripts/after_race.py --list
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (key, human name, command). The key is what --skip takes.
STEPS: list[tuple[str, str, list[str]]] = [
    # FIRST because it is the only step whose data EXPIRES. Kalshi prunes a
    # race's markets after roughly seven weekends and the price history 404s
    # with them, so this weekend's odds must be captured within about two
    # months or they are gone for good. Every other step reads local caches
    # and can be re-run whenever. The runner stops at the first failure, so
    # running it first also means a broken later step never costs us the odds.
    ("odds",      "market odds (time-critical)",
     [sys.executable, "scripts/fetch_odds.py", "--backfill", "--max-events", "3"]),
    # Right after the odds, and for a related reason: both record what was
    # KNOWABLE BEFORE the race, which nothing computed from the session cache
    # can reconstruct afterwards. Cheap (only new races) and idempotent; a row
    # left incomplete by the mid-weekend run is completed here, because every
    # lead time (D-1..D-3) has passed by now.
    ("forecast",  "race-day rain forecast",
     [sys.executable, "scripts/fetch_race_forecast.py"]),
    ("pitstops",  "pit stops",
     [sys.executable, "scripts/fetch_pitstops.py"]),
    ("archive",   "results archive",
     [sys.executable, "-m", "f1lib.fetch_historical_results"]),
    ("incidents", "incident register",
     [sys.executable, "scripts/compute_incidents.py"]),
    ("teampace",  "team pace table",
     [sys.executable, "scripts/compute_team_pace.py"]),
    ("driverpace", "driver pace table",
     [sys.executable, "-m", "f1lib.driver_ratings"]),
    ("racestats", "race stats",
     [sys.executable, "scripts/compute_race_stats.py"]),
    ("atr",       "ATR sliding scale",
     [sys.executable, "scripts/compute_atr.py"]),
    ("topspeed",  "PU top-speed index",
     [sys.executable, "scripts/compute_pu_topspeed.py"]),
    ("carprofile", "car concept profile",
     [sys.executable, "scripts/compute_car_profile.py"]),
    ("backtest",   "pace-model scorecard",
     [sys.executable, "scripts/backtest_pace_model.py"]),
    ("decomp",    "weekend decomposition",
     [sys.executable, "scripts/compute_weekend_decomp.py"]),
    ("upgradestudy", "upgrade event study",
     [sys.executable, "scripts/compute_upgrade_study.py"]),
    ("mistakes",  "micro-mistakes",
     [sys.executable, "compute_mistakes.py"]),
    # Both read every cached session, so they belong after the fetch steps and
    # before the review, which cites them.
    ("retention", "lap retention per session",
     [sys.executable, "scripts/compute_lap_retention.py"]),
    ("sessionwx", "per-session weather",
     [sys.executable, "scripts/compute_session_weather.py"]),
    # LAST, because it needs the rebuilt pace + driver tables above to work
    # out who fell outside their error bar. Writes only the skeleton rows;
    # the cause and the note are written by hand afterwards (see FOLLOW_UPS).
    ("review",    "post-race review rows",
     [sys.executable, "scripts/seed_model_review.py", "--latest"]),
    # Gathers the evidence for the rows just seeded. Still writes no verdict —
    # it only means the review can be done from the archive instead of from
    # memory, which is what makes it survivable a week after the race.
    ("dossier",   "review evidence dossier",
     [sys.executable, "scripts/review_dossier.py", "--latest"]),
]

FOLLOW_UPS = [
    "model review    open data/model_review.csv and fill in `category` +",
    "                `note` for the rows just seeded (3-12 a race), reading",
    "                data/review_dossiers/<season>__<Event>.md alongside it —",
    "                that has the practice read, the laps behind each number,",
    "                the screens and the race-control log per driver.",
    "                The category vocabulary is listed by",
    "                python scripts/seed_model_review.py --help",
    "radio review    /radio-review <Meeting>   (fetch the audio SOON - mp3s are",
    "                purged upstream after a few weeks)",
    'quali 3D scene  python scripts/build_quali_scenes.py <season> "<Meeting>"',
    "curated CSVs    python scripts/during_weekend.py --check-only",
    "                (tyre allocation, upgrades, PU + gearbox pools, penalties)",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", action="append", default=[], metavar="KEY",
                    help="skip a step by key (repeatable); see --list")
    ap.add_argument("--skip-mistakes", action="store_true",
                    help="alias for --skip mistakes")
    ap.add_argument("--list", action="store_true", help="print the steps and exit")
    args = ap.parse_args()

    if args.list:
        for key, name, cmd in STEPS:
            print(f"  {key:<11} {name:<20} {' '.join(cmd[1:])}")
        return 0

    skip = {s.lower() for s in args.skip}
    if args.skip_mistakes:
        skip.add("mistakes")
    unknown = skip - {k for k, _, _ in STEPS}
    if unknown:
        print(f"Unknown --skip key(s): {', '.join(sorted(unknown))}. "
              "Run with --list to see them.")
        return 2

    steps = [s for s in STEPS if s[0] not in skip]

    t0 = time.time()
    for i, (key, name, cmd) in enumerate(steps, 1):
        print(f"\n=== [{i}/{len(steps)}] {name}: {' '.join(cmd[1:])} ===",
              flush=True)
        t = time.time()
        rc = subprocess.run(cmd, cwd=ROOT).returncode
        if rc != 0:
            print(f"\nFAILED at step {i} ({name}, exit {rc}) - later steps "
                  "not run. Fix and re-run; every step is idempotent "
                  f"(or skip it: --skip {key}).")
            return rc
        print(f"=== {name} done in {time.time() - t:.0f}s ===", flush=True)

    print(f"\nAll {len(steps)} steps done in {(time.time() - t0) / 60:.1f} min.")
    print("\nStill to do by hand:")
    for line in FOLLOW_UPS:
        print(f"  {line}")
    _polymarket_reminder()
    return 0


def _polymarket_reminder() -> None:
    """Name the races missing from the Polymarket backfill.

    That backfill needs a VPN, so it cannot be a step in this chain — it would
    fail the run every time the VPN is off. Instead the chain just says what
    is outstanding, which is the whole "don't forget" mechanism: it costs
    nothing when there is nothing to do, and it reads only the CSV, so it
    never touches the network.

    Not urgent the way the Kalshi step is - Polymarket keeps resolved markets
    indefinitely - but its RESOLUTION decays with age (hourly while recent,
    12-hourly once old), so sooner is still better.
    """
    try:
        from f1lib.polymarket import missing_events
        gaps = missing_events(Path("data/odds_snapshots.csv"))
    except Exception:
        return
    if not gaps:
        return
    print(f"\n  polymarket    {len(gaps)} race(s) not yet backfilled "
          f"({', '.join(gaps[:3])}{'...' if len(gaps) > 3 else ''})")
    print("                needs the VPN on (non-French exit), then:")
    print("                  .venv\\Scripts\\python scripts\\fetch_odds.py "
          "--source polymarket")
    print("                resumable - it picks up exactly what is missing")


if __name__ == "__main__":
    raise SystemExit(main())
