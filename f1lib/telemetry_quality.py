"""Per-lap telemetry feed quality: flag laps whose live-timing feed is
missing or stair-stepped, so telemetry consumers can skip them.

A healthy feed delivers a sample every ~0.25 s per source and changes value on
almost every one: X/Y of the 'pos' source moves on > 95% of samples, the car
channels (Speed / RPM) change on > 90% of 'car' samples. Two failure modes,
measured per (driver, lap) on the lap-synced clock (f1lib/lap_sync):

  * stair-stepped: values re-emitted for seconds, then a jump. 2026
    Hungarian GP race from lap ~7: car channels move on ~33% of samples, pos
    on ~8%. 2026 Chinese GP FP1: car channels frozen throughout.
  * missing: 2026 Monaco GP race, the pos stream stops ~8 min after the
    start. The merged 'car' rows still carry X/Y, but those are
    extrapolated, i.e. fictional.

A third, found 2026-10-13: the car packet FREEZES — Speed, RPM and Throttle
all repeat the exact same values for seconds while the car is running (Stroll,
Singapore 2026 Q: 133 km/h / 12502 rpm held for 3.5 s while changing up from
2nd to 4th). The moving-share test misses it because the other samples of the
lap move. Measured as `car_frozen_s`, the longest such run above
MIN_SPEED_KMH. Healthy seasons never reach MAX_FROZEN_S: 2024 and 2025 put 6
and 23 laps over 2.0 s out of 71,000; 2026 put 2,720 (5.5%), concentrated on
the China / Japan / Hungary weekends. A Speed-ONLY plateau is NOT a freeze —
at the top of a straight (and under 2026 energy clipping) the speed really is
constant while RPM still moves; compute_section_profile's old Speed-only gate
threw those laps away and with them most of Aston Martin's.

Shifting the clock cannot fix any of them; measuring corners, phases or racing
lines on those laps measures the feed, not the car. The two sources fail
independently, so they are flagged separately: `pos_bad` matters to anything
using X/Y (replays, racing lines, lap-start positions), `car_bad` to anything
using Speed / Throttle / Brake / RPM (mistakes, phases, traits).

  pos_cov / car_cov        samples in the lap / (lap duration / 0.3 s), capped at 1
  pos_moving / car_moving  share of consecutive samples whose X-or-Y / Speed-or-
                           RPM changed, over samples with Speed >= 30 km/h (a
                           parked car repeats legitimately)

scripts/audit_telemetry_quality.py writes data/telemetry_quality.csv (one row
per session) and data/telemetry_degraded_laps.csv (one row per degraded
driver-lap); `degraded_laps` / `degraded_mask` read the latter.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

SESSION_CSV = Path("data/telemetry_quality.csv")
DEGRADED_CSV = Path("data/telemetry_degraded_laps.csv")

MIN_MOVING = 0.5          # below: stair-stepped
MIN_COVERAGE = 0.5        # below: missing (nominal rate ~0.25 s per source)
NOMINAL_DT = 0.3
MIN_SAMPLES = 20          # moving share needs this many judged samples
MIN_SPEED_KMH = 30.0      # only samples of a moving car are judged on movement
MAX_SESSION_BAD = 0.5     # above: the whole session is unusable for that channel
MAX_FROZEN_S = 2.0        # car packet (Speed+RPM+Throttle) frozen this long: car_bad


def _moving(t: np.ndarray, vals: list[np.ndarray]) -> np.ndarray:
    """1.0 where any channel differs from the previous sample (index 0: nan)."""
    ch = np.zeros(t.size, bool)
    for v in vals:
        ch[1:] |= v[1:] != v[:-1]
    out = ch.astype(float)
    if out.size:
        out[0] = np.nan
    return out


def _frozen_run_s(t: np.ndarray, key: np.ndarray, judged: np.ndarray,
                  starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """Per lap window: longest duration (s) of consecutive samples whose
    `key` (the whole car packet) repeats, every sample judged (moving car)."""
    out = np.zeros(starts.size)
    if t.size < 2:
        return out
    same = np.zeros(t.size, bool)
    same[1:] = (key[1:] == key[:-1]) & judged[1:] & judged[:-1]
    # run id: a new run starts wherever `same` is False
    rid = np.cumsum(~same)
    lo, hi = np.searchsorted(t, starts), np.searchsorted(t, ends)
    for i, (a, b) in enumerate(zip(lo, hi)):
        if b - a < 2:
            continue
        r = rid[a:b]
        tt = t[a:b]
        # duration of each run inside the window = last - first timestamp
        first = np.r_[True, r[1:] != r[:-1]]
        last = np.r_[r[1:] != r[:-1], True]
        d = tt[last] - tt[first]
        out[i] = float(d.max()) if d.size else 0.0
    return out


def lap_quality(laps: pd.DataFrame, tel: pd.DataFrame) -> pd.DataFrame:
    """Per (DriverNo, LapNo): coverage and moving share per source, the
    longest frozen car packet (car_frozen_s), pos_bad, car_bad, degraded.

    `tel` must be on the lap clock (read it through lap_sync.read_telemetry /
    load_session). Garage (0,0) pos samples count as missing."""
    lp = laps[["DriverNo", "LapNo", "LapStartTime", "Time"]].copy()
    lp["DriverNo"] = lp["DriverNo"].astype(str).str.strip()
    lp = lp.dropna(subset=["LapStartTime", "Time"])
    tel = tel.assign(DriverNo=tel["DriverNo"].astype(str).str.strip())
    groups = dict(tuple(tel.groupby("DriverNo")))
    rows = []
    for drv, L in lp.groupby("DriverNo"):
        L = L.sort_values("LapStartTime")
        starts = L["LapStartTime"].to_numpy(float)
        ends = L["Time"].to_numpy(float)
        dur = np.clip(ends - starts, 1e-6, None)
        g = groups.get(drv, tel.iloc[0:0])
        out = {"DriverNo": drv, "LapNo": L["LapNo"].to_numpy()}
        for src, cols in (("pos", ("X", "Y")), ("car", ("Speed", "RPM"))):
            s = g[g["Source"] == src] if "Source" in g.columns else g
            cols = [c for c in cols if c in s.columns]
            if src == "pos" and not s.empty:
                s = s[(s["X"] != 0) | (s["Y"] != 0)]
            s = s.sort_values("timestamp")
            t = s["timestamp"].to_numpy(float)
            mv = _moving(t, [s[c].to_numpy(float) for c in cols])
            # a parked car (red flag, garage) legitimately repeats its values
            if "Speed" in s.columns and mv.size:
                mv[s["Speed"].to_numpy(float) < MIN_SPEED_KMH] = np.nan
            lo, hi = np.searchsorted(t, starts), np.searchsorted(t, ends)
            share = []
            for a, b in zip(lo, hi):
                w = mv[max(a, 1):b]
                share.append(float(np.nanmean(w)) if np.isfinite(w).sum() >= MIN_SAMPLES
                             else np.nan)
            out[f"{src}_cov"] = np.round(np.minimum((hi - lo) * NOMINAL_DT / dur, 1.0), 3)
            out[f"{src}_moving"] = np.round(np.asarray(share, float), 3)
            if src == "car":
                pk = [c for c in ("Speed", "RPM", "Throttle") if c in s.columns]
                if pk and "Speed" in s.columns:
                    key = np.rec.fromarrays([s[c].to_numpy(float) for c in pk])
                    judged = s["Speed"].to_numpy(float) >= MIN_SPEED_KMH
                    out["car_frozen_s"] = np.round(
                        _frozen_run_s(t, key, judged, starts, ends), 2)
                else:
                    out["car_frozen_s"] = np.zeros(len(starts))
        rows.append(pd.DataFrame(out))
    cols = ["DriverNo", "LapNo", "pos_cov", "pos_moving", "car_cov", "car_moving",
            "car_frozen_s", "pos_bad", "car_bad", "degraded"]
    if not rows:
        return pd.DataFrame(columns=cols)
    q = pd.concat(rows, ignore_index=True)
    for src in ("pos", "car"):
        q[f"{src}_bad"] = (q[f"{src}_cov"] < MIN_COVERAGE) | (q[f"{src}_moving"] < MIN_MOVING)
    if "car_frozen_s" not in q.columns:
        q["car_frozen_s"] = 0.0
    q["car_bad"] |= q["car_frozen_s"] >= MAX_FROZEN_S
    q["degraded"] = q["pos_bad"] | q["car_bad"]
    return q[cols]


@lru_cache(maxsize=1)
def _degraded_table(mtime: float) -> dict[str, pd.DataFrame]:
    df = pd.read_csv(DEGRADED_CSV, dtype={"DriverNo": str, "stem": str})
    df["DriverNo"] = df["DriverNo"].str.strip()
    df["LapNo"] = df["LapNo"].astype(int)
    return {stem: g for stem, g in df.groupby("stem")}


def degraded_laps(stem: str, channel: str = "any") -> frozenset:
    """{(DriverNo, LapNo)} of degraded laps for cache stem
    `season__Meeting__Session`. channel: 'car' (Speed/Throttle/Brake/RPM),
    'pos' (X/Y) or 'any'. Empty when clean or not audited."""
    if not DEGRADED_CSV.exists():
        return frozenset()
    try:
        g = _degraded_table(DEGRADED_CSV.stat().st_mtime).get(stem)
    except Exception as exc:  # a broken CSV must never block an analysis
        logging.warning("telemetry_quality: cannot read %s: %s", DEGRADED_CSV, exc)
        return frozenset()
    if g is None:
        return frozenset()
    if channel != "any":
        g = g[g[f"{channel}_bad"].astype(bool)]
    return frozenset(zip(g["DriverNo"], g["LapNo"]))


@lru_cache(maxsize=1)
def _session_table(mtime: float) -> pd.DataFrame:
    return pd.read_csv(SESSION_CSV).set_index("stem")


def session_unusable(stem: str, channel: str = "car") -> bool:
    """True when more than half of the session's driver-laps have a degraded
    `channel` feed ('car' / 'pos'). The few clean laps left (2026 Hungarian
    race: laps 2-6) are not representative, so analyses drop the session
    instead of reporting a stub. False when clean or not audited."""
    if not SESSION_CSV.exists():
        return False
    try:
        t = _session_table(SESSION_CSV.stat().st_mtime)
        if stem not in t.index:
            return False
        r = t.loc[stem]
        return bool(r["n_laps"] and r[f"n_{channel}_bad"] / r["n_laps"] > MAX_SESSION_BAD)
    except Exception as exc:  # a broken CSV must never block an analysis
        logging.warning("telemetry_quality: cannot read %s: %s", SESSION_CSV, exc)
        return False


def degraded_mask(laps: pd.DataFrame, channel: str = "any",
                  stem: str | None = None) -> pd.Series:
    """Boolean Series over `laps` rows: True where the lap's `channel` feed is
    degraded. `stem` defaults to the laps' own season/meeting/session columns
    (a multi-session frame is handled per session)."""
    out = pd.Series(False, index=laps.index)
    if laps.empty:
        return out
    if stem is not None:
        groups = [(stem, laps)]
    else:
        from f1lib.data_loader import _session_key
        groups = [(_session_key(str(s), str(m), str(se)), g)
                  for (s, m, se), g in laps.groupby(["season", "meeting", "session"])]
    for st, g in groups:
        bad = degraded_laps(st, channel)
        if not bad:
            continue
        key = zip(g["DriverNo"].astype(str).str.strip(),
                  pd.to_numeric(g["LapNo"], errors="coerce").fillna(-1).astype(int))
        out.loc[g.index] = [k in bad for k in key]
    return out
