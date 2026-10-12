"""Seed data/dnf_causes.csv with the retirements and stops race control cannot
explain - in EVERY session.

Writes SKELETON rows only - season/round/event/session/driver/team/status/laps
filled in, and `cause_family` deliberately blank. Filling it is the
hand-curation step; a blank row is the worklist, not an answer.

THREE SOURCES, one row per (season, event, session, driver):
  Race    the race results archive: every non-finish (as before 2026-10-12)
  Sprint  the sprint results archive, same rules (sprint retirements were not
          tracked at all until 2026-10-12)
  Practice 1-3, Qualifying, Sprint Qualifying / Shootout
          f1lib.session_stops: a car that stopped on track and brought out a
          red flag / VSC / SC, a race driver who never ran or set no time.
          Its evidence goes into `note` ("DETECTED: ..."); `status_archive`
          says which kind of event it is.

WHAT IT DELIBERATELY SKIPS. A Race or Sprint retirement `f1lib.incidents`
already classifies as a collision. Race control logged those contemporaneously,
so curating them by hand would duplicate a measurement and drift from it. Run
this AFTER the incident register is rebuilt (that is the order in
after_race.py) or it will seed rows the register was about to explain.

A DETECTED STOP THE PRESS SHOWS WAS NOT ONE (a car that limped back, a timing
glitch) is not deleted: set its `status_archive` to "False alarm" and say why
in `note`. The row then blocks re-seeding and every card skips it.

THE `press_checked` DISCIPLINE. When you research a row, stamp today's date in
`press_checked` EVEN IF YOU FIND NOTHING, and leave `cause_family` blank. That
is what separates "looked, press never said" from "nobody has looked yet" -
without it the two are identical in the file and the reliability card's
coverage gradient becomes invisible. `--todo` counts both.

Usage
-----
    python scripts/seed_dnf_causes.py                 # every cached season
    python scripts/seed_dnf_causes.py --season 2026
    python scripts/seed_dnf_causes.py --latest        # the most recent event
    python scripts/seed_dnf_causes.py --todo          # what is outstanding
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
from pathlib import Path

import pandas as pd

from f1lib.config import HISTORICAL_DIR
from f1lib.dnf_causes import (
    CAUSES_PATH, COLS, FAMILIES, causes_df, normalise_family,
)
from f1lib.incidents import classify_retirement, session_of

ARCHIVE = Path(HISTORICAL_DIR) / "race_results_all.parquet"
SPRINT_ARCHIVE = Path(HISTORICAL_DIR) / "sprint_results_all.parquet"
FIRST_SEASON = 2023          # pre-2023 archives name the cause themselves

# Statuses that are not a retirement at all. Mirrors tabs/reliability.py; the
# 2023 vocabulary change means BOTH eras must be listed (see the project's
# recurring-failure-modes note on status matching).
FINISHED = {"Finished", "Lapped", "+1 Lap", "+2 Laps", "+3 Laps",
            "+4 Laps", "+5 Laps", "+6 Laps"}
# Non-finishes whose Status ALREADY names the cause, so there is nothing to
# research. "Did not start" is NOT one of them: it says the car never took the
# start and nothing about why (a qualifying crash, a failure on the grid, a
# withdrawn entry all look identical), so DNS rows are seeded like any other.
SELF_EXPLAINING = {"Withdrew", "Illness"}

SESSION_ORDER = ["Practice 1", "Practice 2", "Practice 3", "Sprint Shootout",
                 "Sprint Qualifying", "Sprint", "Qualifying", "Race"]
KEY = ["season", "event", "session", "driver"]


def _archive(path: Path) -> pd.DataFrame:
    if not path.exists():
        if path == ARCHIVE:
            raise SystemExit(f"no results archive at {path}")
        return pd.DataFrame()
    return pd.read_parquet(path)


def _seed_results(path: Path, session: str, season, event) -> list[dict]:
    r = _archive(path)
    if r.empty:
        return []
    r = r[~r["Status"].isin(FINISHED) & r["Status"].notna()]
    r = r[~r["Status"].isin(SELF_EXPLAINING)]
    r = r[pd.to_numeric(r["season"], errors="coerce") >= FIRST_SEASON]
    if season is not None:
        r = r[pd.to_numeric(r["season"], errors="coerce") == int(season)]
    if event:
        r = r[r["event_name"].astype(str).str.strip() == str(event).strip()]
    rows = []
    for _, x in r.iterrows():
        s, ev = int(x["season"]), str(x["event_name"])
        drv = str(x["Abbreviation"])
        got = classify_retirement(s, ev, drv, x.get("Laps"), session=session)
        if got["cause"] == "collision":
            continue                      # race control already owns this one
        rows.append({
            "season": s, "round": x.get("round_number"), "event": ev,
            "session": session, "driver": drv,
            "team": str(x.get("TeamName", "")),
            "status_archive": str(x.get("Status", "")),
            "laps": x.get("Laps"),
        })
    return rows


def _seed_stops(season, event) -> list[dict]:
    from f1lib import session_stops
    from f1lib.config import SESSIONS_DIR, SESSIONS_LITE_DIR
    if season is not None:
        seasons = [int(season)]
    else:
        seasons = sorted({int(p.name.split("__")[0])
                          for base in (Path(SESSIONS_DIR), Path(SESSIONS_LITE_DIR))
                          for p in base.glob("*__laps.parquet")
                          if p.name.split("__")[0].isdigit()})
    seasons = [s for s in seasons if s >= FIRST_SEASON]
    arch = _archive(ARCHIVE)
    rows = []
    for s in seasons:
        d = session_stops.detect_season(s)
        if d.empty:
            continue
        if event:
            d = d[d["event"].astype(str).str.strip() == str(event).strip()]
        a = arch[arch["season"] == s]
        rnd = (a.drop_duplicates("event_name")
               .set_index("event_name")["round_number"].to_dict())
        # some lap feeds carry no Team; the race entry knows it
        team = {(e, dv): t for e, dv, t in
                zip(a["event_name"], a["Abbreviation"], a["TeamName"])}
        for _, x in d.iterrows():
            rows.append({
                "season": s, "round": rnd.get(x["event"]), "event": x["event"],
                "session": x["session"], "driver": x["driver"],
                "team": (str(x["team"] or "").strip()
                         or team.get((x["event"], x["driver"]), "")),
                "status_archive": x["status"],
                "laps": x["laps"], "note": f"DETECTED: {x['evidence']}",
            })
    return rows


def seed(season: int | None = None, event: str | None = None) -> pd.DataFrame:
    rows = (_seed_results(ARCHIVE, "Race", season, event)
            + _seed_results(SPRINT_ARCHIVE, "Sprint", season, event)
            + _seed_stops(season, event))
    out = pd.DataFrame(rows, columns=COLS)
    for c in ("cause_family", "cause_detail", "confidence", "source",
              "source_date", "press_checked", "overrides_register"):
        out[c] = out[c].fillna("")
    out["note"] = out["note"].fillna("")
    return out


def _latest() -> tuple[int, str] | None:
    """The newest CACHED race (shared definition, f1lib.latest_race).

    This used to be the newest race in the results archive, which lags the
    flag: run on race day it named the PREVIOUS round, re-found that round's
    rows already present, and reported "Added 0" as if the new race had no
    retirements. Now the race is the right one, and a missing classification
    is reported as exactly that.
    """
    from f1lib.latest_race import archive_has_race, latest_cached_race
    season, event, _ = latest_cached_race()
    if not archive_has_race(season, event):
        print(f"[latest] {season} {event}: no classified result in the "
              "archive yet, so its retirements are unknown - NOTHING SEEDED. "
              "Re-run once the archive step has picked the race up.")
        return None
    return season, event


def _sort(d: pd.DataFrame) -> pd.DataFrame:
    order = {s: i for i, s in enumerate(SESSION_ORDER)}
    return (d.assign(_o=session_of(d).map(order).fillna(99))
            .sort_values(["season", "round", "_o", "driver"])
            .drop(columns="_o"))


def _report_todo() -> int:
    d = causes_df()
    if d.empty:
        print("data/dnf_causes.csv not seeded yet - run without --todo first.")
        return 0
    fam = d["cause_family"].map(normalise_family)
    checked = d["press_checked"].astype(str).str.strip()
    alarm = d["status_archive"].astype(str).eq("False alarm")
    filled = fam.ne("")
    looked = (~filled) & checked.ne("") & checked.ne("nan") & ~alarm
    todo = (~filled) & (~looked) & ~alarm
    print(f"{len(d)} seeded row(s)")
    print(f"  {int(filled.sum()):4d} with a cause")
    print(f"  {int(looked.sum()):4d} researched, press said nothing "
          "(press_checked stamped, cause blank)")
    print(f"  {int(alarm.sum()):4d} false alarms (detected, not a stop)")
    print(f"  {int(todo.sum()):4d} not yet looked at")
    sess = session_of(d)
    tab = pd.DataFrame({"session": sess, "state": "todo"})
    tab.loc[filled, "state"] = "cause"
    tab.loc[looked, "state"] = "looked"
    tab.loc[alarm, "state"] = "false alarm"
    print()
    print(tab.groupby(["session", "state"]).size().unstack(fill_value=0)
          .to_string())
    if filled.any():
        print()
        print(fam[filled].value_counts().to_string())
    if todo.any():
        print()
        print("Oldest outstanding:")
        cols = ["season", "event", "session", "driver", "team",
                "status_archive", "laps"]
        print(_sort(d[todo])[cols].head(12).to_string(index=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--event")
    ap.add_argument("--latest", action="store_true",
                    help="only the most recent cached event (all its sessions)")
    ap.add_argument("--todo", action="store_true",
                    help="report what is outstanding and exit")
    args = ap.parse_args()

    if args.todo:
        return _report_todo()

    season, event = args.season, args.event
    if args.latest:
        got = _latest()
        if got is None:
            return 0
        season, event = got
        print(f"[latest] {season} {event}")

    new = seed(season, event)
    if new.empty:
        print("Nothing to seed - every retirement in scope is already "
              "explained by race control.")
        return 0

    if CAUSES_PATH.exists():
        old = pd.read_csv(CAUSES_PATH)
        for c in COLS:
            if c not in old.columns:
                old[c] = ""
        old["session"] = session_of(old)
        old = old[COLS]
        # never clobber a cause somebody already researched
        seen = set(old[KEY].astype(str).apply(tuple, axis=1))
        mask = new[KEY].astype(str).apply(tuple, axis=1).isin(seen)
        already = int(mask.sum())
        new = new[~mask]
        if already:
            print(f"{already} row(s) already present - left untouched")
        out = pd.concat([old, new], ignore_index=True)
    else:
        out = new

    CAUSES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _sort(out).to_csv(CAUSES_PATH, index=False)
    print(f"\nAdded {len(new)} skeleton row(s) -> {CAUSES_PATH}")
    if not new.empty:
        print(new.groupby("session").size().to_string())
        print(new[["season", "event", "session", "driver", "team",
                   "status_archive", "laps"]].to_string(index=False))
    print(f"\nFill `cause_family` (one of: {', '.join(FAMILIES)}), "
          "`cause_detail`, `confidence`, `source`, `source_date`.")
    print("Stamp `press_checked` with today's date even when you find "
          "nothing - that is what makes the gap countable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
