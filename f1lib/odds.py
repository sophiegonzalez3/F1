"""Market-implied probabilities: the Kalshi client, and the de-vigging maths.

WHY THIS EXISTS
---------------
`race_forecast.py` emits p_win / p_podium / p_points / e_finish / p_dnf and has
never been scored on any of them — `backtest_pace_model.csv` measures PACE
error only. A betting market is a well-calibrated probability reference that is
available BEFORE the race, so a systematic disagreement between our p_podium
and the market is the most informative signal available about the outcome
layer, and it does not require waiting for a result.

WHY KALSHI AND NOT A BOOKMAKER
------------------------------
F1 coverage is the binding constraint, and almost nothing has it. Verified
2026-08-08:

  the-odds-api.com   no motorsport at all - 15 sport groups, zero racing
  sportsdataapi.com  DNS no longer resolves; the service is gone
  sportmonks.com     F1 product is stats, not odds; EUR 79/mo, no free tier
  polymarket.com     DNS-blocked from France (resolves to an *.anj.fr cert -
                     the ANJ regulator block page), so unusable unattended
  Betfair Exchange   real F1 outrights, but needs an account + app key

Kalshi is a CFTC-regulated exchange whose public market-data REST API needs no
account, no key and no auth, and it lists per-race F1 markets that map almost
one-to-one onto the forecaster's outputs. Prices are already probabilities in
dollars (0-1), which is what we want; a bookmaker's decimal odds would need
inverting first.

WHAT IS NOT COVERED, HONESTLY
-----------------------------
`p_points` (top-10) and `p_dnf` have NO market. `KXF1RACETOP10` exists as a
series but has never been populated for F1, and `KXF1RETIRE` is about a driver
leaving the SPORT, not retiring from a race. The calibration study therefore
covers win / podium / pole, not the full quartet.

LEAKAGE
-------
Nothing here may ever become a model input. If the market feeds the forecaster,
the forecaster can no longer be scored against the market (and any future
betting edge is gone by construction). `tests/test_odds.py` pins that
structurally: no module on the model path is allowed to read odds_snapshots.csv.
This module is read by the collector and by evaluation code only.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

logger = logging.getLogger(__name__)

API = "https://api.elections.kalshi.com/trade-api/v2"
BOOKMAKER = "kalshi"
CALENDAR = Path("data/season_calendar.csv")

# Measured 2026-08-08: 12 rapid requests all succeeded at ~4.9 req/s, but a
# 33-request sweep tripped 429 partway. Throttle below the observed ceiling
# rather than at it — this runs unattended and a ban helps nobody.
MIN_INTERVAL = 0.35          # seconds between requests
MAX_RETRIES = 5

# A yes/no book this wide carries no usable information: on a settled or
# not-yet-traded market Kalshi reports bid=0.00 / ask=1.00, whose midpoint is a
# meaningless 0.50. Anything at or above this falls back to the last trade.
MAX_SPREAD = 0.25


# ─────────────────────────────────────────────────────────────
# What we collect
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MarketKind:
    """One Kalshi series and how to read it.

    `arity` is how many of the listed contracts settle YES, and it is the part
    that is easy to get wrong: a podium market has THREE winners, so its prices
    sum to ~3, not ~1. Normalising it to 1.0 would be wrong by a factor of
    three on the single most important market we collect.

    `lock_session` is the session whose START makes the outcome unknowable-no-
    more. It exists because `close_time` is NOT that moment — see `lock_time`.
    """
    market: str
    arity: int
    scope: str = "race"       # race | season
    entity: str = "driver"    # driver | team
    lock_session: str | None = "Race"


MARKET_KINDS: dict[str, MarketKind] = {
    "KXF1RACE":           MarketKind("win", 1),
    "KXF1RACEPODIUM":     MarketKind("podium", 3),
    "KXF1POLE":           MarketKind("pole", 1, lock_session="Qualifying"),
    "KXF1FASTLAP":        MarketKind("fastest_lap", 1),
    "KXF1RACESPRINT":     MarketKind("sprint_win", 1, lock_session="Sprint"),
    "KXF1H2H":            MarketKind("h2h", 1),
    "KXF1TOPCONSTRUCTOR": MarketKind("top_constructor", 1, entity="team"),
    "KXF1":               MarketKind("wdc", 1, scope="season", lock_session=None),
    "KXF1CONSTRUCTORS":   MarketKind("wcc", 1, scope="season", entity="team",
                                     lock_session=None),
}

# The series that matter for scoring race_forecast.py. Kept separate from the
# catalogue above so a cheap run can skip the season-long and novelty markets.
CORE_SERIES = ["KXF1RACE", "KXF1RACEPODIUM", "KXF1POLE"]

# Series that exist in Kalshi's catalogue but have NEVER been populated for F1
# (all returned 0 events on 2026-08-08). Listed so a future reader does not
# repeat the search, and so a collector can cheaply notice if they wake up.
KNOWN_EMPTY = ["KXF1RACETOP5", "KXF1RACETOP10", "KXF1RACETOPX", "KXF1QUALIFY"]

COLUMNS = [
    "snapshot_ts", "season", "round", "event", "market", "scope", "bookmaker",
    "entity", "driver", "driver_name", "series_ticker", "event_ticker",
    "market_ticker", "yes_bid", "yes_ask", "last_price", "spread",
    "price_source", "p_raw", "n_runners", "arity", "overround",
    "p_devig_basic", "p_devig_power", "p_devig_shin",
    "volume", "open_interest", "status", "result",
    "locks_at", "hours_to_lock", "pre_lock", "close_time", "fetched_from",
]


# ─────────────────────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────────────────────

class KalshiClient:
    """Throttled, retrying, read-only client for Kalshi's public endpoints.

    Read-only by construction: there is no auth and no order-placing method
    here, so this cannot trade even by accident.
    """

    def __init__(self, min_interval: float = MIN_INTERVAL) -> None:
        self.min_interval = min_interval
        self._last = 0.0

    def _get(self, path: str, **params) -> dict:
        url = f"{API}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None})
        for attempt in range(MAX_RETRIES):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            req = urllib.request.Request(
                url, headers={"Accept": "application/json",
                              "User-Agent": "f1-dashboard-odds/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=30) as f:
                    return json.load(f)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return {}
                if exc.code in (429, 500, 502, 503, 504):
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError):
                time.sleep(1.5 * (attempt + 1))
        logger.warning("giving up on %s after %d attempts", url, MAX_RETRIES)
        return {}

    def events(self, series: str, status: str | None = None,
               limit: int = 200) -> list[dict]:
        return self._get("/events", series_ticker=series, status=status,
                         limit=limit).get("events") or []

    def markets(self, event_ticker: str, limit: int = 200) -> list[dict]:
        return self._get("/markets", event_ticker=event_ticker,
                         limit=limit).get("markets") or []

    def candlesticks(self, series: str, market_ticker: str,
                     start_ts: int, end_ts: int,
                     period_interval: int = 60) -> list[dict]:
        """Historical OHLC for one contract.

        This is the endpoint that makes a limited backfill possible at all —
        it is public and free, contradicting the usual "historical odds are
        paid everywhere". The catch is upstream: Kalshi prunes the /markets
        listing after roughly seven race weekends, and once a market is pruned
        its candlesticks 404 too. So this can only ever reach back as far as
        the markets still resident today.
        """
        return self._get(
            f"/series/{series}/markets/{market_ticker}/candlesticks",
            start_ts=start_ts, end_ts=end_ts,
            period_interval=period_interval).get("candlesticks") or []


# ─────────────────────────────────────────────────────────────
# De-vigging
# ─────────────────────────────────────────────────────────────
#
# Raw prices do not sum to the number of winners. On a bookmaker that surplus
# is the margin; on an exchange it is the bid-ask spread plus whatever the book
# is carrying. Either way the tail is distorted by favourite-longshot bias, and
# the tail is where the interesting disagreements with a pace model live.
#
# All three methods are stored alongside the raw price so the choice can be
# revisited later without re-fetching anything — which matters because the
# fetch cannot be repeated after the fact.

def devig_basic(prices: np.ndarray, arity: int = 1) -> np.ndarray:
    """Proportional normalisation. Included as the naive reference, not
    because it is right: it rescales every runner by the same factor, which
    systematically overstates longshots."""
    p = np.asarray(prices, dtype=float)
    tot = np.nansum(p)
    if not np.isfinite(tot) or tot <= 0:
        return np.full_like(p, np.nan)
    return p * arity / tot


def devig_power(prices: np.ndarray, arity: int = 1) -> np.ndarray:
    """Power method: p_i = pi_i ** alpha, alpha solved so the sum is `arity`.

    Shrinks longshots harder than favourites, which is the shape of the bias,
    and unlike Shin it generalises cleanly to a multi-winner market — so this
    is the one method defined for every market we collect, podium included.
    """
    p = np.asarray(prices, dtype=float)
    ok = np.isfinite(p) & (p > 0) & (p < 1)
    if ok.sum() < 2:
        return np.full_like(p, np.nan)
    q = p[ok]

    def gap(alpha: float) -> float:
        return float(np.sum(q ** alpha) - arity)

    try:
        # sum is decreasing in alpha (all q < 1), so bracket outwards.
        lo, hi = 1e-3, 1.0
        while gap(hi) > 0 and hi < 64:
            hi *= 2
        if gap(lo) < 0 or gap(hi) > 0:
            return devig_basic(p, arity)
        alpha = brentq(gap, lo, hi, maxiter=200)
    except (ValueError, RuntimeError):
        return devig_basic(p, arity)

    out = np.full_like(p, np.nan)
    out[ok] = q ** alpha
    return out


def devig_shin(prices: np.ndarray, arity: int = 1) -> np.ndarray:
    """Shin (1993): prices are distorted by a share `z` of insider money.

    Defined only for a single-winner market — the model is about a book on a
    partition of outcomes, and stretching it to a three-slot podium would be
    inventing maths rather than applying it. Multi-winner markets get NaN here
    on purpose; use the power method for those.
    """
    p = np.asarray(prices, dtype=float)
    if arity != 1:
        return np.full_like(p, np.nan)
    ok = np.isfinite(p) & (p > 0) & (p < 1)
    if ok.sum() < 2:
        return np.full_like(p, np.nan)
    q = p[ok]
    book = float(q.sum())
    if book <= 1.0:                     # no overround to strip (or underround)
        return devig_basic(p, arity)

    def implied(z: float) -> np.ndarray:
        root = np.sqrt(z * z + 4.0 * (1.0 - z) * q * q / book)
        return (root - z) / (2.0 * (1.0 - z))

    def gap(z: float) -> float:
        return float(implied(z).sum() - 1.0)

    try:
        lo, hi = 1e-9, 1.0 - 1e-9
        if gap(lo) < 0 or gap(hi) > 0:
            return devig_power(p, arity)
        z = brentq(gap, lo, hi, maxiter=200)
    except (ValueError, RuntimeError):
        return devig_power(p, arity)

    out = np.full_like(p, np.nan)
    out[ok] = implied(z)
    return out


# ─────────────────────────────────────────────────────────────
# Price selection
# ─────────────────────────────────────────────────────────────

def _f(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return np.nan
    return x if np.isfinite(x) else np.nan


def pick_price(yes_bid: float, yes_ask: float,
               last: float) -> tuple[float, str]:
    """The one number we treat as the market's probability, and where it came
    from. Recorded rather than inferred later, because the raw bid/ask of a
    settled market (0.00 / 1.00) has a plausible-looking midpoint of 0.50 that
    would quietly poison a calibration study."""
    bid, ask, last = _f(yes_bid), _f(yes_ask), _f(last)
    spread = ask - bid if np.isfinite(ask) and np.isfinite(bid) else np.nan

    if np.isfinite(spread) and 0 <= spread <= MAX_SPREAD and (bid > 0 or ask < 1):
        return (bid + ask) / 2.0, "mid"
    if np.isfinite(last) and 0 < last < 1:
        return last, "last"
    if np.isfinite(spread) and (bid > 0 or ask < 1):
        return (bid + ask) / 2.0, "wide_mid"
    return np.nan, "none"


# ─────────────────────────────────────────────────────────────
# Kalshi event -> repo event
# ─────────────────────────────────────────────────────────────
#
# Kalshi's own identifiers are not stable enough to key on. The ticker suffix
# changed format between seasons (2025 "SGP25"/"MCGP25" vs 2026
# "BARGP26"/"MONGP26") and sub_title drifts too ("Hungarian Grand Prix 2026",
# "2025 F1 Australian Grand Prix", plain "Monaco Grand Prix"). The market's
# CLOSE TIME is exact and format-free — a race-winner market closes at lights
# out — so the calendar date is the join key, with the name only breaking ties.

# Everything that is market-description rather than race-identity. This has to
# strip HARD, because the name is sometimes the only usable signal: when a race
# is relocated or rescheduled (the 2026 Bahrain Grand Prix is run in Malaysia,
# months off its original slot) the date in a market's slug is the date it was
# CREATED against and no longer points at the race. Leaving "driver"/"finish"
# in diluted "Bahrain Grand Prix: Driver Podium Finish" down to a 0.42 match
# against "Bahrain Grand Prix" — under the threshold, so it resolved to nothing.
_STOP = re.compile(r"\b(f1|formula\s*1|grand\s*prix|gp|20\d\d|winner|main|race|"
                   r"qualifying|session|q3|pole|position|podium|finishers?|"
                   r"finish|driver|constructor|matchup|vs|sprint|fastest|lap)\b")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = _STOP.sub(" ", s)
    return re.sub(r"[^a-z ]+", " ", s).strip()


def load_calendar(path: Path = CALENDAR) -> pd.DataFrame:
    try:
        cal = pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=["season", "round", "event", "event_date"])
    cal["event_date"] = pd.to_datetime(cal["event_date"], errors="coerce")
    return cal.dropna(subset=["event_date"])


def parse_ts(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def resolve_event(close_dt: datetime | None, sub_title: str, title: str,
                  calendar: pd.DataFrame,
                  window_days: int = 4) -> tuple[int | None, int | None, str | None]:
    """(season, round, event) for a Kalshi event, or (season, None, None).

    Matched on race date: a pole market closes on the Saturday and a race
    market on the Sunday, so a +/-4 day window catches both without ever
    reaching the next event (the calendar's tightest gap is 7 days).
    """
    if close_dt is None or calendar.empty:
        return (None, None, None)
    season = close_dt.year
    cand = calendar[calendar["season"].astype(int) == season].copy()
    if cand.empty:
        return (season, None, None)

    close_date = pd.Timestamp(close_dt.date())
    cand["dist"] = (cand["event_date"] - close_date).abs().dt.days
    cand = cand[cand["dist"] <= window_days]
    if cand.empty:
        return (season, None, None)

    want = _norm(sub_title) or _norm(title)
    cand["sim"] = [_similar(want, _norm(e)) for e in cand["event"]]
    # Date first, name only to break a tie — the date is the reliable signal.
    cand = cand.sort_values(["dist", "sim"], ascending=[True, False])
    top = cand.iloc[0]
    return (season, int(top["round"]), str(top["event"]))


def _similar(a: str, b: str) -> float:
    """Token overlap, falling back to character similarity.

    The fallback is not decoration: Polymarket ships real typos in its slugs
    ("azerbijan-grand-prix-winner"), which share no token with "Azerbaijan"
    and would score a flat zero on set overlap alone.
    """
    if not a or not b:
        return 0.0
    ta, tb = set(a.split()), set(b.split())
    jaccard = len(ta & tb) / max(1, len(ta | tb))
    return max(jaccard, difflib.SequenceMatcher(None, a, b).ratio())


# ─────────────────────────────────────────────────────────────
# When the outcome stops being unknown
# ─────────────────────────────────────────────────────────────
#
# THE TRAP THIS EXISTS TO CLOSE. Kalshi's `close_time` is the SETTLEMENT time,
# not lights out. Hungary 2026 closed at 18:00:52 UTC; the race started at
# 13:00. So "the last price 2 hours before close" is a price taken with 40
# laps already run, and scoring against it gives a Brier of 0.0000 and 100%
# skill — a number that looks like a triumph and is pure leakage.
#
# A calibration benchmark is worthless unless every price used predates the
# event it predicts, so the honest anchor is the SESSION START, taken from
# FastF1's schedule (which the repo already depends on and caches).

_SCHEDULE_CACHE: dict[int, dict[tuple[str, str], datetime]] = {}


def _session_starts(season: int) -> dict[tuple[str, str], datetime]:
    """{(event, session): UTC start} for one season, or {} if unavailable.

    Degrades to empty rather than raising: a missing schedule must cost us the
    `locks_at` stamp, never the snapshot itself — the price is the perishable
    part and can't be re-fetched, while this can be backfilled any time.
    """
    if season in _SCHEDULE_CACHE:
        return _SCHEDULE_CACHE[season]
    out: dict[tuple[str, str], datetime] = {}
    try:
        import fastf1
        sched = fastf1.get_event_schedule(int(season), include_testing=False)
        for _, row in sched.iterrows():
            event = str(row.get("EventName") or "")
            for i in range(1, 6):
                name = row.get(f"Session{i}")
                when = row.get(f"Session{i}DateUtc")
                if not name or pd.isna(when):
                    continue
                out[(event, str(name))] = pd.Timestamp(when).to_pydatetime().replace(
                    tzinfo=timezone.utc)
    except Exception as exc:
        logger.info("no session schedule for %s (%s) - locks_at left blank",
                    season, type(exc).__name__)
    _SCHEDULE_CACHE[season] = out
    return out


def lock_time(season: int | None, event: str | None,
              kind: MarketKind) -> datetime | None:
    """UTC start of the session that decides this market, or None."""
    if season is None or not event or kind.lock_session is None:
        return None
    starts = _session_starts(int(season))
    hit = starts.get((event, kind.lock_session))
    if hit is None and kind.lock_session == "Sprint":
        hit = starts.get((event, "Sprint Race"))
    return hit


# ─────────────────────────────────────────────────────────────
# Row building
# ─────────────────────────────────────────────────────────────

def driver_code(market_ticker: str, event_ticker: str) -> str:
    """Kalshi contract tickers are "<event>-<CODE>", and the code is the FIA
    three-letter abbreviation the rest of the repo already keys on."""
    suffix = str(market_ticker)
    if suffix.startswith(str(event_ticker) + "-"):
        suffix = suffix[len(str(event_ticker)) + 1:]
    return suffix.split("-")[0].upper()


def build_rows(markets: list[dict], kind: MarketKind, series: str,
               event_ticker: str, season: int | None, rnd: int | None,
               event: str | None, snapshot_ts: str,
               fetched_from: str = "live", bookmaker: str = BOOKMAKER,
               code_of=None) -> list[dict]:
    """One snapshot of one market: raw prices plus all three de-vigged sets.

    Source-agnostic on purpose. Kalshi and Polymarket describe a contract
    completely differently, but both are reshaped into the same market dict
    before they get here, so the pricing rule, the de-vigging and the lock
    stamp are provably identical across sources — which is the whole point of
    keeping them in one file and comparing them.

    `code_of` extracts the driver code; it differs per source (Kalshi encodes
    it in the ticker, Polymarket gives a full name that needs the archive).
    """
    if code_of is None:
        def code_of(m):
            return driver_code(m.get("ticker", ""), event_ticker)
    raw, meta = [], []
    for m in markets:
        price, src = pick_price(m.get("yes_bid_dollars"),
                                m.get("yes_ask_dollars"),
                                m.get("last_price_dollars"))
        raw.append(price)
        meta.append((m, src))

    arr = np.asarray(raw, dtype=float)
    n_runners = int(np.isfinite(arr).sum())
    total = float(np.nansum(arr)) if n_runners else np.nan
    overround = total / kind.arity if n_runners and kind.arity else np.nan

    basic = devig_basic(arr, kind.arity)
    power = devig_power(arr, kind.arity)
    shin = devig_shin(arr, kind.arity)

    locks = lock_time(season, event, kind)
    taken = parse_ts(snapshot_ts)
    if locks is not None and taken is not None:
        hours_to_lock = (locks - taken).total_seconds() / 3600.0
        pre_lock = hours_to_lock > 0
    else:
        hours_to_lock, pre_lock = np.nan, None

    rows = []
    for i, (m, src) in enumerate(meta):
        bid, ask = _f(m.get("yes_bid_dollars")), _f(m.get("yes_ask_dollars"))
        rows.append({
            "snapshot_ts": snapshot_ts,
            "season": season, "round": rnd, "event": event,
            "market": kind.market, "scope": kind.scope, "bookmaker": bookmaker,
            "entity": kind.entity,
            "driver": code_of(m),
            "driver_name": m.get("yes_sub_title"),
            "series_ticker": series, "event_ticker": event_ticker,
            "market_ticker": m.get("ticker"),
            "yes_bid": bid, "yes_ask": ask,
            "last_price": _f(m.get("last_price_dollars")),
            "spread": ask - bid if np.isfinite(ask) and np.isfinite(bid) else np.nan,
            "price_source": src,
            "p_raw": arr[i],
            "n_runners": n_runners, "arity": kind.arity, "overround": overround,
            "p_devig_basic": basic[i], "p_devig_power": power[i],
            "p_devig_shin": shin[i],
            "volume": _f(m.get("volume_fp")),
            "open_interest": _f(m.get("open_interest_fp")),
            "status": m.get("status"), "result": m.get("result"),
            "locks_at": locks.strftime("%Y-%m-%dT%H:%M:%SZ") if locks else None,
            "hours_to_lock": hours_to_lock, "pre_lock": pre_lock,
            "close_time": m.get("close_time"),
            "fetched_from": fetched_from,
        })
    return rows


def candles_to_markets(candles: list[dict], market: dict) -> list[tuple[str, dict]]:
    """Replay one contract's candlesticks as a series of market-shaped dicts,
    so a backfilled snapshot goes through exactly the same pricing and
    de-vigging path as a live one."""
    out = []
    for c in candles:
        end = c.get("end_period_ts")
        if end is None:
            continue
        px = c.get("price") or {}
        bid = (c.get("yes_bid") or {}).get("close_dollars")
        ask = (c.get("yes_ask") or {}).get("close_dollars")
        if px.get("close_dollars") is None and bid is None and ask is None:
            continue
        ts = datetime.fromtimestamp(int(end), tz=timezone.utc)
        out.append((ts.strftime("%Y-%m-%dT%H:%M:%SZ"), {
            **market,
            "yes_bid_dollars": bid,
            "yes_ask_dollars": ask,
            "last_price_dollars": px.get("close_dollars"),
            "volume_fp": c.get("volume_fp"),
            "open_interest_fp": c.get("open_interest_fp"),
        }))
    return out


# ─────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────

KEY = ["snapshot_ts", "bookmaker", "market_ticker"]


def append_snapshots(rows: list[dict], path: Path) -> tuple[int, int]:
    """Append-only merge. Returns (added, total).

    De-duplicates on (snapshot_ts, bookmaker, market_ticker) so re-running a
    backfill is idempotent, while a live snapshot — which carries a fresh
    timestamp — always lands as new rows.
    """
    new = pd.DataFrame(rows, columns=COLUMNS) if rows else pd.DataFrame(columns=COLUMNS)
    if path.exists():
        # low_memory=False: the file is append-only and now large enough that
        # chunked inference guesses different dtypes per chunk for the
        # nullable columns (pre_lock, result) and warns on every run.
        old = pd.read_csv(path, low_memory=False)
        for c in COLUMNS:
            if c not in old.columns:
                old[c] = np.nan
        combined = pd.concat([old[COLUMNS], new], ignore_index=True)
    else:
        old = pd.DataFrame(columns=COLUMNS)
        combined = new
    combined = combined.drop_duplicates(subset=KEY, keep="first")
    combined = combined.sort_values(["snapshot_ts", "market", "market_ticker"])
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    return len(combined) - len(old), len(combined)
