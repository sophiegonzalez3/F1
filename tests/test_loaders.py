"""Tests for the data-collection layer: radio topic tagging, pit-stop
parsing helpers, cache-key sanitisation, and the reference CSVs."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from radio_loader import tag_topics
from pitstops_loader import _parse_duration
from data_loader import _sanitize, _session_key

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


def test_circuit_characteristics_computed_schema():
    p = ROOT / "data" / "circuit_characteristics_computed.csv"
    if not p.exists():
        pytest.skip("computed characteristics not generated yet")
    df = pd.read_csv(p)
    assert {"circuit_key", "avg_speed_score", "full_throttle_score",
            "lateral_load_score"} <= set(df.columns)
    for col in ("avg_speed_score", "full_throttle_score", "lateral_load_score"):
        assert df[col].dropna().between(1, 4).all()
