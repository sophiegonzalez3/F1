"""Audit every cached session's telemetry feed for stair-stepped (degraded)
laps → data/telemetry_quality.csv (per session) + data/telemetry_degraded_laps.csv
(per degraded driver-lap). See f1lib/telemetry_quality.py.

Run after audit_lap_sync.py: laps are judged on the lap-synced clock.

Usage:  python scripts/audit_telemetry_quality.py [--season 2026] [--meeting "Hungarian Grand Prix"]
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from f1lib import telemetry_quality as tq  # noqa: E402
from f1lib.data_loader import _sanitize  # noqa: E402
from f1lib.lap_sync import read_telemetry  # noqa: E402

SESSIONS = Path("data/sessions")
TEL_COLS = ["DriverNo", "timestamp", "X", "Y", "Speed", "RPM", "Source"]
DEG_COLS = ["DriverNo", "LapNo", "pos_cov", "pos_moving", "car_cov", "car_moving",
            "pos_bad", "car_bad"]


def _audit(stem: str):
    laps = pd.read_parquet(SESSIONS / f"{stem}__laps.parquet")
    if laps.empty:
        return None, None
    tel = read_telemetry(SESSIONS / f"{stem}__telemetry.parquet", columns=TEL_COLS)
    q = tq.lap_quality(laps, tel)
    season, _, _ = stem.split("__", 2)
    meeting, session = str(laps["meeting"].iloc[0]), str(laps["session"].iloc[0])
    summ = {"stem": stem, "season": season, "meeting": meeting, "session": session,
            "n_laps": len(q)}
    for c in ("pos_cov", "pos_moving", "car_cov", "car_moving"):
        summ[f"{c}_med"] = round(float(q[c].median()), 3)
    summ.update({"n_pos_bad": int(q["pos_bad"].sum()), "n_car_bad": int(q["car_bad"].sum()),
                 "n_degraded": int(q["degraded"].sum()),
                 "share_degraded": round(float(q["degraded"].mean()), 3) if len(q) else 0.0})
    bad = q[q["degraded"]].assign(stem=stem)
    return summ, bad[["stem", *DEG_COLS]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--meeting")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    stems = []
    for tp in sorted(SESSIONS.glob("*__telemetry.parquet")):
        stem = tp.name[: -len("__telemetry.parquet")]
        season, ev, _ = stem.split("__", 2)
        if not (SESSIONS / f"{stem}__laps.parquet").exists():
            continue
        if args.season and int(season) != args.season:
            continue
        if args.meeting and ev != _sanitize(args.meeting):
            continue
        stems.append(stem)

    summ, bad = [], []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for s, b in ex.map(_audit, stems):
            if s is None:
                continue
            summ.append(s)
            if not b.empty:
                bad.append(b)
            if s["n_degraded"]:
                print(f"{s['season']} {s['meeting']:28s} {s['session']:18s} "
                      f"{s['n_degraded']:4d}/{s['n_laps']} laps degraded "
                      f"(pos bad {s['n_pos_bad']}, car bad {s['n_car_bad']})",
                      flush=True)

    out = pd.DataFrame(summ)
    deg = (pd.concat(bad, ignore_index=True) if bad else
           pd.DataFrame(columns=["stem", *DEG_COLS]))
    if args.season or args.meeting:
        done = set(out["stem"])
        for path in (tq.SESSION_CSV, tq.DEGRADED_CSV):
            if path.exists():
                old = pd.read_csv(path, dtype={"DriverNo": str, "season": str})
                old = old[~old["stem"].isin(done)]
                if path == tq.SESSION_CSV:
                    out = pd.concat([old, out], ignore_index=True)
                elif not old.empty:
                    deg = pd.concat([old, deg], ignore_index=True)
    out.sort_values("stem").to_csv(tq.SESSION_CSV, index=False)
    deg.sort_values(["stem", "DriverNo", "LapNo"]).to_csv(tq.DEGRADED_CSV, index=False)
    print(f"\nwrote {tq.SESSION_CSV}: {len(out)} sessions, "
          f"{int((out['n_degraded'] > 0).sum())} with degraded laps; "
          f"{len(deg)} degraded driver-laps -> {tq.DEGRADED_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
