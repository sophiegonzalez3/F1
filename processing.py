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
    _max_lap_in_stint = df.groupby(
        ["session_name", "DriverNo", "Stint"]
    )["LapInStint"].transform("max")
    df["FuelLoad_kg"] = ((_max_lap_in_stint - df["LapInStint"]) * 1.5).clip(lower=0)
    df["LapTime_FuelCorrected"] = df["LapTime_s"] - (df["FuelLoad_kg"] * FUEL_CORRECTION)

    # ── Team color ───────────────────────────────────────────
    df["TeamColor"] = df["Team"].map(TEAM_COLORS).fillna("#808080")

    assert len(df) == n_input, (
        f"clean_and_enrich_laps changed row count: {n_input} → {len(df)}"
    )
    logger.info("clean_and_enrich_laps: output %d rows  ✓", len(df))
    return df


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
    """Linear tyre-degradation fit for one stint (fuel-corrected)."""
    nan_result = pd.Series({"Stint_Deg_Rate": np.nan, "Stint_Deg_R2": np.nan})
    if len(group) < 3:
        return nan_result

    x = group["LapInStint"].values.astype(float)
    y = group["LapTime_FuelCorrected"].values.astype(float)
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 3:
        return nan_result

    x, y = x[mask], y[mask]
    try:
        coeffs = np.polyfit(x, y, 1)
        slope  = float(coeffs[0])
        y_hat  = np.polyval(coeffs, x)
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2     = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
        return pd.Series({
            "Stint_Deg_Rate": round(slope, 4),
            "Stint_Deg_R2":   round(r2,    4),
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

    _tyre_start_col = "TyreLife" if "TyreLife" in valid.columns else "LapInStint"

    stint_summary = (
        valid.groupby(["session_name", "Driver_Short", "Team", "Stint", "Compound"])
        .agg(
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

    valid["Is_Quali_Sim"] = (
        (valid["Delta_To_Best_pct"] <= delta_pct_threshold)
        & (valid["PseudoTyreAge"] <= max_tyre_age)
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