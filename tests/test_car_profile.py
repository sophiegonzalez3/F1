"""Tests for the car-concept profile.

The point of this feature is that every axis it presents as a season trait has
been shown to BE one. These tests pin that contract: the split-half reliability
figures quoted in the UI must still hold against the shipped table, and the
enrichment order that tyre wear depends on must not regress.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROFILE = ROOT / "data" / "car_profile.csv"

_spec = importlib.util.spec_from_file_location(
    "compute_car_profile", ROOT / "scripts" / "compute_car_profile.py")
ccp = importlib.util.module_from_spec(_spec)
sys.modules["compute_car_profile"] = ccp
_spec.loader.exec_module(ccp)


@pytest.fixture(scope="module")
def profile() -> pd.DataFrame:
    if not PROFILE.exists():
        pytest.skip("car_profile.csv not built")
    d = pd.read_csv(PROFILE)
    if d.empty:
        pytest.skip("car_profile.csv empty")
    return d[d["season"] == d["season"].max()]


def _split_half(df: pd.DataFrame, col: str) -> float:
    """Spearman-Brown reliability of the season average for one axis."""
    M = df.pivot_table(index="team", columns="round", values=col)
    cols = sorted(c for c in M.columns if np.isfinite(c))
    if len(cols) < 4:
        return float("nan")
    h1, h2 = M[cols[0::2]].mean(axis=1), M[cols[1::2]].mean(axis=1)
    ok = h1.notna() & h2.notna()
    if ok.sum() < 5:
        return float("nan")
    r = float(np.corrcoef(h1[ok], h2[ok])[0, 1])
    return (2 * r) / (1 + r) if r > -1 else float("nan")


def test_every_matrix_axis_is_actually_a_season_trait(profile):
    """The concept matrix claims these are car properties — prove it.

    If one of these drops below the bar on future data, the honest response is
    to move it out of the matrix, not to quietly keep presenting it.
    """
    from tabs.car_profile import AXES
    for col, label, _unit, _better, quoted, _doc in AXES:
        if col not in profile.columns:
            pytest.skip(f"{col} not in the shipped table")
        rel = _split_half(profile, col)
        assert np.isfinite(rel), f"{label}: not enough data to validate"
        assert rel >= 0.6, (
            f"{label} ({col}) split-half reliability {rel:.2f} is below the 0.6 "
            f"bar — it is no longer a season trait and should leave the matrix")
        assert abs(rel - quoted) < 0.25, (
            f"{label}: UI quotes reliability {quoted:.2f} but the shipped data "
            f"gives {rel:.2f} — update the AXES table")


def test_degradation_needs_the_perturbed_lap_filter(profile):
    """Tyre wear is only a usable axis when safety-car / perturbed laps are
    excluded before the track-evolution fit. Fitting on them drops its
    reliability from ~0.69 to ~0.17 — the bug that first made this axis look
    like noise. This pins the working state so a reordering of the enrichment
    chain in build_event() fails loudly instead of silently degrading."""
    if "deg_spl" not in profile.columns or profile["deg_spl"].notna().sum() < 40:
        pytest.skip("no degradation data")
    rel = _split_half(profile, "deg_spl")
    assert np.isfinite(rel) and rel >= 0.6, (
        f"tyre wear reliability {rel:.2f} — check that build_event() still "
        f"runs flag_perturbed_laps before enrich_track_evolution")


def test_axes_are_centred_on_the_field(profile):
    """Every axis is a versus-the-field-that-weekend number, so each event's
    values must sum to about zero. A drifting centre would mean the circuit is
    leaking back into what should be a pure team comparison."""
    from tabs.car_profile import AXES
    for col, label, *_ in AXES:
        if col not in profile.columns:
            continue
        means = profile.groupby("round")[col].mean().dropna()
        assert means.abs().max() < 0.5, (
            f"{label} is not centred: worst event mean {means.abs().max():.3f}")


def test_top_end_fade_is_a_share(profile):
    """fade_pct is a percentage of pinned-throttle samples, centred — so it
    cannot legitimately exceed ±100."""
    if "fade_pct" not in profile.columns:
        pytest.skip("no fade data")
    v = profile["fade_pct"].dropna()
    assert v.between(-100, 100).all()


def test_canon_folds_renamed_teams():
    assert ccp.canon("RB") == "Racing Bulls"
    assert ccp.canon("AlphaTauri") == "Racing Bulls"
    assert ccp.canon("Kick Sauber") == "Sauber"
    assert ccp.canon("Ferrari") == "Ferrari"


def test_best_laps_picks_one_lap_per_driver():
    fl = pd.DataFrame({
        "Driver_Short": ["VER", "VER", "NOR", "NOR"],
        "ValidLap": [True, True, True, False],
        "LapTime_s": [90.0, 89.0, 91.0, 80.0],
    })
    b = ccp._best_laps(fl)
    assert len(b) == 2
    assert b.set_index("Driver_Short")["LapTime_s"].to_dict() == {
        "VER": 89.0, "NOR": 91.0}, "must ignore the invalid 80 s lap"
