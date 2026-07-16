"""Micro-mistake detection from telemetry — where a driver loses time and errs.

The idea: a driver's median way through a corner is their "intent"; laps that
deviate from it are mistakes, and the deviations are visible in telemetry long
before they show up as a lost position. Per clean lap and per corner this
module measures the corner traversal time and two action signatures:

  lift          exit-phase throttle drop (≥85% → ≤50% → ≥85% with no brake) —
                a correction after running wide / losing the rear
  brake_reapp   brake released then re-applied before the apex — a misjudged
                entry (too deep, adjusting)

and flags a corner as a *slow outlier* when its time exceeds the driver's own
session median for that corner by max(0.25 s, 3×MAD) — but by less than a cap,
so traffic, yellow flags and SC laps don't masquerade as driving errors. Laps
in dirty air are excluded from the slow-outlier count entirely.

Everything is aggregated per (driver, corner): number of clean laps, mistake
counts by type, and the total time lost versus the driver's own median. A
separate per-lap event table feeds the pressure analysis (does the error rate
rise when a car is within striking distance behind?).

Corner geometry comes from the cached track maps (data/track_maps/), read
directly from disk so this module works offline in compute scripts — the
fractional corner positions are unit-independent and valid across seasons for
the same circuit.

Used by compute_mistakes.py (archive scan → data/mistakes_all.parquet) and by
the DUEL tab (live analysis of the loaded weekend).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TRACK_MAPS_DIR = Path("data/track_maps")

# detection thresholds
SLOW_FLOOR_S = 0.25       # minimum excess over median to call a corner slow
SLOW_MAD_K = 3.0          # ... or 3× the corner's MAD, whichever is larger
SLOW_CAP_S = 2.5          # excess beyond this = traffic/flag artefact, not a mistake
LIFT_HI, LIFT_LO = 85.0, 50.0   # exit-lift signature thresholds (% throttle)
PRESSURE_GAP_S = 1.5      # a car within this behind = "under pressure"


# ─────────────────────────────────────────────────────────────
# Corner geometry (offline read of the track-map cache)
# ─────────────────────────────────────────────────────────────

def track_map_slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_").lower()


def corner_fractions_from_geometry(line: pd.DataFrame,
                                   corners: pd.DataFrame) -> pd.DataFrame:
    """Each corner's fractional position along the lap (0 = start line), plus
    its X/Y for map plotting. Same math as tabs/telemetry.py but keeps X/Y."""
    if (line is None or corners is None or line.empty or corners.empty
            or not {"X", "Y"}.issubset(line.columns)
            or not {"X", "Y"}.issubset(corners.columns)):
        return pd.DataFrame()
    lx = line["X"].to_numpy(float); ly = line["Y"].to_numpy(float)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(lx), np.diff(ly)))])
    total = cum[-1]
    if not np.isfinite(total) or total <= 0:
        return pd.DataFrame()
    rows = []
    for _, c in corners.iterrows():
        i = int(np.argmin((lx - c["X"]) ** 2 + (ly - c["Y"]) ** 2))
        num = c.get("Number")
        letter = c.get("Letter")
        letter = "" if (letter is None or (isinstance(letter, float)
                                           and np.isnan(letter))) else str(letter).strip()
        try:
            label = f"{int(num)}{letter}"
        except (TypeError, ValueError):
            label = f"{num}{letter}"
        rows.append({"label": label, "frac": cum[i] / total,
                     "X": float(c["X"]), "Y": float(c["Y"])})
    return pd.DataFrame(rows).sort_values("frac").reset_index(drop=True)


def load_corner_fractions(event_name: str,
                          season: int | None = None) -> pd.DataFrame:
    """Corner fractions for a circuit from the on-disk track-map cache.
    Prefers the requested season's map, falls back to the latest cached one
    for the same circuit slug (geometry is stable across seasons)."""
    slug = track_map_slug(event_name)
    cands = sorted(TRACK_MAPS_DIR.glob(f"*_{slug}_*_corners.parquet"))
    if not cands:
        return pd.DataFrame()

    def _season_of(p: Path) -> int:
        try:
            return int(p.name.split("_", 1)[0])
        except ValueError:
            return 0

    pick = None
    if season is not None:
        same = [p for p in cands if _season_of(p) == int(season)]
        pick = same[-1] if same else None
    if pick is None:
        pick = max(cands, key=_season_of)
    line_path = Path(str(pick).replace("_corners.parquet", ".parquet"))
    if not line_path.exists():
        return pd.DataFrame()
    try:
        corners = pd.read_parquet(pick)
        line = pd.read_parquet(line_path)
    except Exception as exc:
        logger.warning("track map read failed for %s: %s", event_name, exc)
        return pd.DataFrame()
    return corner_fractions_from_geometry(line, corners)


def load_track_line(event_name: str, season: int | None = None) -> pd.DataFrame:
    """The cached racing line (X/Y/speed/drs/sector) for map plotting, with a
    'frac' column (fractional distance along the lap)."""
    slug = track_map_slug(event_name)
    cands = sorted(TRACK_MAPS_DIR.glob(f"*_{slug}_*.parquet"))
    cands = [p for p in cands if not p.name.endswith("_corners.parquet")]
    if not cands:
        return pd.DataFrame()

    def _season_of(p: Path) -> int:
        try:
            return int(p.name.split("_", 1)[0])
        except ValueError:
            return 0

    pick = None
    if season is not None:
        same = [p for p in cands if _season_of(p) == int(season)]
        pick = same[-1] if same else None
    if pick is None:
        pick = max(cands, key=_season_of)
    try:
        line = pd.read_parquet(pick)
    except Exception:
        return pd.DataFrame()
    if line.empty or not {"X", "Y"}.issubset(line.columns):
        return pd.DataFrame()
    lx = line["X"].to_numpy(float); ly = line["Y"].to_numpy(float)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(lx), np.diff(ly)))])
    total = cum[-1] if len(cum) else 0.0
    line = line.copy()
    line["frac"] = cum / total if total > 0 else 0.0
    # rotation lives in the meta json next to the line parquet
    meta = Path(str(pick).replace(".parquet", ".json"))
    rot = 0.0
    if meta.exists():
        try:
            rot = float(json.loads(meta.read_text()).get("rotation", 0.0))
        except Exception:
            rot = 0.0
    line.attrs["rotation"] = rot
    return line


# ─────────────────────────────────────────────────────────────
# Per-lap corner features
# ─────────────────────────────────────────────────────────────

def _lap_corner_features(t_rel: np.ndarray, dist: np.ndarray,
                         spd: np.ndarray, thr: np.ndarray | None,
                         brk: np.ndarray | None,
                         fracs: pd.DataFrame) -> list[dict]:
    """Corner features for ONE lap. Arrays are the lap's telemetry sorted by
    time; `fracs` is the circuit corner table (label, frac). Returns one dict
    per corner: label, time_s, vmin, lift, brake_reapp."""
    total = float(dist[-1]) if len(dist) else 0.0
    if not np.isfinite(total) or total <= 0 or len(dist) < 10:
        return []
    centers = fracs["frac"].to_numpy(float) * total
    labels = fracs["label"].tolist()
    n = len(centers)
    # zone boundaries at midpoints between consecutive corner apexes
    bounds = np.empty(n + 1)
    bounds[0] = 0.0
    bounds[-1] = total
    bounds[1:-1] = (centers[:-1] + centers[1:]) / 2.0
    # traversal time at each boundary by interpolating t over distance
    # (dist is monotonic by construction — integrated speed)
    tb = np.interp(bounds, dist, t_rel)
    out = []
    for i in range(n):
        lo, hi = bounds[i], bounds[i + 1]
        m = (dist >= lo) & (dist <= hi)
        if m.sum() < 3:
            continue
        seg_spd = spd[m]
        vmin = float(np.nanmin(seg_spd)) if np.isfinite(seg_spd).any() else np.nan
        apex_i = int(np.nanargmin(seg_spd)) if np.isfinite(seg_spd).any() else 0
        lift = 0
        brake_reapp = 0
        if thr is not None:
            seg_thr = thr[m]
            seg_brk = brk[m] if brk is not None else np.zeros(m.sum())
            # exit lift: after the apex, throttle ≥HI then ≤LO then ≥HI, no brake
            ex_thr = seg_thr[apex_i:]
            ex_brk = seg_brk[apex_i:]
            state = 0
            for v, b in zip(ex_thr, ex_brk):
                if state == 0 and v >= LIFT_HI:
                    state = 1
                elif state == 1 and v <= LIFT_LO and not b:
                    state = 2
                elif state == 2 and (b or v <= 5):
                    state = 0          # braking / bailed → not a lift signature
                elif state == 2 and v >= LIFT_HI:
                    lift = 1
                    break
        if brk is not None:
            # entry brake re-application: on → off (≥2 samples) → on again
            # before (just past) the apex
            en_brk = (brk[m][: apex_i + 2] > 0.5).astype(int)
            if len(en_brk) >= 4:
                d = np.diff(en_brk)
                offs = np.where(d == -1)[0]
                ons = np.where(d == 1)[0]
                for o in offs:
                    later = ons[ons >= o + 2]     # ≥2 samples released
                    if later.size:
                        brake_reapp = 1
                        break
        out.append({"corner": labels[i], "time_s": float(tb[i + 1] - tb[i]),
                    "vmin": vmin, "lift": lift, "brake_reapp": brake_reapp})
    return out


def corner_features_for_session(laps: pd.DataFrame, telemetry: pd.DataFrame,
                                fracs: pd.DataFrame,
                                drivers: list[str] | None = None
                                ) -> pd.DataFrame:
    """Per-lap, per-corner features for every analysable lap of a session.

    `laps` must be the enriched frame (LapTime_s, ValidLap, Driver_Short,
    LapStartTime); `telemetry` the matching raw/enriched telemetry with a float
    `timestamp` column. Returns rows [Driver_Short, Team, LapNo, corner,
    time_s, vmin, lift, brake_reapp]."""
    if laps.empty or telemetry.empty or fracs.empty:
        return pd.DataFrame()
    lp = laps[pd.to_numeric(laps["LapTime_s"], errors="coerce") > 0].copy()
    if drivers:
        lp = lp[lp["Driver_Short"].isin(drivers)]
    if lp.empty:
        return pd.DataFrame()

    tel = telemetry
    if "timestamp" in tel.columns and tel["timestamp"].dtype == object:
        tel = tel.copy()
        tel["timestamp"] = pd.to_numeric(tel["timestamp"], errors="coerce")

    rows = []
    for dno, g in lp.groupby(lp["DriverNo"].astype(str).str.strip()):
        pool = tel[tel["DriverNo"].astype(str).str.strip() == dno]
        if pool.empty:
            continue
        pool = pool.sort_values("timestamp")
        ts = pool["timestamp"].to_numpy(float)
        spd_all = pd.to_numeric(pool["Speed"], errors="coerce").to_numpy(float)
        thr_all = (pd.to_numeric(pool["Throttle"], errors="coerce").to_numpy(float)
                   if "Throttle" in pool.columns else None)
        brk_all = (pd.to_numeric(pool["Brake"], errors="coerce").fillna(0)
                   .to_numpy(float) if "Brake" in pool.columns else None)
        drv = g["Driver_Short"].iloc[0]
        team = g["Team"].iloc[0] if "Team" in g.columns else ""
        for _, lap in g.iterrows():
            start = pd.to_numeric(lap.get("LapStartTime"), errors="coerce")
            dur = pd.to_numeric(lap.get("LapTime_s"), errors="coerce")
            if not (np.isfinite(start) and np.isfinite(dur)):
                continue
            i0, i1 = np.searchsorted(ts, [start, start + dur])
            if i1 - i0 < 20:
                continue
            t_rel = ts[i0:i1] - start
            spd = spd_all[i0:i1]
            # distance by integrating speed (km/h → m/s), same as the
            # telemetry tab
            v = np.nan_to_num(spd, nan=0.0) * (1000.0 / 3600.0)
            dt = np.diff(t_rel)
            dist = np.concatenate([[0.0], np.cumsum((v[1:] + v[:-1]) / 2 * dt)])
            feats = _lap_corner_features(
                t_rel, dist, spd,
                thr_all[i0:i1] if thr_all is not None else None,
                brk_all[i0:i1] if brk_all is not None else None, fracs)
            for f in feats:
                f.update({"Driver_Short": drv, "Team": team,
                          "LapNo": int(lap["LapNo"])})
            rows.extend(feats)
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────
# Aggregation: mistakes per (driver, corner) + per-lap events
# ─────────────────────────────────────────────────────────────

def _analysis_lap_mask(laps: pd.DataFrame) -> pd.Series:
    """Laps whose corner times are meaningful: green flag, no pit in/out,
    plausible lap time (excludes SC crawls and in/out laps)."""
    lt = pd.to_numeric(laps["LapTime_s"], errors="coerce")
    ok = lt.notna() & (lt > 0)
    med = lt[ok].median()
    if np.isfinite(med):
        ok &= lt < med + 10.0
    if "TrackStatus" in laps.columns:
        ok &= laps["TrackStatus"].astype(str).isin(["1", "1.0"])
    for c in ("PitOutTime", "PitInTime"):
        if c in laps.columns:
            ok &= laps[c].isna()
    if "PitOut" in laps.columns:                       # cached raw schema
        ok &= ~laps["PitOut"].fillna(False).astype(bool)
    if "PitIn" in laps.columns:
        ok &= ~laps["PitIn"].fillna(False).astype(bool)
    return ok


def aggregate_mistakes(feats: pd.DataFrame, laps: pd.DataFrame
                       ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(corner_agg, lap_events) from per-lap corner features.

    corner_agg: per (Driver_Short, corner) — n_laps, n_slow, n_lift,
                n_brake_reapp, time_lost_s, med_time_s.
    lap_events: per (Driver_Short, LapNo) — n_events (for pressure analysis).

    Slow-outlier detection compares each lap's corner time to the driver's own
    median for that corner; laps in dirty air (flag from the enrichment
    pipeline, when present) are excluded from the slow count so traffic
    doesn't read as error."""
    if feats.empty:
        return pd.DataFrame(), pd.DataFrame()
    f = feats.copy()

    ok = _analysis_lap_mask(laps)
    keep = set(map(tuple, laps.loc[ok, ["Driver_Short", "LapNo"]]
                   .itertuples(index=False, name=None)))
    f = f[[(d, l) in keep for d, l in zip(f["Driver_Short"], f["LapNo"])]]
    if f.empty:
        return pd.DataFrame(), pd.DataFrame()

    dirty = set()
    if "Dirty_Air" in laps.columns:
        dd = laps[laps["Dirty_Air"].fillna(False).astype(bool)]
        dirty = set(map(tuple, dd[["Driver_Short", "LapNo"]]
                        .itertuples(index=False, name=None)))
    f["_dirty"] = [(d, l) in dirty for d, l in zip(f["Driver_Short"], f["LapNo"])]

    g = f.groupby(["Driver_Short", "corner"])["time_s"]
    med = g.transform("median")
    mad = (f["time_s"] - med).abs().groupby(
        [f["Driver_Short"], f["corner"]]).transform("median")
    thresh = np.maximum(SLOW_FLOOR_S, SLOW_MAD_K * mad)
    excess = f["time_s"] - med
    f["slow"] = ((excess > thresh) & (excess < SLOW_CAP_S) & ~f["_dirty"]).astype(int)
    f["lost"] = np.where(f["slow"] == 1, excess, 0.0)
    # lifts/re-applications in dirty air are reactions to the car ahead
    f.loc[f["_dirty"], ["lift", "brake_reapp"]] = 0

    agg = (f.groupby(["Driver_Short", "Team", "corner"], as_index=False)
           .agg(n_laps=("time_s", "size"), n_slow=("slow", "sum"),
                n_lift=("lift", "sum"), n_brake_reapp=("brake_reapp", "sum"),
                time_lost_s=("lost", "sum"), med_time_s=("time_s", "median")))
    agg["n_mistakes"] = agg["n_slow"] + agg["n_lift"] + agg["n_brake_reapp"]

    f["n_events"] = f["slow"] + f["lift"] + f["brake_reapp"]
    lap_events = (f.groupby(["Driver_Short", "LapNo"], as_index=False)
                  .agg(n_events=("n_events", "sum")))
    return agg, lap_events


# ─────────────────────────────────────────────────────────────
# Track-limit deletions per corner
# ─────────────────────────────────────────────────────────────

_TL_TURN_RE = re.compile(r"TURN\s+(\d+)", re.IGNORECASE)


def track_limit_deletions(laps: pd.DataFrame) -> pd.DataFrame:
    """Per (Driver_Short, corner) count of track-limit lap deletions, parsed
    from the DeletedReason carried on the lap rows."""
    if "DeletedReason" not in laps.columns:
        return pd.DataFrame()
    d = laps.dropna(subset=["DeletedReason"]).copy()
    if "IsDeleted" in d.columns:
        d = d[d["IsDeleted"].fillna(False).astype(bool)]
    d = d[d["DeletedReason"].astype(str).str.contains("TRACK LIMITS",
                                                      case=False, na=False)]
    if d.empty:
        return pd.DataFrame()
    d["corner"] = d["DeletedReason"].astype(str).str.extract(_TL_TURN_RE,
                                                             expand=False)
    d = d.dropna(subset=["corner"])
    if d.empty:
        return pd.DataFrame()
    return (d.groupby(["Driver_Short", "corner"], as_index=False)
            .size().rename(columns={"size": "tl_deletions"}))


# ─────────────────────────────────────────────────────────────
# Pressure analysis
# ─────────────────────────────────────────────────────────────

def pressure_table(laps: pd.DataFrame, lap_events: pd.DataFrame
                   ) -> pd.DataFrame:
    """Per-driver mistake rates with and without a car within
    PRESSURE_GAP_S behind (race sessions only — needs live Position).

    Gap to the car behind at the end of each lap = difference of the two
    cars' lap-completion session times at equal lap number."""
    need = {"Position", "LapStartTime", "LapTime_s", "Driver_Short", "LapNo"}
    if lap_events.empty or not need.issubset(laps.columns):
        return pd.DataFrame()
    lp = laps.copy()
    lp["Position"] = pd.to_numeric(lp["Position"], errors="coerce")
    lp["t_end"] = (pd.to_numeric(lp["LapStartTime"], errors="coerce")
                   + pd.to_numeric(lp["LapTime_s"], errors="coerce"))
    lp = lp.dropna(subset=["Position", "t_end"])
    if lp.empty:
        return pd.DataFrame()

    parts = []
    for _, g in lp.groupby("LapNo"):
        g = g.sort_values("Position")
        gap_behind = g["t_end"].shift(-1) - g["t_end"]
        parts.append(pd.DataFrame({
            "Driver_Short": g["Driver_Short"], "LapNo": g["LapNo"],
            "pressured": gap_behind <= PRESSURE_GAP_S}))
    press = pd.concat(parts, ignore_index=True)
    press["pressured"] = press["pressured"].fillna(False)

    ev = lap_events.merge(press, on=["Driver_Short", "LapNo"], how="inner")
    if ev.empty:
        return pd.DataFrame()
    out = (ev.groupby(["Driver_Short", "pressured"])
           .agg(laps=("LapNo", "size"), events=("n_events", "sum"))
           .reset_index())
    piv = out.pivot(index="Driver_Short", columns="pressured",
                    values=["laps", "events"]).fillna(0)
    piv.columns = [f"{a}_{'p' if b else 'f'}" for a, b in piv.columns]
    piv = piv.reset_index()
    for c in ("laps_p", "laps_f", "events_p", "events_f"):
        if c not in piv.columns:
            piv[c] = 0
    return piv
