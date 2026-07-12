"""
F1 Dashboard – Team-Radio Review Helper
=======================================
Companion CLI to radio_loader.py for the transcript review workflow
(see .claude/skills/radio-review/SKILL.md for the full process).

Commands
--------
python scripts/radio_review.py dump  <season> <meeting>
    Print every clip (filename | clock | driver | transcript) followed by a
    race-context brief built from the local session data (results, pit stops,
    filtered race-control messages). One output = everything a reviewer needs
    to cross-check transcripts against what actually happened.

python scripts/radio_review.py apply <season> <meeting> <corrections.json>
    Apply hand-review corrections and mark ALL clips of the meeting reviewed.
    The JSON maps mp3 filename -> corrected transcript, e.g.
        {"ANT_12_20260705_161020.mp3": "No Bono, the suspension is broken."}
    Only `Transcript` (working copy) is edited; `Transcript_raw` stays the
    verbatim whisper output. reviewed=True means "checked", not "edited" —
    unlisted clips are marked reviewed as-is.
"""

from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import json
import sys
from pathlib import Path

import pandas as pd

from f1lib.config import SESSIONS_DIR, PITSTOPS_DIR
from f1lib.radio_loader import _key, _parquet_path

# race-control noise filter: keep only messages a reviewer can anchor on
_RC_KEEP = ("PENALTY|INVESTIGAT|SAFETY|VIRTUAL|RED FLAG|DELETED|INCIDENT|"
            "RETIRE|STOPPED|PUNCTURE|DEBRIS|RAIN|WET")


def _radio_df(season, meeting) -> pd.DataFrame:
    pq = _parquet_path(season, meeting)
    if not pq.exists():
        sys.exit(f"No radio cache for {meeting} {season} — run "
                 f"`python -m f1lib.radio_loader {season} \"{meeting}\"` first.")
    return pd.read_parquet(pq)


def dump(season, meeting) -> None:
    df = _radio_df(season, meeting)
    print(f"===== {meeting} {season} — {len(df)} clips =====")
    for _, r in df.iterrows():
        fname = r["Mp3"].rsplit("/", 1)[-1]
        mark = "✓" if r.get("reviewed") else "•"
        print(f"{mark} {fname} | {r['Clock']} {r['Driver_Short']}: {r['Transcript']}")

    key = _key(season, meeting)
    res_p = Path(SESSIONS_DIR) / f"{key}__results.parquet"
    if res_p.exists():
        res = pd.read_parquet(res_p)
        cols = [c for c in ("Abbreviation", "TeamName", "ClassifiedPosition",
                            "GridPosition", "Status") if c in res.columns]
        print("\n--- Results ---")
        print(res[cols].to_string(index=False))

    pit_p = Path(PITSTOPS_DIR) / f"{key}__pitstops.parquet"
    if pit_p.exists():
        pit = pd.read_parquet(pit_p)
        cols = [c for c in ("Driver_Short", "LapNo", "StopNo",
                            "StationaryTime_s", "Utc") if c in pit.columns]
        print("\n--- Pit stops (Utc ≈ clip Clock for box calls) ---")
        print(pit[cols].to_string(index=False))

    rc_p = Path(SESSIONS_DIR) / f"{key}__race_control.parquet"
    if rc_p.exists():
        rc = pd.read_parquet(rc_p)
        m = rc["Message"].str.contains(_RC_KEEP, case=False, na=False)
        cols = [c for c in ("Lap", "Message") if c in rc.columns]
        print("\n--- Race control (filtered) ---")
        print(rc.loc[m, cols].to_string(index=False))


def apply(season, meeting, corrections_file) -> None:
    corrections: dict[str, str] = json.loads(
        Path(corrections_file).read_text(encoding="utf-8"))
    pq = _parquet_path(season, meeting)
    df = _radio_df(season, meeting)
    fnames = df["Mp3"].str.rsplit("/", n=1).str[-1]
    unknown = set(corrections) - set(fnames)
    if unknown:
        sys.exit(f"Corrections reference unknown clips: {sorted(unknown)}")
    hits = fnames.map(corrections)
    df.loc[hits.notna(), "Transcript"] = hits[hits.notna()]
    df["reviewed"] = True
    df.to_parquet(pq, index=False)
    print(f"{meeting} {season}: {hits.notna().sum()} corrected, "
          f"{len(df)} clips marked reviewed")


if __name__ == "__main__":
    # Windows consoles default to cp1252, which can't print ✓ or transcript
    # punctuation — force UTF-8 rather than crash mid-dump.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 4 or sys.argv[1] not in ("dump", "apply"):
        sys.exit(__doc__)
    cmd, season, meeting = sys.argv[1], sys.argv[2], sys.argv[3]
    if cmd == "dump":
        dump(season, meeting)
    else:
        if len(sys.argv) < 5:
            sys.exit("apply needs: <season> <meeting> <corrections.json>")
        apply(season, meeting, sys.argv[4])
