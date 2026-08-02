"""Circuit identity — that a Grand Prix's *name* never decides which physical
track its data is pooled with.

The three relationships that a single event slug cannot express, each of which
has really happened on the F1 calendar:

  1. same name, different circuit  — Spanish GP: Barcelona → Madring (2026);
                                      Bahrain GP: Sakhir → Sepang (2026)
  2. different name, same circuit  — British + 70th Anniversary (Silverstone);
                                      Austrian + Styrian (Red Bull Ring);
                                      Brazilian + São Paulo (Interlagos)
  3. same venue, different layout  — Bahrain GP vs Sakhir GP (outer loop, 2020)
"""
from pathlib import Path

import pandas as pd
import pytest

from f1lib.circuits import (
    add_circuit_id, audit_calendar, circuit_id, event_slug, french_key,
    has_explicit_rule, same_circuit, _RULES,
)

ROOT = Path(__file__).resolve().parents[1]


# ── 1. same name, different circuit ──────────────────────────

@pytest.mark.parametrize("season,expected", [
    (2019, "barcelona_catalunya"),
    (2025, "barcelona_catalunya"),
    (2026, "madring"),
])
def test_spanish_gp_moves_to_madrid(season, expected):
    assert circuit_id("Spanish Grand Prix", season) == expected


@pytest.mark.parametrize("season,expected", [
    (2024, "sakhir"),
    (2025, "sakhir"),
    (2026, "sepang"),      # relocated by the Middle East conflict, name kept
    (2027, "sakhir"),      # window is 2026-only, so it reverts by itself
])
def test_bahrain_gp_relocates_for_2026_only(season, expected):
    assert circuit_id("Bahrain Grand Prix", season) == expected


def test_relocated_events_do_not_pool():
    assert not same_circuit("Spanish Grand Prix", 2025,
                            "Spanish Grand Prix", 2026)
    assert not same_circuit("Bahrain Grand Prix", 2025,
                            "Bahrain Grand Prix", 2026)


# ── 2. different name, same circuit ──────────────────────────

@pytest.mark.parametrize("a,sa,b,sb", [
    ("British Grand Prix", 2020, "70th Anniversary Grand Prix", 2020),
    ("Austrian Grand Prix", 2021, "Styrian Grand Prix", 2021),
    ("Brazilian Grand Prix", 2019, "São Paulo Grand Prix", 2024),
    ("Mexican Grand Prix", 2019, "Mexico City Grand Prix", 2024),
    # Barcelona kept its history when 2026 renamed it
    ("Spanish Grand Prix", 2025, "Barcelona Grand Prix", 2026),
])
def test_aliases_pool(a, sa, b, sb):
    assert same_circuit(a, sa, b, sb)


def test_sao_paulo_spellings_agree():
    """The archive slug, the ASCII form and track_map_slug's underscore form."""
    ids = {circuit_id(n, 2024) for n in
           ("São Paulo Grand Prix", "Sao Paulo Grand Prix", "s_o_paulo_grand_prix")}
    assert ids == {"interlagos"}


# ── 3. same venue, different layout ──────────────────────────

def test_sakhir_outer_loop_is_a_different_circuit():
    """2020 ran both at Bahrain a week apart, on different layouts — corner 4
    is not the same corner, so these must never pool."""
    assert not same_circuit("Bahrain Grand Prix", 2020, "Sakhir Grand Prix", 2020)
    assert circuit_id("Sakhir Grand Prix", 2020) == "sakhir_outer"


# ── the safe default ─────────────────────────────────────────

def test_unknown_event_gets_its_own_identity():
    """Wrongly splitting is visible and recoverable; wrongly merging is silent
    corruption. A brand-new venue must therefore never inherit an existing id."""
    cid = circuit_id("Cape Town Grand Prix", 2029)
    assert cid == "cape_town_grand_prix"
    assert not has_explicit_rule("Cape Town Grand Prix")
    existing = {c for rules in _RULES.values() for _, _, c in rules}
    assert cid not in existing


def test_event_slug_matches_archive_slugify():
    assert event_slug("Emilia Romagna Grand Prix") == "emilia_romagna_grand_prix"
    assert event_slug("70th Anniversary Grand Prix") == "70th_anniversary_grand_prix"


# ── frame helper ─────────────────────────────────────────────

def test_add_circuit_id_is_per_row_seasonal():
    df = pd.DataFrame({
        "season":     [2025, 2026, 2026],
        "event_name": ["Spanish Grand Prix", "Spanish Grand Prix",
                       "Barcelona Grand Prix"],
    })
    got = add_circuit_id(df)["circuit_id"].tolist()
    assert got == ["barcelona_catalunya", "madring", "barcelona_catalunya"]


# ── the self-defending audit ─────────────────────────────────

def _calendar(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["season", "event", "country", "location"])


def test_audit_flags_an_unregistered_relocation(tmp_path):
    """The check that would have caught Madrid and Sepang without being told."""
    p = tmp_path / "cal.csv"
    _calendar([
        (2025, "Someplace Grand Prix", "Oldland", "Old Town"),
        (2026, "Someplace Grand Prix", "Newland", "New Town"),
    ]).to_csv(p, index=False)
    problems = audit_calendar(p)
    assert len(problems) == 1 and "Someplace Grand Prix" in problems[0]


def test_audit_accepts_a_registered_relocation(tmp_path):
    p = tmp_path / "cal.csv"
    _calendar([
        (2025, "Spanish Grand Prix", "Spain", "Barcelona"),
        (2026, "Spanish Grand Prix", "Spain", "Madrid"),
    ]).to_csv(p, index=False)
    assert audit_calendar(p) == []


def test_audit_ignores_cosmetic_location_renames(tmp_path):
    """FastF1 respells venues between seasons; an audit that cries wolf is
    an audit that gets ignored."""
    p = tmp_path / "cal.csv"
    _calendar([
        (2024, "Monaco Grand Prix", "Monaco", "Monaco"),
        (2026, "Monaco Grand Prix", "Monaco", "Monte Carlo"),
        (2024, "Miami Grand Prix", "United States", "Miami"),
        (2026, "Miami Grand Prix", "United States", "Miami Gardens"),
    ]).to_csv(p, index=False)
    assert audit_calendar(p) == []


# ── TRACK-tab reference key ──────────────────────────────────
#
# The reference data (circuit_characteristics.csv, pirelli_ratings.csv, the
# curated dicts in tabs/track.py) is keyed on a French slug. Resolving it from
# the event name alone gave the 2026 Madrid race Barcelona's profile, Pirelli
# ratings and lap record.

@pytest.mark.parametrize("event,season,expected", [
    ("Spanish Grand Prix",    2025, "espagne"),          # Barcelona
    ("Spanish Grand Prix",    2026, "madrid"),           # the Madring
    ("Barcelona Grand Prix",  2026, "espagne"),
    ("Bahrain Grand Prix",    2025, "bahrein"),
    ("Monaco Grand Prix",     2026, "monaco"),
    ("Hungarian Grand Prix",  2026, "hongrie"),
    # aliases inherit their circuit's reference row
    ("Styrian Grand Prix",         2021, "autriche"),
    ("70th Anniversary Grand Prix", 2020, "grande_bretagne"),
    ("Brazilian Grand Prix",       2019, "bresil"),
])
def test_french_key_is_season_aware(event, season, expected):
    assert french_key(event, season) == expected


@pytest.mark.parametrize("event,season", [
    ("Bahrain Grand Prix", 2026),   # Sepang — must not borrow Sakhir's row
    ("Sakhir Grand Prix",  2020),   # outer loop — must not borrow Bahrain's
    ("Portuguese Grand Prix", 2021),
])
def test_unreferenced_circuits_return_none_not_a_neighbour(event, season):
    """None makes the TRACK tab say "no reference data"; a neighbour's key
    would make it quietly show the wrong circuit."""
    assert french_key(event, season) is None


def test_madrid_never_resolves_to_barcelona():
    """The specific regression: every route from the 2026 Spanish GP must
    avoid Barcelona's reference data."""
    assert french_key("Spanish Grand Prix", 2026) != "espagne"
    assert circuit_id("Spanish Grand Prix", 2026) != \
        circuit_id("Spanish Grand Prix", 2025)
    assert circuit_id("Spanish Grand Prix", 2026) != \
        circuit_id("Barcelona Grand Prix", 2026)


# ── track-map resolution ─────────────────────────────────────

def _write_map(dirpath: Path, season: int, slug: str) -> None:
    """A minimal corner map + racing line, as the track-map cache stores them."""
    stem = f"{season}_{slug}_Q"
    pd.DataFrame({"Number": [1, 2], "X": [0.0, 1.0], "Y": [0.0, 1.0],
                  "Letter": ["", ""]}).to_parquet(
        dirpath / f"{stem}_corners.parquet", index=False)
    pd.DataFrame({"X": [0.0, 1.0], "Y": [0.0, 1.0],
                  "Speed": [100.0, 200.0]}).to_parquet(
        dirpath / f"{stem}.parquet", index=False)


def test_track_map_lookup_never_crosses_venues(tmp_path, monkeypatch):
    """The 2026 Spanish GP is the Madring. With only Barcelona's 2025 map
    cached, the old slug-based fallback served Barcelona's corners for a
    Madrid session — silently, and with no way to notice."""
    import f1lib.mistakes as mistakes
    monkeypatch.setattr(mistakes, "TRACK_MAPS_DIR", tmp_path)
    _write_map(tmp_path, 2025, "spanish_grand_prix")      # Barcelona

    barcelona = mistakes._same_circuit_maps("Spanish Grand Prix", 2025,
                                            "*_corners.parquet")
    madrid = mistakes._same_circuit_maps("Spanish Grand Prix", 2026,
                                         "*_corners.parquet")
    assert len(barcelona) == 1
    assert madrid == []                                    # no map, not a wrong one
    assert mistakes.load_corner_fractions("Spanish Grand Prix", 2026).empty


def test_track_map_lookup_shares_maps_within_a_circuit(tmp_path, monkeypatch):
    """The flip side: one circuit's aliases should share their maps."""
    import f1lib.mistakes as mistakes
    monkeypatch.setattr(mistakes, "TRACK_MAPS_DIR", tmp_path)
    _write_map(tmp_path, 2020, "70th_anniversary_grand_prix")

    found = mistakes._same_circuit_maps("British Grand Prix", 2026,
                                        "*_corners.parquet")
    assert len(found) == 1 and found[0][0] == 2020


def test_parse_map_name_roundtrip():
    import f1lib.mistakes as mistakes
    assert mistakes._parse_map_name(
        Path("2026_barcelona_grand_prix_Q_corners.parquet")) == (2026, "barcelona_grand_prix")
    assert mistakes._parse_map_name(
        Path("2026_hungarian_grand_prix_FP2.parquet")) == (2026, "hungarian_grand_prix")
    assert mistakes._parse_map_name(Path("not_a_map.parquet")) is None


def test_real_calendar_is_registered():
    """Tripwire: the shipped calendar must have no unregistered relocation."""
    cal = ROOT / "data" / "season_calendar.csv"
    if not cal.exists():
        pytest.skip("season_calendar.csv not generated yet")
    assert audit_calendar(cal) == []
