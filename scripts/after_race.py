"""Run the whole post-race data refresh in one go.

Prerequisite: the race weekend's sessions are cached under data/sessions/
(run `scripts/during_weekend.py`, or load the event in the app's Data tab —
this script computes from the cache, it does not fetch sessions).

Steps, in dependency order:

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
]

FOLLOW_UPS = [
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
