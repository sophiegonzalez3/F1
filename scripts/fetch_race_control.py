"""Backfill race-control messages for races held in the laps-only lite store.

Why this exists
---------------
`f1lib.processing.flag_perturbed_laps` takes three signals. Two of them ride
along in the laps frame (the per-lap TrackStatus column and sector anomalies);
the third, race-control messages, is a separate table. Without it the flagger
still catches safety cars and VSCs, but it misses SHORT SECTOR YELLOWS — the
ones that never reach the per-lap status.

`scripts/fetch_practice_laps.py` writes laps and weather only, so every
session backfilled into `data/sessions_lite/` is missing that third signal.

A CORRECTION, recorded because the wrong version of this story was briefly
believed and acted on. This script was written to explain why 2022 scored so
badly on long-run pace (z_sd 2.62 at the prior against 0.94-1.50 for
2023-26). Missing race control was NOT the cause, and two measurements say so:

  * the race-control signal had never fired for ANY season. `_normalize_rcm`
    fell through to pd.to_numeric on FastF1's absolute-datetime Time column
    and produced nanoseconds since the epoch, which never matched a lap
    window. Fixed in f1lib/processing.py — but it means 2023-26 were not
    getting the signal either, so it cannot be what separated them from 2022.
  * 2022's long-run error is ONE EVENT. Monaco 2022 scores mean|z| 10.6;
    the season's MEDIAN event scores 0.44, which is entirely normal. Monaco
    2022 ran 44% of its laps in rain. The season also had Japan (98% wet),
    Hungary (28%) and Singapore (18%) — an unusual concentration.

So 2022 is a WEATHER outlier, not a data defect, and the fat tail is the one
already documented under "REJECTED: widening the variance for rain" in
f1lib/pace_model.py.

This script is still worth having: race-control messages are genuinely absent
from the lite store, the signal genuinely works now, and blue flags and
track-limits detection depend on the same fix. What it is NOT is a fix for
2022's pace numbers.

CAVEAT for lite-store sessions: `LapStartDate` is entirely null there
(FastF1 does not populate it when a session is loaded without messages), and
the session-start offset is derived from it. So RCM timing signals stay
inactive for lite sessions even once these files exist — they only become
useful if the laps are re-fetched with messages=True.

This fetches ONLY the messages — `load(laps=False, telemetry=False,
weather=False, messages=True)` — so it costs a few API calls per session and
no telemetry. That is the whole reason the affected races were never simply
re-fetched into the full cache: the full path pulls telemetry, which is
gigabytes per season and is why the lite store exists at all.

Usage
-----
    python scripts/fetch_race_control.py                  # every lite race missing RCM
    python scripts/fetch_race_control.py --season 2022    # one season
    python scripts/fetch_race_control.py --dry-run
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import fastf1

import f1lib.data_loader as dl
from f1lib.config import SESSIONS_DIR, SESSIONS_LITE_DIR

LITE = Path(SESSIONS_LITE_DIR)
FULL = Path(SESSIONS_DIR)


def pending(season: int | None) -> list[tuple[int, str, str]]:
    """(season, meeting, session) for lite-store sessions with laps but no
    race-control table. Skips anything the full cache already covers."""
    out = []
    for p in sorted(LITE.glob("*__laps.parquet")):
        key = p.name.replace("__laps.parquet", "")
        try:
            season_s, meeting_s, session_s = key.split("__", 2)
        except ValueError:
            continue
        if not season_s.isdigit():
            continue
        if season is not None and int(season_s) != season:
            continue
        if (FULL / f"{key}__race_control.parquet").exists():
            continue          # the full cache already has it
        if (LITE / f"{key}__race_control.parquet").exists():
            continue          # already backfilled
        out.append((int(season_s), meeting_s.replace("_", " "),
                    session_s.replace("_", " ")))
    return out


def fetch_one(season: int, meeting: str, session: str) -> bool:
    key = dl._session_key(str(season), meeting, session)
    sess_name = dl._session_name(str(season), meeting, session)
    ff1_sess = fastf1.get_session(season, meeting, dl._ff1_session_id(session))
    # messages ONLY — no laps, no telemetry, no weather
    ff1_sess.load(laps=False, telemetry=False, weather=False, messages=True)
    rcm = dl._safe_attr(ff1_sess, "race_control_messages")
    if rcm.empty:
        print(f"  [empty]  {key} — no race-control messages returned",
              flush=True)
        return False
    dl._tag(rcm, session, str(season), meeting, sess_name)
    dl._save_df(rcm, LITE / f"{key}__race_control.parquet")
    print(f"  [saved]  {key} — {len(rcm):,} messages", flush=True)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    todo = pending(args.season)
    if not todo:
        print("Nothing to fetch — every lite session already has race control.")
        return 0
    print(f"{len(todo)} session(s) missing race control:")
    for s, m, sess in todo:
        print(f"  {s}  {m}  {sess}")
    if args.dry_run:
        return 0

    LITE.mkdir(parents=True, exist_ok=True)
    ok = failed = 0
    for season, meeting, session in todo:
        for attempt in range(3):
            try:
                ok += bool(fetch_one(season, meeting, session))
                break
            except Exception as exc:
                # FastF1 enforces 500 API calls/h; back off rather than die
                # halfway through a backfill (same handling as
                # fetch_practice_laps.py).
                if "500 calls" in str(exc) or "RateLimit" in type(exc).__name__:
                    print("  [rate-limited] sleeping 15 min…", flush=True)
                    time.sleep(900)
                    continue
                if attempt == 2:
                    print(f"  [FAILED] {season} {meeting} {session}: "
                          f"{type(exc).__name__} {exc}", flush=True)
                    failed += 1
                    break
                time.sleep(5)
        time.sleep(1.0)                        # be polite to the API
    print(f"\nDone: {ok} saved, {failed} failed.")
    print("Now rebuild the pace table with a FULL run — NOT --season, which "
          "writes only that season and clobbers the consolidated CSV:")
    print("    python scripts/compute_team_pace.py")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
