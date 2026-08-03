"""Build the race-incident register -> data/incidents.csv.

Why this exists
---------------
The results archive stopped recording WHY a car retired. From 2023 onward
every non-finish is a bare "Retired" — 44 of them in 2026, none classified —
so the dashboard's mechanical-vs-incident split has been dead code for three
seasons. Race control, which IS cached per session, never stopped saying it.

The more valuable half is contact that does NOT end a race. A car that picks
up floor damage on lap 3 runs fifty compromised laps, and every one of them
currently flows into race pace, into the degradation curves and into the car
concept axes as if it were representative. Worse: the outlier gate that would
normally catch them is grouped per (session, compound, TEAM), so a damaged car
drags its own team's reference median down and its bad laps stay ValidLap.

What race control gives, and what it does not
---------------------------------------------
Cached messages carry a bounded, machine-readable incident vocabulary — over
2026 that is 248 messages across 11 races, 20 distinct reasons. They do NOT
carry retirements or debris (measured: zero "STOPPED"/"RETIRED"/"DEBRIS"
messages all season), so a retirement's cause is inferred by matching it
against the incidents found here rather than read off directly.

Deduplication
-------------
One incident is announced several times: NOTED, then UNDER INVESTIGATION, then
the penalty, then PENALTY SERVED. All stages repeat the incident's clock time
in trailing parentheses — "(15:57:04)" — which is a stable key. The Lap column
is NOT: it records when the MESSAGE was published, so the same collision shows
up at laps 39, 40, 44 and 50. The incident lap is therefore the EARLIEST lap
among the messages sharing a key.

About a third of messages carry no timestamp; those fall back to a
(event, cars, reason) key, which merges two separate incidents by the same
driver for the same reason in one race. Rare, and flagged by n_messages.

Usage
-----
    python scripts/compute_incidents.py                 # every cached season
    python scripts/compute_incidents.py --season 2026
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import re
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

OUT_PATH = Path("data/incidents.csv")
SESSIONS_DIR = Path("data/sessions")

# ── Reason → kind ────────────────────────────────────────────
# CONTACT is the one that matters for lap-time damage: these are the reasons
# that mean two cars (or a car and the scenery) touched. Everything else is
# either an excursion or paperwork, and must not be treated as damage.
_CONTACT = (
    "causing a collision",
    "collision",
    "forcing another driver off the track",
    "moving under braking",
    "unsafe release",
    "erratic driving",
    "dangerous driving",
    # a two-car incident the stewards logged without categorising it
    "incident (reason unstated)",
)
_OFF_TRACK = (
    "leaving the track and gaining an advantage",
    "track limits",
    "leaving the track",
)


def classify(reason: str) -> str:
    r = str(reason).strip().casefold()
    if any(k in r for k in _CONTACT):
        return "contact"
    if any(k in r for k in _OFF_TRACK):
        return "off-track"
    return "procedural"


# ── Message parsing ──────────────────────────────────────────
_CARS_RE = re.compile(r"CARS?\s+([\d]+)\s*\(([A-Z]{3})\)"
                      r"(?:\s+AND\s+([\d]+)\s*\(([A-Z]{3})\))?", re.I)
_TS_RE = re.compile(r"\((\d{2}:\d{2}:\d{2})\)\s*$")
_PENALTY_RE = re.compile(
    r"(\d+\s*SECOND\s*TIME\s*PENALTY|STOP-AND-GO\s*PENALTY|DRIVE\s*THROUGH"
    r"|\d+\s*PLACE\s*GRID|REPRIMAND|DISQUALIFI)", re.I)


def _reason_of(msg: str) -> str | None:
    """The FIA reason, i.e. the text after the last ' - ', timestamp stripped."""
    parts = re.split(r"\s+-\s+", msg)
    if len(parts) < 2:
        return None
    return _TS_RE.sub("", parts[-1]).strip()


def _outcome_of(msg: str) -> str:
    u = msg.upper()
    if "NO FURTHER INVESTIGATION" in u or "NO FURTHER ACTION" in u:
        return "no action"
    pen = _PENALTY_RE.search(msg)
    if pen:
        return f"penalty: {pen.group(1).strip().lower()}"
    if "UNDER INVESTIGATION" in u:
        return "investigated"
    if "WILL BE INVESTIGATED AFTER THE RACE" in u:
        return "investigated after race"
    if "NOTED" in u:
        return "noted"
    return "seen"


_OUTCOME_RANK = {"seen": 0, "noted": 1, "investigated": 2,
                 "investigated after race": 3, "no action": 4}


def _best_outcome(values: list[str]) -> str:
    """A penalty always wins; otherwise the furthest the stewards got."""
    pen = [v for v in values if v.startswith("penalty")]
    if pen:
        return sorted(pen)[-1]
    return max(values, key=lambda v: _OUTCOME_RANK.get(v, -1))


def parse_race_control(rc: pd.DataFrame) -> pd.DataFrame:
    """One row per (message, driver involved). Stages are collapsed later."""
    rows = []
    for r in rc.itertuples():
        msg = str(getattr(r, "Message", "") or "")
        u = msg.upper()
        if "INCIDENT" not in u and "PENALTY" not in u:
            continue
        if "LAP DELETED" in u or ("TIME" in u and "DELETED" in u):
            continue                       # track-limits lap deletions: not this
        m = _CARS_RE.search(msg)
        if not m:
            continue
        reason = _reason_of(msg)
        if not reason:
            # The FIA often logs a two-car incident with NO stated reason —
            # "TURN 13 INCIDENT INVOLVING CARS 43 (COL) AND 87 (BEA) NOTED".
            # Dropping those would discard exactly the first-lap tangles this
            # register exists to catch, so an uncategorised MULTI-car incident
            # is recorded as contact with the reason marked unstated. A
            # single-car one stays unclassified: it is as likely a spin or an
            # off as a touch, and guessing would poison the damage detector.
            if not m.group(3):
                continue
            reason = "INCIDENT (reason unstated)"
        ts = _TS_RE.search(msg)
        lap = pd.to_numeric(getattr(r, "Lap", np.nan), errors="coerce")
        pair = [(m.group(1), m.group(2).upper())]
        if m.group(3):
            pair.append((m.group(3), m.group(4).upper()))
        for car_no, code in pair:
            other = [c for n, c in pair if c != code]
            rows.append({
                "lap_msg": lap,
                "driver": code,
                "car_no": car_no,
                "reason": reason,
                "counterparty": other[0] if other else "",
                "outcome": _outcome_of(msg),
                "ts": ts.group(1) if ts else "",
                "message": msg,
            })
    return pd.DataFrame(rows)


def collapse(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse the NOTED / INVESTIGATED / PENALTY stages into one incident."""
    if df.empty:
        return df
    d = df.copy()
    # the timestamp is the real incident id; without one, fall back to the
    # (driver, reason, counterparty) triple for that race
    d["_key"] = np.where(
        d["ts"].astype(str) != "",
        d["driver"] + "|" + d["ts"].astype(str) + "|" + d["reason"],
        d["driver"] + "|nots|" + d["reason"] + "|" + d["counterparty"])
    out = (d.groupby("_key")
             .agg(driver=("driver", "first"),
                  car_no=("car_no", "first"),
                  reason=("reason", "first"),
                  counterparty=("counterparty",
                                lambda s: next((v for v in s if v), "")),
                  # publication lap varies across stages — the incident
                  # happened at or before the FIRST mention
                  lap=("lap_msg", "min"),
                  outcome=("outcome", lambda s: _best_outcome(list(s))),
                  incident_time=("ts", "first"),
                  n_messages=("message", "size"))
             .reset_index(drop=True))
    out["kind"] = out["reason"].map(classify)
    return out


# ── Per-event assembly ───────────────────────────────────────

def build_event(season: int, stem: str) -> pd.DataFrame:
    p = SESSIONS_DIR / f"{season}__{stem}__Race__race_control.parquet"
    if not p.exists():
        return pd.DataFrame()
    try:
        rc = pd.read_parquet(p)
    except Exception as exc:
        print(f"  {stem}: race control unreadable ({exc})")
        return pd.DataFrame()
    inc = collapse(parse_race_control(rc))
    if inc.empty:
        return inc
    inc.insert(0, "event", stem.replace("_", " "))
    inc.insert(0, "season", season)
    return inc


def cached_races(season: int) -> list[str]:
    return sorted({p.name.split("__")[1] for p in
                   SESSIONS_DIR.glob(f"{season}__*__Race__race_control.parquet")})


def _round_map(season: int) -> dict[str, int]:
    p = Path("data/historical_results/quali_results_all.parquet")
    if not p.exists():
        return {}
    try:
        q = pd.read_parquet(p)
    except Exception:
        return {}
    q = q[q["season"] == season]
    return {str(r.event_name): int(r.round_number)
            for r in q.drop_duplicates("event_name").itertuples()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, action="append")
    args = ap.parse_args()

    seasons = args.season or sorted(
        {int(p.name.split("__")[0])
         for p in SESSIONS_DIR.glob("*__*__Race__race_control.parquet")})
    if not seasons:
        print("No cached race-control data under data/sessions/.")
        return 1

    frames = []
    for season in seasons:
        rounds = _round_map(season)
        races = cached_races(season)
        print(f"[{season}] {len(races)} cached race(s)")
        for stem in races:
            df = build_event(season, stem)
            if df.empty:
                print(f"  {stem}: no incidents parsed")
                continue
            df["round"] = df["event"].map(
                lambda e: rounds.get(e, rounds.get(e + " Grand Prix", np.nan)))
            n_contact = int((df["kind"] == "contact").sum())
            print(f"  {stem}: {len(df)} incident(s) · {n_contact} contact")
            frames.append(df)

    if not frames:
        print("Nothing built.")
        return 1
    out = pd.concat(frames, ignore_index=True)
    cols = ["season", "round", "event", "lap", "driver", "car_no", "kind",
            "reason", "counterparty", "outcome", "incident_time", "n_messages"]
    out = out[cols].sort_values(["season", "round", "lap", "driver"])
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {len(out)} rows -> {OUT_PATH}")
    print(out["kind"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
