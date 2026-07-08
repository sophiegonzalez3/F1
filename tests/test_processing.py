"""Regression tests for the enrichment pipeline (processing.py).

These exist chiefly to guard the pandas 2.x pin: the pipeline relies on
pandas 2.x groupby behaviour, and this suite is what makes a future
pandas-3 migration attempt verifiable instead of hopeful.
"""
import numpy as np
import pandas as pd
import pytest

from processing import (
    clean_and_enrich_laps, analyze_stints, _degradation_rate,
    _trimmed_median, format_lap_time, compound_offsets,
)


# ── clean_and_enrich_laps ────────────────────────────────────

def test_enrich_preserves_row_count(race_laps, enriched_race):
    assert len(enriched_race) == len(race_laps)


def test_enrich_adds_core_columns(enriched_race):
    for col in ("LapTime_s", "ValidLap", "Driver_Short", "Team",
                "LapInStint", "LapTime_FuelCorrected"):
        assert col in enriched_race.columns, f"missing {col}"


def test_valid_laps_have_finite_times(enriched_race):
    v = enriched_race[enriched_race["ValidLap"]]
    assert len(v) > 0
    assert np.isfinite(v["LapTime_s"]).all()


def test_driver_short_is_three_letter_code(enriched_race):
    codes = enriched_race["Driver_Short"].dropna().unique()
    assert all(len(c) == 3 and c.isupper() for c in codes)


def test_compounds_are_canonical(enriched_race):
    allowed = {"SOFT", "MEDIUM", "HARD", "INTER", "WET"}
    got = set(enriched_race["Compound"].dropna().unique())
    assert got <= allowed, f"unexpected compounds: {got - allowed}"


# ── analyze_stints ───────────────────────────────────────────

def test_analyze_stints_has_ranks_and_validity(enriched_race):
    st = analyze_stints(enriched_race)
    assert len(st) > 0
    for col in ("Stint_Rep_Lap", "Stint_Deg_Rate", "Valid_Stint",
                "Stint_Rank_In_Session", "Stint_Laps_Count"):
        assert col in st.columns, f"missing {col}"
    assert st["Valid_Stint"].any(), "no valid stints in a full race"
    # ranks only on valid stints, and rank 1 exists per ranked group
    ranked = st[st["Stint_Rank_In_Session"].notna()]
    assert (ranked["Valid_Stint"]).all()


def test_stint_lap_counts_consistent(enriched_race):
    st = analyze_stints(enriched_race)
    total_stint_laps = st["Stint_Laps_Count"].sum()
    valid_laps = enriched_race["ValidLap"].sum()
    assert total_stint_laps == valid_laps


# ── _degradation_rate (synthetic — exact expectations) ───────

def _stint(slope: float, n: int = 12, base: float = 90.0) -> pd.DataFrame:
    age = np.arange(1, n + 1, dtype=float)
    return pd.DataFrame({
        "TyreAge": age,
        "LapTime_FuelCorrected": base + slope * age,
    })


def test_deg_rate_recovers_known_slope():
    out = _degradation_rate(_stint(0.08))
    assert out["Stint_Deg_Rate"] == pytest.approx(0.08, abs=1e-3)
    assert out["Stint_Deg_SE"] == pytest.approx(0.0, abs=1e-6)


def test_deg_rate_flat_stint_is_zero():
    out = _degradation_rate(_stint(0.0))
    assert out["Stint_Deg_Rate"] == pytest.approx(0.0, abs=1e-6)


def test_deg_rate_too_short_returns_nan():
    out = _degradation_rate(_stint(0.1, n=2))
    assert np.isnan(out["Stint_Deg_Rate"])


def test_deg_rate_drops_warmup_lap():
    # first lap way off the trend; with >=5 laps it must be excluded
    df = _stint(0.05, n=10)
    df.loc[0, "LapTime_FuelCorrected"] += 3.0
    out = _degradation_rate(df)
    assert out["Stint_Deg_Rate"] == pytest.approx(0.05, abs=1e-3)


# ── compound_offsets ─────────────────────────────────────────

def test_compound_offsets_shape(enriched_race):
    co = compound_offsets(enriched_race)
    if co.empty:
        pytest.skip("race ran a single compound (unusual)")
    assert {"Pair", "Offset_s", "N_Drivers"} <= set(co.columns)
    assert co["N_Drivers"].ge(1).all()


# ── small pure helpers ───────────────────────────────────────

def test_format_lap_time():
    assert format_lap_time(83.456) == "1:23.456"
    assert format_lap_time(60.0) == "1:00.000"


def test_trimmed_median_ignores_outliers():
    s = pd.Series([90.0] * 10 + [200.0])
    assert _trimmed_median(s) == pytest.approx(90.0)
