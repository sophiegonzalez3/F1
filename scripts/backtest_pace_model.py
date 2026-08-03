"""Backtest the progressive pace model against actual weekend outcomes.

For every event with practice data cached (data/sessions or the laps-only
backfill in data/sessions_lite), this replays the weekend: freezes the
model's prediction at the prior and after each practice session, then scores
those predictions against what actually happened —

  onelap   → team session-normalised one-lap pace  (quali_pace_pct)
  longrun  → team race pace                          (race_pace_pct)

both from data/team_pace_by_event.csv, and both the same columns the model's
own prior is built from. Everything is compared in mean-centered space (each
set minus its own mean).

These used to be the raw gap-to-pole / gap-to-fastest columns. Scoring against
those meant part of the measured error was Q1->Q3 track evolution that no model
could predict — whether a team's best lap lands in Q1 or Q2 shifts that target
~0.6 pp, and it flipped on 19% of round-to-round steps in 2026. Raw MAE from
before that change is NOT comparable with raw MAE after it; Spearman rho is
(scale-free), and so is model-MAE-over-baseline-MAE.

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
    python scripts/backtest_pace_model.py --tune          # two-stage grid search:
                                                  # train 2024, validate 2025,
                                                  # hold out 2026 (new era)
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
from f1lib.pace_model import PaceModel, era_of, DEFAULTS

OUT = Path("data/backtest_pace_model.csv")
# Score against the SAME quantity the model's prior is built from — the
# session-normalised, field-median-relative pace columns. Scoring against the
# raw gap-to-pole meant part of the measured error was Q1→Q3 track evolution
# the model could not have predicted: a team whose best lap flips Q-session
# moves that target ~0.6 pp for reasons invisible on Friday.
#
# NOTE for anyone comparing to older runs: raw MAE is NOT comparable across
# this change, because the target itself changed. Spearman rho is (it is
# scale-free), and so is the model's MAE relative to the raw-FP baseline,
# since the baseline is scored on the same target.
TARGET = {"onelap": "quali_pace_pct", "longrun": "race_pace_pct"}
_TARGET_FALLBACK = {"onelap": "quali_gap_pct", "longrun": "race_pace_gap_pct"}


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
    if col not in model.pace.columns:          # table predates the pace columns
        col = _TARGET_FALLBACK[kind]
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

_STAGE_LABEL_SHORT = {"Practice 1": "FP1", "Practice 2": "FP2",
                      "Practice 3": "FP3"}
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

def _stage_score(bt: pd.DataFrame, kind: str) -> float:
    """Lower is better: MAE penalised, rank correlation rewarded. Scored on
    the post-practice stages, which is when the prediction is actually read."""
    d = bt[(bt["kind"] == kind) & (bt["stage"].str.startswith("after"))]
    if d.empty:
        return float("inf")
    return float(d["mae"].mean() - 0.5 * d["rho"].mean())


# A base-noise constant is only identifiable if the training set actually
# contains events scored at that stage. Below this many, the grid search sees
# an unchanged score for every candidate value and returns whichever it tried
# first — a fabricated constant that looks like a result. 2024 has ZERO
# long-run FP3 events, so that constant was "optimised" on nothing.
MIN_TUNE_EVENTS = 5


def _stage_coverage(seasons: list[int]) -> pd.Series:
    """Events per (kind, stage) in the training set — what each constant can
    actually be fitted on."""
    bt = backtest(PaceModel(), list(seasons), verbose=False)
    if bt.empty:
        return pd.Series(dtype=int)
    return bt.groupby(["kind", "stage"])["event"].nunique()


def tune(train=(2024,), validate=(2025,), holdout=(2026,)) -> None:
    """Grid-search the practice base-noise constants.

    Two stages, not one 6-D grid: `_update_one` only ever reads
    base_noise[(kind, session)], so the one-lap posterior is independent of the
    long-run constants. Tuning them separately is 4³+4³ = 128 fits instead of
    4⁶ = 4096, for the same answer.

    Three season groups, deliberately:
      train     grid-searched on
      validate  same era, never tuned on — catches overfitting
      holdout   DIFFERENT regulation era, never tuned on — catches constants
                that only work for the era they were fitted in

    The holdout matters here: 2026 is a new formula. Its absolute errors are
    not expected to match the ground-effect seasons and a difference there is
    not evidence of a bug — what the holdout is really asking is whether the
    model still beats its baselines, not whether it hits the same MAE.
    """
    onelap_grid = [0.20, 0.30, 0.40, 0.55]
    longrun_grid = [0.35, 0.50, 0.70, 0.85]
    sess = ["Practice 1", "Practice 2", "Practice 3"]

    cov = _stage_coverage(list(train))
    print(f"Training-set coverage ({list(train)}) — a constant needs at least "
          f"{MIN_TUNE_EVENTS} events to be identifiable:")
    unidentified = set()
    for kind in ("onelap", "longrun"):
        for sname in sess:
            n = int(cov.get((kind, f"after {_STAGE_LABEL_SHORT[sname]}"), 0))
            flag = "" if n >= MIN_TUNE_EVENTS else "   <- NOT IDENTIFIABLE, keeping default"
            if n < MIN_TUNE_EVENTS:
                unidentified.add((kind, sname))
            print(f"  {kind:<8} {sname:<11} {n:3d} events{flag}")
    print()

    print(f"Stage 1/2 — one-lap noise, {len(onelap_grid)**3} fits on "
          f"{list(train)}…", flush=True)
    best_one = None
    for combo in itertools.product(onelap_grid, repeat=3):
        bn = {("onelap", s_): v for s_, v in zip(sess, combo)
              if ("onelap", s_) not in unidentified}
        sc = _stage_score(backtest(PaceModel(base_noise={**DEFAULTS["base_noise"],
                                                        **bn}),
                                   list(train), verbose=False), "onelap")
        if best_one is None or sc < best_one[0]:
            best_one = (sc, bn)
    print(f"  best one-lap: "
          f"{ {s: v for (_, s), v in best_one[1].items()} }  score {best_one[0]:.3f}")

    print(f"\nStage 2/2 — long-run noise, {len(longrun_grid)**3} fits…",
          flush=True)
    best_lng = None
    for combo in itertools.product(longrun_grid, repeat=3):
        bn = {**best_one[1], **{("longrun", s_): v for s_, v in zip(sess, combo)
                                if ("longrun", s_) not in unidentified}}
        sc = _stage_score(backtest(PaceModel(base_noise={**DEFAULTS["base_noise"],
                                                         **bn}),
                                   list(train), verbose=False), "longrun")
        if best_lng is None or sc < best_lng[0]:
            best_lng = (sc, bn)
    tuned = {**DEFAULTS["base_noise"], **best_lng[1]}
    print(f"  best long-run: "
          f"{ {s: v for (k, s), v in best_lng[1].items() if k == 'longrun'} }"
          f"  score {best_lng[0]:.3f}")

    print("\n" + "=" * 66)
    print("TUNED base_noise (paste into DEFAULTS in f1lib/pace_model.py):")
    for k in sorted(best_lng[1]):
        print(f"    {k}: {best_lng[1][k]}")

    for label, seasons_ in (("VALIDATE (same era, not tuned on)", validate),
                            ("HOLDOUT (different era, not tuned on)", holdout)):
        if not seasons_:
            continue
        print("\n" + "=" * 66)
        print(f"{label}: {list(seasons_)}")
        print("\n--- tuned ---")
        print_summary(backtest(PaceModel(base_noise=tuned), list(seasons_),
                               verbose=False))
        print("\n--- current defaults ---")
        print_summary(backtest(PaceModel(), list(seasons_), verbose=False))


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
