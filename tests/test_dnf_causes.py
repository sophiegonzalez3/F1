"""Curated DNF causes layered over the race-control register.

The archive stopped recording causes in 2023 (bare "Retired"), race control
recovers only the contact it investigated, and the ~169 retirements it never
saw can come from press or nowhere. The properties worth pinning are the ones
that keep the two layers honest:

1. MEASURED BEATS REPORTED. A curated row must never overwrite a cause race
   control established. Otherwise one curation mistake silently rewrites an
   FIA record, and nothing in the chart would show it.
2. A SKELETON IS NOT AN ANSWER. seed_dnf_causes.py writes blank rows as a
   worklist. A blank `cause_family` must read as "still unknown", never as a
   cause, or the seeding step would itself "classify" 171 retirements.
3. "LOOKED, FOUND NOTHING" IS A DISTINCT STATE. `press_checked` stamped with a
   blank family is the honest record of a search that came up empty. It must
   not become a cause, and it must stay countable.
"""
import pandas as pd
import pytest

import f1lib.dnf_causes as dc


def _curated(monkeypatch, rows):
    df = pd.DataFrame(rows, columns=dc.COLS)
    monkeypatch.setattr(dc, "causes_df", lambda: df)


def _register(monkeypatch, cause):
    """Pin what race control would say, so the layering is what is tested."""
    import f1lib.incidents as inc
    monkeypatch.setattr(
        inc, "classify_retirement",
        lambda *a, **k: {"cause": cause, "incident_lap": None,
                         "counterparty": "SAI" if cause == "collision" else "",
                         "earlier_contact": False})


# ── layer ordering ───────────────────────────────────────────

def test_race_control_outranks_curation(monkeypatch):
    """The register says collision; the curated file says mechanical. The
    register wins and the curated row is ignored, not merged."""
    _register(monkeypatch, "collision")
    _curated(monkeypatch, [{
        "season": 2026, "event": "Dutch Grand Prix", "driver": "ALB",
        "cause_family": "mechanical", "confidence": "reported"}])
    got = dc.resolve_cause(2026, "Dutch Grand Prix", "ALB", 66)
    assert got["cause_family"] == "collision"
    assert got["cause_source"] == "race_control"
    assert got["confidence"] == "measured"


def test_curation_fills_only_what_race_control_missed(monkeypatch):
    _register(monkeypatch, "unclassified")
    _curated(monkeypatch, [{
        "season": 2026, "event": "Dutch Grand Prix", "driver": "OCO",
        "cause_family": "mechanical", "confidence": "reported"}])
    got = dc.resolve_cause(2026, "Dutch Grand Prix", "OCO", 52)
    assert got["cause_family"] == "mechanical"
    assert got["cause_source"] == "press"


def test_unknown_stays_unknown_when_neither_layer_has_it(monkeypatch):
    _register(monkeypatch, "unclassified")
    _curated(monkeypatch, [])
    got = dc.resolve_cause(2026, "Dutch Grand Prix", "BOT", 61)
    assert got["cause_family"] == ""
    assert got["cause_source"] == ""


# ── the curated file's own discipline ────────────────────────

def test_a_seeded_but_unfilled_row_is_not_a_cause(monkeypatch):
    """171 skeletons were seeded. If a blank family read as an answer, the
    seeding step alone would 'explain' every retirement in the archive."""
    _curated(monkeypatch, [{
        "season": 2026, "event": "Dutch Grand Prix", "driver": "BOT",
        "cause_family": "", "confidence": ""}])
    assert dc.curated_cause(2026, "Dutch Grand Prix", "BOT") is None


def test_press_checked_without_a_family_is_still_not_a_cause(monkeypatch):
    """'I looked and the press never said' is a real, recorded state — and it
    is emphatically not a classification."""
    _curated(monkeypatch, [{
        "season": 2026, "event": "Dutch Grand Prix", "driver": "STR",
        "cause_family": "", "press_checked": "2026-08-23",
        "note": "no cause given by any source"}])
    assert dc.curated_cause(2026, "Dutch Grand Prix", "STR") is None


def test_an_unrecognised_family_is_rejected_not_passed_through(monkeypatch):
    """A typo must not invent a bucket the card has no colour for."""
    _curated(monkeypatch, [{
        "season": 2026, "event": "Dutch Grand Prix", "driver": "BEA",
        "cause_family": "gearboxx", "confidence": "reported"}])
    assert dc.curated_cause(2026, "Dutch Grand Prix", "BEA") is None


def test_a_team_statement_can_be_marked_as_a_claim(monkeypatch):
    _curated(monkeypatch, [{
        "season": 2026, "event": "Dutch Grand Prix", "driver": "OCO",
        "cause_family": "mechanical", "confidence": "claimed"}])
    got = dc.curated_cause(2026, "Dutch Grand Prix", "OCO")
    assert got["confidence"] == "claimed", (
        "a principal saying 'a PU issue' must stay filterable")


def test_no_withdrawal_family():
    """Measured, not assumed: the 2019-2022 archive holds 3 `Withdrew` and 2
    `Illness` rows in four seasons, and reliability.py already buckets those
    under 'Did not start'. Disqualification is twice as common and IS a
    family."""
    assert "withdrawal" not in dc.FAMILIES
    assert "disqualified" in dc.FAMILIES


def test_families_are_descriptive_not_attributive():
    """'solo accident' describes what happened; 'driver error' would assign a
    fault nobody measured."""
    assert "solo accident" in dc.FAMILIES
    assert "driver error" not in dc.FAMILIES


# ── against the real file ────────────────────────────────────

def test_curated_file_uses_only_known_families_and_confidences():
    d = dc.causes_df()
    if d.empty:
        pytest.skip("data/dnf_causes.csv not seeded")
    fam = d["cause_family"].astype(str).str.strip().str.lower()
    bad = set(fam[fam.ne("") & fam.ne("nan")]) - set(dc.FAMILIES)
    assert not bad, f"unknown cause_family values: {bad}"
    conf = d["confidence"].astype(str).str.strip().str.lower()
    badc = set(conf[conf.ne("") & conf.ne("nan")]) - set(dc.CONFIDENCE)
    assert not badc, f"unknown confidence values: {badc}"


def test_every_filled_row_cites_a_source():
    """The house rule for every curated CSV: a claim without a URL is not a
    row. Enforced here because this file's whole purpose is provenance."""
    d = dc.causes_df()
    if d.empty:
        pytest.skip("data/dnf_causes.csv not seeded")
    fam = d["cause_family"].astype(str).str.strip().str.lower()
    filled = d[fam.isin(dc.FAMILIES)]
    if filled.empty:
        pytest.skip("nothing curated yet")
    src = filled["source"].astype(str).str.strip()
    missing = filled.loc[src.eq("") | src.eq("nan"), "driver"].tolist()
    assert not missing, f"curated rows with no source: {missing}"


def test_curated_rows_never_duplicate_a_race_control_collision():
    """'Do not curate what is measurable' — a hand-written collision would
    shadow the register and drift from it. The seeder skips these; this
    catches one added by hand."""
    from f1lib.incidents import classify_retirement
    d = dc.causes_df()
    if d.empty:
        pytest.skip("data/dnf_causes.csv not seeded")
    fam = d["cause_family"].astype(str).str.strip().str.lower()
    clash = []
    for _, row in d[fam.eq("collision")].iterrows():
        got = classify_retirement(row["season"], str(row["event"]),
                                  row["driver"], row.get("laps"))
        if got["cause"] == "collision":
            clash.append(f"{row['season']} {row['event']} {row['driver']}")
    assert not clash, f"curated collisions the register already owns: {clash}"
