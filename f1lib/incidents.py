"""Race-incident register (data/incidents.csv, built by compute_incidents.py).

The results archive has recorded a bare "Retired" for every non-finish since
2023, so the dashboard's mechanical-vs-incident DNF split has been dead code
for three seasons. Race control still says what happened; this reads it back.

Two honest limits, both measured rather than assumed:

CAUSALITY NEEDS PROXIMITY, ASYMMETRICALLY. Matching a retirement to *any*
earlier contact incident is mostly false positives — in 2026 it "explains" 6
of 44 retirements, but Verstappen's China incident was on lap 19 and he
retired on lap 45. Damage that ends a race ends it quickly, so only an
incident within `CAUSAL_WINDOW` laps BEFORE the last lap counts as the cause.
Everything else stays unclassified, which is the truthful answer.

The window does NOT stop at the last lap, though. Race control's `Lap` is the
message's PUBLICATION lap, and a driver cannot be in contact after retiring,
so a contact row above their last lap is always late reporting — never a real
event. It is allowed up to `PUBLICATION_LAG` laps after. Without that the
register was blind to every FIRST-LAP collision: the car is classified at
Laps=0 but the tangle is announced on lap 2-4.

NO DAMAGE FLAG. An automatic "this lap is compromised by earlier contact" flag
was built and rejected. Comparing a driver's clean laps before and after
contact within one stint looked convincing (+0.6 to +1.2 s/lap across five
cases) until the null distribution was built: cutting a stint at a RANDOM lap
with no incident gives a median step of +0.55 s, because within a stint the
later laps are simply on older tyres. 46% of random cut points beat 0.60 s.
Controlling for degradation against the field curve left one case of four
above the noise. With 4-8 testable incidents a season there is not enough to
build a detector on, so this module does not pretend to have one.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

INCIDENTS_PATH = Path("data/incidents.csv")

# Laps between an incident and a retirement for the incident to be treated as
# its cause. Read off the data rather than picked: across the cached archive
# the gap between a retirement and its most recent prior contact clusters at
# 0,1,2,3,4,6 laps and then jumps to 10,13,14,…,52. Six sits in that gap. It
# also matches the physics — a car with race-ending damage stops on track or
# limps in within a lap or two, and race control's lap is the message's
# publication lap, which lags the incident itself.
CAUSAL_WINDOW = 6

# How many laps AFTER a driver's last lap a contact row may still be matched.
# Read off the data the same way CAUSAL_WINDOW was: across 2023-2026 there are
# 38 retirements whose contact row lands after the last lap, and the gap
# clusters at 2 (13 cases), 3 (7), 4 (10) and 5 (5) — 35 of 38 — then jumps to
# 10, 19 and 50. Six sits in that gap and rejects the three outliers.
#
# This bound is safe in a way the backward one is not: a contact row is keyed
# to a driver, and a driver can only be in contact while running, so anything
# above their last lap is publication lag by construction. It is bounded
# anyway because a LATE-PUBLISHED row can still describe an EARLY incident —
# unbounded, a lap-3 tangle announced on lap 50 would "explain" a lap-45
# retirement, which is exactly what CAUSAL_WINDOW exists to prevent.
PUBLICATION_LAG = 6

_COLS = ["season", "round", "event", "lap", "driver", "car_no", "kind",
         "reason", "counterparty", "outcome", "incident_time", "n_messages"]

_CACHE: dict = {"mtime": None, "df": pd.DataFrame(columns=_COLS)}


def incidents_df() -> pd.DataFrame:
    """The register; empty frame (with columns) when it hasn't been built."""
    try:
        mtime = INCIDENTS_PATH.stat().st_mtime if INCIDENTS_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _CACHE["mtime"]:
        df = pd.DataFrame(columns=_COLS)
        if mtime is not None:
            try:
                df = pd.read_csv(INCIDENTS_PATH)
            except Exception as exc:
                print(f"Incident register       : failed to read ({exc})")
        _CACHE["df"] = df
        _CACHE["mtime"] = mtime
    return _CACHE["df"]


def has_incidents(season) -> bool:
    d = incidents_df()
    if d.empty:
        return False
    try:
        return bool((d["season"] == int(season)).any())
    except (TypeError, ValueError):
        return False


def contact_for(season, event: str | None = None) -> pd.DataFrame:
    """Contact incidents for a season, optionally one event."""
    d = incidents_df()
    if d.empty:
        return d
    try:
        m = (d["season"] == int(season)) & (d["kind"] == "contact")
    except (TypeError, ValueError):
        return d.iloc[0:0]
    if event:
        m &= d["event"].astype(str).str.strip() == str(event).strip()
    return d[m].copy()


def classify_retirement(season, event: str, driver: str, last_lap) -> dict:
    """Was this retirement caused by contact?

    Returns {"cause": "collision" | "unclassified",
             "incident_lap": float | None,
             "counterparty": str,
             "earlier_contact": bool,
             "penalty": str}   # collision only: the stewards' penalty on
                               # THIS driver for it, "" when none

    `earlier_contact` is reported separately and deliberately NOT treated as a
    cause: a lap-3 tangle followed by a lap-43 retirement is two events, not
    one, and conflating them is how you turn a reliability chart into a
    collision chart.
    """
    out = {"cause": "unclassified", "incident_lap": None,
           "counterparty": "", "earlier_contact": False}
    c = contact_for(season, event)
    if c.empty or driver is None:
        return out
    c = c[c["driver"].astype(str).str.upper() == str(driver).strip().upper()]
    laps = pd.to_numeric(c["lap"], errors="coerce")
    c = c.assign(_lap=laps).dropna(subset=["_lap"])
    if c.empty:
        return out
    last = pd.to_numeric(pd.Series([last_lap]), errors="coerce").iloc[0]
    if pd.isna(last):
        return out
    out["earlier_contact"] = bool((c["_lap"] <= last).any())
    causal = c[(c["_lap"] <= last + PUBLICATION_LAG)
               & (c["_lap"] >= last - CAUSAL_WINDOW)]
    if causal.empty:
        return out
    row = causal.sort_values("_lap").iloc[-1]
    # The row's lap may be a PUBLICATION lap sitting after the driver's last
    # lap (see PUBLICATION_LAG). Report the physically possible value, not the
    # message's: "collision on lap 71" for a car classified at 66 laps is a
    # number no reader or downstream consumer can use.
    lap = min(float(row["_lap"]), float(last))
    # A penalty message often names no counterparty, and it is the LATEST row,
    # so take the other car from whichever causal row names one.
    named = causal.get("counterparty", pd.Series(dtype=object)
                       ).dropna().astype(str).str.strip()
    named = named[named.ne("") & named.ne("nan")]
    cp = str(row.get("counterparty", "") or "")
    if cp in ("", "nan") and not named.empty:
        cp = named.iloc[-1]
    # The stewards' ruling on THIS contact, when they penalised this driver.
    # Read by f1lib.dnf_causes to impute an at-fault collision to the driver.
    # Only a penalty FOR CAUSING A COLLISION: the same window can hold a
    # penalty for something else entirely — Bortoleto, Australia 2025, was
    # penalised for an unsafe release; Sainz, Bahrain 2025, for forcing
    # Antonelli off — and neither ruling says who caused the contact.
    #
    # The penalty is matched to the INCIDENT, not to the retirement window:
    # the decision can be published long after the car stopped — Ocon, Monaco
    # 2024, out on lap 0 after hitting Gasly, penalised on lap 8 — so it is the
    # driver's next "causing a collision" penalty after the incident, provided
    # no other collision of his sits in between.
    cp = "" if cp == "nan" else cp
    incident_lap = float(causal["_lap"].min())
    out.update(cause="collision", incident_lap=lap, counterparty=cp,
               penalty=_collision_penalty(c, incident_lap),
               counterparty_penalty=_collision_penalty(
                   _driver_rows(season, event, cp), incident_lap) if cp else "")
    return out


def _driver_rows(season, event: str, driver: str) -> pd.DataFrame:
    c = contact_for(season, event)
    if c.empty:
        return c
    c = c[c["driver"].astype(str).str.upper() == str(driver).strip().upper()]
    return c.assign(_lap=pd.to_numeric(c["lap"], errors="coerce")
                    ).dropna(subset=["_lap"])


def _collision_penalty(rows: pd.DataFrame, incident_lap: float) -> str:
    """The penalty a driver received FOR CAUSING the collision at
    `incident_lap` ("10 second time penalty"), or "" when none. Penalties for
    anything else (unsafe release, forcing off) never count."""
    if rows is None or rows.empty:
        return ""
    reason = rows.get("reason", pd.Series("", index=rows.index)
                      ).astype(str).str.upper()
    outcome = rows.get("outcome", pd.Series("", index=rows.index)).astype(str)
    coll = reason.eq("CAUSING A COLLISION")
    is_pen = outcome.str.startswith("penalty")
    pens = rows[coll & is_pen & (rows["_lap"] >= incident_lap - 1)
                ].sort_values("_lap")
    if pens.empty:
        return ""
    p = pens.iloc[0]
    # another collision of his between the incident and this penalty means
    # the penalty may be for THAT one
    between = rows[coll & ~is_pen & (rows["_lap"] > incident_lap + 1)
                   & (rows["_lap"] < p["_lap"])]
    if not between.empty:
        return ""
    return str(p["outcome"]).replace("penalty: ", "")
