"""Tests for the shared qualifying normaliser and the driver-rating layer.

f1lib/quali_norm.py owns one correction used by two consumers with different
entities (teams in compute_team_pace, drivers in driver_ratings), so the
properties are pinned once here: it removes the Q1→Q3 track evolution, is
not fooled by front-runners cruising in Q1, and refuses rather than guesses
when the round cannot be normalised.

The driver-layer tests cover audit finding 09 — the artifact that mattered
was not the pole anchor (a per-event shift, which the car-event dummy in the
fit absorbs) but the evolution landing INSIDE the teammate contrast, which
is the entire signal the rating is built from.
"""
import numpy as np
import pandas as pd
import pytest

from f1lib import quali_norm as qn


def _round(rows: dict) -> pd.DataFrame:
    """{entity: {"Q1": t, ...}} -> a quali-results-shaped frame."""
    return pd.DataFrame([
        {"driver": e, **{s: times.get(s, np.nan) for s in qn.Q_SESSIONS}}
        for e, times in rows.items()
    ])


def test_removes_the_session_offset():
    """Two identical cars, one knocked out in Q1, must come out level — the
    raw best-of-Q gap puts the Q1 car ~1% behind on track state alone."""
    g = _round({"A": {"Q1": 90.0, "Q2": 89.1},
                "B": {"Q1": 90.0, "Q2": 89.1},
                "C": {"Q1": 90.0}})
    out = qn.normalised_gap_pct(g, "driver")
    assert out
    assert out["C"] == pytest.approx(out["A"], abs=0.02)


def test_q1_cruising_does_not_flatter_eliminated_entrants():
    """MS-05, at the level the shared module owns it. Front-runners bank a
    lap on used rubber in Q1; an offset averaged over that mixture overstates
    the evolution and hands the excess to whoever only ran Q1."""
    evo, sandbag = 1.004, 1.008
    true_q2 = {"A": 88.0, "B": 88.1, "C": 88.2,      # advance to Q3
               "D": 89.0, "E": 89.1, "F": 89.2}      # out in Q2
    g = _round({
        **{t: {"Q1": v * evo * sandbag, "Q2": v, "Q3": v / evo}
           for t, v in true_q2.items() if t in ("A", "B", "C")},
        **{t: {"Q1": v * evo, "Q2": v}
           for t, v in true_q2.items() if t in ("D", "E", "F")},
        "G": {"Q1": 90.0 * evo},
    })
    out = qn.normalised_gap_pct(g, "driver")
    assert out
    assert out["G"] == pytest.approx(+1.124, abs=0.10)   # no bonus
    assert out["A"] == pytest.approx(-1.124, abs=0.10)   # no self-penalty


def test_teammate_contrast_is_freed_of_track_evolution():
    """The property the driver rating actually stands on: two teammates of
    EQUAL pace, one eliminated in Q1 and one reaching Q3, must show no
    contrast. Uncorrected they differ by the full evolution."""
    evo = 1.005
    g = _round({
        # equal-pace teammates, different exits
        "FAST_EXIT": {"Q1": 90.0 * evo * evo},
        "FAST_Q3": {"Q1": 90.0 * evo * evo, "Q2": 90.0 * evo, "Q3": 90.0},
        # a spread of other cars so the offsets are identified
        "M1": {"Q1": 90.5 * evo * evo, "Q2": 90.5 * evo},
        "M2": {"Q1": 90.6 * evo * evo, "Q2": 90.6 * evo},
        "M3": {"Q1": 90.7 * evo * evo, "Q2": 90.7 * evo},
        "S1": {"Q1": 91.5 * evo * evo},
        "S2": {"Q1": 91.6 * evo * evo},
    })
    out = qn.normalised_gap_pct(g, "driver")
    assert out
    assert out["FAST_EXIT"] == pytest.approx(out["FAST_Q3"], abs=0.05), (
        "equal teammates split across Q-sessions still show a contrast")

    raw = g[list(qn.Q_SESSIONS)].min(axis=1)
    raw_gap = (raw / raw.min() - 1) * 100
    assert abs(raw_gap.iloc[0] - raw_gap.iloc[1]) > 0.9, (
        "expected the uncorrected measure to show a large false contrast")


def test_refuses_when_not_identifiable():
    assert qn.normalised_gap_pct(_round({"A": {"Q1": 90.0}}), "driver") == {}


def test_rejects_implausible_rounds():
    g = _round({"A": {"Q1": 90.0, "Q2": 89.0},
                "B": {"Q1": 90.2, "Q2": 89.2},
                "C": {"Q1": 400.0}})
    assert qn.normalised_gap_pct(g, "driver") == {}


def test_n_sessions_counts_participation():
    g = _round({"A": {"Q1": 90.0, "Q2": 89.1, "Q3": 89.0},
                "B": {"Q1": 90.0}})
    assert qn.n_sessions(g, "driver") == {"A": 3, "B": 1}


# ── driver-rating layer ──────────────────────────────────────

def test_input_clip_is_measured_within_the_car():
    """A backmarker is slow because of its CAR, and the car-event dummy
    already absorbs that — clipping on the absolute gap discarded those rows
    wholesale (14% of quali rows) and took their teammate contrasts with
    them. The clip must key off deviation from the driver's own car."""
    from f1lib.driver_ratings import MAX_TEAMMATE_DEV, DriverRatings

    assert set(MAX_TEAMMATE_DEV) == {"race", "quali"}
    # a slow-but-consistent pair must survive; a blown session must not
    rows = []
    for i, ev in enumerate(["E1", "E2", "E3", "E4"]):
        rows += [
            # backmarker car: both drivers ~+3% on the field, close together
            {"season": 2026, "round": i + 1, "event": ev, "team": "Slow",
             "driver": "SLOW_A", "kind": "quali", "gap_pct": 3.0},
            {"season": 2026, "round": i + 1, "event": ev, "team": "Slow",
             "driver": "SLOW_B", "kind": "quali", "gap_pct": 3.2},
            {"season": 2026, "round": i + 1, "event": ev, "team": "Fast",
             "driver": "FAST_A", "kind": "quali", "gap_pct": -1.0},
            {"season": 2026, "round": i + 1, "event": ev, "team": "Fast",
             "driver": "FAST_B", "kind": "quali", "gap_pct": -0.8},
        ]
    df = pd.DataFrame(rows)
    df["event_idx"] = df["round"] - 1
    dr = DriverRatings.__new__(DriverRatings)
    eff = dr._fit(df, as_of_idx=3, kind="quali")
    got = set(eff["driver"])
    assert {"SLOW_A", "SLOW_B"} <= got, (
        "a slow CAR's drivers were clipped out; the clip is reading car pace "
        "as a bad session")
    # and the slow pair's contrast is preserved (A ahead of B by ~0.2)
    e = eff.set_index("driver")["effect"]
    assert e["SLOW_A"] < e["SLOW_B"]


def test_shipped_driver_table_is_field_median_centred():
    """Both kinds must straddle zero. A table anchored on pole or on the
    fastest driver is non-negative by construction — the tell that the
    moving baseline came back."""
    path = "data/driver_pace_by_event.csv"
    try:
        d = pd.read_csv(path)
    except OSError:
        pytest.skip("driver pace table not built")
    for kind in ("quali", "race"):
        g = d[d["kind"] == kind]["gap_pct"]
        if g.empty:
            continue
        assert g.min() < 0 < g.max(), f"{kind} gaps are not field-centred"
        assert abs(g.median()) < 0.35
