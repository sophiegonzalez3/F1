"""Curated DNF causes (data/dnf_causes.csv) layered over the race-control register.

WHY THIS FILE EXISTS. The results archive recorded a rich cause vocabulary
until 2022 - Engine, Gearbox, Hydraulics, Accident, Collision - and since 2023
records a bare "Retired" for every non-finish. That information is gone, not
hidden: it cannot be recovered from timing or telemetry.

Race control recovers PART of it. `f1lib.incidents` reads back every contact
the stewards investigated, which is why 48 of 237 retirements (2023-26) are
classified as collisions. But race control only logs what it INVESTIGATES: a
car that simply stops draws no stewards' message at all, so 169 retirements
have no contact row and never will. Those are mechanical failures, solo
accidents and disqualifications, and press is the only remaining source.

THE RULE THIS MODULE ENFORCES: measured beats reported, always. `cause_source`
is never collapsed. A cause from race control outranks anything curated; a
curated row only ever fills a hole. The reliability card renders the two
differently, because a chart that silently mixes "the FIA logged this" with
"a journalist wrote this" claims a precision it does not have.

DO NOT CURATE WHAT IS MEASURABLE. Collisions are race control's job - hand-
writing one duplicates a fact the register already holds and will drift from
it. This file is for the 169, not the 48.

BIAS, AND THE COLUMN THAT MAKES IT VISIBLE. Press does not report every
retirement to the same depth: a front-runner's failure gets a named component,
a backmarker's gets "a technical problem". Left alone that produces a chart
where the big teams' DNFs look explained and everyone else's look mysterious -
a coverage artifact wearing the costume of data. `press_checked` is therefore
stamped with the date EVEN WHEN THE SEARCH FOUND NOTHING, so "looked, found
nothing" is distinguishable from "never looked" and the gradient is countable.

A TEAM'S EXPLANATION IS A CLAIM, NOT A MEASUREMENT. "We had a PU issue" from a
team principal is evidence about what the team chose to say. Record it, cite
it, and set `confidence` to "claimed" so it can be filtered out.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

CAUSES_PATH = Path("data/dnf_causes.csv")

# Families, not details. "Mechanical vs collision vs solo accident vs
# disqualified" is reportable with confidence; "hydraulics vs gearbox" often is
# not, and one combined field pressures the curator into guessing the half they
# do not know. `cause_detail` is free text and may be blank.
#
# Calibrated against the 2019-2022 archive, the last era that recorded real
# causes (~250 genuine non-finishes):
#   mechanical     the long tail - Engine 18, Power Unit 15, Brakes 13,
#                  Gearbox 12, Suspension 8, Hydraulics 6, ... ~130 rows
#   collision      Collision 58 + Collision damage 22 + Puncture 3
#   solo accident  Accident 25 + Spun off 4 - off or into the wall with
#                  no counterparty. DESCRIPTIVE on purpose: "driver
#                  error" would assign a fault nobody measured, and a
#                  lap-1 snap on cold tyres may be the car, the driver or
#                  the track. The pre-2023 archive was descriptive too.
#   disqualified   14 across the whole archive, 6 in 2025 alone (the Chinese
#                  GP triple, Bahrain, the Las Vegas McLaren double). NOT a
#                  reliability event, and it pollutes the read if bucketed
#                  with failures.
# Deliberately NO "withdrawal" family: the same archive holds 3 Withdrew and 2
# Illness rows in four seasons, and reliability.py already buckets those under
# "Did not start". One row every eighteen months does not earn a family.
FAMILIES = ("mechanical", "collision", "solo accident", "disqualified")

# How much weight the row's cause carries.
#   measured   a timing/FIA fact (reserved for race_control rows)
#   reported   press states the cause as fact, from its own reporting
#   claimed    the team said it - a claim about what they chose to say
CONFIDENCE = ("measured", "reported", "claimed")

COLS = ["season", "round", "event", "driver", "team", "status_archive",
        "laps", "cause_family", "cause_detail", "confidence",
        "source", "source_date", "press_checked", "note"]

_CACHE: dict = {"mtime": None, "df": pd.DataFrame(columns=COLS)}


def causes_df() -> pd.DataFrame:
    """The curated table; empty frame (with columns) when it isn't built."""
    try:
        mtime = CAUSES_PATH.stat().st_mtime if CAUSES_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _CACHE["mtime"]:
        df = pd.DataFrame(columns=COLS)
        if mtime is not None:
            try:
                df = pd.read_csv(CAUSES_PATH)
                for c in COLS:
                    if c not in df.columns:
                        df[c] = ""
            except Exception as exc:
                print(f"DNF causes              : failed to read ({exc})")
        _CACHE["df"] = df
        _CACHE["mtime"] = mtime
    return _CACHE["df"]


def has_causes(season) -> bool:
    d = causes_df()
    if d.empty:
        return False
    try:
        return bool((pd.to_numeric(d["season"], errors="coerce")
                     == int(season)).any())
    except (TypeError, ValueError):
        return False


def curated_cause(season, event: str, driver: str) -> dict | None:
    """The curated cause for one retirement, or None if nobody has filled it.

    A seeded-but-unfilled row (blank `cause_family`) returns None: the seeding
    script writes skeletons so the curator can see what is outstanding, and a
    skeleton is not an answer.
    """
    d = causes_df()
    if d.empty or driver is None:
        return None
    try:
        m = (pd.to_numeric(d["season"], errors="coerce") == int(season))
    except (TypeError, ValueError):
        return None
    m &= d["event"].astype(str).str.strip() == str(event).strip()
    m &= (d["driver"].astype(str).str.upper().str.strip()
          == str(driver).upper().strip())
    hit = d[m]
    if hit.empty:
        return None
    row = hit.iloc[0]
    fam = str(row.get("cause_family", "") or "").strip().lower()
    if fam not in FAMILIES:
        return None
    conf = str(row.get("confidence", "") or "").strip().lower()
    return {
        "cause_family": fam,
        "cause_detail": str(row.get("cause_detail", "") or "").strip(),
        "cause_source": "press",
        "confidence": conf if conf in CONFIDENCE else "reported",
        "source": str(row.get("source", "") or "").strip(),
        "note": str(row.get("note", "") or "").strip(),
    }


def resolve_cause(season, event: str, driver: str, last_lap) -> dict:
    """One retirement's cause, race control first and curation only to fill.

    Returns `cause_family` ("" when still unknown) and `cause_source`
    ("race_control" | "press" | ""), plus detail/counterparty/confidence.

    Ordering is the whole point: race control is a contemporaneous FIA record,
    curation is a person reading the press weeks later. Where they disagree the
    register wins and the curated row is ignored rather than merged, so a
    curation mistake can never overwrite a measurement.
    """
    from f1lib.incidents import classify_retirement

    out = {"cause_family": "", "cause_source": "", "cause_detail": "",
           "counterparty": "", "confidence": "", "source": "", "note": ""}
    got = classify_retirement(season, event, driver, last_lap)
    if got["cause"] == "collision":
        out.update(cause_family="collision", cause_source="race_control",
                   counterparty=str(got.get("counterparty", "") or ""),
                   confidence="measured")
        return out
    cur = curated_cause(season, event, driver)
    if cur:
        out.update(**cur)
    return out
