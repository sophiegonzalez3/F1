"""Snapshot F1 betting-market prices into data/odds_snapshots.csv.

The market is a well-calibrated probability reference that exists BEFORE the
race, which makes it the only way to score `race_forecast.py`'s p_win /
p_podium without waiting for a result. The timestamp matters as much as the
price — odds move all weekend — so this is a repeated snapshot, not a fetch.

Source: Kalshi's public market-data API (no account, no key, no auth). Why not
a bookmaker, and what is NOT covered, is documented in `f1lib/odds.py`.

TIME-CRITICAL
-------------
Kalshi prunes markets from its listing after roughly seven race weekends, and
a pruned market's price history 404s with it. So `--backfill` reaches back
about two months and no further, and that window slides forward every race.
Everything older is gone for good. This is the one feed in the repo that gets
permanently worse the longer it is left.

Usage
-----
    .venv/Scripts/python scripts/fetch_odds.py              # snapshot now (core markets)
    .venv/Scripts/python scripts/fetch_odds.py --all        # every F1 series
    .venv/Scripts/python scripts/fetch_odds.py --backfill   # rebuild history while it lasts
    .venv/Scripts/python scripts/fetch_odds.py --status     # what is live, write nothing
    .venv/Scripts/python scripts/fetch_odds.py --dry-run
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from f1lib.odds import (CORE_SERIES, KNOWN_EMPTY, MARKET_KINDS, KalshiClient,
                        append_snapshots, build_rows, candles_to_markets,
                        load_calendar, parse_ts, resolve_event)

OUT = Path("data/odds_snapshots.csv")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _series_list(all_markets: bool, only: list[str] | None) -> list[str]:
    if only:
        return [s.upper() for s in only]
    return list(MARKET_KINDS) if all_markets else list(CORE_SERIES)


# ─────────────────────────────────────────────────────────────
# live snapshot
# ─────────────────────────────────────────────────────────────

def snapshot(client: KalshiClient, series_list: list[str],
             calendar: pd.DataFrame, snapshot_ts: str) -> list[dict]:
    rows: list[dict] = []
    for series in series_list:
        kind = MARKET_KINDS.get(series)
        if kind is None:
            print(f"  {series:20s} unknown series - skipped")
            continue
        events = client.events(series, status="open")
        if not events:
            print(f"  {series:20s} no open events")
            continue
        for ev in events:
            et = ev.get("event_ticker")
            markets = client.markets(et)
            if not markets:
                continue
            close = parse_ts((markets[0] or {}).get("close_time"))
            season, rnd, event = resolve_event(
                close, ev.get("sub_title"), ev.get("title"), calendar)
            new = build_rows(markets, kind, series, et, season, rnd, event,
                             snapshot_ts, fetched_from="live")
            rows += new
            label = event or ev.get("sub_title") or et
            priced = sum(1 for r in new if pd.notna(r["p_raw"]))
            over = new[0]["overround"] if new else float("nan")
            print(f"  {series:20s} {label:32.32s} {priced:>3}/{len(new)} priced"
                  f"  overround={over:.3f}")
    return rows


# ─────────────────────────────────────────────────────────────
# backfill from candlesticks
# ─────────────────────────────────────────────────────────────

def backfill(client: KalshiClient, series_list: list[str],
             calendar: pd.DataFrame, interval: int,
             max_events: int) -> list[dict]:
    """Reconstruct hourly snapshots for every market Kalshi still serves.

    Runs each reconstructed timestamp through the same build_rows path as a
    live snapshot, so backfilled and live rows are directly comparable —
    including the de-vigging, which needs the whole field at one instant and
    so has to be regrouped by timestamp here.
    """
    rows: list[dict] = []
    for series in series_list:
        kind = MARKET_KINDS.get(series)
        if kind is None:
            continue
        events = client.events(series)
        done = 0
        for ev in events:
            if done >= max_events:
                break
            et = ev.get("event_ticker")
            markets = client.markets(et)
            if not markets:
                continue                      # pruned upstream - unreachable
            done += 1
            close = parse_ts(markets[0].get("close_time"))
            season, rnd, event = resolve_event(
                close, ev.get("sub_title"), ev.get("title"), calendar)

            # ts -> the whole field's market dicts at that instant
            frames: dict[str, list[dict]] = {}
            for m in markets:
                o = parse_ts(m.get("open_time"))
                c = parse_ts(m.get("close_time"))
                if o is None or c is None:
                    continue
                candles = client.candlesticks(
                    series, m.get("ticker", ""), int(o.timestamp()),
                    int(c.timestamp()), period_interval=interval)
                for ts, snap in candles_to_markets(candles, m):
                    frames.setdefault(ts, []).append(snap)

            n_before = len(rows)
            for ts in sorted(frames):
                rows += build_rows(frames[ts], kind, series, et, season, rnd,
                                   event, ts, fetched_from="candlestick")
            label = event or ev.get("sub_title") or et
            print(f"  {series:18s} {label:30.30s} {len(frames):>4} snapshots"
                  f"  {len(rows) - n_before:>6} rows")
    return rows


# ─────────────────────────────────────────────────────────────
# polymarket backfill
# ─────────────────────────────────────────────────────────────

def _already_have(out: Path, bookmaker: str) -> set[str]:
    """Event tickers already collected for a source, so a re-run resumes
    instead of refetching. This is what makes forgetting the VPN cheap: the
    next run with it on simply picks up the gap."""
    if not out.exists():
        return set()
    try:
        d = pd.read_csv(out, usecols=["bookmaker", "event_ticker"])
    except Exception:
        return set()
    return set(d[d.bookmaker == bookmaker]["event_ticker"].astype(str))


def polymarket_backfill(out: Path, calendar: pd.DataFrame, fidelity: int,
                        seasons: tuple[int, ...], force: bool,
                        max_events: int) -> list[dict]:
    from f1lib import polymarket as pm

    client = pm.PolymarketClient()
    client.check_reachable()          # raises PolymarketBlocked if VPN is off

    print("  discovering F1 events...", flush=True)
    events = client.f1_events()
    done = set() if force else _already_have(out, pm.BOOKMAKER)
    todo = []
    for ev in events:
        kind = pm.classify(ev)
        if kind is None:
            continue
        when = pm.event_date(ev)
        if when is None or when.year not in seasons:
            continue
        if str(ev.get("slug")) in done:
            continue
        todo.append((ev, kind, when))
    todo.sort(key=lambda t: t[2], reverse=True)      # newest first
    print(f"  {len(events)} F1 events, {len(todo)} to fetch "
          f"({len(done)} already collected)\n")

    rows: list[dict] = []
    for i, (ev, kind, when) in enumerate(todo[:max_events], 1):
        try:
            new = pm.rows_for_event(client, ev, kind, calendar, fidelity)
        except pm.PolymarketBlocked:
            raise
        except Exception as exc:
            print(f"  [{i}/{min(len(todo), max_events)}] {str(ev.get('slug'))[:44]:46s}"
                  f" FAILED ({type(exc).__name__})")
            continue
        rows += new
        snaps = len({r['snapshot_ts'] for r in new})
        label = new[0]["event"] if new and new[0]["event"] else "UNMAPPED"
        unmapped = sum(1 for r in new if not r["driver"])
        print(f"  [{i}/{min(len(todo), max_events)}] {str(ev.get('slug'))[:44]:46s}"
              f" {kind.market:7s} {label[:24]:26s} {snaps:>4} snaps {len(new):>6} rows"
              + (f"  !! {unmapped} unmapped driver(s)" if unmapped else ""),
              flush=True)   # long job: progress must be visible while it runs
    return rows


# ─────────────────────────────────────────────────────────────
# status
# ─────────────────────────────────────────────────────────────

def status(client: KalshiClient, calendar: pd.DataFrame) -> None:
    print("Series               events  open  newest")
    for series, kind in MARKET_KINDS.items():
        events = client.events(series)
        open_ev = client.events(series, status="open")
        newest = events[0].get("sub_title") or events[0].get("event_ticker") \
            if events else "-"
        print(f"  {series:18s} {len(events):>6} {len(open_ev):>5}  "
              f"{str(newest)[:40]}  [{kind.market}, arity {kind.arity}]")
    print("\nNever populated for F1 (checked 2026-08-08): "
          + ", ".join(KNOWN_EMPTY))
    if OUT.exists():
        d = pd.read_csv(OUT)
        print(f"\n{OUT}: {len(d):,} rows, "
              f"{d['snapshot_ts'].nunique()} distinct snapshots, "
              f"{d['event'].nunique()} events")
        if len(d):
            print(f"  span {d['snapshot_ts'].min()} .. {d['snapshot_ts'].max()}")
    else:
        print(f"\n{OUT}: not created yet")


# ─────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backfill", action="store_true",
                    help="rebuild hourly history from candlesticks "
                         "(only reaches markets Kalshi still serves)")
    ap.add_argument("--all", action="store_true",
                    help="every F1 series, not just win/podium/pole")
    ap.add_argument("--series", action="append",
                    help="one specific series ticker (repeatable)")
    ap.add_argument("--interval", type=int, default=60, choices=[1, 60, 1440],
                    help="backfill candle size in minutes (default 60)")
    ap.add_argument("--max-events", type=int, default=50,
                    help="backfill: cap events per series")
    ap.add_argument("--source", default="kalshi",
                    choices=["kalshi", "polymarket"],
                    help="kalshi (default, no VPN needed) or polymarket "
                         "(historical only, needs a VPN from France)")
    ap.add_argument("--seasons", type=int, nargs="+", default=[2024, 2025, 2026],
                    help="polymarket: seasons to backfill")
    ap.add_argument("--force", action="store_true",
                    help="polymarket: refetch events already collected")
    ap.add_argument("--status", action="store_true",
                    help="report coverage and write nothing")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s  %(message)s")
    # lock_time() reads FastF1's schedule, which announces its cache on import.
    # That banner is about FastF1's cache, not about odds - keep it out of the
    # per-event progress lines.
    try:
        import fastf1
        fastf1.set_log_level("ERROR")
    except Exception:
        pass
    logging.getLogger("fastf1").setLevel(logging.ERROR)

    client = KalshiClient()
    calendar = load_calendar()
    if calendar.empty:
        print("!! data/season_calendar.csv unreadable - rows will have no "
              "event name. Run scripts/fetch_calendar.py first.")

    if args.status:
        status(client, calendar)
        return 0

    series_list = _series_list(args.all, args.series)
    ts = _now()

    if args.source == "polymarket":
        from f1lib.polymarket import PolymarketBlocked
        print("=== polymarket historical backfill ===")
        print("Reaches races Kalshi has already pruned (2024-2026). Resolution "
              "decays with age:\n hourly for recent markets, 12-hourly once "
              "they are old, so sooner is better.\n")
        try:
            rows = polymarket_backfill(args.out, calendar, args.interval,
                                       tuple(args.seasons), args.force,
                                       args.max_events)
        except PolymarketBlocked as exc:
            print(f"\n!! {exc}")
            return 3
    elif args.backfill:
        print(f"=== backfill ({args.interval}-minute candles) ===")
        print("Reaches only the markets Kalshi still serves (~7 race "
              "weekends); older ones are gone.\n")
        rows = backfill(client, series_list, calendar, args.interval,
                        args.max_events)
    else:
        print(f"=== snapshot {ts} ===")
        rows = snapshot(client, series_list, calendar, ts)

    if not rows:
        print("\nNo priced markets found. Between race weekends this is "
              "normal - Kalshi lists a race about a week ahead.")
        return 0

    if args.dry_run:
        d = pd.DataFrame(rows)
        print(f"\n--dry-run: {len(d):,} rows, "
              f"{d['snapshot_ts'].nunique()} snapshots, not written")
        return 0

    added, total = append_snapshots(rows, args.out)
    print(f"\n{args.out}: +{added:,} new rows ({total:,} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
