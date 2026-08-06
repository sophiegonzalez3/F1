"""Tests for the pace model's UNCERTAINTY, as opposed to its point estimate.

The model's whole selling point is that every prediction carries an error bar.
Nothing measured that error bar for a long time, because the backtest stored
only MAE and rank correlation — and MAE scores "-1.02 +/- 0.01" and
"-1.02 +/- 5.00" identically. When calibration was finally measured, the
long-run prior turned out to be covering 49% of outcomes inside its own
1-sigma band against a target of 68%: the intervals were about half as wide
as they had earned.

The cause was a textbook one — the prior reported the variance of the MEAN of
past races where it needed the PREDICTIVE variance of the next one — and these
tests pin the fix so it cannot silently regress back.
"""
import numpy as np
import pandas as pd
import pytest

from f1lib.pace_model import DEFAULTS, PaceModel

TEAMS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]


def _pace_csv(tmp_path, scatter: float, n_rounds: int = 9):
    """A synthetic pace table where one team's form BOUNCES by a fixed amount.

    Deterministic on purpose — Alpha alternates +/- `scatter` around -1.0. A
    seeded random history makes the realised scatter differ from the nominal
    one, which turns an assertion about the FORMULA into an assertion about
    the draw.
    """
    rows = []
    for rnd in range(1, n_rounds + 1):
        gaps = {"Alpha": -1.0 + (scatter if rnd % 2 else -scatter)}
        for i, t in enumerate(TEAMS[1:], start=1):
            gaps[t] = float(i) * 0.5
        for t, g in gaps.items():
            rows.append({"season": 2026, "round": rnd, "event": f"Race {rnd}",
                         "team": t, "onelap_speed_pct": g,
                         "race_pace_pct": g, "onelap_n_sessions": 3})
    p = tmp_path / "pace.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


def _formula_inputs(model, round_=10):
    """The (resid_var, n_eff) the prior is built from, read back out of the
    model's own history helper so the test compares FORMULAS on identical
    inputs rather than re-deriving the data."""
    h = model._centered_history(2026, round_, model.col_onelap)
    g = h[h["team"] == "Alpha"]
    w = 0.5 ** (g["dist"] / model.p["half_life_rounds"])
    mean = float(np.average(g["gap_c"], weights=w))
    n_eff = float(w.sum() ** 2 / (w ** 2).sum())
    resid_var = float(np.average((g["gap_c"] - mean) ** 2, weights=w))
    return resid_var, n_eff


def _alpha_prior(tmp_path, scatter, **overrides):
    m = PaceModel(pace_csv=_pace_csv(tmp_path, scatter), **overrides)
    pri = m.prior(2026, 10, TEAMS)
    row = pri[(pri["team"] == "Alpha") & (pri["kind"] == "onelap")].iloc[0]
    return float(row["var"]), m


# ─────────────────────────────────────────────────────────────
# The prior reports a PREDICTIVE variance
# ─────────────────────────────────────────────────────────────

def test_prior_uses_the_predictive_variance_not_the_variance_of_the_mean(tmp_path):
    """The exact formula, pinned.

    Two candidates, same inputs:
        variance of the MEAN  = resid_var / n_eff          <- the old bug
        PREDICTIVE variance   = resid_var * (1 + 1/n_eff)  <- correct

    They answer different questions. The first is "where is the CENTRE of this
    team's bouncing?", which gets sharper the more races you see. The second is
    "where will the NEXT race land?", which never gets sharper than the
    bouncing itself. Only the second is what the model is asked for, and at a
    typical n_eff around 7.5 they differ by a factor of 8.5.
    """
    var, m = _alpha_prior(tmp_path, scatter=1.0)
    resid_var, n_eff = _formula_inputs(m)
    floor = DEFAULTS["min_prior_var"]
    predictive = resid_var * (1 + 1 / n_eff) + floor
    of_the_mean = resid_var / n_eff + floor

    assert var == pytest.approx(predictive, rel=1e-6), (
        "prior variance no longer matches the predictive formula")
    assert var > 3 * of_the_mean, (
        f"prior variance {var:.4f} is close to the variance of the mean "
        f"({of_the_mean:.4f}) — the over-confidence bug is back")


def test_prior_sd_reflects_the_scatter_it_saw(tmp_path):
    """The same property as a human would state it: a team whose form has been
    bouncing by about a percent should carry a prior of about a percent, not a
    third of one.

    The band is wide because per-round centering shrinks a single team's
    deviation slightly (its own noise is inside the round mean it is measured
    against) — the point is the order of magnitude, not the third decimal.
    """
    var, _ = _alpha_prior(tmp_path, scatter=1.0)
    sd = np.sqrt(var)
    assert 0.7 <= sd <= 1.4, (
        f"prior sd {sd:.3f} does not reflect the ~1.0% scatter it was built "
        "from — has _prior_kind reverted to resid_var / n_eff?")


def test_prior_variance_does_not_collapse_with_more_history(tmp_path):
    """A team with a long, consistently NOISY record is not a team we know
    precisely — it is a team we know to be erratic. Under the old formula the
    variance fell as history accumulated, so the more evidence of volatility
    the model saw, the more certain it claimed to be."""
    short, _ = _alpha_prior(tmp_path, scatter=1.0, )
    m_long = PaceModel(pace_csv=_pace_csv(tmp_path, 1.0, n_rounds=30))
    pri = m_long.prior(2026, 31, TEAMS)
    long = float(pri[(pri["team"] == "Alpha")
                     & (pri["kind"] == "onelap")].iloc[0]["var"])
    assert long > 0.5 * short, (
        f"variance fell from {short:.3f} to {long:.3f} as more evidence of "
        "volatility arrived — that is the mean-variance bug returning")


def test_a_metronomic_team_still_gets_the_floor(tmp_path):
    """Zero observed scatter must not mean zero uncertainty: the car can still
    be developed, crashed, or rained on. min_prior_var is the guard."""
    var, _ = _alpha_prior(tmp_path, scatter=0.0)
    assert var == pytest.approx(DEFAULTS["min_prior_var"], abs=1e-6)


# ─────────────────────────────────────────────────────────────
# Process noise
# ─────────────────────────────────────────────────────────────

def test_drift_is_an_exact_noop_when_disabled(tmp_path):
    m = PaceModel(pace_csv=_pace_csv(tmp_path, 0.5), process_var_per_stage=0.0)
    st = m.prior(2026, 10, TEAMS)
    pd.testing.assert_frame_equal(m._drift(st), st)


def test_drift_inflates_variance_by_q_and_respects_the_cap(tmp_path):
    m = PaceModel(pace_csv=_pace_csv(tmp_path, 0.5), process_var_per_stage=0.05)
    st = m.prior(2026, 10, TEAMS)
    out = m._drift(st)
    assert np.allclose(out["var"], np.minimum(st["var"] + 0.05,
                                              DEFAULTS["max_prior_var"]))
    # and the mean is never touched — drift is uncertainty, not a new belief
    assert np.allclose(out["mean"], st["mean"])


def test_process_noise_slows_the_variance_collapse(tmp_path):
    """Three sessions of updates with no process noise drive the variance
    monotonically toward zero. With Q > 0 the same three updates must leave
    strictly more uncertainty behind."""
    meas = pd.concat([
        pd.DataFrame({"team": TEAMS, "kind": "onelap", "gap_pct": 0.0,
                      "se_pct": 0.10, "session": s})
        for s in ("Practice 1", "Practice 2", "Practice 3")])
    csv = _pace_csv(tmp_path, 0.5)

    def final_var(q):
        m = PaceModel(pace_csv=csv, process_var_per_stage=q)
        st = m.predict_weekend(2026, "Race 10", measurements=meas, round_=10)
        last = st["after FP3"]
        return float(last[(last["team"] == "Alpha")
                          & (last["kind"] == "onelap")].iloc[0]["var"])

    assert final_var(0.05) > final_var(0.0)


# ─────────────────────────────────────────────────────────────
# The scoring rules themselves
# ─────────────────────────────────────────────────────────────

def _rules():
    from scripts.backtest_pace_model import _crps_gauss, _nll_gauss
    return _crps_gauss, _nll_gauss


def test_crps_collapses_to_absolute_error_for_a_sharp_forecast():
    """CRPS is MAE generalised to a distribution, and the two must agree in
    the limit — that is what makes a point forecast and a distributional one
    comparable on one scale."""
    crps, _ = _rules()
    y, mu = np.array([2.0]), np.array([1.0])
    assert crps(y, mu, np.array([1e-6]))[0] == pytest.approx(1.0, abs=1e-3)


def test_log_score_punishes_confidence_more_than_error():
    """The property MAE cannot express. Hold the error fixed and shrink the
    claimed uncertainty: the log score must get dramatically worse, because
    the forecast asserted something false with more conviction.

    Taken from the real worst case in the archive — Sauber at a wet
    Silverstone, missed by 5.08% while claiming +/-0.39%.
    """
    _, nll = _rules()
    y, mu = np.array([-4.338]), np.array([0.741])
    confident = nll(y, mu, np.array([0.39]))[0]
    honest = nll(y, mu, np.array([1.20]))[0]
    assert confident > 8 * honest
    assert honest > 0


def test_score_reports_calibration_only_when_an_sd_is_present():
    """The raw-FP baseline is a bare timing-screen read: it makes no claim to
    be wrong by any particular amount, so its calibration columns must come
    back NaN rather than silently defaulting to something."""
    from scripts.backtest_pace_model import _score
    actual = pd.Series({"A": -1.0, "B": 0.0, "C": 0.5, "D": 0.5})
    withsd = pd.DataFrame({"team": list("ABCD"), "kind": "onelap",
                           "mean": [-0.9, 0.1, 0.4, 0.4], "sd": 0.3})
    without = withsd.drop(columns=["sd"])
    assert np.isfinite(_score(withsd, actual, "onelap")["nll"])
    assert np.isnan(_score(without, actual, "onelap")["nll"])
    # point accuracy is reported either way
    assert _score(without, actual, "onelap")["mae"] == pytest.approx(
        _score(withsd, actual, "onelap")["mae"])
