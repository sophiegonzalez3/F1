"""Which race is "the latest", and is it in the results archive yet?

One definition shared by every `--latest` flag in the post-race chain. They
used to disagree: seed_model_review took the newest event in the pace table,
seed_dnf_causes the newest event in the results archive. When the archive lags
(Jolpica publishes the classification hours after the flag), the two named
DIFFERENT races in the same run — 2026 Bahrain for the review, the previous
round (Azerbaijan) for the DNF worklist, which then silently seeded nothing.

The latest race is the newest RACE session in the session cache, because that
is what the rest of the chain computes from. The archive check is a separate
question, and `python -m f1lib.latest_race` answers it with an exit code so
after_race.py can stop before the steps that need the classification.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from f1lib.config import HISTORICAL_DIR, SESSIONS_DIR
from f1lib.data_loader import _sanitize, event_name_from_stem

CALENDAR = Path("data/season_calendar.csv")
RACE_ARCHIVE = Path(HISTORICAL_DIR) / "race_results_all.parquet"


def latest_cached_race() -> tuple[int, str, int | None] | None:
    """(season, event, round) of the newest cached Race session, or None."""
    races = []
    for p in Path(SESSIONS_DIR).glob("*__*__Race__laps.parquet"):
        season_s, stem = p.name.split("__")[:2]
        if season_s.isdigit():
            races.append((int(season_s), event_name_from_stem(season_s, stem)))
    if not races:
        return None
    rounds: dict[tuple[int, str], int] = {}
    if CALENDAR.exists():
        cal = pd.read_csv(CALENDAR, usecols=["season", "round", "event"])
        rounds = {(int(s), _sanitize(e)): int(r)
                  for s, r, e in cal.itertuples(index=False)}
    keyed = [(s, rounds.get((s, _sanitize(e)), -1), e) for s, e in races]
    s, r, e = max(keyed)
    return s, e, (r if r >= 0 else None)


def archive_has_race(season: int, event: str) -> bool:
    """True when the results archive holds a CLASSIFIED result for the race."""
    if not RACE_ARCHIVE.exists():
        return False
    r = pd.read_parquet(RACE_ARCHIVE, columns=["season", "event_name", "Position"])
    r = r[(pd.to_numeric(r["season"], errors="coerce") == int(season))
          & (r["event_name"].map(_sanitize) == _sanitize(event))]
    return bool(r["Position"].notna().any())


def main() -> int:
    got = latest_cached_race()
    if got is None:
        print("No cached race sessions.")
        return 0
    season, event, rnd = got
    if archive_has_race(season, event):
        print(f"OK - {season} {event} (round {rnd}) is in the results archive.")
        return 0
    print(f"!! {season} {event} (round {rnd}) is cached but NOT in the results "
          "archive - its official classification is not published yet "
          "(Jolpica usually lags the flag by several hours to a day).")
    print("   Without it: the weekend decomposition skips this race, the DNF "
          "worklist has no retirements to seed, and standings/ATR stop at the "
          "previous round.")
    print("   Re-run after_race.py later (FastF1's web cache expires after "
          "12 h), or pass --skip archivecheck to carry on regardless.")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
