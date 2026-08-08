"""Polymarket as a HISTORICAL source, to reach the races Kalshi has destroyed.

WHAT THIS BUYS THAT KALSHI CANNOT
---------------------------------
Kalshi prunes a race's markets after roughly seven weekends and the price
history 404s with them, which caps `fetch_odds.py --backfill` at the last ~7
races. Polymarket keeps resolved markets indexed indefinitely. Measured
2026-08-08 over 333 F1-tagged events:

    season   winner  podium  pole  sprint
    2024          9       0     0       0
    2025         24       3    22       7
    2026         13      11    26       8

So this recovers the 2026 rounds Kalshi has already dropped, all of 2025, and
part of 2024 — none of which is obtainable any other way.

TWO THINGS IT IS WORSE AT, BOTH LOAD-BEARING
--------------------------------------------
1. RESOLUTION DECAYS WITH AGE. Polymarket downsamples as a market ages. The
   2026 Belgian podium still serves 268 hourly points; the 2025 Brazilian and
   Abu Dhabi podiums serve ONLY 12-hour candles (`fidelity=60` returns an empty
   array). So this source is also perishable — just slowly, in resolution,
   rather than all at once. Fetch sooner rather than later.
2. IT NEEDS A VPN FROM FRANCE. gamma-api.polymarket.com is DNS-hijacked to an
   `*.anj.fr` block page by the French regulator. That is why this is a manual
   backfill and not a scheduled feed, and why `PolymarketBlocked` exists: the
   failure has to be legible ("your VPN is off") rather than a raw SSL error.

Because it is manual, it is built to be FORGETTABLE: every run is idempotent
and resumable, so running it whenever the VPN happens to be up simply catches
up whatever is missing. `missing_events()` reports the gap, and after_race.py
prints that gap as a reminder without ever failing on it.

THE ONE FILTER THIS SOURCE REQUIRES: `overround`
------------------------------------------------
A 12-hour candle with no trades in it comes back as a flat 0.50 rather than as
a gap. A handful of those in one snapshot inflates the book badly, and the
de-vigged numbers that result look perfectly reasonable. Measured on the 2025
Abu Dhabi podium, consecutive snapshots ran:

    2025-12-07T00:00Z   21 runners   raw sum 3.128   overround 1.043   GOOD
    2025-12-07T12:00Z   21 runners   raw sum 6.014   overround 2.005   3 stuck at 0.50

The good one is a genuinely excellent book — its top three prices were exactly
the podium. The bad one prices half the field at a coin flip. Both de-vig
without complaint, because normalisation cannot tell a wrong book from a wide
one, so `p_devig_power` is quietly wrong on the second.

`overround` separates them cleanly and is stored on every row. ALWAYS filter
on it for this source (roughly 0.9 to 1.25); `pre_lock` alone is not enough.
Kalshi's two-sided book cannot fail this way — `pick_price` sees bid=0/ask=1
and returns NaN — which is why the filter matters here and not there.

Prices go through `f1lib.odds.build_rows`, so the pricing rule, the de-vigging
and the lock stamp are identical to Kalshi's — which is what makes the two
sources comparable on the 2026 races where they overlap.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import ssl
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from f1lib.odds import (MarketKind, _norm, _similar, build_rows, load_calendar,
                        parse_ts)

logger = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
BOOKMAKER = "polymarket"

MIN_INTERVAL = 0.30
MAX_RETRIES = 4
PAGE = 100          # Gamma caps a page at 100 whatever `limit` says

ARCHIVE = Path("data/historical_results/race_results_all.parquet")

# Slug shapes seen in the wild. Order matters - "sprint winner" must be tested
# before plain "winner", and podium before everything.
_KINDS: list[tuple[re.Pattern, MarketKind]] = [
    (re.compile(r"podium"),                 MarketKind("podium", 3)),
    (re.compile(r"sprint.*winner|sprint$"), MarketKind("sprint_win", 1,
                                                       lock_session="Sprint")),
    (re.compile(r"pole"),                   MarketKind("pole", 1,
                                                       lock_session="Qualifying")),
    (re.compile(r"winner"),                 MarketKind("win", 1)),
]

# Motorsport that is not F1 but lands in the same tag or search.
_NOT_F1 = re.compile(r"detroit|indycar|indy-|nascar|chevrolet|motogp|moto-gp|"
                     r"le-mans|formula-e|formula-2|formula-3|f2-|f3-")

# Championship / novelty markets: real, but not a per-race outcome we score.
# "constructor" is SINGULAR on purpose - it also catches the plural, and the
# per-race "constructor-pole-position" markets price TEAMS, not drivers. Those
# slipped through a plural-only pattern and wrote ~11k rows whose driver code
# was blank because "Ferrari" is not a driver.
_NOT_RACE = re.compile(r"champion|constructor|title|season|driver-to-|"
                       r"team-|next-|sign|contract|retire|first-|any-")


class PolymarketBlocked(RuntimeError):
    """Raised when the ANJ block is in the way — i.e. the VPN is off.

    A distinct type rather than a generic error so callers can tell "you
    forgot the VPN" (retry later, nothing is wrong) apart from "the API
    changed" (someone needs to look at it).
    """


# ─────────────────────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────────────────────

class PolymarketClient:
    """Throttled, read-only Gamma + CLOB client. Places no orders, holds no
    key, and touches no wallet — there is no signing code here at all."""

    def __init__(self, min_interval: float = MIN_INTERVAL) -> None:
        self.min_interval = min_interval
        self._last = 0.0

    def _get(self, url: str):
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
                    return None
                if exc.code in (429, 500, 502, 503, 504):
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
            except urllib.error.URLError as exc:
                # The block presents as a TLS name mismatch: DNS points at the
                # regulator's server, whose cert is for *.anj.fr.
                if isinstance(getattr(exc, "reason", None),
                              ssl.SSLCertVerificationError):
                    raise PolymarketBlocked(
                        "Polymarket is DNS-blocked on this network (the cert "
                        "served is the ANJ block page, not Polymarket's).\n"
                        "   -> turn the VPN on (non-French exit) and re-run; "
                        "nothing is lost, the backfill resumes where it "
                        "stopped.") from None
                time.sleep(1.0 * (attempt + 1))
            except ssl.SSLCertVerificationError:
                raise PolymarketBlocked(
                    "Polymarket is DNS-blocked on this network — turn the VPN "
                    "on (non-French exit) and re-run.") from None
        return None

    def check_reachable(self) -> None:
        """Fail fast and legibly, before any long loop, if the VPN is off."""
        self._get(f"{GAMMA}/events?limit=1")

    def f1_events(self, max_pages: int = 60) -> list[dict]:
        """Every F1-tagged event. Paginated by hand because Gamma silently
        caps a page at 100 however large `limit` is — reading the first page
        and trusting `limit=500` undercounts 333 events as 100."""
        out, off = [], 0
        for _ in range(max_pages):
            batch = self._get(f"{GAMMA}/events?limit={PAGE}&offset={off}&tag_slug=f1")
            if not batch:
                break
            out += batch
            off += len(batch)
            if len(batch) < PAGE:
                break
        return out

    def prices_history(self, token_id: str, fidelity: int) -> list[dict]:
        r = self._get(f"{CLOB}/prices-history?market={token_id}"
                      f"&interval=max&fidelity={fidelity}")
        return (r or {}).get("history") or []


# ─────────────────────────────────────────────────────────────
# Identity
# ─────────────────────────────────────────────────────────────

_NAME_TO_CODE: dict[str, str] | None = None


def name_to_code() -> dict[str, str]:
    """{'Pierre Gasly': 'GAS', 'gasly': 'GAS', ...} from the results archive.

    Polymarket labels a contract with a driver's full name; the rest of the
    repo keys on the FIA three-letter code. The archive already carries both
    for every season, so no hand-written table is needed (and none can drift).
    """
    global _NAME_TO_CODE
    if _NAME_TO_CODE is not None:
        return _NAME_TO_CODE
    m: dict[str, str] = {}
    try:
        d = pd.read_parquet(ARCHIVE, columns=["FullName", "LastName",
                                              "Abbreviation"])
        for full, last, ab in d.drop_duplicates().itertuples(index=False):
            if not isinstance(ab, str):
                continue
            for key in (full, last):
                if isinstance(key, str) and key.strip():
                    m.setdefault(_norm_name(key), ab.upper())
    except Exception as exc:
        logger.warning("driver name map unavailable (%s): %s",
                       ARCHIVE, type(exc).__name__)
    _NAME_TO_CODE = m
    return m


_SUFFIX = {"jr", "jnr", "sr", "snr", "ii", "iii"}

# Not drivers, but genuine contracts in the book: "Other" is the field bucket,
# and Polymarket lists "Driver A".."Driver E" as placeholders on a race whose
# entry list is not final. Their prices are part of what the market sums to,
# so they MUST stay in the row set or the de-vigging normalises against an
# incomplete book — they just must never be joined to a car.
_FIELD = re.compile(r"^(other|another|field|driver\s*[a-z])$", re.I)
FIELD_CODE = "FIELD"


def _norm_name(s: str) -> str:
    """Accent-folded, letters only.

    The fold is load-bearing: Polymarket writes "Nico Hülkenberg" and the
    archive has "Nico Hulkenberg". Stripping non-ASCII without folding turns
    the umlaut into nothing ("hlkenberg") and loses that driver's entire price
    series across every race, silently.
    """
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", s.lower())


def code_for(name: str) -> str:
    """Three-letter code for a Polymarket contract label.

    Returns FIELD_CODE for the field/placeholder buckets and '' for a genuine
    driver we could not map. Empty rather than a guess: an unmapped driver
    must be visibly unjoinable downstream, never silently attached to the
    wrong car.
    """
    raw = str(name or "").strip()
    if not raw or _FIELD.match(raw):
        return FIELD_CODE
    m = name_to_code()
    n = _norm_name(raw)
    if n in m:
        return m[n]
    # Drop honorifics before taking the surname: Polymarket writes "Carlos
    # Sainz Jr.", where the last token is the suffix, not the family name.
    parts = [p for p in re.split(r"\s+", raw)
             if _norm_name(p) and _norm_name(p) not in _SUFFIX]
    for tok in reversed(parts):
        if _norm_name(tok) in m:
            return m[_norm_name(tok)]
    if len(parts) >= 2:                      # "Carlos Sainz Jr." -> "carlossainz"
        joined = _norm_name("".join(parts))
        if joined in m:
            return m[joined]
    # Last resort: Polymarket ships misspelled drivers ("Nico Hulkenburg",
    # "George Russel"). A high cutoff keeps this from inventing a match -
    # teammates' surnames are nowhere near this similar to each other.
    close = difflib.get_close_matches(n, list(m), n=1, cutoff=0.88)
    if close:
        return m[close[0]]
    return ""


# ─────────────────────────────────────────────────────────────
# Event classification and mapping
# ─────────────────────────────────────────────────────────────

_SLUG_DATE = re.compile(r"(20\d\d)-(\d\d)-(\d\d)")


def classify(event: dict) -> MarketKind | None:
    """Which of our markets this Polymarket event is, or None to skip it."""
    slug = str(event.get("slug") or "").lower()
    title = str(event.get("title") or "").lower()
    if not slug or _NOT_F1.search(slug):
        return None
    if _NOT_RACE.search(slug):
        return None
    if "grand prix" not in title and "grand-prix" not in slug and "gp" not in slug:
        return None
    for pat, kind in _KINDS:
        if pat.search(slug):
            return kind
    return None


def event_date(event: dict) -> datetime | None:
    """Best available race date — approximate by nature, so never decisive.

    Priority is deliberate. The slug's date is the most consistent field;
    `gameStartTime` is right but often absent; `endDate` is usually the race
    day but was SEVEN DAYS late on the 2026 Belgian podium, which would have
    mapped it onto the Hungarian Grand Prix.

    But none of them can be trusted outright, because a market's date is the
    date it was created AGAINST. When a race is relocated or rescheduled the
    slug keeps the old slot forever: the 2026 Bahrain Grand Prix moved to
    Malaysia in October, and its April markets are still slugged April. That
    is why `resolve` lets the NAME win on its own and treats the date as a
    tie-breaker rather than a gate.
    """
    m = _SLUG_DATE.search(str(event.get("slug") or ""))
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc)
        except ValueError:
            pass
    for mk in event.get("markets") or []:
        gst = mk.get("gameStartTime")
        if gst:
            t = parse_ts(str(gst).replace(" ", "T").replace("+00", "+00:00"))
            if t:
                return t
    return parse_ts(event.get("endDate"))


def resolve(event: dict, calendar: pd.DataFrame,
            window_days: int = 12) -> tuple[int | None, int | None, str | None]:
    """(season, round, event) for a Polymarket event.

    NAME-first, unlike the Kalshi path. Kalshi's close time is exact so date
    can lead there; here the date is only approximately right and the title is
    clean ("Belgian Grand Prix: Driver Podium Finish"), so name leads and date
    narrows the season and breaks ties between a circuit's repeat visits.
    """
    when = event_date(event)
    if when is None or calendar.empty:
        return (None, None, None)
    season = when.year
    cand = calendar[calendar["season"].astype(int) == season].copy()
    if cand.empty:
        return (season, None, None)

    want = _norm(event.get("title")) or _norm(event.get("slug"))
    day = pd.Timestamp(when.date())
    cand["dist"] = (cand["event_date"] - day).abs().dt.days
    cand["sim"] = [_similar(want, _norm(e)) for e in cand["event"]]

    near = cand[cand["dist"] <= window_days]
    pool = near if not near.empty else cand
    pool = pool.sort_values(["sim", "dist"], ascending=[False, True])
    top = pool.iloc[0]
    # An unambiguous name is enough on its own, however far off the date is —
    # that is what survives a relocated race. Only reject when the name is
    # weak AND the date does not vouch for it.
    if float(top["sim"]) < 0.45 and int(top["dist"]) > 4:
        return (season, None, None)
    return (season, int(top["round"]), str(top["event"]))


# ─────────────────────────────────────────────────────────────
# Prices
# ─────────────────────────────────────────────────────────────

def _token_id(market: dict) -> str | None:
    tk = market.get("clobTokenIds")
    if isinstance(tk, str):
        try:
            tk = json.loads(tk)
        except Exception:
            return None
    return tk[0] if isinstance(tk, list) and tk else None


def _result(market: dict) -> str | None:
    """'yes' / 'no' once settled. outcomePrices is ['1','0'] when YES won."""
    if not market.get("closed"):
        return None
    op = market.get("outcomePrices")
    if isinstance(op, str):
        try:
            op = json.loads(op)
        except Exception:
            return None
    if isinstance(op, list) and op:
        try:
            return "yes" if float(op[0]) >= 0.5 else "no"
        except (TypeError, ValueError):
            return None
    return None


def _served_fidelity(client: PolymarketClient, event: dict,
                     preferred: int) -> int:
    """Pick ONE fidelity for the whole event.

    This must be decided per event, not per contract. Polymarket downsamples
    old markets, so a per-contract fallback silently mixes hourly and
    12-hourly series inside a single race — and then no two drivers share a
    timestamp. De-vigging needs the whole field priced at the SAME instant, so
    a mixed event yields snapshots holding one or two runners and an overround
    near zero: numbers that look computed and mean nothing.

    Probed on the busiest contract, since a thinly traded one can be empty at
    a fidelity the rest of the book serves fine.
    """
    if preferred >= 720:
        return 720
    markets = sorted(event.get("markets") or [],
                     key=lambda m: -float(m.get("volumeNum") or 0))
    for m in markets[:3]:
        tok = _token_id(m)
        if tok and client.prices_history(tok, preferred):
            return preferred
    return 720


def _grid(ts: int, fidelity: int) -> int:
    """Snap a point onto the fidelity grid so the field lines up exactly."""
    step = max(1, fidelity) * 60
    return (ts // step) * step


def fetch_series(client: PolymarketClient, event: dict,
                 fidelity: int) -> tuple[dict[str, list[dict]], int]:
    """{snapshot_ts: [market-shaped dicts]} for one event, plus the fidelity
    actually served. Every contract is fetched at that one fidelity and
    snapped to its grid, so each snapshot holds the whole field."""
    used = _served_fidelity(client, event, fidelity)
    frames: dict[str, list[dict]] = {}
    for m in event.get("markets") or []:
        tok = _token_id(m)
        if not tok:
            continue
        pts = client.prices_history(tok, used)
        name = m.get("groupItemTitle") or m.get("question") or ""
        res = _result(m)
        for p in pts:
            t, price = p.get("t"), p.get("p")
            if t is None or price is None:
                continue
            ts = datetime.fromtimestamp(_grid(int(t), used),
                                        tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            frames.setdefault(ts, []).append({
                "ticker": m.get("slug") or m.get("conditionId") or "",
                "yes_sub_title": name,
                "_code": code_for(name),
                # A single traded price, not a two-sided book: Polymarket's
                # history endpoint serves one number per point. Recorded as
                # `last` so price_source says so rather than implying a mid.
                "yes_bid_dollars": None, "yes_ask_dollars": None,
                "last_price_dollars": price,
                "volume_fp": m.get("volumeNum"), "open_interest_fp": None,
                "status": "closed" if m.get("closed") else "open",
                "result": res,
                "close_time": m.get("endDateIso") or m.get("endDate"),
            })
    return frames, used


def rows_for_event(client: PolymarketClient, event: dict, kind: MarketKind,
                   calendar: pd.DataFrame, fidelity: int = 60) -> list[dict]:
    season, rnd, name = resolve(event, calendar)
    frames, used = fetch_series(client, event, fidelity)
    rows: list[dict] = []
    for ts in sorted(frames):
        rows += build_rows(
            frames[ts], kind, str(event.get("slug") or ""),
            str(event.get("slug") or ""), season, rnd, name, ts,
            fetched_from=f"polymarket_{used}m", bookmaker=BOOKMAKER,
            code_of=lambda m: m.get("_code", ""))
    return rows


# ─────────────────────────────────────────────────────────────
# Gap reporting — the "did I forget the VPN" affordance
# ─────────────────────────────────────────────────────────────

def missing_events(out_csv: Path,
                   seasons: tuple[int, ...] = (2025, 2026)) -> list[str]:
    """Races with Kalshi rows but no Polymarket rows, newest first.

    Deliberately offline — it reads only the CSV, so `after_race.py` can print
    the reminder with the VPN off and without a network call.
    """
    if not out_csv.exists():
        return []
    try:
        d = pd.read_csv(out_csv, usecols=["season", "event", "bookmaker", "market"])
    except Exception:
        return []
    d = d[d["season"].isin(seasons) & d["event"].notna()]
    have = set(d[d.bookmaker == BOOKMAKER]["event"])
    want = set(d[d.bookmaker != BOOKMAKER]["event"])
    return sorted(want - have)
