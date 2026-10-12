"""Lap-boundary ↔ telemetry-clock sync (FastF1 mis-synced sessions).

For a few sessions FastF1's lap boundaries (laps `LapStartTime`, session
seconds) and its telemetry clock (telemetry `timestamp`) disagree by several
seconds, per driver — audit Oct 2026 over every cached session: the 2026
Bahrain GP race (at Sepang) +19.6 s for 21 of 22 drivers (FastF1 itself warns
"completed the race distance 00:19.478 before the recorded end of the
session"), Zandvoort 2023 +2.2 s / 2026 +1.6 s, Austria 2026 race −1.9 s,
Las Vegas 2024 +0.5 s, Austria 2026 quali drifting −1.2 → −1.5 s then ~0.
The LAP clock is the right one (lap-start order matches the official running
order exactly; raw telemetry does not), and speed and position agree with
each other — so the fix shifts telemetry `timestamp` onto the lap clock.

  * the start/finish point of a weekend is the location most lap starts agree
    on across ALL its cached sessions (most sessions are fine, so the
    consensus is robust even when one session is badly shifted);
  * per lap, the crossing time is the moment the pos trace passes closest to
    that point (linear interpolation between pos samples), searched ±25 s
    around LapStartTime. Laps on a stair-stepped (degraded) pos trace, or
    whose offset disagrees with both neighbouring laps, are dropped; a
    rolling median of 3 gives one knot per lap, and the shift interpolates
    between knots (the offset can drift and step within a session);
  * a driver is corrected only when enough laps sit clearly off the line AND
    the shift puts them back on it — aligned sessions are never touched.

scripts/audit_lap_sync.py writes data/lap_sync_offsets.csv (summary per
driver-session, all cached sessions) and data/lap_sync_knots.csv (knots of
the corrected drivers). `apply_offsets` / `read_telemetry` read the knots, so
the load-time fix costs one small CSV read. X/Y are in DECIMETRES throughout.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

OFFSETS_CSV = Path("data/lap_sync_offsets.csv")   # per driver-session summary
KNOTS_CSV = Path("data/lap_sync_knots.csv")       # per-lap knots, corrected drivers only

SF_CLUSTER_DM = 150.0     # lap starts within 15 m count as "on the same spot"
OFF_LINE_DM = 200.0       # driver median lap start > 20 m off the line → shifted
CROSS_MAX_DM = 300.0      # a lap's closest approach must be within 30 m
SEARCH_S = 25.0           # crossing searched ±25 s around LapStartTime
MIN_TRACE_MOVING = 0.5    # ≥ half the pos samples near the line must move
NEIGHBOUR_TOL_S = 0.3     # a lap's offset must match a neighbouring lap's
MIN_OFFSET_S = 0.25       # ≈ 20 m at start/finish speed: below that, noise
MIN_SHARE_OFF = 0.3       # ≥ 30% of a driver's lap starts > OFF_LINE_DM off
MIN_LAPS = 3


def _pos(tel: pd.DataFrame) -> pd.DataFrame:
    """Position samples only (raw, not interpolated), off the (0,0) garage."""
    p = tel
    if "Source" in p.columns:
        p = p[p["Source"] == "pos"]
    p = p[["DriverNo", "timestamp", "X", "Y"]].dropna()
    p = p[(p["X"] != 0) | (p["Y"] != 0)]
    p = p.assign(DriverNo=p["DriverNo"].astype(str).str.strip())
    return p.sort_values(["DriverNo", "timestamp"])


def _timed_laps(laps: pd.DataFrame) -> pd.DataFrame:
    """Flying-start laps: lap ≥ 2, not a pit-out lap (those start in the pit
    lane), with a LapStartTime."""
    lp = laps.copy()
    lp["DriverNo"] = lp["DriverNo"].astype(str).str.strip()
    lp = lp[pd.to_numeric(lp["LapNo"], errors="coerce") >= 2]
    lp = lp[lp["LapStartTime"].notna()]
    if "PitOut" in lp.columns:
        lp = lp[lp["PitOut"].isna()]
    return lp[["DriverNo", "LapNo", "LapStartTime"]]


def lap_start_points(laps: pd.DataFrame, tel: pd.DataFrame,
                     tol_s: float = 1.0) -> pd.DataFrame:
    """Per lap: the pos sample nearest LapStartTime (within tol_s) → X, Y."""
    pos = _pos(tel)
    out = []
    for drv, lp in _timed_laps(laps).groupby("DriverNo"):
        p = pos[pos["DriverNo"] == drv]
        if p.empty:
            continue
        t = p["timestamp"].to_numpy(float)
        q = lp["LapStartTime"].to_numpy(float)
        i = np.clip(np.searchsorted(t, q), 1, len(t) - 1)
        i = np.where(np.abs(t[i - 1] - q) < np.abs(t[i] - q), i - 1, i)
        ok = np.abs(t[i] - q) <= tol_s
        out.append(pd.DataFrame({
            "DriverNo": drv, "LapNo": lp["LapNo"].to_numpy()[ok],
            "X": p["X"].to_numpy(float)[i[ok]], "Y": p["Y"].to_numpy(float)[i[ok]],
        }))
    return (pd.concat(out, ignore_index=True) if out
            else pd.DataFrame(columns=["DriverNo", "LapNo", "X", "Y"]))


def consensus_sf(points: list[pd.DataFrame]) -> tuple[float, float] | None:
    """Start/finish point = per-driver-session median lap start with the most
    other driver-sessions within SF_CLUSTER_DM, refined to the median of that
    cluster. `points` = lap_start_points frames (one per session)."""
    meds = [p.groupby("DriverNo")[["X", "Y"]].median() for p in points if not p.empty]
    if not meds:
        return None
    m = pd.concat(meds).to_numpy(float)
    d = np.hypot(m[:, None, 0] - m[None, :, 0], m[:, None, 1] - m[None, :, 1])
    support = (d <= SF_CLUSTER_DM).sum(axis=1)
    best = int(np.argmax(support))
    cl = m[d[best] <= SF_CLUSTER_DM]
    return float(np.median(cl[:, 0])), float(np.median(cl[:, 1]))


def _crossing_times(t: np.ndarray, x: np.ndarray, y: np.ndarray,
                    sf: tuple[float, float], q: float) -> float | None:
    """Time the trace passes closest to sf within ±SEARCH_S of q."""
    lo, hi = np.searchsorted(t, [q - SEARCH_S, q + SEARCH_S])
    if hi - lo < 3:
        return None
    tt, xx, yy = t[lo:hi], x[lo:hi], y[lo:hi]
    # project sf onto every segment, keep the closest
    dx, dy = np.diff(xx), np.diff(yy)
    seg2 = dx * dx + dy * dy
    with np.errstate(invalid="ignore", divide="ignore"):
        u = ((sf[0] - xx[:-1]) * dx + (sf[1] - yy[:-1]) * dy) / seg2
    u = np.clip(np.nan_to_num(u), 0.0, 1.0)
    px, py = xx[:-1] + u * dx, yy[:-1] + u * dy
    dist = np.hypot(px - sf[0], py - sf[1])
    # several passes in the window (slow laps / short tracks): the one nearest q
    cand = np.flatnonzero(dist <= CROSS_MAX_DM)
    if cand.size == 0:
        return None
    tc = tt[:-1][cand] + u[cand] * np.diff(tt)[cand]
    # keep the local minimum of each pass, then the pass nearest q
    passes = np.split(cand, np.flatnonzero(np.diff(cand) > 1) + 1)
    best_t = [tc[np.isin(cand, ps)][np.argmin(dist[ps])] for ps in passes]
    return float(min(best_t, key=lambda v: abs(v - q)))


def _trace_ok(t: np.ndarray, x: np.ndarray, y: np.ndarray, tc: float,
              half: float = 5.0) -> bool:
    """False when the pos trace around tc is stair-stepped (a degraded feed
    repeating the same X/Y for seconds — 2026 Hungarian race): there the
    'crossing' is just the nearest frozen sample. X OR Y must move: on a
    straight aligned with an axis (Monaco's) one of them barely changes."""
    lo, hi = np.searchsorted(t, [tc - half, tc + half])
    if hi - lo < 8:
        return False
    moving = (np.diff(x[lo:hi]) != 0) | (np.diff(y[lo:hi]) != 0)
    return float(moving.mean()) >= MIN_TRACE_MOVING


def _consistent(off: np.ndarray, tol: float = NEIGHBOUR_TOL_S) -> np.ndarray:
    """Keep a lap's offset only if it agrees with the previous or next one."""
    keep = np.zeros(off.size, bool)
    if off.size >= 2:
        d = np.abs(np.diff(off)) <= tol
        keep[:-1] |= d
        keep[1:] |= d
    return keep


def shift_at(ts: np.ndarray, knot_t: np.ndarray, knot_off: np.ndarray) -> np.ndarray:
    """Offset (s) to subtract at telemetry times ts: linear between knots,
    flat beyond the ends."""
    return np.interp(ts, knot_t, knot_off)


def estimate_offsets(laps: pd.DataFrame, tel: pd.DataFrame,
                     sf: tuple[float, float]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per driver: per-lap telemetry-minus-lap clock offsets → knots
    (t on the TELEMETRY clock, offset_s), and a summary row with the lap-start
    distance from sf before/after correction and whether it applies.

    The offset is not always constant: Austria 2026 qualifying drifts from
    −1.2 to −1.5 s and then steps to ~0, so the correction interpolates
    between per-lap knots instead of using one number per driver."""
    pts = lap_start_points(laps, tel)
    pts["d"] = np.hypot(pts["X"] - sf[0], pts["Y"] - sf[1])
    pos = _pos(tel)
    rows, knots = [], []
    for drv, lp in _timed_laps(laps).groupby("DriverNo"):
        p = pos[pos["DriverNo"] == drv]
        dpts = pts[pts["DriverNo"] == drv]
        if p.empty or dpts.empty:
            continue
        t, x, y = (p[c].to_numpy(float) for c in ("timestamp", "X", "Y"))
        lp = lp.sort_values("LapStartTime")
        q_all = lp["LapStartTime"].to_numpy(float)
        qs, offs = [], []
        for q in q_all:
            tc = _crossing_times(t, x, y, sf, q)
            if tc is not None and _trace_ok(t, x, y, tc):
                qs.append(q)
                offs.append(tc - q)
        degraded = (float(np.mean([not _trace_ok(t, x, y, q) for q in q_all]))
                    if q_all.size else 0.0)
        qs, offs = np.asarray(qs), np.asarray(offs)
        keep = _consistent(offs)
        qs, offs = qs[keep], offs[keep]
        if offs.size >= 3:      # rolling median of 3 against single-lap jitter
            sm = pd.Series(offs).rolling(3, center=True, min_periods=1).median().to_numpy()
        else:
            sm = offs
        before = dpts["d"].to_numpy(float)
        row = {"DriverNo": drv, "n_laps": int(before.size), "n_knots": int(sm.size),
               "before_m": round(float(np.median(before)) / 10, 1),
               "share_off": round(float((before > OFF_LINE_DM).mean()), 3),
               "offset_s": round(float(np.median(sm)), 3) if sm.size else np.nan,
               "offset_min_s": round(float(sm.min()), 3) if sm.size else np.nan,
               "offset_max_s": round(float(sm.max()), 3) if sm.size else np.nan,
               "after_m": np.nan, "share_off_after": np.nan,
               "degraded_share": round(degraded, 3), "apply": False}
        n_big = int((np.abs(sm) > MIN_OFFSET_S).sum())
        if (sm.size >= MIN_LAPS and n_big >= max(MIN_LAPS, 0.2 * sm.size)
                and row["share_off"] >= MIN_SHARE_OFF):
            kt = qs + sm                             # knots on the telemetry clock
            fixed = p.assign(timestamp=t - shift_at(t, kt, sm))
            after = lap_start_points(laps[laps["DriverNo"].astype(str).str.strip() == drv],
                                     fixed)
            ad = np.hypot(after["X"] - sf[0], after["Y"] - sf[1]).to_numpy(float)
            if ad.size:
                row["after_m"] = round(float(np.median(ad)) / 10, 1)
                row["share_off_after"] = round(float((ad > OFF_LINE_DM).mean()), 3)
                # the shift must actually put the laps back on the line
                row["apply"] = bool(row["share_off_after"] < 0.5 * row["share_off"]
                                    and row["after_m"] * 10 <= OFF_LINE_DM)
            if row["apply"]:
                knots.append(pd.DataFrame({"DriverNo": drv, "t_tel": np.round(kt, 3),
                                           "offset_s": np.round(sm, 3)}))
        if not row["apply"]:
            row["after_m"] = row["before_m"]
            row["share_off_after"] = row["share_off"]
        rows.append(row)
    kn = (pd.concat(knots, ignore_index=True) if knots
          else pd.DataFrame(columns=["DriverNo", "t_tel", "offset_s"]))
    return pd.DataFrame(rows), kn


# ── load-time correction ──────────────────────────────────────

@lru_cache(maxsize=1)
def _knots_table(mtime: float) -> dict[str, dict[str, tuple[np.ndarray, np.ndarray]]]:
    df = pd.read_csv(KNOTS_CSV, dtype={"DriverNo": str, "stem": str})
    out: dict[str, dict] = {}
    for (stem, drv), g in df.sort_values("t_tel").groupby(["stem", "DriverNo"]):
        out.setdefault(stem, {})[drv.strip()] = (g["t_tel"].to_numpy(float),
                                                 g["offset_s"].to_numpy(float))
    return out


def offsets_for(stem: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """{DriverNo: (knot_t, knot_offset)} for cache stem
    `season__Meeting__Session`; empty for aligned sessions or when the audit
    has not been run."""
    if not KNOTS_CSV.exists():
        return {}
    try:
        return _knots_table(KNOTS_CSV.stat().st_mtime).get(stem, {})
    except Exception as exc:  # a broken CSV must never block a load
        logging.warning("lap_sync: cannot read %s: %s", KNOTS_CSV, exc)
        return {}


def apply_offsets(tel: pd.DataFrame, stem: str) -> pd.DataFrame:
    """Shift mis-synced drivers' telemetry onto the lap clock. Returns `tel`
    itself when nothing applies, else a corrected copy. Only ever apply to a
    frame freshly read from the cache — never write the result back to it."""
    if tel.empty or not {"timestamp", "DriverNo"}.issubset(tel.columns):
        return tel
    offs = offsets_for(stem)
    if not offs:
        return tel
    tel = tel.copy()
    ts = tel["timestamp"].to_numpy(float).copy()
    drv = tel["DriverNo"].astype(str).str.strip().to_numpy()
    for d, (kt, ko) in offs.items():
        m = drv == d
        if m.any():
            ts[m] -= shift_at(ts[m], kt, ko)
    tel["timestamp"] = ts
    return tel


def read_telemetry(path: Path | str, columns: list[str] | None = None) -> pd.DataFrame:
    """pd.read_parquet for a data/sessions/*__telemetry.parquet, with the
    lap-sync correction applied. Use this instead of a raw read wherever
    telemetry is sliced by lap times."""
    path = Path(path)
    cols = None
    if columns is not None:
        cols = list(dict.fromkeys([*columns, "timestamp", "DriverNo"]))
    tel = pd.read_parquet(path, columns=cols)
    tel = apply_offsets(tel, path.name[: -len("__telemetry.parquet")])
    return tel[columns] if columns is not None else tel
