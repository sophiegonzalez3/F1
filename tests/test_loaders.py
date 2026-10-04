"""Tests for the data-collection layer: radio topic tagging, pit-stop
parsing helpers, cache-key sanitisation, and the reference CSVs."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from f1lib.radio_loader import tag_topics
from f1lib.pitstops_loader import _parse_duration
from f1lib.data_loader import _sanitize, _session_key

ROOT = Path(__file__).resolve().parents[1]


# ── radio topic tagging ──────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("Box, box, box.", "PIT CALL"),
    ("These tyres are dead, big deg on the rears.", "TYRES"),
    ("Rain expected in ten minutes.", "WEATHER"),
    ("Blue flags for the car behind.", "TRAFFIC / FLAGS"),
    ("Use overtake button now, watch the battery.", "ENERGY / MODE"),
    ("We are thinking plan B, push now.", "STRATEGY"),
    ("My brakes are gone, something's broken.", "CAR / DAMAGE"),
])
def test_tag_topics_hits(text, expected):
    assert expected in tag_topics(text)


def test_tag_topics_empty_and_chitchat():
    assert tag_topics("") == ""
    assert tag_topics(None) == ""
    assert tag_topics("Great job mate.") == ""


def test_tag_topics_multi():
    got = tag_topics("Box this lap, the softs are finished.")
    assert "PIT CALL" in got and "TYRES" in got


# ── pit-stop duration parsing ────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("21.297", 21.297),
    ("16:12.356", 16 * 60 + 12.356),   # red-flag / repair stops
    ("", np.nan),
    (None, np.nan),
    ("abc", np.nan),
])
def test_parse_duration(raw, expected):
    got = _parse_duration(raw)
    if isinstance(expected, float) and np.isnan(expected):
        assert np.isnan(got)
    else:
        assert got == pytest.approx(expected)


# ── cache keys ───────────────────────────────────────────────

def test_sanitize_strips_specials():
    assert _sanitize("São Paulo Grand Prix!") == "S_o_Paulo_Grand_Prix"


def test_session_key_stable():
    assert (_session_key("2026", "Austrian Grand Prix", "Race")
            == "2026__Austrian_Grand_Prix__Race")


# ── reference CSVs ───────────────────────────────────────────

def test_tyre_allocations_schema():
    df = pd.read_csv(ROOT / "data" / "tyre_allocations.csv")
    assert {"season", "event", "hard", "medium", "soft"} <= set(df.columns)
    compounds = pd.concat([df["hard"], df["medium"], df["soft"]])
    assert compounds.str.fullmatch(r"C[1-6]").all()
    # soft must be softer (higher C-number) than hard
    h = df["hard"].str[1].astype(int)
    s = df["soft"].str[1].astype(int)
    assert (s > h).all()


# ── results-archive integrity ────────────────────────────────
#
# Regression cover for the silent rot found 2026-08-02: FastF1 can return a
# results table with driver/team names filled but Position/Points/GridPosition
# entirely NaN. Such a frame is not empty, so it used to be written and then
# cache-hit forever, quietly corrupting the championship standings (and the ATR
# table derived from them). See _has_usable_results.

def _named_but_unclassified() -> pd.DataFrame:
    """The poisoned shape: real drivers, no classification at all."""
    return pd.DataFrame({
        "DriverNumber": ["63", "16", "44"],
        "Abbreviation": ["RUS", "LEC", "HAM"],
        "TeamName":     ["Mercedes", "Ferrari", "Ferrari"],
        "Position":     [np.nan, np.nan, np.nan],
        "Points":       [np.nan, np.nan, np.nan],
        "GridPosition": [np.nan, np.nan, np.nan],
    })


def _classified() -> pd.DataFrame:
    df = _named_but_unclassified()
    df["Position"] = [1.0, 2.0, 3.0]
    df["Points"]   = [25.0, 18.0, 15.0]
    df["GridPosition"] = [1.0, 3.0, 2.0]
    return df


@pytest.mark.parametrize("frame,expected", [
    (_classified(),                True),
    (_named_but_unclassified(),    False),   # the bug
    (pd.DataFrame(),               False),
    (_classified().drop(columns=["Position"]), False),
])
def test_has_usable_results(frame, expected):
    from f1lib.fetch_historical_results import _has_usable_results
    assert _has_usable_results(frame) is expected


def test_has_usable_results_keeps_partial_classification():
    """A DNF/DNS leaves some positions blank — that frame is still real data."""
    from f1lib.fetch_historical_results import _has_usable_results
    df = _classified()
    df.loc[2, ["Position", "Points"]] = np.nan
    assert _has_usable_results(df) is True


class _StubSession:
    def __init__(self, results):
        self.results = results


def test_safe_df_discards_unclassified_frame():
    """The whole point: this must not reach _write_parquet."""
    from f1lib.fetch_historical_results import _safe_df
    assert _safe_df(_StubSession(_named_but_unclassified())).empty


@pytest.mark.parametrize("results", [None, pd.DataFrame()])
def test_safe_df_handles_missing_results(results):
    from f1lib.fetch_historical_results import _safe_df
    assert _safe_df(_StubSession(results)).empty


def test_safe_df_passes_real_results_through():
    from f1lib.fetch_historical_results import _safe_df
    got = _safe_df(_StubSession(_classified()))
    assert len(got) == 3 and got["Position"].notna().all()


def test_verify_archive_flags_only_the_rotted_file(tmp_path):
    from f1lib.fetch_historical_results import verify_archive
    for sub in ("race", "quali", "sprint"):
        (tmp_path / sub).mkdir(parents=True)
    good = tmp_path / "race" / "2026_01_australian_grand_prix.parquet"
    bad  = tmp_path / "race" / "2026_08_austrian_grand_prix.parquet"
    _classified().to_parquet(good, index=False)
    _named_but_unclassified().to_parquet(bad, index=False)

    assert verify_archive(tmp_path) == [bad]


def test_verify_archive_clean_when_empty(tmp_path):
    from f1lib.fetch_historical_results import verify_archive
    assert verify_archive(tmp_path) == []


def test_bundled_archive_has_no_unclassified_rounds():
    """Tripwire on the real archive, so the rot can't creep back in unnoticed."""
    from f1lib.fetch_historical_results import verify_archive
    archive = ROOT / "data" / "historical_results"
    if not archive.exists():
        pytest.skip("results archive not fetched yet")
    assert verify_archive(archive) == []


def test_circuit_characteristics_computed_schema():
    p = ROOT / "data" / "circuit_characteristics_computed.csv"
    if not p.exists():
        pytest.skip("computed characteristics not generated yet")
    df = pd.read_csv(p)
    assert {"circuit_key", "avg_speed_score", "full_throttle_score",
            "lateral_load_score"} <= set(df.columns)
    for col in ("avg_speed_score", "full_throttle_score", "lateral_load_score"):
        assert df[col].dropna().between(1, 4).all()


# ── event-name guard (fuzzy-match ghosts) ────────────────────

from f1lib.data_loader import _event_names_match
from f1lib.pitstops_loader import _COLUMNS, _is_partial, _merge_sources


@pytest.mark.parametrize("a,b,expected", [
    ("São Paulo Grand Prix", "São Paulo Grand Prix", True),
    ("S o Paulo Grand Prix", "São Paulo Grand Prix", True),   # from a filename
    ("Sao Paulo Grand Prix", "São Paulo Grand Prix", True),
    ("spanish grand prix", "Spanish Grand Prix", True),
    # the ghosts FastF1 produced by fuzzy matching
    ("Chinese Grand Prix", "Japanese Grand Prix", False),
    ("Emilia Romagna Grand Prix", "Belgian Grand Prix", False),
    ("Barcelona Grand Prix", "Spanish Grand Prix", False),
])
def test_event_names_match(a, b, expected):
    assert _event_names_match(a, b) is expected


# ── pit-stop feed merge ──────────────────────────────────────

def _stops(source, rows):
    return pd.DataFrame([{
        "season": "2026", "meeting": "X", "round": 1, "DriverNo": d,
        "Driver_Short": code, "LapNo": float(lap), "StopNo": n,
        "StationaryTime_s": stat, "PitLaneTime_s": 22.0, "Utc": "",
        "source": source} for d, code, lap, n, stat in rows], columns=_COLUMNS)


def test_merge_prefers_the_fuller_feed():
    # live timing truncated to first stops; Jolpica has every stop
    lt = _stops("livetiming", [("16", "", 9, 1, 2.4), ("44", "", 31, 1, 3.1)])
    jd = _stops("jolpica", [("16", "LEC", 9, 1, np.nan), ("16", "LEC", 28, 2, np.nan),
                            ("44", "HAM", 31, 1, np.nan)])
    out = _merge_sources(lt, jd)
    assert len(out) == 3
    assert out["Driver_Short"].tolist() == ["LEC", "LEC", "HAM"]
    # stationary times grafted where live timing has the same (car, lap)
    assert out["StationaryTime_s"].tolist()[0] == 2.4
    assert np.isnan(out["StationaryTime_s"].tolist()[1])
    assert out["source"].tolist() == ["livetiming", "jolpica", "livetiming"]


def test_merge_keeps_complete_live_timing():
    lt = _stops("livetiming", [("16", "", 9, 1, 2.4)])
    jd = _stops("jolpica", [("16", "LEC", 9, 1, np.nan)])
    out = _merge_sources(lt, jd)
    assert out["source"].tolist() == ["livetiming"]
    assert out["Driver_Short"].tolist() == ["LEC"]


@pytest.mark.parametrize("n,expected,partial", [
    (18, 73, True),      # 2026 Bahrain as first cached
    (60, 61, False),
    (2, 3, False),       # too few stops to judge
    (10, None, False),   # no laps cached to compare against
])
def test_is_partial(n, expected, partial):
    assert _is_partial(n, expected) is partial
