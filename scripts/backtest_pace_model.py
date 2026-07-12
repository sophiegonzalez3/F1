"""Backtest the progressive pace model against actual weekend outcomes.

For every event with practice data cached (data/sessions or the laps-only
backfill in data/sessions_lite), this replays the weekend: freezes the
model's prediction at the prior and after each practice session, then scores
those predictions against what actually happened —

  onelap   → team qualifying gap to pole   (quali_gap_pct, results archive)
  longrun  → team race-pace gap to best     (race_pace_gap_pct, cached races)

both from data/team_pace_by_event.csv. Everything is compared in
mean-centered gap space (each set minus its own mean) so predicted gaps to
the FIELD MEAN and archive gaps to pole/best live on one scale.

Metrics per (era, stage, kind)
------------------------------
  MAE       mean absolute error, % (lower better)
  Spearman  rank correlation predicted vs actual (higher better) — the
            "did we get the ORDER right" score, which is what a preview cares
            about most
  n         events scored

Baselines the model must beat
-----------------------------
  prior      season-form only, no practice used (the "before FP1" column)
  raw-FP     the latest practice session's measurement taken literally, with
             no prior and no cross-session blending — "just read the timing
             screen". If the model can't beat this, the machinery adds nothing.

Usage
-----
    python scripts/backtest_pace_model.py                 # all cached events
    python scripts/backtest_pace_model.py --seasons 2024 2025
    python scripts/backtest_pace_model.py --tune          # grid-search base noise on
                                                  # 2024, validate on 2025
"""
from __future__ import annotations

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import itertools
import logging
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import f1lib.data_loader as dl
from f1lib.config import SESSIONS_DIR, SESSIONS_LITE_DIR
from f1lib.pace_features import event_measurements, PRACTICE_SESSIONS
from f1lib.pace_model import PaceModel, era_of

OUT = Path("data/backtest_pace_model.csv")
TARGET = {"onelap": "quali_gap_pct", "longrun": "race_pace_gap_pct"}


# ─────────────────────────────────────────────────────────────
# Which events can we replay?
# ─────────────────────────────────────────────────────────────

def _has_practice(season: int, event: str) -> bool:
    for base in (Path(SESSIONS_DIR), Path(SESSIONS_LITE_DIR)):
        for sess in PRACTICE_SESSIONS:
            key = dl._session_key(str(season), event, sess)
            if (base / f"{key}__laps.parquet").exists():
                return True
    return False


def backtestable_events(model: PaceModel, seasons: list[int]
                        ) -> list[tuple[int, str, int]]:
    out = []
    for season in seasons:
        s = model.pace[model.pace["season"] == season]
        for event in s["event"].unique():
            if _has_practice(season, event):
                out.append((season, event, int(
                    s[s["event"] == event]["round"].iloc[0])))
    return out


# ─────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────

def _actual(model: PaceModel, season: int, event: str,
            kind: str) -> pd.Series:
    """Actual outcome per team, mean-centered. Empty if unavailable."""
    col = TARGET[kind]
    s = model.pace[(model.pace["season"] == season)
                   & (model.pace["event"] == event)]
    a = s.dropna(subset=[col]).set_index("team")[col]
    return a - a.mean() if len(a) >= 4 else pd.Series(dtype=float)


def _score(pred: pd.DataFrame, actual: pd.Series, kind: str) -> dict | None:
    """MAE + Spearman for one prediction (team, kind, mean) vs actual."""
    p = pred[pred["kind"] == kind].set_index("team")["mean"]
    common = p.index.intersection(actual.index)
    if len(common) < 4:
        return None
    pv = (p[common] - p[common].mean()).values
    av = (actual[common] - actual[common].mean()).values
    rho = spearmanr(pv, av).correlation if len(common) > 2 else np.nan
    return {"mae": float(np.mean(np.abs(pv - av))),
            "rho": float(rho), "n_teams": len(common)}


def _raw_fp_prediction(meas: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Latest practice session's measurement of `kind`, taken literally."""
    mk = meas[meas["kind"] == kind]
    for sess in reversed(PRACTICE_SESSIONS):
        m = mk[mk["session"] == sess]
        if not m.empty:
            return pd.DataFrame({"team": m["team"], "kind": kind,
                                 "mean": m["gap_pct"].values})
    return pd.DataFrame(columns=["team", "kind", "mean"])


def backtest(model: PaceModel, seasons: list[int],
             verbose: bool = True) -> pd.DataFrame:
    events = backtestable_events(model, seasons)
    rows = []
    for season, event, round_ in events:
        meas, _ = event_measurements(season, event)
        if meas is None or meas.empty:
            continue
        stages = model.predict_weekend(season, event,
                                       measurements=meas, round_=round_)
        for kind in ("onelap", "longrun"):
            actual = _actual(model, season, event, kind)
            if actual.empty:
                continue
            for stage_name, st in stages.items():
                sc = _score(st, actual, kind)
                if sc:
                    rows.append({"season": season, "era": era_of(season),
                                 "event": event, "round": round_,
                                 "kind": kind, "stage": stage_name, **sc})
            # raw-FP baseline (only meaningful as an end-of-practice read)
            raw = _raw_fp_prediction(meas, kind)
            if not raw.empty:
                sc = _score(raw, actual, kind)
                if sc:
                    rows.append({"season": season, "era": era_of(season),
                                 "event": event, "round": round_,
                                 "kind": kind, "stage": "raw-FP", **sc})
        if verbose:
            print(f"  scored {season} {event}", flush=True)
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────

_STAGE_ORDER = ["prior", "after FP1", "after FP2", "after FP3",
                "after SprintQuali", "after Sprint", "raw-FP"]


def summarize(bt: pd.DataFrame) -> pd.DataFrame:
    if bt.empty:
        return bt
    g = (bt.groupby(["era", "kind", "stage"])
         .agg(mae=("mae", "mean"), rho=("rho", "mean"), n=("mae", "size"))
         .reset_index())
    g["stage"] = pd.Categorical(g["stage"], _STAGE_ORDER, ordered=True)
    return g.sort_values(["era", "kind", "stage"]).reset_index(drop=True)


def print_summary(bt: pd.DataFrame) -> None:
    s = summarize(bt)
    if s.empty:
        print("No events scored — is any practice data cached?")
        return
    for (era, kind), g in s.groupby(["era", "kind"]):
        print(f"\n=== {era}  ·  {kind}  "
              f"({int(g['n'].max())} events) ===")
        print(f"  {'stage':<12}{'MAE %':>9}{'Spearman':>11}{'n':>6}")
        for _, r in g.iterrows():
            print(f"  {r['stage']:<12}{r['mae']:>9.3f}{r['rho']:>11.3f}"
                  f"{int(r['n']):>6}")
    paired_summary(bt)


def paired_summary(bt: pd.DataFrame) -> None:
    """Prior vs the final practice read, scored on the SAME events only, so
    the 'practice helps' claim isn't an artifact of varying coverage. The
    final read = the latest non-raw stage that exists for that event."""
    stage_rank = {s: i for i, s in enumerate(_STAGE_ORDER) if s != "raw-FP"}
    rows = []
    for (era, kind), g in bt[bt["stage"] != "raw-FP"].groupby(["era", "kind"]):
        for event, ge in g.groupby("event"):
            prior = ge[ge["stage"] == "prior"]
            practiced = ge[ge["stage"] != "prior"]
            if prior.empty or practiced.empty:
                continue
            final = practiced.loc[[practiced["stage"].map(stage_rank).idxmax()]]
            rows.append({"era": era, "kind": kind,
                         "mae_prior": prior["mae"].iloc[0],
                         "mae_final": final["mae"].iloc[0],
                         "rho_prior": prior["rho"].iloc[0],
                         "rho_final": final["rho"].iloc[0]})
    pf = pd.DataFrame(rows)
    if pf.empty:
        return
    print("\n-- PAIRED: prior vs final practice read (same events) --")
    print(f"  {'era':<15}{'kind':<9}{'MAE prior>final':>18}"
          f"{'rho prior>final':>18}{'n':>5}")
    for (era, kind), g in pf.groupby(["era", "kind"]):
        print(f"  {era:<15}{kind:<9}"
              f"{g['mae_prior'].mean():>8.3f}>{g['mae_final'].mean():<8.3f}"
              f"{g['rho_prior'].mean():>8.3f}>{g['rho_final'].mean():<8.3f}"
              f"{len(g):>5}")


# ─────────────────────────────────────────────────────────────
# Tuning: grid-search base noise on 2024, validate on 2025
# ─────────────────────────────────────────────────────────────

def tune(model_path=None) -> None:
    onelap_grid = [0.25, 0.35, 0.5]
    longrun_grid = [0.35, 0.5, 0.7]
    print("Grid-searching base-noise on 2024 (train) → 2025 (validate)…\n")
    best = None
    for o1, o2, o3, l1, l2, l3 in itertools.product(
            onelap_grid, onelap_grid, onelap_grid,
            longrun_grid, longrun_grid, longrun_grid):
        bn = {("onelap", "Practice 1"): o1, ("onelap", "Practice 2"): o2,
              ("onelap", "Practice 3"): o3, ("longrun", "Practice 1"): l1,
              ("longrun", "Practice 2"): l2, ("longrun", "Practice 3"): l3}
        m = PaceModel(base_noise=bn)
        bt = backtest(m, [2024], verbose=False)
        fp3 = bt[(bt["stage"] == "after FP3")]
        if fp3.empty:
            continue
        score = fp3["mae"].mean() - 0.5 * fp3["rho"].mean()  # low MAE, high rho
        if best is None or score < best[0]:
            best = (score, bn)
    print("Best base-noise on 2024:")
    for k, v in best[1].items():
        print(f"    {k}: {v}")
    print("\nValidating on 2025 with tuned constants:")
    print_summary(backtest(PaceModel(base_noise=best[1]), [2025], verbose=False))
    print("\nvs default constants on 2025:")
    print_summary(backtest(PaceModel(), [2025], verbose=False))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", nargs="+", type=int,
                    default=[2024, 2025, 2026])
    ap.add_argument("--tune", action="store_true")
    args = ap.parse_args()
    if args.tune:
        tune()
        return 0
    model = PaceModel()
    bt = backtest(model, args.seasons)
    if bt.empty:
        print("Nothing to score.")
        return 1
    bt.to_csv(OUT, index=False)
    print(f"\nWrote {len(bt)} scored rows -> {OUT}")
    print_summary(bt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
