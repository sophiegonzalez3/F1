"""Scan the cached session archive for micro-mistakes → data/mistakes_all.parquet.

For every cached session with full telemetry (data/sessions/*__telemetry.parquet)
this runs the per-corner mistake detector in f1lib/mistakes.py and writes one
parquet per session to data/mistakes/, then consolidates everything into

    data/mistakes_all.parquet           per (season, meeting, session, driver,
                                        corner): laps, mistake counts by type,
                                        time lost vs own median, TL deletions
    data/mistakes_pressure_all.parquet  per (season, meeting, driver): mistake
                                        rates with/without a car within 1.5 s
                                        behind (races only)

Re-run after fetching a new event (like compute_race_stats.py). Already-
computed sessions are skipped unless --force. Sessions whose circuit has no
cached track map (no corner geometry) are skipped with a warning — fetch the
map once via the TRACK tab, or any telemetry view of that circuit.

Usage:  python compute_mistakes.py [--force] [--season 2025] [--limit N]
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from f1lib.circuits import circuit_id

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

from f1lib.mistakes import (
    aggregate_mistakes, corner_features_for_session, load_corner_fractions,
    pressure_table, track_limit_deletions,
)
from f1lib.processing import clean_and_enrich_laps, flag_dirty_air

logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")

SESSIONS_DIR = Path("data/sessions")
OUT_DIR = Path("data/mistakes")
OUT_ALL = Path("data/mistakes_all.parquet")
OUT_PRESSURE = Path("data/mistakes_pressure_all.parquet")
HIST_RACE = Path("data/historical_results/race_results_all.parquet")


def _circuit_key_map() -> dict[str, str]:
    """event_name → circuit_key from the historical results archive.

    Kept for the legacy `circuit_key` column only. It maps a name to ONE key
    for all time, which is precisely why it must not be used to decide which
    physical track a session belongs to — see `circuit_id` below.
    """
    if not HIST_RACE.exists():
        return {}
    r = pd.read_parquet(HIST_RACE, columns=["event_name", "circuit_key"])
    return (r.dropna().drop_duplicates("event_name")
            .set_index("event_name")["circuit_key"].to_dict())


def _discover() -> list[dict]:
    """Every cached session that has BOTH laps and telemetry parquets."""
    out = []
    for tp in sorted(SESSIONS_DIR.glob("*__telemetry.parquet")):
        base = tp.name[: -len("__telemetry.parquet")]
        lp = SESSIONS_DIR / f"{base}__laps.parquet"
        if not lp.exists():
            continue
        season_s, meeting_s, session_s = base.split("__", 2)
        out.append({"base": base, "laps": lp, "tel": tp,
                    "season": int(season_s),
                    "session": session_s.replace("_", " ")})
    return out


def _process_one(item: dict, ck_map: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_parquet(item["laps"])
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame()
    meeting = str(raw["meeting"].iloc[0])
    season = item["season"]
    laps = clean_and_enrich_laps(raw)
    laps = flag_dirty_air(laps)

    fracs = load_corner_fractions(meeting, season)
    if fracs.empty:
        print(f"  !! no track map for {meeting} — skipped", flush=True)
        return pd.DataFrame(), pd.DataFrame()

    tel = pd.read_parquet(
        item["tel"],
        columns=["timestamp", "Speed", "Throttle", "Brake", "DriverNo"])
    feats = corner_features_for_session(laps, tel, fracs)
    agg, lap_events = aggregate_mistakes(feats, laps)
    if agg.empty:
        return pd.DataFrame(), pd.DataFrame()

    tl = track_limit_deletions(laps)
    if not tl.empty:
        agg = agg.merge(tl, on=["Driver_Short", "corner"], how="outer")
        agg["tl_deletions"] = agg["tl_deletions"].fillna(0).astype(int)
        # TL-only corners (no telemetry row) still need identity columns
        agg["Team"] = agg.groupby("Driver_Short")["Team"].transform(
            lambda s: s.ffill().bfill())
        for c in ("n_laps", "n_slow", "n_lift", "n_brake_reapp", "n_mistakes"):
            agg[c] = agg[c].fillna(0).astype(int)
        agg["time_lost_s"] = agg["time_lost_s"].fillna(0.0)
    else:
        agg["tl_deletions"] = 0

    agg.insert(0, "season", season)
    agg.insert(1, "meeting", meeting)
    agg.insert(2, "circuit_key", ck_map.get(meeting, ""))
    # The identity that survives a race changing venue. circuit_key above is
    # the slugified event name and cannot separate the 2026 Madrid "Spanish
    # Grand Prix" from Barcelona's, nor the Sepang-hosted "Bahrain Grand Prix"
    # from Sakhir's — corner numbers would be pooled across unrelated tracks.
    agg.insert(3, "circuit_id", circuit_id(meeting, season))
    agg.insert(4, "session", item["session"])

    press = pd.DataFrame()
    if item["session"] in ("Race", "Sprint"):
        press = pressure_table(laps, lap_events)
        if not press.empty:
            press.insert(0, "season", season)
            press.insert(1, "meeting", meeting)
            press.insert(2, "circuit_key", ck_map.get(meeting, ""))
            press.insert(3, "circuit_id", circuit_id(meeting, season))
            press.insert(4, "session", item["session"])
    return agg, press


def _consolidate() -> None:
    aggs, press = [], []
    for p in sorted(OUT_DIR.glob("*__corners.parquet")):
        df = pd.read_parquet(p)
        if not df.empty:
            aggs.append(df)
    for p in sorted(OUT_DIR.glob("*__pressure.parquet")):
        df = pd.read_parquet(p)
        if not df.empty:
            press.append(df)
    if aggs:
        pd.concat(aggs, ignore_index=True).to_parquet(OUT_ALL, index=False)
        print(f"wrote {OUT_ALL}  ({sum(len(a) for a in aggs):,} rows)")
    if press:
        pd.concat(press, ignore_index=True).to_parquet(OUT_PRESSURE, index=False)
        print(f"wrote {OUT_PRESSURE}  ({sum(len(p) for p in press):,} rows)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="recompute sessions that already have an output file")
    ap.add_argument("--season", type=int, default=None,
                    help="only process this season")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N sessions (smoke testing)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ck_map = _circuit_key_map()
    items = _discover()
    if args.season:
        items = [i for i in items if i["season"] == args.season]
    print(f"{len(items)} cached sessions with telemetry", flush=True)

    done = 0
    for item in items:
        out_c = OUT_DIR / f"{item['base']}__corners.parquet"
        out_p = OUT_DIR / f"{item['base']}__pressure.parquet"
        if out_c.exists() and not args.force:
            continue
        t0 = time.perf_counter()
        try:
            agg, press = _process_one(item, ck_map)
        except Exception as exc:
            print(f"  !! {item['base']}: {exc}", flush=True)
            continue
        if agg.empty:
            # empty marker (schema only) so the session isn't rescanned
            pd.DataFrame(columns=["season", "meeting", "circuit_key", "session",
                                  "Driver_Short", "Team", "corner"]
                         ).to_parquet(out_c, index=False)
            continue
        agg.to_parquet(out_c, index=False)
        if not press.empty:
            press.to_parquet(out_p, index=False)
        done += 1
        print(f"  {item['base']}: {len(agg)} corner rows, "
              f"{len(press)} pressure rows  ({time.perf_counter()-t0:.1f}s)",
              flush=True)
        if args.limit and done >= args.limit:
            break

    _consolidate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
