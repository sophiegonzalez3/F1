"""Curated DNF causes (data/dnf_causes.csv) layered over the race-control register.

WHY THIS FILE EXISTS. The results archive recorded a rich cause vocabulary
until 2022 - Engine, Gearbox, Hydraulics, Accident, Collision - and since 2023
records a bare "Retired" for every non-finish. That information is gone, not
hidden: it cannot be recovered from timing or telemetry.

Race control recovers PART of it. `f1lib.incidents` reads back every contact
the stewards investigated, which is why 48 of 237 retirements (2023-26) are
classified as collisions. But race control only logs what it INVESTIGATES: a
car that simply stops draws no stewards' message at all, so 169 retirements
have no contact row and never will. Those are car failures, driver crashes
and disqualifications, and press is the only remaining source.

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

# Families, not details — and since 2026-10-07 the families answer ONE
# question: WHO IS THE RETIREMENT IMPUTABLE TO? (They used to be descriptive —
# "mechanical", "solo accident" — and the rename is a deliberate change of
# meaning, decided with the dashboard's owner.) "hydraulics vs gearbox" stays
# in the free-text `cause_detail`, because it often is not reportable.
#
#   car imputable     the car or the TEAM: any component failure, and any
#                     team decision to stop a healthy car (strategy, saving
#                     the engine, ending a test run, an operational error at a
#                     stop). Was "mechanical".
#   driver imputable  the driver: crashes and offs with no other car,
#                     the driver's fitness or illness, and FLOOR / UNDERBODY
#                     DAMAGE OF UNSTATED ORIGIN — usually a kerb taken too
#                     hard, so it defaults here unless the press says
#                     otherwise. Was "solo accident".
#   collision         imputable to NEITHER the car nor that driver: contact
#                     with another car, debris from somebody else's crash, a
#                     foreign object (Sainz's drain cover, Las Vegas 2023), a
#                     puncture. Floor damage belongs here only when the press
#                     says with confidence where it came from.
#   disqualified      not a reliability event at all; kept apart so it never
#                     pollutes the read.
#
# Calibrated against the 2019-2022 archive, the last era that recorded real
# causes (~250 genuine non-finishes): car ~130 (Engine 18, Power Unit 15,
# Brakes 13, Gearbox 12, ...), collision 83 (Collision 58, Collision damage 22,
# Puncture 3), driver 29 (Accident 25, Spun off 4), disqualified 14.
# Deliberately NO "withdrawal" family: the archive's Withdrew / Illness rows are
# bucketed "Did not start" from the status alone; a curated withdrawal gets the
# family of its REASON (illness -> driver, team choice -> car).
CAR, COLLISION, DRIVER, DSQ = ("car imputable", "collision",
                               "driver imputable", "disqualified")
FAMILIES = (CAR, COLLISION, DRIVER, DSQ)

# Old spellings, read as their successors so a stale row, a merge from an old
# branch or a hand edit from memory cannot silently fall out of the chart.
LEGACY_FAMILIES = {"mechanical": CAR, "solo accident": DRIVER}


def normalise_family(value) -> str:
    """A cause_family cell as one of FAMILIES, or "" when blank/unknown."""
    fam = str(value or "").strip().lower()
    fam = LEGACY_FAMILIES.get(fam, fam)
    return fam if fam in FAMILIES else ""


# The pre-2023 archive's own Status vocabulary, read through the same lens.
# One map, used by the reliability card AND the DUEL tab, so the two can never
# disagree about what "Accident" means. Undertray / wings stay with the car —
# the archive files them as component failures and its word is kept. The list
# is every cause-naming status actually present in race_results_all (2019-26);
# the old reliability map missed seven of them (Overheating, Wheel,
# Electronics, Exhaust, Transmission, Radiator, Out of fuel), which left those
# retirements "unclassified".
_CAR_STATUSES = {
    "Engine", "Power Unit", "Brakes", "Gearbox", "Suspension", "Hydraulics",
    "Power loss", "Water pressure", "Overheating", "Oil leak", "Wheel",
    "Undertray", "Electronics", "Fuel pressure", "Water leak", "Exhaust",
    "Turbo", "Transmission", "Mechanical", "Electrical", "Cooling system",
    "Driveshaft", "Differential", "Fuel pump", "Out of fuel", "Front wing",
    "Fuel leak", "Rear wing", "Radiator", "Vibrations", "Water pump",
    "Wheel nut"}
_COLLISION_STATUSES = {"Collision", "Collision damage", "Puncture", "Damage",
                       "Debris"}
_DRIVER_STATUSES = {"Accident", "Spun off"}
STATUS_FAMILY = {**{s: CAR for s in _CAR_STATUSES},
                 **{s: COLLISION for s in _COLLISION_STATUSES},
                 **{s: DRIVER for s in _DRIVER_STATUSES},
                 "Disqualified": DSQ}
DNS_STATUSES = {"Did not start", "Withdrew", "Illness"}


def family_of(season, event: str, driver: str, last_lap, status) -> str:
    """The family of one non-finish: the archive's own status when it names a
    cause (pre-2023), otherwise race control then curation (resolve_cause).
    "" when nobody knows yet."""
    fam = STATUS_FAMILY.get(str(status).strip())
    if fam:
        return fam
    return resolve_cause(season, event, driver, last_lap)["cause_family"]

# How much weight the row's cause carries.
#   measured   a timing/FIA fact (reserved for race_control rows)
#   reported   press states the cause as fact, from its own reporting
#   claimed    the team said it - a claim about what they chose to say
CONFIDENCE = ("measured", "reported", "claimed")

COLS = ["season", "round", "event", "driver", "team", "status_archive",
        "laps", "cause_family", "cause_detail", "confidence",
        "source", "source_date", "press_checked", "note",
        "overrides_register"]

# THE ONE EXCEPTION TO "measured beats reported". The register's collision
# call for a retirement is not itself a measurement: it is an INFERENCE that a
# logged contact within CAUSAL_WINDOW laps of the stop caused it. When race
# control logged only "INCIDENT (reason unstated) — no action" and the car then
# stopped with a failure, that inference is wrong — Russell, Canada 2026: a
# no-action brush with Antonelli on lap 26, then a battery failure on lap 30.
# A curated row with overrides_register = "yes" wins over the register, and
# MUST say in its note what the register inferred and why it does not hold.
# Never set it to settle a disagreement about fault — only about cause —
# EXCEPT on an explicit OWNER'S RULING, whose note must start "OWNER'S
# RULING" (Hamilton, Qatar 2023: no stewards' action, but his own full
# admission; Lawson and Bortoleto, Australia 2025: solo crashes the register
# misread from an unsafe-release message).
#
# HIERARCHY (owner's rule, 2026-10-07): a STEWARDS' DECISION always supersedes
# race control's message log. The register only knows that a contact was
# logged near the stop; the stewards' published decision is the FIA's own
# finding on what happened — Lawson, Miami 2026: contact with Gasly logged,
# but the stewards found a gearbox failure caused it ("nothing that he could
# do"), so the row is car imputable with confidence "measured".

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
    fam = normalise_family(row.get("cause_family", ""))
    if not fam:
        return None
    conf = str(row.get("confidence", "") or "").strip().lower()
    override = str(row.get("overrides_register", "") or "").strip().lower()
    return {
        "overrides_register": override in ("yes", "true", "1"),
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
    cur = curated_cause(season, event, driver)
    if cur and cur.pop("overrides_register", False):
        out.update(**cur)
        out["note"] = (out["note"] + " " if out["note"] else "") + (
            f"[Overrides the register, which inferred a collision with "
            f"{got.get('counterparty') or 'another car'}.]"
            if got["cause"] == "collision" else "")
        out["note"] = out["note"].strip()
        return out
    if got["cause"] == "collision":
        cp = str(got.get("counterparty", "") or "")
        lap_n = int(got.get("incident_lap") or 0)
        other = got.get("counterparty_penalty") or (
            _grid_ruling(season, event, cp) if cp else "")
        verdict = (f"the stewards penalised {cp} for it ({other})" if other
                   else f"no penalty to {driver} for it")
        out.update(cause_family=COLLISION, cause_source="race_control",
                   counterparty=cp, confidence="measured",
                   cause_detail=(f"COLLISION with {cp or 'another car'} on "
                                 f"lap {lap_n}; {verdict}."))
        ruling = got.get("penalty") or _grid_ruling(season, event, driver)
        if ruling:
            # AT FAULT -> driver imputable, on the stewards' ruling alone.
            out.update(cause_family=DRIVER, cause_detail=(
                f"COLLISION with {cp or 'another car'} on lap "
                f"{int(got['incident_lap'] or 0)}; the stewards penalised "
                f"{driver} for it ({ruling}), so it is imputed to the driver."))
            out["note"] = AT_FAULT_NOTE
        return out
    if cur:
        cur.pop("overrides_register", None)
        out.update(**cur)
    return out


# ── At-fault collisions ──────────────────────────────────────
# A collision is imputable to "neither" only when the retiring driver was not
# the one at fault. Fault is judged on ONE criterion, deliberately: the
# STEWARDS' RULING on that contact (an in-race penalty in the register, or a
# grid drop carried to the next event "for causing a collision" in the FIA
# final starting grid). Not the press — whose verdict on who "owned" a corner
# tends to follow the reporter's nationality — and not the curator's eye.
# The stewards are not perfectly consistent either (the same move can draw a
# penalty one weekend and "no further action" the next), which is why every
# such row still says in its detail that a collision happened.
def is_collision(cause: dict) -> bool:
    """Did contact end this race — WHOEVER it is imputed to? True for the
    collision family and for an at-fault collision imputed to the driver
    (its detail always starts "COLLISION", curated rows included)."""
    return (cause.get("cause_family") == COLLISION
            or str(cause.get("cause_detail", "")).upper().startswith("COLLISION"))


AT_FAULT_NOTE = ("A collision happened, whatever the ruling. Imputed to the "
                 "driver because the stewards penalised him for this contact; "
                 "their rulings on similar contact are not always consistent.")

_GRID_PATH = Path("data/grid_penalties.csv")
_GRID_CACHE: dict = {"mtime": None, "df": pd.DataFrame()}


def _grid_ruling(season, event: str, driver: str) -> str:
    """A grid penalty "for causing a collision" at `event`, served at a later
    event (data/grid_penalties.csv) — "" when none."""
    try:
        mtime = _GRID_PATH.stat().st_mtime if _GRID_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _GRID_CACHE["mtime"]:
        try:
            _GRID_CACHE["df"] = pd.read_csv(_GRID_PATH) if mtime else pd.DataFrame()
        except Exception:
            _GRID_CACHE["df"] = pd.DataFrame()
        _GRID_CACHE["mtime"] = mtime
    g = _GRID_CACHE["df"]
    if g.empty or driver is None:
        return ""
    hit = g[(g["driver"].astype(str) == str(driver))
            & g["reason"].astype(str).str.contains("collision", case=False)
            & g["stewards_doc"].astype(str).str.contains(
                f"({season} {event})", regex=False)]
    if hit.empty:
        return ""
    h = hit.iloc[0]
    return f"{int(h['places'])}-place grid penalty at the {h['event']}"


# Power-unit failures, read from the curated detail. Families stay coarse on
# purpose (see FAMILIES), so "was it the PU?" is answered from the wording:
# the PU's own elements (ICE, turbo, MGU-K, energy store / battery, control
# electronics) plus the generic "engine" / "power unit". Deliberately NOT
# matched: fuel system, cooling/water, hydraulics, clutch/anti-stall, a bare
# "electrical problem" — all real failures, none of them attributable to the
# power unit from the text alone.
_PU_WORDS = ("power unit", "power-unit", "engine", "battery", "energy store",
             "ers ", "ers issue", "mgu", "turbo", " ice ")


def is_pu_failure(cause: dict) -> bool:
    """True when a resolved cause names the power unit."""
    if cause.get("cause_family") != CAR:
        return False
    text = f" {cause.get('cause_detail', '')} ".lower()
    return any(w in text for w in _PU_WORDS)
