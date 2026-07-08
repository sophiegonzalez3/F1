"""
F1 Dashboard – Data Processing & Feature Engineering
All transformation logic extracted from the notebook.

New in this version
-------------------
enrich_weather(laps, weather)
    Joins nearest weather snapshot onto each lap.
    Adds: TrackTemp, AirTemp, Humidity, Pressure, WindSpeed, WindDirection, Rainfall.

enrich_track_limits(laps, rcm)
    Parses race-control messages for track-limits violations / lap deletions.
    Adds: Track_Limits_Violation (bool), Track_Limits_Count (cumulative per driver/session).

enrich_blue_flags(laps, rcm)
    Detects blue-flag events from RCM and matches them to laps.
    Adds: Blue_Flag (bool).

enrich_session_results(laps, results)
    Joins official session results onto laps (one result row → all laps of that driver).
    Adds: Classified_Position, Grid_Position, Q1_s, Q2_s, Q3_s, Race_Status, Race_Points.

flag_perturbed_laps(df, sector_iqr_multiplier, rcm)
    Extended with Signal 3: RCM event time-series.  The RCM source catches
    short sector-level yellows that the per-lap TrackStatus column misses.
    New columns: RCM_Perturbed (bool), RCM_Flag_Type (str), RCM_Flag_Sector (int).

filter_by_stint_key(laps, stint_key)
    Resolves the previous TODO – returns all laps for a given Stint_key.
"""

from __future__ import annotations

import logging
import pandas as pd
import numpy as np

from config import (
    TEAM_COLORS,
    OUTLIER_THRESHOLD,
    FUEL_CORRECTION,
    RACE_FUEL_KG,
    FUEL_BURN_PER_LAP,
    TRACK_EVO_BINS,
    TRACK_EVO_MIN_LAPS,
    get_min_laps_for_compound,
    MIN_LAPS_MEDIUM,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Compound cleaning
# ─────────────────────────────────────────────────────────────

_UNKNOWN_COMPOUNDS = {"UNKNOWN", "TEST_UNKNOWN"}


def _clean_compounds_inplace(df: pd.DataFrame) -> pd.DataFrame:
    """
    Reassign UNKNOWN / NaN compound labels to the dominant (mode) compound
    for each driver × stint group.  Stints with *no* valid compound at all
    are labelled "MISSING".

    Must be called after Driver_Short and Stint_key have been added to df
    (both are produced earlier in clean_and_enrich_laps).

    The original labels are expected to already be stored in Compound_RAW
    before this function is called.
    """
    def _assign_dominant(group: pd.DataFrame) -> pd.DataFrame:
        real = group.loc[
            ~group["Compound"].isin(_UNKNOWN_COMPOUNDS) & group["Compound"].notna(),
            "Compound",
        ]
        dominant = real.mode()[0] if (not real.empty and real.notna().any()) else "MISSING"
        group = group.copy()
        group["Compound"] = dominant
        return group

    before_missing = (df["Compound"].isna() | df["Compound"].isin(_UNKNOWN_COMPOUNDS)).sum()
    df = (
        df.groupby(["Driver_Short", "Stint_key"], group_keys=False)
        .apply(_assign_dominant)
    )
    after_missing = (df["Compound"] == "MISSING").sum()
    logger.info(
        "  Compound cleaning: %d raw unknown/NaN → %d laps still MISSING after reassignment",
        before_missing, after_missing,
    )
    return df


def clean_and_enrich_laps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Full cleaning + feature-engineering pipeline for a laps DataFrame.
    Safe to call on a combined multi-session frame.

    Columns added
    -------------
    Driver_Short, Team, TeamColor
    LapTime_s
    PitLap, InLap, OutLap
    Stint (1-based), Stint_key, LapInStint, PseudoTyreAge (alias)
    TyreAge_Delta  – |LapInStint – TyreLife|  (only if TyreLife present)
    PseudoSpeed
    ValidLap
    FuelLoad_kg, LapTime_FuelCorrected
    Compound_RAW   – original Compound column before cleaning
    Compound       – cleaned version: UNKNOWN/NaN laps reassigned to the
                     dominant (mode) compound for that driver×stint;
                     stints with no valid compound at all → "MISSING"
    """
    n_input = len(df)
    logger.info("clean_and_enrich_laps: input %d rows", n_input)
    df = df.copy()

    # ── Preserve raw compound label before any cleaning ──────
    df["Compound_RAW"] = df["Compound"].copy()

    # ── Driver / Team ────────────────────────────────────────
    df["Driver"] = df["Driver"].astype("string")
    df["Team"] = (
        df["Driver"]
        .apply(lambda x: x.split("-")[-1] if "-" in str(x) else "Unknown")
        .str.strip()
    )
    df["Driver_Short"] = (
        df["Driver"]
        .apply(lambda x: x.split("-")[0] if "-" in str(x) else str(x))
        .str.strip()
        .str.replace(r"\[\d+\]", "", regex=True)
        .str.strip()
    )

    # ── Backfill missing/blank team labels ───────────────────
    # A driver's team is constant across a weekend, but some sessions arrive
    # with an empty team suffix (e.g. "VER-" → ""), seen in early 2026 practice
    # feeds. Left as-is these blanks colour every affected driver grey in the
    # team-coloured charts. Fill them from the same driver's known team in the
    # other loaded sessions so colouring is consistent everywhere.
    _blank = df["Team"].isna() | df["Team"].isin(["", "Unknown"])
    if _blank.any():
        _known = (
            df.loc[~_blank, ["Driver_Short", "Team"]]
            .groupby("Driver_Short")["Team"]
            .agg(lambda s: s.mode().iloc[0] if not s.mode().empty else s.iloc[0])
        )
        _fill = df.loc[_blank, "Driver_Short"].map(_known)
        df.loc[_blank, "Team"] = _fill.where(_fill.notna(), df.loc[_blank, "Team"])
        n_filled = int(_fill.notna().sum())
        if n_filled:
            logger.info("clean_and_enrich_laps: backfilled team for %d blank-team laps",
                        n_filled)

    # ── Lap time in seconds ──────────────────────────────────
    if pd.api.types.is_timedelta64_dtype(df["LapTime"]):
        df["LapTime_s"] = df["LapTime"].dt.total_seconds()
    elif df["LapTime"].dtype == object:
        def _lt_to_s(v):
            if hasattr(v, "total_seconds"):
                return v.total_seconds()
            try:
                return float(v)
            except (TypeError, ValueError):
                return float("nan")
        df["LapTime_s"] = df["LapTime"].map(_lt_to_s)
    else:
        df["LapTime_s"] = pd.to_numeric(df["LapTime"], errors="coerce")

    n_with_time = df["LapTime_s"].notna().sum()
    logger.info(
        "  LapTime coverage : %d / %d laps (%.1f%%)",
        n_with_time, n_input, 100 * n_with_time / max(n_input, 1),
    )

    # ── Pit flags ───────────────────────────────────────────
    df["InLap"]  = df["PitIn"].notna()
    df["OutLap"] = df["PitOut"].notna()
    df["PitLap"] = df["InLap"] | df["OutLap"]

    # ── Normalise time columns ───────────────────────────────
    for _tcol in ["LapStartTime", "LapTime", "PitIn", "PitOut"]:
        if _tcol not in df.columns:
            continue
        if pd.api.types.is_timedelta64_dtype(df[_tcol]):
            df[_tcol] = df[_tcol].dt.total_seconds()
        else:
            def _to_seconds(v):
                if pd.isna(v) if not hasattr(v, 'total_seconds') else False:
                    return float("nan")
                if hasattr(v, "total_seconds"):
                    return v.total_seconds()
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return float("nan")
            if df[_tcol].dtype == object:
                df[_tcol] = df[_tcol].map(_to_seconds)

    # ── Stint numbering (1-based) ────────────────────────────
    df = df.sort_values(["session_name", "DriverNo", "LapStartTime"])
    df["_new_stint"] = (
        (df.groupby(["session_name", "DriverNo"]).cumcount() == 0) | df["OutLap"]
    )
    df["Stint"] = df.groupby(["session_name", "DriverNo"])["_new_stint"].cumsum()
    df = df.drop(columns=["_new_stint"])

    df["Stint_key"] = (
        df["Stint"].astype("string")
        + "_" + df["Driver_Short"]
        + "_" + df["session_name"]
    )

    df["LapInStint"] = (
        df.groupby(["session_name", "DriverNo", "Stint"]).cumcount() + 1
    )
    df["PseudoTyreAge"] = df["LapInStint"]

    # ── Compound cleaning ────────────────────────────────────
    df = _clean_compounds_inplace(df)

    if "TyreLife" in df.columns:
        df["TyreAge_Delta"] = (df["LapInStint"] - df["TyreLife"]).abs()
        mismatch = (df["TyreAge_Delta"] > 2).sum()
        if mismatch:
            logger.warning(
                "  TyreAge delta > 2 laps on %d rows — check stint detection", mismatch
            )

    # ── Speed aggregate ──────────────────────────────────────
    speed_cols = ["Speed_I1", "Speed_I2", "Speed_FL", "Speed_ST"]
    available  = [c for c in speed_cols if c in df.columns]
    if available:
        df["PseudoSpeed"] = df[available].mean(axis=1, skipna=True)

    # ── Per-session/compound/team outlier reference median ───
    _clean_mask = ~df["PitLap"] & df["LapTime_s"].notna() & (df["LapTime_s"] > 0)
    _clean      = df[_clean_mask]

    _med_sct = (
        _clean.groupby(["session_name", "Compound", "Team"])["LapTime_s"]
        .median().rename("_median_ref")
    )
    _med_sc = (
        _clean.groupby(["session_name", "Compound"])["LapTime_s"]
        .median().rename("_median_sc")
    )
    _med_s = (
        _clean.groupby("session_name")["LapTime_s"]
        .median().rename("_median_s")
    )

    df = df.join(_med_sct, on=["session_name", "Compound", "Team"])
    df = df.join(_med_sc,  on=["session_name", "Compound"])
    df = df.join(_med_s,   on="session_name")
    df["_median_ref"] = (
        df["_median_ref"]
        .fillna(df["_median_sc"])
        .fillna(df["_median_s"])
    )
    df = df.drop(columns=["_median_sc", "_median_s"])

    n_fallback = df["_median_ref"].isna().sum()
    if n_fallback:
        logger.warning("  %d laps have no median reference at any level — check data", n_fallback)

    # ── Valid lap flag ───────────────────────────────────────
    if "IsDeleted" in df.columns:
        _is_deleted = (
            df["IsDeleted"]
            .map(lambda v: str(v).strip().lower() in ("true", "1", "yes")
                 if pd.notna(v) else False)
            .astype(bool)
        )
        _not_deleted = ~_is_deleted
    else:
        _not_deleted = pd.Series(True, index=df.index)
    df["ValidLap"] = (
        (~df["PitLap"])
        & _not_deleted
        & df["LapTime_s"].notna()
        & (df["LapTime_s"] > 0)
        & (df["LapTime_s"] < df["_median_ref"] * OUTLIER_THRESHOLD)
    )
    df = df.drop(columns=["_median_ref"])

    n_valid = df["ValidLap"].sum()
    logger.info(
        "  Valid laps       : %d / %d (%.1f%%)",
        n_valid, n_input, 100 * n_valid / max(n_input, 1),
    )

    # ── Fuel-corrected lap time ──────────────────────────────
    # Race / Sprint: fuel is a function of the RACE lap number — the car
    # starts with the full load and burns it linearly over the race distance
    # regardless of pit stops. Modelling it per stint (the old approach)
    # "refuelled" the car at every stop, which made cross-stint fuel-corrected
    # comparisons invalid.
    #   Race   : burn = RACE_FUEL_KG / total_laps  (auto-adapts per circuit)
    #   Sprint : same linear shape at the fallback burn rate (short distance,
    #            car fuelled for the sprint only, so the level is ~right)
    # Practice / Quali: the true load is unknown (teams run different
    # programmes), so we keep a per-stint model — the level is arbitrary but
    # the within-stint SLOPE (what degradation fits consume) is correct.
    _lap_no = pd.to_numeric(df["LapNo"], errors="coerce")
    _total_laps = _lap_no.groupby(df["session_name"]).transform("max")

    _is_race   = df["session_name"].astype(str).str.startswith("Race_")
    _is_sprint = df["session_name"].astype(str).str.startswith("Sprint_")

    _burn = pd.Series(FUEL_BURN_PER_LAP, index=df.index)
    _burn[_is_race] = (RACE_FUEL_KG / _total_laps[_is_race]).clip(upper=3.0)

    _max_lap_in_stint = df.groupby(
        ["session_name", "DriverNo", "Stint"]
    )["LapInStint"].transform("max")

    _fuel_race  = (_total_laps - _lap_no) * _burn
    _fuel_stint = (_max_lap_in_stint - df["LapInStint"]) * _burn
    df["FuelLoad_kg"] = (
        _fuel_race.where(_is_race | _is_sprint, _fuel_stint).clip(lower=0)
    )
    df["LapTime_FuelCorrected"] = df["LapTime_s"] - (df["FuelLoad_kg"] * FUEL_CORRECTION)

    # ── Team color ───────────────────────────────────────────
    df["TeamColor"] = df["Team"].map(TEAM_COLORS).fillna("#808080")

    assert len(df) == n_input, (
        f"clean_and_enrich_laps changed row count: {n_input} → {len(df)}"
    )
    logger.info("clean_and_enrich_laps: output %d rows  ✓", len(df))
    return df


# ─────────────────────────────────────────────────────────────
# Track-evolution estimation
# ─────────────────────────────────────────────────────────────

def enrich_track_evolution(
    laps: pd.DataFrame,
    n_bins: int = TRACK_EVO_BINS,
    min_laps: int = TRACK_EVO_MIN_LAPS,
) -> pd.DataFrame:
    """
    Estimate field-wide track evolution (grip gain as rubber goes down) per
    session and remove it from the fuel-corrected lap times.

    The track typically gains 0.5–1.5 s of grip across a session. Left in the
    data, that improvement cancels part of the tyre-degradation signal — deg
    slopes come out too flat or even negative ("the tyre got faster"), which
    is track evolution, not tyre behaviour.

    Model (per session, on clean laps only)
    ---------------------------------------
    LapTime_FuelCorrected ~ driver + TyreAge×compound + session-time bin

    Driver dummies absorb car/driver pace, per-compound tyre-age slopes absorb
    degradation, and the session-time bin coefficients are the evolution
    estimate. Solved with ordinary least squares (np.linalg.lstsq). The bin
    effects are then linearly interpolated over session time (a step-wise
    correction would inject artificial jumps into within-stint deg slopes).

    Practice sessions: the pool is restricted to SHORT runs (stints of
    ≤ 8 laps). Long practice runs are race sims on heavy, unknown fuel —
    including them makes the "evolution" estimate track the run-programme mix
    (verified on 2026 Australia FP2: ±3.4 s swings) instead of grip. Short
    runs are all on comparably low fuel throughout the session.

    Races: the trend also absorbs any systematic error in the linear fuel
    model, which is exactly what the degradation fits want removed.

    Columns added
    -------------
    TrackEvo_s             – estimated field-wide pace offset vs session start
                             (negative = field got faster). 0 when the session
                             has too little data to fit.
    LapTime_TrackCorrected – LapTime_FuelCorrected − TrackEvo_s. Use this for
                             degradation analysis.

    Guard rails
    -----------
    - Sessions with < min_laps clean laps, or < 3 usable time bins → no fit.
    - If tyre age and session time are near-collinear in the pool (|r| > 0.97,
      e.g. a sprint where nobody stops), the two effects cannot be separated
      → no fit, logged as a warning.
    """
    laps = laps.copy()
    laps["TrackEvo_s"] = 0.0

    has_perturb = "Perturbed_Lap" in laps.columns
    if not has_perturb:
        logger.warning(
            "enrich_track_evolution: Perturbed_Lap column missing — "
            "call after flag_perturbed_laps for a cleaner fit."
        )

    _age_col = "TyreAge" if "TyreAge" in laps.columns else "LapInStint"

    # Stint length (all laps, incl. pit laps) for the practice short-run filter
    _stint_len = laps.groupby(
        ["session_name", "DriverNo", "Stint"]
    )["LapInStint"].transform("max")

    for sess in laps["session_name"].unique():
        s_mask  = laps["session_name"] == sess
        is_race = str(sess).startswith(("Race_", "Sprint_"))

        pool_mask = (
            s_mask
            & laps["ValidLap"]
            & laps["LapTime_FuelCorrected"].notna()
            & pd.to_numeric(laps["LapStartTime"], errors="coerce").notna()
            & (laps["LapInStint"] >= 2)          # skip out-lap-adjacent laps
        )
        if has_perturb:
            pool_mask &= ~laps["Perturbed_Lap"]
        if "Dirty_Air" in laps.columns:
            pool_mask &= ~laps["Dirty_Air"]
        if not is_race:
            pool_mask &= _stint_len <= 8         # practice: short runs only

        pool = laps[pool_mask]
        if len(pool) < min_laps:
            logger.info(
                "enrich_track_evolution: %s — only %d clean laps (<%d), skipped",
                sess, len(pool), min_laps,
            )
            continue

        t   = pd.to_numeric(pool["LapStartTime"], errors="coerce")
        age = pd.to_numeric(pool[_age_col], errors="coerce").fillna(
            pool["LapInStint"]
        )

        # Identifiability guard: age vs session time collinearity
        r = np.corrcoef(t, age)[0, 1] if t.nunique() > 1 and age.nunique() > 1 else 1.0
        if not np.isfinite(r) or abs(r) > 0.97:
            logger.warning(
                "enrich_track_evolution: %s — tyre age and session time are "
                "collinear (r=%.3f), evolution not identifiable, skipped",
                sess, r,
            )
            continue

        # Session-time bins (quantile → roughly equal lap counts per bin).
        # Adaptive count: at least ~20 laps per bin, otherwise sparse bins
        # containing only one or two drivers confound the bin effect with
        # those drivers' identities and the fit explodes.
        n_bins_req = int(np.clip(len(pool) // 20, 3, n_bins))
        try:
            bins, edges = pd.qcut(
                t, q=n_bins_req, labels=False, retbins=True, duplicates="drop"
            )
        except ValueError:
            continue
        n_eff_bins = int(bins.max()) + 1
        if n_eff_bins < 3:
            continue

        # ── Design matrix ────────────────────────────────────
        y = pool["LapTime_FuelCorrected"].values.astype(float)

        drivers   = pd.get_dummies(pool["Driver_Short"], drop_first=False)
        compounds = pool["Compound"].astype(str)
        age_cols  = {}
        for comp in compounds.unique():
            age_cols[f"_age_{comp}"] = np.where(compounds == comp, age, 0.0)
        age_df   = pd.DataFrame(age_cols, index=pool.index)
        bin_dum  = pd.get_dummies(bins, prefix="_bin", drop_first=True)

        X = pd.concat([drivers, age_df, bin_dum], axis=1).astype(float)
        X_cols = list(X.columns)

        # Mild ridge penalty on the bin coefficients only: shrinks bins whose
        # laps come from few drivers toward 0 instead of letting them blow up,
        # while leaving driver and tyre-age effects untouched.
        _lam = np.zeros(len(X_cols))
        _lam[[i for i, c in enumerate(X_cols) if c.startswith("_bin_")]] = 4.0
        Xv = X.values
        try:
            beta = np.linalg.solve(Xv.T @ Xv + np.diag(_lam), Xv.T @ y)
        except np.linalg.LinAlgError:
            try:
                beta, *_ = np.linalg.lstsq(Xv, y, rcond=None)
            except np.linalg.LinAlgError:
                logger.warning(
                    "enrich_track_evolution: %s — fit failed, skipped", sess)
                continue

        coef = dict(zip(X_cols, beta))
        # Evolution per bin, relative to the first bin (dropped dummy = 0)
        evo_by_bin = {0: 0.0}
        for b in range(1, n_eff_bins):
            evo_by_bin[b] = float(coef.get(f"_bin_{b}", 0.0))

        # Interpolate over bin CENTERS so the correction is a smooth curve —
        # a step function would put artificial jumps inside stints that span
        # a bin boundary, distorting their fitted deg slopes.
        centers = t.groupby(bins).mean()
        xp = centers.sort_index().values.astype(float)
        fp = np.array([evo_by_bin[b] for b in sorted(evo_by_bin)])

        t_all = pd.to_numeric(laps.loc[s_mask, "LapStartTime"], errors="coerce")
        evo_all = np.interp(t_all.values.astype(float), xp, fp)
        laps.loc[s_mask, "TrackEvo_s"] = np.where(
            np.isfinite(evo_all), evo_all, 0.0
        )

        logger.info(
            "enrich_track_evolution: %s — %d clean laps (%s), %d bins, "
            "evolution %.3f → %.3f s vs session start",
            sess, len(pool), "all stints" if is_race else "short runs ≤8 laps",
            n_eff_bins, fp.min(), fp.max(),
        )

    laps["LapTime_TrackCorrected"] = laps["LapTime_FuelCorrected"] - laps["TrackEvo_s"]
    return laps


# ─────────────────────────────────────────────────────────────
# Stint analysis
# ─────────────────────────────────────────────────────────────

def _trimmed_median(s: pd.Series) -> float:
    """Median of laps that fall within the 10th–90th percentile range."""
    if len(s) < 4:
        return s.median()
    lo, hi = s.quantile([0.10, 0.90])
    trimmed = s[s.between(lo, hi)]
    return trimmed.median() if len(trimmed) else s.median()


def _degradation_rate(group: pd.DataFrame) -> pd.Series:
    """
    Linear tyre-degradation fit for one stint.

    Uses LapTime_TrackCorrected (fuel- AND track-evolution-corrected) when
    available, falling back to LapTime_FuelCorrected. The first flying lap of
    the stint is dropped when the stint is long enough (≥5 laps) — the tyre
    is still coming up to temperature there, and that warm-up transient
    contaminates a linear fit.

    Returns
    -------
    Stint_Deg_Rate – slope in s/lap of tyre age
    Stint_Deg_R2   – fit R² (kept for reference; NOT a good stint selector,
                     because R² is proportional to |slope| — a genuinely flat
                     stint always has low R²)
    Stint_Deg_SE   – standard error of the slope. Use this for reliability:
                     it is small when the stint is long and the laps are
                     consistent, regardless of how steep the slope is.
    """
    nan_result = pd.Series({
        "Stint_Deg_Rate": np.nan, "Stint_Deg_R2": np.nan, "Stint_Deg_SE": np.nan,
    })
    if len(group) < 3:
        return nan_result

    # Use the real tyre age (FastF1 TyreLife → TyreAge) as the degradation
    # x-axis; fall back to LapInStint only if it is unavailable.
    _age_col = "TyreAge" if "TyreAge" in group.columns else "LapInStint"
    _y_col = ("LapTime_TrackCorrected"
              if "LapTime_TrackCorrected" in group.columns
              else "LapTime_FuelCorrected")

    g = group
    if "Dirty_Air" in g.columns:
        g_clean = g[~g["Dirty_Air"]]
        if len(g_clean) >= 3:                    # keep fit possible in traffic-heavy stints
            g = g_clean
    if len(g) >= 5:
        g = g[g[_age_col] > g[_age_col].min()]   # drop the warm-up lap

    x = g[_age_col].values.astype(float)
    y = g[_y_col].values.astype(float)
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 3:
        return nan_result

    x, y = x[mask], y[mask]
    if np.ptp(x) == 0:
        return nan_result
    try:
        coeffs = np.polyfit(x, y, 1)
        slope  = float(coeffs[0])
        y_hat  = np.polyval(coeffs, x)
        n      = len(x)
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        ss_x   = float(np.sum((x - x.mean()) ** 2))
        r2     = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
        se     = (np.sqrt((ss_res / (n - 2)) / ss_x)
                  if (n > 2 and ss_x > 0) else np.nan)
        return pd.Series({
            "Stint_Deg_Rate": round(slope, 4),
            "Stint_Deg_R2":   round(r2,    4),
            "Stint_Deg_SE":   round(se,    4) if np.isfinite(se) else np.nan,
        })
    except (np.linalg.LinAlgError, ValueError):
        return nan_result


def analyze_stints(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compound-specific stint aggregation with validity flags, degradation
    rates, trimmed pace metrics, and four ranking dimensions.

    Ranking columns produced
    ------------------------
    Stint_Rank_In_Session      – within [session, driver, compound]
    Stint_Rank_Across_Sessions – within [driver, compound] ignoring session
    Stint_Rank_No_Compound     – within [session, driver] ignoring compound
    Stint_Rank_Overall         – global, across all drivers/sessions/compounds
    All ranks are NaN for invalid stints.  Rank 1 = fastest.
    """
    valid = df[df["ValidLap"]].copy()

    _tyre_start_col = "TyreAge" if "TyreAge" in valid.columns else "LapInStint"

    _agg_kwargs = dict(
        Stint_Avg_Lap    =("LapTime_s",             "mean"),
        Stint_Median_Lap =("LapTime_s",             "median"),
        Stint_Rep_Lap    =("LapTime_s",             _trimmed_median),
        Stint_Best_Lap   =("LapTime_s",             "min"),
        Stint_P10_Lap    =("LapTime_s",             lambda s: s.quantile(0.10)),
        Stint_P90_Lap    =("LapTime_s",             lambda s: s.quantile(0.90)),
        Stint_Std_Dev    =("LapTime_s",             "std"),
        Stint_Laps_Count =("LapTime_s",             "count"),
        Stint_FuelCorr   =("LapTime_FuelCorrected", _trimmed_median),
        Stint_Start_Tyre =(_tyre_start_col,         "min"),
        Stint_Max_Tyre   =(_tyre_start_col,         "max"),
    )
    if "LapTime_TrackCorrected" in valid.columns:
        _agg_kwargs["Stint_TrackCorr"] = ("LapTime_TrackCorrected", _trimmed_median)

    stint_summary = (
        valid.groupby(["session_name", "Driver_Short", "Team", "Stint", "Compound"])
        .agg(**_agg_kwargs)
        .round(3)
        .reset_index()
    )

    deg = (
        valid.groupby(["session_name", "Driver_Short", "Stint"])
        .apply(_degradation_rate, include_groups=False)
        .reset_index()
    )
    if "Stint_Deg_R2" in deg.columns:
        n_deg  = deg["Stint_Deg_Rate"].notna().sum()
        n_good = (deg["Stint_Deg_R2"] >= 0.75).sum()
        n_weak = (deg["Stint_Deg_R2"].between(0.4, 0.75)).sum()
        logger.info(
            "  Deg rate computed on %d stints: %d good fit (R²≥0.75), "
            "%d weak (0.40–0.75), %d poor/NaN",
            n_deg, n_good, n_weak, n_deg - n_good - n_weak,
        )
    stint_summary = stint_summary.merge(
        deg, on=["session_name", "Driver_Short", "Stint"], how="left"
    )

    stint_summary["Min_Laps_Required"] = (
        stint_summary["Compound"].apply(get_min_laps_for_compound).fillna(MIN_LAPS_MEDIUM)
    )
    stint_summary["Valid_Stint"] = (
        stint_summary["Stint_Laps_Count"] >= stint_summary["Min_Laps_Required"]
    )

    _best_in_session_compound = (
        stint_summary[stint_summary["Valid_Stint"]]
        .groupby(["session_name", "Compound"])["Stint_Rep_Lap"]
        .min().rename("_best_sc")
    )
    _best_across_sessions = (
        stint_summary[stint_summary["Valid_Stint"]]
        .groupby("Compound")["Stint_Rep_Lap"]
        .min().rename("_best_c")
    )
    stint_summary = stint_summary.join(_best_in_session_compound, on=["session_name", "Compound"])
    stint_summary = stint_summary.join(_best_across_sessions, on="Compound")
    stint_summary["Gap_To_Best_In_Session_s"]      = (stint_summary["Stint_Rep_Lap"] - stint_summary["_best_sc"]).round(3)
    stint_summary["Gap_To_Best_Across_Sessions_s"] = (stint_summary["Stint_Rep_Lap"] - stint_summary["_best_c"]).round(3)
    stint_summary = stint_summary.drop(columns=["_best_sc", "_best_c"])

    _v = stint_summary["Valid_Stint"]

    stint_summary["Stint_Rank_In_Session"] = np.nan
    stint_summary.loc[_v, "Stint_Rank_In_Session"] = (
        stint_summary[_v]
        .groupby(["session_name", "Driver_Short", "Compound"])["Stint_Rep_Lap"]
        .rank(method="dense", ascending=True)
    )

    stint_summary["Stint_Rank_Across_Sessions"] = np.nan
    stint_summary.loc[_v, "Stint_Rank_Across_Sessions"] = (
        stint_summary[_v]
        .groupby(["Driver_Short", "Compound"])["Stint_Rep_Lap"]
        .rank(method="dense", ascending=True)
    )

    stint_summary["Stint_Rank_No_Compound"] = np.nan
    stint_summary.loc[_v, "Stint_Rank_No_Compound"] = (
        stint_summary[_v]
        .groupby(["session_name", "Driver_Short"])["Stint_Rep_Lap"]
        .rank(method="dense", ascending=True)
    )

    stint_summary["Stint_Rank_Overall"] = np.nan
    stint_summary.loc[_v, "Stint_Rank_Overall"] = (
        stint_summary.loc[_v, "Stint_Rep_Lap"]
        .rank(method="dense", ascending=True)
    )

    rank_cols = [
        "Stint_Rank_In_Session", "Stint_Rank_Across_Sessions",
        "Stint_Rank_No_Compound", "Stint_Rank_Overall",
    ]
    for col in rank_cols:
        stint_summary[col] = stint_summary[col].astype("Int64")

    n_total = len(stint_summary)
    n_valid = _v.sum()
    logger.info(
        "analyze_stints: %d stints total, %d valid (%.0f%%)",
        n_total, n_valid, 100 * n_valid / max(n_total, 1),
    )
    logger.debug(
        "  Avg deg rate by compound:\n%s",
        stint_summary[_v].groupby("Compound")[["Stint_Deg_Rate", "Stint_Deg_R2"]]
        .mean().round(4).to_string(),
    )

    return stint_summary


# ─────────────────────────────────────────────────────────────
# Field-level degradation curves
# ─────────────────────────────────────────────────────────────

def field_deg_curves(
    laps: pd.DataFrame,
    compound: str,
    baseline_laps: int = 3,
    min_stint_laps: int = 5,
    min_stints_per_age: int = 3,
) -> dict | None:
    """
    Pool every clean stint on *compound* into a field-level degradation curve,
    plus per-team median curves and a per-driver deviation ranking.

    This is the paddock-style view of degradation: instead of fitting each
    stint in isolation (noisy), every stint contributes its lap-time delta
    vs its own early-stint baseline, and the pooled median at each tyre age
    is the field curve. Individual teams/drivers are then read as deviations
    from that curve — much more robust than comparing per-stint slopes.

    Per stint (≥ min_stint_laps clean laps):
        Delta_s(lap) = corrected lap time − median of the stint's first
                       `baseline_laps` clean laps
    Uses LapTime_TrackCorrected when present (fuel + track evolution removed),
    else LapTime_FuelCorrected.

    Returns None when there is not enough data, else a dict of DataFrames:
    curve       – _age, median, q25, q75, n_stints   (ages with enough stints)
    team_curves – Team, _age, median, n              (per-team median deltas)
    driver_dev  – Driver_Short, Team, Avg_Dev_s, N_Laps
                  Avg_Dev_s = mean residual vs the field median at equal tyre
                  age; negative = degrades less than the field.
    """
    _y   = ("LapTime_TrackCorrected"
            if "LapTime_TrackCorrected" in laps.columns
            else "LapTime_FuelCorrected")
    _age = "TyreAge" if "TyreAge" in laps.columns else "LapInStint"

    pool = laps[
        laps["ValidLap"]
        & (laps["Compound"] == compound)
        & laps[_y].notna()
    ].copy()
    if "Perturbed_Lap" in pool.columns:
        pool = pool[~pool["Perturbed_Lap"]]
    if "Dirty_Air" in pool.columns:
        pool = pool[~pool["Dirty_Air"]]
    if pool.empty:
        return None

    pool["_age"] = (
        pd.to_numeric(pool[_age], errors="coerce")
        .fillna(pool["LapInStint"])
        .round()
        .astype(int)
    )

    parts = []
    for (sess, drv_no, stint), g in pool.groupby(
        ["session_name", "DriverNo", "Stint"]
    ):
        if len(g) < min_stint_laps:
            continue
        g = g.sort_values("_age")
        base = g[_y].head(baseline_laps).median()
        if pd.isna(base):
            continue
        d = g[["Driver_Short", "Team", "_age"]].copy()
        d["Delta_s"]   = g[_y] - base
        d["_stint_id"] = f"{sess}|{drv_no}|{stint}"
        parts.append(d)
    if not parts:
        return None
    long_df = pd.concat(parts, ignore_index=True)

    curve = (
        long_df.groupby("_age")
        .agg(
            median  =("Delta_s",   "median"),
            q25     =("Delta_s",   lambda s: s.quantile(0.25)),
            q75     =("Delta_s",   lambda s: s.quantile(0.75)),
            n_stints=("_stint_id", "nunique"),
        )
        .reset_index()
    )
    curve = curve[curve["n_stints"] >= min_stints_per_age]
    if len(curve) < 3:
        return None

    team_curves = (
        long_df[long_df["_age"].isin(curve["_age"])]
        .groupby(["Team", "_age"])
        .agg(median=("Delta_s", "median"), n=("Delta_s", "size"))
        .reset_index()
    )
    team_curves = team_curves[team_curves["n"] >= 2]

    fm = curve.set_index("_age")["median"]
    long_df["_resid"] = long_df["Delta_s"] - long_df["_age"].map(fm)
    driver_dev = (
        long_df.dropna(subset=["_resid"])
        .groupby(["Driver_Short", "Team"])
        .agg(Avg_Dev_s=("_resid", "mean"), N_Laps=("_resid", "size"))
        .reset_index()
    )
    driver_dev = driver_dev[driver_dev["N_Laps"] >= 8]

    logger.info(
        "field_deg_curves: %s — %d stints pooled, ages %d–%d, %d drivers ranked",
        compound, long_df["_stint_id"].nunique(),
        int(curve["_age"].min()), int(curve["_age"].max()), len(driver_dev),
    )
    return {"curve": curve, "team_curves": team_curves, "driver_dev": driver_dev}


# ─────────────────────────────────────────────────────────────
# Tyre-cliff detection
# ─────────────────────────────────────────────────────────────

def detect_stint_cliffs(
    laps: pd.DataFrame,
    min_stint_laps: int = 10,
    min_tail: int = 3,
    min_extra_slope: float = 0.10,
    min_sse_gain: float = 0.25,
    min_base_slope: float = -0.10,
    min_cliff_slope: float = 0.05,
) -> pd.DataFrame:
    """
    Detect degradation cliffs — the point where a tyre's slow linear phase
    turns into a sharply steeper one — in every long clean stint.

    Model: two-segment hinge fit  y = a + b·x + c·max(0, x − x0), scanned
    over candidate breakpoints x0. A cliff is reported when
      - the post-cliff EXTRA slope c ≥ min_extra_slope (s/lap on top of the
        base rate),
      - the hinge fit explains ≥ min_sse_gain more of the variance than a
        plain straight line (so noise doesn't fake a cliff),
      - at least min_tail laps lie after the breakpoint,
      - the base phase is not strongly IMPROVING (base slope ≥
        min_base_slope) and the post phase genuinely degrades (total slope
        ≥ min_cliff_slope). Without these two, the tyre warm-up phase or a
        post-Safety-Car pace recovery gets mislabelled as a "cliff" — those
        are improving→degrading transitions, not late-stint drop-offs.

    Uses LapTime_TrackCorrected (fuel + evolution removed) so a cliff is a
    tyre event, not a fuel or grip artefact. Dirty-air laps are excluded
    when the column exists.

    Returns one row per detected cliff:
    session_name, Driver_Short, Team, Stint, Compound,
    Cliff_Age (tyre age where it starts), Base_Slope (s/lap before),
    Cliff_Slope (s/lap after = base + extra), N_Laps, Tail_Laps.
    """
    _y   = ("LapTime_TrackCorrected"
            if "LapTime_TrackCorrected" in laps.columns
            else "LapTime_FuelCorrected")
    _age = "TyreAge" if "TyreAge" in laps.columns else "LapInStint"

    pool = laps[laps["ValidLap"] & laps[_y].notna()].copy()
    if "Perturbed_Lap" in pool.columns:
        pool = pool[~pool["Perturbed_Lap"]]
    if "Dirty_Air" in pool.columns:
        pool = pool[~pool["Dirty_Air"]]
    if pool.empty:
        return pd.DataFrame()

    rows = []
    for (sess, drv_no, stint), g in pool.groupby(
        ["session_name", "DriverNo", "Stint"]
    ):
        if len(g) < min_stint_laps:
            continue
        g = g.sort_values(_age)
        x = pd.to_numeric(g[_age], errors="coerce").values.astype(float)
        y = g[_y].values.astype(float)
        ok = np.isfinite(x) & np.isfinite(y)
        x, y = x[ok], y[ok]
        if len(x) < min_stint_laps or np.ptp(x) == 0:
            continue

        # Plain linear reference
        X1 = np.column_stack([np.ones_like(x), x])
        beta1, *_ = np.linalg.lstsq(X1, y, rcond=None)
        sse_lin = float(np.sum((y - X1 @ beta1) ** 2))
        if sse_lin <= 0:
            continue

        # Hinge scan: breakpoint must leave ≥4 laps before, ≥min_tail after
        best = None
        for k in range(4, len(x) - min_tail + 1):
            x0 = x[k - 1]
            hinge = np.maximum(0.0, x - x0)
            if hinge.max() == 0:
                continue
            X2 = np.column_stack([np.ones_like(x), x, hinge])
            try:
                beta2, *_ = np.linalg.lstsq(X2, y, rcond=None)
            except np.linalg.LinAlgError:
                continue
            sse2 = float(np.sum((y - X2 @ beta2) ** 2))
            if best is None or sse2 < best[0]:
                best = (sse2, x0, beta2, len(x) - k)

        if best is None:
            continue
        sse2, x0, beta2, tail_n = best
        base  = float(beta2[1])
        extra = float(beta2[2])
        gain  = 1.0 - sse2 / sse_lin
        if (extra < min_extra_slope or gain < min_sse_gain
                or base < min_base_slope
                or base + extra < min_cliff_slope):
            continue

        rows.append(dict(
            session_name=sess,
            Driver_Short=g["Driver_Short"].iloc[0],
            Team=g["Team"].iloc[0],
            Stint=stint,
            Compound=g["Compound"].iloc[0],
            Cliff_Age=float(x0),
            Base_Slope=round(float(beta2[1]), 4),
            Cliff_Slope=round(float(beta2[1] + extra), 4),
            N_Laps=int(len(x)),
            Tail_Laps=int(tail_n),
        ))

    out = pd.DataFrame(rows)
    logger.info("detect_stint_cliffs: %d cliffs found in %d candidate stints",
                len(out), pool.groupby(["session_name", "DriverNo", "Stint"]).ngroups)
    return out


# ─────────────────────────────────────────────────────────────
# Compound pace offsets (race sessions)
# ─────────────────────────────────────────────────────────────

def compound_offsets(
    laps: pd.DataFrame,
    max_age: int = 10,
    min_laps_per_side: int = 3,
) -> pd.DataFrame:
    """
    Estimate the pace offset between tyre compounds from RACE/Sprint laps.

    Race laps only: the race fuel model is anchored to the real race lap
    number, so corrected times are comparable across compounds. (Practice is
    excluded on purpose — fuel loads there are unknown and differ by run
    programme, which would contaminate the offsets.)

    Method: within each driver, take the trimmed median of corrected lap
    times on each compound at tyre age ≤ max_age; difference the compounds
    within the driver (cancels car+driver pace); aggregate the per-driver
    differences across the field (median + IQR).

    Returns one row per compound pair:
    Pair ("SOFT → MEDIUM"), Offset_s (median; positive = second compound
    slower), Q25, Q75, N_Drivers.
    """
    _y   = ("LapTime_TrackCorrected"
            if "LapTime_TrackCorrected" in laps.columns
            else "LapTime_FuelCorrected")
    _age = "TyreAge" if "TyreAge" in laps.columns else "LapInStint"

    pool = laps[
        laps["session_name"].astype(str).str.startswith(("Race_", "Sprint_"))
        & laps["ValidLap"]
        & laps[_y].notna()
    ].copy()
    if "Perturbed_Lap" in pool.columns:
        pool = pool[~pool["Perturbed_Lap"]]
    if "Dirty_Air" in pool.columns:
        pool = pool[~pool["Dirty_Air"]]
    pool = pool[pd.to_numeric(pool[_age], errors="coerce") <= max_age]
    if pool.empty:
        return pd.DataFrame()

    per_dc = (
        pool.groupby(["Driver_Short", "Compound"])[_y]
        .agg(rep=_trimmed_median, n="size")
        .reset_index()
    )
    per_dc = per_dc[per_dc["n"] >= min_laps_per_side]

    order = ["SOFT", "MEDIUM", "HARD", "INTER", "WET"]
    comps = [c for c in order if c in per_dc["Compound"].unique()]
    rows = []
    for i, c1 in enumerate(comps):
        for c2 in comps[i + 1:]:
            wide = per_dc.pivot(index="Driver_Short", columns="Compound",
                                values="rep")
            if c1 not in wide.columns or c2 not in wide.columns:
                continue
            diff = (wide[c2] - wide[c1]).dropna()
            if len(diff) < 3:
                continue
            rows.append(dict(
                Pair=f"{c1} → {c2}",
                Offset_s=round(float(diff.median()), 3),
                Q25=round(float(diff.quantile(0.25)), 3),
                Q75=round(float(diff.quantile(0.75)), 3),
                N_Drivers=int(len(diff)),
            ))
    out = pd.DataFrame(rows)
    if not out.empty:
        logger.info("compound_offsets: %s",
                    "; ".join(f"{r.Pair}: {r.Offset_s:+.2f}s (n={r.N_Drivers})"
                              for r in out.itertuples()))
    return out


# ─────────────────────────────────────────────────────────────
# Dirty-air flagging (races)
# ─────────────────────────────────────────────────────────────

def flag_dirty_air(laps: pd.DataFrame, threshold_s: float = 2.0) -> pd.DataFrame:
    """
    Flag race laps run close behind another car ("dirty air").

    A car within ~2 s of the car ahead loses downforce and slides more, and
    within ~1 s it is usually pace-limited by the leader — either way the lap
    says nothing about the tyre. Degradation fits and field curves exclude
    these laps.

    Gap estimate: within each race session and lap number, cars are ordered
    by Position and the gap is the difference in end-of-lap timestamps
    between consecutive classification positions. (Approximation: lapped
    traffic sitting directly ahead is not caught, but blue-flag laps are
    already flagged separately.)

    Column added: Dirty_Air (bool, False outside races / when Position or
    timing data is missing).
    """
    laps = laps.copy()
    laps["Dirty_Air"] = False

    need = {"Position", "LapNo", "LapStartTime", "LapTime_s"}
    if not need.issubset(laps.columns):
        logger.info("flag_dirty_air: required columns missing — no laps flagged")
        return laps

    is_race = laps["session_name"].astype(str).str.startswith(("Race_", "Sprint_"))
    race = laps[is_race].copy()
    if race.empty:
        return laps

    race["_t_end"] = (
        pd.to_numeric(race["LapStartTime"], errors="coerce")
        + pd.to_numeric(race["LapTime_s"], errors="coerce")
    )
    race["_pos"] = pd.to_numeric(race["Position"], errors="coerce")
    race = race[race["_t_end"].notna() & race["_pos"].notna()]

    race = race.sort_values(["session_name", "LapNo", "_pos"])
    grp = race.groupby(["session_name", "LapNo"])
    gap_ahead = race["_t_end"] - grp["_t_end"].shift(1)
    pos_gap   = race["_pos"] - grp["_pos"].shift(1)

    dirty_idx = race.index[
        gap_ahead.notna() & (gap_ahead >= 0) & (gap_ahead < threshold_s)
        & (pos_gap == 1)
    ]
    laps.loc[dirty_idx, "Dirty_Air"] = True

    n = int(laps["Dirty_Air"].sum())
    logger.info("flag_dirty_air: %d race laps flagged (< %.1f s behind the car ahead)",
                n, threshold_s)
    return laps


# ─────────────────────────────────────────────────────────────
# Quali-sim identification
# ─────────────────────────────────────────────────────────────

def identify_quali_sim_laps(
    df: pd.DataFrame,
    delta_pct_threshold: float = 0.5,
    max_tyre_age: int = 4,
) -> pd.DataFrame:
    df = df.copy()
    valid = df[df["ValidLap"]].copy()

    best_laps = (
        valid.groupby(["session_name", "Driver_Short", "Compound"])["LapTime_s"]
        .min().reset_index().rename(columns={"LapTime_s": "Best_Lap"})
    )
    valid = valid.merge(best_laps, on=["session_name", "Driver_Short", "Compound"], how="left")
    valid["Delta_To_Best_pct"] = (valid["LapTime_s"] - valid["Best_Lap"]) / valid["Best_Lap"] * 100

    # Prefer the real tyre age; fall back to PseudoTyreAge per-row where the
    # raw TyreAge is missing.
    _age = (valid["TyreAge"].fillna(valid["PseudoTyreAge"])
            if "TyreAge" in valid.columns else valid["PseudoTyreAge"])
    valid["Is_Quali_Sim"] = (
        (valid["Delta_To_Best_pct"] <= delta_pct_threshold)
        & (_age <= max_tyre_age)
    )

    df = df.merge(
        valid[["session_name", "Driver_Short", "Compound", "LapNo", "Is_Quali_Sim"]],
        on=["session_name", "LapNo", "Driver_Short", "Compound"],
        how="left",
    )
    df["Is_Quali_Sim"] = df["Is_Quali_Sim"].fillna(False)
    return df


# ─────────────────────────────────────────────────────────────
# Best laps per driver/compound (for leaderboard cards)
# ─────────────────────────────────────────────────────────────

def best_laps_table(df: pd.DataFrame) -> pd.DataFrame:
    """Return the best valid lap per driver per compound per session."""
    valid = df[df["ValidLap"]].copy()
    idx = valid.groupby(["session_name", "Driver_Short", "Compound"])["LapTime_s"].idxmin()
    return valid.loc[idx].reset_index(drop=True)


def format_lap_time(seconds: float) -> str:
    """Convert float seconds → 'm:ss.mmm' string."""
    if pd.isna(seconds) or seconds <= 0:
        return "—"
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:06.3f}"


# ─────────────────────────────────────────────────────────────
# RCM normalisation helper (shared by flag_perturbed_laps,
# enrich_track_limits, enrich_blue_flags)
# ─────────────────────────────────────────────────────────────

def _normalize_rcm(rcm: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise a raw race-control-messages DataFrame for downstream use.

    Transformations
    ---------------
    - Time → Time_s (float seconds from session start)
    - Flag, Category, Scope, Message → str, stripped, NA→""
    - Sector → float (NaN when absent)
    - RacingNumber → str, stripped (leading zeros preserved; "" when absent)

    Returns a copy; the original is unmodified.
    """
    rcm = rcm.copy()

    # ── Time → float seconds ─────────────────────────────────
    if "Time" in rcm.columns:
        if pd.api.types.is_timedelta64_dtype(rcm["Time"]):
            rcm["Time_s"] = rcm["Time"].dt.total_seconds()
        elif rcm["Time"].dtype == object:
            def _t(v):
                if hasattr(v, "total_seconds"):
                    return v.total_seconds()
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return float("nan")
            rcm["Time_s"] = rcm["Time"].map(_t)
        else:
            rcm["Time_s"] = pd.to_numeric(rcm["Time"], errors="coerce")
    else:
        rcm["Time_s"] = np.nan

    # ── String columns ───────────────────────────────────────
    for col in ("Flag", "Category", "Scope", "Message"):
        if col in rcm.columns:
            rcm[col] = rcm[col].fillna("").astype(str).str.strip()
        else:
            rcm[col] = ""

    # ── Sector as numeric ────────────────────────────────────
    if "Sector" in rcm.columns:
        rcm["Sector"] = pd.to_numeric(rcm["Sector"], errors="coerce")
    else:
        rcm["Sector"] = np.nan

    # ── RacingNumber as string ───────────────────────────────
    if "RacingNumber" in rcm.columns:
        rcm["RacingNumber"] = rcm["RacingNumber"].fillna("").astype(str).str.strip()
    else:
        rcm["RacingNumber"] = ""

    # ── Lap as numeric ───────────────────────────────────────
    if "Lap" in rcm.columns:
        rcm["Lap"] = pd.to_numeric(rcm["Lap"], errors="coerce")

    return rcm


# ─────────────────────────────────────────────────────────────
# Perturbed-lap flagging  (Signal 1 + 2 + NEW Signal 3 via RCM)
# ─────────────────────────────────────────────────────────────

_PERTURB_CODES: dict[str, str] = {
    "2": "Yellow",
    "3": "DoubleYellow",
    "4": "SafetyCar",
    "5": "RedFlag",
    "6": "VSC",
    "7": "VSCEnding",
}
_PERTURB_SET = set(_PERTURB_CODES.keys())

# RCM flag values that disrupt pace (yellow/SC/VSC/red).
# Blue, black-and-white, chequered etc. do NOT slow the whole lap.
_RCM_PERTURB_FLAGS = {"YELLOW", "DOUBLE YELLOW", "RED", "RED FLAG"}
_RCM_PERTURB_CATS  = {"safetycar", "virtualsafetycar", "vsc", "redflag"}


def flag_perturbed_laps(
    df: pd.DataFrame,
    sector_iqr_multiplier: float = 2.5,
    rcm: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Add three complementary perturbation signals to the laps DataFrame.

    Columns added
    -------------
    TrackStatus_Flag   – str  : worst flag code seen during this lap
                                ("Clear", "Yellow", "DoubleYellow",
                                 "SafetyCar", "VSC", "VSCEnding", "RedFlag")
    Sector_Anomaly     – bool : any sector time > sector_iqr_multiplier×IQR
                                above driver's per-session/compound 75th pct
    RCM_Perturbed      – bool : an RCM yellow/SC/VSC/red event's timestamp
                                falls within [LapStartTime, LapStartTime+LapTime_s]
                                (catches short sector yellows invisible in
                                 the per-lap TrackStatus column)
    RCM_Flag_Type      – str  : Flag value from the RCM event ("YELLOW" etc.),
                                or "" when RCM_Perturbed is False
    RCM_Flag_Sector    – int  : sector number (1/2/3) when Scope=="Sector",
                                0 when the flag covers the whole track or
                                sector information is unavailable
    Perturbed_Lap      – bool : True when ANY of the three signals fires.
                                Filter on ~Perturbed_Lap for clean pace analysis.

    Parameters
    ----------
    df   : laps DataFrame (must have run through clean_and_enrich_laps)
    rcm  : race-control messages DataFrame from data_loader (may be None/empty)
    """
    df = df.copy()

    # ── Signal 1: TrackStatus per-lap column ─────────────────
    if "TrackStatus" in df.columns:
        def _parse_status(val) -> str:
            if pd.isna(val):
                return "Clear"
            s = str(val).strip()
            severity = ["5", "4", "6", "7", "3", "2"]
            for code in severity:
                if code in s:
                    return _PERTURB_CODES[code]
            return "Clear"
        df["TrackStatus_Flag"] = df["TrackStatus"].apply(_parse_status)
    else:
        logger.warning(
            "flag_perturbed_laps: 'TrackStatus' column not found — "
            "Signal 1 set to 'Unknown' for all laps."
        )
        df["TrackStatus_Flag"] = "Unknown"

    _status_perturbed = df["TrackStatus_Flag"].isin(
        set(_PERTURB_CODES.values()) | {"Unknown"}
    ) & (df["TrackStatus_Flag"] != "Clear")

    # ── Signal 2: Sector time anomaly ────────────────────────
    sector_cols = [c for c in ["Sector1Time", "Sector2Time", "Sector3Time"]
                   if c in df.columns]
    df["Sector_Anomaly"] = False

    if sector_cols:
        for col in sector_cols:
            s_col = f"_{col}_s"
            if pd.api.types.is_timedelta64_dtype(df[col]):
                df[s_col] = df[col].dt.total_seconds()
            else:
                df[s_col] = pd.to_numeric(df[col], errors="coerce")

        _sec_s_cols = [f"_{c}_s" for c in sector_cols]
        group_keys = ["session_name", "Driver_Short", "Compound"]
        _clean = df[~df["PitLap"] & df["LapTime_s"].notna()].copy()

        for s_col in _sec_s_cols:
            q75 = (
                _clean.groupby(group_keys)[s_col]
                .quantile(0.75).rename(f"_q75_{s_col}")
            )
            iqr = (
                _clean.groupby(group_keys)[s_col]
                .apply(lambda x: x.quantile(0.75) - x.quantile(0.25))
                .rename(f"_iqr_{s_col}")
            )
            df = df.join(q75, on=group_keys)
            df = df.join(iqr, on=group_keys)
            threshold_col = f"_thresh_{s_col}"
            df[threshold_col] = (
                df[f"_q75_{s_col}"] + sector_iqr_multiplier * df[f"_iqr_{s_col}"]
            )
            df["Sector_Anomaly"] |= (
                df[s_col].notna()
                & df[threshold_col].notna()
                & (df[s_col] > df[threshold_col])
            )
            df = df.drop(columns=[
                f"_q75_{s_col}", f"_iqr_{s_col}", threshold_col, s_col
            ])
    else:
        logger.warning(
            "flag_perturbed_laps: no SectorNTime columns found — "
            "Sector_Anomaly signal inactive."
        )

    # ── Signal 3: RCM time-series ────────────────────────────
    # For each yellow / SC / VSC / red event in the RCM feed, flag every
    # lap whose window [LapStartTime, LapStartTime+LapTime_s] contains the
    # event timestamp.  This catches sector-level yellows that last less than
    # one lap and are therefore invisible in the per-lap TrackStatus column.
    df["RCM_Perturbed"]   = False
    df["RCM_Flag_Type"]   = ""
    df["RCM_Flag_Sector"] = 0

    n_rcm_perturbed = 0
    n_rcm_events    = 0

    if rcm is not None and not rcm.empty:
        rcm_c = _normalize_rcm(rcm)

        # Select events that actually disrupt lap times
        _flag_match = rcm_c["Flag"].str.upper().isin(_RCM_PERTURB_FLAGS)
        _cat_match  = rcm_c["Category"].str.lower().isin(_RCM_PERTURB_CATS)
        # Also catch SC/VSC encoded in Message when Flag is empty
        _msg_match  = (
            rcm_c["Flag"].eq("") &
            rcm_c["Message"].str.upper().str.contains(
                r"SAFETY CAR|VIRTUAL SAFETY CAR|VSC", na=False, regex=True
            )
        )
        perturb_events = rcm_c[_flag_match | _cat_match | _msg_match].copy()
        n_rcm_events   = len(perturb_events)

        if not perturb_events.empty and "LapStartTime" in df.columns and "LapTime_s" in df.columns:
            lap_starts = df["LapStartTime"].values.astype(float)
            lap_ends   = (
                df["LapStartTime"].fillna(0) + df["LapTime_s"].fillna(120)
            ).values.astype(float)
            sess_col   = df["session_name"].values

            for _, ev in perturb_events.iterrows():
                t    = ev["Time_s"]
                sess = ev.get("session_name", "")
                if not np.isfinite(t):
                    continue

                # Vectorised: find laps in the same session whose window contains t
                hit = (
                    (sess_col == sess)
                    & (lap_starts <= t)
                    & (t <= lap_ends)
                )
                if not hit.any():
                    continue

                flag_str   = str(ev["Flag"]).upper() or str(ev["Category"])
                scope_str  = str(ev["Scope"]).upper()
                sector_val = int(ev["Sector"]) if (
                    pd.notna(ev["Sector"]) and scope_str == "SECTOR"
                ) else 0

                hit_idx = df.index[hit]
                df.loc[hit_idx, "RCM_Perturbed"] = True

                # Only overwrite type/sector if not already set (first event wins)
                no_type_yet = df.loc[hit_idx, "RCM_Flag_Type"] == ""
                df.loc[hit_idx[no_type_yet], "RCM_Flag_Type"]   = flag_str
                df.loc[hit_idx[no_type_yet], "RCM_Flag_Sector"] = sector_val

            n_rcm_perturbed = int(df["RCM_Perturbed"].sum())

    # ── Combined flag ─────────────────────────────────────────
    df["Perturbed_Lap"] = _status_perturbed | df["Sector_Anomaly"] | df["RCM_Perturbed"]

    n_perturbed  = int(df["Perturbed_Lap"].sum())
    n_status_sig = int(_status_perturbed.sum())
    n_sector_sig = int(df["Sector_Anomaly"].sum())
    logger.info(
        "flag_perturbed_laps: %d perturbed laps flagged "
        "(Signal1/TrackStatus: %d  |  Signal2/Sector: %d  |  "
        "Signal3/RCM [%d events]: %d)",
        n_perturbed, n_status_sig, n_sector_sig, n_rcm_events, n_rcm_perturbed,
    )
    return df


# ─────────────────────────────────────────────────────────────
# Race position change flagging
# ─────────────────────────────────────────────────────────────

def flag_position_changes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect lap-by-lap position gains and losses for each driver.
    Relevant for Race sessions only; gracefully no-ops for FP/Quali.

    Columns added
    -------------
    Pos_Delta       – positive = gained places (lower number = better)
    Pos_Delta_Clean – Pos_Delta with pit-lap rows zeroed out
    Overtook        – gained ≥1 position on a clean lap
    WasOvertaken    – lost  ≥1 position on a clean lap
    """
    df = df.copy()

    if "Position" not in df.columns:
        logger.warning(
            "flag_position_changes: 'Position' column not found — "
            "no position flags added."
        )
        df["Pos_Delta"]       = np.nan
        df["Pos_Delta_Clean"] = 0
        df["Overtook"]        = False
        df["WasOvertaken"]    = False
        return df

    df = df.sort_values(["session_name", "DriverNo", "LapNo"])
    df["_prev_pos"] = df.groupby(["session_name", "DriverNo"])["Position"].shift(1)
    df["Pos_Delta"] = (df["_prev_pos"] - df["Position"]).astype("float")

    _pit_mask = df["InLap"] | df["OutLap"]
    df.loc[_pit_mask, "Pos_Delta"] = np.nan

    df["Pos_Delta_Clean"] = df["Pos_Delta"].fillna(0).astype(int)
    df["Overtook"]        = df["Pos_Delta"] > 0
    df["WasOvertaken"]    = df["Pos_Delta"] < 0
    df = df.drop(columns=["_prev_pos"])

    logger.info(
        "flag_position_changes: %d overtaking moves, %d losses flagged",
        df["Overtook"].sum(), df["WasOvertaken"].sum(),
    )
    return df


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def filter_by_stint_key(laps: pd.DataFrame, stint_key: str) -> pd.DataFrame:
    """Return all laps belonging to the given Stint_key."""
    return laps[laps["Stint_key"] == stint_key].copy()


def enrich_telemetry(telemetry: pd.DataFrame, laps: pd.DataFrame) -> pd.DataFrame:
    """Join team/driver info from laps onto the telemetry frame."""
    if telemetry.empty:
        return telemetry
    telemetry = telemetry.copy()
    # Normalize timestamp to float seconds.  A freshly-fetched session carries
    # timedelta values while cache-loaded ones are float; concatenating the two
    # upstream yields an object column that breaks numeric comparisons in
    # _lap_telemetry.  Coerce defensively so it is always float64 here.
    if "timestamp" in telemetry.columns and telemetry["timestamp"].dtype == object:
        ts = telemetry["timestamp"]
        td = pd.to_timedelta(ts, errors="coerce")
        telemetry["timestamp"] = td.dt.total_seconds().fillna(
            pd.to_numeric(ts, errors="coerce")
        )
    elif "timestamp" in telemetry.columns and pd.api.types.is_timedelta64_dtype(
        telemetry["timestamp"]
    ):
        telemetry["timestamp"] = telemetry["timestamp"].dt.total_seconds()
    key_cols = ["session_name", "DriverNo"]
    meta = (
        laps[key_cols + ["Driver_Short", "Team", "TeamColor"]]
        .drop_duplicates(subset=key_cols)
    )
    return telemetry.merge(meta, on=key_cols, how="left")


def clipped_range(series: pd.Series, margin_ratio: float = 0.2) -> list:
    ymin, ymax = series.min(), series.max()
    margin = (ymax - ymin) * margin_ratio
    return [ymin - margin, ymax + margin / 4]


# ─────────────────────────────────────────────────────────────
# Weather enrichment
# ─────────────────────────────────────────────────────────────

_WEATHER_COLS = (
    "TrackTemp", "AirTemp", "Humidity", "Pressure",
    "WindSpeed", "WindDirection", "Rainfall",
)


def enrich_weather(laps: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """
    Join the nearest weather snapshot onto each lap using a backward
    asof merge on LapStartTime.

    Columns added
    -------------
    TrackTemp      – track surface temperature (°C)
    AirTemp        – ambient air temperature (°C)
    Humidity       – relative humidity (%)
    Pressure       – barometric pressure (mbar)
    WindSpeed      – wind speed (m/s or km/h depending on livef1 version)
    WindDirection  – wind direction (degrees)
    Rainfall       – bool: rain detected during this reading

    Implementation note
    -------------------
    The merge is performed per session so that time values from different
    sessions (all session-relative from T0) are never cross-contaminated.
    A tolerance of 300 s (5 min) is applied: if no weather reading exists
    within the last 5 minutes, the weather columns are left as NaN.
    """
    # Always add the columns so downstream code can rely on their presence
    laps = laps.copy()
    if weather.empty:
        for col in _WEATHER_COLS:
            if col not in laps.columns:
                laps[col] = np.nan
        logger.info("enrich_weather: no weather data — columns filled with NaN")
        return laps

    weather = weather.copy()

    # Normalise Time → float seconds (saved as float after cache round-trip,
    # but may arrive as timedelta when fetched live)
    if "Time" in weather.columns:
        if pd.api.types.is_timedelta64_dtype(weather["Time"]):
            weather["_wx_time_s"] = weather["Time"].dt.total_seconds()
        else:
            weather["_wx_time_s"] = pd.to_numeric(weather["Time"], errors="coerce")
    else:
        logger.warning("enrich_weather: no Time column in weather data — filling NaN")
        for col in _WEATHER_COLS:
            if col not in laps.columns:
                laps[col] = np.nan
        return laps

    avail_wx = [c for c in _WEATHER_COLS if c in weather.columns]
    if not avail_wx:
        logger.warning("enrich_weather: none of %s found in weather data", _WEATHER_COLS)
        for col in _WEATHER_COLS:
            if col not in laps.columns:
                laps[col] = np.nan
        return laps

    laps["_lst_wx"] = pd.to_numeric(laps["LapStartTime"], errors="coerce")

    parts = []
    for sess in laps["session_name"].unique():
        lap_sub = laps[laps["session_name"] == sess].copy()
        wx_sub  = weather[weather["session_name"] == sess].dropna(
            subset=["_wx_time_s"]
        ).copy()

        if wx_sub.empty:
            for col in avail_wx:
                lap_sub[col] = np.nan
            parts.append(lap_sub)
            continue

        wx_sub  = wx_sub.sort_values("_wx_time_s")
        orig_idx = lap_sub.index
        # Save original index as a column so merge_asof's fresh RangeIndex
        # doesn't destroy it — merge_asof always returns a 0-based index.
        lap_sorted = lap_sub.sort_values("_lst_wx").reset_index(names=["_orig_idx"])

        merged = pd.merge_asof(
            lap_sorted,
            wx_sub[["_wx_time_s"] + avail_wx].drop_duplicates("_wx_time_s"),
            left_on="_lst_wx",
            right_on="_wx_time_s",
            direction="backward",
            tolerance=300.0,   # 5 min gap tolerance
        )
        merged = merged.drop(columns=["_wx_time_s"], errors="ignore")
        # Restore the original index and row order
        merged = merged.set_index("_orig_idx")
        merged.index.name = None
        merged = merged.reindex(orig_idx)
        parts.append(merged)

    result = pd.concat(parts)
    result = result.drop(columns=["_lst_wx"], errors="ignore")

    # Ensure all weather columns present even if not in this dataset
    for col in _WEATHER_COLS:
        if col not in result.columns:
            result[col] = np.nan

    n_wx = int(result["TrackTemp"].notna().sum()) if "TrackTemp" in result.columns else 0
    logger.info(
        "enrich_weather: %d / %d laps have weather data (%s)",
        n_wx, len(result), avail_wx,
    )
    return result


# ─────────────────────────────────────────────────────────────
# Track limits enrichment
# ─────────────────────────────────────────────────────────────

def enrich_track_limits(laps: pd.DataFrame, rcm: pd.DataFrame) -> pd.DataFrame:
    """
    Parse race-control messages for track-limits events and join them
    onto the laps DataFrame.

    Detection strategy (two signals, combined with OR)
    --------------------------------------------------
    Signal A – Category: looks for RCM Category values containing
               "LapTimeDeleted" (official lap deletion) or "OffTrack" /
               "TrackLimits" (warnings that may precede deletion).
    Signal B – Message text: scans for "TRACK LIMITS" or "LAP DELETED"
               or "TIME DELETED" in the free-text message.

    Matching to laps
    ----------------
    Preferred: RCM Lap field (direct lap number, most reliable).
    Fallback:  time-based — the event timestamp falls within
               [LapStartTime, LapStartTime + LapTime_s] for that driver.

    Columns added
    -------------
    Track_Limits_Violation – bool : a track-limits event was recorded for
                                    this specific lap (may or may not have
                                    resulted in lap deletion — see IsDeleted
                                    for definitive deletion status)
    Track_Limits_Count     – int  : cumulative track-limits events for this
                                    driver in this session up to and including
                                    this lap (useful for "third strike" analysis)
    """
    laps = laps.copy()
    laps["Track_Limits_Violation"] = False
    laps["Track_Limits_Count"]     = 0

    if rcm is None or rcm.empty:
        return laps

    rcm_c = _normalize_rcm(rcm)

    # ── Detect track-limits events ───────────────────────────
    _cat_match = (
        rcm_c["Category"].str.lower().str.contains(
            r"laptimedel|offtrack|tracklimit", na=False, regex=True
        )
    )
    _msg_match = (
        rcm_c["Message"].str.upper().str.contains(
            r"TRACK LIMITS|LAP DELETED|TIME DELETED", na=False, regex=True
        )
    )
    tl_events = rcm_c[_cat_match | _msg_match].copy()

    if tl_events.empty:
        logger.info("enrich_track_limits: no track-limits events found in RCM")
        return laps

    # Normalise driver number for joining
    tl_events["_drv"] = tl_events["RacingNumber"].str.lstrip("0")
    laps["_drv_norm"] = laps["DriverNo"].astype(str).str.strip().str.lstrip("0")

    has_lap_col = "Lap" in tl_events.columns and tl_events["Lap"].notna().any()

    for _, ev in tl_events.iterrows():
        sess = ev.get("session_name", "")
        drv  = ev["_drv"]
        if not drv:
            continue

        base_mask = (
            (laps["session_name"] == sess) &
            (laps["_drv_norm"] == drv)
        )

        if has_lap_col and pd.notna(ev.get("Lap")):
            # Preferred: match by explicit lap number
            lap_mask = base_mask & (laps["LapNo"] == int(ev["Lap"]))
        else:
            # Fallback: time-based matching
            t = ev["Time_s"]
            if not np.isfinite(t):
                continue
            lap_mask = (
                base_mask &
                (laps["LapStartTime"] <= t) &
                (laps["LapStartTime"] + laps["LapTime_s"].fillna(120) >= t)
            )

        if lap_mask.any():
            laps.loc[lap_mask, "Track_Limits_Violation"] = True

    # ── Cumulative count per driver per session ───────────────
    laps["Track_Limits_Count"] = (
        laps.sort_values(["session_name", "_drv_norm", "LapNo"])
        .groupby(["session_name", "_drv_norm"])["Track_Limits_Violation"]
        .cumsum()
        .fillna(0)
        .astype(int)
    )

    laps = laps.drop(columns=["_drv_norm"])

    n_viol = int(laps["Track_Limits_Violation"].sum())
    logger.info(
        "enrich_track_limits: %d lap violations flagged from %d RCM events",
        n_viol, len(tl_events),
    )
    return laps


# ─────────────────────────────────────────────────────────────
# Blue flag enrichment
# ─────────────────────────────────────────────────────────────

def enrich_blue_flags(laps: pd.DataFrame, rcm: pd.DataFrame) -> pd.DataFrame:
    """
    Detect blue-flag events from race-control messages and mark the
    corresponding lap for each driver.

    A blue flag is shown to a driver about to be lapped.  Lapping
    traffic typically costs 0.5–1.5 s, so identifying blue-flag laps
    lets you exclude them from pace analysis or understand why a
    driver's lap time suddenly spiked.

    Column added
    ------------
    Blue_Flag – bool : this lap was run under a blue flag for that driver
                       (the flag time falls within [LapStartTime, LapStartTime+LapTime_s])
    """
    laps = laps.copy()
    laps["Blue_Flag"] = False

    if rcm is None or rcm.empty:
        return laps

    rcm_c = _normalize_rcm(rcm)

    blue_events = rcm_c[rcm_c["Flag"].str.upper() == "BLUE"].copy()

    if blue_events.empty:
        logger.info("enrich_blue_flags: no blue-flag events in RCM")
        return laps

    blue_events["_drv"] = blue_events["RacingNumber"].str.lstrip("0")
    laps["_drv_norm"]   = laps["DriverNo"].astype(str).str.strip().str.lstrip("0")

    for _, ev in blue_events.iterrows():
        t    = ev["Time_s"]
        sess = ev.get("session_name", "")
        drv  = ev["_drv"]
        if not np.isfinite(t) or not drv:
            continue

        mask = (
            (laps["session_name"] == sess) &
            (laps["_drv_norm"] == drv) &
            (laps["LapStartTime"] <= t) &
            (laps["LapStartTime"] + laps["LapTime_s"].fillna(200) >= t)
        )
        if mask.any():
            laps.loc[mask, "Blue_Flag"] = True

    n_blue = int(laps["Blue_Flag"].sum())
    logger.info(
        "enrich_blue_flags: %d laps flagged from %d blue-flag events",
        n_blue, len(blue_events),
    )
    laps = laps.drop(columns=["_drv_norm"])
    return laps


# ─────────────────────────────────────────────────────────────
# Session results enrichment
# ─────────────────────────────────────────────────────────────

def enrich_session_results(laps: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """
    Join official session-classification data onto the laps DataFrame.
    The results carry one row per driver per session; every lap for that
    driver in that session receives the same result values.

    Works for all session types with graceful degradation:
      FP        → Classified_Position (by best lap time), no Q times
      Quali     → Q1_s, Q2_s, Q3_s (lap times), Classified_Position
      Race      → Classified_Position, Grid_Position, Race_Status,
                  Race_Points, Q1_s/Q2_s/Q3_s (that weekend's quali times)

    Columns added
    -------------
    Classified_Position – int   : official finish / classification position
    Grid_Position       – int   : starting grid position (Race only, else NaN)
    Q1_s                – float : Q1 best lap time in seconds
    Q2_s                – float : Q2 best lap time in seconds
    Q3_s                – float : Q3 best lap time in seconds
    Race_Status         – str   : "Finished", "DNF", "+1 Lap", etc.
    Race_Points         – float : championship points scored (Race only)

    Notes
    -----
    - Q times are NaN for FP sessions and for drivers eliminated in Q1/Q2.
    - Classified_Position conflicts with the per-lap Position column (on-track
      race position) intentionally — the names are distinct.
    - Driver matching: results["DriverNumber"] ↔ laps["DriverNo"], both
      normalised to stripped strings ("16" not "016").
    """
    laps = laps.copy()

    _result_defaults = {
        "Classified_Position": np.nan,
        "Grid_Position":       np.nan,
        "Q1_s":                np.nan,
        "Q2_s":                np.nan,
        "Q3_s":                np.nan,
        "Race_Status":         "",
        "Race_Points":         np.nan,
    }

    if results is None or results.empty:
        for col, val in _result_defaults.items():
            if col not in laps.columns:
                laps[col] = val
        logger.info("enrich_session_results: no results data — columns filled with defaults")
        return laps

    results = results.copy()

    # ── Normalise Q time columns (timedelta → float, or already float) ──
    def _to_s(col):
        if col not in results.columns:
            return
        if pd.api.types.is_timedelta64_dtype(results[col]):
            results[f"{col}_s"] = results[col].dt.total_seconds()
        elif results[col].dtype == object:
            def _conv(v):
                if hasattr(v, "total_seconds"):
                    return v.total_seconds()
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return np.nan
            results[f"{col}_s"] = results[col].map(_conv)
        else:
            results[f"{col}_s"] = pd.to_numeric(results[col], errors="coerce")

    for q in ("Q1", "Q2", "Q3"):
        _to_s(q)

    # ── Build the columns-to-join map ────────────────────────
    # raw column in results  →  target column name on laps
    col_map: dict[str, str] = {}
    # Prefer ClassifiedPosition over Position to avoid duplicate target columns
    if "ClassifiedPosition" in results.columns:
        col_map["ClassifiedPosition"] = "Classified_Position"
    elif "Position" in results.columns:
        col_map["Position"] = "Classified_Position"
    if "GridPosition"       in results.columns: col_map["GridPosition"]       = "Grid_Position"
    if "Q1_s"               in results.columns: col_map["Q1_s"]               = "Q1_s"
    if "Q2_s"               in results.columns: col_map["Q2_s"]               = "Q2_s"
    if "Q3_s"               in results.columns: col_map["Q3_s"]               = "Q3_s"
    if "Status"             in results.columns: col_map["Status"]             = "Race_Status"
    if "Points"             in results.columns: col_map["Points"]             = "Race_Points"

    # ── Identify driver-number column in results ─────────────
    drv_col = next(
        (c for c in ("DriverNumber", "DriverNo", "RacingNumber", "Number")
         if c in results.columns),
        None,
    )
    if drv_col is None:
        logger.warning(
            "enrich_session_results: cannot find driver-number column "
            "(tried DriverNumber, DriverNo, RacingNumber, Number) — skipping"
        )
        for col, val in _result_defaults.items():
            if col not in laps.columns:
                laps[col] = val
        return laps

    # ── Normalise driver numbers to stripped strings ─────────
    results["_drv_key"] = results[drv_col].astype(str).str.strip().str.lstrip("0")
    laps["_drv_key"]    = laps["DriverNo"].astype(str).str.strip().str.lstrip("0")

    # ── Build slim results frame ─────────────────────────────
    src_cols = [c for c in col_map if c in results.columns]
    res_slim = (
        results[["session_name", "_drv_key"] + src_cols]
        .drop_duplicates(subset=["session_name", "_drv_key"])
        .rename(columns=col_map)
    )

    # ── Merge (left so all laps are preserved) ────────────────
    n_before = len(laps)
    laps = laps.merge(res_slim, on=["session_name", "_drv_key"], how="left")
    assert len(laps) == n_before, (
        f"enrich_session_results changed row count: {n_before} → {len(laps)}"
    )

    # ── Fill defaults for any columns still absent ───────────
    for col, val in _result_defaults.items():
        if col not in laps.columns:
            laps[col] = val

    # ── Clean up temp key ─────────────────────────────────────
    laps = laps.drop(columns=["_drv_key"])

    joined = [col_map[c] for c in src_cols]
    logger.info("enrich_session_results: joined columns %s", joined)
    return laps