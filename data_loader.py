"""
F1 Dashboard – Data Loader (FastF1 backend)
============================================
Replaces the livef1-based loader with FastF1, which exposes all the data
sources we need: laps, telemetry, weather, track status, race-control
messages, and session results.

Two-layer caching
-----------------
Layer 1 – FastF1's own disk cache (set via FASTF1_CACHE_DIR in config.py).
           FastF1 caches the raw API responses as pickle files so repeated
           loads of the same session are near-instant.
Layer 2 – Our own Parquet store (SESSIONS_DIR in config.py).
           Stores the *already-mapped* DataFrames so app startup only
           reads Parquet — no FastF1 overhead at all on a cache hit.

Column mapping
--------------
FastF1 uses different column names from livef1.  A mapping layer in this
file translates FastF1's names to the names processing.py and app.py
already expect, so those files need zero changes.

    FastF1 laps          → processing.py / app.py
    ─────────────────────────────────────────────
    DriverNumber         → DriverNo
    LapNumber            → LapNo
    PitInTime            → PitIn
    PitOutTime           → PitOut
    Deleted              → IsDeleted
    SpeedI1/I2/FL/ST     → Speed_I1/I2/FL/ST
    Abbreviation+TeamName→ Driver  ("VER-Red Bull Racing" synthetic field)

    FastF1 telemetry     → processing.py / app.py
    ─────────────────────────────────────────────
    DriverNumber         → DriverNo
    nGear                → GearNo
    SessionTime          → timestamp

Public API (unchanged from livef1 version)
------------------------------------------
load_session(season, meeting, session)
    → dict: laps, telemetry, weather, track_status, race_control, results,
            session_name, meta, from_cache

load_sessions(session_info_list)
    → dict of combined DataFrames

list_cached_sessions()   clear_cache()   cache_summary()   is_cached()
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd
import numpy as np

try:
    import fastf1
    FASTF1_AVAILABLE = True
except ImportError:
    FASTF1_AVAILABLE = False
    logging.warning("fastf1 not installed — only cached data will be available.  "
                    "Run: pip install fastf1")

from config import SESSIONS_DIR, FASTF1_CACHE_DIR

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# FastF1 session-identifier mapping
# ─────────────────────────────────────────────────────────────
# FastF1 accepts these exact strings as the session identifier.
# They match the SESSION values used in SESSION_INFO_LIST in app.py.
_SESSION_ALIASES: dict[str, str] = {
    "Practice 1":       "FP1",
    "Practice 2":       "FP2",
    "Practice 3":       "FP3",
    "Sprint Qualifying":"SQ",
    "Sprint":           "Sprint",
    "Qualifying":       "Q",
    "Race":             "R",
}


def _ff1_session_id(session: str) -> str:
    """Translate long session name to FastF1 short identifier."""
    return _SESSION_ALIASES.get(session, session)


# ─────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────

def _sanitize(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "_", str(text)).strip("_")


def _session_key(season: str, meeting: str, session: str) -> str:
    return f"{_sanitize(season)}__{_sanitize(meeting)}__{_sanitize(session)}"


def _session_name(season: str, meeting: str, session: str) -> str:
    return f"{session}_{meeting}_{season}"


def _cache_paths(key: str) -> dict[str, Path]:
    base = Path(SESSIONS_DIR)
    return {
        "laps":         base / f"{key}__laps.parquet",
        "telemetry":    base / f"{key}__telemetry.parquet",
        "meta":         base / f"{key}__meta.parquet",
        "weather":      base / f"{key}__weather.parquet",
        "track_status": base / f"{key}__track_status.parquet",
        "race_control": base / f"{key}__race_control.parquet",
        "results":      base / f"{key}__results.parquet",
    }


def _ensure_dirs() -> None:
    Path(SESSIONS_DIR).mkdir(parents=True, exist_ok=True)
    Path(FASTF1_CACHE_DIR).mkdir(parents=True, exist_ok=True)


def _tag(df: pd.DataFrame, session: str, season: str,
         meeting: str, sess_name: str) -> None:
    """Attach session-identification columns in place."""
    df["session"]      = session
    df["season"]       = season
    df["meeting"]      = meeting
    df["session_name"] = sess_name


# ─────────────────────────────────────────────────────────────
# Parquet I/O
# ─────────────────────────────────────────────────────────────

def _save_df(df: pd.DataFrame, path: Path) -> None:
    """Persist a DataFrame as Parquet, safely handling edge-case types."""
    import pyarrow as pa

    df = df.copy()

    # timedelta → float seconds
    for col in df.select_dtypes(include=["timedelta64[ns]"]).columns:
        df[col] = df[col].dt.total_seconds()

    # datetime64 with timezone → strip tz (pyarrow compat)
    for col in df.select_dtypes(include=["datetimetz"]).columns:
        df[col] = df[col].dt.tz_localize(None)

    # object columns with non-primitive values → str
    for col in df.select_dtypes(include=["object"]).columns:
        try:
            pa.array(df[col], from_pandas=True)
        except (pa.lib.ArrowInvalid, pa.lib.ArrowTypeError):
            logger.warning("Column '%s' has non-primitive values — casting to str", col)
            df[col] = df[col].astype(str)

    df.to_parquet(path, index=False, engine="pyarrow")
    logger.info("Saved  %s  (%d rows)", path.name, len(df))


def _load_df(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path, engine="pyarrow")
    logger.info("Loaded %s  (%d rows)", path.name, len(df))
    return df


def _load_df_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return _load_df(path)


# ─────────────────────────────────────────────────────────────
# Column mapping — FastF1 → processing.py / app.py
# ─────────────────────────────────────────────────────────────

def _map_laps(ff1_laps: pd.DataFrame) -> pd.DataFrame:
    """
    Translate FastF1 laps DataFrame column names and synthesize the
    'Driver' column (format: "VER-Red Bull Racing") that processing.py
    uses to extract Driver_Short and Team.

    FastF1 lap columns of interest:
      DriverNumber, LapNumber, PitInTime, PitOutTime,
      Deleted (bool), SpeedI1/I2/FL/ST,
      Abbreviation (3-letter code), TeamName,
      LapTime, LapStartTime, Sector1/2/3Time,
      Compound, TyreLife, TrackStatus, Position, IsPersonalBest
    """
    df = ff1_laps.copy()

    # ── Core renames ─────────────────────────────────────────
    renames = {
        "DriverNumber": "DriverNo",
        "LapNumber":    "LapNo",
        "PitInTime":    "PitIn",
        "PitOutTime":   "PitOut",
        "Deleted":      "IsDeleted",
        "SpeedI1":      "Speed_I1",
        "SpeedI2":      "Speed_I2",
        "SpeedFL":      "Speed_FL",
        "SpeedST":      "Speed_ST",
        "TyreLife":     "TyreAge"
    }
    df = df.rename(columns={k: v for k, v in renames.items() if k in df.columns})

    # ── Synthesize "Driver" = "VER-Red Bull Racing" ──────────
    # processing.py splits on "-" to get Driver_Short and Team.
    #
    # FastF1 laps use:
    #   "Driver"  → 3-letter abbreviation (e.g. "VER")
    #   "Team"    → full team name (e.g. "Red Bull Racing")
    # FastF1 results/driver-info may instead use "Abbreviation"/"TeamName".
    # We always overwrite "Driver" with the synthesized combined format.
    abbr_col = next(
        (c for c in ("Abbreviation", "Driver") if c in df.columns), None
    )
    team_col = next(
        (c for c in ("Team", "TeamName") if c in df.columns), None
    )

    if abbr_col and team_col:
        df["Driver"] = (
            df[abbr_col].fillna("UNK").astype(str).str.strip()
            + "-"
            + df[team_col].fillna("Unknown").astype(str).str.strip()
        )
    elif abbr_col:
        df["Driver"] = df[abbr_col].fillna("UNK").astype(str).str.strip()
    else:
        df["Driver"] = "UNK-Unknown"

    # ── DriverNo as string ────────────────────────────────────
    if "DriverNo" in df.columns:
        df["DriverNo"] = df["DriverNo"].astype(str).str.strip()

    # ── Compound → uppercase (safety net) ────────────────────
    if "Compound" in df.columns:
        df["Compound"] = (
            df["Compound"].astype(str).str.upper()
            .replace({"NAN": np.nan, "NONE": np.nan, "": np.nan})
        )
        df.loc[df["Compound"] == "UNKNOWN", "Compound"] = np.nan

    # ── IsDeleted: FastF1 Deleted is bool ─────────────────────
    if "IsDeleted" in df.columns:
        df["IsDeleted"] = df["IsDeleted"].fillna(False).astype(bool)

    logger.debug("_map_laps: %d rows, columns: %s", len(df), list(df.columns))
    return df


def _map_telemetry(ff1_tel: pd.DataFrame) -> pd.DataFrame:
    """
    Translate FastF1 car-data DataFrame column names.

    FastF1 car_data columns:
      Date (datetime), SessionTime (timedelta), DriverNumber,
      Speed (km/h), RPM, nGear, Throttle (0-100), Brake (bool/0-1),
      DRS, Source
    """
    df = ff1_tel.copy()

    renames = {
        "DriverNumber": "DriverNo",
        "nGear":        "GearNo",
        "SessionTime":  "timestamp",
    }
    df = df.rename(columns={k: v for k, v in renames.items() if k in df.columns})

    if "DriverNo" in df.columns:
        df["DriverNo"] = df["DriverNo"].astype(str).str.strip()

    return df


# ─────────────────────────────────────────────────────────────
# FastF1 fetch helpers
# ─────────────────────────────────────────────────────────────

def _fetch_telemetry(ff1_session) -> pd.DataFrame:
    """
    Combine per-driver car telemetry from a loaded FastF1 session into
    a single DataFrame with a DriverNumber column.

    FastF1 stores car data as a dict-like object keyed by driver number
    string.  Each value is a Telemetry DataFrame; we attach DriverNumber
    manually (FastF1's Telemetry class has no add_driver_info method —
    the previous version of this code silently caught AttributeError on
    every driver and persisted empty Parquet caches).
    """
    parts = []
    for drv_num in ff1_session.drivers:
        try:
            tel = ff1_session.car_data[drv_num].copy()
            if tel.empty:
                continue
            tel["DriverNumber"] = str(drv_num)
            parts.append(tel)
        except Exception as exc:
            logger.warning("Telemetry unavailable for driver %s: %s", drv_num, exc)

    if not parts:
        return pd.DataFrame()

    combined = pd.concat(parts, ignore_index=True)
    return _map_telemetry(combined)


def _safe_attr(ff1_session, attr_name: str) -> pd.DataFrame:
    """
    Safely retrieve a session attribute (weather_data, race_control_messages,
    etc.).  Returns empty DataFrame if the attribute is absent, None, or
    raises any exception.
    """
    try:
        val = getattr(ff1_session, attr_name, None)
        if val is None:
            logger.info("  [%s] is None", attr_name)
            return pd.DataFrame()
        if hasattr(val, "empty") and val.empty:
            logger.info("  [%s] is empty", attr_name)
            return pd.DataFrame()
        return val.copy() if hasattr(val, "copy") else pd.DataFrame(val)
    except Exception as exc:
        logger.warning("  [%s] fetch failed: %s", attr_name, exc)
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────
# Core loader
# ─────────────────────────────────────────────────────────────

def load_session(
    season: str,
    meeting: str,
    session: str,
    force_reload: bool = False,
) -> dict:
    """
    Load a single session.

    Returns
    -------
    dict with keys:
        laps, telemetry, weather, track_status, race_control, results,
        session_name, meta, from_cache

    All DataFrames degrade gracefully to empty when a source is
    unavailable.  laps and telemetry are the only mandatory frames.

    FastF1 session.load() flags used
    ---------------------------------
    laps=True       – lap timing (mandatory)
    telemetry=True  – car telemetry (mandatory)
    weather=True    – weather time-series
    messages=True   – race-control messages + track status
    """
    _ensure_dirs()

    key       = _session_key(season, meeting, session)
    sess_name = _session_name(season, meeting, session)
    paths     = _cache_paths(key)

    # ── 1. Try Parquet cache ──────────────────────────────────
    if not force_reload and paths["laps"].exists() and paths["telemetry"].exists():
        laps      = _load_df(paths["laps"])
        telemetry = _load_df(paths["telemetry"])

        # Empty caches happen when a prior fetch silently failed (e.g. a
        # FastF1 API call raised inside a swallowed try/except). Treat
        # them as a miss so we re-fetch instead of returning empty frames
        # forever.
        if laps.empty or telemetry.empty:
            print(
                f"  [cache STALE] {key} — laps={len(laps)} tel={len(telemetry)};"
                " ignoring cache and re-fetching",
                flush=True,
            )
        else:
            print(f"  [cache HIT]  {key}", flush=True)
            for df in (laps, telemetry):
                _tag(df, session, season, meeting, sess_name)

            weather      = _load_df_or_empty(paths["weather"])
            track_status = _load_df_or_empty(paths["track_status"])
            race_control = _load_df_or_empty(paths["race_control"])
            results      = _load_df_or_empty(paths["results"])

            for df in (weather, track_status, race_control, results):
                if not df.empty and "session_name" not in df.columns:
                    _tag(df, session, season, meeting, sess_name)

            return {
                "laps":         laps,
                "telemetry":    telemetry,
                "weather":      weather,
                "track_status": track_status,
                "race_control": race_control,
                "results":      results,
                "session_name": sess_name,
                "meta":         {"season": season, "meeting": meeting, "session": session},
                "from_cache":   True,
            }

    # ── 2. Fetch via FastF1 ───────────────────────────────────
    if not FASTF1_AVAILABLE:
        raise RuntimeError(
            f"fastf1 is not installed and no Parquet cache exists for: {key}\n"
            "Run:  pip install fastf1"
        )

    # Point FastF1 at its own cache directory
    fastf1.Cache.enable_cache(str(Path(FASTF1_CACHE_DIR)))

    print(f"  [FastF1]     {key} — this may take 1–3 min on first load…", flush=True)

    ff1_id   = _ff1_session_id(session)
    ff1_sess = fastf1.get_session(int(season), meeting, ff1_id)

    ff1_sess.load(
        laps=True,
        telemetry=True,
        weather=True,
        messages=True,
    )

    # ── Core data ─────────────────────────────────────────────
    laps      = _map_laps(ff1_sess.laps)
    telemetry = _fetch_telemetry(ff1_sess)

    # ── Extended data ─────────────────────────────────────────
    weather      = _safe_attr(ff1_sess, "weather_data")
    track_status = _safe_attr(ff1_sess, "track_status")
    race_control = _safe_attr(ff1_sess, "race_control_messages")
    results      = _safe_attr(ff1_sess, "results")

    # ── Tag everything ────────────────────────────────────────
    for df in (laps, telemetry, weather, track_status, race_control, results):
        if not df.empty:
            _tag(df, session, season, meeting, sess_name)

    # ── 3. Persist to Parquet ─────────────────────────────────
    print(f"  [saving]     laps ({len(laps):,} rows)…", flush=True)
    _save_df(laps, paths["laps"])
    print(f"  [saving]     telemetry ({len(telemetry):,} rows)…", flush=True)
    _save_df(telemetry, paths["telemetry"])

    for src_name, src_df, src_path in [
        ("weather",      weather,      paths["weather"]),
        ("track_status", track_status, paths["track_status"]),
        ("race_control", race_control, paths["race_control"]),
        ("results",      results,      paths["results"]),
    ]:
        if not src_df.empty:
            print(f"  [saving]     {src_name} ({len(src_df):,} rows)…", flush=True)
            _save_df(src_df, src_path)
        else:
            logger.info("  [%s] empty — not saved", src_name)

    # ── 4. Meta ───────────────────────────────────────────────
    meta_df = pd.DataFrame([{
        "season":    season,
        "meeting":   meeting,
        "session":   session,
        "key":       key,
        "laps_rows": len(laps),
        "tel_rows":  len(telemetry),
        "wx_rows":   len(weather),
        "ts_rows":   len(track_status),
        "rcm_rows":  len(race_control),
        "res_rows":  len(results),
    }])
    _save_df(meta_df, paths["meta"])

    return {
        "laps":         laps,
        "telemetry":    telemetry,
        "weather":      weather,
        "track_status": track_status,
        "race_control": race_control,
        "results":      results,
        "session_name": sess_name,
        "meta":         {"season": season, "meeting": meeting, "session": session},
        "from_cache":   False,
    }


# ─────────────────────────────────────────────────────────────
# Batch loader
# ─────────────────────────────────────────────────────────────

def load_sessions(
    session_info_list: list[dict],
    force_reload: bool = False,
) -> dict[str, pd.DataFrame]:
    """
    Load multiple sessions and return combined DataFrames.

    Parameters
    ----------
    session_info_list : list of dicts with keys SEASON, MEETING, SESSION
    force_reload      : bypass both caches and re-fetch from FastF1

    Returns
    -------
    dict with keys:
        laps, telemetry, weather, track_status, race_control, results

    Migration note — old livef1 loader returned a (laps, telemetry) tuple:

        # Old:
        laps_raw, telemetry_raw = load_sessions(info)

        # New:
        data          = load_sessions(info)
        laps_raw      = data["laps"]
        telemetry_raw = data["telemetry"]
    """
    buckets: dict[str, list[pd.DataFrame]] = {
        k: [] for k in ("laps", "telemetry", "weather",
                         "track_status", "race_control", "results")
    }

    for info in session_info_list:
        result = load_session(
            season       = str(info["SEASON"]),
            meeting      = info["MEETING"],
            session      = info["SESSION"],
            force_reload = force_reload,
        )
        source = "cache" if result["from_cache"] else "FastF1"
        logger.info("  [%s] %s", source, result["session_name"])

        for key in buckets:
            df = result[key]
            if not df.empty:
                buckets[key].append(df)

    return {
        key: pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        for key, frames in buckets.items()
    }


# ─────────────────────────────────────────────────────────────
# Cache management
# ─────────────────────────────────────────────────────────────

def list_cached_sessions() -> list[dict]:
    base = Path(SESSIONS_DIR)
    if not base.exists():
        return []
    sessions = []
    for meta_path in sorted(base.glob("*__meta.parquet")):
        try:
            df = pd.read_parquet(meta_path)
            sessions.append(df.iloc[0].to_dict())
        except Exception as exc:
            logger.warning("Could not read %s: %s", meta_path, exc)
    return sessions


def is_cached(season: str, meeting: str, session: str) -> bool:
    key   = _session_key(season, meeting, session)
    paths = _cache_paths(key)
    return paths["laps"].exists() and paths["telemetry"].exists()


def clear_cache(season: str = None, meeting: str = None, session: str = None) -> int:
    """
    Remove per-session Parquet files from SESSIONS_DIR.
    Does NOT touch FastF1's own cache (FASTF1_CACHE_DIR).
    To clear FastF1's cache too: fastf1.Cache.clear_cache(FASTF1_CACHE_DIR)
    """
    base = Path(SESSIONS_DIR)
    if not base.exists():
        return 0
    if season and meeting and session:
        key     = _session_key(season, meeting, session)
        pattern = f"{key}__*.parquet"
    else:
        pattern = "*.parquet"
    deleted = 0
    for f in base.glob(pattern):
        f.unlink()
        deleted += 1
        logger.info("Deleted cache file: %s", f.name)
    return deleted


def cache_summary() -> str:
    sessions = list_cached_sessions()
    if not sessions:
        return "Cache is empty."
    hdr = (
        f"{'SEASON':<8} {'MEETING':<30} {'SESSION':<20} "
        f"{'LAPS':>6} {'TEL':>7} {'WX':>5} {'RCM':>5} {'RES':>5}"
    )
    lines = [hdr, "─" * 88]
    for s in sessions:
        lines.append(
            f"{s.get('season',  '?'):<8} "
            f"{s.get('meeting', '?'):<30} "
            f"{s.get('session', '?'):<20} "
            f"{s.get('laps_rows', 0):>6,} "
            f"{s.get('tel_rows',  0):>7,} "
            f"{s.get('wx_rows',   0):>5,} "
            f"{s.get('rcm_rows',  0):>5,} "
            f"{s.get('res_rows',  0):>5,}"
        )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Quick CLI test
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    print(cache_summary())