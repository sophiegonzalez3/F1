"""Backfill the previous season's Race for every cached meeting.

The RACE tab falls back to season-1 when the loaded season's race hasn't
happened yet (``_resolve_race_data``), and year-on-year comparisons at a
circuit need last year's laps. This pre-fetches those races in bulk so the
fallback works offline instead of triggering a slow FastF1 fetch the first
time each tab is opened.

For every distinct (season, meeting) with any cached session, it fetches
``(season-1, meeting, "Race")`` through the normal ``data_loader`` path, so
the result lands in data/sessions/ exactly like any other cached session.

Meeting names can shift between seasons (FastF1 fuzzy-matches, which
usually resolves it); failures are reported at the end, not fatal.

Usage
-----
    python scripts/fetch_previous_races.py             # backfill season-1 races
    python scripts/fetch_previous_races.py --dry-run   # only list what would be fetched
    python scripts/fetch_previous_races.py --sessions "Race,Qualifying"
                                               # also backfill other sessions
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import sys
import warnings

warnings.filterwarnings("ignore")

import f1lib.data_loader as dl

dry_run = "--dry-run" in sys.argv
sessions_to_fetch = ["Race"]
if "--sessions" in sys.argv:
    raw = sys.argv[sys.argv.index("--sessions") + 1]
    sessions_to_fetch = [s.strip() for s in raw.split(",") if s.strip()]


def main() -> int:
    cached = dl.list_cached_sessions()
    if not cached:
        print("No cached sessions found under data/sessions/ — nothing to do.")
        return 0

    meetings = sorted({(int(s["season"]), str(s["meeting"])) for s in cached})
    todo = [
        (season - 1, meeting, sess)
        for season, meeting in meetings
        for sess in sessions_to_fetch
        if not dl.is_cached(str(season - 1), meeting, sess)
    ]
    print(f"{len(meetings)} cached meeting(s); {len(todo)} previous-season "
          f"session(s) to fetch ({', '.join(sessions_to_fetch)})\n", flush=True)

    if dry_run:
        for season, meeting, sess in todo:
            print(f"  would fetch {season} {meeting} – {sess}")
        return 0

    ok, fail = [], []
    for i, (season, meeting, sess) in enumerate(todo, 1):
        label = f"{season} {meeting} – {sess}"
        print(f"[{i}/{len(todo)}] {label} …", flush=True)
        try:
            out = dl.load_session(str(season), meeting, sess)
            n = len(out["laps"])
            if n:
                ok.append(label)
                print(f"    OK   {n:,} laps", flush=True)
            else:
                fail.append((label, "no laps returned"))
                print("    WARN no laps returned", flush=True)
        except Exception as exc:                   # noqa: BLE001 — report & continue
            fail.append((label, str(exc)))
            print(f"    FAILED: {exc}", flush=True)

    print(f"\nDone. {len(ok)} ok, {len(fail)} failed/empty.")
    for label, why in fail:
        print(f"  ✗ {label} — {why}")
    return 0 if not fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
