"""Per-session team pace measurements for the weekend prediction model.

Turns one session's laps into a small table of *measurements*: for each team,
an estimate of one-lap pace and long-run (race) pace expressed as a % gap to
the field mean, each with a standard error. These are the observations the
Bayesian layer in pace_model.py blends with its prior.

Methodology (deliberately different from the PRACTICE tab's min-lap gaps)
------------------------------------------------------------------------
Both measurement kinds come from a within-session fixed-effects OLS rather
than raw best/median laps, so compound choice, tyre age and track evolution
are adjusted for instead of ignored:

  one-lap   clean quali-sim laps:
                evolution-corrected lap%  ~  driver + compound
  long-run  clean non-quali-sim dry laps in runs of ≥ LONGRUN_MIN_RUN laps:
                evolution- & fuel-corrected lap%  ~  driver + compound
                                                     + tyre-age

Track evolution is NOT a regressor here: within a long run tyre age and the
session clock advance together (most drivers do one long run), so the two
effects are unidentifiable in-model and the fit explodes. Instead we reuse
processing.enrich_track_evolution, which estimates evolution from SHORT runs
only (≤8 laps, where fuel is comparable and age resets often) and subtracts
it from every lap (LapTime_TrackCorrected) before the fit.

The driver coefficients are the pace estimates; the OLS covariance gives
their standard errors, so a 4-lap read is *known* to be worth less than a
20-lap read. Team estimate = the team's best (lowest) driver coefficient,
matching how the targets in team_pace_by_event.csv are defined. Measurements
with absurd uncertainty or magnitude (SE > MAX_SE, |gap| > MAX_GAP) are
dropped rather than emitted.

All gaps are centered on the field mean (not the field best): the minimum of
noisy estimates is itself noisy, the mean is stable. Convert to gap-to-best
for display with `to_gap_to_best`.

Data access
-----------
`load_event_practice` reads practice laps from the app's full session cache
(data/sessions/) first and falls back to the laps-only backfill store
(data/sessions_lite/, written by fetch_practice_laps.py).
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

import data_loader as dl
from config import SESSIONS_DIR, SESSIONS_LITE_DIR
from processing import (
    clean_and_enrich_laps, flag_perturbed_laps, identify_quali_sim_laps,
    enrich_track_evolution,
)

logger = logging.getLogger(__name__)

# Archive/legacy team names → canonical, one identity across seasons
# (mirrors compute_team_pace.TEAM_CANON — kept importable from here so the
# model layer has no dependency on the CLI script).
TEAM_CANON = {
    "RB": "Racing Bulls", "AlphaTauri": "Racing Bulls",
    "Kick Sauber": "Sauber", "Alfa Romeo": "Sauber", "Alfa Romeo Racing": "Sauber",
}

DRY_COMPOUNDS = {"SOFT", "MEDIUM", "HARD"}

ONELAP_MIN_POOL = 8      # min clean quali-sim laps in a session to fit at all
ONELAP_MIN_TEAMS = 4
LONGRUN_MIN_RUN = 5      # a "long run" is a stint with ≥ this many laps
LONGRUN_MIN_POOL = 25
LONGRUN_MIN_DRIVER = 4   # drop drivers with fewer clean long-run laps
WET_DRY_SHARE = 0.5      # < this share of clean laps on dry tyres → wet session
MAX_SE = 2.0             # % — measurements less certain than this are useless
MAX_GAP = 6.0            # % — |gap| beyond any plausible F1 field spread
MIN_TEAMS_SET = 6        # a measurement set covering fewer teams than this is
                         # discarded: gaps are centered within the set, and a
                         # 3-team reference fabricates large relative gaps

PRACTICE_SESSIONS = ("Practice 1", "Practice 2", "Practice 3")

# Every session that runs BEFORE qualifying/the race and therefore carries
# usable pre-outcome pace, in weekend order. On a sprint weekend only FP1 of
# the practices exists, but Sprint Qualifying (a real low-fuel quali) and the
# Sprint (a real race on race fuel) are richer signals than practice — the
# Sprint especially is the best long-run read available. Which kind each
# contributes is set in _SESSION_KINDS.
INPUT_SESSIONS = ("Practice 1", "Practice 2", "Practice 3",
                  "Sprint Qualifying", "Sprint")

# session → which measurement kinds it can produce. Sprint Qualifying is a
# one-lap session; the Sprint is a race (long-run only). Practices give both.
_SESSION_KINDS = {
    "Practice 1": ("onelap", "longrun"),
    "Practice 2": ("onelap", "longrun"),
    "Practice 3": ("onelap", "longrun"),
    "Sprint Qualifying": ("onelap",),
    "Sprint": ("longrun",),
}


def canon(team: str) -> str:
    return TEAM_CANON.get(str(team).strip(), str(team).strip())


# ─────────────────────────────────────────────────────────────
# Data access
# ─────────────────────────────────────────────────────────────

def _laps_path(season: int | str, event: str, session: str) -> Path | None:
    key = dl._session_key(str(season), event, session)
    for base in (Path(SESSIONS_DIR), Path(SESSIONS_LITE_DIR)):
        p = base / f"{key}__laps.parquet"
        if p.exists():
            return p
    return None


def available_practice_sessions(season: int | str, event: str) -> list[str]:
    return [s for s in INPUT_SESSIONS
            if _laps_path(season, event, s) is not None]


def load_event_practice(season: int | str, event: str) -> pd.DataFrame:
    """Raw (unenriched) pre-outcome laps for one event (all practices plus
    Sprint Qualifying and the Sprint), concatenated and tagged with
    session/season/meeting/session_name like the app loader."""
    frames = []
    for session in INPUT_SESSIONS:
        p = _laps_path(season, event, session)
        if p is None:
            continue
        laps = pd.read_parquet(p)
        if laps.empty:
            continue
        if "session_name" not in laps.columns:
            dl._tag(laps, session, str(season), event,
                    dl._session_name(str(season), event, session))
        frames.append(laps)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def enrich_for_features(raw: pd.DataFrame) -> pd.DataFrame:
    """Standard enrichment chain for measurement extraction. Track evolution
    is fitted from short runs and baked into LapTime_TrackCorrected, which
    both measurement kinds then use as their response."""
    laps = clean_and_enrich_laps(raw)
    laps = flag_perturbed_laps(laps)
    laps = identify_quali_sim_laps(laps)
    laps = enrich_track_evolution(laps)
    return laps


# ─────────────────────────────────────────────────────────────
# OLS with standard errors
# ─────────────────────────────────────────────────────────────

class _Fit:
    """OLS result: coefficients, SEs, residuals, pooled residual sigma."""
    def __init__(self, coef, se, resid, sigma):
        self.coef, self.se, self.resid, self.sigma = coef, se, resid, sigma


def _ols_effects(y: np.ndarray, X: pd.DataFrame,
                 ridge: float = 1e-6) -> _Fit | None:
    """OLS coefficients + standard errors. Tiny ridge for numerical safety
    only (does not meaningfully bias estimates). None if under-determined."""
    n, p = X.shape
    if n <= p + 2:
        return None
    Xv = X.values.astype(float)
    XtX = Xv.T @ Xv + ridge * np.eye(p)
    try:
        XtX_inv = np.linalg.inv(XtX)
    except np.linalg.LinAlgError:
        return None
    beta = XtX_inv @ (Xv.T @ y)
    resid = y - Xv @ beta
    s2 = float(resid @ resid) / (n - p)
    se = np.sqrt(np.clip(np.diag(XtX_inv) * s2, 0.0, None))
    return _Fit(pd.Series(beta, index=X.columns),
                pd.Series(se, index=X.columns), resid, float(np.sqrt(s2)))


def _driver_scaled_se(fit: _Fit, pool: pd.DataFrame,
                      shrink_n: int = 4) -> pd.Series:
    """Rescale each driver coefficient's SE by that driver's OWN residual
    spread instead of the pooled one: a driver whose long run is metronomic
    should not inherit the noise of a teammate's scrappy programme. Small
    samples are shrunk toward the pooled sigma (shrink_n pseudo-laps)."""
    res = pd.Series(fit.resid, index=pool.index)
    se = fit.se.copy()
    pooled_var = fit.sigma ** 2
    for drv, grp in pool.groupby("Driver_Short"):
        col = f"drv_{drv}"
        if col not in se.index:
            continue
        n_d = len(grp)
        var_d = float(res.loc[grp.index].var(ddof=1)) if n_d > 2 else pooled_var
        var_blend = (n_d * var_d + shrink_n * pooled_var) / (n_d + shrink_n)
        if pooled_var > 0:
            se[col] = se[col] * np.sqrt(var_blend / pooled_var)
    return se


def _design(pool: pd.DataFrame, extra: dict[str, np.ndarray]) -> pd.DataFrame:
    """Driver dummies (no intercept) + compound dummies (ref = most common)
    + any extra numeric regressors."""
    drivers = pd.get_dummies(pool["Driver_Short"], prefix="drv")
    comp = pool["Compound"].astype(str)
    ref = comp.mode().iloc[0]
    comp_dum = pd.get_dummies(comp, prefix="cmp")
    comp_dum = comp_dum.drop(columns=[f"cmp_{ref}"], errors="ignore")
    parts = [drivers, comp_dum]
    if extra:
        parts.append(pd.DataFrame(extra, index=pool.index))
    return pd.concat(parts, axis=1).astype(float)


def _driver_rows(pool: pd.DataFrame, coef: pd.Series, se: pd.Series,
                 kind: str) -> pd.DataFrame:
    """Assemble per-driver estimates (centered on the field mean of teams).
    Drivers whose estimate is hopelessly uncertain or implausible are dropped
    before centering so they can't drag the reference around."""
    dmap = (pool.drop_duplicates("Driver_Short")
            .set_index("Driver_Short")["Team"].map(canon))
    counts = pool.groupby("Driver_Short").size()
    rows = []
    for col in coef.index:
        if not col.startswith("drv_"):
            continue
        drv = col[len("drv_"):]
        if se[col] > MAX_SE:
            continue
        team = str(dmap.get(drv, "") or "").strip()
        if team in ("", "Unknown", "nan"):
            continue          # blank-team FP1 feed rows: not attributable
        rows.append({"driver": drv, "team": team,
                     "kind": kind, "gap_pct": float(coef[col]),
                     "se_pct": float(se[col]),
                     "n_laps": int(counts.get(drv, 0))})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # team estimate = best driver; center all gaps on the mean of team bests
    team_best = df.groupby("team")["gap_pct"].min()
    df["gap_pct"] -= team_best.mean()
    df = df[df["gap_pct"].abs() <= MAX_GAP].reset_index(drop=True)
    # a set covering few teams (sparse session, or a fit so bad the
    # plausibility filter gutted it) has no usable common reference
    if df.empty or df["team"].nunique() < MIN_TEAMS_SET:
        return pd.DataFrame()
    return df


def _team_rows(driver_df: pd.DataFrame) -> pd.DataFrame:
    """Best-driver estimate per team (matches the target definition)."""
    if driver_df.empty:
        return driver_df
    idx = driver_df.groupby("team")["gap_pct"].idxmin()
    out = driver_df.loc[idx, ["team", "kind", "gap_pct", "se_pct"]].copy()
    out["n_laps"] = driver_df.groupby("team")["n_laps"].sum().loc[out["team"]].values
    out["n_drivers"] = driver_df.groupby("team").size().loc[out["team"]].values
    return out.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# Measurement extraction
# ─────────────────────────────────────────────────────────────

def _clean_mask(sl: pd.DataFrame) -> pd.Series:
    m = sl["ValidLap"] & sl["LapTime_s"].notna()
    if "Perturbed_Lap" in sl.columns:
        m &= ~sl["Perturbed_Lap"]
    return m


def _is_wet(sl: pd.DataFrame) -> bool:
    clean = sl[_clean_mask(sl)]
    if clean.empty:
        return True
    dry_share = clean["Compound"].astype(str).isin(DRY_COMPOUNDS).mean()
    return dry_share < WET_DRY_SHARE


def _onelap_measurements(sl: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(team_rows, driver_rows) of one-lap pace for a single session's laps."""
    empty = pd.DataFrame()
    pool = sl[_clean_mask(sl) & sl["Is_Quali_Sim"]
              & sl["Compound"].astype(str).isin(DRY_COMPOUNDS)].copy()
    if len(pool) < ONELAP_MIN_POOL:
        return empty, empty
    if pool.groupby("Driver_Short")["Team"].first().map(canon).nunique() < ONELAP_MIN_TEAMS:
        return empty, empty
    ycol = ("LapTime_TrackCorrected" if "LapTime_TrackCorrected" in pool.columns
            else "LapTime_s")
    ref = pool[ycol].median()
    y = (100.0 * (pool[ycol] / ref - 1)).values
    X = _design(pool, {})
    fit = _ols_effects(y, X)
    if fit is None:
        return empty, empty
    drv = _driver_rows(pool, fit.coef, fit.se, kind="onelap")
    return _team_rows(drv), drv


def _longrun_measurements(sl: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(team_rows, driver_rows) of long-run pace for a single session's laps."""
    empty = pd.DataFrame()
    stint_len = sl.groupby(["session_name", "DriverNo", "Stint"])["LapInStint"] \
                  .transform("max")
    age_col = "TyreAge" if "TyreAge" in sl.columns else "PseudoTyreAge"
    age = pd.to_numeric(sl[age_col], errors="coerce").fillna(sl["PseudoTyreAge"])
    pool = sl[_clean_mask(sl)
              & ~sl["Is_Quali_Sim"]
              & sl["Compound"].astype(str).isin(DRY_COMPOUNDS)
              & (stint_len >= LONGRUN_MIN_RUN)
              & (sl["LapInStint"] >= 2)
              & (age <= 40)].copy()
    if pool.empty:
        return empty, empty
    ycol = ("LapTime_TrackCorrected" if "LapTime_TrackCorrected" in pool.columns
            else "LapTime_FuelCorrected")
    # ValidLap's outlier gate is generous (+25% of the session median), so
    # practice long runs still contain cool-downs, aborted laps and backing
    # off for gaps — 15%+ within-driver spread vs ~0.6% on true sim laps.
    # Trim anything more than 2.5% slower than its own stint's median; genuine
    # degradation across a run stays well inside that.
    stint_med = pool.groupby(["session_name", "DriverNo", "Stint"])[ycol] \
                    .transform("median")
    pool = pool[pool[ycol] <= stint_med * 1.025]
    # a driver with a couple of laps contributes a meaningless coefficient
    counts = pool.groupby("Driver_Short")["LapTime_s"].transform("size")
    pool = pool[counts >= LONGRUN_MIN_DRIVER]
    if len(pool) < LONGRUN_MIN_POOL:
        return empty, empty
    def _fit_pool(p: pd.DataFrame) -> _Fit | None:
        ref = p[ycol].median()
        y = (100.0 * (p[ycol] / ref - 1)).values
        a = pd.to_numeric(p[age_col], errors="coerce").fillna(p["PseudoTyreAge"])
        X = _design(p, {"age": (a - a.mean()).values})
        return _ols_effects(y, X)

    fit = _fit_pool(pool)
    if fit is None:
        return empty, empty
    # Robust second pass: drop laps that are slow outliers vs the fit (missed
    # cool-downs, traffic the perturbation flags didn't catch), then refit.
    rsig = 1.4826 * np.median(np.abs(fit.resid - np.median(fit.resid)))
    keep = fit.resid <= 2.5 * max(rsig, 0.05)
    if keep.sum() < len(keep) and keep.sum() >= LONGRUN_MIN_POOL:
        pool2 = pool[keep]
        fit2 = _fit_pool(pool2)
        if fit2 is not None:
            fit, pool = fit2, pool2
    se = _driver_scaled_se(fit, pool)
    drv = _driver_rows(pool, fit.coef, se, kind="longrun")
    return _team_rows(drv), drv


def session_measurements(laps: pd.DataFrame, session_name: str
                         ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extract (team_measurements, driver_measurements) from ONE session of an
    enriched laps frame. Empty frames when the session is wet or too sparse.

    Returned columns (team): team, kind ('onelap'|'longrun'), gap_pct (% gap
    to field mean), se_pct, n_laps, n_drivers, plus session/season/meeting.
    """
    sl = laps[laps["session_name"] == session_name]
    empty = pd.DataFrame()
    if sl.empty or _is_wet(sl):
        if not sl.empty:
            logger.info("session_measurements: %s looks wet — skipped",
                        session_name)
        return empty, empty
    # only run the kinds this session type can produce (Sprint Qualifying =
    # one-lap, the Sprint = long-run, practices = both)
    kinds = _SESSION_KINDS.get(str(sl["session"].iloc[0]), ("onelap", "longrun"))
    t1, d1 = _onelap_measurements(sl) if "onelap" in kinds else (empty, empty)
    t2, d2 = _longrun_measurements(sl) if "longrun" in kinds else (empty, empty)
    team = pd.concat([t1, t2], ignore_index=True)
    driver = pd.concat([d1, d2], ignore_index=True)
    for df in (team, driver):
        if not df.empty:
            df["session"] = sl["session"].iloc[0]
            df["season"] = int(sl["season"].iloc[0])
            df["meeting"] = sl["meeting"].iloc[0]
    return team, driver


def event_measurements(season: int | str, event: str
                       ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """All practice-session measurements for one event: one enrichment pass,
    then per-session extraction, in session order."""
    raw = load_event_practice(season, event)
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame()
    laps = enrich_for_features(raw)
    teams, drivers = [], []
    for sess_name in sorted(laps["session_name"].unique()):
        t, d = session_measurements(laps, sess_name)
        if not t.empty:
            teams.append(t)
        if not d.empty:
            drivers.append(d)
    team = pd.concat(teams, ignore_index=True) if teams else pd.DataFrame()
    driver = pd.concat(drivers, ignore_index=True) if drivers else pd.DataFrame()
    return team, driver


def to_gap_to_best(df: pd.DataFrame, col: str = "gap_pct") -> pd.DataFrame:
    """Re-express mean-centered gaps as gaps to the best team (for display)."""
    out = df.copy()
    out[col] = out[col] - out[col].min()
    return out
