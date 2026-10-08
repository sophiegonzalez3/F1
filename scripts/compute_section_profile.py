"""Where on a lap each car is strong, by DRIVING PHASE, across a whole season
— qualifying and race pace. Feeds the SEASON tab's "Car Character" card.

WHY PHASES. Every lap is cut into GRID slices and each slice is classed by
what the reference car is DOING there — braking, cornering under load at low
or high speed, accelerating, running flat out at top speed — from its own
telemetry. A slice of Suzuka and a slice of Monza in the same phase are the
same kind of work for the car, which is what lets a team's strength in one
carry over to another.

The definitions were chosen on evidence (2026-10-08 research bench: 1,000
slices per lap, every team, scored by whether a team's pace-adjusted profile on
one random half of the tracks predicts the other half, averaged over 300
splits). Only three phases clear the 0.6 bar in 2026 qualifying, 2025
qualifying AND 2026 race pace:

    low-speed cornering   lateral load ≥ 1.5 g below 200 km/h   .84 / .63 / .68
    traction              accelerating below 200 km/h            .70 / .64 / .67
    top speed             full throttle ≥ 270 km/h, no load      .82 / .73 / .80

What failed, so nobody re-adds it:
  * corner classes by apex speed (the previous card): .62-.83 in 2026 but
    -.03 to .50 in 2025 — not a stable property across eras;
  * plain speed bands: 180-240 km/h is the MOST reliable band in 2025 and the
    least in 2026;
  * high-speed cornering (≥ 200 km/h under load): its team gaps track OVERALL
    lap pace at r ≈ 0.99 — mid/high-speed aero IS the pace, so once pace is
    removed nothing distinctive is left. It is computed (section
    "high_speed") but the card shows it as context, not as a trait;
  * braking: passes 2026 qualifying only.

Pipeline, per event:
  1. Reference = the session's fastest lap with a healthy speed channel (no
     frozen plateau), NOT the cached X/Y track line (the 2026 Suzuka line has a
     30% hole). Phase labels come from the QUALIFYING reference so a stretch of
     track carries the same label in both sessions.
  2. Every candidate lap is gated (distance within 2% of the reference;
     speed-channel plateau) and ALIGNED to the reference speed trace by a
     circular shift — lap-start timestamps can sit seconds off (Austria 2026).
  3. Time per slice from the lap's time-vs-fraction curve; summed per phase.
     Qualifying = each team's best clean lap; race = every lap of each driver's
     fastest quarter of clean green-flag laps (the zone-dominance rule), averaged
     per team.

FastF1 position X/Y are DECIMETRES (Monza's line measures ~57,600 units for a
5.76 km lap); lateral load is computed from them after converting to metres.

Output: data/section_profile.csv (session column: Qualifying / Race).

Usage
-----
    python scripts/compute_section_profile.py              # latest season, both sessions
    python scripts/compute_section_profile.py --season 2026
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

SESSIONS = Path("data/sessions")
OUT = Path("data/section_profile.csv")

GRID = 1000              # slices per lap
LAT_G = 1.5              # "cornering" = lateral load at or above this
LOW_SPEED_KMH = 200.0    # low-speed cornering / traction below this
TOP_SPEED_KMH = 270.0    # top-speed phase at or above this, full throttle
FULL_THROTTLE = 95.0     # %
BRAKE_DECEL = -6.0       # m/s² — braking when the brake is on or decel exceeds
SMOOTH_M = 40.0          # smoothing for speed-derived acceleration
CURV_M = 30.0            # smoothing for heading/curvature
PHASES = ("low_speed", "traction", "top_speed", "high_speed", "braking",
          "transition")

# Lap gates (see the research note in the module docstring)
DIST_TOL = 0.02          # integrated distance within 2% of the reference
MAX_FLAT = 6             # samples (~1.5 s) — longer = frozen speed channel
ALIGN_GRID = 2000
MAX_SHIFT = 0.10         # search ±10% of a lap
MATCH_TOL_KMH = 18.0     # mean |Δspeed| after alignment above this = reject
RACE_QUARTILE = 0.25
RACE_MIN_LAPS = 3


def _flat_run(v: np.ndarray) -> int:
    """Longest run of identical consecutive speed samples (frozen channel)."""
    if v.size < 2:
        return 0
    same = np.concatenate([[False], np.diff(v) == 0])
    best = cur = 0
    for x in same:
        cur = cur + 1 if x else 0
        best = max(best, cur)
    return best


def _lap_curve(tel: pd.DataFrame, start: float, dur: float):
    """One lap's car channel -> dict(frac, t, f, v_kmh, dist_m, window) or
    None on a dropout. frac/t are pinned to 0 and dur at the line."""
    w = tel[(tel["timestamp"] >= start) & (tel["timestamp"] <= start + dur)]
    car = w[w["Source"] == "car"].sort_values("timestamp")
    if len(car) < 50:
        return None
    tt = car["timestamp"].to_numpy(float) - start
    v = pd.to_numeric(car["Speed"], errors="coerce").fillna(0).to_numpy(float) / 3.6
    if _flat_run(v) > MAX_FLAT:
        return None
    d = np.concatenate([[0.0], np.cumsum((v[1:] + v[:-1]) / 2 * np.diff(tt))])
    if d[-1] <= 0:
        return None
    f = d / d[-1]
    return {"frac": np.concatenate([[0.0], f, [1.0]]),
            "t": np.concatenate([[0.0], tt, [dur]]),
            "f": f, "v": v * 3.6, "dist": float(d[-1]),
            "car": car, "win": w, "start": start, "dur": dur}


def _align(c: dict, ref: dict) -> float | None:
    """Circular shift (lap fraction) mapping this lap's speed trace onto the
    reference's; None when nothing matches."""
    g = np.linspace(0, 1, ALIGN_GRID, endpoint=False)
    r = np.interp(g, ref["f"], ref["v"])
    lap = np.interp(g, c["f"], c["v"])
    best, best_err = 0, np.inf
    for k in range(-int(MAX_SHIFT * ALIGN_GRID), int(MAX_SHIFT * ALIGN_GRID) + 1):
        err = np.mean(np.abs(np.roll(lap, k) - r))
        if err < best_err:
            best, best_err = k, err
    return None if best_err > MATCH_TOL_KMH else best / ALIGN_GRID


def _slice_times(c: dict, shift: float) -> np.ndarray:
    """Time spent in each of GRID track slices (track fraction = the lap's own
    fraction + shift, circular)."""
    edges = np.linspace(0, 1, GRID + 1) - shift
    n = np.floor(edges)
    T = np.interp(edges - n, c["frac"], c["t"]) + n * c["dur"]
    return np.diff(T)


def _phases(ref: dict) -> np.ndarray:
    """Phase label per slice, from the reference lap's own telemetry."""
    centre = (np.arange(GRID) + 0.5) / GRID
    car, win = ref["car"], ref["win"]
    spd = np.interp(centre, ref["f"], ref["v"])
    thr = np.interp(centre, ref["f"],
                    pd.to_numeric(car["Throttle"], errors="coerce").fillna(0).to_numpy(float))
    brk = np.interp(centre, ref["f"], car["Brake"].astype(float).to_numpy())
    ds = ref["dist"] / GRID
    v = spd / 3.6
    k = max(1, int(SMOOTH_M / ds))
    vs = pd.Series(v).rolling(k, center=True, min_periods=1).mean().to_numpy()
    along = np.gradient(vs ** 2 / 2, ds)                     # m/s²
    lat = np.zeros(GRID)
    pos = win[(win["Source"] == "pos") & (win["X"].abs() + win["Y"].abs() > 0)]
    if len(pos) > 50:
        tcar = car["timestamp"].to_numpy(float) - ref["start"]
        fpos = np.interp(pos["timestamp"].to_numpy(float) - ref["start"], tcar, ref["f"])
        x = np.interp(centre, fpos, pos["X"].to_numpy(float) / 10.0)   # dm -> m
        y = np.interp(centre, fpos, pos["Y"].to_numpy(float) / 10.0)
        kk = max(2, int(CURV_M / ds))
        xs = pd.Series(x).rolling(kk, center=True, min_periods=1).mean().to_numpy()
        ys = pd.Series(y).rolling(kk, center=True, min_periods=1).mean().to_numpy()
        hd = np.unwrap(np.arctan2(np.gradient(ys), np.gradient(xs)))
        curv = pd.Series(np.gradient(hd) / ds).rolling(
            kk, center=True, min_periods=1).mean().to_numpy()
        lat = v ** 2 * np.abs(curv) / 9.81
    lab = np.array(["transition"] * GRID, dtype=object)
    lab[(brk > 0.5) | (along < BRAKE_DECEL)] = "braking"
    free = lab == "transition"
    corner = free & (lat >= LAT_G)
    lab[corner & (spd < LOW_SPEED_KMH)] = "low_speed"
    lab[corner & (spd >= LOW_SPEED_KMH)] = "high_speed"
    free = lab == "transition"
    lab[free & (thr >= FULL_THROTTLE) & (spd >= TOP_SPEED_KMH)] = "top_speed"
    lab[free & (spd < LOW_SPEED_KMH) & (along > 0)] = "traction"
    return lab


def _clean_laps(laps: pd.DataFrame) -> pd.DataFrame:
    l = laps[laps["LapTime"].notna() & ~laps["IsDeleted"].astype(bool)
             & laps["PitOut"].isna() & laps["PitIn"].isna()]
    return l.sort_values("LapTime")


def _race_laps(laps: pd.DataFrame) -> pd.DataFrame:
    """Clean green-flag race laps (no lap 1, no pit in/out, accurate), then
    each driver's fastest RACE_QUARTILE."""
    l = laps[laps["LapTime"].notna() & ~laps["IsDeleted"].astype(bool)
             & laps["PitOut"].isna() & laps["PitIn"].isna()
             & laps["IsAccurate"].astype(bool) & (laps["LapNo"] > 1)
             & (laps["TrackStatus"].astype(str) == "1")]
    keep = []
    for _, g in l.groupby("Driver"):
        if len(g) >= RACE_MIN_LAPS:
            g = g.sort_values("LapTime")
            keep.append(g.head(max(RACE_MIN_LAPS, int(round(len(g) * RACE_QUARTILE)))))
    return pd.concat(keep) if keep else l.iloc[0:0]


def _load(season: int, event: str, session: str):
    stem = f"{season}__{event.replace(' ', '_')}__{session}"
    lp, tp = SESSIONS / f"{stem}__laps.parquet", SESSIONS / f"{stem}__telemetry.parquet"
    if not (lp.exists() and tp.exists()):
        return None
    laps = pd.read_parquet(lp)
    tel = pd.read_parquet(tp, columns=["timestamp", "Speed", "Source", "DriverNo",
                                       "Throttle", "Brake", "X", "Y"])
    tel["DriverNo"] = tel["DriverNo"].astype(str).str.strip()
    return laps, {k: g for k, g in tel.groupby("DriverNo")}


def _curve(pools, b):
    pool = pools.get(str(b.DriverNo).strip())
    return None if pool is None else _lap_curve(pool, float(b.LapStartTime),
                                                float(b.LapTime))


def _reference(laps, pools, n: int = 30):
    """The fastest clean lap whose integrated distance agrees with the MEDIAN
    of the session's clean laps. Taking simply the fastest healthy-looking lap
    picked a Sepang 2026 race lap that integrated to 5,268 m against ~5,450 m
    for everyone else — a dropout the plateau check missed — and then every
    good lap failed the distance gate against it."""
    curves = [c for c in (_curve(pools, b) for b in
                          _clean_laps(laps).head(n).itertuples()) if c is not None]
    if not curves:
        return None
    med = float(np.median([c["dist"] for c in curves]))
    for c in curves:                     # already fastest-first
        if abs(c["dist"] / med - 1) <= DIST_TOL / 2:
            return c
    return None


def build(season: int) -> pd.DataFrame:
    rows = []
    cal = pd.read_csv("data/season_calendar.csv")
    cal = cal[cal["season"] == season].sort_values("round")
    for r in cal.itertuples():
        q = _load(season, r.event, "Qualifying")
        if q is None:
            continue
        qref = _reference(*q)
        if qref is None:
            print(f"  R{int(r.round):02d} {r.event}: no clean qualifying reference - skipped")
            continue
        labels = _phases(qref)
        share = {p: float((labels == p).mean()) for p in PHASES}
        for session in ("Qualifying", "Race"):
            src = q if session == "Qualifying" else _load(season, r.event, "Race")
            if src is None:
                continue
            laps, pools = src
            ref = qref if session == "Qualifying" else _reference(laps, pools)
            if ref is None:
                continue
            per = []
            if session == "Qualifying":
                groups = ((t, tl[tl["LapTime"] <= tl["LapTime"].min() * 1.01])
                          for t, tl in _clean_laps(laps).groupby("Team"))
            else:
                groups = _race_laps(laps).groupby("Team")
            for team, tl in groups:
                acc, n, lap_sum = np.zeros(GRID), 0, 0.0
                for b in tl.itertuples():
                    c = _curve(pools, b)
                    if c is None or abs(c["dist"] / ref["dist"] - 1) > DIST_TOL:
                        continue
                    sh = _align(c, ref)
                    if sh is None:
                        continue
                    acc += _slice_times(c, sh); n += 1; lap_sum += float(b.LapTime)
                    if session == "Qualifying":
                        break          # one lap: the team's best clean one
                if n and (session == "Qualifying" or n >= RACE_MIN_LAPS):
                    per.append({"team": team, "n": n, "lap": lap_sum / n,
                                **{p: float(acc[labels == p].sum() / n)
                                   for p in PHASES}})
            if len(per) < 6:
                print(f"  R{int(r.round):02d} {r.event} {session}: only "
                      f"{len(per)} teams - skipped")
                continue
            d = pd.DataFrame(per)
            for p in PHASES:
                med = float(d[p].median())
                for x in d.itertuples():
                    rows.append({"season": season, "round": int(r.round),
                                 "event": r.event, "session": session,
                                 "team": x.team, "lap_s": x.lap, "n_laps": x.n,
                                 "section": p, "team_s": getattr(x, p),
                                 "median_s": med, "lap_share": round(share[p], 4)})
            print(f"  R{int(r.round):02d} {r.event} {session}: {len(d)} teams · "
                  + ", ".join(f"{p} {share[p]:.0%}" for p in PHASES))
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int)
    a = ap.parse_args()
    if a.season is None:
        a.season = int(pd.read_csv("data/season_calendar.csv")["season"].max())
    print(f"Section (phase) profile, {a.season}:")
    new = build(a.season)
    if OUT.exists():
        old = pd.read_csv(OUT)
        if "session" in old.columns:
            new = pd.concat([old[old["season"] != a.season], new], ignore_index=True)
    new.to_csv(OUT, index=False)
    print(f"{len(new[new['season'] == a.season])} row(s) -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
