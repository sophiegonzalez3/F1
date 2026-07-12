"""Regression tests for the enrichment pipeline (processing.py).

These exist chiefly to guard the pandas 2.x pin: the pipeline relies on
pandas 2.x groupby behaviour, and this suite is what makes a future
pandas-3 migration attempt verifiable instead of hopeful.
"""
import numpy as np
import pandas as pd
import pytest

from f1lib.processing import (
    clean_and_enrich_laps, analyze_stints, _degradation_rate,
    _trimmed_median, format_lap_time, compound_offsets,
    detect_wet_crossover, dirty_air_penalty, traffic_exposure_curve,
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


# ── detect_wet_crossover ─────────────────────────────────────

def _wet_race(cross_lap=20, n_laps=40, n_drivers=10) -> pd.DataFrame:
    """Synthetic drying race: everyone on INTER, half switch to slick around
    cross_lap. Inter pace ~ constant; slick pace improves as the track dries,
    starting slower and ending clearly faster → one to_slick crossover."""
    rows = []
    for d in range(n_drivers):
        code = f"D{d:02d}"
        switch = cross_lap + (d - n_drivers / 2)   # staggered switches
        for lap in range(1, n_laps + 1):
            on_slick = lap >= switch
            # dryness 0→1 over the race; slick lap time falls with dryness,
            # inter roughly flat (slightly worse as it dries)
            dry = lap / n_laps
            if on_slick:
                lt = 105 - 25 * dry
            else:
                lt = 92 + 8 * dry
            rows.append({"LapNo": lap, "Driver_Short": code, "Team": "T",
                         "LapTime_s": lt,
                         "Compound": "SLICK_PLACEHOLDER" if on_slick else "INTER",
                         "PitIn": np.nan, "PitOut": np.nan})
    df = pd.DataFrame(rows)
    df.loc[df["Compound"] == "SLICK_PLACEHOLDER", "Compound"] = "MEDIUM"
    return df


def test_wet_crossover_none_for_dry_race():
    rows = [{"LapNo": l, "Driver_Short": f"D{d}", "Team": "T",
             "LapTime_s": 90.0, "Compound": "MEDIUM",
             "PitIn": np.nan, "PitOut": np.nan}
            for d in range(10) for l in range(1, 40)]
    assert detect_wet_crossover(pd.DataFrame(rows)) is None


def test_wet_crossover_detects_transition():
    res = detect_wet_crossover(_wet_race(cross_lap=20))
    assert res is not None
    assert res["crossings"], "expected at least one crossing"
    laps = [c["lap"] for c in res["crossings"]]
    # crossover should land near where slick pace overtakes inter pace
    assert any(10 <= l <= 30 for l in laps)
    assert all(c["direction"] == "to_slick" for c in res["crossings"])


def test_wet_crossover_switch_timing_columns():
    res = detect_wet_crossover(_wet_race())
    sw = res["switches"]
    assert {"Driver_Short", "lap", "direction", "delta_laps",
            "time_lost_s"} <= set(sw.columns)
    assert (sw["direction"] == "to_slick").all()


# ── dirty_air_penalty / traffic_exposure_curve ───────────────

def _traffic_race(penalty=0.5, n_drivers=8, n_laps=30) -> pd.DataFrame:
    """Each driver runs one stint; laps 10–16 are flagged dirty air and are
    exactly `penalty` seconds slower — the measurement should recover it."""
    rows = []
    for d in range(n_drivers):
        for lap in range(1, n_laps + 1):
            dirty = 10 <= lap <= 16
            rows.append({
                "Driver_Short": f"D{d:02d}", "Stint": 1, "LapNo": lap,
                "LapTime_s": 90.0 + d * 0.1 + (penalty if dirty else 0.0),
                "Dirty_Air": dirty, "ValidLap": True,
            })
    return pd.DataFrame(rows)


def test_dirty_air_penalty_recovers_known_value():
    res = dirty_air_penalty(_traffic_race(penalty=0.5))
    assert res is not None
    assert res["penalty_s"] == pytest.approx(0.5, abs=0.01)
    assert res["n_stints"] == 8


def test_dirty_air_penalty_none_when_unmeasurable():
    df = _traffic_race()
    df["Dirty_Air"] = False          # nothing to pair against
    assert dirty_air_penalty(df) is None


def test_traffic_exposure_curve_evenly_spaced_field():
    # 20 cars at constant 2 s spacing, identical 90 s laps: with pit_loss 22
    # a mid-field car has 10 rivals in its rejoin window, linearly weighted →
    # Σ 2k/22 for k=1..10 = 5.0; the median sits just below (tail cars have
    # fewer rivals behind them).
    rows = []
    for d in range(20):
        for lap in range(1, 31):
            lt = 90.0 + (2.0 * d if lap == 1 else 0.0)   # stagger via lap 1
            rows.append({"Driver_Short": f"D{d:02d}", "LapNo": lap,
                         "LapTime_s": lt})
    curve = traffic_exposure_curve(pd.DataFrame(rows), pit_loss=22.0)
    assert curve is not None
    mid = curve.loc[15]
    assert 3.5 < mid < 5.5
    # constant spacing → roughly constant exposure across the race
    assert curve.loc[5:25].std() < 0.5


def test_traffic_exposure_none_for_tiny_field():
    rows = [{"Driver_Short": f"D{d}", "LapNo": l, "LapTime_s": 90.0}
            for d in range(3) for l in range(1, 10)]
    assert traffic_exposure_curve(pd.DataFrame(rows), pit_loss=22.0) is None
