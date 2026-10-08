"""Fetch + transcribe a race's team radio — the automated half of /radio-review.

after_race.py runs this for the newest cached race, EARLY in the chain,
because F1 purges the radio mp3s a few weeks after the event (HTTP 403) and
the transcription cannot be redone after that. Whisper (medium.en, CPU) takes
a few minutes for the ~20-40 clips F1 publishes per race.

What stays manual is the REVIEW — correcting name/jargon mishears against the
race context and marking clips reviewed. That needs judgement, so it is the
`/radio-review <Meeting>` skill, which now starts from these transcripts
instead of fetching them.

Exit codes: 0 when the radio is cached (new or already), or when F1 has none
to give (purged, or a race without a published feed) — neither is a fault
of this run. 1 only when the transcription itself failed.

Usage
-----
    python scripts/fetch_radio.py 2026 "Bahrain Grand Prix"
    python scripts/fetch_radio.py --latest
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import logging
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("season", nargs="?", type=int)
    ap.add_argument("meeting", nargs="?")
    ap.add_argument("--latest", action="store_true",
                    help="the newest cached race (f1lib.latest_race)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")
    try:                                   # fastf1 owns its own INFO handler
        import fastf1
        fastf1.set_log_level("WARNING")
    except Exception:
        pass

    if args.latest or not (args.season and args.meeting):
        from f1lib.latest_race import latest_cached_race
        season, meeting, _ = latest_cached_race()
    else:
        season, meeting = args.season, args.meeting

    from f1lib.radio_loader import (load_race_radio, race_radio_available,
                                    radio_cached)
    label = f"{season} {meeting}"
    if radio_cached(season, meeting):
        df = load_race_radio(season, meeting)
        n_rev = int(df["reviewed"].sum())
        print(f"{label}: {len(df)} clips already transcribed, "
              f"{n_rev} reviewed.")
        if n_rev < len(df):
            print(f'  -> review them:  /radio-review {meeting}')
        return 0

    if not race_radio_available(season, meeting):
        print(f"{label}: F1 serves no race radio for this event (purged "
              "upstream, or never published) - nothing to transcribe.")
        return 0

    t0 = time.time()
    try:
        df = load_race_radio(season, meeting)
    except Exception as exc:
        print(f"{label}: transcription FAILED - {type(exc).__name__}: {exc}")
        return 1
    if df.empty:
        print(f"{label}: the radio feed exists but held no clips.")
        return 0
    print(f"{label}: transcribed {len(df)} clips from "
          f"{df['Driver_Short'].nunique()} drivers in {time.time() - t0:.0f}s.")
    print(f'  -> review them:  /radio-review {meeting}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
