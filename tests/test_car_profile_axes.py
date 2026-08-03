"""Validation tests for the car-concept axes (tabs/car_profile.py).

The project's rule is that a derived axis must be validated before it ships,
and that split-half reliability alone is not enough — it cannot tell "measures
the trait reliably" from "reliably measures something else". These tests hold
the shipped axes to the claims their own descriptions make, against the
shipped data, so a claim cannot quietly stop being true.

The `save_pct` tests exist because an external review recommended re-scoring
that axis as a deficiency ("lower is better", renamed Energy deficit). The
data does not support it, and these pin the evidence for leaving it unscored
so the question does not get re-litigated from memory.
"""
import numpy as np
import pandas as pd
import pytest

from f1lib.pace_features import canon

PROFILE = "data/car_profile.csv"
PACE = "data/team_pace_by_event.csv"
RESULTS = "data/historical_results/race_results_all.parquet"


def _profile():
    try:
        d = pd.read_csv(PROFILE)
    except OSError:
        pytest.skip("car_profile.csv not built")
    if d.empty:
        pytest.skip("car_profile.csv empty")
    return d


def _corr(a: pd.Series, b: pd.Series) -> float:
    m = a.notna() & b.notna()
    if m.sum() < 30:
        pytest.skip("not enough overlapping rows")
    return float(np.corrcoef(a[m], b[m])[0, 1])


def test_unscored_axes_declare_no_direction():
    """An axis rendered neutral must carry better=None, and a scored axis
    must carry a real direction — the cell colour and the metadata cannot
    disagree."""
    from tabs.car_profile import AXES

    for col, label, unit, better, rel, desc in AXES:
        assert better in (True, False, None)
        if better is None:
            assert "not" in desc.lower() and "scored" in desc.lower(), (
                f"{label} renders neutral but its description never says why")


def test_save_pct_is_not_associated_with_being_slower():
    """The reason Energy saving stays unscored. If coasting more genuinely
    cost lap time, this would fire and the axis should be re-scored as a
    deficiency — which is exactly what an external review recommended on
    reasoning alone."""
    d = _profile()
    try:
        pace = pd.read_csv(PACE)
    except OSError:
        pytest.skip("pace table not built")
    pace["team"] = pace["team"].map(canon)
    m = d.merge(pace[["season", "event", "team", "race_pace_pct"]],
                on=["season", "event", "team"], how="left")
    m = m.dropna(subset=["save_pct", "race_pace_pct"])
    if len(m) < 50:
        pytest.skip("not enough joined rows")

    assert abs(_corr(m["save_pct"], m["race_pace_pct"])) < 0.20, (
        "Energy saving now tracks race pace — re-examine whether it should "
        "be scored as a deficiency rather than left neutral")

    # the strongest form: a team coasting more than ITS OWN average
    for c in ("save_pct", "race_pace_pct"):
        m[c + "_w"] = m[c] - m.groupby(["season", "team"])[c].transform("mean")
    assert abs(_corr(m["save_pct_w"], m["race_pace_pct_w"])) < 0.20, (
        "within a team, coasting more now tracks being slower")


def test_save_pct_is_not_a_traffic_artifact():
    """The other reading that would invalidate the axis: that it just marks
    cars stuck in traffic, which is track position and not a car property."""
    d = _profile()
    try:
        r = pd.read_parquet(RESULTS)
    except OSError:
        pytest.skip("results archive not built")
    r["team"] = r["TeamName"].map(canon)
    pos = (r.groupby(["season", "event_name", "team"])["Position"].median()
           .rename("med_pos").reset_index()
           .rename(columns={"event_name": "event"}))
    m = d.merge(pos, on=["season", "event", "team"], how="left")
    m = m.dropna(subset=["save_pct", "med_pos"])
    assert abs(_corr(m["save_pct"], m["med_pos"])) < 0.25, (
        "Energy saving now tracks finishing position — it may be measuring "
        "traffic exposure rather than energy management")


def test_axes_are_not_measuring_the_same_thing():
    """Five axes are only worth five columns if they are distinct. Anything
    approaching collinearity means one of them is redundant."""
    d = _profile()
    cols = [c for c in ("straight_kmh", "corner_pct", "fade_pct", "save_pct",
                        "deg_spl") if c in d.columns]
    corr = d[cols].corr().abs()
    np.fill_diagonal(corr.values, 0.0)
    worst = corr.max().max()
    pair = corr.stack().idxmax()
    assert worst < 0.85, f"{pair} are nearly the same measure (r={worst:.2f})"
