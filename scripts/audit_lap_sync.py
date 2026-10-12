"""Audit every cached session for lap-boundary ↔ telemetry-clock drift and
write the correction tables → data/lap_sync_offsets.csv (summary per
driver-session) + data/lap_sync_knots.csv (per-lap knots, corrected drivers).

For each weekend: lap starts (pos sample nearest LapStartTime, laps ≥ 2, no
pit-out laps) of all its cached sessions → consensus start/finish point →
per-driver, per-lap offsets (f1lib/lap_sync.py). `after_m` re-measures the
lap-start distance with the correction applied, so the table proves its own
fix.

Re-run after fetching new sessions (after_race / during_weekend do).

Usage:  python scripts/audit_lap_sync.py [--season 2026] [--meeting "Bahrain Grand Prix"]
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from f1lib import lap_sync  # noqa: E402
from f1lib.data_loader import _sanitize  # noqa: E402

SESSIONS = Path("data/sessions")
TEL_COLS = ["DriverNo", "timestamp", "X", "Y", "Source"]
LAP_COLS = ["DriverNo", "LapNo", "LapStartTime", "PitOut", "meeting", "session", "season"]


def _read(stem: str):
    laps = pd.read_parquet(SESSIONS / f"{stem}__laps.parquet")
    laps = laps[[c for c in LAP_COLS if c in laps.columns]]
    tel = pd.read_parquet(SESSIONS / f"{stem}__telemetry.parquet", columns=TEL_COLS)
    return laps, tel


def _audit_weekend(job) -> tuple[list[pd.DataFrame], list[pd.DataFrame], list[str]]:
    season, stems, meeting_filter = job
    rows, knots, lines = [], [], []
    data, pts = {}, []
    for stem in stems:
        try:
            laps, tel = _read(stem)
        except Exception as exc:
            lines.append(f"  skip {stem}: {exc}")
            continue
        if laps.empty or tel.empty:
            continue
        if meeting_filter and str(laps["meeting"].iloc[0]) != meeting_filter:
            return [], [], []
        data[stem] = (laps, tel)
        pts.append(lap_sync.lap_start_points(laps, tel))
    sf = lap_sync.consensus_sf(pts) if data else None
    if sf is None:
        return [], [], lines
    for stem, (laps, tel) in data.items():
        off, kn = lap_sync.estimate_offsets(laps, tel, sf)
        if off.empty:
            continue
        meeting, session = str(laps["meeting"].iloc[0]), str(laps["session"].iloc[0])
        for df in (off, kn):
            df.insert(0, "stem", stem)
        off.insert(1, "season", season)
        off.insert(2, "meeting", meeting)
        off.insert(3, "session", session)
        off["sf_x"], off["sf_y"] = round(sf[0], 1), round(sf[1], 1)
        rows.append(off)
        knots.append(kn)
        n_fix = int(off["apply"].sum())
        flag = (f"  <- {n_fix} driver(s) shifted "
                f"{off.loc[off['apply'], 'offset_s'].median():+.2f} s" if n_fix else "")
        deg = float(off["degraded_share"].median())
        if deg > 0.3:
            flag += f"  !! pos feed missing or stair-stepped on {deg:.0%} of laps (offset unmeasurable there)"
        lines.append(f"{season} {meeting:28s} {session:18s} median lap start "
                     f"{off['before_m'].median():6.1f} m -> "
                     f"{off['after_m'].median():6.1f} m{flag}")
    return rows, knots, lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--meeting")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    weekends: dict[tuple[str, str], list[str]] = defaultdict(list)
    for tp in sorted(SESSIONS.glob("*__telemetry.parquet")):
        stem = tp.name[: -len("__telemetry.parquet")]
        if not (SESSIONS / f"{stem}__laps.parquet").exists():
            continue
        season, ev, _ = stem.split("__", 2)
        if args.season and int(season) != args.season:
            continue
        if args.meeting and ev != _sanitize(args.meeting):
            continue
        weekends[(season, ev)].append(stem)

    jobs = [(season, stems, args.meeting) for (season, _), stems in weekends.items()]
    rows, knots = [], []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for frames, kns, lines in ex.map(_audit_weekend, jobs):
            rows.extend(frames)
            knots.extend(kns)
            for ln in lines:
                print(ln, flush=True)

    out = pd.concat(rows, ignore_index=True)
    kn = pd.concat([k for k in knots if not k.empty] or
                   [pd.DataFrame(columns=["stem", "DriverNo", "t_tel", "offset_s"])],
                   ignore_index=True)
    if args.season or args.meeting:
        # partial run: replace only the audited sessions
        done = set(out["stem"])
        for path, cur in ((lap_sync.OFFSETS_CSV, "out"), (lap_sync.KNOTS_CSV, "kn")):
            if path.exists():
                old = pd.read_csv(path, dtype={"DriverNo": str, "season": str})
                old = old[~old["stem"].isin(done)]
                if cur == "out":
                    out = pd.concat([old, out], ignore_index=True)
                else:
                    kn = pd.concat([old, kn], ignore_index=True)
    out = out.sort_values(["stem", "DriverNo"])
    out.to_csv(lap_sync.OFFSETS_CSV, index=False)
    kn.sort_values(["stem", "DriverNo", "t_tel"]).to_csv(lap_sync.KNOTS_CSV, index=False)
    fixed = out[out["apply"]]
    print(f"\nwrote {lap_sync.OFFSETS_CSV}: {len(out)} driver-sessions, "
          f"{len(fixed)} corrected in "
          f"{fixed['stem'].nunique()} session(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
