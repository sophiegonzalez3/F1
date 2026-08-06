"""Tests for how the race forecast models retirements.

Two properties are pinned here, both of which were assumptions before they
were measurements:

  * retirement risk varies by CIRCUIT (0.72x Barcelona to 1.38x Australia over
    3235 classified starts), and the per-circuit statistic must be keyed on
    circuit_id rather than on the archive's event-derived circuit_key;
  * teammates' retirements are CORRELATED (P(both) 3.06% against 2.02% under
    independence), so the simulator draws them through a shared per-team
    shock instead of as independent Bernoullis.

Deliberately NOT modelled, and pinned as such in the module docstring: a
per-driver rate (p = 0.20) and a per-grid-slot rate (the raw gradient is car
quality — within a team the back-starting car retires 15.1% vs 13.3%,
McNemar p = 0.15).
"""
import numpy as np
import pandas as pd
import pytest

from f1lib.race_forecast import DEFAULTS, RaceForecaster


@pytest.fixture(scope="module")
def rf():
    f = RaceForecaster()
    if f._results.empty:
        pytest.skip("results archive not built")
    return f


def _pred(n_teams=3):
    rows = []
    for i in range(n_teams):
        for j in (0, 1):
            rows.append({"driver": f"D{i}{j}", "team": f"T{i}",
                         "mean": 0.1 * (2 * i + j), "car_var": 0.05,
                         "drv_var": 0.01})
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────
# Per-circuit rate
# ─────────────────────────────────────────────────────────────

def test_circuit_multipliers_are_keyed_on_circuit_id_not_event_name(rf):
    """Barcelona is the same circuit whether the event is called the Spanish
    or the Barcelona Grand Prix. Keyed on the archive's circuit_key these
    split into two thin samples, and the renamed half shrank to the field
    mean — reporting the SAFEST circuit in the archive (0.72x) as one of the
    harshest (1.27x)."""
    a = rf.dnf_multiplier("Spanish Grand Prix")
    b = rf.dnf_multiplier("Barcelona Grand Prix")
    assert a == pytest.approx(b), (
        "the same circuit under two event names produced different retirement "
        "rates — has the per-circuit key reverted to circuit_key?")
    assert a < 1.0, "Barcelona is the archive's lowest-attrition circuit"


def test_unknown_event_falls_back_to_the_field_average(rf):
    assert rf.dnf_multiplier("Some Grand Prix That Never Ran") == 1.0


def test_circuit_spread_is_real_but_bounded(rf):
    m = pd.Series(rf._circuit_dnf_map)
    assert len(m) > 15
    # shrinkage must keep every circuit inside a sane band; an unshrunk
    # 20-start circuit would otherwise swing to 0.35 or 0.05 on noise
    assert 0.4 < m.min() < 0.95, f"lowest multiplier {m.min():.2f} implausible"
    assert 1.1 < m.max() < 2.0, f"highest multiplier {m.max():.2f} implausible"


def test_simulated_rate_matches_the_configured_rate_times_the_circuit(rf):
    ev = "Australian Grand Prix"
    sim = rf.simulate(_pred(), event=ev)
    target = DEFAULTS["dnf_rate"] * rf.dnf_multiplier(ev)
    assert sim["dnf"].mean() == pytest.approx(target, abs=0.006)


# ─────────────────────────────────────────────────────────────
# Correlated teammate failures
# ─────────────────────────────────────────────────────────────

def test_teammates_retire_together_more_often_than_chance(rf):
    """The measured lift is ~1.5x. Independent Bernoulli draws give 1.0 and
    understate double retirements by half, which inflates every OTHER
    driver's podium and points probability."""
    sim = rf.simulate(_pred(), event="Belgian Grand Prix")
    d = sim["dnf"]
    both = (d[:, 0] & d[:, 1]).mean()
    indep = d[:, 0].mean() * d[:, 1].mean()
    assert both / indep > 1.25, (
        f"teammate retirements only {both/indep:.2f}x independent — is the "
        "shared per-team shock still wired in?")


def test_drivers_on_different_teams_stay_independent(rf):
    """The shock is per TEAM. If it leaked across teams the whole field would
    retire together and the forecast's tails would be nonsense."""
    sim = rf.simulate(_pred(), event="Belgian Grand Prix")
    d = sim["dnf"]
    cross = (d[:, 0] & d[:, 2]).mean()
    indep = d[:, 0].mean() * d[:, 2].mean()
    assert 0.8 < cross / indep < 1.25


def test_correlation_can_be_switched_off(rf):
    f = RaceForecaster(dnf_corr=0.0)
    d = f.simulate(_pred(), event="Belgian Grand Prix")["dnf"]
    both = (d[:, 0] & d[:, 1]).mean()
    indep = d[:, 0].mean() * d[:, 1].mean()
    assert 0.8 < both / indep < 1.25


def test_explicit_per_driver_rates_still_override(rf):
    """The dnf_rates hook predates this and must keep working — it is how a
    per-team reliability model would be plugged in later."""
    p = _pred()
    rates = {"D00": 0.9, "D01": 0.9}
    d = rf.simulate(p, event="Belgian Grand Prix", dnf_rates=rates)["dnf"]
    assert d[:, 0].mean() > 0.8
    assert d[:, 4].mean() < 0.3      # untouched driver keeps the circuit rate
