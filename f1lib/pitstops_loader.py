"""
F1 Dashboard – Pit-Stop Data Loader
===================================
Fetches *real* per-stop pit data (not inferred from lap-time deltas) and
caches it as Parquet under data/pitstops/.

Two sources, tried in order:

1. **F1 live-timing archive** — ``PitStopSeries.jsonStream`` carries, per stop,
   the true **stationary time** (``PitStopTime``, e.g. "2.4") *and* the
   pit-lane transit time (``PitLaneTime``), keyed by racing number + lap.
   Like team radio, F1 only keeps this feed for recent events.

2. **Jolpica (Ergast successor)** — ``/f1/{season}/{round}/pitstops`` has the
   pit-lane duration + time of day for every race back to 2012. No stationary
   time, but it makes the pit-crew data collectable for any historical race.

Public API
----------
load_pitstops(season, meeting, force=False) -> pd.DataFrame
    One row per stop. Columns:
      season, meeting, round, DriverNo (racing number, "" when unknown),
      Driver_Short (3-letter code, "" when unknown), LapNo, StopNo,
      StationaryTime_s (NaN when only Jolpica data exists), PitLaneTime_s,
      Utc, source ("livetiming" | "jolpica")
pitstops_cached(season, meeting) -> bool
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from f1lib.config import PITSTOPS_DIR
# Reuse the live-timing helpers from the radio loader (same archive, same
# api_path resolution via FastF1). faster-whisper is lazy-loaded there, so
# this import stays lightweight.
from f1lib.radio_loader import _http_get, _race_api_path, _sanitize, _BASE

logger = logging.getLogger(__name__)

_JOLPICA = "https://api.jolpi.ca/ergast/f1"

_SCHEDULE_MEMO: dict[str, dict] = {}     # season -> {raceName.lower(): round}
_DRIVERS_MEMO: dict[str, dict] = {}      # season -> {driverId: (code, number)}

_COLUMNS = ["season", "meeting", "round", "DriverNo", "Driver_Short",
            "LapNo", "StopNo", "StationaryTime_s", "PitLaneTime_s",
            "Utc", "source"]


def _parquet_path(season, meeting) -> Path:
    return Path(PITSTOPS_DIR) / (
        f"{_sanitize(season)}__{_sanitize(meeting)}__Race__pitstops.parquet"
    )


def pitstops_cached(season, meeting) -> bool:
    return _parquet_path(season, meeting).exists()


# ─────────────────────────────────────────────────────────────
# Jolpica helpers
# ─────────────────────────────────────────────────────────────

def _jolpica_json(path: str) -> dict | None:
    url = f"{_JOLPICA}/{path}"
    try:
        return json.loads(_http_get(url).decode("utf-8", "ignore"))
    except Exception as exc:
        logger.warning("Jolpica fetch failed (%s): %s", url, exc)
        return None


def _season_round(season, meeting) -> int | None:
    """Resolve a meeting name to its championship round via the Jolpica
    season schedule (exact match first, then substring)."""
    season = str(season)
    if season not in _SCHEDULE_MEMO:
        data = _jolpica_json(f"{season}.json?limit=100")
        races = (data or {}).get("MRData", {}).get("RaceTable", {}).get("Races", [])
        _SCHEDULE_MEMO[season] = {
            r["raceName"].strip().lower(): int(r["round"]) for r in races
        }
    sched = _SCHEDULE_MEMO[season]
    name = str(meeting).strip().lower()
    if name in sched:
        return sched[name]
    for race_name, rnd in sched.items():
        if name in race_name or race_name in name:
            return rnd
    logger.warning("No Jolpica round found for %s %s", season, meeting)
    return None


def _season_drivers(season) -> dict:
    """driverId -> (3-letter code, permanent number) for a season."""
    season = str(season)
    if season not in _DRIVERS_MEMO:
        data = _jolpica_json(f"{season}/drivers.json?limit=100")
        drivers = (data or {}).get("MRData", {}).get("DriverTable", {}).get("Drivers", [])
        _DRIVERS_MEMO[season] = {
            d["driverId"]: (d.get("code", ""), d.get("permanentNumber", ""))
            for d in drivers
        }
    return _DRIVERS_MEMO[season]


def _parse_duration(val) -> float:
    """Jolpica durations are seconds ('21.297') but switch to 'M:SS.mmm'
    for very long stops (red flags, repairs)."""
    s = str(val or "").strip()
    if not s:
        return np.nan
    try:
        if ":" in s:
            mins, secs = s.rsplit(":", 1)
            return float(mins) * 60.0 + float(secs)
        return float(s)
    except ValueError:
        return np.nan


def _fetch_jolpica_stops(season, meeting) -> pd.DataFrame:
    rnd = _season_round(season, meeting)
    if rnd is None:
        return pd.DataFrame()
    stops, offset, total = [], 0, None
    while total is None or offset < total:
        data = _jolpica_json(f"{season}/{rnd}/pitstops.json?limit=100&offset={offset}")
        if data is None:
            break
        mr = data.get("MRData", {})
        total = int(mr.get("total", 0))
        races = mr.get("RaceTable", {}).get("Races", [])
        if not races:
            break
        stops.extend(races[0].get("PitStops", []))
        offset += 100
    if not stops:
        return pd.DataFrame()

    dmap = _season_drivers(season)
    rows = []
    for s in stops:
        code, number = dmap.get(s.get("driverId", ""), ("", ""))
        rows.append({
            "season":           str(season),
            "meeting":          meeting,
            "round":            rnd,
            "DriverNo":         str(number),
            "Driver_Short":     code,
            "LapNo":            int(s.get("lap", 0)),
            "StopNo":           int(s.get("stop", 0)),
            "StationaryTime_s": np.nan,
            "PitLaneTime_s":    _parse_duration(s.get("duration")),
            "Utc":              s.get("time", ""),
            "source":           "jolpica",
        })
    return pd.DataFrame(rows, columns=_COLUMNS)


# ─────────────────────────────────────────────────────────────
# Live-timing PitStopSeries
# ─────────────────────────────────────────────────────────────

def _fetch_livetiming_stops(season, meeting) -> pd.DataFrame:
    """Parse PitStopSeries.jsonStream — lines look like
    ``01:12:03.942{"PitTimes":{"44":[{"Timestamp":...,"PitStop":{...}}]}}``."""
    try:
        rel = _race_api_path(season, meeting)
    except Exception as exc:
        logger.warning("api_path resolution failed for %s %s: %s",
                       season, meeting, exc)
        return pd.DataFrame()
    if not rel:
        return pd.DataFrame()
    url = _BASE + rel + "PitStopSeries.jsonStream"
    try:
        txt = _http_get(url).decode("utf-8-sig", "ignore")
    except Exception as exc:
        logger.info("PitStopSeries unavailable (%s): %s", url, exc)
        return pd.DataFrame()

    rows, seen = [], set()
    for line in txt.splitlines():
        brace = line.find("{")
        if brace < 0:
            continue
        try:
            obj = json.loads(line[brace:])
        except Exception:
            continue
        for entries in obj.get("PitTimes", {}).values():
            if not isinstance(entries, list):
                continue
            for e in entries:
                ps = e.get("PitStop", {}) if isinstance(e, dict) else {}
                num = str(ps.get("RacingNumber", "")).strip()
                utc = str(e.get("Timestamp", "")) if isinstance(e, dict) else ""
                if not num or (num, utc) in seen:
                    continue
                seen.add((num, utc))
                # Lap can be missing/empty in some feeds — keep the stop,
                # the lap number just won't plot on the lap axis.
                lap = pd.to_numeric(ps.get("Lap"), errors="coerce")
                rows.append({
                    "season":           str(season),
                    "meeting":          meeting,
                    "round":            np.nan,
                    "DriverNo":         num,
                    "Driver_Short":     "",
                    "LapNo":            float(lap) if pd.notna(lap) else np.nan,
                    "StopNo":           0,          # filled below
                    "StationaryTime_s": pd.to_numeric(ps.get("PitStopTime"), errors="coerce"),
                    "PitLaneTime_s":    pd.to_numeric(ps.get("PitLaneTime"), errors="coerce"),
                    "Utc":              utc,
                    "source":           "livetiming",
                })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=_COLUMNS)
    df = df.sort_values(["DriverNo", "Utc"]).reset_index(drop=True)
    df["StopNo"] = df.groupby("DriverNo").cumcount() + 1
    return df


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def load_pitstops(season, meeting, force: bool = False) -> pd.DataFrame:
    """Fetch (or load from cache) the pit stops of a meeting's race.
    Empty DataFrame when neither source has data (race not run yet, or
    the meeting name resolves nowhere)."""
    pq = _parquet_path(season, meeting)
    if pq.exists() and not force:
        df = pd.read_parquet(pq)
        logger.info("[pitstops cache HIT] %s %s (%d stops)", season, meeting, len(df))
        return df

    df = _fetch_livetiming_stops(season, meeting)
    if df.empty:
        df = _fetch_jolpica_stops(season, meeting)
    else:
        # Jolpica knows the round number, driver codes and lap numbers (which
        # some live-timing feeds omit) — enrich when it answers. Join key is
        # (permanent number, stop index); the car whose racing number differs
        # from its permanent number (the champion's #1) simply stays unfilled.
        rnd = _season_round(season, meeting)
        if rnd is not None:
            df["round"] = rnd
        jd = _fetch_jolpica_stops(season, meeting)
        if not jd.empty:
            jmap = jd.set_index([jd["DriverNo"].astype(str),
                                 jd["StopNo"].astype(int)])
            idx = pd.MultiIndex.from_arrays(
                [df["DriverNo"].astype(str), df["StopNo"].astype(int)])
            df["LapNo"] = df["LapNo"].fillna(
                pd.Series(jmap["LapNo"].reindex(idx).values, index=df.index))
            need = df["Driver_Short"].fillna("").eq("")
            codes = pd.Series(jmap["Driver_Short"].reindex(idx).values,
                              index=df.index)
            df.loc[need, "Driver_Short"] = codes[need].fillna("")
    if df.empty:
        logger.info("[pitstops] no data for %s %s", season, meeting)
        return df

    pq.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(pq, index=False)
    logger.info("[pitstops] saved %s %s (%d stops, source=%s)",
                season, meeting, len(df), df["source"].iloc[0])
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    import sys
    yr  = sys.argv[1] if len(sys.argv) > 1 else "2026"
    mtg = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "Austrian Grand Prix"
    out = load_pitstops(yr, mtg)
    print(out.to_string() if not out.empty else "no pit-stop data")
