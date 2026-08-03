"""Build the per-event CAR CONCEPT profile -> data/car_profile.csv.

What this is
------------
"Which car is quicker" is answered by team_pace_by_event.csv. This answers the
next question — *why*. It decomposes each team's weekend into the physical
traits that produce lap time, so you can tell a low-drag rocket from a
downforce monster from a car that simply looks after its tyres.

One row per (season, round, event, team). Every axis is CENTRED ON THE FIELD
that weekend, because all of them are dominated by the circuit otherwise: a
Monza speed trap reads 340 km/h and a Monaco one 290, and no team property
survives that. Centring asks "versus the other cars that were there", which is
the only comparison that carries across a season.

Axes
----
  straight_kmh   Speed trap (Speed_ST) on the driver's three quickest laps,
                 team = mean of its two cars, minus the field mean. The public
                 proxy for engine + low drag. Solid measurement, but it is a
                 SETUP choice as much as a car property — teams trade wing for
                 straight-line speed circuit by circuit.
  corner_pct     Apex (minimum) speed at every medium/fast corner on the best
                 lap, each corner expressed vs the field's mean at THAT corner,
                 then averaged. Relative-per-corner matters: averaging raw apex
                 speeds lets the corner-to-corner speed scale bury the
                 car-to-car difference. High = carries more speed through
                 corners = more downforce (or more front-end confidence).
  fade_pct       Share of pinned-throttle (>98%) samples where the car is
                 DECELERATING — the signature of a car that has stopped pulling
                 near the top of its range. PROXY: public telemetry carries no
                 battery-state channel, so this cannot separate "out of
                 deployment" from "hit its drag limit". Shipped as top-end
                 fade, which is what it measures.
  save_pct       Coasting share (throttle <5%, off the brakes) in the race
                 minus the same in qualifying. Qualifying is the max-attack
                 baseline, so the difference is deliberate lift-and-coast —
                 fuel and energy management. PROXY.
  deg_spl        Mean deviation from the pooled field degradation curve at
                 equal tyre age (s/lap; negative = kinder to its tyres),
                 averaged over compounds. Age- and compound-matched, so it is
                 not merely "who ran longer stints". Split-half reliability
                 0.69 — the weakest of the five, because tyre behaviour tracks
                 temperature and compound as well as the car.

                 This one is fragile to the enrichment order: the race laps
                 MUST go through flag_perturbed_laps before
                 enrich_track_evolution, or the fit includes safety-car laps
                 and the measurement collapses (reliability 0.17 — i.e. pure
                 noise). build_event() does this; do not reorder it.

Reliability is deliberately NOT here: it comes free from the results archive
and data/pu_penalties.csv at render time, and needs no telemetry pass.

Cost
----
Reads the cached Qualifying + Race telemetry for every event of the season
(~1.5 M samples each), so it is the slowest job in the maintenance chain after
compute_mistakes.py. Telemetry is indexed by driver once per session rather
than rescanned per lap, which is what keeps it to ~1 min per event.

Usage
-----
    python scripts/compute_car_profile.py                 # every cached season
    python scripts/compute_car_profile.py --season 2026
    python scripts/compute_car_profile.py --season 2026 --event Hungarian
"""
from __future__ import annotations

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import glob
import re
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from f1lib.processing import (
    clean_and_enrich_laps, field_deg_curves,
    flag_dirty_air, flag_perturbed_laps, enrich_track_evolution,
)

OUT_PATH = Path("data/car_profile.csv")
SESSIONS_DIR = Path("data/sessions")
TRACK_MAPS = Path("data/track_maps")

# corners slower than this are traction/braking-limited rather than
# downforce-limited — the season-fixed slow/medium boundary from
# scripts/compute_corner_classes.py (data/corner_speed_classes.json)
SLOW_MAX_KMH = 146.0
APEX_BAND_M = 60.0          # ± window around a corner when hunting the apex
MIN_STRAIGHT_M = 300.0      # shorter flat-out runs aren't straights
# Max slope standard error (s/lap) for a degradation fit to be believed —
# the same gate tabs/stints.py puts on its Degradation Rate bars.
MAX_DEG_SE = 0.5

TEAM_CANON = {
    "RB": "Racing Bulls", "AlphaTauri": "Racing Bulls",
    "Kick Sauber": "Sauber", "Alfa Romeo": "Sauber",
    "Alfa Romeo Racing": "Sauber",
}


def canon(team) -> str:
    return TEAM_CANON.get(str(team).strip(), str(team).strip())


# ─────────────────────────────────────────────────────────────
# telemetry helpers
# ─────────────────────────────────────────────────────────────

def _index_telemetry(tel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split the session telemetry by driver ONCE. Filtering a 1.5 M-row frame
    per lap is what makes the naive version unusable; this makes each lap
    lookup a slice of a few thousand rows."""
    if tel is None or tel.empty:
        return {}
    t = tel.copy()
    t["_dno"] = t["DriverNo"].astype(str).str.strip()
    return {d: g.sort_values("timestamp") for d, g in t.groupby("_dno")}


def _lap_telemetry(by_drv: dict, row) -> pd.DataFrame | None:
    """One lap's telemetry with Distance integrated from speed — the same
    quantity FastF1's add_distance() produces, and the same one tabs/telemetry
    plots against."""
    g = by_drv.get(str(row["DriverNo"]).strip())
    if g is None:
        return None
    start = pd.to_numeric(row.get("LapStartTime"), errors="coerce")
    dur = pd.to_numeric(row.get("LapTime_s"), errors="coerce")
    if not (np.isfinite(start) and np.isfinite(dur)):
        return None
    ts = g["timestamp"].to_numpy(float)
    lo, hi = np.searchsorted(ts, start), np.searchsorted(ts, start + dur)
    if hi - lo < 50:
        return None
    t = g.iloc[lo:hi].copy()
    tr = (t["timestamp"] - start).to_numpy(float)
    sp = pd.to_numeric(t["Speed"], errors="coerce").fillna(0).to_numpy(float) / 3.6
    t["Distance"] = np.concatenate(
        [[0.0], np.cumsum((sp[1:] + sp[:-1]) / 2 * np.diff(tr))])
    return t


def _best_laps(fl: pd.DataFrame) -> pd.DataFrame:
    v = fl[fl["ValidLap"] & fl["LapTime_s"].notna()]
    if v.empty:
        return v
    return v.loc[v.groupby("Driver_Short")["LapTime_s"].idxmin()]


# ─────────────────────────────────────────────────────────────
# axes
# ─────────────────────────────────────────────────────────────

def straight_speed(fl: pd.DataFrame) -> pd.Series:
    """Per driver: median of their three highest speed-trap readings — three,
    not one, so a single tow doesn't set the number."""
    v = fl[fl["Speed_ST"].notna()]
    out = {}
    for drv, g in v.groupby("Driver_Short"):
        top = g["Speed_ST"].nlargest(3)
        if len(top):
            out[drv] = float(top.median())
    return pd.Series(out, dtype=float)


def corner_speed(fl: pd.DataFrame, by_drv: dict,
                 corners: pd.DataFrame) -> pd.Series:
    """Mean per-corner apex speed vs the field, medium and fast corners only."""
    if corners is None or corners.empty or "Distance" not in corners.columns:
        return pd.Series(dtype=float)
    cd = corners["Distance"].to_numpy(float)
    cd = cd[np.isfinite(cd)]
    if cd.size < 3 or cd.max() <= 0:
        return pd.Series(dtype=float)
    apex = {}
    for _, row in _best_laps(fl).iterrows():
        t = _lap_telemetry(by_drv, row)
        if t is None:
            continue
        d = t["Distance"].to_numpy(float)
        sp = pd.to_numeric(t["Speed"], errors="coerce").to_numpy(float)
        if d[-1] <= 0:
            continue
        # the corner table's Distance is on the reference line; a driver's
        # integrated distance differs by a percent or two, so rescale rather
        # than assume they share an origin
        scale = d[-1] / cd.max()
        vals = []
        for c in cd:
            m = np.abs(d - c * scale) <= APEX_BAND_M
            vals.append(float(np.nanmin(sp[m])) if m.any() else np.nan)
        apex[row["Driver_Short"]] = vals
    if not apex:
        return pd.Series(dtype=float)
    A = pd.DataFrame(apex).T
    field = A.mean(axis=0)
    keep = field >= SLOW_MAX_KMH
    if keep.sum() < 3:                       # a street circuit with no fast corners
        keep = field.notna()
    if keep.sum() < 1:
        return pd.Series(dtype=float)
    rel = (A.loc[:, keep].div(field[keep], axis=1) - 1) * 100
    return rel.mean(axis=1)


def top_end_fade(fl: pd.DataFrame, by_drv: dict) -> pd.Series:
    """Share of pinned-throttle samples where the car is DECELERATING.

    The signature of a car that has stopped pulling near the top of its range,
    whether because the electrical deployment has run out or because it has
    simply hit its drag limit. Those two causes cannot be separated from public
    telemetry — there is no battery-state channel — so this ships as "top-end
    fade", which is what it demonstrably measures, rather than as an ERS
    number it cannot honestly claim to be.

    An earlier version took peak-minus-end speed over the longest flat-out run.
    That was stable but correlated -0.31 with race pace, i.e. it mostly
    re-measured "is this car fast". Requiring throttle >98% and counting
    falling samples cuts that to -0.25 while keeping split-half reliability at
    0.84, so it is the more specific of the two.
    """
    out = {}
    for _, row in _best_laps(fl).iterrows():
        t = _lap_telemetry(by_drv, row)
        if t is None:
            continue
        sp = pd.to_numeric(t["Speed"], errors="coerce").to_numpy(float)
        th = pd.to_numeric(t["Throttle"], errors="coerce").fillna(0).to_numpy(float)
        br = t["Brake"].to_numpy(bool) if "Brake" in t.columns else np.zeros(len(t), bool)
        go = (th > 98) & (~br)
        if go.sum() < 20:
            continue
        falling = np.diff(sp) < 0
        g = go[1:]
        if g.sum() < 10:
            continue
        out[row["Driver_Short"]] = float(falling[g].mean()) * 100
    return pd.Series(out, dtype=float)


def coast_share(fl: pd.DataFrame, by_drv: dict, n_laps: int = 8) -> pd.Series:
    """Share of the lap off both pedals, median over the driver's quickest
    clean laps (quickest, so it reflects intent rather than traffic)."""
    v = fl[fl["ValidLap"] & fl["LapTime_s"].notna()]
    out = {}
    for drv, g in v.groupby("Driver_Short"):
        shares = []
        for _, row in g.nsmallest(min(n_laps, len(g)), "LapTime_s").iterrows():
            t = _lap_telemetry(by_drv, row)
            if t is None:
                continue
            th = pd.to_numeric(t["Throttle"], errors="coerce").fillna(0).to_numpy()
            br = t["Brake"].to_numpy(bool) if "Brake" in t.columns else np.zeros(len(t), bool)
            shares.append(float(((th < 5) & ~br).mean()) * 100)
        if shares:
            out[drv] = float(np.median(shares))
    return pd.Series(out, dtype=float)


def deg_dev(rf: pd.DataFrame) -> pd.Series:
    """Mean deviation from the pooled field degradation curve at equal tyre
    age, averaged over compounds (s/lap; negative = kinder to its tyres).

    Estimator choice was settled by split-half reliability over the 2026
    season (average the odd rounds and the even rounds, then correlate):
    per-stint slopes scored -0.04 — pure noise, exactly as
    field_deg_curves' own docstring warns — while this pooled, age-matched
    deviation scores 0.69 and is a usable season trait.

    Caller contract: `rf` must already have been through flag_perturbed_laps
    AND flag_dirty_air AND enrich_track_evolution, in that order. Skipping the
    perturbed-lap flag lets safety-car laps into the curve fit and drops the
    reliability from 0.69 back to 0.17.
    """
    devs = []
    for cmp in ("SOFT", "MEDIUM", "HARD"):
        try:
            res = field_deg_curves(rf, cmp)
        except Exception:
            continue
        if not res or "driver_dev" not in res:
            continue
        d = res["driver_dev"]
        if d is None or d.empty or "Avg_Dev_s" not in d.columns:
            continue
        devs.append(d[["Team", "Avg_Dev_s"]])
    if not devs:
        return pd.Series(dtype=float)
    out = pd.concat(devs).groupby("Team")["Avg_Dev_s"].mean()
    out.index = [canon(t) for t in out.index]
    return out


# ─────────────────────────────────────────────────────────────
# per-event assembly
# ─────────────────────────────────────────────────────────────

def _to_team(series: pd.Series, fl: pd.DataFrame) -> pd.Series:
    """Driver-indexed → team mean (a team is its two cars, averaged)."""
    if series.empty:
        return series
    tm = fl.drop_duplicates("Driver_Short").set_index("Driver_Short")["Team"]
    df = pd.DataFrame({"v": series}).join(tm)
    df["Team"] = df["Team"].map(canon)
    return df.dropna(subset=["Team"]).groupby("Team")["v"].mean()


def _centre(s: pd.Series) -> pd.Series:
    """Versus the field that weekend — see the module docstring."""
    return s - s.mean() if len(s) else s


def _corner_table(season: int, slug: str) -> pd.DataFrame | None:
    for suffix in ("Q", "FP2", "FP1", "FP3", "R"):
        p = TRACK_MAPS / f"{season}_{slug}_{suffix}_corners.parquet"
        if p.exists():
            try:
                return pd.read_parquet(p)
            except Exception:
                continue
    return None


def _load(season: int, event_file: str, kind: str):
    lp = SESSIONS_DIR / f"{season}__{event_file}__{kind}__laps.parquet"
    tp = SESSIONS_DIR / f"{season}__{event_file}__{kind}__telemetry.parquet"
    if not lp.exists():
        return None, None
    try:
        fl = clean_and_enrich_laps(pd.read_parquet(lp))
    except Exception as exc:
        print(f"    {kind}: lap pipeline failed ({exc})")
        return None, None
    tel = None
    if tp.exists():
        try:
            tel = pd.read_parquet(tp)
        except Exception as exc:
            print(f"    {kind}: telemetry unreadable ({exc})")
    return fl, tel


def build_event(season: int, event_file: str, event_name: str) -> pd.DataFrame:
    slug = event_file.lower()
    corners = _corner_table(season, slug)

    qf, qtel = _load(season, event_file, "Qualifying")
    rf, rtel = _load(season, event_file, "Race")
    if rf is not None and not rf.empty:
        # field_deg_curves wants the corrected lap column and clean-air flags;
        # perturbed laps must be flagged BEFORE the evolution fit or it warns
        # and fits on safety-car laps too
        try:
            rf = enrich_track_evolution(flag_dirty_air(flag_perturbed_laps(rf)))
        except Exception as exc:
            print(f"    race enrichment partial ({exc})")
    if qf is None and rf is None:
        return pd.DataFrame()

    cols: dict[str, pd.Series] = {}
    coast_q = pd.Series(dtype=float)

    if qf is not None and not qf.empty:
        cols["straight_kmh"] = _centre(_to_team(straight_speed(qf), qf))
        if qtel is not None and not qtel.empty:
            by = _index_telemetry(qtel)
            cols["corner_pct"] = _centre(_to_team(corner_speed(qf, by, corners), qf))
            cols["fade_pct"] = _centre(_to_team(top_end_fade(qf, by), qf))
            coast_q = _to_team(coast_share(qf, by), qf)

    if rf is not None and not rf.empty:
        cols["deg_spl"] = _centre(deg_dev(rf))
        if rtel is not None and not rtel.empty and len(coast_q):
            coast_r = _to_team(coast_share(rf, _index_telemetry(rtel)), rf)
            common = coast_r.index.intersection(coast_q.index)
            if len(common):
                cols["save_pct"] = _centre(coast_r[common] - coast_q[common])

    cols = {k: v for k, v in cols.items() if len(v)}
    if not cols:
        return pd.DataFrame()
    out = pd.DataFrame(cols)
    out.index.name = "team"
    out = out.reset_index()
    out.insert(0, "event", event_name)
    out.insert(0, "season", season)
    return out


# ─────────────────────────────────────────────────────────────
# discovery / main
# ─────────────────────────────────────────────────────────────

def cached_events(season: int) -> list[tuple[str, str]]:
    """(file_stem, pretty_name) for every event with cached Qualifying laps."""
    out = []
    for p in sorted(SESSIONS_DIR.glob(f"{season}__*__Qualifying__laps.parquet")):
        stem = p.name.split("__")[1]
        out.append((stem, stem.replace("_", " ")))
    return out


def _round_map(season: int) -> dict[str, int]:
    p = Path("data/historical_results/quali_results_all.parquet")
    if not p.exists():
        return {}
    try:
        q = pd.read_parquet(p)
    except Exception:
        return {}
    q = q[q["season"] == season]
    return {str(r.event_name): int(r.round_number)
            for r in q.drop_duplicates("event_name").itertuples()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, action="append")
    ap.add_argument("--event", help="substring filter on the event name")
    args = ap.parse_args()

    seasons = args.season
    if not seasons:
        seasons = sorted({int(p.name.split("__")[0])
                          for p in SESSIONS_DIR.glob("*__*__Qualifying__laps.parquet")})
    if not seasons:
        print("No cached qualifying sessions found under data/sessions/.")
        return 1

    frames = []
    for season in seasons:
        rounds = _round_map(season)
        evs = cached_events(season)
        if args.event:
            evs = [e for e in evs if args.event.lower() in e[0].lower()]
        print(f"[{season}] {len(evs)} cached event(s)")
        for stem, name in evs:
            df = build_event(season, stem, name)
            if df.empty:
                print(f"  {name}: nothing computable")
                continue
            df["round"] = df["event"].map(
                lambda e: rounds.get(e, rounds.get(e + " Grand Prix", np.nan)))
            got = [c for c in ("straight_kmh", "corner_pct", "fade_pct",
                               "save_pct", "deg_spl") if c in df.columns]
            print(f"  {name}: {len(df)} teams · {', '.join(got)}")
            frames.append(df)

    if not frames:
        print("Nothing built.")
        return 1
    out = pd.concat(frames, ignore_index=True)
    # keep a stable column order regardless of which axes each event produced
    order = ["season", "round", "event", "team", "straight_kmh", "corner_pct",
             "fade_pct", "save_pct", "deg_spl"]
    for c in order:
        if c not in out.columns:
            out[c] = np.nan
    out = out[order].sort_values(["season", "round", "team"])
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {len(out)} rows -> {OUT_PATH}")
    for c in order[4:]:
        print(f"  {c:<14} {out[c].notna().sum():4d} values")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
