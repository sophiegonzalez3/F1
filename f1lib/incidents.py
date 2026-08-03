"""Race-incident register (data/incidents.csv, built by compute_incidents.py).

The results archive has recorded a bare "Retired" for every non-finish since
2023, so the dashboard's mechanical-vs-incident DNF split has been dead code
for three seasons. Race control still says what happened; this reads it back.

Two honest limits, both measured rather than assumed:

CAUSALITY NEEDS PROXIMITY. Matching a retirement to *any* earlier contact
incident is mostly false positives — in 2026 it "explains" 6 of 44
retirements, but Verstappen's China incident was on lap 19 and he retired on
lap 45. Damage that ends a race ends it quickly, so only an incident within
`CAUSAL_WINDOW` laps of the last lap counts as the cause. Everything else
stays unclassified, which is the truthful answer.

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
             "earlier_contact": bool}

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
    causal = c[(c["_lap"] <= last + 1) & (c["_lap"] >= last - CAUSAL_WINDOW)]
    if causal.empty:
        return out
    row = causal.sort_values("_lap").iloc[-1]
    out.update(cause="collision", incident_lap=float(row["_lap"]),
               counterparty=str(row.get("counterparty", "") or ""))
    return out
