"""Seed data/dnf_causes.csv with the retirements race control cannot explain.

Writes SKELETON rows only - season/round/event/driver/team/status/laps filled
in from the archive, and `cause_family` deliberately blank. Filling it is the
hand-curation step; a blank row is the worklist, not an answer.

WHAT IT DELIBERATELY SKIPS. Anything `f1lib.incidents` already classifies as a
collision. Race control logged those contemporaneously, so curating them by
hand would duplicate a measurement and drift from it. Run this AFTER the
incident register is rebuilt (that is the order in after_race.py) or it will
seed rows the register was about to explain.

THE `press_checked` DISCIPLINE. When you research a row, stamp today's date in
`press_checked` EVEN IF YOU FIND NOTHING, and leave `cause_family` blank. That
is what separates "looked, press never said" from "nobody has looked yet" -
without it the two are identical in the file and the reliability card's
coverage gradient becomes invisible. `--todo` counts both.

Usage
-----
    python scripts/seed_dnf_causes.py                 # every cached season
    python scripts/seed_dnf_causes.py --season 2026
    python scripts/seed_dnf_causes.py --latest        # the most recent race
    python scripts/seed_dnf_causes.py --todo          # what is outstanding
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
from pathlib import Path

import pandas as pd

from f1lib.config import HISTORICAL_DIR
from f1lib.dnf_causes import CAUSES_PATH, COLS, FAMILIES, causes_df
from f1lib.incidents import classify_retirement

ARCHIVE = Path(HISTORICAL_DIR) / "race_results_all.parquet"

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


def _archive() -> pd.DataFrame:
    if not ARCHIVE.exists():
        raise SystemExit(f"no results archive at {ARCHIVE}")
    return pd.read_parquet(ARCHIVE)


def seed(season: int | None = None, event: str | None = None) -> pd.DataFrame:
    r = _archive()
    r = r[~r["Status"].isin(FINISHED) & r["Status"].notna()]
    r = r[~r["Status"].isin(SELF_EXPLAINING)]
    # Pre-2023 the archive names the cause, so there is nothing to curate.
    r = r[pd.to_numeric(r["season"], errors="coerce") >= 2023]
    if season is not None:
        r = r[pd.to_numeric(r["season"], errors="coerce") == int(season)]
    if event:
        r = r[r["event_name"].astype(str).str.strip() == str(event).strip()]

    rows = []
    for _, x in r.iterrows():
        s, ev = int(x["season"]), str(x["event_name"])
        drv = str(x["Abbreviation"])
        got = classify_retirement(s, ev, drv, x.get("Laps"))
        if got["cause"] == "collision":
            continue                      # race control already owns this one
        rows.append({
            "season": s,
            "round": x.get("round_number"),
            "event": ev,
            "driver": drv,
            "team": str(x.get("TeamName", "")),
            "status_archive": str(x.get("Status", "")),
            "laps": x.get("Laps"),
            "cause_family": "", "cause_detail": "", "confidence": "",
            "source": "", "source_date": "", "press_checked": "", "note": "",
        })
    return pd.DataFrame(rows, columns=COLS)


def _latest() -> tuple[int, str]:
    r = _archive()
    r = r.dropna(subset=["season", "round_number"])
    last = r.sort_values(["season", "round_number"]).iloc[-1]
    return int(last["season"]), str(last["event_name"])


def _report_todo() -> int:
    d = causes_df()
    if d.empty:
        print("data/dnf_causes.csv not seeded yet - run without --todo first.")
        return 0
    fam = d["cause_family"].astype(str).str.strip().str.lower()
    checked = d["press_checked"].astype(str).str.strip()
    filled = fam.isin(FAMILIES)
    looked = (~filled) & checked.ne("") & checked.ne("nan")
    todo = (~filled) & (~looked)
    print(f"{len(d)} seeded retirement(s)")
    print(f"  {int(filled.sum()):4d} with a cause")
    print(f"  {int(looked.sum()):4d} researched, press said nothing "
          "(press_checked stamped, cause blank)")
    print(f"  {int(todo.sum()):4d} not yet looked at")
    if filled.any():
        print()
        print(d[filled]["cause_family"].value_counts().to_string())
    if todo.any():
        print()
        print("Oldest outstanding:")
        cols = ["season", "event", "driver", "team", "status_archive", "laps"]
        print(d[todo].sort_values(["season", "round"])[cols]
              .head(12).to_string(index=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--event")
    ap.add_argument("--latest", action="store_true",
                    help="only the most recent race in the archive")
    ap.add_argument("--todo", action="store_true",
                    help="report what is outstanding and exit")
    args = ap.parse_args()

    if args.todo:
        return _report_todo()

    season, event = args.season, args.event
    if args.latest:
        season, event = _latest()
        print(f"[latest] {season} {event}")

    new = seed(season, event)
    if new.empty:
        print("Nothing to seed - every retirement in scope is already "
              "explained by race control.")
        return 0

    key = ["season", "event", "driver"]
    if CAUSES_PATH.exists():
        old = pd.read_csv(CAUSES_PATH)
        for c in COLS:
            if c not in old.columns:
                old[c] = ""
        # never clobber a cause somebody already researched
        seen = old[key].astype(str).apply(tuple, axis=1)
        mask = new[key].astype(str).apply(tuple, axis=1).isin(set(seen))
        already = int(mask.sum())
        new = new[~mask]
        if already:
            print(f"{already} row(s) already present - left untouched")
        out = pd.concat([old, new], ignore_index=True)
    else:
        out = new

    CAUSES_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.sort_values(["season", "round", "driver"]).to_csv(CAUSES_PATH,
                                                          index=False)
    print(f"\nAdded {len(new)} skeleton row(s) -> {CAUSES_PATH}")
    if not new.empty:
        print(new[["season", "event", "driver", "team", "laps"]]
              .to_string(index=False))
    print(f"\nFill `cause_family` (one of: {', '.join(FAMILIES)}), "
          "`cause_detail`, `confidence`, `source`, `source_date`.")
    print("Stamp `press_checked` with today's date even when you find "
          "nothing - that is what makes the gap countable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
