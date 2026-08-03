"""Tests for the weekend decomposition (f1lib/weekend_decomp.py).

The card's one non-negotiable property is pinned first: the components must
sum EXACTLY to actual − expected, because a waterfall that doesn't close is a
chart lying about arithmetic. The seconds→points conversion's sanity rules
(backmarker stops price to zero, position value is measured off the archive's
gap-to-winner column) are pinned alongside.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from f1lib.weekend_decomp import (
    _COMPONENTS, _exp_points, _exp_points_no_own_dnf, _is_finished,
    _points_slope, _points_vector, _position_seconds, decomp_df,
)

ROOT = Path(__file__).resolve().parents[1]


# ── points machinery ─────────────────────────────────────────

def test_points_vector_scores_the_table_and_zeroes_dnfs():
    finish = np.array([[1, 2, 11], [3, 1, 10]])
    dnf = np.array([[False, False, False], [False, True, False]])
    pts = _points_vector(finish, dnf)
    assert pts.tolist() == [[25, 18, 0], [15, 0, 1]]


def test_exp_points_is_the_sim_mean():
    sim = {"drivers": ["A", "B"],
           "finish": np.array([[1, 2], [2, 1]]),
           "dnf": np.zeros((2, 2), dtype=bool)}
    e = _exp_points(sim)
    assert e["A"] == pytest.approx((25 + 18) / 2)
    assert e["B"] == pytest.approx((18 + 25) / 2)


def test_no_own_dnf_conditions_on_the_right_driver():
    sim = {"drivers": ["A", "B"],
           "finish": np.array([[1, 2], [2, 1], [5, 1]]),
           "dnf": np.array([[False, False], [True, False], [False, False]])}
    # A's no-DNF sims are rows 0 and 2 → mean of P1, P5
    assert _exp_points_no_own_dnf(sim, "A") == pytest.approx((25 + 10) / 2)
    assert _exp_points_no_own_dnf(sim, "missing") == 0.0


def test_points_slope_zero_outside_the_points():
    """A P16 team's pit-stop seconds must convert to ~0 points — the slope is
    what makes the seconds→points pricing honest for backmarkers."""
    assert _points_slope(16) == 0.0
    assert _points_slope(3) == pytest.approx((18 - 12) / 2)
    assert _points_slope(float("nan")) == 0.0


def test_position_seconds_reads_gap_to_winner_semantics():
    """Archive Time = total for P1, gap TO WINNER for others. Consecutive
    diffs of the sorted gaps are the inter-car gaps; the winner's own total
    must never enter."""
    res = pd.DataFrame({
        "Status": ["Finished"] * 5 + ["Lapped"],
        "Position": [1, 2, 3, 4, 5, 6],
        "Time": [5996.0, 4.0, 10.0, 13.0, 18.0, 30.0],
    })
    # gaps: 4 (P1→P2), 6, 3, 5 → median 4.5;  the Lapped row is excluded
    assert _position_seconds(res) == pytest.approx(4.5)


def test_is_finished_vocabulary():
    s = pd.Series(["Finished", "Lapped", "+1 Lap", "Retired",
                   "Did not start", None])
    assert _is_finished(s).tolist() == [True, True, True, False, False, False]


# ── the shipped table ────────────────────────────────────────

def test_decomposition_closes_exactly():
    """exp_points + Σ components == actual_points on every shipped row (the
    residual is closed-form, so any gap means the writer and reader drifted)."""
    d = decomp_df()
    if d.empty:
        pytest.skip("weekend_decomp.csv not built")
    gap = (d["exp_points"] + d[list(_COMPONENTS)].sum(axis=1)
           - d["actual_points"]).abs()
    assert gap.max() < 0.05, "components no longer sum to actual − expected"


@pytest.mark.filterwarnings("ignore::FutureWarning")
def test_upgrade_package_widens_the_prior_variance_only():
    """A declared performance package must make the team's prior WIDER (less
    predictable) and must never move its mean (direction unknown). Everyone
    else's state stays untouched."""
    from f1lib.pace_model import PaceModel

    if not (ROOT / "data" / "team_pace_by_event.csv").exists() \
            or not (ROOT / "data" / "upgrades.csv").exists():
        pytest.skip("tables not built")
    u = pd.read_csv(ROOT / "data" / "upgrades.csv", encoding="utf-8-sig")
    perf = u[u["category"] == "Performance"]
    if perf.empty:
        pytest.skip("no performance upgrades recorded")
    # the biggest package on record is the sharpest test
    season, event, team = (perf.groupby(["season", "event", "team"]).size()
                           .idxmax())
    m_on = PaceModel()
    m_off = PaceModel(upgrade_var_per_item=0.0)
    on = m_on.predict_weekend(int(season), event)["prior"]
    off = m_off.predict_weekend(int(season), event)["prior"]
    key = ["team", "kind"]
    j = on.set_index(key).join(off.set_index(key), rsuffix="_off")
    t = j.loc[team]
    assert (t["var"] > t["var_off"]).all(), "package did not widen the prior"
    assert (j["mean"] - j["mean_off"]).abs().max() < 1e-9, \
        "upgrade widening moved a prior mean"


def test_shipped_table_covers_the_current_season():
    d = decomp_df()
    if d.empty:
        pytest.skip("weekend_decomp.csv not built")
    latest = d[d["season"] == d["season"].max()]
    assert latest.groupby("event").ngroups >= 1
    # a decomposed event carries the full field, not a fragment
    assert (latest.groupby("event")["team"].count() >= 8).all()
