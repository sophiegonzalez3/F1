"""Build the weekend-decomposition table -> data/weekend_decomp.csv.

One row per (season, round, event, team): actual points minus the pace-model
expectation, split into quali / start / pit crew / SC luck / incidents /
on-track. All the mechanics live in f1lib/weekend_decomp.py — this script just
walks every cached race and writes the table the RACE tab reads.

Only races whose laps are cached can be decomposed (lap-1 order, pit-stop
track status and position value all come from the lap data), so coverage
equals the race archive's.

Usage
-----
    python scripts/compute_weekend_decomp.py                 # every cached season
    python scripts/compute_weekend_decomp.py --season 2026
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd

from f1lib.weekend_decomp import DECOMP_PATH, decompose_event

SESSIONS_DIR = Path("data/sessions")


def cached_races() -> list[tuple[int, str]]:
    """(season, event) for every race with cached laps, in calendar order.

    Cache filenames are `_sanitize`d (non-ASCII → "_"), so the event name
    cannot be read back off the filename directly — "São Paulo" becomes
    "S_o_Paulo" and a naive underscore→space inverse never matches the
    archive again. Resolve each filename against the results archive's real
    event names through the same sanitizer instead."""
    from f1lib.data_loader import _sanitize

    res = pd.read_parquet("data/historical_results/race_results_all.parquet")
    names = {(int(s), _sanitize(e)): str(e)
             for s, e in res[["season", "event_name"]]
             .drop_duplicates().itertuples(index=False)}
    out = []
    for p in sorted(SESSIONS_DIR.glob("*__Race__laps.parquet")):
        parts = p.name.split("__")
        if len(parts) < 3:
            continue
        try:
            season = int(parts[0])
        except ValueError:
            continue
        event = names.get((season, parts[1]))
        if event is None:                       # not in the archive (yet)
            event = parts[1].replace("_", " ")
        out.append((season, event))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None)
    args = ap.parse_args()

    races = cached_races()
    if args.season:
        races = [r for r in races if r[0] == args.season]
    if not races:
        print("No cached races found.")
        return 1

    # One model + forecaster across all events: both cache their tables.
    from f1lib.pace_model import PaceModel
    from f1lib.race_forecast import RaceForecaster
    model, rf = PaceModel(), RaceForecaster()

    frames = []
    for season, event in races:
        try:
            df = decompose_event(season, event, model=model, forecaster=rf)
        except Exception as exc:
            print(f"  [{season} {event}] failed: {exc}")
            continue
        if df.empty:
            print(f"  [{season} {event}] skipped (no pace table / ratings)")
            continue
        check = (df["exp_points"] + df[list(
            ("d_quali", "d_start", "d_pit", "d_sc", "d_incidents",
             "d_ontrack"))].sum(axis=1) - df["actual_points"]).abs().max()
        print(f"  [{season} {event}] {len(df)} teams "
              f"(residual closure {check:.3f} pts)")
        frames.append(df)
    if not frames:
        print("Nothing built.")
        return 1
    out = pd.concat(frames, ignore_index=True).sort_values(
        ["season", "round", "team"])
    out.to_csv(DECOMP_PATH, index=False)
    print(f"\nWrote {len(out)} rows -> {DECOMP_PATH} "
          f"({out['season'].nunique()} seasons, "
          f"{out.groupby(['season', 'round']).ngroups} events)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
