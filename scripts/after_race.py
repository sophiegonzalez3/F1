"""Run the whole post-race data refresh in one go.

Prerequisite: the race weekend's sessions are cached under data/sessions/
(load the event in the app's Data tab first — this script computes, it does
not fetch sessions).

Steps, in dependency order:

  1. f1lib.fetch_historical_results    results/quali/sprint archive + standings
  2. scripts/compute_team_pace.py      per-event pace table (needs the archive)
  3. scripts/compute_race_stats.py     SC rates, overtakes, pit league, ...
  4. scripts/compute_atr.py            ATR sliding scale (needs standings)
  5. compute_mistakes.py               micro-mistake archive (telemetry, slow)

Stops at the first failing step. Not covered here (interactive / optional):
the `radio-review` skill, and `build_quali_scenes.py <season> "<Meeting>"`.

Usage
-----
    .venv/Scripts/python scripts/after_race.py
    .venv/Scripts/python scripts/after_race.py --skip-mistakes   # fast pass
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STEPS: list[tuple[str, list[str]]] = [
    ("results archive",   [sys.executable, "-m", "f1lib.fetch_historical_results"]),
    ("team pace table",   [sys.executable, "scripts/compute_team_pace.py"]),
    ("race stats",        [sys.executable, "scripts/compute_race_stats.py"]),
    ("ATR sliding scale", [sys.executable, "scripts/compute_atr.py"]),
    ("micro-mistakes",    [sys.executable, "compute_mistakes.py"]),
]


def main() -> int:
    steps = STEPS
    if "--skip-mistakes" in sys.argv:
        steps = [s for s in steps if s[0] != "micro-mistakes"]

    t0 = time.time()
    for i, (name, cmd) in enumerate(steps, 1):
        print(f"\n=== [{i}/{len(steps)}] {name}: {' '.join(cmd[1:])} ===",
              flush=True)
        t = time.time()
        rc = subprocess.run(cmd, cwd=ROOT).returncode
        if rc != 0:
            print(f"\nFAILED at step {i} ({name}, exit {rc}) — later steps "
                  "not run. Fix and re-run; every step is idempotent.")
            return rc
        print(f"=== {name} done in {time.time() - t:.0f}s ===", flush=True)

    print(f"\nAll {len(steps)} steps done in {(time.time() - t0) / 60:.1f} min.")
    print("Remember (not automated): the radio-review skill, and optionally")
    print('  build_quali_scenes.py <season> "<Meeting>" for the 3D replay.')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
