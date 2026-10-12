"""Stops and lost running OUTSIDE the race: practice, qualifying, sprint
qualifying. The candidates `scripts/seed_dnf_causes.py` seeds into
data/dnf_causes.csv with their `session`, so a crash in FP2 or a failure in Q1
is researched exactly like a race retirement.

WHY THE TIMING DATA AND NOT RACE CONTROL. Race control announces the red flag
but never the car: across 2026 practice and qualifying not one message names a
stopped car ("SESSION WILL BE TEMPORARILY STOPPED", "RED FLAG", "MARSHALS ON
TRACK AT TURN 10"). The car is found from the lap feed instead.

THE RULE, read off a known case (Spain 2026 FP3, red flag at 5448 s, Bearman
in the barriers at La Monumental). When a red flag ends a session nobody runs
again and several cars' last lap has no pit entry, because the cars still
lapping return under red and FastF1 drops that in-lap. A car is "stopped on
track" at an incident when it

  1. was on track at the onset (its last event before it was a sector
     crossing or a pit exit, not a pit entry),
  2. was actually lapping (that event is less than ON_TRACK_WINDOW before),
  3. never set another sector time later in the session, and
  4. ONLY IF THE FLAG ENDED THE SESSION: produced no timing event of any kind -
     not even a pit entry - from the onset until RETURN_WINDOW after the flag.
     When the session resumed, rule 3 alone singles the car out (everyone
     caught by the flag runs again), and a stopped car may be recovered to the
     pit lane within minutes: Stroll, Hungary 2026 FP1, suspension failure,
     pit entry +279 s - rejected by rule 4 until 2026-10-12.

Rule 4 is what separates the culprit when the red flag ENDS the session and
nobody runs again. Every car caught by the flag drives back and logs a pit
entry within a few minutes (Gasly +137 s, Lindblad +167 s at Spain FP3);
the stopped car logs nothing - Bearman nothing at all, Hamilton (red flag
earlier in that session) only a pit entry 37 minutes later, when the car was
brought back on a truck. A first attempt that asked whether the car was
"overdue" at its own sector pace failed on Bearman: out-lap sectors inflate
the median.

The onset is the first yellow of the run-up to a red flag / VSC / safety car
(within RUNUP of it), else the flag itself. In PRACTICE only, a car that stops
with no flag at all (a quiet stop in a run-off area) is also caught when its
last lap is UNFINISHED, it never pitted, and the session ran on for more than
QUIET_STOP — "no flag", the weakest evidence. Not in qualifying: a car knocked
out of Q1 has no recorded in-lap, so it looks exactly like that.

WHAT IT CANNOT SEE, stated so nobody reads the counts as complete:
  * a failure that limps back to the pits (the garage hides it — press only),
  * a stop at the very end of a session (indistinguishable from the flag),
  * which of two cars in a collision was at fault (race control, if it logged
    it, is in data/incidents.csv with session = that session).
Every candidate is checked against the press before it gets a cause; a
candidate the press shows was NOT a stop is kept with status FALSE_ALARM so
the seeder never re-adds it and every card skips it.

NO-SHOWS. A race driver on the session's entry list (the results table) with
no lap at all "did not run" (practice) / "did not take part" (qualifying); in
qualifying, laps but no timed lap is "no time set". FP1 rookie swaps never
appear here: the replaced race driver is not on that session's entry list.
These are CONSEQUENCES as often as causes (Bearman, Spain 2026: crashed in
FP3, rebuilt car, missed qualifying), so the card counts them as running lost,
not as separate incidents.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SESSIONS_DIR = Path("data/sessions")
LITE_DIR = Path("data/sessions_lite")

# Sessions this module covers. Race and Sprint come from the results archives.
NON_RACE = ("Practice 1", "Practice 2", "Practice 3", "Sprint Shootout",
            "Sprint Qualifying", "Qualifying")
QUALI_LIKE = ("Qualifying", "Sprint Qualifying", "Sprint Shootout")

ON_TRACK_WINDOW = 240.0   # s — longest gap between two timing events of a
                          # car that is genuinely running
RUNUP = 90.0              # s — a yellow this close before a red/VSC/SC is
                          # the same incident
QUIET_STOP = 300.0        # s — a no-flag stop must be this far from the end
RETURN_WINDOW = 300.0     # s after the flag — a car caught by it is back in
                          # the pit lane well within this (max 167 s seen)

STOPPED = "Stopped on track"
DID_NOT_RUN = "Did not run"
DID_NOT_TAKE_PART = "Did not take part"
NO_TIME = "No time set"
FALSE_ALARM = "False alarm"          # set by the curator, never by detect()
# status_archive values the seeder writes for this module's rows
STATUSES = (STOPPED, DID_NOT_RUN, DID_NOT_TAKE_PART, NO_TIME)
LOST_RUNNING = (DID_NOT_RUN, DID_NOT_TAKE_PART, NO_TIME)

_FLAG = {"5": "red flag", "6": "VSC", "4": "safety car"}


def _read(season: int, stem: str, session: str, part: str) -> pd.DataFrame | None:
    name = f"{season}__{stem}__{session.replace(' ', '_')}__{part}.parquet"
    for base in (SESSIONS_DIR, LITE_DIR):
        if (base / name).exists():
            try:
                return pd.read_parquet(base / name)
            except Exception:
                return None
    return None


def cached_sessions(season: int) -> list[tuple[str, str]]:
    """(meeting stem, session) for every NON_RACE session with laps cached."""
    out = set()
    for base in (SESSIONS_DIR, LITE_DIR):
        for p in base.glob(f"{season}__*__laps.parquet"):
            parts = p.name.split("__")
            if len(parts) == 4 and parts[2].replace("_", " ") in NON_RACE:
                out.add((parts[1], parts[2].replace("_", " ")))
    return sorted(out)


def _events(laps: pd.DataFrame) -> pd.DataFrame:
    """Every timing event of every car: (code, t, kind, nxt) with kind in
    out / sector / in, sorted by time. `nxt` is the sector the car is in
    AFTER the event (0 once it is in the pits). A sector line crossed after
    the lap's pit entry is the pit-lane timing line, not running: dropped."""
    pit_in = pd.to_numeric(laps["PitIn"], errors="coerce") \
        if "PitIn" in laps.columns else pd.Series(np.nan, index=laps.index)
    rows = []
    for c, kind, nxt in (("PitOut", "out", 1),
                         ("Sector1SessionTime", "sector", 2),
                         ("Sector2SessionTime", "sector", 3),
                         ("Sector3SessionTime", "sector", 1),
                         ("PitIn", "in", 0)):
        if c not in laps.columns:
            continue
        t = pd.to_numeric(laps[c], errors="coerce")
        ok = t.notna()
        if kind == "sector":
            ok &= ~(pit_in.notna() & (t >= pit_in))
        rows.append(pd.DataFrame({"code": laps.loc[ok, "code"], "t": t[ok],
                                  "kind": kind, "nxt": nxt}))
    if not rows:
        return pd.DataFrame(columns=["code", "t", "kind", "nxt"])
    return pd.concat(rows, ignore_index=True).sort_values("t")


def _sector_pace(laps: pd.DataFrame) -> dict:
    """{(code, sector): median seconds}; the field median per sector is the
    fallback under (None, sector)."""
    out = {}
    for k in (1, 2, 3):
        col = f"Sector{k}Time"
        if col not in laps.columns:
            continue
        v = pd.to_numeric(laps[col], errors="coerce")
        out[(None, k)] = float(v.median()) if v.notna().any() else 40.0
        for code, m in v.groupby(laps["code"]).median().items():
            if pd.notna(m):
                out[(code, k)] = float(m)
    return out


def _onsets(ts: pd.DataFrame | None) -> list[tuple[float, float, str]]:
    """(incident onset, flag time, flag) in session seconds for every red
    flag, VSC and safety car. The onset is the start of the yellow that ran
    into the flag when there was one."""
    if ts is None or ts.empty:
        return []
    t = pd.to_numeric(ts["Time"], errors="coerce").tolist()
    st = ts["Status"].astype(str).str.strip().tolist()
    out = []
    for i, (ti, si) in enumerate(zip(t, st)):
        if si not in _FLAG or pd.isna(ti) or (i and st[i - 1] == si):
            continue
        # walk back through the UNBROKEN yellow run into the flag: an earlier
        # yellow that had already gone back to green is a different incident
        # (Baku 2026 FP2: a cleared yellow at 1953 s, then Lindblad's at 1980 s)
        onset, j = ti, i - 1
        while j >= 0 and st[j] == "2" and pd.notna(t[j]) and ti - t[j] <= RUNUP:
            onset, j = t[j], j - 1
        out.append((float(onset), float(ti), _FLAG[si]))
    return out


def detect(season: int, stem: str, session: str) -> pd.DataFrame:
    """One row per (driver, session) event: driver, team, status, laps,
    t_stop (session seconds, stops only), evidence."""
    laps = _read(season, stem, session, "laps")
    if laps is None or laps.empty or "Driver" not in laps.columns:
        return pd.DataFrame()
    laps = laps.copy()
    laps["code"] = laps["Driver"].astype(str).str[:3].str.upper()
    team_of = (laps.dropna(subset=["Team"]).drop_duplicates("code")
               .set_index("code")["Team"].to_dict()) if "Team" in laps else {}
    ev = _events(laps)
    if ev.empty:
        return pd.DataFrame()
    end_t = float(ev["t"].max())
    rows: list[dict] = []

    def _add(code, status, evidence, t_stop=np.nan):
        rows.append({"driver": code, "team": team_of.get(code, ""),
                     "status": status, "laps": int((laps["code"] == code).sum()),
                     "t_stop": t_stop, "evidence": evidence})

    # In qualifying a flag that ENDS Q1 is followed by Q2, so "the session
    # resumed" must mean the driver's own elimination group ran again: else
    # every Q1 exit caught by a Q1-ending red flag "never ran again" (Baku 2023
    # sprint shootout: five false stops). Practice is one group.
    res = _read(season, stem, session, "results")
    group = _segment_groups(res) if session in QUALI_LIKE else {}

    # 1. stopped on track at a red flag / VSC / SC
    stopped = set()
    for t0, t_flag, flag in _onsets(_read(season, stem, session, "track_status")):
        for code, g in ev.groupby("code"):
            if code in stopped:
                continue
            before = g[g["t"] < t0]
            if before.empty:
                continue
            last = before.iloc[-1]
            if last["kind"] == "in" or t0 - last["t"] > ON_TRACK_WINDOW:
                continue
            after = g[g["t"] > t0]
            if (after["kind"] == "sector").any():
                continue                      # ran again: not a stop
            # When the session RESUMED, everyone caught by the flag runs again,
            # so "never ran again" already singles the car out — and a stopped
            # car may still be recovered to the pit lane within minutes (Stroll,
            # Hungary 2026 FP1, suspension failure: pit entry +279 s). Only
            # when the flag ENDED the session does that pit entry have to be
            # told apart from the field driving back under red.
            peers = ev["code"] != code
            if group:
                peers &= ev["code"].map(group).eq(group.get(code, 1))
            resumed = (peers & (ev["kind"] == "sector")
                       & (ev["t"] > t_flag + RETURN_WINDOW)).any()
            if not resumed and (after["t"] <= t_flag + RETURN_WINDOW).any():
                continue                      # caught by it, drove back
            stopped.add(code)
            back = (f"; reached the pit lane {after['t'].min() - t_flag:.0f} s "
                    "after the flag" if not after.empty else "")
            _add(code, STOPPED,
                 f"{flag}: last timed {t0 - last['t']:.0f} s before the "
                 "incident, never ran again"
                 + (" although the session resumed" if resumed else
                    f", no timing for {RETURN_WINDOW:.0f} s after the flag")
                 + back, round(float(last["t"]), 1))

    # 2. practice only: a quiet stop with no flag at all
    if session not in QUALI_LIKE:
        for code, g in ev.groupby("code"):
            if code in stopped:
                continue
            last = g.iloc[-1]
            if last["kind"] == "in" or end_t - last["t"] < QUIET_STOP:
                continue
            mine = laps[laps["code"] == code]
            ln = pd.to_numeric(mine["LapNo"], errors="coerce")
            if ln.notna().sum() == 0:
                continue
            last_lap = mine.loc[ln.idxmax()]
            if (pd.notna(pd.to_numeric(last_lap.get("LapTime"), errors="coerce"))
                    or pd.notna(pd.to_numeric(last_lap.get("PitIn"), errors="coerce"))):
                continue
            stopped.add(code)
            _add(code, STOPPED, f"no flag: unfinished last lap, never pitted, "
                 f"session ran on {end_t - last['t']:.0f} s",
                 round(float(last["t"]), 1))

    # 3. no-shows among the race drivers on the entry list
    if res is not None and not res.empty and "Abbreviation" in res.columns:
        racers = _race_drivers(season, stem)
        timed = set(laps.loc[pd.to_numeric(laps["LapTime"], errors="coerce")
                             .notna(), "code"])
        ran = set(laps["code"])
        for _, r in res.iterrows():
            code = str(r["Abbreviation"]).upper()
            if code in stopped or (racers and code not in racers):
                continue
            if code not in ran:
                status = (DID_NOT_TAKE_PART if session in QUALI_LIKE
                          else DID_NOT_RUN)
            elif session in QUALI_LIKE and code not in timed:
                status = NO_TIME
            else:
                continue
            team_of.setdefault(code, str(r.get("TeamName", "")))
            _add(code, status, "on the entry list, no lap / no timed lap "
                 "in the lap feed")
    return pd.DataFrame(rows)


def _segment_groups(res: pd.DataFrame | None) -> dict[str, int]:
    """Driver -> qualifying segment he was knocked out in (1 = Q1, 2 = Q2,
    3 = reached Q3), from the classification. 20 cars: 15 reach Q2; 22 cars
    (2026): 16. No classified position (no time) counts as a Q1 exit."""
    if res is None or res.empty or "Abbreviation" not in res.columns:
        return {}
    n = len(res)
    q2 = 16 if n >= 22 else 15
    pos_col = (pd.to_numeric(res["Position"], errors="coerce")
               if "Position" in res.columns else pd.Series(np.nan, index=res.index))
    out = {}
    for code, pos in zip(res["Abbreviation"].astype(str).str.upper(), pos_col):
        out[code] = 3 if pos <= 10 else 2 if pos <= q2 else 1
    return out


_RACERS: dict = {}


def _race_drivers(season: int, stem: str) -> set[str]:
    """Drivers in this event's race classification, so a reserve on a
    practice entry list who never ran is not a 'did not run'."""
    if season not in _RACERS:
        p = Path("data/historical_results/race_results_all.parquet")
        if not p.exists():
            _RACERS[season] = {}
        else:
            r = pd.read_parquet(p, columns=["season", "event_name",
                                            "Abbreviation"])
            r = r[r["season"] == season]
            _RACERS[season] = {ev: set(g["Abbreviation"].astype(str))
                               for ev, g in r.groupby("event_name")}
    from f1lib.data_loader import event_name_from_stem
    return _RACERS[season].get(event_name_from_stem(season, stem), set())


def detect_season(season: int) -> pd.DataFrame:
    from f1lib.data_loader import event_name_from_stem
    frames = []
    for stem, session in cached_sessions(season):
        d = detect(season, stem, session)
        if d.empty:
            continue
        d.insert(0, "session", session)
        d.insert(0, "event", event_name_from_stem(season, stem))
        d.insert(0, "season", season)
        frames.append(d)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
