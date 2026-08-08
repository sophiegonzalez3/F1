"""Guards for the outcome scorecard.

Every claim about the forecaster now rests on these functions, so they get
tests of their own. Two are about correctness; the other two are about not
fooling ourselves.

1. THE GRID BASELINE MUST BE LEAK-FREE. It is the reference the model is
   judged against, so if it were fitted on the race being scored it would
   flatter itself and make the model look worse than it is.

2. THE BOOTSTRAP MUST CLUSTER ON RACES. One result moves all ~20 of a race's
   rows together. Treating them as independent turns a 0.005 Brier gap into
   a confident finding — which is exactly how the 2026-only run appeared to
   show the model beating the market before five seasons overturned it.
"""
import numpy as np
import pandas as pd
import pytest

from scripts.backtest_race_forecast import (TARGETS, add_climatology,
                                            add_grid_baseline,
                                            bootstrap_compare, brier, logloss,
                                            skill)


# ─────────────────────────────────────────────────────────────
# scoring primitives
# ─────────────────────────────────────────────────────────────

def test_brier_is_mean_squared_error():
    assert brier([1, 0], [1, 0]) == 0.0
    assert brier([0, 1], [1, 0]) == 1.0
    assert brier([0.5, 0.5], [1, 0]) == pytest.approx(0.25)


def test_logloss_rewards_confident_correctness():
    assert logloss([0.99], [1]) < logloss([0.6], [1]) < logloss([0.4], [1])


def test_logloss_is_finite_on_a_confident_miss():
    """An unclipped log score returns inf the first time a 0.0 comes true,
    which silently destroys a whole season's mean."""
    assert np.isfinite(logloss([0.0], [1])) and np.isfinite(logloss([1.0], [0]))


def test_skill_is_fraction_of_reference_error_removed():
    assert skill(0.05, 0.10) == pytest.approx(0.5)
    assert skill(0.10, 0.10) == pytest.approx(0.0)
    assert np.isnan(skill(0.05, 0.0))


def test_climatology_is_the_field_base_rate():
    d = pd.DataFrame({"n_starters": [20, 20]})
    d = add_climatology(d)
    assert d["clim_win"].iloc[0] == pytest.approx(1 / 20)
    assert d["clim_podium"].iloc[0] == pytest.approx(3 / 20)
    assert d["clim_points"].iloc[0] == pytest.approx(10 / 20)


def test_climatology_handles_a_field_smaller_than_the_threshold():
    """A 2-car field cannot have a 3-car podium; the probability is 1.0, not
    1.5."""
    d = add_climatology(pd.DataFrame({"n_starters": [2]}))
    assert d["clim_podium"].iloc[0] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────
# leak-freedom
# ─────────────────────────────────────────────────────────────

def _synthetic(n_races=40, n_drivers=20, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(n_races):
        grid = rng.permutation(n_drivers) + 1
        for i, g in enumerate(grid):
            fin = g
            rows.append({"season": 2020 + r // 20, "round": r % 20 + 1,
                         "event": f"E{r}", "driver": f"D{i}", "grid": g,
                         "n_starters": n_drivers, "finish_actual": fin,
                         "win_actual": int(fin <= 1),
                         "podium_actual": int(fin <= 3),
                         "points_actual": int(fin <= 10)})
    return pd.DataFrame(rows)


def test_grid_baseline_never_sees_the_race_it_scores():
    """Flip the LAST race's outcomes completely. A leak-free baseline's
    predictions for every earlier race must be untouched."""
    d = _synthetic()
    base = add_grid_baseline(d.copy())

    tampered = d.copy()
    last = tampered["event"] == tampered["event"].iloc[-1]
    for name, _c, _m in TARGETS:
        tampered.loc[last, f"{name}_actual"] = 1 - tampered.loc[last, f"{name}_actual"]
    after = add_grid_baseline(tampered)

    earlier = base["event"] != base["event"].iloc[-1]
    for name, _c, _m in TARGETS:
        a = base.loc[earlier, f"gridb_{name}"].fillna(-1).values
        b = after.loc[earlier, f"gridb_{name}"].fillna(-1).values
        assert np.allclose(a, b), (
            f"gridb_{name} for earlier races changed when a LATER race's "
            f"outcome was altered - the baseline is reading the future")


def test_grid_baseline_declines_to_predict_without_enough_history():
    """Early races have no window to fit on. Better a NaN, which the scorer
    drops, than a confident number from four data points."""
    d = add_grid_baseline(_synthetic(n_races=4))
    assert d["gridb_win"].isna().all()


# ─────────────────────────────────────────────────────────────
# inference
# ─────────────────────────────────────────────────────────────

def _paired(n_races, edge, seed=1):
    """Races where `p` is better than `q` by a fixed margin on every row."""
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(n_races):
        for i in range(20):
            y = int(rng.random() < 0.15)
            rows.append({"season": 2024, "event": f"E{r}", "y_actual": y,
                         "p": np.clip(0.15 + edge * (y - 0.15), 0, 1),
                         "q": 0.15})
    return pd.DataFrame(rows)


def test_bootstrap_detects_a_real_difference():
    r = bootstrap_compare(_paired(60, 0.6), "p", "q", "y_actual", n_boot=2000)
    assert r["significant"] and r["diff"] < 0 and r["hi"] < 0


def test_bootstrap_calls_a_null_difference_insignificant():
    d = _paired(60, 0.0)
    r = bootstrap_compare(d, "p", "q", "y_actual", n_boot=2000)
    assert not r["significant"]


def test_bootstrap_clusters_on_races_not_driver_races():
    """The interval must widen when the same rows are grouped into FEWER
    races. If clustering were ignored, both would give the same CI — and the
    row-level one would be far too narrow to be honest."""
    d = _paired(40, 0.25)
    many = bootstrap_compare(d, "p", "q", "y_actual", n_boot=4000)
    one_per_row = d.copy()
    one_per_row["event"] = [f"E{i}" for i in range(len(d))]
    rows = bootstrap_compare(one_per_row, "p", "q", "y_actual", n_boot=4000)
    assert (many["hi"] - many["lo"]) > (rows["hi"] - rows["lo"]), (
        "clustering by race did not widen the interval - the bootstrap is "
        "treating 20 correlated driver-rows as 20 independent observations")


def test_bootstrap_declines_on_too_few_races():
    assert bootstrap_compare(_paired(3, 0.5), "p", "q", "y_actual") == {}
