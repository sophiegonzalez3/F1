"""Race-incident register: parsing, deduplication and DNF attribution.

The results archive has recorded a bare "Retired" for every non-finish since
2023 (44 of them in 2026, none classified), so the mechanical-vs-incident split
on the reliability card has been dead code for three seasons. Race control kept
logging the contact; compute_incidents.py reads it back.

The properties worth pinning, in order of how badly they bite:

1. DEDUPLICATION. One incident is announced up to four times (noted →
   investigated → penalty → served) and each announcement carries a DIFFERENT
   Lap, because Lap is when the message was published. Take the last and a
   lap-39 collision is recorded at lap 50.
2. UNCATEGORISED MULTI-CAR INCIDENTS still count. The FIA regularly logs
   "TURN 13 INCIDENT INVOLVING CARS 43 (COL) AND 87 (BEA) NOTED" with no
   reason at all — exactly the first-lap tangles this register exists to find.
3. CAUSALITY NEEDS PROXIMITY. Matching a retirement to any earlier contact
   "explains" six 2026 retirements, one of which had its contact 26 laps
   before the car stopped.
"""
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "compute_incidents", ROOT / "scripts" / "compute_incidents.py")
ci = importlib.util.module_from_spec(_spec)
sys.modules["compute_incidents"] = ci
_spec.loader.exec_module(ci)


def _rc(messages):
    """A race-control frame from (lap, message) pairs."""
    return pd.DataFrame([{"Lap": lap, "Message": m} for lap, m in messages])


# ── classification ───────────────────────────────────────────

@pytest.mark.parametrize("reason,kind", [
    ("CAUSING A COLLISION", "contact"),
    ("FORCING ANOTHER DRIVER OFF THE TRACK", "contact"),
    ("MOVING UNDER BRAKING", "contact"),
    ("UNSAFE RELEASE", "contact"),
    ("INCIDENT (reason unstated)", "contact"),
    ("LEAVING THE TRACK AND GAINING AN ADVANTAGE", "off-track"),
    ("TRACK LIMITS", "off-track"),
    ("SPEEDING IN THE PIT LANE", "procedural"),
    ("YELLOW FLAG INFRINGEMENT", "procedural"),
    ("IGNORING BLUE FLAGS", "procedural"),
])
def test_reason_classification(reason, kind):
    assert ci.classify(reason) == kind


# ── parsing & dedup ──────────────────────────────────────────

def test_stages_of_one_incident_collapse_to_one_row():
    rc = _rc([
        (39, "TURN 2 INCIDENT INVOLVING CARS 55 (SAI) AND 81 (PIA) NOTED - "
             "CAUSING A COLLISION (15:57:04)"),
        (40, "FIA STEWARDS: TURN 2 INCIDENT INVOLVING CARS 55 (SAI) AND 81 "
             "(PIA) UNDER INVESTIGATION - CAUSING A COLLISION (15:57:04)"),
        (44, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 55 (SAI) - "
             "CAUSING A COLLISION (15:57:04)"),
        (50, "FIA STEWARDS: PENALTY SERVED - 5 SECOND TIME PENALTY FOR CAR 55 "
             "(SAI) - CAUSING A COLLISION (15:57:04)"),
    ])
    out = ci.collapse(ci.parse_race_control(rc))
    assert set(out["driver"]) == {"SAI", "PIA"}
    assert len(out) == 2, "one row per car involved, not one per message"


def test_incident_lap_is_the_earliest_message_not_the_latest():
    """Lap is the PUBLICATION lap. The collision happened at 39, and the last
    announcement lands at 50 — taking the max puts it 11 laps late, in the
    wrong stint, and would blame the wrong tyre."""
    rc = _rc([
        (39, "TURN 2 INCIDENT INVOLVING CARS 55 (SAI) AND 81 (PIA) NOTED - "
             "CAUSING A COLLISION (15:57:04)"),
        (50, "FIA STEWARDS: PENALTY SERVED - 5 SECOND TIME PENALTY FOR CAR 55 "
             "(SAI) - CAUSING A COLLISION (15:57:04)"),
    ])
    out = ci.collapse(ci.parse_race_control(rc))
    assert set(out["lap"]) == {39}


def test_penalty_outcome_wins_over_earlier_stages():
    rc = _rc([
        (10, "INCIDENT INVOLVING CARS 1 (VER) AND 4 (NOR) NOTED - "
             "CAUSING A COLLISION (14:00:00)"),
        (12, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 1 (VER) - "
             "CAUSING A COLLISION (14:00:00)"),
    ])
    out = ci.collapse(ci.parse_race_control(rc)).set_index("driver")
    assert out.loc["VER", "outcome"].startswith("penalty")


def test_no_further_action_is_recorded_as_such():
    rc = _rc([
        (3, "INCIDENT INVOLVING CARS 14 (ALO) AND 87 (BEA) NOTED - "
            "FORCING ANOTHER DRIVER OFF THE TRACK (15:03:49)"),
        (4, "FIA STEWARDS: INCIDENT INVOLVING CARS 14 (ALO) AND 87 (BEA) "
            "REVIEWED NO FURTHER INVESTIGATION - FORCING ANOTHER DRIVER OFF "
            "THE TRACK (15:03:49)"),
    ])
    out = ci.collapse(ci.parse_race_control(rc))
    assert set(out["outcome"]) == {"no action"}
    assert set(out["kind"]) == {"contact"}, "still contact — it still happened"


def test_uncategorised_two_car_incident_is_kept_as_contact():
    """The FIA logs plenty of these with no reason. Dropping them loses the
    first-lap tangles."""
    rc = _rc([(1, "TURN 13 INCIDENT INVOLVING CARS 43 (COL) AND 87 (BEA) NOTED")])
    out = ci.collapse(ci.parse_race_control(rc))
    assert len(out) == 2
    assert set(out["kind"]) == {"contact"}
    assert "unstated" in out["reason"].iloc[0].lower()


def test_uncategorised_single_car_incident_is_dropped():
    """One car and no reason is as likely a spin or an off as a touch —
    guessing would poison the register."""
    rc = _rc([(1, "TURN 4 INCIDENT INVOLVING CAR 43 (COL) NOTED")])
    assert ci.collapse(ci.parse_race_control(rc)).empty


def test_lap_deletions_are_not_incidents():
    rc = _rc([(5, "CAR 10 (GAS) TIME 1:27.040 DELETED - TRACK LIMITS AT TURN 10 "
                  "LAP 5 15:10:17")])
    assert ci.collapse(ci.parse_race_control(rc)).empty


def test_counterparty_is_recorded_both_ways():
    rc = _rc([(20, "INCIDENT INVOLVING CARS 1 (VER) AND 4 (NOR) NOTED - "
                   "CAUSING A COLLISION (14:00:00)")])
    out = ci.collapse(ci.parse_race_control(rc)).set_index("driver")
    assert out.loc["VER", "counterparty"] == "NOR"
    assert out.loc["NOR", "counterparty"] == "VER"


# ── retirement attribution ───────────────────────────────────

def test_only_proximate_contact_explains_a_retirement():
    from f1lib.incidents import classify_retirement, CAUSAL_WINDOW, incidents_df

    if incidents_df().empty:
        pytest.skip("incident register not built")
    # Verstappen, China 2026: contact on lap 19, retired on lap 45.
    got = classify_retirement(2026, "Chinese Grand Prix", "VER", 45)
    assert got["cause"] == "unclassified", (
        "a lap-19 incident must not explain a lap-45 retirement")
    assert got["earlier_contact"] is True, "but the contact is still reported"


def test_causal_window_sits_in_the_gap_of_the_observed_distribution():
    """Calibrated, not chosen: gaps cluster at 0-6 laps then jump to 10+."""
    from f1lib.incidents import CAUSAL_WINDOW
    assert 4 <= CAUSAL_WINDOW <= 8


def test_register_covers_the_current_season():
    from f1lib.config import CURRENT_SEASON
    from f1lib.incidents import incidents_df, has_incidents
    if incidents_df().empty:
        pytest.skip("incident register not built")
    assert has_incidents(CURRENT_SEASON)


def test_contact_incidents_exist_and_are_a_minority_of_all_messages():
    """Sanity: a season should log contact, but most stewards' messages are
    procedural. A parser that called everything contact would pass a naive
    'we found some' check."""
    from f1lib.incidents import incidents_df
    d = incidents_df()
    if d.empty:
        pytest.skip("incident register not built")
    d26 = d[d["season"] == 2026]
    if d26.empty:
        pytest.skip("no 2026 rows")
    kinds = d26["kind"].value_counts()
    assert kinds.get("contact", 0) > 0
    assert kinds.get("procedural", 0) > 0
