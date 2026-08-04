"""Tests for the finisher classification behind the race forecast.

`_is_finish` decides who counts as a classified finisher, which decides the
per-circuit passability the forecast is built on. It is exposed to a moving
target: the results archive changed its status vocabulary in 2023 ("+1 Lap"
became "Lapped"), and the old rule excluded anything containing "Lap", so
375 lapped FINISHERS were silently reclassified as retirements. Nothing
failed — the numbers just quietly meant something else.

These tests pin both vocabularies at once, so the next rename is caught by a
red test rather than by someone noticing an implausible retirement rate.
"""
import pandas as pd
import pytest

from f1lib.race_forecast import DEFAULTS, _is_finish


def test_both_archive_vocabularies_are_understood():
    s = pd.Series([
        "Finished",          # both eras
        "+1 Lap", "+2 Laps",  # pre-2023 lapped finishers
        "Lapped",            # 2023+ lapped finisher
        "Retired", "Accident", "Collision", "Engine", "Gearbox",
        "Disqualified", "Did not start",
    ])
    got = _is_finish(s).tolist()
    assert got[:4] == [True, True, True, True], "a lapped car still finished"
    assert not any(got[4:]), "a retirement is being counted as a finish"


def test_lapped_cars_are_not_a_retirement_epidemic():
    """The symptom that exposed the bug: with lapped finishers miscounted,
    the archive appeared to show a ~50% retirement rate in 2026. Any season's
    real rate sits well under a quarter."""
    try:
        r = pd.read_parquet("data/historical_results/race_results_all.parquet")
    except OSError:
        pytest.skip("results archive not built")
    r = r[r["GridPosition"] > 0]
    if r.empty:
        pytest.skip("no classified starts")
    rate = 1 - _is_finish(r["Status"]).groupby(r["season"]).mean()
    assert rate.max() < 0.25, (
        f"season {rate.idxmax()} shows a {rate.max():.0%} retirement rate — "
        "the status vocabulary has probably changed again")


def test_dnf_rate_constant_matches_the_archive():
    """dnf_rate is a measured quantity, so it must stay near what the archive
    says. Deliberately loose: it should track the era, not chase one season."""
    try:
        r = pd.read_parquet("data/historical_results/race_results_all.parquet")
    except OSError:
        pytest.skip("results archive not built")
    pre = r[(r["GridPosition"] > 0) & (r["season"] < 2026)]
    if len(pre) < 500:
        pytest.skip("not enough pre-2026 starts")
    measured = 1 - _is_finish(pre["Status"]).mean()
    assert abs(DEFAULTS["dnf_rate"] - measured) < 0.05, (
        f"dnf_rate={DEFAULTS['dnf_rate']} vs {measured:.3f} measured "
        "pre-2026 — re-derive it")
