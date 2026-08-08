"""Guards for the Polymarket historical source.

It exists to reach races Kalshi has pruned, and it is fetched by hand over a
VPN. That combination makes three things worth pinning.

1. TIMESTAMP ALIGNMENT. De-vigging needs the whole field priced at one
   instant. Polymarket downsamples old markets, so fetching each contract at
   whatever fidelity it happens to serve mixes hourly and 12-hourly inside one
   race and no two drivers share a timestamp — yielding snapshots of one or
   two runners whose overround is near zero. Numbers that look computed and
   mean nothing.

2. THE FIELD BUCKET. "Other" and "Driver A".."Driver E" are real contracts
   carrying real money. They must stay in the book (or normalisation runs
   against an incomplete one) but must never be joined to a car.

3. THE BLOCK IS LEGIBLE. From France the API is DNS-hijacked to a regulator
   block page. That has to surface as "your VPN is off", not as a raw SSL
   error, because forgetting the VPN is the expected failure mode.
"""
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from f1lib import polymarket as pm
from f1lib.odds import load_calendar


# ─────────────────────────────────────────────────────────────
# identity
# ─────────────────────────────────────────────────────────────

def test_driver_names_map_to_repo_three_letter_codes():
    m = pm.name_to_code()
    if not m:
        pytest.skip("results archive not present")
    for name, want in [("Max Verstappen", "VER"), ("Pierre Gasly", "GAS"),
                       ("Charles Leclerc", "LEC"), ("Lando Norris", "NOR")]:
        assert pm.code_for(name) == want, name


def test_honorific_suffix_does_not_break_the_surname_fallback():
    """Polymarket writes 'Carlos Sainz Jr.', where the last token is the
    suffix rather than the family name. Taking the last token blindly loses a
    real driver's whole price series."""
    if not pm.name_to_code():
        pytest.skip("results archive not present")
    assert pm.code_for("Carlos Sainz Jr.") == "SAI"


@pytest.mark.parametrize("label", ["Other", "Driver A", "Driver E", "field"])
def test_field_buckets_are_labelled_not_dropped(label):
    """They carry real money and belong in the book; they are simply not a
    car. Dropping them would normalise against an incomplete market."""
    assert pm.code_for(label) == pm.FIELD_CODE


def test_unknown_driver_returns_empty_not_a_guess():
    assert pm.code_for("Nobody McNobody") == ""


def test_accented_name_maps():
    """Polymarket writes 'Nico Hulkenberg' with an umlaut, the archive without.
    Stripping non-ASCII without folding gives 'hlkenberg' and silently loses
    that driver's entire price series across every race."""
    if not pm.name_to_code():
        pytest.skip("results archive not present")
    assert pm.code_for("Nico Hülkenberg") == "HUL"


@pytest.mark.parametrize("typo,want", [("Nico Hulkenburg", "HUL"),
                                       ("George Russel ", "RUS")])
def test_misspelled_names_still_map(typo, want):
    """Real labels seen in the feed. Both were writing blank driver codes."""
    if not pm.name_to_code():
        pytest.skip("results archive not present")
    assert pm.code_for(typo) == want


def test_team_name_is_not_mistaken_for_a_driver():
    if not pm.name_to_code():
        pytest.skip("results archive not present")
    for team in ("Ferrari", "Aston Martin", "Alpine"):
        assert pm.code_for(team) == "", team


def test_fuzzy_fallback_does_not_invent_a_teammate():
    """The 0.88 cutoff has to be tight enough that a genuinely unknown name
    stays unknown rather than being snapped onto the nearest driver."""
    if not pm.name_to_code():
        pytest.skip("results archive not present")
    for bogus in ("Nobody McNobody", "Some Person", "Driver Zed"):
        assert pm.code_for(bogus) in ("", pm.FIELD_CODE), bogus


# ─────────────────────────────────────────────────────────────
# classification
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("slug,expect", [
    ("f1-belgian-grand-prix-driver-podium-2026-07-19", "podium"),
    ("f1-singapore-grand-prix-winner", "win"),
    ("f1-italian-grand-prix-driver-pole-position-2026-09-06", "pole"),
    ("china-grand-prix-sprint-winner", "sprint_win"),
])
def test_slug_classification(slug, expect):
    got = pm.classify({"slug": slug, "title": "Grand Prix"})
    assert got is not None and got.market == expect


@pytest.mark.parametrize("slug", [
    "2025-chevrolet-detroit-grand-prix-winner",   # IndyCar
    "indycar-grand-prix-winner",
    "f1-constructors-champion",                   # season-long, not a race
    "2026-f1-drivers-champion",
    # Per-race but priced on TEAMS. A plural-only pattern let these through
    # and they wrote ~11.5k rows whose driver code was blank, because
    # "Ferrari" is not a driver.
    "f1-hungarian-grand-prix-constructor-pole-position-2026-07-26",
    "f1-belgian-grand-prix-constructor-pole-position-2026-07-19",
])
def test_non_race_and_non_f1_events_are_skipped(slug):
    assert pm.classify({"slug": slug, "title": "Grand Prix"}) is None


def test_podium_keeps_arity_three():
    assert pm.classify({"slug": "f1-x-grand-prix-driver-podium-2026-01-01",
                        "title": "Grand Prix"}).arity == 3


# ─────────────────────────────────────────────────────────────
# dates and mapping
# ─────────────────────────────────────────────────────────────

def test_slug_date_beats_a_wrong_end_date():
    """The 2026 Belgian podium carries endDate a full week late, which lands
    on the Hungarian Grand Prix. The slug's own date has never been wrong, so
    it must win."""
    ev = {"slug": "f1-belgian-grand-prix-driver-podium-2026-07-19",
          "endDate": "2026-07-26T13:00:00Z", "markets": []}
    assert pm.event_date(ev).date().isoformat() == "2026-07-19"


def test_event_maps_to_the_named_race_not_the_nearest_date():
    cal = load_calendar()
    if cal.empty or cal[cal.season == 2026].empty:
        pytest.skip("calendar not present")
    ev = {"slug": "f1-belgian-grand-prix-driver-podium-2026-07-19",
          "title": "Belgian Grand Prix: Driver Podium Finish",
          "endDate": "2026-07-26T13:00:00Z", "markets": []}
    season, rnd, name = pm.resolve(ev, cal)
    assert (season, name) == (2026, "Belgian Grand Prix")


def test_relocated_race_resolves_by_name_despite_a_far_off_date():
    """A market's date is the date it was CREATED against. The 2026 Bahrain
    Grand Prix is run in Malaysia months off its original slot, so its markets
    are slugged April while the race is in October — 175 days apart. The name
    is unambiguous and must be allowed to win on its own, or every rescheduled
    race silently resolves to nothing.
    """
    cal = load_calendar()
    if cal.empty or cal[cal.season == 2026].empty:
        pytest.skip("calendar not present")
    bah = cal[(cal.season == 2026) & cal.event.str.contains("Bahrain", case=False)]
    if bah.empty:
        pytest.skip("no 2026 Bahrain round in the calendar")
    ev = {"slug": "f1-bahrain-grand-prix-driver-podium-2026-04-12",
          "title": "Bahrain Grand Prix: Driver Podium Finish", "markets": []}
    season, rnd, name = pm.resolve(ev, cal)
    assert (season, name) == (2026, "Bahrain Grand Prix")
    assert rnd == int(bah.iloc[0]["round"])


def test_market_description_words_do_not_dilute_the_race_name():
    """'Bahrain Grand Prix: Driver Podium Finish' scored 0.42 against 'Bahrain
    Grand Prix' while 'driver' and 'finish' survived normalisation — under the
    threshold, so it matched nothing."""
    from f1lib.odds import _norm, _similar
    assert _similar(_norm("Bahrain Grand Prix: Driver Podium Finish"),
                    _norm("Bahrain Grand Prix")) > 0.9


def test_typo_in_slug_still_resolves():
    """Polymarket ships 'azerbijan-grand-prix-winner'. Token-set matching
    scores that a flat zero against 'Azerbaijan'."""
    cal = load_calendar()
    if cal.empty or cal[cal.season == 2024].empty:
        pytest.skip("2024 calendar not present")
    ev = {"slug": "azerbijan-grand-prix-winner",
          "title": "Azerbaijan Grand Prix Winner",
          "endDate": "2024-09-15T12:00:00Z", "markets": []}
    _, _, name = pm.resolve(ev, cal)
    assert name == "Azerbaijan Grand Prix"


# ─────────────────────────────────────────────────────────────
# the alignment bug
# ─────────────────────────────────────────────────────────────

def test_grid_snaps_points_onto_a_common_clock():
    step = 720 * 60
    a = pm._grid(1764000123, 720)
    b = pm._grid(1764000987, 720)
    assert a == b and a % step == 0


def test_mixed_fidelity_would_break_the_book_so_one_is_chosen():
    """Regression guard for the real bug: per-contract fidelity fallback gave
    252 rows spread over 175 snapshots — 1.4 runners each — and every
    overround was meaningless. One fidelity per event is the fix."""
    class FakeClient:
        def __init__(self):
            self.asked = []

        def prices_history(self, token, fidelity):
            self.asked.append(fidelity)
            return [] if fidelity == 60 else [{"t": 1764000000, "p": 0.5}]

    ev = {"markets": [{"clobTokenIds": json.dumps([f"t{i}", f"n{i}"]),
                       "groupItemTitle": f"D{i}", "volumeNum": 100 - i}
                      for i in range(5)]}
    c = FakeClient()
    frames, used = pm.fetch_series(c, ev, fidelity=60)
    assert used == 720, "should fall back once for the whole event"
    assert len(frames) == 1, f"field split across {len(frames)} timestamps"
    assert len(next(iter(frames.values()))) == 5, "not every runner in the book"
    assert 60 not in c.asked[3:], "kept probing hourly per contract"


# ─────────────────────────────────────────────────────────────
# the overround filter
# ─────────────────────────────────────────────────────────────

def test_stale_flat_prices_show_up_as_a_broken_overround():
    """A 12h candle with no trades returns 0.50 rather than a gap. That must
    remain VISIBLE in overround, because the de-vigger cannot tell a wrong
    book from a wide one and will normalise it without complaint."""
    from f1lib.odds import MarketKind, build_rows
    good = [{"ticker": f"t{i}", "yes_sub_title": f"D{i}", "_code": f"D{i}",
             "last_price_dollars": p} for i, p in
            enumerate([0.88, 0.71, 0.66, 0.36, 0.17, 0.05, 0.02, 0.01])]
    stale = good[:3] + [{"ticker": f"s{i}", "yes_sub_title": f"S{i}",
                         "_code": f"S{i}", "last_price_dollars": 0.50}
                        for i in range(5)]
    kind = MarketKind("podium", 3)
    f = lambda ms: build_rows(ms, kind, "s", "e", 2025, 1, None, "2025-01-01T00:00:00Z",
                              bookmaker="polymarket",
                              code_of=lambda m: m.get("_code", ""))[0]["overround"]
    assert f(good) < 1.25, "a real book should pass the documented filter"
    assert f(stale) > 1.5, "a stale book must NOT pass it"


# ─────────────────────────────────────────────────────────────
# forgetting the VPN
# ─────────────────────────────────────────────────────────────

def test_block_raises_a_named_error_not_a_raw_ssl_failure():
    """Forgetting the VPN is the expected failure, so it gets its own type
    and a message that says what to do."""
    import ssl
    import urllib.error
    c = pm.PolymarketClient(min_interval=0)

    def boom(*a, **k):
        raise urllib.error.URLError(ssl.SSLCertVerificationError("hostname mismatch"))

    import urllib.request
    orig, urllib.request.urlopen = urllib.request.urlopen, boom
    try:
        with pytest.raises(pm.PolymarketBlocked) as e:
            c.check_reachable()
    finally:
        urllib.request.urlopen = orig
    assert "vpn" in str(e.value).lower()


def test_missing_events_reports_the_gap_offline(tmp_path):
    """after_race.py prints this reminder with the VPN off, so it must never
    touch the network."""
    p = tmp_path / "odds.csv"
    pd.DataFrame([
        {"season": 2026, "event": "Belgian Grand Prix", "bookmaker": "kalshi", "market": "win"},
        {"season": 2026, "event": "Belgian Grand Prix", "bookmaker": "polymarket", "market": "win"},
        {"season": 2026, "event": "Monaco Grand Prix", "bookmaker": "kalshi", "market": "win"},
    ]).to_csv(p, index=False)
    assert pm.missing_events(p) == ["Monaco Grand Prix"]


def test_missing_events_on_a_fresh_repo_is_empty(tmp_path):
    assert pm.missing_events(tmp_path / "nope.csv") == []
