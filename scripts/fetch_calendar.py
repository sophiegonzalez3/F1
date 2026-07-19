"""Build data/season_calendar.csv — the per-season event schedule that the
SEASON tab's calendar ribbon reads.

The SEASON tab is deliberately load-free (it only reads CSVs), so the schedule
is fetched once here via FastF1's get_event_schedule and written to disk, the
same fetch->CSV->tab-reads-CSV pattern as the other compute scripts.

Columns: season, round, event, country, location, event_date (Sunday race
date, ISO), sprint (bool). Testing events are excluded.

Usage
-----
    python scripts/fetch_calendar.py                 # every season in team_pace + 2026
    python scripts/fetch_calendar.py --seasons 2026  # one season
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd
import fastf1

from f1lib.config import FASTF1_CACHE_DIR

OUT = Path("data/season_calendar.csv")


def _is_sprint(event_format: str) -> bool:
    """FastF1 EventFormat is 'conventional' for normal weekends and some
    'sprint*' variant (sprint / sprint_shootout / sprint_qualifying) when a
    sprint race is on the bill."""
    return "sprint" in str(event_format).lower()


def season_rows(season: int) -> list[dict]:
    sched = fastf1.get_event_schedule(season, include_testing=False)
    rows: list[dict] = []
    for _, ev in sched.iterrows():
        rnd = ev.get("RoundNumber")
        if pd.isna(rnd) or int(rnd) < 1:
            continue                         # pre-season / testing rows
        date = ev.get("EventDate")
        rows.append({
            "season": season,
            "round": int(rnd),
            "event": str(ev.get("EventName", "")),
            "country": str(ev.get("Country", "")),
            "location": str(ev.get("Location", "")),
            "event_date": pd.Timestamp(date).date().isoformat() if pd.notna(date) else "",
            "sprint": _is_sprint(ev.get("EventFormat", "")),
        })
    return rows


def _default_seasons() -> list[int]:
    """Seasons already present in team_pace_by_event.csv, plus 2026."""
    seasons = {2026}
    try:
        pace = pd.read_csv("data/team_pace_by_event.csv")
        seasons |= {int(s) for s in pace["season"].unique()}
    except Exception:
        pass
    return sorted(seasons)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", nargs="+", type=int, default=None)
    args = ap.parse_args()

    fastf1.Cache.enable_cache(str(Path(FASTF1_CACHE_DIR)))
    fastf1.set_log_level("WARNING")

    seasons = args.seasons or _default_seasons()
    rows: list[dict] = []
    for season in seasons:
        try:
            r = season_rows(season)
            rows.extend(r)
            print(f"  [ok]   {season} — {len(r)} events", flush=True)
        except Exception as exc:
            print(f"  [fail] {season} — {exc}", flush=True)

    if not rows:
        print("No events fetched; leaving existing file untouched.")
        return 1

    df = pd.DataFrame(rows).sort_values(["season", "round"]).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"[saved] {OUT} — {len(df)} events across {df['season'].nunique()} seasons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
