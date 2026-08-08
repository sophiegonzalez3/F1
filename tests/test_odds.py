"""Guards for the odds feed.

Three things here are worth a test rather than a comment.

1. MARKET ARITY. A podium market has three winners, so its prices sum to ~3.
   Every de-vigger takes `arity` and must hit it exactly. Normalising podium
   to 1.0 is the single most likely mistake in this feed and it would be wrong
   by a factor of three on the market the whole calibration study rests on.

2. THE SETTLED-BOOK MIDPOINT. Kalshi reports bid=0.00 / ask=1.00 on a market
   with no live book. That midpoint is a perfectly plausible-looking 0.50 and
   would quietly poison a calibration study with fake coin-flips.

3. LEAKAGE. Odds must never reach the model. If the forecaster consumed the
   market it could no longer be SCORED against the market, and any future
   betting edge would be gone by construction. That is a property of the
   import graph, so it is pinned structurally rather than trusted.
"""
import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from f1lib.odds import (COLUMNS, MARKET_KINDS, append_snapshots, build_rows,
                        devig_basic, devig_power, devig_shin, driver_code,
                        load_calendar, pick_price, resolve_event)

ROOT = Path(__file__).resolve().parents[1]

# A realistic 20-runner F1 outright book: one clear favourite, a long tail,
# and a 13% overround — the shape measured on Hungary 2026.
BOOK = np.array([0.345, 0.295, 0.220, 0.115, 0.040, 0.025, 0.020, 0.015,
                 0.012, 0.010, 0.008, 0.006, 0.005, 0.004, 0.003, 0.002])


# ─────────────────────────────────────────────────────────────
# de-vigging
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fn", [devig_basic, devig_power])
@pytest.mark.parametrize("arity", [1, 3])
def test_devig_sums_to_arity(fn, arity):
    """The whole point: a de-vigged book sums to the number of winners."""
    out = fn(BOOK * arity, arity)
    assert np.isclose(np.nansum(out), arity, atol=1e-6)


def test_shin_sums_to_one():
    out = devig_shin(BOOK, 1)
    assert np.isclose(np.nansum(out), 1.0, atol=1e-6)


def test_shin_abstains_on_multi_winner_markets():
    """Shin models a book on a partition of outcomes. A three-slot podium is
    not one, so it returns NaN rather than a confident wrong number."""
    assert np.all(np.isnan(devig_shin(BOOK * 3, 3)))


@pytest.mark.parametrize("fn", [devig_power, devig_shin])
def test_devig_shrinks_longshots_more_than_favourites(fn):
    """Favourite-longshot bias: naive normalisation scales everyone equally,
    so it leaves the tail too fat. Both real methods must take proportionally
    more out of the longshots than out of the favourite."""
    basic, other = devig_basic(BOOK, 1), fn(BOOK, 1)
    fav = other[0] / basic[0]
    tail = np.nansum(other[-8:]) / np.nansum(basic[-8:])
    assert tail < fav, f"{fn.__name__} did not shrink the tail (tail={tail:.3f} fav={fav:.3f})"


def test_devig_handles_underround():
    """A thin exchange book can sum to LESS than the arity. That is not an
    error and must not raise or return garbage."""
    thin = np.array([0.30, 0.25, 0.20])
    for fn in (devig_basic, devig_power, devig_shin):
        out = fn(thin, 1)
        assert np.isclose(np.nansum(out), 1.0, atol=1e-6), fn.__name__


@pytest.mark.parametrize("bad", [np.array([np.nan, np.nan]), np.array([0.5]),
                                 np.array([0.0, 0.0])])
def test_devig_degenerate_input_is_nan_not_exception(bad):
    for fn in (devig_basic, devig_power, devig_shin):
        fn(bad, 1)          # must not raise


def test_raw_price_is_preserved_alongside_devigged():
    """The fetch cannot be repeated after the fact, so the raw price must
    survive in the file for any future method to be applied to."""
    for c in ("p_raw", "p_devig_basic", "p_devig_power", "p_devig_shin",
              "yes_bid", "yes_ask", "overround"):
        assert c in COLUMNS


# ─────────────────────────────────────────────────────────────
# price selection
# ─────────────────────────────────────────────────────────────

def test_empty_book_does_not_become_a_coin_flip():
    price, src = pick_price(0.0, 1.0, None)
    assert src == "none" and np.isnan(price)


def test_empty_book_falls_back_to_last_trade():
    price, src = pick_price(0.0, 1.0, 0.42)
    assert src == "last" and price == pytest.approx(0.42)


def test_tight_book_uses_midpoint():
    price, src = pick_price(0.34, 0.36, 0.30)
    assert src == "mid" and price == pytest.approx(0.35)


# ─────────────────────────────────────────────────────────────
# identity
# ─────────────────────────────────────────────────────────────

def test_driver_code_matches_repo_three_letter_convention():
    assert driver_code("KXF1RACE-HUNGP26-NOR", "KXF1RACE-HUNGP26") == "NOR"
    assert driver_code("KXF1H2H-BRIGP26VERHAM-VER", "KXF1H2H-BRIGP26VERHAM") == "VER"


def test_event_resolves_by_date_not_by_ticker_name():
    """Kalshi's ticker suffix changed format between 2025 and 2026 and its
    sub_title drifts, so the join is on the race date. A pole market closing
    on the Saturday must still land on the right event."""
    cal = load_calendar()
    if cal.empty:
        pytest.skip("season_calendar.csv not present")
    row = cal[cal["season"].astype(int) == 2026]
    if row.empty:
        pytest.skip("no 2026 calendar rows")
    target = row.iloc[len(row) // 2]
    race_day = target["event_date"].to_pydatetime().replace(tzinfo=None)

    from datetime import timezone
    for offset, label in [(0, "race day"), (-1, "quali Saturday")]:
        close = (race_day + pd.Timedelta(days=offset)).replace(tzinfo=timezone.utc)
        season, rnd, event = resolve_event(close, "", "", cal)
        assert event == target["event"], f"{label}: got {event}"
        assert rnd == int(target["round"])


def test_unmatched_event_degrades_to_none_not_to_a_wrong_race():
    cal = load_calendar()
    if cal.empty:
        pytest.skip("season_calendar.csv not present")
    from datetime import datetime, timezone
    # mid-February: no race within 4 days of it in any season
    season, rnd, event = resolve_event(
        datetime(2026, 2, 14, tzinfo=timezone.utc), "Nowhere GP", "", cal)
    assert event is None and rnd is None and season == 2026


# ─────────────────────────────────────────────────────────────
# the lock-time trap
# ─────────────────────────────────────────────────────────────

def test_pre_lock_flag_is_set_relative_to_the_session_not_the_close():
    """Kalshi's close_time is SETTLEMENT. Hungary 2026 closed at 18:00:52 UTC
    with the race starting at 13:00, so a price 'two hours before close' was
    taken with most of the race already run. Scoring against those gives a
    Brier of 0.0000 and 100% skill — leakage that looks like a triumph.

    Anything at or after lights out must be flagged, whatever close_time says.
    """
    kind = MARKET_KINDS["KXF1RACE"]
    made = [build_rows(_fake_markets(1), kind, "KXF1RACE", "KXF1RACE-XGP26",
                       2026, 11, "Hungarian Grand Prix", ts)[0]
            for ts in ("2026-07-25T13:00:00Z",   # day before  -> pre-lock
                       "2026-07-26T16:00:00Z")]  # mid-race    -> NOT pre-lock
    if made[0]["locks_at"] is None:
        pytest.skip("FastF1 schedule unavailable; locks_at degrades to blank")
    assert made[0]["pre_lock"] is True, "day-before price wrongly flagged post-lock"
    assert made[1]["pre_lock"] is False, (
        "a price taken during the race was accepted as pre-race - this is the "
        "leakage that makes the benchmark meaningless")
    assert made[1]["locks_at"] < made[1]["close_time"], (
        "locks_at must precede close_time; if they are equal the settlement "
        "time has been mistaken for the race start again")


def test_season_long_markets_have_no_lock_time():
    """The WDC has no single moment it becomes knowable, so it gets no
    lock stamp rather than a misleading one."""
    row = build_rows(_fake_markets(1), MARKET_KINDS["KXF1"], "KXF1", "KXF1-26",
                     2026, None, None, "2026-07-01T00:00:00Z")[0]
    assert row["locks_at"] is None and row["pre_lock"] is None


# ─────────────────────────────────────────────────────────────
# storage
# ─────────────────────────────────────────────────────────────

def _fake_markets(n=4):
    return [{"ticker": f"KXF1RACE-XGP26-D{i}", "yes_sub_title": f"Driver {i}",
             "yes_bid_dollars": 0.30 - 0.05 * i,
             "yes_ask_dollars": 0.32 - 0.05 * i,
             "last_price_dollars": 0.31 - 0.05 * i,
             "volume_fp": "100", "open_interest_fp": "10",
             "status": "finalized", "result": "no",
             "close_time": "2026-07-26T18:00:00Z"} for i in range(n)]


def test_append_is_idempotent(tmp_path):
    """Backfill re-runs must not duplicate. The key is
    (snapshot_ts, bookmaker, market_ticker)."""
    rows = build_rows(_fake_markets(), MARKET_KINDS["KXF1RACE"], "KXF1RACE",
                      "KXF1RACE-XGP26", 2026, 11, "Hungarian Grand Prix",
                      "2026-07-26T12:00:00Z")
    out = tmp_path / "odds.csv"
    added1, total1 = append_snapshots(rows, out)
    added2, total2 = append_snapshots(rows, out)
    assert added1 == len(rows) and added2 == 0 and total1 == total2


def test_append_is_additive_across_snapshots(tmp_path):
    out = tmp_path / "odds.csv"
    for ts in ("2026-07-26T12:00:00Z", "2026-07-26T13:00:00Z"):
        rows = build_rows(_fake_markets(), MARKET_KINDS["KXF1RACE"], "KXF1RACE",
                          "KXF1RACE-XGP26", 2026, 11, "Hungarian Grand Prix", ts)
        append_snapshots(rows, out)
    d = pd.read_csv(out)
    assert d["snapshot_ts"].nunique() == 2 and len(d) == 8
    assert list(d.columns) == COLUMNS


# ─────────────────────────────────────────────────────────────
# leakage
# ─────────────────────────────────────────────────────────────
#
# The market is the YARDSTICK. A model that has seen it cannot be measured
# against it, and would carry no edge if this were ever used to bet.

# Anything that PRODUCES a prediction. None of it may so much as mention the
# odds feed.
#
# `scripts/backtest_race_forecast.py` is deliberately NOT here: it SCORES
# predictions against the market, which is the entire purpose of collecting
# the market, and is what this rule's own failure message tells you to do
# ("put the comparison in an evaluation script instead"). The guarantee that
# matters there is narrower and is pinned separately below — the part of it
# that builds forecasts must stay odds-blind.
MODEL_PATH = [
    "f1lib/pace_features.py", "f1lib/pace_model.py", "f1lib/race_forecast.py",
    "f1lib/driver_ratings.py", "f1lib/duel.py", "f1lib/processing.py",
    "scripts/compute_team_pace.py", "scripts/compute_weekend_decomp.py",
    "scripts/backtest_pace_model.py", "scripts/rolling_holdout.py",
]

FORBIDDEN = ("odds_snapshots", "f1lib.odds", "f1lib/odds", "kalshi")


@pytest.mark.parametrize("rel", MODEL_PATH)
def test_model_path_never_reads_odds(rel):
    """Structural, not aspirational: if a model module ever mentions the odds
    feed this fails, whatever the intention was."""
    p = ROOT / rel
    if not p.exists():
        pytest.skip(f"{rel} not present")
    src = p.read_text(encoding="utf-8", errors="ignore").lower()
    for token in FORBIDDEN:
        assert token not in src, (
            f"{rel} references '{token}'. Odds are the benchmark the outcome "
            f"model is scored against - feeding them back in makes that score "
            f"meaningless. Put the comparison in an evaluation script instead.")


def test_the_backtest_builds_forecasts_before_it_ever_sees_the_market():
    """The scorecard is allowed to READ odds — that is its job. What it may
    never do is let them touch a prediction.

    Pinned on `replay()`, the function that runs the pace model and the
    forecaster: it must be odds-blind, so the market can only ever be joined
    on afterwards to score what was already produced. Without this, the
    file's exemption from MODEL_PATH would be an unguarded hole.
    """
    src = (ROOT / "scripts" / "backtest_race_forecast.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "replay"), None)
    assert fn is not None, "replay() has been renamed - update this guard"
    # Statements only — the docstring is free to discuss the market, since
    # explaining why the file is arranged this way is the point of it.
    stmts = fn.body
    if (stmts and isinstance(stmts[0], ast.Expr)
            and isinstance(getattr(stmts[0], "value", None), ast.Constant)
            and isinstance(stmts[0].value.value, str)):
        stmts = stmts[1:]
    body = "\n".join(ast.get_source_segment(src, s) or "" for s in stmts)
    for token in ("odds", "mkt_", "market", "devig", "bookmaker"):
        assert token not in body.lower(), (
            f"replay() mentions '{token}'. It generates the forecasts being "
            f"scored, so it must not see the market at all - join the odds on "
            f"afterwards, in add_market().")


def test_odds_module_imports_no_model_code():
    """The dependency must not run the other way either: f1lib/odds.py is a
    collector, so importing the forecaster here would invite a future edit
    that closes the loop."""
    tree = ast.parse((ROOT / "f1lib" / "odds.py").read_text(encoding="utf-8"))
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
    banned = {"f1lib.pace_model", "f1lib.race_forecast", "f1lib.pace_features",
              "f1lib.driver_ratings"}
    assert not (imported & banned), f"odds.py imports model code: {imported & banned}"
