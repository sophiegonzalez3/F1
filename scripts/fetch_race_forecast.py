"""Archive the RACE-DAY WEATHER FORECAST as it stood before each race.

WHY A FORECAST AND NOT THE WEATHER
----------------------------------
The pace model's residual miscalibration is almost entirely wet races: dry
long-run runs z_sd 1.02 against a target of 1.00, wet runs 4.66. The fix is
blocked not by the size of the effect but by seeing it coming — and
`f1lib/pace_model.py` records two ex-ante predictors already tested and dead:

    per-circuit historical wet frequency   rho +0.030, p=0.70, n=164
    rain in THIS weekend's practice        rho +0.115, p=0.26, n=98
                                           (and FADING as n grew = a null)

Both are weak proxies for the thing that actually predicts rain: a weather
forecast. `f1lib.duel.rain_forecast` already pulls Open-Meteo, but only for
UPCOMING events, so it has never been scored against anything.

LEAK-FREEDOM IS THE WHOLE POINT
-------------------------------
Open-Meteo's *historical-forecast* API stitches together the first hours of
each model run, which makes it an ANALYSIS — near-observed weather. Scoring
against that would be reading the answer, the same mistake as using a race's
own rainfall to widen its own interval.

The *previous-runs* API is the honest one: `precipitation_previous_dayN` is
what the model predicted N days ahead of the valid time. This script stores
D-1, D-2 and D-3 alongside the analysis, so the analysis can act as a
reference while only the lead-time columns are ever used as a predictor.

THE ARCHIVE ONLY REACHES 2024, AND MAY ROLL OFF
-----------------------------------------------
Measured 2026-08-08: `_previous_dayN` returns full 24-hour coverage from 2024
onward and NOTHING for 2019-2023 — and it returns nulls, which sum to a silent
0.0 if you are not counting them. That caps the usable sample at 61 races with
7 wet, so the calibration question this was meant to answer is not yet
answerable and needs roughly three more seasons.

That is exactly why this exists as a stored feed rather than an analysis: the
window can only shrink from the far end, and the same "collect it before you
need it" logic that applies to odds applies here.

Usage
-----
    .venv/Scripts/python scripts/fetch_race_forecast.py
    .venv/Scripts/python scripts/fetch_race_forecast.py --seasons 2026
    .venv/Scripts/python scripts/fetch_race_forecast.py --status
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import requests

API = "https://previous-runs-api.open-meteo.com/v1/forecast"

# MODEL CHOICE IS WHAT MAKES THE HISTORY EXIST. The previous-runs archive is
# per-model, and the default is useless here: ECMWF/GFS/ICON return nothing
# before 2024, which capped the usable sample at 5 wet races. JMA is archived
# from 2018 and returns full 24-hour D-2 AND D-3 coverage for every season we
# have — verified 2026-08-08 at 2018-09-02 through 2024-09-01.
#
# JMA GSM is a Japanese global model, so its skill over Europe is not
# guaranteed to match ECMWF's. That is an empirical question, not an
# assumption: 2024+ has BOTH, so `--model` lets the two be scored against each
# other on the overlap before anything is built on either.
MODEL = "jma_seamless"
OUT = Path("data/race_weather_forecast.csv")
CALENDAR = Path("data/season_calendar.csv")

# Lead times to keep. D-3 is roughly "when the team packs its wet setup"; D-1
# is the last word before parc ferme. `precipitation` (no suffix) is the
# ANALYSIS and is stored only as a reference — never as a predictor.
LEADS = [0, 1, 2, 3]
MIN_INTERVAL = 0.4          # be polite to a free API

# Windows relative to the SCHEDULED race start, in hours. A whole-day sum is
# too blunt: Miami 2026 forecast 26.4 mm and raced in drizzle, Hungary 2025
# forecast 13.8 mm and stayed dry, because rain at 8am counts the same as rain
# at lights out.
#
# `pre3` and `pre1` are not decoration. A track soaked in the hour before the
# start is chaotic even if not a drop falls during the race — the first lap is
# run on a wet surface either way — so track WETNESS and race-hour RAIN are
# different predictors and are kept apart.
#
# CAVEAT, deliberate: this is the SCHEDULED start. Races are delayed for rain
# (Spa and Suzuka repeatedly, and US rounds for lightning holds), so a
# delayed race may then run in the dry. That cuts both ways and is not a bug
# to fix here — a forecast is made against the schedule, which is exactly the
# information a strategist has. `race_start_utc` is stored so any future work
# can compare against actual running.
WINDOWS = {"pre3": (-3, 0), "pre1": (-1, 0), "race": (0, 2),
           "window": (-1, 2), "day": None}

LEAD_KEYS = ["analysis", "d1", "d2", "d3"]

COLUMNS = (["season", "round", "event", "race_date", "race_start_utc",
            "lat", "lon", "model"]
           + [f"precip_mm_{w}_{k}" for k in LEAD_KEYS for w in WINDOWS]
           + [f"n_hours_{k}" for k in LEAD_KEYS]
           + ["fetched_at"])


def _vars() -> list[str]:
    out = []
    for lead in LEADS:
        sfx = "" if lead == 0 else f"_previous_day{lead}"
        out.append(f"precipitation{sfx}")
        if lead:
            out.append(f"precipitation_probability{sfx}")
    return out


def fetch_one(lat: float, lon: float, day: str,
              start_utc: pd.Timestamp | None,
              model: str = MODEL) -> dict:
    """Windowed precipitation for one race, per lead time.

    Fetches the day before and after as well, because a window can straddle
    midnight UTC — a 05:00 UTC start in Melbourne with a 3-hour lead-in sits
    partly in the previous day, and clipping it would quietly report a dry
    build-up.
    """
    d0 = pd.Timestamp(day)
    r = requests.get(API, params={
        "latitude": lat, "longitude": lon,
        "start_date": str((d0 - pd.Timedelta(days=1)).date()),
        "end_date": str((d0 + pd.Timedelta(days=1)).date()),
        "hourly": ",".join(_vars()),
        "models": model,
        "timezone": "UTC"}, timeout=30)      # UTC, to match the race clock
    r.raise_for_status()
    h = r.json().get("hourly", {})
    times = pd.to_datetime(pd.Series(h.get("time") or []))

    out: dict = {}
    for lead in LEADS:
        sfx = "" if lead == 0 else f"_previous_day{lead}"
        key = "analysis" if lead == 0 else f"d{lead}"
        vals = pd.Series(h.get(f"precipitation{sfx}") or [], dtype="float64")
        real = vals.notna()
        # The count is the point: an all-null series sums to 0.0, which is
        # indistinguishable from a genuinely dry day unless the number of
        # real observations travels beside it.
        out[f"n_hours_{key}"] = int(real.sum())
        for wname, span in WINDOWS.items():
            if len(vals) != len(times) or not real.any():
                out[f"precip_mm_{wname}_{key}"] = np.nan
                continue
            if span is None or start_utc is None:
                sel = times.dt.date == d0.date()          # whole race day
            else:
                lo = start_utc + pd.Timedelta(hours=span[0])
                hi = start_utc + pd.Timedelta(hours=span[1])
                sel = (times >= lo) & (times < hi)
            got = vals[sel.values & real.values]
            out[f"precip_mm_{wname}_{key}"] = (float(got.sum())
                                               if len(got) else np.nan)
    return out


def _race_starts(seasons) -> dict[tuple[int, str], pd.Timestamp]:
    """Scheduled race start (UTC) per event, from FastF1's schedule."""
    out: dict[tuple[int, str], pd.Timestamp] = {}
    try:
        import fastf1
        fastf1.set_log_level("ERROR")
    except Exception:
        return out
    for season in sorted({int(s) for s in seasons}):
        try:
            sched = fastf1.get_event_schedule(int(season), include_testing=False)
        except Exception:
            continue
        for _, row in sched.iterrows():
            for i in range(1, 6):
                if str(row.get(f"Session{i}")) == "Race":
                    when = row.get(f"Session{i}DateUtc")
                    if pd.notna(when):
                        out[(int(season), str(row["EventName"]))] = \
                            pd.Timestamp(when)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seasons", type=int, nargs="+")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--model", default=MODEL,
                    help=f"Open-Meteo model (default {MODEL}; it is the only "
                         "one archived back to 2018)")
    ap.add_argument("--force", action="store_true",
                    help="refetch races already stored")
    args = ap.parse_args()

    if args.status:
        if not OUT.exists():
            print(f"{OUT}: not created yet")
            return 0
        d = pd.read_csv(OUT)
        print(f"{OUT}: {len(d)} races, seasons "
              f"{sorted(d['season'].unique())}")
        print(f"  with a real D-2 forecast: "
              f"{int((d['n_hours_d2'] > 0).sum())}")
        return 0

    from f1lib.track_scene import _circuit_conf

    cal = pd.read_csv(CALENDAR)
    cal = cal.dropna(subset=["event_date"])
    if args.seasons:
        cal = cal[cal["season"].isin(args.seasons)]
    # 2019 is the archive floor for JMA (2018 works, but the results archive
    # starts in 2019). `n_hours_*` still guards every row, so a model with
    # shallower history writes NaN rather than a silent zero.
    cal = cal[cal["season"] >= 2019]
    # Include the CURRENT weekend, not just finished races. Run mid-weekend the
    # D-2 forecast for Sunday already exists (it was issued on the Friday) but
    # D-1 does not yet, so the row lands incomplete and is completed by the
    # post-race run — see the refetch rule below.
    cutoff = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
    cal = cal[pd.to_datetime(cal["event_date"]) < cutoff]

    have: set[tuple] = set()
    if OUT.exists() and not args.force:
        old = pd.read_csv(OUT)
        # A row is only "done" once every lead time is populated. Without this
        # a mid-weekend fetch would permanently pin a partial row, and the
        # missing leads would look like a dry forecast rather than an absent
        # one.
        lead_cols = [c for c in old.columns if c.startswith("n_hours_")]
        complete = old[lead_cols].fillna(0).gt(0).all(axis=1) if lead_cols \
            else pd.Series(True, index=old.index)
        have = set(zip(old.loc[complete, "season"], old.loc[complete, "event"]))
        partial = int((~complete).sum())
        if partial:
            print(f"  {partial} incomplete row(s) will be refetched")

    rows, skipped = [], 0
    todo = [r for _, r in cal.iterrows()
            if (r["season"], r["event"]) not in have]
    starts = _race_starts(cal["season"].unique())
    print(f"race start times resolved for {len(starts)} events")
    print(f"{len(cal)} races in range, {len(todo)} to fetch "
          f"({len(have)} already stored)\n")
    no_coords: list[str] = []
    for i, r in enumerate(todo, 1):
        conf = _circuit_conf(str(r["event"]))
        if not conf or not conf.get("latlon"):
            skipped += 1
            no_coords.append(f"{int(r['season'])} {r['event']}")
            continue
        lat, lon = conf["latlon"]
        day = str(pd.to_datetime(r["event_date"]).date())
        start = starts.get((int(r["season"]), str(r["event"])))
        try:
            got = fetch_one(lat, lon, day, start, args.model)
        except Exception as exc:
            print(f"  [{i}/{len(todo)}] {int(r['season'])} "
                  f"{str(r['event'])[:26]:28s} FAILED ({type(exc).__name__})")
            continue
        rows.append({"season": int(r["season"]),
                     "round": r.get("round"), "event": str(r["event"]),
                     "race_date": day,
                     "race_start_utc": (start.strftime("%Y-%m-%dT%H:%M:%SZ")
                                        if start is not None else ""),
                     "lat": lat, "lon": lon, "model": args.model,
                     "fetched_at": pd.Timestamp.utcnow().strftime(
                         "%Y-%m-%dT%H:%M:%SZ"), **got})
        print(f"  [{i}/{len(todo)}] {int(r['season'])} "
              f"{str(r['event'])[:24]:26s} D-2 pre1={got['precip_mm_pre1_d2']:5.1f} "
              f"race={got['precip_mm_race_d2']:5.1f} day={got['precip_mm_day_d2']:6.1f}mm"
              f"  (n={got['n_hours_d2']})", flush=True)
        time.sleep(MIN_INTERVAL)

    if no_coords:
        # Named, not silently counted: these are one-off circuits missing from
        # track_scene's table (Mugello, Portimao, Sochi, Istanbul, Paul Ricard,
        # the Nurburgring...). Each costs a race, and two of them were WET —
        # the sample that actually matters here.
        print(f"\n  {len(no_coords)} race(s) have no circuit coordinates and are "
              f"skipped every run:")
        for n in no_coords[:20]:
            print(f"    {n}")
        print("    -> add them to f1lib/track_scene's circuit table to include them")

    if not rows:
        print("\nNothing new to fetch.")
        return 0
    new = pd.DataFrame(rows)
    if OUT.exists() and not args.force:
        new = pd.concat([pd.read_csv(OUT), new], ignore_index=True)
    new = new.drop_duplicates(["season", "event"], keep="last")
    for c in COLUMNS:
        if c not in new.columns:
            new[c] = np.nan
    OUT.parent.mkdir(parents=True, exist_ok=True)
    new[COLUMNS].to_csv(OUT, index=False)
    print(f"\nWrote {OUT} ({len(new)} races"
          + (f", {skipped} skipped for missing coordinates)" if skipped else ")"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
