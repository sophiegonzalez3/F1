"""Derive circuit characteristics from cached telemetry instead of hand scores.

data/circuit_characteristics.csv is hand-maintained. Most of what it scores is
directly measurable from data the app already caches:

  avg speed      – mean speed over the circuit's fastest cached lap
  full throttle  – % of that lap spent at ≥ THROTTLE_THRESHOLD % throttle
  braking share  – % of that lap on the brakes (extra info column, unscored)
  lateral load   – p90 lateral acceleration (v²·curvature from smoothed X/Y)
  tyre deg       – median valid-stint deg rate (s/lap) from the circuit's race,
                   via the same pipeline the STINTS tab uses

For each circuit it picks the latest cached season, uses the highest-grip
session available (Q > SQ > FP3 > FP2 > FP1 > Sprint > Race) for the fast-lap
metrics and the Race for deg. Results go to
data/circuit_characteristics_computed.csv; app.py overlays those scores on the
manual CSV at startup (tyre difficulty stays manual — it isn't measurable).

Usage
-----
    python compute_circuit_characteristics.py            # all cached circuits
    python compute_circuit_characteristics.py --verbose  # per-lap details
"""
from __future__ import annotations

import sys
import re
import warnings
from datetime import date

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

import data_loader as dl
from config import HIST_CIRCUIT_KEY_MAP, THROTTLE_THRESHOLD
from processing import (
    clean_and_enrich_laps, flag_dirty_air, enrich_track_evolution,
    analyze_stints,
)

VERBOSE = "--verbose" in sys.argv
OUT_PATH = "data/circuit_characteristics_computed.csv"

# Highest-grip session first: the fast-lap metrics should describe the circuit
# at its quickest, which is qualifying.
SESSION_PRIORITY = ["Qualifying", "Sprint Qualifying", "Practice 3",
                    "Practice 2", "Practice 1", "Sprint", "Race"]

# Fixed score thresholds (1–4), chosen so the classic anchors land where the
# hand-scored CSV puts them (Monaco lowest speed/throttle, Monza highest, …).
THRESHOLDS = {
    # metric:            (t12, t23, t34)  -> score 1 below t12, 4 above t34
    "avg_speed_kmh":     (175, 205, 230),
    # 2026 cars spend less time flat-out (energy management), so the bands sit
    # lower than the classic 50–80% rule of thumb
    "full_throttle_pct": (45, 55, 65),
    "lat_g_p90":         (2.6, 3.3, 4.0),
    "tyre_deg_s_lap":    (0.03, 0.06, 0.10),
}
LABELS = {1: "Low", 2: "Medium", 3: "High", 4: "Very high"}

_EVENT_TO_CIRCUIT = {
    hist: fr for fr, hists in HIST_CIRCUIT_KEY_MAP.items() for hist in hists
}


def _slugify(name) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def _score(metric: str, value: float) -> int | None:
    if value is None or not np.isfinite(value):
        return None
    t12, t23, t34 = THRESHOLDS[metric]
    return 1 if value < t12 else 2 if value < t23 else 3 if value < t34 else 4


# ─────────────────────────────────────────────────────────────
# Fast-lap metrics
# ─────────────────────────────────────────────────────────────

def _fastest_lap_candidates(laps: pd.DataFrame) -> pd.DataFrame:
    """Clean flying laps, fastest first."""
    m = (
        pd.to_numeric(laps["LapTime"], errors="coerce").gt(30)
        & ~laps["IsDeleted"].fillna(False).astype(bool)
        & laps["PitIn"].isna() & laps["PitOut"].isna()
    )
    if "IsAccurate" in laps.columns:
        m &= laps["IsAccurate"].fillna(False).astype(bool)
    return laps[m].sort_values("LapTime").head(8)


def _lap_slice(tel: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
    dno   = str(row["DriverNo"]).strip()
    start = float(row["LapStartTime"])
    dur   = float(row["LapTime"])
    sub = tel[
        (tel["DriverNo"].astype(str).str.strip() == dno)
        & (tel["timestamp"] >= start) & (tel["timestamp"] <= start + dur)
    ].sort_values("timestamp")
    return sub


def _lateral_g_p90(sub: pd.DataFrame) -> float:
    """p90 lateral acceleration (in g): a_lat = v²·κ.

    Curvature is computed on the path resampled to a uniform ~8 m arc-length
    grid and then smoothed. Differentiating raw positions against *time*
    amplifies position noise quadratically (worst at low speed, where samples
    bunch up) and produced absurd 7–8 g readings even at Monaco; the
    distance parameterization makes the second derivative noise-stable.
    X/Y are in 1/10 m (FastF1); speed comes from the Speed channel."""
    if not {"X", "Y", "Speed"}.issubset(sub.columns):
        return np.nan
    d = sub.dropna(subset=["X", "Y"])
    if len(d) < 60 or d["X"].notna().mean() < 0.5:
        return np.nan
    x = d["X"].rolling(5, center=True, min_periods=1).mean().to_numpy(float) / 10.0
    y = d["Y"].rolling(5, center=True, min_periods=1).mean().to_numpy(float) / 10.0
    v = pd.to_numeric(d["Speed"], errors="coerce").ffill().to_numpy(float) / 3.6

    # cumulative arc length, then uniform resampling every ~8 m
    seg = np.hypot(np.diff(x), np.diff(y))
    s = np.concatenate([[0.0], np.cumsum(seg)])
    lap_len = s[-1]
    if lap_len < 1000:                      # not a full flying lap
        return np.nan
    s_u = np.arange(0, lap_len, 8.0)
    if len(s_u) < 80:
        return np.nan
    x_u = np.interp(s_u, s, x)
    y_u = np.interp(s_u, s, y)
    v_u = np.interp(s_u, s, v)
    # light smoothing on the resampled path (~40 m window)
    x_u = pd.Series(x_u).rolling(5, center=True, min_periods=1).mean().to_numpy()
    y_u = pd.Series(y_u).rolling(5, center=True, min_periods=1).mean().to_numpy()

    xp, yp   = np.gradient(x_u, s_u), np.gradient(y_u, s_u)
    xpp, ypp = np.gradient(xp, s_u), np.gradient(yp, s_u)
    denom = np.power(xp ** 2 + yp ** 2, 1.5)
    with np.errstate(divide="ignore", invalid="ignore"):
        kappa = np.abs(xp * ypp - yp * xpp) / denom
        a_lat = v_u ** 2 * kappa / 9.81
    a_lat = a_lat[np.isfinite(a_lat) & (v_u > 15)]
    if len(a_lat) < 40:
        return np.nan
    return float(np.percentile(a_lat, 90))


def _fast_lap_metrics(key: str) -> dict | None:
    paths = dl._cache_paths(key)
    if not (paths["laps"].exists() and paths["telemetry"].exists()):
        return None
    laps = pd.read_parquet(paths["laps"])
    cands = _fastest_lap_candidates(laps)
    if cands.empty:
        return None
    avail = pq_cols(paths["telemetry"])
    tel = pd.read_parquet(
        paths["telemetry"],
        columns=[c for c in ("timestamp", "DriverNo", "Speed", "Throttle",
                             "Brake", "X", "Y") if c in avail],
    )
    for _, row in cands.iterrows():
        sub = _lap_slice(tel, row)
        if len(sub) < 100:
            continue
        spd = pd.to_numeric(sub["Speed"], errors="coerce")
        thr = pd.to_numeric(sub["Throttle"], errors="coerce")
        brk = sub["Brake"]
        brk = (pd.to_numeric(brk, errors="coerce") > 0
               if brk.dtype != bool else brk)
        out = {
            "avg_speed_kmh":     round(float(spd.mean()), 1),
            "full_throttle_pct": round(float((thr >= THROTTLE_THRESHOLD).mean()) * 100, 1),
            "brake_pct":         round(float(brk.mean()) * 100, 1),
            "lat_g_p90":         round(_lateral_g_p90(sub), 2),
            "fast_lap":          f"{row['Driver']} {row['LapTime']:.3f}s",
        }
        if VERBOSE:
            print(f"      lap {row['Driver']} {row['LapTime']:.3f}s → {out}")
        return out
    return None


def pq_cols(path) -> list[str]:
    import pyarrow.parquet as pq
    return pq.ParquetFile(path).schema.names


# ─────────────────────────────────────────────────────────────
# Race tyre-deg metric
# ─────────────────────────────────────────────────────────────

def _race_deg_metric(key: str) -> float:
    """Median valid-stint deg rate (s/lap) via the STINTS-tab pipeline."""
    paths = dl._cache_paths(key)
    if not paths["laps"].exists():
        return np.nan
    laps = pd.read_parquet(paths["laps"])
    try:
        fl = clean_and_enrich_laps(laps)
        fl = flag_dirty_air(fl)
        fl = enrich_track_evolution(fl)
        st = analyze_stints(fl)
    except Exception as exc:
        print(f"      deg pipeline failed: {exc}")
        return np.nan
    ok = st[st["Valid_Stint"] & st["Stint_Deg_Rate"].notna()
            & st["Compound"].isin(["SOFT", "MEDIUM", "HARD"])]
    if len(ok) < 5:
        return np.nan
    return round(float(ok["Stint_Deg_Rate"].median()), 4)


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main() -> int:
    sessions = dl.list_cached_sessions()
    if not sessions:
        print("No cached sessions under data/sessions/ — nothing to compute.")
        return 1

    # circuit → {season → {session → key}}
    by_circuit: dict[str, dict[int, dict[str, str]]] = {}
    for s in sessions:
        ck = _EVENT_TO_CIRCUIT.get(_slugify(s["meeting"]))
        if ck is None:
            continue
        by_circuit.setdefault(ck, {}).setdefault(
            int(s["season"]), {})[str(s["session"])] = s["key"]

    rows = []
    for ck in sorted(by_circuit):
        season = max(by_circuit[ck])
        sess_map = by_circuit[ck][season]
        fast_key = next((sess_map[s] for s in SESSION_PRIORITY if s in sess_map), None)
        # deg: prefer the same season's race, else the newest cached race
        race_key = sess_map.get("Race")
        if race_key is None:
            for yr in sorted(by_circuit[ck], reverse=True):
                if "Race" in by_circuit[ck][yr]:
                    race_key = by_circuit[ck][yr]["Race"]
                    break
        print(f"[{ck}] season {season} · fast-lap from {fast_key} · deg from {race_key}")

        metrics = _fast_lap_metrics(fast_key) if fast_key else None
        if metrics is None:
            print("      no usable fast lap — skipped")
            continue
        deg = _race_deg_metric(race_key) if race_key else np.nan
        metrics["tyre_deg_s_lap"] = deg

        row = {"circuit_key": ck, "season": season,
               "source_session": fast_key, **metrics,
               "computed_on": date.today().isoformat()}
        for metric, (label_col, score_col) in {
            "avg_speed_kmh":     ("avg_speed_label", "avg_speed_score"),
            "full_throttle_pct": ("full_throttle_label", "full_throttle_score"),
            "lat_g_p90":         ("lateral_load_label", "lateral_load_score"),
            "tyre_deg_s_lap":    ("tyre_deg_label", "tyre_deg_score"),
        }.items():
            sc = _score(metric, row.get(metric))
            row[score_col] = sc
            row[label_col] = LABELS.get(sc, "")
        rows.append(row)
        print(f"      speed {row['avg_speed_kmh']} km/h ({row['avg_speed_score']}) · "
              f"throttle {row['full_throttle_pct']}% ({row['full_throttle_score']}) · "
              f"lat {row['lat_g_p90']}g ({row['lateral_load_score']}) · "
              f"deg {row['tyre_deg_s_lap']} s/lap ({row['tyre_deg_score']})")

    if not rows:
        print("Nothing computed.")
        return 1
    out = pd.DataFrame(rows)
    out.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {len(out)} circuits -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
