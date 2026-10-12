"""Stops outside the race (f1lib/session_stops.py), on synthetic sessions.

Each case is a real one from 2026, reduced to the timing events that decided
it. The detector reads only the lap feed, the track-status table and the
entry list, so those three are all a case needs.

1. A RED FLAG THAT ENDS THE SESSION. Nobody runs again, so "never ran again"
   is true of everyone; what singles the stopped car out is that it logs no
   timing at all afterwards, while the cars caught by the flag log a pit entry
   within minutes (Spain FP3: Bearman stopped; Gasly +137 s in the pit lane).
2. A RED FLAG THE SESSION RESUMES FROM. Everyone caught by it runs again, so
   never running again is enough - and the stopped car may reach the pit lane
   within minutes on a truck (Hungary FP1: Stroll +279 s).
3. THE ONSET IS THE YELLOW THAT RAN INTO THE FLAG, not an earlier yellow that
   had already cleared (Baku FP2: Lindblad).
4. A sector line crossed after the pit entry is the pit-lane timing line, not
   running.
5. NO-SHOWS come from the entry list: a race driver with no lap "did not
   run"; an FP1 rookie swap leaves the race driver OFF the entry list and is
   not a no-show.
"""
import numpy as np
import pandas as pd
import pytest

import f1lib.session_stops as ss


def _lap(code, start, s1, s2, s3, lap_time=np.nan, pit_in=np.nan,
         pit_out=np.nan, lap_no=1, team="Team"):
    return {"Driver": f"{code}-{team}", "Team": team, "LapNo": lap_no,
            "LapStartTime": start, "Sector1SessionTime": s1,
            "Sector2SessionTime": s2, "Sector3SessionTime": s3,
            "Sector1Time": 30.0, "Sector2Time": 30.0, "Sector3Time": 30.0,
            "LapTime": lap_time, "PitIn": pit_in, "PitOut": pit_out}


def _ts(*rows):
    return pd.DataFrame([{"Time": t, "Status": s} for t, s in rows])


def _session(monkeypatch, laps, ts, results=None, racers=None):
    data = {"laps": pd.DataFrame(laps), "track_status": ts,
            "results": results}
    monkeypatch.setattr(ss, "_read",
                        lambda season, stem, session, part: data.get(part))
    monkeypatch.setattr(ss, "_race_drivers", lambda season, stem: racers or set())


def _stopped(d):
    return set(d.loc[d["status"] == ss.STOPPED, "driver"]) if not d.empty else set()


def test_session_ending_red_flag_singles_out_the_car_that_logs_nothing(monkeypatch):
    laps = [
        # BEA: last sector 40 s before the yellow, then nothing at all
        _lap("BEA", 300, 330, 360, 395, 95),
        # GAS: mid-sector at the flag, drives back - pit entry +137 s
        _lap("GAS", 380, 410, 426, np.nan, np.nan, pit_in=585, lap_no=2),
    ]
    _session(monkeypatch, laps, _ts((0, "1"), (435, "2"), (448, "5")))
    assert _stopped(ss.detect(2026, "X", "Practice 3")) == {"BEA"}


def test_resumed_session_needs_only_never_ran_again(monkeypatch):
    laps = [
        # STR: stopped, recovered to the pit lane +279 s, never ran again
        _lap("STR", 2850, 2880, 2916, 2942, 92),
        _lap("STR", 2942, np.nan, np.nan, np.nan, pit_in=3284, lap_no=2),
        # VER: caught by the flag, back in the pits, then runs again
        _lap("VER", 2900, 2930, 2960, 2990, 90),
        _lap("VER", 2990, np.nan, np.nan, np.nan, pit_in=3100, lap_no=2),
        _lap("VER", 3500, 3530, 3560, 3590, 90, pit_out=3480, lap_no=3),
    ]
    _session(monkeypatch, laps, _ts((0, "1"), (2985, "2"), (3005, "5"),
                                     (3132, "1")))
    assert _stopped(ss.detect(2026, "X", "Practice 1")) == {"STR"}


def test_onset_is_the_yellow_that_ran_into_the_flag(monkeypatch):
    laps = [
        # LIN crosses a line during an EARLIER yellow that cleared, then
        # crashes; the red follows a second, separate yellow
        _lap("LIN", 1880, 1917, 1955, np.nan),
    ]
    _session(monkeypatch, laps,
             _ts((0, "1"), (1953, "2"), (1970, "1"), (1980, "2"), (1996, "5")))
    assert _stopped(ss.detect(2026, "X", "Practice 2")) == {"LIN"}
    assert ss._onsets(_ts((1953, "2"), (1970, "1"), (1980, "2"),
                          (1996, "5")))[0][0] == 1980


def test_pit_lane_timing_line_is_not_running(monkeypatch):
    laps = [
        # ALB pits at 1535; the sector-3 stamp at 1536 is the pit-lane line.
        # He is in the garage when the later red flag comes out.
        _lap("ALB", 1430, 1460, 1494, 1536, 106, pit_in=1535, lap_no=2),
        _lap("HAM", 2100, 2153, 2186, np.nan, lap_no=5),
    ]
    _session(monkeypatch, laps, _ts((0, "1"), (2225, "2"), (2242, "5")))
    assert _stopped(ss.detect(2026, "X", "Practice 3")) == {"HAM"}


def test_quiet_stop_rule_never_runs_in_qualifying(monkeypatch):
    # a Q1 exit has no recorded in-lap - it must not read as a stop
    laps = [_lap("STR", 1900, 1930, 1960, 1990, 90),
            _lap("VER", 2000, 2030, 2060, 2090, 90),
            _lap("VER", 3900, 3930, 3960, 3990, 90, lap_no=2)]
    _session(monkeypatch, laps, _ts((0, "1")))
    assert _stopped(ss.detect(2026, "X", "Qualifying")) == set()


@pytest.mark.parametrize("session,expected", [
    ("Practice 2", ss.DID_NOT_RUN), ("Qualifying", ss.DID_NOT_TAKE_PART)])
def test_entry_list_no_show(monkeypatch, session, expected):
    laps = [_lap("VER", 100, 130, 160, 190, 90)]
    res = pd.DataFrame({"Abbreviation": ["VER", "STR"],
                        "TeamName": ["Red Bull", "Aston Martin"]})
    _session(monkeypatch, laps, _ts((0, "1")), res, racers={"VER", "STR"})
    d = ss.detect(2026, "X", session)
    assert d.set_index("driver")["status"].to_dict() == {"STR": expected}


def test_fp1_rookie_swap_is_not_a_no_show(monkeypatch):
    # the replaced race driver (SAI) is not on FP1's entry list at all
    laps = [_lap("BRO", 100, 130, 160, 190, 90)]
    res = pd.DataFrame({"Abbreviation": ["BRO"], "TeamName": ["Williams"]})
    _session(monkeypatch, laps, _ts((0, "1")), res, racers={"SAI", "ALB"})
    assert ss.detect(2026, "X", "Practice 1").empty


def test_false_alarm_is_never_a_detector_status():
    """'False alarm' is the curator's verdict on a detected row; the seeder
    must never write it, and every card skips it."""
    assert ss.FALSE_ALARM not in ss.STATUSES
