"""Tests for the observation-noise calibration (scripts/calibrate_pace_noise.py).

The model's `base_noise` table says how much to distrust each practice
session. Those constants used to be defensible only by assertion — a grid
search over them was shown to be unidentifiable on the available events. The
calibration estimates them from an identity instead (attenuation of the
outcome-on-measurement slope), so these tests pin the identity's arithmetic
on synthetic data where the true noise is known, and pin the one qualitative
conclusion the real data supports: practice long runs are a far weaker read
than practice one-lap runs.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "calibrate_pace_noise", ROOT / "scripts" / "calibrate_pace_noise.py")
cal = importlib.util.module_from_spec(_spec)
sys.modules["calibrate_pace_noise"] = cal
_spec.loader.exec_module(cal)


def _synthetic(true_sd: float, noise: float, se: float, n: int = 4000,
               outcome_noise: float = 0.5, seed: int = 3) -> pd.DataFrame:
    """Measurements of a latent with KNOWN noise, so the estimator can be
    checked against the value it is supposed to recover."""
    rng = np.random.default_rng(seed)
    theta = rng.normal(0, true_sd, n)
    total = np.sqrt(noise ** 2 + se ** 2)
    return pd.DataFrame({
        "m": theta + rng.normal(0, total, n),
        "se": np.full(n, se),
        "r": theta + rng.normal(0, outcome_noise, n),
    })


def test_recovers_a_known_noise():
    """The whole method in one assertion: plant a measurement with noise 0.9
    on top of an SE of 0.4 and the estimator must find 0.9 back."""
    d = _synthetic(true_sd=1.0, noise=0.9, se=0.4)
    out = cal.implied_noise(d)
    assert out["identified"]
    assert out["implied"] == pytest.approx(0.9, abs=0.12)


def test_noise_in_the_outcome_does_not_bias_the_estimate():
    """Noise in the OUTCOME must not change the answer — that is the reason
    this identity works at all where a correlation would mislead. The race is
    a noisy read of true pace too, and that must not be charged to practice.
    """
    quiet = cal.implied_noise(_synthetic(1.0, 0.9, 0.4, outcome_noise=0.1))
    loud = cal.implied_noise(_synthetic(1.0, 0.9, 0.4, outcome_noise=2.0))
    assert quiet["implied"] == pytest.approx(loud["implied"], abs=0.15)
    # ...even though the apparent correlation collapses
    assert abs(loud["r"]) < abs(quiet["r"])


def test_se_dominated_block_reports_not_identified():
    """When the reported fit SE already exceeds the whole spread of the
    measurement there is nothing left to attribute, and the estimator must
    say 'not identified' rather than 'zero noise' — reading it as zero would
    argue for trusting the session completely, the opposite of the truth.

    This is a real case, not a hypothetical: on pre-2026 data the one-lap FP3
    block reports a mean SE (1.227) larger than the standard deviation of the
    measurements themselves (1.171), which cannot be true of an accurate SE.
    """
    d = _synthetic(true_sd=0.5, noise=0.3, se=0.3)
    d["se"] = 2.0                      # reported SE far exceeds the real spread
    out = cal.implied_noise(d)
    assert not out["identified"]
    assert np.isnan(out["implied"])


def test_long_runs_are_a_weaker_read_than_one_lap_runs():
    """The model's central qualitative claim about practice, pinned against
    the shipped constants: every long-run session must carry more noise than
    every one-lap practice session. Practice race sims run on unknown fuel
    and engine modes; quali sims do not."""
    from f1lib.pace_model import DEFAULTS

    base = DEFAULTS["base_noise"]
    onelap = [v for (kind, sess), v in base.items()
              if kind == "onelap" and sess.startswith("Practice")]
    longrun = [v for (kind, sess), v in base.items()
               if kind == "longrun" and sess.startswith("Practice")]
    assert onelap and longrun
    assert min(longrun) > max(onelap), (
        "a practice long-run session is being trusted more than a one-lap "
        "session — the backtest says that makes practice drift worse than "
        "the season-form prior")


@pytest.mark.filterwarnings("ignore::FutureWarning")
def test_shipped_constants_sit_in_the_calibrated_band():
    """Guard rail, not a re-derivation: no shipped practice constant may drift
    outside the range the estimation sample supports. Kept deliberately wide
    (the point is to catch a constant being moved to 0.1 or 3.0, not to pin
    the third decimal), and it never reads 2026 — that is the holdout."""
    from f1lib.pace_model import DEFAULTS

    for (kind, session), v in DEFAULTS["base_noise"].items():
        if not session.startswith("Practice"):
            continue
        lo, hi = (0.15, 1.0) if kind == "onelap" else (0.4, 1.6)
        assert lo <= v <= hi, (
            f"base_noise[{kind!r}, {session!r}] = {v} is outside the band the "
            f"attenuation calibration supports ({lo}-{hi}); re-run "
            "scripts/calibrate_pace_noise.py before changing it")
