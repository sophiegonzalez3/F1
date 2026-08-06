"""Backtest the progressive pace model against actual weekend outcomes.

For every event with practice data cached (data/sessions or the laps-only
backfill in data/sessions_lite), this replays the weekend: freezes the
model's prediction at the prior and after each practice session, then scores
those predictions against what actually happened —

  onelap   → team session-normalised one-lap pace  (onelap_speed_pct)
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
POINT ACCURACY
  MAE       mean absolute error, % (lower better)
  RMSE      root mean squared error, %. RMSE/MAE > sqrt(pi/2) = 1.253 means
            the errors are fat-tailed rather than Gaussian — this model runs
            at ~1.45, and the tail is almost entirely WET RACES.
  Spearman  rank correlation predicted vs actual (higher better)
  Kendall   rank correlation counting PAIRS, which converts straight into
            plain English: P(a random pair of teams is ordered correctly)
            = (1 + tau) / 2. tau 0.65 -> 83% of head-to-heads right.

CALIBRATION — are the error bars honest?
  z_sd      standard deviation of (actual - predicted) / sd. Should be 1.00.
  cov68     share of outcomes inside +/-1 sd. Should be 68%.
  cov95     share inside +/-1.96 sd. Should be 95%.
  CRPS      MAE generalised to a distribution (collapses to MAE for a point
            forecast). Rewards sharp AND calibrated, gently.
  NLL       negative log predictive density — the strictly proper score. The
            only metric that punishes OVERCONFIDENCE, and therefore the only
            one that can tell "sharpened" from "over-sharpened".

  n         events scored

Why the calibration block exists: MAE scores "-1.02 +/- 0.01" and
"-1.02 +/- 5.00" identically, so for a model whose entire selling point is
reporting uncertainty it is blind in exactly the wrong place. Measuring it
found the prior reporting the variance of the MEAN of past races where it
needed the PREDICTIVE variance of the next one — a ~2x understatement of
long-run uncertainty that MAE could never have surfaced.

A per-team detail table is written alongside (OUT_DETAIL) because the
aggregate cannot answer "which teams blow up, and when".

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
import re
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

import numpy as np
import pandas as pd
from scipy.stats import kendalltau, norm, spearmanr

import f1lib.data_loader as dl
from f1lib.config import SESSIONS_DIR, SESSIONS_LITE_DIR
from f1lib.pace_features import event_measurements, PRACTICE_SESSIONS
from f1lib.pace_model import PaceModel, era_of, DEFAULTS

OUT = Path("data/backtest_pace_model.csv")
# Per-team detail behind every scored row. Separate file so the aggregate one
# the BRIEF tab reads keeps its shape and stays small.
OUT_DETAIL = Path("data/backtest_pace_detail.csv")
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
TARGET = {"onelap": "onelap_speed_pct", "longrun": "race_pace_pct"}
_TARGET_FALLBACK = {"onelap": "quali_result_gap_pct", "longrun": "race_pace_gap_pct"}


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


# Measurement extraction (load laps -> enrich -> per-session OLS) is by far
# the slowest part of a replay, and it does not depend on any model parameter.
# The tuning loop re-runs the same events 128 times, so without this cache a
# grid search costs 128 full enrichment passes — which is the real reason the
# search used to be pinned to a single training season.
_MEAS_CACHE: dict[tuple[int, str], pd.DataFrame] = {}
# ...and on disk too, under the gitignored cache/ tree, so a re-tune does not
# pay the enrichment cost again. Measurements are a pure function of the cached
# laps; delete the directory after re-fetching a session.
_MEAS_DIR = Path("cache/pace_measurements")


def _measurements(season: int, event: str) -> pd.DataFrame:
    key = (int(season), str(event))
    if key in _MEAS_CACHE:
        return _MEAS_CACHE[key]
    slug = f"{key[0]}__{re.sub(r'[^A-Za-z0-9]+', '_', key[1])}.pkl"
    path = _MEAS_DIR / slug
    if path.exists():
        try:
            _MEAS_CACHE[key] = pd.read_pickle(path)
            return _MEAS_CACHE[key]
        except Exception:
            pass                      # unreadable cache entry: just rebuild it
    meas, _ = event_measurements(season, event)
    meas = meas if meas is not None else pd.DataFrame()
    _MEAS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        meas.to_pickle(path)
    except Exception as exc:
        logging.getLogger(__name__).debug("measurement cache write failed: %s", exc)
    _MEAS_CACHE[key] = meas
    return meas


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


def _crps_gauss(y: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    """CRPS of a Gaussian forecast against a scalar outcome, closed form.

    Generalises MAE to a distribution: it collapses to |y - mu| as sd -> 0, so
    a point forecast and a distributional one are scored on the same scale.
    Unlike the log score it stays finite when an outcome lands far into the
    tail, which is why both are reported — they disagree in a useful way.
    """
    z = (y - mu) / sd
    return sd * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / np.sqrt(np.pi))


def _nll_gauss(y: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    """Negative log predictive density — the strictly proper score.

    Punishes CONFIDENT errors quadratically in z, so it is the only metric
    here that can tell a sharpened prediction from an over-sharpened one.
    """
    return 0.5 * np.log(2 * np.pi * sd ** 2) + (y - mu) ** 2 / (2 * sd ** 2)


def _score(pred: pd.DataFrame, actual: pd.Series, kind: str) -> dict | None:
    """Score one prediction (team, kind, mean[, sd]) against the outcome.

    Point accuracy (MAE, Spearman) plus — when the prediction carries an `sd`
    — the CALIBRATION metrics that MAE structurally cannot see. MAE scores a
    prediction of "-1.02 +/- 0.01" and "-1.02 +/- 5.00" identically; the whole
    value of a Bayesian model is in that second number, so it has to be
    measured. `raw-FP` has no sd and reports NaN for these, which is itself
    the point: a bare timing-screen read makes no claim to be wrong by any
    particular amount.

    mean_z2 rather than the standard deviation of z: means of z-squared pool
    correctly across events when weighted by n_teams, whereas per-event
    standard deviations (10 teams each) do not.
    """
    sub = pred[pred["kind"] == kind].set_index("team")
    p = sub["mean"]
    common = p.index.intersection(actual.index)
    if len(common) < 4:
        return None
    pv = (p[common] - p[common].mean()).values
    av = (actual[common] - actual[common].mean()).values
    rho = spearmanr(pv, av).correlation if len(common) > 2 else np.nan
    tau = kendalltau(pv, av).correlation if len(common) > 2 else np.nan
    out = {"mae": float(np.mean(np.abs(pv - av))),
           "rmse": float(np.sqrt(np.mean((pv - av) ** 2))),
           "rho": float(rho), "tau": float(tau), "n_teams": len(common)}
    if "sd" in sub.columns and sub.loc[common, "sd"].notna().all():
        sd = sub.loc[common, "sd"].values.astype(float)
        z = (av - pv) / sd
        out.update({
            "mean_z2": float(np.mean(z ** 2)),
            "cov68": float(np.mean(np.abs(z) <= 1.0)),
            "cov95": float(np.mean(np.abs(z) <= 1.96)),
            "crps": float(np.mean(_crps_gauss(av, pv, sd))),
            "nll": float(np.mean(_nll_gauss(av, pv, sd))),
        })
    else:
        out.update({k: np.nan for k in
                    ("mean_z2", "cov68", "cov95", "crps", "nll")})
    return out


def _detail_rows(pred: pd.DataFrame, actual: pd.Series, kind: str,
                 **tags) -> list[dict]:
    """Per-TEAM prediction/outcome rows behind one score.

    The aggregate table cannot answer "which teams blow up, and when" — the
    fat tail in this model turns out to be a handful of wet races, and that
    is invisible once each event is reduced to a single MAE.
    """
    sub = pred[pred["kind"] == kind].set_index("team")
    p = sub["mean"]
    common = p.index.intersection(actual.index)
    if len(common) < 4:
        return []
    pv = p[common] - p[common].mean()
    av = actual[common] - actual[common].mean()
    has_sd = "sd" in sub.columns
    return [{**tags, "kind": kind, "team": t,
             "pred": float(pv[t]),
             "sd": float(sub.loc[t, "sd"]) if has_sd else np.nan,
             "actual": float(av[t]),
             "err": float(av[t] - pv[t])} for t in common]


def _raw_fp_prediction(meas: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Latest practice session's measurement of `kind`, taken literally."""
    mk = meas[meas["kind"] == kind]
    for sess in reversed(PRACTICE_SESSIONS):
        m = mk[mk["session"] == sess]
        if not m.empty:
            return pd.DataFrame({"team": m["team"], "kind": kind,
                                 "mean": m["gap_pct"].values})
    return pd.DataFrame(columns=["team", "kind", "mean"])


def _quali_gap(model: PaceModel, season: int, event: str) -> pd.Series | None:
    """Session-normalised actual qualifying gap per team, centred on the
    field mean — the same measurement PaceModel.actual_quali_gap produces
    live, taken from the pace table so it exists for every archived season.
    """
    p = model.pace
    row = (p[(p["season"] == season) & (p["event"] == event)]
           .set_index("team")[model.col_onelap].dropna())
    if len(row) < 4:
        return None
    return row - row.mean()


def backtest(model: PaceModel, seasons: list[int],
             verbose: bool = True,
             detail: list[dict] | None = None) -> pd.DataFrame:
    """Replay every event and score each stage.

    Pass a list as `detail` to have the per-team prediction/outcome rows
    appended to it as a side effect (see `_detail_rows`); the tuning loop
    omits it, since it only reads the aggregate score.

    The post-quali stage IS scored, and doing so is leak-free — a point
    worth spelling out, because this backtest used to skip it out of
    caution and that left a constant used live on every race weekend with
    nothing measuring it.

    Qualifying happens BEFORE the race, so using its result to predict race
    pace is an ordinary ex-ante prediction. The update touches only the
    LONG-RUN latent, and the long-run target is race_pace_pct, measured from
    race laps that do not exist yet at that point in the weekend. The prior
    itself only ever reads strictly-earlier rounds.

    What WOULD be circular is scoring the ONE-LAP target after feeding in the
    qualifying result — qualifying predicting qualifying. The one-lap latent
    is never touched by this update, so that stage is skipped for `onelap`
    rather than reported as a free win.
    """
    events = backtestable_events(model, seasons)
    rows = []
    for season, event, round_ in events:
        meas = _measurements(season, event)
        if meas is None or meas.empty:
            continue
        stages = model.predict_weekend(season, event,
                                       measurements=meas, round_=round_,
                                       quali_gap=_quali_gap(model, season, event))
        for kind in ("onelap", "longrun"):
            actual = _actual(model, season, event, kind)
            if actual.empty:
                continue
            tags = {"season": season, "era": era_of(season), "event": event,
                    "round": round_}
            for stage_name, st in stages.items():
                if stage_name == "after Quali" and kind == "onelap":
                    continue        # circular — see the docstring
                sc = _score(st, actual, kind)
                if sc:
                    rows.append({**tags, "kind": kind, "stage": stage_name,
                                 **sc})
                    if detail is not None:
                        detail.extend(_detail_rows(st, actual, kind,
                                                   **tags, stage=stage_name))
            # raw-FP baseline (only meaningful as an end-of-practice read)
            raw = _raw_fp_prediction(meas, kind)
            if not raw.empty:
                sc = _score(raw, actual, kind)
                if sc:
                    rows.append({**tags, "kind": kind, "stage": "raw-FP",
                                 **sc})
                    if detail is not None:
                        detail.extend(_detail_rows(raw, actual, kind,
                                                   **tags, stage="raw-FP"))
        if verbose:
            print(f"  scored {season} {event}", flush=True)
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────

_STAGE_LABEL_SHORT = {"Practice 1": "FP1", "Practice 2": "FP2",
                      "Practice 3": "FP3"}
_STAGE_ORDER = ["prior", "after FP1", "after FP2", "after FP3",
                "after SprintQuali", "after Sprint", "after Quali", "raw-FP"]


def _pooled(g: pd.DataFrame, col: str) -> float:
    """Team-weighted mean of a per-event statistic, skipping events where it
    is undefined (raw-FP carries no sd)."""
    d = g.dropna(subset=[col])
    if d.empty or d["n_teams"].sum() == 0:
        return float("nan")
    return float((d[col] * d["n_teams"]).sum() / d["n_teams"].sum())


def summarize(bt: pd.DataFrame) -> pd.DataFrame:
    if bt.empty:
        return bt
    rows = []
    for (era, kind, stage), g in bt.groupby(["era", "kind", "stage"]):
        rows.append({
            "era": era, "kind": kind, "stage": stage,
            "mae": g["mae"].mean(), "rho": g["rho"].mean(),
            "tau": g["tau"].mean() if "tau" in g else np.nan,
            # z_sd pools through the MEAN OF z-SQUARED, not by averaging
            # per-event standard deviations (10 teams each, far too noisy)
            "z_sd": np.sqrt(_pooled(g, "mean_z2")) if "mean_z2" in g else np.nan,
            "cov68": _pooled(g, "cov68") if "cov68" in g else np.nan,
            "cov95": _pooled(g, "cov95") if "cov95" in g else np.nan,
            "crps": _pooled(g, "crps") if "crps" in g else np.nan,
            "nll": _pooled(g, "nll") if "nll" in g else np.nan,
            "n": len(g),
        })
    g = pd.DataFrame(rows)
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
        print(f"  {'stage':<12}{'MAE %':>9}{'rho':>8}{'tau':>8}"
              f"{'z_sd':>8}{'cov68':>8}{'cov95':>8}{'CRPS':>8}{'NLL':>9}{'n':>5}")
        for _, r in g.iterrows():
            print(f"  {r['stage']:<12}{r['mae']:>9.3f}{r['rho']:>8.3f}"
                  f"{r['tau']:>8.3f}{r['z_sd']:>8.2f}"
                  f"{100*r['cov68']:>7.1f}%{100*r['cov95']:>7.1f}%"
                  f"{r['crps']:>8.3f}{r['nll']:>9.3f}{int(r['n']):>5}")
    print("\n  z_sd should be 1.00, cov68 68%, cov95 95% if the error bars are"
          " honest.\n  raw-FP reports no sd, so its calibration columns are"
          " blank by construction.")
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
# Tuning: grid-search base noise on 2022-24, validate 2025, hold out 2026
# ─────────────────────────────────────────────────────────────

def _stage_score(bt: pd.DataFrame, kind: str, objective: str = "point") -> float:
    """Lower is better. Scored on the post-practice stages, which is when the
    prediction is actually read.

    objective="point"  MAE penalised, rank correlation rewarded. The historical
                       objective: it judges WHERE the prediction sits and says
                       nothing about the interval around it.
    objective="crps"   mean CRPS. Strictly proper (so it cannot be gamed) and
                       it charges for over-confidence, but it grows LINEARLY
                       in the tail rather than quadratically. That matters
                       here — see the warning about "nll" below.
    objective="nll"    mean negative log predictive density. Also strictly
                       proper, and DEGENERATE FOR THIS PROBLEM. Do not use it
                       to tune base_noise.

                       Measured, 2022-24 training set: the search drove every
                       one of the six constants to its grid CEILING (one-lap
                       0.60, long-run 1.30) and flattened the weekend
                       progression to a single value per kind. The mechanism
                       is plain once seen — raising base_noise shrinks K,
                       which keeps the posterior near the (now well-calibrated)
                       prior, so "ignore practice entirely" is the log score's
                       optimum. On the 2025 validation season the tuned set
                       made practice worth literally nothing: paired one-lap
                       MAE 0.216 -> 0.216, and long-run FP2 got worse
                       (0.488 -> 0.570) while coverage overshot to 84% against
                       a 68% target.

                       The root cause is that the errors are fat-tailed
                       (RMSE/MAE ~1.45, and the tail is wet races). A GAUSSIAN
                       log score on fat-tailed errors is dominated by the tail,
                       so it buys unlimited tail insurance with the mean
                       signal. CRPS pays a linear premium instead and does not
                       collapse this way.
    """
    d = bt[(bt["kind"] == kind) & (bt["stage"].str.startswith("after"))]
    if d.empty:
        return float("inf")
    if objective in ("nll", "crps"):
        s = _pooled(d, objective)
        return float(s) if np.isfinite(s) else float("inf")
    return float(d["mae"].mean() - 0.5 * d["rho"].mean())


# A base-noise constant is only identifiable if the training set actually
# contains events scored at that stage. Below this many, the grid search sees
# an unchanged score for every candidate value and returns whichever it tried
# first — a fabricated constant that looks like a result. 2024 has ZERO
# long-run FP3 events, so that constant was "optimised" on nothing.
MIN_TUNE_EVENTS = 5


def _warn_if_on_boundary(best: dict, grid: list[float], label: str) -> None:
    """A grid search that returns an EDGE value has not found an optimum, it
    has run out of room — the true optimum is somewhere off the end of the
    grid, and the reported number is an artifact of where the grid stopped.

    This is not hypothetical. Tuning base_noise on the log score returned the
    ceiling for all six constants at once, which is what exposed that objective
    as degenerate (see _stage_score). Nothing warned; the numbers just looked
    like a result. A run that trips this should be treated as a failed search,
    not a tuned constant.
    """
    lo, hi = min(grid), max(grid)
    edge = {s: v for (_, s), v in best.items() if v in (lo, hi)}
    if not edge:
        return
    print(f"  !! {label}: {len(edge)}/{len(best)} constants landed ON A GRID "
          f"EDGE ({edge}) — grid spans {lo}-{hi}.")
    if len(edge) == len(best):
        print("  !! EVERY constant is on an edge. Treat this as a FAILED "
              "search: widen the grid, or suspect the objective has a "
              "degenerate direction, before pasting anything.")


def _stage_coverage(seasons: list[int]) -> pd.Series:
    """Events per (kind, stage) in the training set — what each constant can
    actually be fitted on."""
    bt = backtest(PaceModel(), list(seasons), verbose=False)
    if bt.empty:
        return pd.Series(dtype=int)
    return bt.groupby(["kind", "stage"])["event"].nunique()


def tune(train=(2023, 2024), validate=(2025,), holdout=(2026,),
         objective: str = "crps") -> None:
    """Grid-search the practice base-noise constants.

    Two stages, not one 6-D grid: `_update_with_set` only ever reads
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

    TRAINING SET WIDENED to 2023-24 (46 events, was 24). The one-season set was
    never a data limit — earlier practice laps have been in the lite store all
    along — it was a RUNTIME limit, because every candidate re-ran the
    enrichment pass. `_MEAS_CACHE` removes that cost, and the wider set
    directly fixes the identifiability hole this docstring used to warn about:
    2024 alone had 2 / 1 / 0 events at long-run FP1 / FP2 / FP3.

    2022 IS DELIBERATELY EXCLUDED — because of WEATHER, which this model
    explicitly does not attempt to predict.

    The first diagnosis was wrong and is recorded here so it is not repeated.
    2022's long-run score looks terrible in aggregate (z_sd 2.62 at the prior,
    4.28 after FP3, against 0.94-1.50 for 2023-26) and that was initially
    blamed on its race laps living in the laps-only lite store with no
    race-control messages. Two measurements killed that: the race-control
    signal had never fired for ANY season (a datetime-vs-seconds bug in
    _normalize_rcm, since fixed), and 2022's damage is concentrated in a
    single event — Monaco scores mean|z| 10.6 while the season's MEDIAN event
    scores 0.44.

    Monaco 2022 ran 44% of its laps in rain. The season also had Japan at 98%,
    Hungary 28% and Singapore 18%. Practice pace does not predict a wet race
    and the model does not claim it does, so tuning the noise constants on
    those events would buy insurance against a risk the model has already
    declined to carry (see "REJECTED: widening the variance for rain" in
    f1lib/pace_model.py). One-lap in 2022 is unremarkable at z_sd 1.18, which
    is the tell: qualifying was largely dry.

    OBJECTIVE defaults to CRPS. base_noise sets how far the posterior variance
    collapses as well as where the mean lands, so a point-accuracy objective
    optimises half of what the constant does and lets the other half drift —
    but the log score, the obvious fix, turns out to be degenerate here (it
    drives every constant to its ceiling; see _stage_score). CRPS is proper,
    charges for over-confidence, and stays linear in the tail. Pass
    objective="point" to reproduce the historical search.
    """
    # Grids extended upward TWICE, from ([0.20-0.55], [0.35-0.85]) to
    # ([0.25-0.60], [0.70-1.30]) and now to these. The prior is the predictive
    # variance and therefore wider, which raises the Kalman gain, so the noise
    # needed to hold practice at a sensible influence is larger than it was
    # when these constants were first set against a too-narrow prior. Both
    # earlier grids were exhausted — every long-run constant came back on the
    # ceiling — which is a search reporting that it ran out of room, not that
    # it found an optimum. `_warn_if_on_boundary` now says so out loud.
    #
    # Upper bounds are set by the guard rails in
    # tests/test_pace_noise_calibration.py: one-lap must stay within
    # 0.15-1.00 and long-run within 0.40-1.60, the band the attenuation
    # calibration supports. A search that pins the long-run grid at 1.60 has
    # left that band and should be treated as evidence of a problem
    # UPSTREAM (a noisy target, or a prior still mis-sized) rather than as a
    # constant to paste.
    onelap_grid = [0.50, 0.65, 0.80, 0.95]
    longrun_grid = [1.00, 1.20, 1.40, 1.60]
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
                                   list(train), verbose=False),
                          "onelap", objective)
        if best_one is None or sc < best_one[0]:
            best_one = (sc, bn)
    print(f"  best one-lap: "
          f"{ {s: v for (_, s), v in best_one[1].items()} }  score {best_one[0]:.3f}")
    _warn_if_on_boundary(best_one[1], onelap_grid, "one-lap")

    print(f"\nStage 2/2 — long-run noise, {len(longrun_grid)**3} fits…",
          flush=True)
    best_lng = None
    for combo in itertools.product(longrun_grid, repeat=3):
        bn = {**best_one[1], **{("longrun", s_): v for s_, v in zip(sess, combo)
                                if ("longrun", s_) not in unidentified}}
        sc = _stage_score(backtest(PaceModel(base_noise={**DEFAULTS["base_noise"],
                                                         **bn}),
                                   list(train), verbose=False),
                          "longrun", objective)
        if best_lng is None or sc < best_lng[0]:
            best_lng = (sc, bn)
    tuned = {**DEFAULTS["base_noise"], **best_lng[1]}
    lng_only = {k: v for k, v in best_lng[1].items() if k[0] == "longrun"}
    print(f"  best long-run: "
          f"{ {s: v for (k, s), v in lng_only.items()} }"
          f"  score {best_lng[0]:.3f}")
    _warn_if_on_boundary(lng_only, longrun_grid, "long-run")

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
    ap.add_argument("--objective", choices=("crps", "nll", "point"),
                    default="crps",
                    help="tuning objective: CRPS (default), the historical "
                         "MAE-and-rank score, or the log score — which is "
                         "DEGENERATE for base_noise, see _stage_score")
    args = ap.parse_args()
    if args.tune:
        tune(objective=args.objective)
        return 0
    model = PaceModel()
    detail: list[dict] = []
    bt = backtest(model, args.seasons, detail=detail)
    if bt.empty:
        print("Nothing to score.")
        return 1
    bt.to_csv(OUT, index=False)
    print(f"\nWrote {len(bt)} scored rows -> {OUT}")
    if detail:
        pd.DataFrame(detail).to_csv(OUT_DETAIL, index=False)
        print(f"Wrote {len(detail)} per-team rows -> {OUT_DETAIL}")
    print_summary(bt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
