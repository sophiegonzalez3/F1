"""Race-driver roster filtering.

F1's mandated rookie FP1 outings put non-race drivers on track — up to six at
once in 2026. They must not reach any field-relative measurement, because
practice measurements are expressed against the session's own median: a
handful of tester laps moves that reference and shifts every team's number at
once.

The two properties that matter, and the second is the one that bites:

1. testers are flagged and excluded from the measured pool;
2. a season with NO roster on file filters NOTHING. data/driver_info.csv covers
   2026 only, so a strict filter would blank the dashboard for every archive
   season — the exact failure the previous standings-based filter had in
   pre-season and at round 1.
"""
import pandas as pd
import pytest

from f1lib.roster import (
    race_drivers, is_race_driver, flag_race_drivers, non_race_drivers_in,
    known_seasons,
)


def _laps(rows):
    return pd.DataFrame(rows, columns=["Driver_Short", "season"])


# ── roster lookup ────────────────────────────────────────────

def test_roster_is_loaded_for_the_current_season():
    r = race_drivers(2026)
    assert r is not None and len(r) >= 20, "2026 roster missing or too small"
    assert {"VER", "NOR", "ALO", "STR"} <= r


def test_unknown_season_returns_none_not_empty():
    """None means 'no roster on file'. An empty set would read as 'nobody
    raced' and delete the whole field."""
    assert race_drivers(1998) is None
    assert race_drivers(None) is None
    assert race_drivers("not a season") is None


def test_is_race_driver_fails_open_on_unknown_seasons():
    assert is_race_driver("VER", 2026) is True
    assert is_race_driver("ARO", 2026) is False       # 2026 FP1 tester
    # no roster for 1998 → everyone counts
    assert is_race_driver("ARO", 1998) is True


def test_lookup_is_case_and_whitespace_tolerant():
    assert is_race_driver(" ver ", 2026) is True


# ── frame flagging ───────────────────────────────────────────

def test_flag_marks_testers_only():
    df = _laps([("VER", 2026), ("ARO", 2026), ("NOR", 2026), ("IWA", 2026)])
    got = flag_race_drivers(df).tolist()
    assert got == [True, False, True, False]
    assert non_race_drivers_in(df) == ["ARO", "IWA"]


def test_flag_fails_open_for_a_season_with_no_roster():
    df = _laps([("VER", 2023), ("SOMEBODY", 2023)])
    assert flag_race_drivers(df).all()
    assert non_race_drivers_in(df) == []


def test_mixed_seasons_are_flagged_independently():
    """A frame spanning seasons must not let one season's roster judge
    another's drivers."""
    df = _laps([("ARO", 2026), ("ARO", 2023), ("VER", 2026)])
    assert flag_race_drivers(df).tolist() == [False, True, True]


def test_missing_columns_fail_open():
    assert flag_race_drivers(pd.DataFrame()).empty is True
    no_season = pd.DataFrame({"Driver_Short": ["ARO"]})
    assert flag_race_drivers(no_season).all()


# ── pipeline integration ─────────────────────────────────────

def test_enrichment_adds_the_flag_without_dropping_laps(race_laps):
    from f1lib.processing import clean_and_enrich_laps
    out = clean_and_enrich_laps(race_laps.copy())
    assert "Is_Race_Driver" in out.columns
    assert len(out) == len(race_laps), "flagging must never drop a lap"
    # a race session has no testers in it
    assert out["Is_Race_Driver"].all()


def test_fp1_with_testers_is_flagged_and_excluded_from_the_pool():
    """The real case: 2026 Austria FP1 ran six non-race drivers."""
    from pathlib import Path
    from f1lib.processing import clean_and_enrich_laps

    p = Path("data/sessions/2026__Austrian_Grand_Prix__Practice_1__laps.parquet")
    if not p.exists():
        pytest.skip("Austria 2026 FP1 not cached")
    fl = clean_and_enrich_laps(pd.read_parquet(p))
    testers = non_race_drivers_in(fl)
    assert len(testers) >= 5, f"expected the rookie outings, got {testers}"
    assert not fl.loc[~fl["Is_Race_Driver"], "Driver_Short"].isin(
        race_drivers(2026)).any()

    # and the model's clean pool must drop them
    from f1lib.pace_features import _clean_mask
    assert not fl.loc[_clean_mask(fl), "Is_Race_Driver"].eq(False).any()


def test_clean_mask_is_a_noop_without_the_flag():
    """pace_features must still work on a frame that predates the column."""
    from f1lib.pace_features import _clean_mask
    df = pd.DataFrame({"ValidLap": [True, True], "LapTime_s": [90.0, 91.0]})
    assert _clean_mask(df).tolist() == [True, True]


def test_driver_info_covers_the_current_season():
    """If the roster stops being maintained the filter quietly stops working —
    it fails open, which is safe but invisible. Pin it."""
    from f1lib.config import CURRENT_SEASON
    assert CURRENT_SEASON in known_seasons(), (
        f"data/driver_info.csv has no {CURRENT_SEASON} roster — test drivers "
        "will no longer be filtered out")
