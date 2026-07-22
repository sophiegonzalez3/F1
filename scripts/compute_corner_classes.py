"""Derive GLOBAL corner-speed-class thresholds from a full season.

The TELEMETRY/overview "Cornering Speed by Track Region" card classifies every
corner as slow / medium / fast. For the metric to be comparable ACROSS events
(so a car being quicker in slow corners than at the previous round means a real
gain — upgrade, balance, driver — and not a shifted definition), the km/h
thresholds that separate the three classes must be FIXED, derived once from a
whole season rather than re-tertiled per track.

Method: for every cached track map of the season, take the fastest-lap speed
trace and each numbered corner's position, and read the apex (minimum) speed in
a short window around the corner. Pool every corner across every event, then
split that distribution into thirds — the 33.3rd and 66.7th percentiles become
the slow|medium and medium|fast boundaries. A track with no slow corners (Monza)
simply contributes few points to the low end; the thresholds stay put.

Output: data/corner_speed_classes.json (thresholds + provenance). tabs/
corner_speed.py reads it, with a baked-in fallback if the file is absent.

Usage
-----
    python scripts/compute_corner_classes.py            # season 2025 (default)
    python scripts/compute_corner_classes.py --season 2025 --verbose
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import glob
import json
import re
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

TRACK_MAPS_DIR = "data/track_maps"

APEX_WINDOW_M = 40.0        # ± metres around a corner marker to search for its apex
OUT_PATH = Path("data/corner_speed_classes.json")


def corner_apex_speeds(line: pd.DataFrame, corners: pd.DataFrame,
                       win_m: float = APEX_WINDOW_M) -> list[float]:
    """Apex (minimum) speed at each numbered corner of one circuit, from the
    cached fastest-lap line. The corner marker is matched to the nearest line
    point by X/Y, then the lowest speed within ``win_m`` of it (measured along
    the lap) is that corner's characteristic apex speed."""
    if (line is None or corners is None or line.empty or corners.empty
            or not {"X", "Y", "Speed"}.issubset(line.columns)
            or not {"X", "Y"}.issubset(corners.columns)):
        return []
    lx = line["X"].to_numpy(float)
    ly = line["Y"].to_numpy(float)
    sp = pd.to_numeric(line["Speed"], errors="coerce").to_numpy(float)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(lx), np.diff(ly)))])
    out = []
    for _, c in corners.iterrows():
        i = int(np.argmin((lx - c["X"]) ** 2 + (ly - c["Y"]) ** 2))
        m = np.abs(cum - cum[i]) <= win_m
        if m.any():
            v = np.nanmin(sp[m])
            if np.isfinite(v):
                out.append(float(v))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    files = sorted(glob.glob(str(Path(TRACK_MAPS_DIR) / f"{args.season}_*_Q.parquet")))
    if not files:
        print(f"No cached {args.season} track maps found under {TRACK_MAPS_DIR}.")
        return 1

    speeds, per_event = [], {}
    for f in files:
        base = f[:-len(".parquet")]
        cpath = base + "_corners.parquet"
        if not _os.path.exists(cpath):
            continue
        line = pd.read_parquet(f)
        corners = pd.read_parquet(cpath)
        apex = corner_apex_speeds(line, corners)
        if apex:
            name = re.sub(r"^\d+_|_Q$", "", _os.path.basename(base))
            per_event[name] = apex
            speeds += apex

    if len(speeds) < 30:
        print(f"Only {len(speeds)} corners found — too few to derive thresholds.")
        return 1

    a = np.array(speeds)
    t_slow = float(np.percentile(a, 100 / 3))
    t_fast = float(np.percentile(a, 200 / 3))

    payload = {
        "season": args.season,
        "slow_max_kmh": round(t_slow, 1),
        "fast_min_kmh": round(t_fast, 1),
        "provenance": {
            "generated": date.today().isoformat(),
            "events": len(per_event),
            "corners": int(a.size),
            "method": "tertiles of per-corner apex (min) speed on the fastest "
                      f"cached Q lap, window ±{APEX_WINDOW_M:.0f} m",
            "percentiles_kmh": {p: round(float(np.percentile(a, p)), 1)
                                for p in (10, 25, 50, 75, 90)},
        },
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2))

    print(f"Wrote {OUT_PATH}")
    print(f"  {len(per_event)} events, {a.size} corners")
    print(f"  slow < {t_slow:.0f} km/h  ·  medium  ·  {t_fast:.0f} km/h < fast")
    for lbl, lo, hi in [("slow", 0, t_slow), ("medium", t_slow, t_fast), ("fast", t_fast, 1e9)]:
        n = int(((a >= lo) & (a < hi)).sum())
        print(f"    {lbl:<7} {n:>3} corners ({100 * n / a.size:.0f}%)")
    if args.verbose:
        for name, ap_ in sorted(per_event.items()):
            print(f"    {name:<32} {len(ap_):>2} corners  "
                  f"apex {min(ap_):.0f}–{max(ap_):.0f} km/h")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
