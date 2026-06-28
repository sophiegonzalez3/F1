"""
F1 Dashboard – app.py 
Run:   python app.py
Open:  http://127.0.0.1:8050
"""
from __future__ import annotations
import logging, warnings
warnings.filterwarnings("ignore")

from pathlib import Path
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import dash
from dash import dcc, html, Input, Output, State, dash_table, ctx, no_update, ALL
import dash_bootstrap_components as dbc

from config import (
    TEAM_COLORS, COMPOUND_COLORS,
    DARK_BG, CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
    SPEED_PERCENTILE, MINI_SECTORS, get_min_laps_for_compound,
    MIN_LAPS_SOFT, MIN_LAPS_MEDIUM, MIN_LAPS_HARD,
    HISTORICAL_DIR, FASTF1_CACHE_DIR,
)
from data_loader import load_sessions, cache_summary, is_cached, list_cached_sessions
from processing import (
    clean_and_enrich_laps, analyze_stints,
    identify_quali_sim_laps, best_laps_table,
    format_lap_time, enrich_telemetry, flag_perturbed_laps,
    enrich_weather, enrich_track_limits,
    enrich_blue_flags, enrich_session_results,
    flag_position_changes,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

# ── Sessions to load at startup (default) ────────────────────
SESSION_INFO_LIST = [
    {"SEASON": "2026", "MEETING": "Australian Grand Prix", "SESSION": "Practice 1"},
    {"SEASON": "2026", "MEETING": "Australian Grand Prix", "SESSION": "Practice 2"},
    {"SEASON": "2026", "MEETING": "Australian Grand Prix", "SESSION": "Practice 3"},
    {"SEASON": "2026", "MEETING": "Australian Grand Prix", "SESSION": "Qualifying"},
    {"SEASON": "2026", "MEETING": "Australian Grand Prix", "SESSION": "Race"},
]

# ── Mutable application state ─────────────────────────────────
# These globals are (re)assigned by rebuild_state() so the Data Selection
# tab can swap the loaded sessions at runtime without restarting the app.
laps_raw = telemetry_raw = weather_raw = race_control_raw = results_raw = None
laps = stints = telemetry = None
SESSIONS = DRIVERS = COMPOUNDS = TEAMS = []
LOADED_SESSION_INFO: list[dict] = []        # the SESSION_INFO_LIST currently loaded
LAST_LOAD_MSG: str = ""                      # human-readable result of the last load


def rebuild_state(session_info_list: list[dict], force_reload: bool = False) -> str:
    """
    Load the given sessions (cache-first) and run the full enrichment
    pipeline, reassigning all module-level data globals in place.

    Returns a short human-readable status string (also stored in
    LAST_LOAD_MSG). Raises nothing — failures are reported in the string.
    """
    global laps_raw, telemetry_raw, weather_raw, race_control_raw, results_raw
    global laps, stints, telemetry
    global SESSIONS, DRIVERS, COMPOUNDS, TEAMS, LOADED_SESSION_INFO, LAST_LOAD_MSG

    if not session_info_list:
        LAST_LOAD_MSG = "No sessions selected — nothing loaded."
        return LAST_LOAD_MSG

    print(f"Loading {len(session_info_list)} session(s) (cache-first)…", flush=True)
    _data = load_sessions(session_info_list, force_reload=force_reload)
    _laps_raw = _data["laps"]
    if _laps_raw is None or _laps_raw.empty:
        LAST_LOAD_MSG = ("Load failed — no lap data returned for the selected "
                         "sessions (FastF1 fetch may have failed).")
        return LAST_LOAD_MSG

    _telemetry_raw    = _data["telemetry"]
    _weather_raw      = _data["weather"]
    _race_control_raw = _data["race_control"]
    _results_raw      = _data["results"]

    _laps = clean_and_enrich_laps(_laps_raw)
    _laps["stint_key"] = _laps["Stint"].astype("string") + "_" + _laps["session_name"]
    _laps = enrich_weather(_laps, _weather_raw)
    _laps = enrich_track_limits(_laps, _race_control_raw)
    _laps = enrich_blue_flags(_laps, _race_control_raw)
    _laps = identify_quali_sim_laps(_laps)
    _laps = flag_perturbed_laps(_laps, rcm=_race_control_raw)
    _laps = enrich_session_results(_laps, _results_raw)
    _laps = flag_position_changes(_laps)
    _stints    = analyze_stints(_laps)
    _telemetry = enrich_telemetry(_telemetry_raw, _laps)

    # ── Commit to module globals atomically (after all heavy work) ──
    laps_raw, telemetry_raw      = _laps_raw, _telemetry_raw
    weather_raw, race_control_raw, results_raw = _weather_raw, _race_control_raw, _results_raw
    laps, stints, telemetry      = _laps, _stints, _telemetry
    SESSIONS  = sorted(laps["session_name"].unique())
    DRIVERS   = sorted(laps["Driver_Short"].dropna().unique())
    COMPOUNDS = [c for c in ["SOFT","MEDIUM","HARD","INTER","WET"]
                 if c in laps["Compound"].unique()]
    TEAMS     = sorted(laps["Team"].dropna().unique())
    LOADED_SESSION_INFO = list(session_info_list)

    from datetime import datetime as _dt
    LAST_LOAD_MSG = (
        f"Loaded {len(SESSIONS)} session(s) · {len(DRIVERS)} drivers · "
        f"{len(TEAMS)} teams  ({_dt.now().strftime('%H:%M:%S')})"
    )
    print(f"Ready  sessions={len(SESSIONS)}  drivers={len(DRIVERS)}  teams={len(TEAMS)}", flush=True)

    # Warm the track-map / corner-marker cache for the loaded meeting(s) in the
    # background so the Telemetry Channels corner lines are ready without a long
    # blocking fetch on first view. No-op at import time (helper not yet defined)
    # and for already-cached circuits.
    _pw = globals().get("_prewarm_track_maps")
    if _pw is not None:
        _pw(list(session_info_list))

    return LAST_LOAD_MSG


# ── Initial load (default sessions) ──────────────────────────
print("Loading sessions (cache-first)…")
rebuild_state(SESSION_INFO_LIST)


# ── Available-session discovery (for the Data Selection tab) ──
AVAILABLE_SEASON  = 2026
SELECTABLE_SEASONS = [2026, 2025, 2024, 2023, 2022, 2021]
_SCHEDULE_CACHE: dict[int, list[dict]] = {}   # season → memoized session list


def _sess_value(season, meeting, session) -> str:
    """Encode a session triple as a single checklist value."""
    return f"{season}|||{meeting}|||{session}"


def _parse_sess_value(value: str) -> dict:
    """Decode a checklist value back into a SESSION_INFO_LIST dict."""
    season, meeting, session = value.split("|||")
    return {"SEASON": season, "MEETING": meeting, "SESSION": session}


def get_available_sessions(season: int = AVAILABLE_SEASON, refresh: bool = False) -> list[dict]:
    """
    Return every session of *season* that has already taken place (date in
    the past), each annotated with whether it is cached locally.

    Source of truth is FastF1's event schedule. If FastF1 is unavailable or
    the network fails, fall back to whatever is in the local Parquet cache so
    the tab still works offline.

    Each item: {round, meeting, session, fmt, season, cached, value}
    Result is memoized per-season in _SCHEDULE_CACHE (refresh=True rebuilds).
    """
    season = int(season)
    if season in _SCHEDULE_CACHE and not refresh:
        # Refresh only the cheap 'cached' flags (files may have appeared)
        for it in _SCHEDULE_CACHE[season]:
            it["cached"] = is_cached(str(it["season"]), it["meeting"], it["session"])
        return _SCHEDULE_CACHE[season]

    items: list[dict] = []
    try:
        import fastf1
        from datetime import datetime, timezone
        fastf1.Cache.enable_cache(str(Path(FASTF1_CACHE_DIR)))
        sched = fastf1.get_event_schedule(season, include_testing=False)
        now = pd.Timestamp(datetime.now(timezone.utc).replace(tzinfo=None))
        for _, e in sched.iterrows():
            rnd  = int(e.get("RoundNumber", 0))
            name = str(e.get("EventName", "")).strip()
            fmt  = str(e.get("EventFormat", "conventional"))
            if not name:
                continue
            for i in range(1, 6):
                sn = e.get(f"Session{i}")
                sd = e.get(f"Session{i}DateUtc")
                if pd.isna(sn) or not str(sn).strip():
                    continue
                try:
                    is_past = pd.to_datetime(sd) <= now
                except Exception:
                    is_past = False
                if not is_past:
                    continue
                items.append({
                    "round": rnd, "meeting": name, "session": str(sn).strip(),
                    "fmt": fmt, "season": season,
                    "cached": is_cached(str(season), name, str(sn).strip()),
                    "value": _sess_value(season, name, str(sn).strip()),
                })
    except Exception as exc:
        print(f"  [schedule] FastF1 unavailable for {season} ({exc}); using local cache", flush=True)

    if not items:
        # Offline fallback: enumerate this season's sessions from the Parquet cache
        for s in list_cached_sessions():
            if str(s.get("season")) != str(season):
                continue
            meeting = s.get("meeting", "?"); session = s.get("session", "?")
            items.append({
                "round": 0, "meeting": meeting, "session": session,
                "fmt": "conventional", "season": season, "cached": True,
                "value": _sess_value(season, meeting, session),
            })

    items.sort(key=lambda x: (x["round"], x["meeting"], x["session"]))
    _SCHEDULE_CACHE[season] = items
    return items


# ── Session-type grouping helpers (for shortcut selectors) ────
def _session_type(session: str) -> str:
    """Bucket a session name into Practice / Qualifying / Sprint / Race."""
    s = session.lower()
    if "sprint" in s:        return "Sprint"      # Sprint + Sprint Qualifying
    if "practice" in s:      return "Practice"
    if "qualifying" in s:    return "Qualifying"
    if "race" in s:          return "Race"
    return "Other"


def _season_meetings(season: int) -> list[str]:
    """Ordered list of unique circuit/meeting names available for *season*."""
    seen, out = set(), []
    for it in get_available_sessions(season):
        if it["meeting"] not in seen:
            seen.add(it["meeting"]); out.append(it["meeting"])
    return out


def _session_option_label(it: dict) -> str:
    tag = "● cached" if it["cached"] else "○ fetch (~1–3 min)"
    rnd = f"R{it['round']}" if it["round"] else "—"
    spr = "  ⚡" if it["session"] in ("Sprint", "Sprint Qualifying") else ""
    return f"{rnd} · {it['meeting']} · {it['session']}{spr}   [{tag}]"


def _session_options(season: int) -> list[dict]:
    return [{"label": _session_option_label(it), "value": it["value"]}
            for it in get_available_sessions(season)]


def _list_summary(season: int) -> str:
    av = get_available_sessions(season)
    n_cached = sum(1 for it in av if it["cached"])
    return f"Season {season} · {len(av)} sessions available · {n_cached} cached · {len(av)-n_cached} to fetch"


def _circuit_buttons(season: int) -> list:
    """One click-to-add button per circuit for *season* (pattern-matching IDs)."""
    btn_style = {"fontSize": "0.72rem", "marginRight": "6px", "marginBottom": "6px"}
    out = []
    for m in _season_meetings(season):
        short = m.replace(" Grand Prix", "")
        out.append(dbc.Button(
            f"+ {short}",
            id={"type": "data-circuit-btn", "index": m},
            size="sm", color="info", outline=True, style=btn_style,
        ))
    return out

# ── Circuit characteristics reference table ───────────────────
_CIRCUIT_CHARS_PATH = Path("data/circuit_characteristics.csv")
try:
    CIRCUIT_CHARS = pd.read_csv(_CIRCUIT_CHARS_PATH, encoding="utf-8-sig")
    print(f"Circuit characteristics: {len(CIRCUIT_CHARS)} circuits loaded")
except FileNotFoundError:
    CIRCUIT_CHARS = pd.DataFrame()
    print("WARNING: data/circuit_characteristics.csv not found — Track Info tab will be limited")

# ── Historical results (race + quali) ────────────────────────
_HIST_BASE = Path(HISTORICAL_DIR)
def _load_hist(filename):
    p = _HIST_BASE / filename
    if p.exists():
        try:
            return pd.read_parquet(p, engine="pyarrow")
        except Exception:
            try:
                return pd.read_csv(p)
            except Exception:
                pass
    return pd.DataFrame()

HIST_RACE  = _load_hist("race_results_all.parquet")
HIST_QUALI = _load_hist("quali_results_all.parquet")
print(f"Historical race results : {len(HIST_RACE):,} rows")
print(f"Historical quali results: {len(HIST_QUALI):,} rows")

# Sprint race results (sprint-format weekends only; may be absent).
HIST_SPRINT = _load_hist("sprint_results_all.parquet")

# Per-round constructor championship standings (season-aware). Prefer the file
# written by fetch_historical_results.py; if it isn't there yet, derive it from
# the race (+ sprint) results we already have so the standings widget still works.
HIST_STANDINGS = _load_hist("constructor_standings_all.parquet")
if HIST_STANDINGS.empty and not HIST_RACE.empty:
    try:
        from fetch_historical_results import build_constructor_standings
        _pts_src = HIST_RACE
        if not HIST_SPRINT.empty:
            _shared = [c for c in HIST_RACE.columns if c in HIST_SPRINT.columns]
            _pts_src = pd.concat([HIST_RACE[_shared], HIST_SPRINT[_shared]],
                                 ignore_index=True)
        HIST_STANDINGS = build_constructor_standings(_pts_src)
        print("Constructor standings   : derived from race"
              f"{'+sprint' if not HIST_SPRINT.empty else ''} results "
              "(run fetch_historical_results.py to cache them)")
    except Exception as _exc:
        print(f"Constructor standings   : unavailable ({_exc})")
print(f"Constructor standings   : {len(HIST_STANDINGS):,} rows")

# ── Team car-development upgrades (per event) ─────────────────
# Curated, human-maintained table of the technical upgrades each team brings to
# a given Grand Prix — mirrors the FIA "Car Presentation" documents published
# each event. One row per (season, event, team, component). The UPGRADES tab
# reads this to show what evolution a team brought to the loaded meeting.
#
#   season       e.g. 2025
#   event        must match the MEETING name, e.g. "Austrian Grand Prix"
#   team         must match a TEAM_COLORS key, e.g. "McLaren"
#   component    affected area, e.g. "Floor Body", "Front Wing"
#   category     FIA-style reason: Performance / Circuit specific / Reliability /
#                Driver comfort / Repairs
#   description  short free-text summary of the change
#   source       provenance tag (e.g. "FIA-2025-AUT", "starter-example")
#
# Edit data/upgrades.csv to add/replace rows — no code changes needed.
_UPGRADES_PATH = Path("data/upgrades.csv")
_UPGRADES_COLS = ["season", "event", "team", "component",
                  "category", "description", "source"]

def _load_upgrades() -> pd.DataFrame:
    if _UPGRADES_PATH.exists():
        try:
            df = pd.read_csv(_UPGRADES_PATH)
            for c in _UPGRADES_COLS:
                if c not in df.columns:
                    df[c] = "" if c != "season" else pd.NA
            df["season"] = pd.to_numeric(df["season"], errors="coerce").astype("Int64")
            for c in ("event", "team", "component", "category", "description", "source"):
                df[c] = df[c].fillna("").astype(str).str.strip()
            return df[_UPGRADES_COLS]
        except Exception as _exc:
            print(f"Team upgrades           : failed to read ({_exc})")
    return pd.DataFrame(columns=_UPGRADES_COLS)

# Cache the parsed CSV but reload automatically when the file changes on disk, so
# editing data/upgrades.csv takes effect without restarting the app (Dash's
# reloader only watches .py files, not data files).
_UPGRADES_CACHE: dict = {"mtime": None, "df": pd.DataFrame(columns=_UPGRADES_COLS)}

def upgrades_df() -> pd.DataFrame:
    """Current upgrades table, re-read from disk whenever the CSV's mtime changes."""
    try:
        mtime = _UPGRADES_PATH.stat().st_mtime if _UPGRADES_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _UPGRADES_CACHE["mtime"]:
        _UPGRADES_CACHE["df"] = _load_upgrades()
        _UPGRADES_CACHE["mtime"] = mtime
    return _UPGRADES_CACHE["df"]

print(f"Team upgrades           : {len(upgrades_df()):,} rows")

def _upgrades_for(season, meeting) -> pd.DataFrame:
    """Upgrade rows for one (season, event) pair, robust to type/whitespace."""
    up = upgrades_df()
    if up.empty or season is None or not meeting:
        return up.iloc[0:0]
    try:
        season = int(season)
    except (TypeError, ValueError):
        return up.iloc[0:0]
    m = str(meeting).strip().casefold()
    sub = up[(up["season"] == season)
             & (up["event"].str.strip().str.casefold() == m)]
    return sub.copy()

def _loaded_meetings() -> list[tuple[int | None, str]]:
    """Unique (season, event) meetings currently loaded, in load order."""
    seen: list[tuple[int | None, str]] = []
    for info in LOADED_SESSION_INFO:
        try:
            season = int(info.get("SEASON"))
        except (TypeError, ValueError):
            season = None
        meeting = str(info.get("MEETING", "")).strip()
        key = (season, meeting)
        if meeting and key not in seen:
            seen.append(key)
    return seen

# Per-round drivers' championship standings (same source, keyed by driver).
HIST_DRIVER_STANDINGS = _load_hist("driver_standings_all.parquet")
if HIST_DRIVER_STANDINGS.empty and not HIST_RACE.empty:
    try:
        from fetch_historical_results import build_driver_standings
        _dpts_src = HIST_RACE
        if not HIST_SPRINT.empty:
            _dshared = [c for c in HIST_RACE.columns if c in HIST_SPRINT.columns]
            _dpts_src = pd.concat([HIST_RACE[_dshared], HIST_SPRINT[_dshared]],
                                  ignore_index=True)
        HIST_DRIVER_STANDINGS = build_driver_standings(_dpts_src)
    except Exception as _exc:
        print(f"Driver standings        : unavailable ({_exc})")
print(f"Driver standings        : {len(HIST_DRIVER_STANDINGS):,} rows")

# circuit_characteristics.csv uses French slugs (e.g. "monaco", "etats_unis")
# while fetch_historical_results.py slugifies the official English event name
# (e.g. "monaco_grand_prix", "united_states_grand_prix"). This map bridges
# the two so the Historical leaderboards filter actually matches rows.
HIST_CIRCUIT_KEY_MAP: dict[str, list[str]] = {
    "abu_dhabi":       ["abu_dhabi_grand_prix"],
    "arabie_saoudite": ["saudi_arabian_grand_prix"],
    "autriche":        ["austrian_grand_prix"],
    "azerbaidjan":     ["azerbaijan_grand_prix"],
    "belgique":        ["belgian_grand_prix"],
    "bresil":          ["s\xe3o_paulo_grand_prix", "brazilian_grand_prix"],
    "canada":          ["canadian_grand_prix"],
    "espagne":         ["spanish_grand_prix", "barcelona_grand_prix"],
    "etats_unis":      ["united_states_grand_prix"],
    "grande_bretagne": ["british_grand_prix"],
    "hongrie":         ["hungarian_grand_prix"],
    "italie":          ["italian_grand_prix"],
    "japon":           ["japanese_grand_prix"],
    "mexique":         ["mexico_city_grand_prix", "mexican_grand_prix"],
    "monaco":          ["monaco_grand_prix"],
    "pays_bas":        ["dutch_grand_prix"],
    "qatar":           ["qatar_grand_prix"],
    "singapour":       ["singapore_grand_prix"],
    "australie":       ["australian_grand_prix"],
    "bahrein":         ["bahrain_grand_prix"],
    "chine":           ["chinese_grand_prix"],
    "emilie_romagne":  ["emilia_romagna_grand_prix"],
    "miami":           ["miami_grand_prix"],
    "las_vegas":       ["las_vegas_grand_prix"],
}

# ── Constructor standings helpers (season-aware, data-driven) ─
def _loaded_meeting_season_round() -> tuple[int | None, int | None, str | None]:
    """
    Infer (season, round_number, event_name) for the meeting currently loaded in
    the Data tab. Uses LOADED_SESSION_INFO for the season + event name, then looks
    the round number up in HIST_RACE. When several meetings are loaded, the most
    advanced round (latest in the season) is used. Returns Nones if unresolved.
    """
    if not LOADED_SESSION_INFO:
        return None, None, None
    best = (None, None, None)   # (season, round, event)
    for info in LOADED_SESSION_INFO:
        try:
            season = int(info.get("SEASON"))
        except (TypeError, ValueError):
            continue
        event = str(info.get("MEETING", "")).strip()
        rnd = None
        if not HIST_STANDINGS.empty:
            sub = HIST_STANDINGS[
                (HIST_STANDINGS["season"] == season)
                & (HIST_STANDINGS["event_name"].astype(str).str.strip() == event)
            ]
            if not sub.empty:
                rnd = int(sub["round_number"].iloc[0])
        if best[0] is None or season > best[0] or (
            season == best[0] and (rnd or 0) > (best[1] or 0)
        ):
            best = (season, rnd, event)
    return best


# ── Track-Info ↔ loaded-meeting bridge ───────────────────────
# Reverse of HIST_CIRCUIT_KEY_MAP: historical slug → Track-Info (French) slug.
_HIST_TO_FR_KEY: dict[str, str] = {
    hk: fr for fr, hks in HIST_CIRCUIT_KEY_MAP.items() for hk in hks
}


def _slugify_event(name) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def _loaded_event() -> tuple[int | None, str | None]:
    """(season, meeting) of the currently loaded meeting, robust to standings
    gaps — falls back to LOADED_SESSION_INFO when round lookup fails."""
    season, _rnd, meeting = _loaded_meeting_season_round()
    if (season is None or not meeting) and LOADED_SESSION_INFO:
        info = LOADED_SESSION_INFO[0]
        meeting = str(info.get("MEETING", "")).strip() or meeting
        try:
            season = int(info.get("SEASON"))
        except (TypeError, ValueError):
            pass
    return season, meeting


def _loaded_circuit_key() -> str | None:
    """Track-Info circuit slug (CIRCUIT_CHARS key) for the loaded meeting, or
    None when it can't be mapped (e.g. circuit absent from the reference CSV)."""
    season, event = _loaded_event()
    if not event:
        return None
    # Prefer the historical circuit_key for this exact event (accent-safe),
    # then translate it to the Track-Info French slug.
    hist_ck = None
    for src in (HIST_RACE, HIST_QUALI):
        if src.empty or "circuit_key" not in src.columns:
            continue
        m = src[src["event_name"].astype(str).str.strip() == str(event).strip()]
        if not m.empty:
            hist_ck = str(m["circuit_key"].iloc[0])
            break
    if hist_ck is None:
        hist_ck = _slugify_event(event)
    fr = _HIST_TO_FR_KEY.get(hist_ck)
    if fr is None and not CIRCUIT_CHARS.empty and (CIRCUIT_CHARS["circuit_key"] == hist_ck).any():
        fr = hist_ck            # already a Track-Info slug
    if fr and not CIRCUIT_CHARS.empty and (CIRCUIT_CHARS["circuit_key"] == fr).any():
        return fr
    return None


def _track_avail_years() -> list[int]:
    """Seasons present in the historical archive, newest first."""
    return sorted(set(
        list(HIST_RACE["season"].unique() if "season" in HIST_RACE.columns else []) +
        list(HIST_QUALI["season"].unique() if "season" in HIST_QUALI.columns else [])
    ), reverse=True)


def _circuit_race_years(circuit_key) -> list[int]:
    """Seasons for which the archive holds a race result for *circuit_key*."""
    keys = HIST_CIRCUIT_KEY_MAP.get(circuit_key, [circuit_key])
    if HIST_RACE.empty or "circuit_key" not in HIST_RACE.columns:
        return []
    return sorted(int(y) for y in
                  HIST_RACE[HIST_RACE["circuit_key"].isin(keys)]["season"].unique())


def _circuit_display_season(circuit_key, avail_years: list[int] | None = None) -> int | None:
    """Season the whole Track-Info page should display for *circuit_key*: the
    current season when that Grand Prix has already run (a race result exists),
    otherwise the previous season (N-1). Clamped to what the archive holds."""
    avail_years = avail_years if avail_years is not None else _track_avail_years()
    if not avail_years:
        return None
    cur = max(avail_years)
    cyears = _circuit_race_years(circuit_key)
    if cur in cyears:                       # this GP has run in the current season
        return cur
    target = cur - 1                        # N-1 otherwise
    if target in avail_years:
        return target
    le = [y for y in avail_years if y <= target]
    return max(le) if le else (max(cyears) if cyears else cur)


def _standings_after_round(season: int, rnd: int | None) -> dict[str, float]:
    """Constructor points (team → cumulative) standing AFTER the given round.
    rnd=None or an unknown round falls back to the latest available round."""
    if HIST_STANDINGS.empty or season is None:
        return {}
    sub = HIST_STANDINGS[HIST_STANDINGS["season"] == season]
    if sub.empty:
        return {}
    rounds = sorted(int(r) for r in sub["round_number"].unique())
    if rnd is None or rnd not in rounds:
        rnd = max(rounds)
    row = sub[sub["round_number"] == rnd]
    return {str(t): float(p) for t, p in zip(row["TeamName"], row["cumulative_points"])}


def _round_points_for(season: int, rnd: int | None) -> dict[str, float]:
    """Points each team scored IN the given round (team → round_points)."""
    if HIST_STANDINGS.empty or season is None or rnd is None:
        return {}
    row = HIST_STANDINGS[
        (HIST_STANDINGS["season"] == season) & (HIST_STANDINGS["round_number"] == rnd)
    ]
    return {str(t): float(p) for t, p in zip(row["TeamName"], row["round_points"])}


def _prev_round(season: int, rnd: int | None) -> int | None:
    """The round immediately before *rnd* that exists for the season, else None."""
    if HIST_STANDINGS.empty or season is None or rnd is None:
        return None
    sub = HIST_STANDINGS[HIST_STANDINGS["season"] == season]
    earlier = sorted(int(r) for r in sub["round_number"].unique() if int(r) < rnd)
    return earlier[-1] if earlier else None


def _team_champ_rank() -> dict[str, int]:
    """team → constructor championship position (1 = leader) for the season and
    round currently loaded in the Data tab. Empty dict if no standings exist."""
    season, rnd, _ = _loaded_meeting_season_round()
    after = _standings_after_round(season, rnd)
    if not after:
        return {}
    ordered = sorted(after.items(), key=lambda kv: -kv[1])
    rank, prev, pr = {}, None, 0
    for i, (t, p) in enumerate(ordered):
        if p != prev:
            pr = i + 1
        rank[t] = pr
        prev = p
    return rank


def _order_teams_by_champ(teams) -> list[str]:
    """Default ordering for team-categorical charts: by current championship
    standing (leader first), with any team not in the standings kept after the
    ranked ones in stable alphabetical order. Charts that are themselves a value
    ranking (gap-to-leader bars, pace order) keep their own ordering instead."""
    rank = _team_champ_rank()
    _BIG = 10 ** 6
    return sorted(set(map(str, teams)), key=lambda t: (rank.get(t, _BIG), t))


def _dense_rank_by_pts(pts: dict) -> dict:
    """Dense rank (1 = most points); ties share a rank."""
    ordered = sorted(pts.items(), key=lambda x: -x[1])
    rank, prev, pr = {}, None, 0
    for i, (k, p) in enumerate(ordered):
        if p != prev:
            pr = i + 1
        rank[k] = pr
        prev = p
    return rank


def _driver_standings_after_round(season, rnd) -> dict:
    """driver → {'pts': float, 'team': str} cumulative AFTER the given round.
    rnd=None or an unknown round falls back to the latest available round."""
    if HIST_DRIVER_STANDINGS.empty or season is None:
        return {}
    sub = HIST_DRIVER_STANDINGS[HIST_DRIVER_STANDINGS["season"] == season]
    if sub.empty:
        return {}
    rounds = sorted(int(r) for r in sub["round_number"].unique())
    if rnd is None or rnd not in rounds:
        rnd = max(rounds)
    row = sub[sub["round_number"] == rnd]
    return {str(d): {"pts": float(p), "team": str(t)}
            for d, p, t in zip(row["Abbreviation"], row["cumulative_points"], row["TeamName"])}


def _driver_round_points(season, rnd) -> dict:
    """Points each driver scored IN the given round (driver → round_points)."""
    if HIST_DRIVER_STANDINGS.empty or season is None or rnd is None:
        return {}
    row = HIST_DRIVER_STANDINGS[
        (HIST_DRIVER_STANDINGS["season"] == season)
        & (HIST_DRIVER_STANDINGS["round_number"] == rnd)
    ]
    return {str(d): float(p) for d, p in zip(row["Abbreviation"], row["round_points"])}


def _standings_leaderboard_body(entities_sorted, rank_after, rank_before,
                                after_pts, round_pts, color_of, primary_of,
                                secondary_of=None, entity_header="CONSTRUCTOR",
                                all_before_zero=False, delta_note=""):
    """Shared championship-leaderboard body (header + ranked rows + delta note),
    used by both the constructor and driver standings widgets so they render
    identically. The ``*_of`` arguments are callables: entity → value."""
    def _arrow(delta):
        if all_before_zero:
            return html.Span("—", style={"color": TEXT_DIM, "fontSize": "0.75rem"})
        if delta > 0:
            return html.Span(f"▲{delta}", style={"color": "#00C04B",
                             "fontWeight": "700", "fontSize": "0.78rem"})
        if delta < 0:
            return html.Span(f"▼{abs(delta)}", style={"color": "#FF4444",
                             "fontWeight": "700", "fontSize": "0.78rem"})
        return html.Span("=", style={"color": TEXT_DIM, "fontSize": "0.78rem"})

    _hcell = {"color": TEXT_DIM, "fontSize": "0.65rem", "fontWeight": "700",
              "letterSpacing": "1px"}
    header = html.Div([
        html.Span("POS", style={"width": "38px", "display": "inline-block", **_hcell}),
        html.Span("Δ",   style={"width": "42px", "display": "inline-block",
                                "textAlign": "center", **_hcell}),
        html.Span(entity_header, style={"flex": "1", **_hcell}),
        html.Span("THIS EVENT", style={"width": "80px", "textAlign": "right", **_hcell}),
        html.Span("TOTAL PTS",  style={"width": "80px", "textAlign": "right", **_hcell}),
    ], style={"display": "flex", "alignItems": "center",
              "padding": "4px 10px 6px 10px",
              "borderBottom": f"1px solid {GRID_CLR}", "marginBottom": "4px"})

    leader_pts = (max(after_pts.values()) if after_pts else 1) or 1
    rows = []
    for e in entities_sorted:
        clr     = color_of(e)
        rank_a  = rank_after.get(e, 99)
        delta   = rank_before.get(e, 99) - rank_a       # positive = moved UP
        pts_now = int(after_pts.get(e, 0))
        pts_evt = int(round_pts.get(e, 0))
        evt_str = f"+{pts_evt}" if pts_evt > 0 else ("—" if pts_evt == 0 else str(pts_evt))
        bar_pct = pts_now / leader_pts * 100

        name_children = [
            html.Span("● ", style={"color": clr, "fontSize": "0.75rem"}),
            html.Span(primary_of(e), style={"color": TEXT_MAIN,
                      "fontWeight": "700" if secondary_of else "600",
                      "fontSize": "0.82rem"}),
        ]
        sec = secondary_of(e) if secondary_of else None
        if sec:
            name_children.append(html.Span(f"  {sec}",
                style={"color": TEXT_DIM, "fontSize": "0.72rem"}))
        name_children.append(html.Div(
            html.Div(style={"width": f"{bar_pct:.1f}%", "height": "4px",
                            "background": clr, "borderRadius": "2px", "opacity": "0.6"}),
            style={"width": "100%", "height": "4px", "background": GRID_CLR,
                   "borderRadius": "2px", "marginTop": "4px"}))

        rows.append(html.Div([
            html.Span(f"P{rank_a}", style={"width": "38px", "display": "inline-block",
                      "color": clr, "fontWeight": "800", "fontSize": "0.88rem"}),
            html.Span(_arrow(delta), style={"width": "42px", "display": "inline-block",
                      "textAlign": "center"}),
            html.Div(name_children, style={"flex": "1", "paddingRight": "8px"}),
            html.Span(evt_str, style={"width": "80px", "textAlign": "right",
                      "color": "#00C04B" if pts_evt > 0 else TEXT_DIM,
                      "fontWeight": "700" if pts_evt > 0 else "400", "fontSize": "0.82rem"}),
            html.Span(f"{pts_now} pts", style={"width": "80px", "textAlign": "right",
                      "color": TEXT_MAIN, "fontWeight": "700", "fontSize": "0.88rem"}),
        ], style={"display": "flex", "alignItems": "center", "padding": "6px 10px",
                  "borderRadius": "6px", "marginBottom": "3px",
                  "background": f"linear-gradient(90deg, {clr}14 0%, transparent 60%)",
                  "border": f"1px solid {clr}28"}))

    return html.Div([
        header,
        html.Div(rows),
        html.P(delta_note, style={"color": TEXT_DIM, "fontSize": "0.65rem",
                                  "marginTop": "10px", "fontStyle": "italic"}),
    ])


def _driver_standings_widget(fl):
    """Drivers' Championship leaderboard for the season/round loaded in the Data
    tab — same look as the Constructor Championship widget. Falls back to points
    from the loaded race laps if the meeting isn't in the historical archive."""
    season, rnd, event = _loaded_meeting_season_round()
    after_src  = _driver_standings_after_round(season, rnd)
    prev_rnd   = _prev_round(season, rnd)
    before_src = _driver_standings_after_round(season, prev_rnd) if prev_rnd else {}
    round_src  = _driver_round_points(season, rnd)
    from_archive = rnd is not None

    if not after_src:
        race_sess = [s for s in fl["session_name"].unique()
                     if (str(s).startswith("Race") or str(s).startswith("Sprint"))
                     and "Qualifying" not in str(s) and "Shootout" not in str(s)]
        if race_sess and "Race_Points" in fl.columns:
            pr = (fl[fl["session_name"].isin(race_sess)]
                  .groupby(["session_name", "Driver_Short", "Team"])["Race_Points"]
                  .first().reset_index())
            pr["Race_Points"] = pd.to_numeric(pr["Race_Points"], errors="coerce").fillna(0)
            agg = pr.groupby(["Driver_Short", "Team"])["Race_Points"].sum().reset_index()
            round_src  = {str(d): float(p) for d, p in zip(agg["Driver_Short"], agg["Race_Points"])}
            after_src  = {str(d): {"pts": float(p), "team": str(t)}
                          for d, p, t in zip(agg["Driver_Short"], agg["Race_Points"], agg["Team"])}
            before_src = {}

    drivers = sorted(set(after_src) | set(before_src) | set(round_src))
    team_of = {}
    for d in drivers:
        if d in after_src:
            team_of[d] = after_src[d]["team"]
        elif d in before_src:
            team_of[d] = before_src[d]["team"]
        else:
            team_of[d] = ""
    after_pts  = {d: (after_src[d]["pts"] if d in after_src else 0) for d in drivers}
    before_pts = {
        d: (before_src[d]["pts"] if d in before_src
            else max(0, after_pts[d] - round_src.get(d, 0)))
        for d in drivers
    }
    round_pts = {d: round_src.get(d, 0) for d in drivers}

    rank_after  = _dense_rank_by_pts(after_pts)
    rank_before = _dense_rank_by_pts(before_pts)
    all_before_zero = all(v == 0 for v in before_pts.values())
    entities_sorted = sorted(
        drivers, key=lambda d: (rank_after.get(d, 99), -after_pts.get(d, 0)))

    season_lbl = str(season) if season else "current"
    if from_archive and event:
        subtitle = f"  ·  standings after {event} (round {rnd})"
    elif from_archive:
        subtitle = f"  ·  standings after round {rnd}"
    else:
        subtitle = "  ·  points from loaded race sessions (not yet in archive)"
    delta_note = (
        "↕ rank change caused by this event  ·  —  = season opener / no prior round"
        if all_before_zero else
        "↕ driver rank change vs the standings before this event"
    )
    info = ("Data: cumulative drivers' championship points for the loaded season, "
            "summed from every race's (and sprint's) points in the historical "
            "archive (driver_standings_all.parquet, built by "
            "fetch_historical_results.py). 'After' = standings through the loaded "
            "meeting's round; 'before' = the previous round; the arrow is the rank "
            "change from this event. Re-run the fetch for new rounds, or load "
            "another season to see its table.")

    body = (
        _standings_leaderboard_body(
            entities_sorted, rank_after, rank_before, after_pts, round_pts,
            color_of=lambda d: TEAM_COLORS.get(team_of.get(d, ""), "#808080"),
            primary_of=lambda d: d,
            secondary_of=lambda d: team_of.get(d, ""),
            entity_header="DRIVER",
            all_before_zero=all_before_zero, delta_note=delta_note,
        )
        if drivers else
        html.P("No driver standings available for the loaded season. "
               "Run fetch_historical_results.py to populate the archive.",
               style={"color": TEXT_DIM, "fontStyle": "italic", "fontSize": "0.8rem"})
    )
    return card(
        html.Span([
            "Drivers' Championship  ",
            html.Span(f"{season_lbl} season", style={"color": ACCENT, "fontWeight": "800"}),
            html.Span(subtitle, style={"color": TEXT_DIM, "fontWeight": "400",
                                       "fontSize": "0.72rem", "marginLeft": "6px"}),
        ]),
        body,
        info=info,
    )

# ── Theme ────────────────────────────────────────────────────
BASE = dict(
    paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
    font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=12),
    xaxis=dict(gridcolor=GRID_CLR, zeroline=False),
    yaxis=dict(gridcolor=GRID_CLR, zeroline=False),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1),
    margin=dict(l=60, r=20, t=50, b=50),
)

def theme(fig, h=450, t=""):
    fig.update_layout(**BASE, height=h, title=t)
    fig.update_xaxes(gridcolor=GRID_CLR, zeroline=False)
    fig.update_yaxes(gridcolor=GRID_CLR, zeroline=False)
    return fig

def card(title, children, info=None):
    """A titled card. Pass `info` to show a small ⓘ tooltip in the header
    explaining what data the graph uses and why it is relevant (hover to read)."""
    header = [html.Span(title, style={"fontWeight":"700","letterSpacing":"1px","fontSize":"0.85rem"})]
    if info:
        header.append(html.Span(
            " ⓘ", title=info,
            style={"cursor":"help","fontSize":"0.72rem","opacity":"0.6",
                   "userSelect":"none","marginLeft":"6px"},
        ))
    return dbc.Card([
        dbc.CardHeader(header),
        dbc.CardBody(children),
    ], className="mb-3",
       style={"background":CARD_BG,"border":f"1px solid {GRID_CLR}","borderRadius":"8px"})

def kpi(label, value, color=ACCENT, tooltip=None):
    label_content = [label, html.Span(
        " ⓘ", title=tooltip,
        style={"cursor":"help","fontSize":"0.65rem","opacity":"0.6","userSelect":"none"}
    )] if tooltip else [label]
    return dbc.Col(dbc.Card(dbc.CardBody([
        html.P(label_content, style={"color":TEXT_DIM,"fontSize":"0.72rem","marginBottom":"4px","letterSpacing":"1px"}),
        html.H4(value, style={"color":color,"fontWeight":"800","marginBottom":0}),
    ]), style={"background":CARD_BG,"border":f"1px solid {GRID_CLR}","borderRadius":"8px"}),
    xs=6, md=3, className="mb-3")

GFX = {"displayModeBar": False}

TABLE_STYLE = dict(
    style_table={"overflowX":"auto"},
    style_cell={"backgroundColor":CARD_BG,"color":TEXT_MAIN,
                "border":f"1px solid {GRID_CLR}","fontSize":"12px","padding":"8px"},
    style_header={"backgroundColor":"#09091A","fontWeight":"bold",
                  "color":ACCENT,"border":f"1px solid {GRID_CLR}"},
    sort_action="native", filter_action="native", page_size=20,
)

# ── Helpers ──────────────────────────────────────────────────
def team_metrics(df):
    v = df[df["ValidLap"]].copy()
    ts = v.groupby("Team").agg(
        Avg_Lap_s=("LapTime_s","mean"), Median_Lap_s=("LapTime_s","median"),
        Lap_Std_s=("LapTime_s","std"),  Best_Lap_s=("LapTime_s","min"),
        Laps=("LapTime_s","count"),     FuelCorr_Median=("LapTime_FuelCorrected","median"),
        Avg_Speed=("PseudoSpeed","mean"),Stints=("Stint","max"),
        Drivers=("Driver_Short","nunique"),
    ).round(3)
    ts["Consistency"] = (ts["Lap_Std_s"]/ts["Median_Lap_s"]*100).round(2)
    f = ts["Best_Lap_s"].min()
    ts["Gap_to_Best_s"]   = (ts["Best_Lap_s"]-f).round(3)
    ts["Gap_to_Best_pct"] = ((ts["Best_Lap_s"]/f-1)*100).round(2)
    return ts.sort_values("Best_Lap_s").reset_index()

def tmgaps(df):
    v = df[df["ValidLap"]].copy()
    b = v.groupby(["Driver_Short","Team"])["LapTime_s"].min().reset_index()
    b.columns = ["Driver_Short","Team","Best_Lap"]
    r = v.groupby(["Driver_Short","Team"])["LapTime_s"].median().reset_index()
    r.columns = ["Driver_Short","Team","Race_Median"]
    s = v.groupby(["Driver_Short","Team"])["LapTime_s"].std().reset_index()
    s.columns = ["Driver_Short","Team","Race_Lap_Std_s"]
    lc= v.groupby(["Driver_Short","Team"])["LapTime_s"].count().reset_index()
    lc.columns=["Driver_Short","Team","Laps_count"]
    m = b.merge(r,on=["Driver_Short","Team"]).merge(s,on=["Driver_Short","Team"]).merge(lc,on=["Driver_Short","Team"])
    m = m.sort_values(["Team","Best_Lap"])
    out=[]
    for _,g in m.groupby("Team"):
        rows=g.to_dict("records"); n=len(rows)
        for i,d in enumerate(rows):
            qg=rg=None
            if n>=2:
                j=1-i if n==2 else None
                if j is not None:
                    o=rows[j]
                    qg=round(d["Best_Lap"]-o["Best_Lap"],3)
                    rg=round(d["Race_Median"]-o["Race_Median"],3)
            out.append({**d,"Quali_Gap_to_Teammate_s":qg,"Race_Gap_to_Teammate_s":rg})
    return pd.DataFrame(out)

def styled_table(data, cols):
    return dash_table.DataTable(data=data, columns=cols, **TABLE_STYLE,
        style_data_conditional=[{"if":{"row_index":0},"backgroundColor":ACCENT+"22","fontWeight":"700"}])

# ── App layout ───────────────────────────────────────────────
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG],
                title="F1 Dashboard", suppress_callback_exceptions=True)

SIDEBAR = dbc.Col([html.Div([
    html.Img(src="https://upload.wikimedia.org/wikipedia/commons/thumb/3/33/F1.svg/1200px-F1.svg.png",
             style={"height":"34px","marginBottom":"18px"}),
    html.Hr(style={"borderColor":GRID_CLR}),
    html.P("SESSIONS", style={"color":TEXT_DIM,"fontSize":"0.68rem","letterSpacing":"2px"}),
    dcc.Checklist(id="session-filter",
        options=[{"label":s,"value":s} for s in SESSIONS], value=SESSIONS,
        inputStyle={"marginRight":"8px","accentColor":ACCENT},
        labelStyle={"display":"block","marginBottom":"8px","fontSize":"0.78rem"}),
    html.Hr(style={"borderColor":GRID_CLR}),
    html.P("COMPOUNDS", style={"color":TEXT_DIM,"fontSize":"0.68rem","letterSpacing":"2px"}),
    dcc.Checklist(id="compound-filter",
        options=[{"label":html.Span(c,style={"color":COMPOUND_COLORS.get(c,"#fff")}),"value":c} for c in COMPOUNDS],
        value=COMPOUNDS,
        inputStyle={"marginRight":"8px","accentColor":ACCENT},
        labelStyle={"display":"block","marginBottom":"8px","fontSize":"0.78rem"}),
    html.Hr(style={"borderColor":GRID_CLR}),
    html.P("TEAMS", style={"color":TEXT_DIM,"fontSize":"0.68rem","letterSpacing":"2px"}),
    dcc.Dropdown(id="team-filter",
        options=[{"label":t,"value":t} for t in TEAMS], value=TEAMS, multi=True,
        style={"backgroundColor":"#111","fontSize":"0.78rem"}),
    html.Hr(style={"borderColor":GRID_CLR}),
    html.P("DRIVERS", style={"color":TEXT_DIM,"fontSize":"0.68rem","letterSpacing":"2px"}),
    dcc.Dropdown(id="driver-filter",
        options=[{"label":d,"value":d} for d in DRIVERS], value=DRIVERS, multi=True,
        style={"backgroundColor":"#111","fontSize":"0.78rem"}),
    html.Hr(style={"borderColor":GRID_CLR}),
    html.Small(cache_summary(), style={"color":TEXT_DIM,"fontSize":"0.65rem","whiteSpace":"pre-line"}),
], style={"padding":"16px","height":"100vh","overflowY":"auto",
          "background":"#09091A","borderRight":f"1px solid {GRID_CLR}"})],
width=2, style={"padding":"0"})

TABS = dbc.Tabs([
    dbc.Tab(label="DATA & QUALITY", tab_id="tab-data"),
    dbc.Tab(label="TRACK",          tab_id="tab-track"),
    dbc.Tab(label="OVERVIEW",       tab_id="tab-overview"),
    dbc.Tab(label="TEAM ANALYSIS",  tab_id="tab-teams"),
    dbc.Tab(label="TELEMETRY", tab_id="tab-laps"),
    dbc.Tab(label="STINTS",         tab_id="tab-stints"),
    dbc.Tab(label="PRACTICE",       tab_id="tab-practice"),
    dbc.Tab(label="RACE",           tab_id="tab-race"),
    dbc.Tab(label="TEAMMATES",      tab_id="tab-teammates"),
    dbc.Tab(label="UPGRADES",       tab_id="tab-upgrades"),
], id="tabs", active_tab="tab-data",
   style={"borderBottom":f"2px solid {ACCENT}","marginBottom":"16px"})

MAIN = dbc.Col([
    html.H2("F1 SESSION ANALYSIS",
            style={"color":ACCENT,"fontWeight":"900","letterSpacing":"3px","marginBottom":"4px","fontSize":"1.3rem"}),
    html.P(" | ".join(SESSIONS), id="main-subtitle",
           style={"color":TEXT_DIM,"marginBottom":"18px","fontSize":"0.78rem"}),
    TABS,
    html.Div(id="tab-content"),
], width=10, style={"padding":"24px","background":DARK_BG,"minHeight":"100vh"})

app.layout = dbc.Container(dbc.Row([SIDEBAR,MAIN],className="g-0"),
    fluid=True, style={"background":DARK_BG,"fontFamily":"Inter, sans-serif"})

# ── Routing callback ─────────────────────────────────────────
@app.callback(Output("tab-content","children"),
              Input("tabs","active_tab"),
              Input("session-filter","value"),
              Input("compound-filter","value"),
              Input("driver-filter","value"),
              Input("team-filter","value"))
def render(tab, ss, sc, sd, st):
    ss=ss or SESSIONS; sc=sc or COMPOUNDS; sd=sd or DRIVERS; st=st or TEAMS
    fl   = laps[laps["session_name"].isin(ss) & laps["Compound"].isin(sc)].copy()
    fl_d = fl[fl["Driver_Short"].isin(sd) & fl["Team"].isin(st)].copy()
    fs   = stints[stints["session_name"].isin(ss) & stints["Compound"].isin(sc)].copy()
    fs_d = fs[fs["Driver_Short"].isin(sd) & fs["Team"].isin(st)].copy()
    dnos = laps[laps["Driver_Short"].isin(sd)]["DriverNo"].unique()
    ft   = telemetry[telemetry["DriverNo"].isin(dnos) & telemetry["session_name"].isin(ss)].copy() if not telemetry.empty else telemetry
    if tab=="tab-data":
        return html.Div([
            tab_data_selection(),
            html.Hr(style={"borderColor": GRID_CLR, "margin": "28px 0 20px"}),
            html.H4("Data Quality",
                    style={"color": TEXT_MAIN, "fontWeight": "800", "letterSpacing": "1px",
                           "marginBottom": "12px", "fontSize": "1.05rem"}),
            tab_data_quality(fl_d, fs_d),
        ])
    if tab=="tab-overview":   return tab_overview(fl_d,fs_d,ft)
    if tab=="tab-teams":      return tab_teams(fl_d, fs_d)
    if tab=="tab-laps":       return tab_laps(fl_d, ft)
    if tab=="tab-stints":     return tab_stints(fl_d,fs_d)
    if tab=="tab-practice":
        # Practice construction / sandbagging adapts to whichever sessions are
        # selected, so unchecking Qualifying/Race lets you preview the mid-event
        # ("after FP2" / "after FP3") picture even on a fully-cached weekend.
        wl = laps[laps["session_name"].isin(ss) & laps["Driver_Short"].isin(sd)
                  & laps["Team"].isin(st) & laps["Compound"].isin(sc)].copy()
        return tab_practice(wl)
    if tab=="tab-race":       return tab_race(sd, st)
    if tab=="tab-teammates":  return tab_teammates(fl_d,fs_d)
    if tab=="tab-track":      return tab_track_info()
    if tab=="tab-upgrades":   return tab_upgrades()
    return html.P("Select a tab.")

# ── Raw Laps Inspector callback ───────────────────────────────
@app.callback(
    Output("inspector-table", "children"),
    Input("inspector-driver",  "value"),
    Input("inspector-session", "value"),
)
def update_inspector(driver, session):
    if not driver or not session:
        return html.P("Select a driver and session.", style={"color": TEXT_DIM})
    sub = laps[(laps["Driver_Short"] == driver) & (laps["session_name"] == session)].sort_values("LapNo")
    if sub.empty:
        return html.P(f"No laps found for {driver} in {session}.", style={"color": TEXT_DIM})
    wanted = ["LapNo", "LapTime_s", "Compound", 'Compound_RAW', "TyreAge", "TyreLife", "LapInStint", "Stint"]
    avail  = [c for c in wanted if c in sub.columns]
    sub    = sub[avail].copy()
    if "LapTime_s" in sub.columns:
        sub.insert(sub.columns.get_loc("LapTime_s") + 1, "LapTime", sub["LapTime_s"].apply(format_lap_time))
    return dash_table.DataTable(
        data=sub.to_dict("records"),
        columns=[{"name": c, "id": c} for c in sub.columns],
        **TABLE_STYLE,
        style_data_conditional=[
            {"if": {"filter_query": "{LapInStint} = 1"}, "borderLeft": f"3px solid {ACCENT}"},
        ],
    )

# ── Stints – Lap Evolution graph callback ────────────────────
@app.callback(
    Output("stints-evo-graph", "figure"),
    Input("stints-evo-session",  "value"),
    State("compound-filter",     "value"),
    State("driver-filter",       "value"),
    State("team-filter",         "value"),
)
def update_stints_evo(session, sc, sd, st):
    sc = sc or COMPOUNDS
    sd = sd or DRIVERS
    st = st or TEAMS

    if not session:
        return go.Figure()

    sv = laps[
        (laps["session_name"] == session)
        & laps["Compound"].isin(sc)
        & laps["Driver_Short"].isin(sd)
        & laps["Team"].isin(st)
    ].copy()

    sess_label = session.split("_")[0]
    return _lap_evolution_fig(
        sv, f"Lap Time Evolution \u2013 All Laps \u2013 {sess_label}"
    )


# ── Stint Lap Inspector callbacks ────────────────────────────
# Compound emoji map for dropdown labels
_COMPOUND_ICON = {"SOFT": "🔴", "MEDIUM": "🟡", "HARD": "⚪", "INTER": "🟢", "WET": "🔵"}


@app.callback(
    Output("stint-insp-key", "options"),
    Output("stint-insp-key", "value"),
    Input("stint-insp-driver", "value"),
    State("session-filter",   "value"),
    State("compound-filter",  "value"),
    State("team-filter",      "value"),
)
def update_stint_key_options(driver, ss, sc, st):
    """Build human-readable ranked-stint options for the inspector dropdown."""
    if not driver:
        return [], None
    ss = ss or SESSIONS
    sc = sc or COMPOUNDS
    st = st or TEAMS

    drv_stints = stints[
        (stints["Driver_Short"] == driver)
        & stints["session_name"].isin(ss)
        & stints["Compound"].isin(sc)
        & stints["Team"].isin(st)
        & stints["Valid_Stint"]
    ].copy()

    if drv_stints.empty:
        return [], None

    # Reconstruct Stint_key (analyze_stints doesn't carry it)
    drv_stints["Stint_key"] = (
        drv_stints["Stint"].astype("string")
        + "_" + drv_stints["Driver_Short"]
        + "_" + drv_stints["session_name"]
    )

    opts: list[dict] = []
    seen_keys: set[str] = set()

    def _add(label: str, row: pd.Series) -> None:
        key = row["Stint_key"]
        if pd.isna(key) or key in seen_keys:
            return
        seen_keys.add(key)
        compound = row.get("Compound", "?")
        icon     = _COMPOUND_ICON.get(compound, "⬜")
        pace_fmt = format_lap_time(row.get("Stint_Rep_Lap", float("nan")))
        laps_n   = int(row.get("Stint_Laps_Count", 0))
        sess     = str(row.get("session_name", "")).split("_")[0]
        opts.append({
            "label": f"{label}  {icon}{compound}  {pace_fmt}  ({laps_n} laps, {sess})",
            "value": key,
        })

    # ── 1. Best overall (lowest Stint_Rep_Lap across all valid stints) ──
    if "Stint_Rank_Overall" in drv_stints.columns:
        best_overall = drv_stints.sort_values("Stint_Rep_Lap").iloc[0]
        _add("Best overall", best_overall)

    # ── 2. Best per session (Stint_Rank_No_Compound = 1 in that session) ──
    for sess in sorted(drv_stints["session_name"].unique()):
        sess_label = sess.split("_")[0]
        sub = drv_stints[drv_stints["session_name"] == sess].sort_values("Stint_Rep_Lap")
        if not sub.empty:
            _add(f"Best in {sess_label}", sub.iloc[0])

    # ── 3. Best per compound (Stint_Rank_Across_Sessions = 1) ──
    for compound in COMPOUNDS:
        sub = drv_stints[drv_stints["Compound"] == compound].sort_values("Stint_Rep_Lap")
        if sub.empty:
            continue
        icon = _COMPOUND_ICON.get(compound, "⬜")
        _add(f"{icon} Best on {compound}", sub.iloc[0])

    # ── 4. Any remaining valid stints not yet listed ──
    for _, row in drv_stints.sort_values("Stint_Rep_Lap").iterrows():
        if row["Stint_key"] not in seen_keys:
            _add(f"   Stint {int(row['Stint'])}", row)

    first_val = opts[0]["value"] if opts else None
    return opts, first_val


@app.callback(
    Output("stint-insp-table", "children"),
    Input("stint-insp-driver", "value"),
    Input("stint-insp-key",    "value"),
)
def render_stint_table(driver, stint_key):
    if not driver or not stint_key:
        return html.P("Select a driver and stint key.", style={"color": TEXT_DIM})
    sub = laps[
        (laps["Driver_Short"] == driver) & (laps["Stint_key"] == stint_key)
    ].sort_values("LapNo")
    if sub.empty:
        return html.P("No laps found for this selection.", style={"color": TEXT_DIM})
    cols_want  = ["Stint_key", "LapNo", "LapTime_s", "Compound", "TyreAge", "LapInStint"]
    cols_avail = [c for c in cols_want if c in sub.columns]
    sub = sub[cols_avail].copy()
    if "LapTime_s" in sub.columns:
        pos = sub.columns.get_loc("LapTime_s") + 1
        sub.insert(pos, "LapTime", sub["LapTime_s"].apply(format_lap_time))
    return dash_table.DataTable(
        data=sub.to_dict("records"),
        columns=[{"name": c, "id": c} for c in sub.columns],
        **TABLE_STYLE,
        style_data_conditional=[
            {"if": {"filter_query": "{LapInStint} = 1"},
             "borderLeft": f"3px solid {ACCENT}"},
        ],
    )


# ══════════════════════════════════════════════════════════════
# TAB – DATA SELECTION  (load / unload sessions at runtime)
# ══════════════════════════════════════════════════════════════
def tab_data_selection() -> html.Div:
    try:
        return _tab_data_selection_inner()
    except Exception as exc:
        import traceback
        return html.Div([
            dbc.Alert([html.B("Data Selection error: "), str(exc)],
                      color="danger", style={"fontSize": "0.82rem"}),
            html.Pre(traceback.format_exc(), style={
                "color": TEXT_DIM, "fontSize": "0.7rem", "background": "#09091A",
                "padding": "12px", "borderRadius": "6px", "overflowX": "auto",
            }),
        ])


def _tab_data_selection_inner() -> html.Div:
    season = AVAILABLE_SEASON
    avail  = get_available_sessions(season)
    loaded_values = {
        _sess_value(i["SEASON"], i["MEETING"], i["SESSION"]) for i in LOADED_SESSION_INFO
    }
    pre_selected = [it["value"] for it in avail if it["value"] in loaded_values]

    status_banner = (
        dbc.Alert(LAST_LOAD_MSG, color="info",
                  style={"fontSize": "0.8rem", "borderRadius": "6px", "marginBottom": "12px"})
        if LAST_LOAD_MSG else html.Div()
    )

    sc_style  = {"fontSize": "0.72rem", "marginRight": "6px", "marginBottom": "6px"}
    lbl_style = {"color": TEXT_DIM, "fontSize": "0.65rem", "letterSpacing": "1px",
                 "fontWeight": "700", "marginBottom": "4px", "display": "block"}

    return html.Div([
        html.H4("Session Data Selection",
                style={"color": TEXT_MAIN, "fontWeight": "800", "letterSpacing": "1px",
                       "marginBottom": "6px", "fontSize": "1.05rem"}),
        html.P([
            "Pick which sessions to load into the dashboard. Pick a season, then "
            "use the shortcuts or tick individual sessions. Sessions already "
            "downloaded are marked ",
            html.Span("● cached", style={"color": "#00D2BE", "fontWeight": "700"}),
            "; selecting an ",
            html.Span("○ fetch", style={"color": "#FF8700", "fontWeight": "700"}),
            " session downloads it from FastF1 the first time (1–3 min each).",
        ], style={"color": TEXT_DIM, "fontSize": "0.82rem", "marginBottom": "10px"}),

        status_banner,

        dbc.Row([
            kpi("CURRENTLY LOADED", str(len(SESSIONS)), ACCENT,
                tooltip="Sessions currently active in the dashboard."),
        ]),

        card("Select Sessions", html.Div([
            # ── Season selector ───────────────────────────────
            dbc.Row([
                dbc.Col([
                    html.Label("SEASON", style=lbl_style),
                    dcc.Dropdown(
                        id="data-season-select",
                        options=[{"label": str(y), "value": y} for y in SELECTABLE_SEASONS],
                        value=season, clearable=False,
                        style={"backgroundColor": "#111", "fontSize": "0.82rem"},
                    ),
                ], md=3),
            ], className="mb-3"),

            # ── Add all sessions for one circuit (one click each) ──
            html.Label("ADD ALL SESSIONS FOR A CIRCUIT", style=lbl_style),
            html.Div(_circuit_buttons(season), id="data-circuit-btns",
                     style={"marginBottom": "8px"}),

            # ── Shortcut buttons by session type ──────────────
            html.Label("QUICK SELECT BY TYPE  (adds to current selection)", style=lbl_style),
            html.Div([
                dbc.Button("+ All Practice",   id="data-sel-practice", size="sm", color="secondary", outline=True, style=sc_style),
                dbc.Button("+ All Qualifying", id="data-sel-quali",    size="sm", color="secondary", outline=True, style=sc_style),
                dbc.Button("+ All Sprint",     id="data-sel-sprint",   size="sm", color="secondary", outline=True, style=sc_style),
                dbc.Button("+ All Race",       id="data-sel-race",     size="sm", color="secondary", outline=True, style=sc_style),
            ], style={"marginBottom": "8px"}),

            html.Label("WHOLE LIST", style=lbl_style),
            html.Div([
                dbc.Button("Select all",         id="data-sel-all",    size="sm", color="secondary", outline=True, style=sc_style),
                dbc.Button("Select cached only", id="data-sel-cached", size="sm", color="secondary", outline=True, style=sc_style),
                dbc.Button("Clear",              id="data-sel-clear",  size="sm", color="secondary", outline=True, style=sc_style),
            ], style={"marginBottom": "10px"}),

            html.Div(_list_summary(season), id="data-list-summary",
                     style={"color": TEXT_DIM, "fontSize": "0.72rem", "marginBottom": "8px"}),

            # ── The scrollable session checklist ──────────────
            html.Div(
                dcc.Checklist(
                    id="data-session-select",
                    options=_session_options(season),
                    value=pre_selected,
                    inputStyle={"marginRight": "8px", "accentColor": ACCENT},
                    labelStyle={"display": "block", "marginBottom": "6px",
                                "fontSize": "0.8rem", "color": TEXT_MAIN},
                ),
                style={"maxHeight": "360px", "overflowY": "auto",
                       "border": f"1px solid {GRID_CLR}", "borderRadius": "6px",
                       "padding": "10px", "background": "#0E0E1C"},
            ),

            html.Hr(style={"borderColor": GRID_CLR}),
            dbc.Button("⟳  Load Selected Sessions", id="data-load-btn",
                       color="danger", style={"fontWeight": "700"}),
            dcc.Loading(
                type="circle", color=ACCENT,
                children=html.Div(id="data-load-status", style={"marginTop": "12px"}),
            ),
        ])),
    ])


# ── Session selector: season switch + shortcut buttons ───────
@app.callback(
    Output("data-session-select", "options"),
    Output("data-session-select", "value"),
    Output("data-list-summary",   "children"),
    Output("data-circuit-btns",   "children"),
    Input("data-season-select",   "value"),
    Input("data-sel-all",      "n_clicks"),
    Input("data-sel-cached",   "n_clicks"),
    Input("data-sel-clear",    "n_clicks"),
    Input("data-sel-practice", "n_clicks"),
    Input("data-sel-quali",    "n_clicks"),
    Input("data-sel-sprint",   "n_clicks"),
    Input("data-sel-race",     "n_clicks"),
    Input({"type": "data-circuit-btn", "index": ALL}, "n_clicks"),
    State("data-session-select", "value"),
    prevent_initial_call=True,
)
def update_session_controls(season, _a, _c, _z, _p, _q, _s, _r, _circ, cur_value):
    trig    = ctx.triggered_id
    season  = int(season) if season else AVAILABLE_SEASON
    avail   = get_available_sessions(season)
    options = _session_options(season)
    summary = _list_summary(season)

    # Season switch → rebuild list + per-circuit buttons, preselect loaded sessions
    if trig == "data-season-select":
        loaded_values = {
            _sess_value(i["SEASON"], i["MEETING"], i["SESSION"]) for i in LOADED_SESSION_INFO
        }
        value = [it["value"] for it in avail if it["value"] in loaded_values]
        return options, value, summary, _circuit_buttons(season)

    # All other triggers keep the same season → buttons untouched
    cur = list(cur_value or [])
    seen = set(cur)

    def _union(pred):
        for it in avail:
            if pred(it) and it["value"] not in seen:
                cur.append(it["value"]); seen.add(it["value"])
        return cur

    if isinstance(trig, dict) and trig.get("type") == "data-circuit-btn":
        # Pattern-matching button can fire on (re)creation with n_clicks=None;
        # ignore those no-op triggers.
        if not any((ctx.triggered[0]["value"],)):
            value = cur
        else:
            value = _union(lambda it: it["meeting"] == trig["index"])
    elif trig == "data-sel-all":      value = [it["value"] for it in avail]
    elif trig == "data-sel-cached":   value = [it["value"] for it in avail if it["cached"]]
    elif trig == "data-sel-clear":    value = []
    elif trig == "data-sel-practice": value = _union(lambda it: _session_type(it["session"]) == "Practice")
    elif trig == "data-sel-quali":    value = _union(lambda it: it["session"] == "Qualifying")
    elif trig == "data-sel-sprint":   value = _union(lambda it: _session_type(it["session"]) == "Sprint")
    elif trig == "data-sel-race":     value = _union(lambda it: it["session"] == "Race")
    else:                             value = cur

    return options, value, summary, no_update


# ── Load selected sessions (rebuilds app state) ──────────────
@app.callback(
    Output("data-load-status",  "children"),
    Output("session-filter",    "options"),
    Output("session-filter",    "value"),
    Output("compound-filter",   "options"),
    Output("compound-filter",   "value"),
    Output("team-filter",       "options"),
    Output("team-filter",       "value"),
    Output("driver-filter",     "options"),
    Output("driver-filter",     "value"),
    Output("main-subtitle",     "children"),
    Input("data-load-btn",      "n_clicks"),
    State("data-session-select", "value"),
    prevent_initial_call=True,
)
def load_selected(_n, selected):
    if not selected:
        warn = dbc.Alert("Select at least one session before loading.",
                         color="warning", style={"fontSize": "0.8rem"})
        return (warn, *([no_update] * 9))

    info = [_parse_sess_value(v) for v in selected]
    try:
        msg = rebuild_state(info)
        ok  = msg.startswith("Loaded")
    except Exception as exc:
        import traceback
        return (
            dbc.Alert([html.B("Load failed: "), str(exc),
                       html.Pre(traceback.format_exc(),
                                style={"fontSize": "0.68rem", "marginTop": "8px",
                                       "whiteSpace": "pre-wrap"})],
                      color="danger", style={"fontSize": "0.8rem"}),
            *([no_update] * 9),
        )

    status = dbc.Alert(("✅ " if ok else "⚠️ ") + msg,
                       color="success" if ok else "warning",
                       style={"fontSize": "0.82rem"})
    if not ok:
        return (status, *([no_update] * 9))

    sess_opts = [{"label": s, "value": s} for s in SESSIONS]
    comp_opts = [{"label": html.Span(c, style={"color": COMPOUND_COLORS.get(c, "#fff")}),
                  "value": c} for c in COMPOUNDS]
    team_opts = [{"label": t, "value": t} for t in TEAMS]
    drv_opts  = [{"label": d, "value": d} for d in DRIVERS]
    subtitle  = " | ".join(SESSIONS)
    return (status,
            sess_opts, SESSIONS,
            comp_opts, COMPOUNDS,
            team_opts, TEAMS,
            drv_opts,  DRIVERS,
            subtitle)


# ══════════════════════════════════════════════════════════════
# TAB 0 – DATA QUALITY
# ══════════════════════════════════════════════════════════════
def _badge(text, color):
    """Small coloured pill."""
    return html.Span(text, style={
        "background": color, "color": "#fff", "borderRadius": "4px",
        "padding": "2px 8px", "fontSize": "0.7rem", "fontWeight": "700",
        "letterSpacing": "0.5px", "marginLeft": "6px",
    })

def _status_icon(ok: bool):
    return "✅" if ok else "❌"

def tab_data_quality(fl, fs):
    # ── 0. Global counts ────────────────────────────────────
    raw_rows      = len(laps_raw)
    enr_rows      = len(laps)
    row_match     = raw_rows == enr_rows

    total         = len(laps)
    has_laptime   = int(laps["LapTime_s"].notna().sum())
    pct_laptime   = has_laptime / total * 100 if total else 0
    valid_count   = int(laps["ValidLap"].sum())
    pct_valid     = valid_count / total * 100 if total else 0
    pit_count     = int(laps["PitLap"].sum())
    outlier_count = int((
        laps["LapTime_s"].notna()
        & (laps["LapTime_s"] > laps["LapTime_s"].median() * 1.25)
        & ~laps["PitLap"]
    ).sum())
    if "Perturbed_Lap" in laps.columns:
        perturbed_count = int(laps["Perturbed_Lap"].sum())
        pct_perturbed   = perturbed_count / total * 100 if total else 0
    else:
        perturbed_count = None
        pct_perturbed   = None

    # ── 1. Per-session overview ──────────────────────────────
    per_sess = (
        laps.groupby("session_name")
        .agg(
            Total_Laps   =("LapNo",       "count"),
            Valid_Laps   =("ValidLap",     "sum"),
            Pit_Laps     =("PitLap",       "sum"),
            With_LapTime =("LapTime_s",    lambda x: x.notna().sum()),
            Drivers      =("Driver_Short", "nunique"),
            Teams        =("Team",         "nunique"),
            Best_Lap_s   =("LapTime_s",    "min"),
            Median_Lap_s =("LapTime_s",    "median"),
            Stints       =("Stint",        "max"),
        )
        .reset_index()
    )
    per_sess["Valid_%"]   = (per_sess["Valid_Laps"]   / per_sess["Total_Laps"] * 100).round(1)
    per_sess["LapTime_%"] = (per_sess["With_LapTime"] / per_sess["Total_Laps"] * 100).round(1)
    per_sess["Best Lap"]  = per_sess["Best_Lap_s"].apply(format_lap_time)
    per_sess = per_sess.rename(columns={"session_name": "Session"})

    sess_tbl = styled_table(
        per_sess[[
            "Session", "Total_Laps", "Valid_Laps", "Valid_%", "Pit_Laps",
            "LapTime_%", "Drivers", "Teams", "Stints", "Best Lap",
        ]].to_dict("records"),
        [{"name": c, "id": c} for c in [
            "Session", "Total_Laps", "Valid_Laps", "Valid_%", "Pit_Laps",
            "LapTime_%", "Drivers", "Teams", "Stints", "Best Lap",
        ]],
    )

    # ── 2. Per-session timing leaderboard (sanity check) ────
    sanity_rows = []
    for sess in SESSIONS:
        sub = laps[(laps["session_name"] == sess) & laps["ValidLap"]].copy()
        if sub.empty:
            continue
        best = (
            sub.groupby("Driver_Short")
            .agg(Best_s=("LapTime_s", "min"), Team=("Team", "first"))
            .reset_index()
            .sort_values("Best_s")
            .reset_index(drop=True)
        )
        best["Rank"]    = best.index + 1
        best["Gap"]     = (best["Best_s"] - best["Best_s"].iloc[0]).apply(
            lambda x: "—" if x == 0 else f"+{x:.3f} s"
        )
        best["Lap Time"] = best["Best_s"].apply(format_lap_time)
        best["Session"]  = sess
        # add compound used on best lap
        best_lap_rows = (
            sub.loc[sub.groupby("Driver_Short")["LapTime_s"].idxmin()][
                ["Driver_Short", "Compound", "TyreAge", "LapNo"]
            ]
        )
        best = best.merge(best_lap_rows, on="Driver_Short", how="left")
        sanity_rows.append(best[["Rank","Session","Driver_Short","Team",
                                  "Lap Time","Gap","Compound","TyreAge","LapNo"]].head(3))

    sanity_df   = pd.concat(sanity_rows, ignore_index=True) if sanity_rows else pd.DataFrame()
    sanity_cols = ["Rank","Session","Driver_Short","Team","Lap Time","Gap","Compound","TyreAge","LapNo"]
    sanity_tbl  = styled_table(
        sanity_df.to_dict("records") if not sanity_df.empty else [],
        [{"name": c, "id": c} for c in sanity_cols] if not sanity_df.empty else [],
    )

    # ── 3. LapTime coverage bar (per session) ───────────────
    fig_cov = go.Figure()
    for _, row in per_sess.iterrows():
        sess = row["Session"]
        fig_cov.add_trace(go.Bar(
            x=[sess], y=[row["Valid_%"]],  name="Valid",
            marker_color="#00D2BE", showlegend=(_ == 0),
        ))
        fig_cov.add_trace(go.Bar(
            x=[sess], y=[row["LapTime_%"]], name="Has LapTime",
            marker_color="#FF8700", showlegend=(_ == 0),
        ))
    theme(fig_cov, 300, "Coverage per Session (%)")
    fig_cov.update_layout(barmode="group", yaxis=dict(range=[0,105], gridcolor=GRID_CLR, zeroline=False),
                           xaxis_title="Session", yaxis_title="%")

    # ── 5. ValidLap breakdown donut per session ──────────────
    breakdown_cards = []
    for sess in SESSIONS:
        sub = laps[laps["session_name"] == sess]
        n_valid    = int(sub["ValidLap"].sum())
        n_pit      = int(sub["PitLap"].sum())
        n_no_time  = int(sub["LapTime_s"].isna().sum())
        n_outlier  = int((
            sub["LapTime_s"].notna()
            & (sub["LapTime_s"] > sub["LapTime_s"].median() * 1.25)
            & ~sub["PitLap"]
        ).sum())
        n_other    = len(sub) - n_valid - n_pit - n_no_time - n_outlier
        n_other    = max(n_other, 0)
        fig_d = px.pie(
            names=["Valid","Pit/OutLap","No LapTime","Outlier (>125%)","Other excluded"],
            values=[n_valid, n_pit, n_no_time, n_outlier, n_other],
            color_discrete_sequence=["#00D2BE","#FF8700","#FFC0CB","#E10600","#808080"],
            hole=0.55,
        )
        theme(fig_d, 260, sess)
        fig_d.update_traces(textinfo="percent+label", textfont_size=9)
        fig_d.update_layout(showlegend=False, margin=dict(l=10,r=10,t=40,b=10))
        breakdown_cards.append(dbc.Col(dcc.Graph(figure=fig_d, config=GFX), md=6))

    # ── 6. Multi-compound stints (integrity check on RAW labels) ─
    # Uses Compound_RAW so we measure the original data quality
    # independently of the cleaning step.
    _compound_col = "Compound_RAW" if "Compound_RAW" in laps.columns else "Compound"
    stint_comp = (
        laps.dropna(subset=[_compound_col])
        .groupby("Stint_key")[_compound_col]
        .nunique()
        .reset_index()
        .rename(columns={_compound_col: "N_Compounds"})
    )
    dirty = stint_comp[stint_comp["N_Compounds"] > 1].copy()
    n_dirty        = len(dirty)
    n_total_stints = len(stint_comp)
    dirty_pct      = n_dirty / n_total_stints * 100 if n_total_stints else 0
    if n_dirty > 0:
        dirty_detail = laps[laps["Stint_key"].isin(dirty["Stint_key"])].groupby(
            ["Stint_key","session_name","Driver_Short","Stint"]
        ).agg(
            Raw_Compounds   =(  _compound_col, lambda x: ", ".join(x.dropna().unique())),
            Clean_Compounds =("Compound",      lambda x: ", ".join(x.dropna().unique())),
        ).reset_index()
        dirty_rows = dirty_detail.to_dict("records")
        dirty_cols = [{"name": c, "id": c} for c in dirty_detail.columns]
    else:
        dirty_rows, dirty_cols = [], []

    dirty_status = _status_icon(n_dirty == 0)
    dirty_tbl    = styled_table(dirty_rows, dirty_cols) if n_dirty > 0 else html.P(
        "✅ All stints use a single compound.", style={"color":"#00D2BE","fontWeight":"700"}
    )

    # ── 6b. Valid stints after cleaning ──────────────────────
    # How many stints pass the minimum-laps threshold on the CLEAN compound?
    # Mirrors analyze_stints logic: count valid laps per driver×stint×compound,
    # compare against the per-compound minimum.
    _stint_laps = (
        laps[laps["ValidLap"]]
        .groupby(["session_name", "Driver_Short", "Stint", "Compound"])
        .size()
        .reset_index(name="_laps")
    )
    _stint_laps["_min_req"] = _stint_laps["Compound"].apply(get_min_laps_for_compound)
    _stint_laps["_passes"]  = _stint_laps["_laps"] >= _stint_laps["_min_req"]
    n_stints_total = len(_stint_laps)
    n_stints_valid = int(_stint_laps["_passes"].sum())
    pct_stints_valid = n_stints_valid / n_stints_total * 100 if n_stints_total else 0

    # ── 7. PseudoTyreAge vs TyreAge comparison ───────────────
    has_tyre_col = "TyreAge" in laps.columns
    if has_tyre_col:
        _pool  = laps[laps["TyreAge"].notna() & laps["PseudoTyreAge"].notna()]
        sample = _pool.sample(min(2000, len(_pool)), random_state=42)
        fig_tyre = go.Figure(go.Scatter(
            x=sample["TyreAge"], y=sample["PseudoTyreAge"],
            mode="markers", marker=dict(size=4, color=ACCENT, opacity=0.5),
            hovertemplate="TyreAge: %{x}<br>PseudoTyreAge: %{y}<extra></extra>",
        ))
        mn = min(sample["TyreAge"].min(), sample["PseudoTyreAge"].min())
        mx = max(sample["TyreAge"].max(), sample["PseudoTyreAge"].max())
        fig_tyre.add_trace(go.Scatter(x=[mn,mx], y=[mn,mx], mode="lines",
            line=dict(color="#00D2BE", dash="dash", width=1), name="Perfect match"))
        theme(fig_tyre, 380, "PseudoTyreAge vs TyreAge (should be on the diagonal)")
        fig_tyre.update_layout(xaxis_title="TyreAge (raw)", yaxis_title="PseudoTyreAge (computed)")
        delta = (sample["PseudoTyreAge"] - sample["TyreAge"]).abs().mean()
        tyre_note = f"Mean absolute deviation: {delta:.2f} laps"
    else:
        fig_tyre = None
        tyre_note = "TyreAge column not present in dataset — PseudoTyreAge cannot be cross-validated."

    # ── 8. Unknown teams ────────────────────────────────────
    unknown_drvs = sorted(laps[laps["Team"] == "Unknown"]["Driver_Short"].unique())

    # ── 9. Column schema table ───────────────────────────────
    schema = pd.DataFrame({
        "Column":     laps.columns.tolist(),
        "DType":      [str(laps[c].dtype) for c in laps.columns],
        "Non-Null":   [int(laps[c].notna().sum()) for c in laps.columns],
        "NaN Count":  [int(laps[c].isna().sum())  for c in laps.columns],
        "NaN %":      [(laps[c].isna().sum() / total * 100).round(1) for c in laps.columns],
        "Unique Vals":[int(laps[c].nunique(dropna=False)) for c in laps.columns],
        "Sample":     [str(laps[c].dropna().iloc[0]) if laps[c].notna().any() else "—"
                       for c in laps.columns],
    })
    # highlight high-nan columns in red
    schema_tbl = dash_table.DataTable(
        data=schema.to_dict("records"),
        columns=[{"name": c, "id": c} for c in schema.columns],
        **TABLE_STYLE,
        style_data_conditional=[
            {"if": {"filter_query": "{NaN %} > 50"}, "backgroundColor": "#3D0A0A", "color": "#FF9999"},
            {"if": {"filter_query": "{NaN %} > 20 && {NaN %} <= 50"}, "backgroundColor": "#2D200A"},
            {"if": {"filter_query": "{NaN %} = 0"}, "color": "#00D2BE"},
        ],
    )

    # ── 10. Compound distribution heat (driver × compound × session) ─
    comp_counts = (
        fl[fl["ValidLap"]]
        .groupby(["session_name","Driver_Short","Compound"])
        .size()
        .reset_index(name="Laps")
    )
    if not comp_counts.empty:
        pivot_cc = comp_counts.pivot_table(
            index="Driver_Short", columns=["session_name","Compound"],
            values="Laps", fill_value=0
        )
        pivot_cc.columns = [f"{s}|{c}" for s, c in pivot_cc.columns]
        fig_comp_heat = go.Figure(go.Heatmap(
            z=pivot_cc.values,
            x=list(pivot_cc.columns),
            y=list(pivot_cc.index),
            colorscale="Blues",
            text=pivot_cc.values,
            texttemplate="%{text}",
            textfont={"size": 9},
            hovertemplate="Driver: %{y}<br>Session|Compound: %{x}<br>Valid Laps: %{z}<extra></extra>",
            colorbar=dict(title=dict(text="Laps", font=dict(color=TEXT_MAIN)), tickfont=dict(color=TEXT_MAIN)),
        ))
        theme(fig_comp_heat, max(300, 26 * len(pivot_cc) + 120),
              "Valid Laps per Driver × Session × Compound")
        fig_comp_heat.update_layout(
            margin=dict(l=80,r=60,t=60,b=120),
            xaxis=dict(tickangle=45, gridcolor=GRID_CLR, zeroline=False),
        )
    else:
        fig_comp_heat = None

    # ── Build layout ─────────────────────────────────────────
    return html.Div([
        # ── KPI row 1 ────────────────────────────────────────
        dbc.Row([
            kpi("TOTAL LAPS (raw)",      f"{raw_rows:,}", "#808080",
                tooltip="Raw row count from livef1 before any enrichment or cleaning."),
            kpi("TOTAL LAPS (enriched)", f"{enr_rows:,}",
                "#00D2BE" if row_match else ACCENT,
                tooltip="Row count after clean_and_enrich_laps(). Should match raw — a mismatch indicates a pipeline bug."),
            kpi("HAS LAP TIME",          f"{pct_laptime:.1f}%", "#FF8700",
                tooltip="% of laps with a non-null LapTime_s. Laps without a time are excluded from all pace analysis."),
            kpi("VALID LAPS",            f"{pct_valid:.1f}%", "#00D2BE",
                tooltip="% of laps passing ALL validity checks: non-pit, non-deleted, has LapTime, and within 125% of compound/team/session median."),
        ]),
        dbc.Row([
            kpi("ROW COUNT MATCH",  f"{_status_icon(row_match)} {'OK' if row_match else 'MISMATCH'}",
                "#00D2BE" if row_match else ACCENT,
                tooltip="Confirms clean_and_enrich_laps() preserved the exact row count. Any change indicates unintended row creation or deletion."),
            kpi("PIT / OUT LAPS",   f"{pit_count:,}", "#FFC0CB",
                tooltip="Laps where the driver entered or exited the pit lane. Excluded from pace and degradation analysis."),
            kpi("OUTLIERS REMOVED", f"{outlier_count:,}", ACCENT,
                tooltip="Laps slower than 125% of the per-session/compound/team median (excluding pit laps). Does NOT use flag_perturbed_laps — see PERTURBED LAPS below."),
            kpi("DIRTY STINTS (raw)",
                f"{dirty_status} {dirty_pct:.1f}% ({n_dirty}/{n_total_stints})",
                "#00D2BE" if n_dirty == 0 else ACCENT,
                tooltip="Based on Compound_RAW: % of stints where more than one raw compound label was recorded. Includes UNKNOWN/NaN that were later cleaned. Non-zero is expected — see the Stint Compound Integrity table below."),
            kpi("VALID STINTS (clean)",
                f"{pct_stints_valid:.1f}% ({n_stints_valid}/{n_stints_total})",
                "#00D2BE" if pct_stints_valid >= 50 else ACCENT,
                tooltip=f"After compound cleaning: % of driver×stint×compound groups meeting the minimum lap threshold (SOFT≥{MIN_LAPS_SOFT}, MEDIUM≥{MIN_LAPS_MEDIUM}, HARD≥{MIN_LAPS_HARD}). These are the stints usable for race pace and degradation analysis."),
        ]),
        *([dbc.Row([
            kpi("PERTURBED LAPS", f"{pct_perturbed:.1f}% ({perturbed_count:,})", "#FFC0CB",
                tooltip="Laps flagged by flag_perturbed_laps(): either TrackStatus indicates Yellow/SC/VSC/RedFlag, OR a sector time anomaly (>2.5× IQR above 75th pct for that driver/session/compound) was detected. These laps are NOT automatically excluded by ValidLap — filter on Perturbed_Lap=False for clean pace analysis."),
        ])] if perturbed_count is not None else []),

        # ── Pipeline check alerts ─────────────────────────────
        *([dbc.Alert(
            f"⚠️  Row count mismatch: raw={raw_rows:,} → enriched={enr_rows:,} "
            f"({enr_rows-raw_rows:+,} rows). Check clean_and_enrich_laps().",
            color="danger", style={"fontSize":"0.8rem","borderRadius":"6px"},
        )] if not row_match else []),
        *([dbc.Alert(
            f"⚠️  Unknown team detected for: {', '.join(unknown_drvs)}. "
            "The Driver column format may not contain '-TeamName'.",
            color="warning", style={"fontSize":"0.8rem","borderRadius":"6px"},
        )] if unknown_drvs else []),

        # ── Coverage & breakdown ─────────────────────────────
        card("Session Coverage (%)", dcc.Graph(figure=fig_cov, config=GFX),
             info=("Data: every enriched lap, grouped by session. Bars show the "
                   "share of laps that are Valid (teal) and that carry a recorded "
                   "LapTime (orange). Why: a quick completeness check — low coverage "
                   "means that session's pace analysis rests on few usable laps.")),
        card("Lap Breakdown by Session", dbc.Row(breakdown_cards),
             info=("Data: all laps per session, classified into Valid, Pit/Out-lap, "
                   "No LapTime, Outlier (>125% of median) and Other-excluded. Why: "
                   "shows exactly why laps are dropped before analysis, so you can "
                   "judge how representative the surviving 'valid' laps are.")),

        # ── Per-session table ────────────────────────────────
        card("Per-Session Statistics", sess_tbl),

        # ── Timing leaderboard (sanity) ──────────────────────
        card(
            html.Span([
                "Timing Leaderboard — Sanity Check  (Top 3 per session)",
                _badge("compare against live memory", "#444"),
            ]),
            sanity_tbl,
        ),

        # ── Compound × Driver heatmap (sidebar-filtered) ─────
        *([card("Valid Laps: Driver × Session × Compound",
                dcc.Graph(figure=fig_comp_heat, config=GFX),
                info=("Data: count of valid laps per driver × session × compound "
                      "(respects the sidebar filters). Why: a sample-size map — "
                      "darker cells mean more laps, so you can see which "
                      "driver/compound/session combinations have enough data to "
                      "trust the pace and degradation numbers elsewhere."))]
          if fig_comp_heat else []),

        # ── Raw Laps Inspector ───────────────────────────────
        card(
            "Raw Laps Inspector",
            html.Div([
                html.P("Inspect every lap for one driver in one session — useful for verifying stint/tyre age detection.",
                       style={"color":TEXT_DIM,"fontSize":"0.8rem","marginBottom":"10px"}),
                dbc.Row([
                    dbc.Col([
                        html.Label("Driver", style={"color":TEXT_DIM,"fontSize":"0.75rem","letterSpacing":"1px"}),
                        dcc.Dropdown(
                            id="inspector-driver",
                            options=[{"label":d,"value":d} for d in sorted(laps["Driver_Short"].dropna().unique())],
                            value=sorted(laps["Driver_Short"].dropna().unique())[0] if len(laps["Driver_Short"].dropna().unique()) else None,
                            style={"backgroundColor":"#111","fontSize":"0.82rem"},
                            clearable=False,
                        ),
                    ], md=4),
                    dbc.Col([
                        html.Label("Session", style={"color":TEXT_DIM,"fontSize":"0.75rem","letterSpacing":"1px"}),
                        dcc.Dropdown(
                            id="inspector-session",
                            options=[{"label":s,"value":s} for s in SESSIONS],
                            value=SESSIONS[0] if SESSIONS else None,
                            style={"backgroundColor":"#111","fontSize":"0.82rem"},
                            clearable=False,
                        ),
                    ], md=4),
                ], className="mb-3"),
                html.Div(id="inspector-table"),
            ]),
        ),

        # ── Multi-compound stints ────────────────────────────
        card(
            html.Span([
                f"{dirty_status} Stint Compound Integrity (Compound_RAW)",
                _badge(f"{n_dirty} dirty stints ({dirty_pct:.1f}%)", "#00D2BE" if n_dirty==0 else ACCENT),
                _badge("Raw labels before cleaning — non-zero is expected", "#444"),
            ]),
            dirty_tbl,
        ),

        # ── TyreAge cross-validation ─────────────────────────
        card(
            "PseudoTyreAge vs TyreAge Cross-Validation",
            html.Div([
                html.P(tyre_note, style={"color": TEXT_DIM, "fontSize": "0.8rem", "marginBottom": "8px"}),
                dcc.Graph(figure=fig_tyre, config=GFX) if fig_tyre else html.Div(),
            ]),
            info=("Data: a random sample of up to 2000 laps that have both the raw "
                  "TyreAge (from the source feed) and the pipeline-computed "
                  "PseudoTyreAge. Why: each point should sit on the dashed diagonal "
                  "if our stint/tyre-age reconstruction is correct — drift off the "
                  "line flags a bug in the tyre-age logic."),
        ),

        # ── Column schema ────────────────────────────────────
        card(
            html.Span([
                "Column Schema",
                _badge("green = 0% NaN  |  yellow = <50%  |  red = >50%", "#444"),
            ]),
            schema_tbl,
        ),
    ])


def tab_overview(fl, fs, ft=None):
    v = fl[fl["ValidLap"]]
    best = format_lap_time(v["LapTime_s"].min()) if len(v) else "—"

    fig_vio = go.Figure()
    for drv in sorted(v["Driver_Short"].dropna().unique()):
        sub  = v[v["Driver_Short"]==drv]["LapTime_s"]
        team = fl[fl["Driver_Short"]==drv]["Team"].iloc[0]
        clr  = TEAM_COLORS.get(team,"#808080")
        fig_vio.add_trace(go.Violin(x=sub, name=drv,
            line_color=clr, fillcolor="rgba({},{},{},0.27)".format(
    int(clr[1:3],16), int(clr[3:5],16), int(clr[5:7],16)
), meanline_visible=True,
            orientation="h", points="all", jitter=0.05, pointpos=0,
            marker=dict(size=3,color=clr)))
    theme(fig_vio,420,"Lap Time Distribution by Driver")
    fig_vio.update_layout(violinmode="overlay",showlegend=False,xaxis_title="Lap Time (s)")

    cc = fl["Compound"].value_counts().reset_index()
    cc.columns=["Compound","Count"]
    fig_pie = px.pie(cc,names="Compound",values="Count",
                     color="Compound",color_discrete_map=COMPOUND_COLORS,hole=0.55)
    theme(fig_pie,300,"Compound Distribution")

    tm = team_metrics(fl)
    tm["Best Lap"] = tm["Best_Lap_s"].apply(format_lap_time)
    tm["Gap"]      = tm["Gap_to_Best_s"].apply(lambda x:f"+{x:.3f}" if x>0 else "—")
    tbl = styled_table(
        tm[["Team","Best Lap","Gap","Median_Lap_s","Lap_Std_s","Consistency","Avg_Speed","Laps"]].rename(columns={
            "Median_Lap_s":"Median (s)","Lap_Std_s":"Std Dev","Consistency":"Consistency %","Avg_Speed":"Avg Speed"
        }).to_dict("records"),
        [{"name":c,"id":c} for c in ["Team","Best Lap","Gap","Median (s)","Std Dev","Consistency %","Avg Speed","Laps"]]
    )
    # ── Driver Performance Matrix ─────────────────────────────
    tg = tmgaps(fl)
    fig_bub = go.Figure()
    max_laps = max(tg["Laps_count"].max(), 1)
    for team in sorted(tg["Team"].unique()):
        g   = tg[tg["Team"] == team]
        clr = TEAM_COLORS.get(team, "#808080")
        fig_bub.add_trace(go.Scatter(
            x=g["Best_Lap"], y=g["Race_Median"],
            mode="markers+text", name=team,
            marker=dict(color=clr, size=g["Laps_count"],
                        sizemode="area", sizeref=2.*max_laps/(40.**2),
                        symbol="circle"),
            text=g["Driver_Short"], textposition="top center",
            textfont=dict(size=10, color=TEXT_MAIN),
            customdata=g[["Driver_Short","Race_Lap_Std_s",
                           "Quali_Gap_to_Teammate_s","Race_Gap_to_Teammate_s"]].values,
            hovertemplate=(
                "Team=%{fullData.name}<br>Best Lap (s)=%{x:.3f}<br>"
                "Median Lap (s)=%{y:.3f}<br>Laps=%{marker.size}<br>"
                "Driver=%{customdata[0]}<br>Std=%{customdata[1]:.3f}<extra></extra>"
            ),
        ))
    theme(fig_bub, 520, "Driver Performance Matrix – Best Lap vs Race Pace (bubble = lap count)")
    fig_bub.update_layout(xaxis_title="Best Lap Time (s)", yaxis_title="Median Lap Time (s)")

    # ── Pace heatmap (Driver × Session) ───────────────────────
    heatmap_cards = []
    pivot = (v.groupby(["Driver_Short", "session_name"])["LapTime_s"]
              .median().unstack(fill_value=np.nan))
    if not pivot.empty:
        norm = pivot.copy()
        for col in norm.columns:
            lo, hi = norm[col].min(), norm[col].max()
            norm[col] = (norm[col] - lo) / (hi - lo) if hi > lo else 0.5
        ss  = [s.split("_")[0] for s in pivot.columns]
        avg = pivot.mean(axis=0); dvs = list(pivot.index)
        fp = make_subplots(rows=2, cols=1, row_heights=[0.08, 0.92],
                           vertical_spacing=0.02, shared_xaxes=True)
        fp.add_trace(go.Heatmap(z=[avg.values], x=ss, y=["Avg"], colorscale="RdYlGn_r",
            showscale=False,
            text=[avg.round(3).values], texttemplate="%{text}", textfont={"size": 10},
            hovertemplate="Session: %{x}<br>Avg: %{z:.3f} s<extra></extra>"), row=1, col=1)
        fp.add_trace(go.Heatmap(z=norm.values, x=ss, y=dvs, colorscale="RdYlGn_r",
            showscale=True,
            text=pivot.round(3).values, texttemplate="%{text}", textfont={"size": 9},
            customdata=pivot.values,
            hovertemplate="Driver: %{y}<br>Session: %{x}<br>Median: %{customdata:.3f} s<extra></extra>",
            colorbar=dict(title=dict(text="Norm", font=dict(color=TEXT_MAIN)),
                          tickfont=dict(color=TEXT_MAIN))), row=2, col=1)
        fp.update_layout(
            title="Pace Heatmap: Driver × Session (column-normalized, red=slower)",
            height=max(300, 80 + 26 * len(dvs)),
            paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
            font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
            margin=dict(l=80, r=100, t=60, b=40))
        heatmap_cards.append(card("Driver × Session Pace Heatmap",
                                  dcc.Graph(figure=fp, config=GFX),
                                  info=("Data: median valid lap time per driver in "
                                        "each session, normalised within each "
                                        "session column (0 = fastest, red = slowest); "
                                        "the top 'Avg' strip shows each session's raw "
                                        "average. Why: lets you compare relative pace "
                                        "across sessions even when absolute lap times "
                                        "differ (fuel, track evolution, conditions).")))

    # ── Cornering Speed heatmap (Driver × speed-band region) ──
    # No TrackRegion column exists in the telemetry pipeline, so derive
    # one here: keep only off-throttle / braking samples (i.e. the car is
    # in a corner phase) and bucket them by speed.
    if (ft is not None and not ft.empty
            and "Speed" in ft.columns and "Driver_Short" in ft.columns):
        tv = ft[ft["Speed"].notna()].copy()
        corner_mask = pd.Series(True, index=tv.index)
        if "Throttle" in tv.columns:
            corner_mask &= tv["Throttle"].fillna(100) < 50
        elif "Brake" in tv.columns:
            corner_mask &= tv["Brake"].fillna(False).astype(bool)
        tv = tv[corner_mask]

        region_order = ["Slow Corners (<130 km/h)",
                        "Medium Corners (130–200)",
                        "Fast Corners (>200)"]
        def _bucket(s):
            if s < 130: return region_order[0]
            if s < 200: return region_order[1]
            return region_order[2]
        tv["TrackRegion"] = tv["Speed"].apply(_bucket)

        if not tv.empty:
            cp = (tv.groupby(["Driver_Short", "TrackRegion"])["Speed"]
                    .mean().unstack(fill_value=np.nan))
            present = [r for r in region_order if r in cp.columns]
            cp = cp.sort_index().reindex(present, axis=1)
            cn = cp.copy()
            for col in cn.columns:
                lo, hi = cn[col].min(), cn[col].max()
                cn[col] = (cn[col] - lo) / (hi - lo) if hi > lo else 0.5
            ravg = cp.mean(axis=0); dc = list(cp.index); rg = list(cp.columns)
            fc = make_subplots(rows=2, cols=1, row_heights=[0.1, 0.9],
                               vertical_spacing=0.03, shared_xaxes=True)
            fc.add_trace(go.Heatmap(z=[ravg.values], x=rg, y=["Avg"], colorscale="RdYlGn",
                showscale=False,
                text=[np.round(ravg.values, 1)], texttemplate="%{text}", textfont={"size": 10},
                hovertemplate="Region: %{x}<br>Avg Speed: %{z:.1f} km/h<extra></extra>"),
                row=1, col=1)
            fc.add_trace(go.Heatmap(z=cn.values, x=rg, y=dc, colorscale="RdYlGn",
                showscale=False,
                text=np.round(cp.values, 1), texttemplate="%{text}", textfont={"size": 9},
                customdata=cp.values,
                hovertemplate="Driver: %{y}<br>Region: %{x}<br>Avg Speed: %{customdata:.1f} km/h<extra></extra>"),
                row=2, col=1)
            fc.update_layout(
                title="Cornering Speed by Track Region<br><sup>Columns normalized for comparison</sup>",
                height=max(900, 30 * len(dc) + 200),
                paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
                margin=dict(l=80, r=40, t=70, b=50))
            fc.update_yaxes(title_text="Driver", row=2, col=1,
                            gridcolor=GRID_CLR, zeroline=False)
            fc.update_xaxes(title_text="Track Region", row=2, col=1,
                            gridcolor=GRID_CLR, zeroline=False)
            heatmap_cards.append(card("Cornering Speed by Track Region",
                                      dcc.Graph(figure=fc, config=GFX),
                                      info=("Data: telemetry speed samples taken only "
                                            "while the car is in a corner phase "
                                            "(throttle <50% or braking), averaged per "
                                            "driver and bucketed into slow (<130 km/h), "
                                            "medium (130–200) and fast (>200) corners; "
                                            "columns normalised for comparison. Why: "
                                            "reveals where each driver carries speed — "
                                            "low-speed traction vs high-speed commitment.")))

    return html.Div([
        dbc.Row([kpi("BEST LAP",best,ACCENT), kpi("VALID LAPS",f"{len(v):,}","#00D2BE"),
                 kpi("DRIVERS",str(fl["Driver_Short"].nunique()),"#FF8700"),
                 kpi("SESSIONS",str(fl["session_name"].nunique()),"#FFC0CB")]),
        _driver_standings_widget(fl),
        dbc.Row([dbc.Col(card("Lap Time Distribution",dcc.Graph(figure=fig_vio,config=GFX),
                              info=("Data: every valid lap per driver, drawn as a "
                                    "horizontal violin coloured by team. Why: shows "
                                    "not just how fast a driver is but how consistent — "
                                    "a tight violin means repeatable pace, a wide or "
                                    "skewed one means scattered laps (traffic, errors, "
                                    "mixed fuel/tyre runs).")),md=8),
                 dbc.Col(card("Compound Mix",dcc.Graph(figure=fig_pie,config=GFX),
                              info=("Data: share of laps run on each tyre compound "
                                    "across the current filter. Why: context for the "
                                    "pace figures — a field that ran mostly softs is "
                                    "not directly comparable to one on hards.")),md=4)]),
        card("Team Performance Overview",tbl),
        card("Driver Performance Matrix",dcc.Graph(figure=fig_bub,config=GFX),
             info=("Data: each driver plotted by best lap (x) vs median lap (y); "
                   "bubble size = number of valid laps. Why: separates one-lap "
                   "qualifying pace from sustained race pace — bottom-left is fast "
                   "over both, and a big gap between a driver's x and y hints at "
                   "tyre management or traffic issues.")),
        *heatmap_cards,
    ])

# ══════════════════════════════════════════════════════════════
# TAB 2 – TEAM ANALYSIS  (reworked)
# ══════════════════════════════════════════════════════════════
def tab_teams(fl, fs):
    try:
        return _tab_teams_inner2(fl, fs)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        return html.Div([
            dbc.Alert([html.B("Team Analysis – error: "), str(exc)],
                      color="danger", style={"fontSize": "0.82rem"}),
            html.Pre(tb, style={
                "color": TEXT_DIM, "fontSize": "0.7rem",
                "background": "#09091A", "padding": "12px",
                "borderRadius": "6px", "overflowX": "auto",
            }),
        ])


def _tab_teams_inner2(fl, fs):
    # ── Session detection ─────────────────────────────────────
    sess_names = fl["session_name"].unique().tolist()
    race_sess  = [s for s in sess_names
                  if (s.startswith("Race") or s.startswith("Sprint"))
                  and "Qualifying" not in s and "Shootout" not in s]
    quali_sess = [s for s in sess_names
                  if "Qualifying" in s or "Shootout" in s]
    has_race   = bool(race_sess)
    has_quali  = bool(quali_sess)

    v = fl[fl["ValidLap"]].copy()
    if v.empty:
        return html.P("No valid laps in current filter.", style={"color": TEXT_DIM})

    _pert   = fl["Perturbed_Lap"] if "Perturbed_Lap" in fl.columns else pd.Series(False, index=fl.index)
    v_clean = fl[fl["ValidLap"] & ~_pert].copy()

    # ── Build team → [driver1, driver2] mapping ───────────────
    pairs: dict = {}
    for team, grp in v.groupby("Team"):
        if str(team) in ("Unknown", "", "nan"):
            continue
        drvs = sorted(grp["Driver_Short"].dropna().unique().tolist())
        if drvs:
            pairs[team] = drvs[:2]

    if not pairs:
        return html.P("No teams found in current filter.", style={"color": TEXT_DIM})

    # Default team ordering = current championship standing (leader first). Charts
    # that rank by their own metric (% gap bars) re-sort and are unaffected; this
    # drives the order of the per-session laps bars and any team-categorical view.
    teams_all = _order_teams_by_champ(pairs.keys())

    # ── Generic helpers ───────────────────────────────────────
    def _drv_val(pool, driver, agg_fn):
        sub = pool[pool["Driver_Short"] == driver]
        if sub.empty:
            return np.nan
        try:
            r = agg_fn(sub)
            return float(r) if (r is not None and pd.notna(r)) else np.nan
        except Exception:
            return np.nan

    def _best_of(va, vb, lower_is_better=True):
        vals = [x for x in [va, vb] if pd.notna(x) and np.isfinite(x)]
        if not vals:
            return np.nan
        return min(vals) if lower_is_better else max(vals)

    def _avg_of(va, vb):
        vals = [x for x in [va, vb] if pd.notna(x) and np.isfinite(x)]
        return float(np.mean(vals)) if vals else np.nan

    def _team_dicts(pool, agg_fn, lower_is_better=True):
        """Return (best_d, avg_d): team → aggregated float."""
        best_d, avg_d = {}, {}
        for team in teams_all:
            drvs = pairs[team]
            va = _drv_val(pool, drvs[0], agg_fn)
            vb = _drv_val(pool, drvs[1], agg_fn) if len(drvs) > 1 else np.nan
            best_d[team] = _best_of(va, vb, lower_is_better)
            avg_d[team]  = _avg_of(va, vb)
        return best_d, avg_d

    # ── % gap to leader helper ────────────────────────────────
    def _pct_gap(value, leader, lower_is_better):
        """Return % gap from leader. Leader = 0%. Others = positive %."""
        if not np.isfinite(leader) or leader == 0:
            return float("nan")
        if lower_is_better:
            return (value - leader) / abs(leader) * 100.0
        else:
            return (leader - value) / abs(leader) * 100.0

    # ── Horizontal bar chart – % gap to leader ────────────────
    def _hbar(data_d, title, fmt_fn=None, lower_is_better=True, xlabel="", pct_gap=True):
        items = [(t, vv) for t, vv in data_d.items() if pd.notna(vv) and np.isfinite(vv)]
        if not items:
            return go.Figure()
        items.sort(key=lambda x: x[1], reverse=not lower_is_better)
        fmt    = fmt_fn or (lambda v: f"{v:.3f}")
        leader = items[0][1]

        if pct_gap and abs(leader) > 1e-9:
            gaps   = [_pct_gap(v, leader, lower_is_better) for _, v in items]
            x_vals = gaps
            # bar text: original value for leader, "value (+gap%)" for others
            bar_text = [
                fmt(v) if i == 0 else f"{fmt(v)}  +{g:.2f}%"
                for i, ((_, v), g) in enumerate(zip(items, gaps))
            ]
            x_title = "% gap to leader  (0 = best)"
        else:
            x_vals  = [v for _, v in items]
            bar_text = [fmt(v) for _, v in items]
            x_title = xlabel or title

        ts     = [i[0] for i in items]
        colors = [TEAM_COLORS.get(t, "#808080") for t in ts]
        fig = go.Figure(go.Bar(
            x=x_vals, y=ts, orientation="h",
            marker_color=colors,
            text=bar_text,
            textposition="outside",
            textfont=dict(size=9, color=TEXT_MAIN),
            hovertemplate="%{y}: %{text}<extra></extra>",
        ))
        h = max(200, len(items) * 44 + 90)
        theme(fig, h, title)
        fig.update_layout(
            xaxis_title=x_title,
            showlegend=False,
            margin=dict(l=140, r=140, t=50, b=40),
        )
        fig.update_xaxes(rangemode="tozero")
        fig.update_yaxes(autorange="reversed")
        return fig

    # ── Grouped compound bar – % gap per compound ─────────────
    def _compound_bars(compound_dicts, title, fmt_fn=None, lower_is_better=True):
        """compound_dicts: {compound: {team: value}}
        Each compound normalised independently to its own leader (0%)."""
        # Sort order by best overall value across compounds
        best_overall: dict = {}
        for cmp, d in compound_dicts.items():
            for t, vv in d.items():
                if pd.notna(vv) and np.isfinite(vv):
                    if t not in best_overall:
                        best_overall[t] = vv
                    else:
                        best_overall[t] = (
                            min(vv, best_overall[t]) if lower_is_better
                            else max(vv, best_overall[t])
                        )
        if not best_overall:
            return go.Figure()
        team_order = sorted(best_overall.keys(),
                            key=lambda t: best_overall[t],
                            reverse=not lower_is_better)
        fmt = fmt_fn or (lambda v: f"{v:.3f}")
        fig = go.Figure()
        for cmp, d in compound_dicts.items():
            raw_items = [(t, d[t]) for t in team_order
                         if pd.notna(d.get(t, np.nan)) and np.isfinite(d.get(t, np.nan))]
            if not raw_items:
                continue
            cmp_leader = min(v for _, v in raw_items) if lower_is_better else max(v for _, v in raw_items)
            y_teams = [t for t, _ in raw_items]
            gaps    = [_pct_gap(v, cmp_leader, lower_is_better) for _, v in raw_items]
            bar_text = [
                fmt(v) if i == 0 else f"{fmt(v)}  +{g:.2f}%"
                for i, ((_, v), g) in enumerate(zip(raw_items, gaps))
            ]
            fig.add_trace(go.Bar(
                x=gaps, y=y_teams, name=cmp,
                orientation="h",
                marker_color=COMPOUND_COLORS.get(cmp, "#808080"),
                text=bar_text,
                textposition="outside",
                textfont=dict(size=8, color=TEXT_MAIN),
                hovertemplate=f"<b>{{{{y}}}}</b> – {cmp}: %{{text}}<extra></extra>",
            ))
        h = max(220, len(team_order) * 58 + 130)
        theme(fig, h, title)
        fig.update_layout(
            barmode="group", showlegend=True,
            xaxis_title="% gap to compound leader  (0 = best per compound)",
            margin=dict(l=140, r=140, t=50, b=40),
            legend=dict(orientation="h", x=0, y=1.14, bgcolor="rgba(0,0,0,0)"),
        )
        fig.update_xaxes(rangemode="tozero")
        fig.update_yaxes(autorange="reversed", categoryorder="array",
                         categoryarray=list(reversed(team_order)))
        return fig

    # ── Laps per session grouped bar – % gap per session ──────
    def _session_laps_bar(laps_per_sess, title, fmt_fn=None):
        fig = go.Figure()
        for sess, d in laps_per_sess.items():
            items = [(t, vv) for t, vv in d.items() if pd.notna(vv) and vv > 0]
            if not items:
                continue
            # Higher laps = better; leader is the team with most laps this session
            leader_laps = max(v for _, v in items)
            ts = [i[0] for i in items]
            vs = [i[1] for i in items]
            gaps = [_pct_gap(v, leader_laps, lower_is_better=False) for v in vs]
            bar_text = [
                (fmt_fn(v) if fmt_fn else str(int(v))) if g == 0.0
                else ((fmt_fn(v) if fmt_fn else str(int(v))) + f"  +{g:.1f}%")
                for v, g in zip(vs, gaps)
            ]
            fig.add_trace(go.Bar(
                y=ts, x=gaps, name=sess.split("_")[0], orientation="h",
                text=bar_text,
                textposition="outside",
                textfont=dict(size=8, color=TEXT_MAIN),
                hovertemplate=f"<b>{{{{y}}}}</b> – {sess.split('_')[0]}: %{{text}}<extra></extra>",
            ))
        h = max(220, len(teams_all) * 50 + 130)
        theme(fig, h, title)
        fig.update_layout(
            barmode="group", showlegend=True,
            xaxis_title="% gap to session leader  (0 = most laps per session)",
            margin=dict(l=140, r=140, t=50, b=40),
            legend=dict(orientation="h", x=0, y=1.14, bgcolor="rgba(0,0,0,0)"),
        )
        fig.update_xaxes(rangemode="tozero")
        fig.update_yaxes(autorange="reversed")
        return fig

    # ═════════════════════════════════════════════════════════
    # COMPUTE ALL METRICS
    # ═════════════════════════════════════════════════════════

    # ── M1: Race pace per compound (best stint, all sessions) ─
    def _best_stint_for_driver(driver, compound):
        if fs is not None and not fs.empty and "Stint_Rank_Across_Sessions" in fs.columns:
            best_s = fs[
                (fs["Driver_Short"] == driver) &
                (fs["Compound"] == compound) &
                fs["Valid_Stint"] &
                (fs["Stint_Rank_Across_Sessions"] == 1)
            ]
            if not best_s.empty and "Stint_FuelCorr" in best_s.columns:
                v_ = pd.to_numeric(best_s["Stint_FuelCorr"], errors="coerce").dropna()
                if not v_.empty:
                    return float(v_.iloc[0])
        # Fallback: trimmed median of fuel-corrected (or raw) laps
        col = "LapTime_FuelCorrected" if "LapTime_FuelCorrected" in v_clean.columns else "LapTime_s"
        sub = v_clean[(v_clean["Driver_Short"] == driver) & (v_clean["Compound"] == compound)]
        if sub.empty:
            return np.nan
        t = sub[col].dropna()
        if t.empty:
            return np.nan
        lo, hi = t.quantile(0.10), t.quantile(0.90)
        trimmed = t[t.between(lo, hi)]
        return float(trimmed.median() if not trimmed.empty else t.median())

    race_pace_best_by_cmp: dict = {}
    race_pace_avg_by_cmp:  dict = {}
    for cmp in COMPOUNDS:
        bd, ad = {}, {}
        for team in teams_all:
            drvs = pairs[team]
            va = _best_stint_for_driver(drvs[0], cmp)
            vb = _best_stint_for_driver(drvs[1], cmp) if len(drvs) > 1 else np.nan
            b  = _best_of(va, vb, lower_is_better=True)
            a  = _avg_of(va, vb)
            if pd.notna(b):
                bd[team] = b
            if pd.notna(a):
                ad[team] = a
        if bd:
            race_pace_best_by_cmp[cmp] = bd
        if ad:
            race_pace_avg_by_cmp[cmp]  = ad

    # ── M2: Best lap overall (all sessions, all compounds) ────
    best_lap_best, best_lap_avg = _team_dicts(v, lambda s: s["LapTime_s"].min())

    # ── M3: NB laps – total ───────────────────────────────────
    laps_tot_best, laps_tot_avg = _team_dicts(
        v, lambda s: float(len(s)), lower_is_better=False)

    # ── M3b: NB laps – per session ────────────────────────────
    laps_per_sess_best: dict = {}
    laps_per_sess_avg:  dict = {}
    for sess in sorted(sess_names):
        pool = v[v["session_name"] == sess]
        if pool.empty:
            continue
        b, a = _team_dicts(pool, lambda s: float(len(s)), lower_is_better=False)
        laps_per_sess_best[sess] = b
        laps_per_sess_avg[sess]  = a

    # ── M4: Pit stop time (race/sprint only) ──────────────────
    pit_best: dict = {}
    pit_avg:  dict = {}
    if has_race and "PitIn" in fl.columns and "PitOut" in fl.columns:
        _race_laps = fl[fl["session_name"].isin(race_sess)].sort_values(
            ["session_name", "DriverNo", "LapNo"])
        _pit_rows: list = []
        for (sess, drv_no), grp in _race_laps.groupby(["session_name", "DriverNo"]):
            grp_s    = grp.sort_values("LapNo")
            in_laps  = grp_s[grp_s["InLap"]  & grp_s["PitIn"].notna()]
            out_laps = grp_s[grp_s["OutLap"] & grp_s["PitOut"].notna()]
            out_dict: dict = {}
            for _, orow in out_laps.iterrows():
                ln = int(orow["LapNo"])
                if ln not in out_dict:
                    out_dict[ln] = float(orow["PitOut"])
            for _, inrow in in_laps.iterrows():
                nxt = int(inrow["LapNo"]) + 1
                try:
                    pit_in_s = float(inrow["PitIn"])
                    if nxt in out_dict and np.isfinite(pit_in_s) and np.isfinite(out_dict[nxt]):
                        dur = out_dict[nxt] - pit_in_s
                        if 1.5 < dur < 65.0:
                            _pit_rows.append({
                                "Driver_Short": inrow["Driver_Short"],
                                "Team":         inrow["Team"],
                                "dur":          dur,
                            })
                except Exception:
                    pass
        if _pit_rows:
            _pit_df = pd.DataFrame(_pit_rows)
            pit_best, pit_avg = _team_dicts(
                _pit_df, lambda s: s["dur"].mean(), lower_is_better=True)

    # ── M5: Qualifying performance ────────────────────────────
    quali_best: dict = {}
    quali_avg:  dict = {}
    if has_quali:
        _ql = fl[fl["session_name"].isin(quali_sess)]
        q_cols = [c for c in ("Q3_s", "Q2_s", "Q1_s") if c in fl.columns]

        def _best_q_for(driver):
            sub = _ql[_ql["Driver_Short"] == driver]
            if sub.empty:
                return np.nan
            for qc in q_cols:
                v_ = pd.to_numeric(sub[qc], errors="coerce").dropna()
                if not v_.empty:
                    return float(v_.iloc[0])
            bl = sub[sub["ValidLap"]]["LapTime_s"].dropna()
            return float(bl.min()) if not bl.empty else np.nan

        for team in teams_all:
            drvs = pairs[team]
            va = _best_q_for(drvs[0])
            vb = _best_q_for(drvs[1]) if len(drvs) > 1 else np.nan
            b  = _best_of(va, vb, lower_is_better=True)
            a  = _avg_of(va, vb)
            if pd.notna(b):
                quali_best[team] = b
            if pd.notna(a):
                quali_avg[team]  = a

    # ── M6: Race pace perf (race/sprint sessions only) ────────
    race_pace_perf_best: dict = {}
    race_pace_perf_avg:  dict = {}
    if has_race:
        v_race = v_clean[v_clean["session_name"].isin(race_sess)]

        def _race_perf_for(driver):
            if fs is not None and not fs.empty:
                fs_race = fs[
                    fs["session_name"].isin(race_sess) &
                    (fs["Driver_Short"] == driver) &
                    fs["Valid_Stint"]
                ]
                if not fs_race.empty and "Stint_Rep_Lap" in fs_race.columns:
                    best = fs_race["Stint_Rep_Lap"].dropna().min()
                    if pd.notna(best):
                        return float(best)
            sub = v_race[v_race["Driver_Short"] == driver]
            if sub.empty:
                return np.nan
            col = "LapTime_FuelCorrected" if "LapTime_FuelCorrected" in sub.columns else "LapTime_s"
            t   = sub[col].dropna()
            if t.empty:
                return np.nan
            lo, hi = t.quantile(0.10), t.quantile(0.90)
            trimmed = t[t.between(lo, hi)]
            return float(trimmed.median() if not trimmed.empty else t.median())

        for team in teams_all:
            drvs = pairs[team]
            va = _race_perf_for(drvs[0])
            vb = _race_perf_for(drvs[1]) if len(drvs) > 1 else np.nan
            b  = _best_of(va, vb, lower_is_better=True)
            a  = _avg_of(va, vb)
            if pd.notna(b):
                race_pace_perf_best[team] = b
            if pd.notna(a):
                race_pace_perf_avg[team]  = a

    # ── M7: Positions gained / lost (race/sprint only) ────────
    pgain_best: dict = {}
    pgain_avg:  dict = {}
    if has_race and "Classified_Position" in fl.columns:
        _rr = fl[fl["session_name"].isin(race_sess)].copy()
        _rr["_fin"]  = pd.to_numeric(_rr["Classified_Position"], errors="coerce")
        _rr["_grid"] = (
            pd.to_numeric(_rr["Grid_Position"], errors="coerce")
            if "Grid_Position" in _rr.columns else np.nan
        )
        _rr["_gain"] = _rr["_grid"] - _rr["_fin"]
        _rr_drv = (
            _rr.groupby(["session_name", "Driver_Short"])
            .agg(_gain=("_gain", "first"))
            .reset_index()
            .groupby("Driver_Short")["_gain"]
            .sum()
            .reset_index()
        )
        _drv_team_map = (
            fl[["Driver_Short", "Team"]].drop_duplicates("Driver_Short")
            .set_index("Driver_Short")["Team"].to_dict()
        )
        _rr_drv["Team"] = _rr_drv["Driver_Short"].map(_drv_team_map)

        for team in teams_all:
            drvs = pairs[team]
            sub_a = _rr_drv[_rr_drv["Driver_Short"] == drvs[0]]
            sub_b = (_rr_drv[_rr_drv["Driver_Short"] == drvs[1]]
                     if len(drvs) > 1 else pd.DataFrame())
            va = float(sub_a["_gain"].iloc[0]) if not sub_a.empty else np.nan
            vb = float(sub_b["_gain"].iloc[0]) if not sub_b.empty else np.nan
            b  = _best_of(va, vb, lower_is_better=False)   # higher gain = better
            a  = _avg_of(va, vb)
            if pd.notna(b):
                pgain_best[team] = b
            if pd.notna(a):
                pgain_avg[team]  = a

    # ═════════════════════════════════════════════════════════
    # CONSTRUCTOR CHAMPIONSHIP STANDINGS WIDGET
    # Data-driven & season-aware. Standings come from the historical
    # constructor table (HIST_STANDINGS — built by fetch_historical_results.py
    # from race points), looked up for the season + round of the meeting loaded
    # in the Data tab:
    #   "after"  = cumulative standings through that round,
    #   "before" = standings through the previous round,
    #   delta    = rank change caused by this event.
    # It updates automatically as new rounds are fetched or another season loads.
    # Falls back to points scored in the loaded race laps if the meeting isn't in
    # the historical archive yet (e.g. fresh live data).
    # ═════════════════════════════════════════════════════════
    _champ_season, _champ_round, _champ_event = _loaded_meeting_season_round()

    _after_pts_src  = _standings_after_round(_champ_season, _champ_round)
    _prev_rnd       = _prev_round(_champ_season, _champ_round)
    _before_pts_src = _standings_after_round(_champ_season, _prev_rnd) if _prev_rnd else {}
    _round_pts_src  = _round_points_for(_champ_season, _champ_round)

    # Fallback: meeting not in the historical archive → derive "this event" points
    # from the loaded race laps so the widget still shows something useful.
    if not _after_pts_src and has_race and "Race_Points" in fl.columns:
        _pts_raw = (
            fl[fl["session_name"].isin(race_sess)]
            .groupby(["session_name", "Driver_Short", "Team"])["Race_Points"]
            .first().reset_index()
        )
        _pts_raw["Race_Points"] = pd.to_numeric(_pts_raw["Race_Points"], errors="coerce").fillna(0)
        _round_pts_src  = _pts_raw.groupby("Team")["Race_Points"].sum().to_dict()
        _after_pts_src  = dict(_round_pts_src)
        _before_pts_src = {}

    _session_team_pts = _round_pts_src

    _all_champ_teams = sorted(
        set(_after_pts_src) | set(_before_pts_src) | set(_session_team_pts)
    )

    def _rank_by_pts(pts_dict):
        """Dense rank (1 = most pts). Ties get the same rank."""
        ordered = sorted(pts_dict.items(), key=lambda x: -x[1])
        rank, prev_pts, prev_rank = {}, None, 0
        for i, (t, p) in enumerate(ordered):
            if p != prev_pts:
                prev_rank = i + 1
            rank[t] = prev_rank
            prev_pts = p
        return rank

    _after_pts  = {t: _after_pts_src.get(t, 0) for t in _all_champ_teams}
    # Prefer the real previous-round standings; otherwise reconstruct as
    # after − this-event points (keeps round-1 / fallback behaviour identical).
    _before_pts = {
        t: (_before_pts_src.get(t, 0) if _before_pts_src
            else max(0, _after_pts[t] - _session_team_pts.get(t, 0)))
        for t in _all_champ_teams
    }

    _rank_after  = _rank_by_pts(_after_pts)
    _rank_before = _rank_by_pts(_before_pts)

    _all_before_zero = all(v == 0 for v in _before_pts.values())

    # Rows sorted by current rank
    _champ_rows_sorted = sorted(
        _all_champ_teams,
        key=lambda t: (_rank_after.get(t, 99), -_after_pts.get(t, 0)),
    )

    _champ_from_archive = _champ_round is not None
    _season_lbl = str(_champ_season) if _champ_season else "current"
    if _champ_from_archive and _champ_event:
        _subtitle_txt = f"  ·  standings after {_champ_event} (round {_champ_round})"
    elif _champ_from_archive:
        _subtitle_txt = f"  ·  standings after round {_champ_round}"
    else:
        _subtitle_txt = "  ·  points from loaded race sessions (not yet in archive)"

    _delta_note = (
        "↕ rank change caused by this event  ·  —  = season opener / no prior round"
        if _all_before_zero else
        "↕ constructor rank change vs the standings before this event"
    )

    _champ_info = (
        "Data: cumulative constructor points for the loaded season, summed from "
        "every race's (and sprint's) points in the historical archive "
        "(constructor_standings_all.parquet, built by fetch_historical_results.py). "
        "'After' = standings through the loaded meeting's round; 'before' = the "
        "previous round; the arrow is the rank change from this event. Re-run the "
        "fetch to pull in newly completed rounds, or load another season to see its "
        "table."
    )

    _champ_body = (
        _standings_leaderboard_body(
            _champ_rows_sorted, _rank_after, _rank_before, _after_pts, _session_team_pts,
            color_of=lambda t: TEAM_COLORS.get(t, "#808080"),
            primary_of=lambda t: t,
            secondary_of=None,
            entity_header="CONSTRUCTOR",
            all_before_zero=_all_before_zero, delta_note=_delta_note,
        )
        if _all_champ_teams else
        html.P(
            "No constructor standings available for the loaded season. "
            "Run fetch_historical_results.py to populate the archive.",
            style={"color": TEXT_DIM, "fontStyle": "italic", "fontSize": "0.8rem"},
        )
    )

    champ_widget = card(
        html.Span([
            "Constructor Championship  ",
            html.Span(f"{_season_lbl} season", style={"color": ACCENT, "fontWeight": "800"}),
            html.Span(_subtitle_txt,
                      style={"color": TEXT_DIM, "fontWeight": "400",
                             "fontSize": "0.72rem", "marginLeft": "6px"}),
        ]),
        _champ_body,
        info=_champ_info,
    )

    # ─────────────────────────────────────────────────────────

    # ═════════════════════════════════════════════════════════
    # COLUMN HEADER HELPER
    # ═════════════════════════════════════════════════════════
    def _col_header(title, subtitle):
        return html.Div([
            html.H5(
                title,
                style={"color": ACCENT, "fontWeight": "800", "letterSpacing": "2px",
                       "marginBottom": "2px", "fontSize": "0.92rem", "textAlign": "center"},
            ),
            html.P(subtitle, style={"color": TEXT_DIM, "fontSize": "0.70rem",
                                     "textAlign": "center", "marginBottom": "14px"}),
            html.Hr(style={"borderColor": GRID_CLR, "marginBottom": "12px"}),
        ])

    def _maybe_card(title, fig, info=None):
        """Only add the card if the figure has at least one trace."""
        if fig and fig.data:
            return [card(title, dcc.Graph(figure=fig, config=GFX), info=info)]
        return []

    # ═════════════════════════════════════════════════════════
    # LEFT COLUMN  – best of 2 drivers
    # ═════════════════════════════════════════════════════════
    left_cards = [_col_header(
        "BEST OF 2 DRIVERS",
        "each metric uses the strongest driver per team",
    )]

    # Race pace per compound (all sessions)
    if race_pace_best_by_cmp:
        left_cards += _maybe_card(
            "Race Pace – Best Stint per Compound (all sessions)",
            _compound_bars(race_pace_best_by_cmp, "Race Pace – Best Stint",
                           fmt_fn=format_lap_time, lower_is_better=True),
            info=("Data: each team's stronger driver, fuel-corrected pace of their "
                  "best valid stint on each compound (all sessions). Bars show the % "
                  "gap to the fastest team on that compound. Why: the cleanest read "
                  "on true race-run pace, separated by tyre."),
        )

    # Best lap overall
    left_cards += _maybe_card(
        "Best Lap Overall (all sessions)",
        _hbar(best_lap_best, "Best Lap Time", fmt_fn=format_lap_time,
              lower_is_better=True, xlabel="Lap Time (s)"),
        info=("Data: the single fastest valid lap set by either driver of each team, "
              "across all sessions; bars show % gap to the fastest team. Why: a raw "
              "measure of ultimate one-lap car+driver performance."),
    )

    # NB laps – total
    left_cards += _maybe_card(
        "Total Valid Laps",
        _hbar(laps_tot_best, "Total Valid Laps",
              fmt_fn=lambda v: str(int(v)), lower_is_better=False, xlabel="Laps"),
        info=("Data: total valid laps completed by the team's busier driver. Why: a "
              "sample-size / reliability indicator — more laps means the other "
              "metrics for that team rest on more evidence."),
    )

    # NB laps – per session
    if laps_per_sess_best:
        _f = _session_laps_bar(laps_per_sess_best, "Valid Laps per Session")
        if _f and _f.data:
            left_cards.append(card("Laps per Session",
                                   dcc.Graph(figure=_f, config=GFX),
                                   info=("Data: valid laps per team (busier driver) "
                                         "broken down by session, as % gap to the team "
                                         "with most laps that session. Why: shows "
                                         "running programmes — who maximised track time "
                                         "in each practice / qualifying / race.")))

    if has_race:
        left_cards += _maybe_card(
            "Pit Stop Duration",
            _hbar(pit_best, "Avg Pit Stop", fmt_fn=lambda v: f"{v:.2f}s",
                  lower_is_better=True, xlabel="Avg Pit Stop (s)"),
            info=("Data: average stationary pit time (PitOut − PitIn of matched "
                  "in/out laps, 1.5–65 s) for the team's faster-stopping driver, "
                  "race/sprint only. Why: pit-crew performance, isolated from "
                  "on-track pace."),
        )

    if has_quali:
        left_cards += _maybe_card(
            "Qualifying Performance",
            _hbar(quali_best, "Best Quali Lap", fmt_fn=format_lap_time,
                  lower_is_better=True, xlabel="Best Quali Lap (s)"),
            info=("Data: best qualifying time (Q3→Q2→Q1 cascade) of the team's "
                  "quicker driver; bars show % gap to pole pace. Why: low-fuel, "
                  "max-attack single-lap performance — the purest car+driver speed."),
        )

    if has_race:
        left_cards += _maybe_card(
            "Race Pace (race/sprint sessions only)",
            _hbar(race_pace_perf_best, "Race Pace", fmt_fn=format_lap_time,
                  lower_is_better=True, xlabel="Race Pace (s)"),
            info=("Data: best representative stint pace of the team's stronger driver "
                  "in race/sprint sessions only (fuel-corrected). Why: actual race-day "
                  "pace, which can differ markedly from one-lap qualifying speed."),
        )
        left_cards += _maybe_card(
            "Positions Gained / Lost (race/sprint)",
            _hbar(pgain_best, "Positions Gained",
                  fmt_fn=lambda v: f"+{int(v)}" if v > 0 else str(int(v)),
                  lower_is_better=False, xlabel="Pos Gained (+) / Lost (−)",
                  pct_gap=False),
            info=("Data: grid position minus classified finish (summed over "
                  "race/sprint sessions), best result of the two drivers. Positive = "
                  "moved up. Why: captures race-craft and strategy, not just raw pace."),
        )

    # ═════════════════════════════════════════════════════════
    # RIGHT COLUMN  – average of 2 drivers
    # ═════════════════════════════════════════════════════════
    right_cards = [_col_header(
        "AVERAGE OF 2 DRIVERS",
        "NaN falls back to available driver — never forced to 0",
    )]

    if race_pace_avg_by_cmp:
        right_cards += _maybe_card(
            "Race Pace – Avg Best Stint per Compound",
            _compound_bars(race_pace_avg_by_cmp, "Race Pace – Avg Stint",
                           fmt_fn=format_lap_time, lower_is_better=True),
            info=("Same data as the left-column race-pace chart, but averaging both "
                  "drivers' best stint per compound instead of taking the best one. "
                  "Why: rewards teams with two strong cars, not just one standout; a "
                  "missing driver falls back to the available one (never forced to 0)."),
        )

    right_cards += _maybe_card(
        "Average Best Lap (all sessions)",
        _hbar(best_lap_avg, "Avg Best Lap", fmt_fn=format_lap_time,
              lower_is_better=True, xlabel="Avg Best Lap (s)"),
        info=("Data: mean of the two drivers' best valid laps per team. Why: a "
              "two-car measure of single-lap speed — penalises line-ups that lean "
              "on one quick driver."),
    )

    right_cards += _maybe_card(
        "Avg Valid Laps per Driver",
        _hbar(laps_tot_avg, "Avg Valid Laps",
              fmt_fn=lambda v: f"{v:.1f}", lower_is_better=False,
              xlabel="Avg Laps per Driver"),
        info=("Data: average number of valid laps per driver in the team. Why: "
              "shows typical track time per car (reliability / programme), not just "
              "the busier driver's total."),
    )

    if laps_per_sess_avg:
        _f = _session_laps_bar(laps_per_sess_avg, "Avg Laps per Session",
                               fmt_fn=lambda v: f"{v:.1f}")
        if _f and _f.data:
            right_cards.append(card("Avg Laps per Session",
                                    dcc.Graph(figure=_f, config=GFX),
                                    info=("Data: average valid laps per driver, split "
                                          "by session, as % gap to the busiest team. "
                                          "Why: per-session running programme on a "
                                          "two-car basis.")))

    if has_race:
        right_cards += _maybe_card(
            "Avg Pit Stop Duration",
            _hbar(pit_avg, "Avg Pit Stop", fmt_fn=lambda v: f"{v:.2f}s",
                  lower_is_better=True, xlabel="Avg Pit Stop (s)"),
            info=("Data: average stationary pit time across both drivers' stops "
                  "(race/sprint, 1.5–65 s window). Why: overall pit-crew consistency, "
                  "not just the single best stop."),
        )

    if has_quali:
        right_cards += _maybe_card(
            "Avg Qualifying Performance",
            _hbar(quali_avg, "Avg Quali Lap", fmt_fn=format_lap_time,
                  lower_is_better=True, xlabel="Avg Quali Lap (s)"),
            info=("Data: mean of both drivers' best qualifying times (Q3→Q2→Q1). "
                  "Why: a two-car view of single-lap speed."),
        )

    if has_race:
        right_cards += _maybe_card(
            "Avg Race Pace (race/sprint sessions only)",
            _hbar(race_pace_perf_avg, "Avg Race Pace", fmt_fn=format_lap_time,
                  lower_is_better=True, xlabel="Avg Race Pace (s)"),
            info=("Data: mean of both drivers' best representative race/sprint stint "
                  "pace (fuel-corrected). Why: sustained race pace measured across the "
                  "whole line-up."),
        )
        right_cards += _maybe_card(
            "Avg Positions Gained / Lost (race/sprint)",
            _hbar(pgain_avg, "Avg Pos Gained",
                  fmt_fn=lambda v: f"+{v:.1f}" if v > 0 else f"{v:.1f}",
                  lower_is_better=False, xlabel="Avg Pos Gained (+) / Lost (−)",
                  pct_gap=False),
            info=("Data: average grid-to-finish positions gained across both drivers. "
                  "Positive = the team typically moved up. Why: team-wide race-craft "
                  "and strategy outcome."),
        )

    # ═════════════════════════════════════════════════════════
    # ASSEMBLE LAYOUT
    # ═════════════════════════════════════════════════════════
    return html.Div([
        champ_widget,
        html.Hr(style={"borderColor": GRID_CLR, "margin": "8px 0 16px 0"}),
        dbc.Row([
            dbc.Col(
                html.Div(left_cards),
                md=6,
                style={
                    "borderRight": f"2px solid {GRID_CLR}",
                    "paddingRight": "14px",
                },
            ),
            dbc.Col(
                html.Div(right_cards),
                md=6,
                style={"paddingLeft": "14px"},
            ),
        ], className="g-0"),
    ])

# ══════════════════════════════════════════════════════════════
# TAB 3 – LAP TIMES
# ══════════════════════════════════════════════════════════════
_LAPTEL_CHANNELS = ["Speed", "Throttle", "Brake", "GearNo"]
_LAPTEL_DASHES   = ["solid", "dash", "dot", "dashdot", "longdash"]


def _lap_telemetry(session, driver_short, lapno):
    """Telemetry samples belonging to one lap, with a lap-relative time column.

    Locates the lap in the global ``laps`` frame (by session / driver / lap
    number), reads its [LapStartTime, LapStartTime+LapTime_s] window, and slices
    the global ``telemetry`` frame to that driver+window. Returns
    ``(tel_sub_sorted_by_t_rel, lap_row)`` or ``(None, lap_row_or_None)``.
    """
    if telemetry is None or telemetry.empty:
        return None, None
    lp = laps[(laps["session_name"] == session)
              & (laps["Driver_Short"] == driver_short)
              & (laps["LapNo"] == lapno)]
    if lp.empty:
        return None, None
    row   = lp.iloc[0]
    dno   = str(row["DriverNo"]).strip()
    start = pd.to_numeric(row.get("LapStartTime"), errors="coerce")
    dur   = pd.to_numeric(row.get("LapTime_s"),    errors="coerce")
    if not (np.isfinite(start) and np.isfinite(dur)):
        return None, row
    tel = telemetry[
        (telemetry["session_name"] == session)
        & (telemetry["DriverNo"].astype(str).str.strip() == dno)
        & (telemetry["timestamp"] >= start)
        & (telemetry["timestamp"] <= start + dur)
    ].copy()
    if tel.empty:
        return None, row
    tel = tel.sort_values("timestamp")
    tel["t_rel"] = tel["timestamp"] - start
    # Distance from the start line (m), integrating speed (km/h→m/s) over time —
    # the same quantity FastF1's Telemetry.add_distance() produces.
    if "Speed" in tel.columns:
        spd = pd.to_numeric(tel["Speed"], errors="coerce").fillna(0).to_numpy() * (1000.0 / 3600.0)
        t   = pd.to_numeric(tel["t_rel"], errors="coerce").fillna(method="ffill").fillna(0).to_numpy()
        if len(t) > 1:
            dt   = np.diff(t)
            avg  = (spd[1:] + spd[:-1]) / 2.0
            tel["Distance"] = np.concatenate([[0.0], np.cumsum(avg * dt)])
        else:
            tel["Distance"] = 0.0
    return tel, row


def _best_lap_telemetry_frame(fl):
    """Concatenated telemetry of each driver's single best valid lap across all
    loaded sessions in *fl* (one best lap per driver). Tagged with Driver_Short
    and Team. Used by the Max-Speed and Gear-usage charts."""
    v = fl[fl["ValidLap"]].copy()
    v = v[pd.to_numeric(v["LapTime_s"], errors="coerce") > 0]
    if v.empty:
        return pd.DataFrame()
    idx   = v.groupby("Driver_Short")["LapTime_s"].idxmin()
    parts = []
    for _, row in v.loc[idx].iterrows():
        tel, _ = _lap_telemetry(row["session_name"], row["Driver_Short"], row["LapNo"])
        if tel is None or tel.empty:
            continue
        tel = tel.copy()
        tel["Driver_Short"] = row["Driver_Short"]
        tel["Team"]         = row["Team"]
        parts.append(tel)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


_CORNER_FRAC_CACHE: dict[tuple, pd.DataFrame] = {}


def _corner_fractions_from_geometry(line, corners) -> pd.DataFrame:
    """Each corner's fractional position along the lap (0=start line, 1=lap end),
    from the cached track-line + corner X/Y. Unit-independent, so it can be scaled
    by any lap's measured distance. Returns DataFrame[label, frac] sorted by frac."""
    if (line is None or corners is None or line.empty or corners.empty
            or not {"X", "Y"}.issubset(line.columns)
            or not {"X", "Y"}.issubset(corners.columns)):
        return pd.DataFrame()
    lx = line["X"].to_numpy(float); ly = line["Y"].to_numpy(float)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(lx), np.diff(ly)))])
    total = cum[-1]
    if not np.isfinite(total) or total <= 0:
        return pd.DataFrame()
    rows = []
    for _, c in corners.iterrows():
        i = int(np.argmin((lx - c["X"]) ** 2 + (ly - c["Y"]) ** 2))
        num = c.get("Number")
        letter = c.get("Letter")
        letter = "" if (letter is None or (isinstance(letter, float) and np.isnan(letter))) else str(letter).strip()
        try:
            label = f"{int(num)}{letter}"
        except (TypeError, ValueError):
            label = f"{num}{letter}"
        rows.append({"label": label, "frac": cum[i] / total})
    return pd.DataFrame(rows).sort_values("frac").reset_index(drop=True)


def _session_meeting_season(session_name) -> tuple[int | None, str | None]:
    """Recover (season, meeting) from a lap's session_name. session_name is built
    as f'{session}_{meeting}_{season}', so prefer an exact match against the loaded
    session info, then fall back to parsing."""
    for info in LOADED_SESSION_INFO:
        sn = f"{info.get('SESSION')}_{info.get('MEETING')}_{info.get('SEASON')}"
        if sn == session_name:
            try:
                return int(info.get("SEASON")), str(info.get("MEETING"))
            except (TypeError, ValueError):
                return None, str(info.get("MEETING"))
    toks = str(session_name).split("_")
    if len(toks) >= 3:
        try:
            return int(toks[-1]), "_".join(toks[1:-1])
        except ValueError:
            return None, "_".join(toks[1:-1])
    return None, None


def _corner_fractions_for(season, event) -> pd.DataFrame:
    """Corner fractional positions for a specific circuit. Uses the app's track-map
    cache and, if that circuit isn't cached yet, fetches it once via get_track_map
    (which then persists it). Result is memoised per (season, event); empty on
    failure so corner markers are simply omitted."""
    if not season or not event:
        return pd.DataFrame()
    key = (int(season), str(event))
    if key in _CORNER_FRAC_CACHE:
        return _CORNER_FRAC_CACHE[key]
    out = pd.DataFrame()
    for sid in ("Q", "R"):           # quali gives the cleanest lap; race as fallback
        try:
            tm = get_track_map(season, event, sid)
        except Exception as exc:
            logging.warning("corner markers: track map fetch failed for %s %s (%s): %s",
                            season, event, sid, exc)
            tm = None
        if tm and tm.get("corners") is not None and not tm["corners"].empty:
            out = _corner_fractions_from_geometry(tm.get("line"), tm["corners"])
            if not out.empty:
                break
    _CORNER_FRAC_CACHE[key] = out
    return out


def _prewarm_track_maps(session_info_list) -> None:
    """Fetch + cache the track map (corner geometry) for each loaded meeting in a
    daemon thread, so the Telemetry Channels corner markers are ready without a
    long blocking fetch the first time that circuit's laps are viewed. Safe to call
    repeatedly — get_track_map / the memo skip already-cached circuits."""
    if globals().get("get_track_map") is None:
        return
    seen: set[tuple] = set()
    targets = []
    for info in session_info_list:
        try:
            season = int(info.get("SEASON"))
        except (TypeError, ValueError):
            continue
        event = str(info.get("MEETING", "")).strip()
        if not event or (season, event) in seen:
            continue
        seen.add((season, event))
        targets.append((season, event))
    if not targets:
        return

    def _worker():
        for season, event in targets:
            try:
                _corner_fractions_for(season, event)
            except Exception:
                pass

    import threading
    threading.Thread(target=_worker, name="track-map-prewarm", daemon=True).start()


def _empty_channel_fig(msg):
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
                       showarrow=False, font=dict(size=13, color=TEXT_DIM))
    theme(fig, 360, "")
    fig.update_xaxes(visible=False); fig.update_yaxes(visible=False)
    return fig


def _laptel_channel_fig(lap_specs):
    """Overlay Speed/Throttle/Brake/Gear traces for each selected lap, aligned on
    lap-relative time so different laps (and drivers) line up. *lap_specs* is a
    list of (session, driver_short, lapno)."""
    if telemetry is None or telemetry.empty:
        return _empty_channel_fig("No telemetry data loaded.")
    channels = [c for c in _LAPTEL_CHANNELS if c in telemetry.columns]
    if not channels:
        return _empty_channel_fig("No telemetry channels available.")

    MAX_POINTS = 2000
    fig = make_subplots(rows=len(channels), cols=1, shared_xaxes=True,
                        vertical_spacing=0.04, subplot_titles=channels)
    any_trace = False
    lap_totals = []                       # measured lap distance (m) per plotted lap
    marker_session = None                 # session_name of the first plotted lap
    for i, (session, driver, lapno) in enumerate(lap_specs):
        tel, row = _lap_telemetry(session, driver, lapno)
        if tel is None or tel.empty:
            continue
        if marker_session is None:
            marker_session = session
        use_dist = "Distance" in tel.columns
        xcol = "Distance" if use_dist else "t_rel"
        if use_dist:
            lap_totals.append(float(tel["Distance"].iloc[-1]))
        clr   = TEAM_COLORS.get(row["Team"], "#808080") if row is not None else "#808080"
        dash  = _LAPTEL_DASHES[i % len(_LAPTEL_DASHES)]
        stride = max(1, len(tel) // MAX_POINTS)
        if stride > 1:
            tel = tel.iloc[::stride]
        label = f"{driver} · {str(session).split('_')[0]} (L{int(lapno)})"
        xunit = "m" if use_dist else "s"
        for r, ch in enumerate(channels, start=1):
            fig.add_trace(go.Scattergl(
                x=tel[xcol], y=tel[ch], mode="lines",
                name=label, legendgroup=label, showlegend=(r == 1),
                line=dict(color=clr, width=1.1, dash=dash),
                hovertemplate=f"<b>{label}</b><br>{ch}: %{{y}}<br>%{{x:.0f}} {xunit}<extra></extra>",
            ), row=r, col=1)
        any_trace = True

    if not any_trace:
        return _empty_channel_fig(
            "No telemetry found for the selected lap(s) — they may predate the "
            "loaded telemetry window.")

    # ── Corner markers (only meaningful on a distance x-axis) ──
    on_distance = bool(lap_totals)
    if on_distance and marker_session:
        season, event = _session_meeting_season(marker_session)
        corner_df = _corner_fractions_for(season, event)
        if not corner_df.empty:
            ref_total = float(np.median(lap_totals))
            line_kw = dict(color="rgba(150,150,150,0.45)", width=1, dash="dot")
            for _, cr in corner_df.iterrows():
                xx = float(cr["frac"]) * ref_total
                # label only on the top subplot; plain dotted lines below
                fig.add_vline(x=xx, row=1, col=1, layer="below", line=line_kw,
                              annotation_text=str(cr["label"]),
                              annotation_position="top",
                              annotation_font=dict(size=8, color=TEXT_DIM))
                for r in range(2, len(channels) + 1):
                    fig.add_vline(x=xx, row=r, col=1, layer="below", line=line_kw)

    for r, ch in enumerate(channels, start=1):
        fig.update_yaxes(title_text=ch, gridcolor=GRID_CLR, zeroline=False, row=r, col=1)
    fig.update_xaxes(
        title_text="Distance from start line (m)" if on_distance else "Time since lap start (s)",
        row=len(channels), col=1)
    fig.update_layout(
        height=max(150 * len(channels) + 60, 320),
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
        legend=dict(bgcolor="rgba(0,0,0,0)"), margin=dict(l=60, r=20, t=60, b=45))
    fig.update_xaxes(gridcolor=GRID_CLR, zeroline=False)
    return fig


# ── Corner Analysis ───────────────────────────────────────────────
# Segment a lap by corner (using the cached corner geometry) and extract,
# per corner, the braking point and the entry / apex / exit speeds. Built on
# the same integrated-Distance telemetry + corner fractions that drive the
# Telemetry Channels overlay, so it needs no extra data source.
_CORNER_ENTRY_CLR = "#4FC3F7"   # light blue  — speed at brake onset
_CORNER_APEX_CLR  = "#FF6E6E"   # red         — minimum (apex) speed
_CORNER_EXIT_CLR  = "#7CE38B"   # green       — speed back on full throttle


def _corner_metrics(tel) -> pd.DataFrame:
    """Per-corner braking & speed metrics for one lap's telemetry.

    *tel* is the frame returned by :func:`_lap_telemetry` (needs ``Distance``,
    ``Speed``; uses ``Brake``/``Throttle``/``GearNo`` when present). Corners are
    located from the cached circuit geometry via :func:`_corner_fractions_for`,
    scaled to this lap's measured length, and the lap is split into one zone per
    corner at the midpoints between consecutive corners.

    Returns DataFrame[label, frac, apex_dist, entry_speed, apex_speed,
    exit_speed, brake_dist, brake_point, min_gear] sorted by distance, or empty.
    """
    if tel is None or tel.empty or "Distance" not in tel.columns:
        return pd.DataFrame()
    season, event = _session_meeting_season(tel["session_name"].iloc[0]) \
        if "session_name" in tel.columns else (None, None)
    corner_df = _corner_fractions_for(season, event)
    if corner_df.empty:
        return pd.DataFrame()

    t = tel.sort_values("Distance").reset_index(drop=True)
    dist = pd.to_numeric(t["Distance"], errors="coerce").to_numpy()
    total = float(dist[-1]) if len(dist) else 0.0
    if not np.isfinite(total) or total <= 0:
        return pd.DataFrame()
    spd  = pd.to_numeric(t.get("Speed"), errors="coerce").to_numpy()
    brk  = (pd.to_numeric(t["Brake"], errors="coerce").fillna(0).to_numpy()
            if "Brake" in t.columns else None)
    thr  = (pd.to_numeric(t["Throttle"], errors="coerce").to_numpy()
            if "Throttle" in t.columns else None)
    gear = (pd.to_numeric(t["GearNo"], errors="coerce").to_numpy()
            if "GearNo" in t.columns else None)

    cd = corner_df.copy()
    cd["dist"] = cd["frac"].astype(float) * total
    cd = cd.sort_values("dist").reset_index(drop=True)
    centers = cd["dist"].to_numpy()
    n = len(centers)

    rows = []
    for i in range(n):
        lo = 0.0   if i == 0     else (centers[i - 1] + centers[i]) / 2.0
        hi = total if i == n - 1 else (centers[i] + centers[i + 1]) / 2.0
        idx = np.where((dist >= lo) & (dist <= hi))[0]
        if idx.size == 0 or np.all(np.isnan(spd[idx])):
            continue
        # Apex = slowest point in the zone.
        apex = idx[int(np.nanargmin(spd[idx]))]
        apex_speed, apex_dist = spd[apex], dist[apex]

        # Braking point: first sample on the approach (zone start → apex) where
        # the brake is applied. brake_dist = metres of braking before the apex.
        brake_dist = np.nan; brake_point = np.nan; entry_speed = np.nan
        if brk is not None:
            appr = idx[idx <= apex]
            on   = np.where(brk[appr] > 0.5)[0]
            if on.size:
                bp = appr[on[0]]
                brake_point = dist[bp]
                brake_dist  = apex_dist - brake_point
                entry_speed = spd[bp]
        if not np.isfinite(entry_speed):           # no brake trace → zone-start speed
            entry_speed = spd[idx[0]]

        # Exit = first point after the apex back on (near-)full throttle, else
        # the end of the zone.
        post = idx[idx >= apex]
        exit_speed = spd[post[-1]] if post.size else apex_speed
        if thr is not None and post.size:
            up = np.where(thr[post] >= 95)[0]
            if up.size:
                exit_speed = spd[post[up[0]]]

        min_gear = np.nan
        if gear is not None and np.isfinite(np.nanmin(gear[idx])):
            min_gear = int(np.nanmin(gear[idx]))

        rows.append({
            "label": cd["label"].iloc[i], "frac": float(cd["frac"].iloc[i]),
            "apex_dist": apex_dist, "entry_speed": entry_speed,
            "apex_speed": apex_speed, "exit_speed": exit_speed,
            "brake_dist": brake_dist, "brake_point": brake_point,
            "min_gear": min_gear,
        })
    return pd.DataFrame(rows)


def _corner_analysis(specs):
    """Build the Corner Analysis outputs for the selected lap(s).

    *specs* is a list of (session, driver_short, lapno). Returns
    ``(fig_speed, fig_brake, table_records, table_columns)``. When a single lap
    is selected the speed chart shows its full entry/apex/exit profile; with
    several laps it overlays each lap's apex speed for a direct comparison.
    """
    metrics = []   # (label_str, team, dataframe)
    for session, driver, lapno in specs:
        tel, row = _lap_telemetry(session, driver, lapno)
        if tel is None or tel.empty:
            continue
        cm = _corner_metrics(tel)
        if cm.empty:
            continue
        team  = row["Team"] if row is not None else None
        label = f"{driver} · {str(session).split('_')[0]} (L{int(lapno)})"
        metrics.append((label, team, cm))

    if not metrics:
        msg = ("No corner geometry available for the selected lap(s) — the "
               "circuit map may still be downloading, or the laps predate the "
               "loaded telemetry window.")
        return (_empty_channel_fig(msg), _empty_channel_fig(msg), [], [])

    # Master corner order (by track position) across every plotted lap.
    order = (pd.concat([m[2][["label", "frac"]] for m in metrics])
               .drop_duplicates("label").sort_values("frac")["label"].tolist())

    fig_speed = go.Figure()
    fig_brake = go.Figure()
    single = len(metrics) == 1

    for i, (label, team, cm) in enumerate(metrics):
        clr  = TEAM_COLORS.get(team, "#808080")
        dash = _LAPTEL_DASHES[i % len(_LAPTEL_DASHES)]
        cm   = cm.set_index("label").reindex(order)
        x    = order

        if single:
            for ycol, cclr, nm in (("entry_speed", _CORNER_ENTRY_CLR, "Entry"),
                                   ("apex_speed",  _CORNER_APEX_CLR,  "Apex"),
                                   ("exit_speed",  _CORNER_EXIT_CLR,  "Exit")):
                fig_speed.add_trace(go.Scatter(
                    x=x, y=cm[ycol], mode="lines+markers", name=nm,
                    line=dict(color=cclr, width=2),
                    marker=dict(size=6),
                    hovertemplate=f"<b>%{{x}}</b><br>{nm}: %{{y:.0f}} km/h<extra></extra>"))
        else:
            fig_speed.add_trace(go.Scatter(
                x=x, y=cm["apex_speed"], mode="lines+markers", name=label,
                line=dict(color=clr, width=2, dash=dash), marker=dict(size=6),
                hovertemplate=(f"<b>{label}</b><br>%{{x}}<br>"
                               "Apex: %{y:.0f} km/h<extra></extra>")))

        # Bars, not lines: flat-out corners have no braking point (NaN), and a
        # line would draw misleading segments across those gaps. A missing bar
        # reads cleanly as "no braking here".
        fig_brake.add_trace(go.Bar(
            x=x, y=cm["brake_dist"], name=label, marker_color=clr,
            marker_pattern_shape=["", "/", ".", "x", "-"][i % 5],
            hovertemplate=(f"<b>{label}</b><br>%{{x}}<br>"
                           "Braking starts %{y:.0f} m before apex<extra></extra>")))

    theme(fig_speed, 380,
          "Corner Entry / Apex / Exit Speed" if single else "Apex Speed by Corner")
    fig_speed.update_layout(xaxis_title="Corner", yaxis_title="Speed (km/h)",
                            xaxis=dict(type="category", categoryorder="array",
                                       categoryarray=order))
    theme(fig_brake, 380, "Braking Point by Corner")
    fig_brake.update_layout(barmode="group", xaxis_title="Corner",
                            yaxis_title="Braking distance before apex (m)",
                            xaxis=dict(type="category", categoryorder="array",
                                       categoryarray=order))

    # Detail table (one row per corner per lap).
    recs = []
    for label, _team, cm in metrics:
        for _, r in cm.iterrows():
            recs.append({
                "Lap": label, "Corner": r["label"],
                "Entry": round(r["entry_speed"]) if np.isfinite(r["entry_speed"]) else None,
                "Apex":  round(r["apex_speed"])  if np.isfinite(r["apex_speed"])  else None,
                "Exit":  round(r["exit_speed"])  if np.isfinite(r["exit_speed"])  else None,
                "Brake (m)": round(r["brake_dist"]) if np.isfinite(r["brake_dist"]) else None,
                "Min Gear": int(r["min_gear"]) if np.isfinite(r["min_gear"]) else None,
            })
    cols = [{"name": c, "id": c} for c in
            ["Lap", "Corner", "Entry", "Apex", "Exit", "Brake (m)", "Min Gear"]]
    return fig_speed, fig_brake, recs, cols


# ── Delta decomposition by track sector ───────────────────────────
# Cumulative time-delta vs distance between selected laps, relative to the
# fastest one, plus a per-timing-sector breakdown of where the time goes.
# Uses _lap_telemetry's integrated Distance + the lap's SectorNTime values;
# no extra data source.
_SECTOR_FILL = ("rgba(255,255,255,0.00)", "rgba(255,255,255,0.035)")


def _minisector_times(dist, trel, n=MINI_SECTORS):
    """Per-mini-sector traversal times for one lap.

    Splits the lap into *n* equal-distance segments (edges at fractions
    0, 1/n … 1 of the lap's measured length) and returns the time spent in each
    by interpolating lap-relative time at the segment edges. *dist* must be
    strictly increasing. Returns a float array of length *n* (NaN where the lap
    is too short), so different laps' mini-sectors line up fraction-for-fraction.
    """
    dist = np.asarray(dist, float); trel = np.asarray(trel, float)
    if dist.size < 2 or not np.isfinite(dist[-1]) or dist[-1] <= 0:
        return np.full(n, np.nan)
    edges = np.linspace(0.0, dist[-1], n + 1)
    t_at  = np.interp(edges, dist, trel)
    return np.diff(t_at)


def _lap_trace(session, driver, lapno):
    """One lap as monotonic (distance, lap-relative time) arrays for interpolation.

    Returns a dict {dist, trel, total, row, label, team, laptime} or None.
    Distance comes from _lap_telemetry (cumulative speed integral, so it is
    non-decreasing); duplicate-distance samples are dropped so the array is
    strictly increasing and safe to use as np.interp's xp.
    """
    tel, row = _lap_telemetry(session, driver, lapno)
    if tel is None or tel.empty or "Distance" not in tel.columns:
        return None
    t = tel.sort_values("Distance")
    dist = pd.to_numeric(t["Distance"], errors="coerce").to_numpy()
    trel = pd.to_numeric(t["t_rel"], errors="coerce").to_numpy()
    ok = np.isfinite(dist) & np.isfinite(trel)
    dist, trel = dist[ok], trel[ok]
    if dist.size < 3:
        return None
    keep = np.concatenate([[True], np.diff(dist) > 0])   # strictly increasing
    dist, trel = dist[keep], trel[keep]
    if dist.size < 3:
        return None
    return {
        "dist": dist, "trel": trel, "total": float(dist[-1]), "row": row,
        "label": f"{driver} · {str(session).split('_')[0]} (L{int(lapno)})",
        "team": row["Team"] if row is not None else None,
        "laptime": pd.to_numeric(row.get("LapTime_s"), errors="coerce") if row is not None else np.nan,
    }


def _delta_decomposition(specs):
    """Delta-vs-distance trace + per-mini-sector breakdown for the selected laps.

    The fastest selected lap is the reference (the zero line); every other lap
    is plotted as cumulative time gained/lost against it. Returns
    ``(fig_delta, fig_sector)``. Needs at least two resolvable laps.
    """
    traces = [tr for tr in (_lap_trace(*s) for s in specs) if tr is not None]
    if len(traces) < 2:
        msg = "Select at least two laps in the Best Lap Leaderboard to compare deltas."
        return _empty_channel_fig(msg), _empty_channel_fig(msg)

    ref = min(traces, key=lambda t: t["laptime"] if np.isfinite(t["laptime"]) else t["trel"][-1])
    grid_max = min(t["total"] for t in traces)
    grid = np.linspace(0.0, grid_max, 600)
    tref = np.interp(grid, ref["dist"], ref["trel"])

    n = MINI_SECTORS
    ms_edges   = np.linspace(0.0, grid_max, n + 1)
    ms_centers = (ms_edges[:-1] + ms_edges[1:]) / 2.0

    fig_delta = go.Figure()
    fig_delta.add_hline(y=0, line=dict(color=TEAM_COLORS.get(ref["team"], "#AAAAAA"),
                                       width=1.4, dash="solid"))

    ms_rows = []              # (lap_label, team, per-mini-sector Δ array)
    di = 0
    for tr in traces:
        if tr is ref:
            continue
        ti = np.interp(grid, tr["dist"], tr["trel"])
        delta = ti - tref
        clr  = TEAM_COLORS.get(tr["team"], "#808080")
        dash = _LAPTEL_DASHES[di % len(_LAPTEL_DASHES)]; di += 1
        fig_delta.add_trace(go.Scatter(
            x=grid, y=delta, mode="lines", name=tr["label"],
            line=dict(color=clr, width=1.8, dash=dash),
            hovertemplate=(f"<b>{tr['label']}</b><br>%{{x:.0f}} m<br>"
                           "Δ %{y:+.3f}s<extra></extra>")))
        # Per-mini-sector delta = change in cumulative delta across each segment.
        cum_at = np.interp(ms_edges, grid, delta)
        ms_rows.append((tr["label"], tr["team"], np.diff(cum_at)))

    # Faint alternating mini-sector bands tie the trace to the bars below.
    for k in range(n):
        if k % 2:
            fig_delta.add_vrect(x0=ms_edges[k], x1=ms_edges[k + 1], layer="below",
                                line_width=0, fillcolor=_SECTOR_FILL[1])

    # Corner markers (same source as the channel overlay).
    season, event = _session_meeting_season(ref["row"]["session_name"]) \
        if ref["row"] is not None and "session_name" in ref["row"] else (None, None)
    corner_df = _corner_fractions_for(season, event)
    if not corner_df.empty:
        for _, cr in corner_df.iterrows():
            fig_delta.add_vline(x=float(cr["frac"]) * grid_max, layer="below",
                                line=dict(color="rgba(150,150,150,0.35)", width=1, dash="dot"))

    theme(fig_delta, 450, f"Time Delta vs Distance  ·  reference: {ref['label']}")
    fig_delta.update_layout(
        margin=dict(l=70, r=20, t=95, b=50),
        title=dict(y=0.96, yanchor="top"),
        xaxis_title="Distance from start line (m)",
        yaxis_title="Δ to reference (s)  ·  ↑ slower",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                    font=dict(size=10)))

    # ── Per-mini-sector bar (shared distance axis with the trace) ──
    fig_sector = go.Figure()
    if ms_rows:
        bar_w = (grid_max / n) * (0.8 / max(1, len(ms_rows)))
        for j, (label, team, vals) in enumerate(ms_rows):
            fig_sector.add_trace(go.Bar(
                x=ms_centers, y=vals, name=label, width=bar_w,
                offset=(j - (len(ms_rows) - 1) / 2.0) * bar_w,
                marker_color=TEAM_COLORS.get(team, "#808080"),
                marker_pattern_shape=["", "/", ".", "x", "-"][j % 5],
                hovertemplate=(f"<b>{label}</b><br>%{{x:.0f}} m<br>"
                               "Δ %{y:+.3f}s in this mini-sector<extra></extra>")))
        theme(fig_sector, 340, f"Time Gained / Lost per Mini-Sector  ·  vs {ref['label']}")
        fig_sector.update_layout(
            barmode="overlay",
            margin=dict(l=70, r=20, t=95, b=45),
            title=dict(y=0.96, yanchor="top"),
            xaxis_title="Distance from start line (m)",
            yaxis_title="Δ to reference (s)  ·  ↑ slower",
            legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                        font=dict(size=10)))
        fig_sector.add_hline(y=0, line=dict(color=TEXT_DIM, width=1))
    else:
        fig_sector = _empty_channel_fig("Could not compute mini-sector deltas.")
    return fig_delta, fig_sector


# ── Racing line comparison ────────────────────────────────────────
# Now possible because the telemetry frame carries X/Y track position (merged
# from FastF1's position stream in data_loader._fetch_telemetry). Each selected
# lap's actual driven line is drawn in the circuit's reference frame.
def _racing_line_fig(specs):
    """Overlay the actual driven X/Y line of each selected lap, oriented with the
    circuit rotation and annotated with corner numbers. A single lap is coloured
    by speed; several laps are team-coloured so you can see where the lines
    diverge — different apex, wider or tighter entry, earlier turn-in."""
    if telemetry is None or telemetry.empty or not {"X", "Y"}.issubset(telemetry.columns):
        return _empty_channel_fig(
            "No position (X/Y) telemetry loaded — re-fetch sessions to enable racing lines.")

    lines, marker_session = [], None
    for session, driver, lapno in specs:
        tel, row = _lap_telemetry(session, driver, lapno)
        if tel is None or tel.empty or not {"X", "Y"}.issubset(tel.columns):
            continue
        t = tel.dropna(subset=["X", "Y"])
        if len(t) < 10:
            continue
        lines.append((session, driver, lapno, row, t))
        if marker_session is None:
            marker_session = session
    if not lines:
        return _empty_channel_fig("No position data found for the selected lap(s).")

    season, event = _session_meeting_season(marker_session)
    try:
        tm = get_track_map(season, event, "Q")
    except Exception:
        tm = None
    ang = (tm["rotation"] / 180.0 * np.pi) if tm else 0.0
    single = len(lines) == 1

    fig = go.Figure()
    for i, (session, driver, lapno, row, t) in enumerate(lines):
        X, Y = _rotate(t["X"].to_numpy(float), t["Y"].to_numpy(float), ang)
        label = f"{driver} · {str(session).split('_')[0]} (L{int(lapno)})"
        if single and "Speed" in t.columns:
            spd = pd.to_numeric(t["Speed"], errors="coerce").to_numpy()
            # Thin neutral underlay so the line reads continuously, speed dots on top.
            fig.add_trace(go.Scattergl(
                x=X, y=Y, mode="lines", showlegend=False, hoverinfo="skip",
                line=dict(color="rgba(160,160,160,0.35)", width=1)))
            fig.add_trace(go.Scattergl(
                x=X, y=Y, mode="markers", name=label,
                marker=dict(size=5, color=spd, colorscale="Turbo", showscale=True,
                            colorbar=dict(title=dict(text="km/h", font=dict(color=TEXT_MAIN)),
                                          tickfont=dict(color=TEXT_MAIN), thickness=12)),
                hovertemplate=f"<b>{label}</b><br>%{{marker.color:.0f}} km/h<extra></extra>"))
        else:
            clr  = TEAM_COLORS.get(row["Team"], "#808080") if row is not None else "#808080"
            dash = _LAPTEL_DASHES[i % len(_LAPTEL_DASHES)]
            fig.add_trace(go.Scattergl(
                x=X, y=Y, mode="lines", name=label,
                line=dict(color=clr, width=2.4, dash=dash),
                hovertemplate=f"<b>{label}</b><extra></extra>"))

    # Corner numbers from the cached circuit geometry (same coordinate frame).
    if tm and tm.get("corners") is not None and not tm["corners"].empty:
        c = tm["corners"]
        cx, cy = _rotate(c["X"].to_numpy(float), c["Y"].to_numpy(float), ang)
        clabels = []
        for _, cc in c.iterrows():
            num, letter = cc.get("Number"), cc.get("Letter")
            letter = "" if letter is None or (isinstance(letter, float) and np.isnan(letter)) else str(letter).strip()
            try:
                clabels.append(f"{int(num)}{letter}")
            except (TypeError, ValueError):
                clabels.append(f"{num}{letter}")
        fig.add_trace(go.Scatter(
            x=cx, y=cy, mode="text", text=clabels, showlegend=False, hoverinfo="skip",
            textfont=dict(size=9, color=TEXT_DIM)))

    ttl = ("Racing Line — coloured by speed" if single
           else "Racing Line Comparison — where the lines diverge")
    _track_map_layout(fig, ttl, height=560)
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left",
                                  x=0, bgcolor="rgba(0,0,0,0)", font=dict(size=10)))
    return fig


def tab_laps(fl, ft):
    sector_fig = _sector_heatmap(fl)

    bt=best_laps_table(fl)
    bt["Best Lap"]=bt["LapTime_s"].apply(format_lap_time)
    disp=bt[["session_name","Driver_Short","Team","Compound","Best Lap","LapTime_s","TyreAge","LapNo"]].rename(columns={
        "session_name":"Session","Driver_Short":"Driver","LapTime_s":"Lap Time (s)","TyreAge":"Tyre Age","LapNo":"Lap #"
    }).sort_values("Lap Time (s)").reset_index(drop=True)
    best_tbl=dash_table.DataTable(
        id="laptel-best-table",
        data=disp.to_dict("records"),
        columns=[{"name":c,"id":c} for c in disp.columns],
        row_selectable="multi",
        selected_rows=[0] if len(disp) else [],
        **TABLE_STYLE,
        style_data_conditional=[
            {"if":{"state":"selected"},
             "backgroundColor":ACCENT+"33","border":f"1px solid {ACCENT}"},
        ],
    )

    # ── Telemetry section ────────────────────────────────────────
    # Max-speed and gear use each driver's single best lap across all loaded
    # sessions; the channel overlay is driven by the leaderboard selection.
    blt = _best_lap_telemetry_frame(fl)

    fig_spd = go.Figure()
    fig_gear = go.Figure()
    if not blt.empty and "Speed" in blt.columns:
        sp=(blt.groupby(["Driver_Short","Team"])["Speed"]
              .quantile(SPEED_PERCENTILE/100.0).reset_index())
        sp.columns=["Driver_Short","Team","MaxSpeed"]
        sp=sp.sort_values("MaxSpeed",ascending=False)
        for _,row in sp.iterrows():
            fig_spd.add_trace(go.Bar(x=[row["Driver_Short"]],y=[row["MaxSpeed"]],
                name=row["Driver_Short"],showlegend=False,
                marker_color=TEAM_COLORS.get(row["Team"],"#808080"),
                hovertemplate=f"<b>{row['Driver_Short']}</b><br>{SPEED_PERCENTILE}th pct: %{{y:.1f}} km/h<extra></extra>"))
        lo=sp["MaxSpeed"].min(); hi=sp["MaxSpeed"].max(); m=(hi-lo)*0.3 if hi>lo else 1
        theme(fig_spd,380,f"Maximum Speed by Driver ({SPEED_PERCENTILE}th pct of best lap)")
        fig_spd.update_layout(xaxis_title="Driver",yaxis_title="Max Speed (km/h)",xaxis=dict(tickangle=0,gridcolor=GRID_CLR,zeroline=False))
        fig_spd.update_yaxes(range=[lo-m,hi+m/4])
    else:
        fig_spd=_empty_channel_fig("No best-lap telemetry available.")

    if not blt.empty and "GearNo" in blt.columns:
        drv_team=blt.dropna(subset=["Driver_Short"]).groupby("Driver_Short")["Team"].first().to_dict()
        gp=(blt.groupby(["Driver_Short","Team","GearNo"]).size().reset_index(name="cnt"))
        gp["total"]=gp.groupby("Driver_Short")["cnt"].transform("sum")
        gp["pct"]=gp["cnt"]/gp["total"]*100
        drv_ord=sorted(gp["Driver_Short"].dropna().unique().tolist())
        drv_colors=[TEAM_COLORS.get(drv_team.get(d,"x"),"#808080") for d in drv_ord]
        for gear in sorted(gp["GearNo"].dropna().unique()):
            sub=gp[gp["GearNo"]==gear].set_index("Driver_Short")
            fig_gear.add_trace(go.Bar(
                x=drv_ord,
                y=[sub.loc[d,"pct"] if d in sub.index else 0 for d in drv_ord],
                name=f"Gear {int(gear)}",
                marker_color=drv_colors,
                hovertemplate="Driver: %{x}<br>Gear "+str(int(gear))+": %{y:.1f}%<extra></extra>"))
        theme(fig_gear,420,"Gear Usage Distribution by Driver (best lap)")
        fig_gear.update_layout(barmode="stack",xaxis_title="Driver",yaxis_title="Time in Gear (%)")
    else:
        fig_gear=_empty_channel_fig("No best-lap telemetry available.")

    ch_title=html.Span([
        "Telemetry Channels (Speed / Throttle / Brake / Gear)",
        html.Span(
            "  ·  vs distance, with corner markers  ·  select laps in the Best Lap "
            "Leaderboard above to overlay them",
            style={"color":TEXT_DIM,"fontWeight":"400","fontSize":"0.72rem","marginLeft":"6px"},
        ),
    ])

    return html.Div([
        card(f"Mini-Sector Dominance — best lap split into {MINI_SECTORS} segments, "
             "% gap to fastest",
             dcc.Graph(figure=sector_fig, config=GFX) if sector_fig.data else
             html.P("No telemetry available for the selected sessions.",
                    style={"color": TEXT_DIM}),
             info=(f"Data: each driver's single best lap is split into {MINI_SECTORS} "
                   "equal-distance mini-sectors (from the telemetry), and each cell is "
                   "coloured by that driver's % gap to the fastest driver through that "
                   "mini-sector (green = quickest there, red = slowest). Drivers are "
                   "ordered fastest lap on top. Why: far finer than the three timing "
                   "sectors — it shows exactly which stretches of track each driver "
                   "owns and where the lap time is really won or lost.")),
        card("Best Lap Leaderboard",
             html.Div([
                 html.P("Select one or more laps (checkbox at left) to drive the "
                        "Telemetry Channels overlay below.",
                        style={"color":TEXT_DIM,"fontSize":"0.74rem","marginBottom":"8px"}),
                 best_tbl,
             ])),
        dbc.Row([dbc.Col(card("Maximum Speed",dcc.Graph(figure=fig_spd,config=GFX),
                              info=(f"Data: the {SPEED_PERCENTILE}th-percentile speed "
                                    "from each driver's single best lap across all "
                                    "loaded sessions (a robust 'top speed' that ignores "
                                    "one-off GPS spikes), team-coloured. Why: a proxy "
                                    "for straight-line speed / power-unit and drag.")),md=6),
                 dbc.Col(card("Gear Usage",dcc.Graph(figure=fig_gear,config=GFX),
                              info=("Data: share of telemetry samples spent in each "
                                    "gear during each driver's best lap across all "
                                    "loaded sessions (stacked to 100%). Why: a "
                                    "fingerprint of how the lap is driven and of "
                                    "gearing/setup choices.")),md=6)]),
        card(ch_title, dcc.Graph(id="laptel-channels-graph",config=GFX),
             info=("Data: raw Speed, Throttle, Brake and Gear telemetry traces for the "
                   "lap(s) you select in the Best Lap Leaderboard, plotted against "
                   "distance from the start line (integrated from speed) so different "
                   "laps and drivers line up corner-for-corner. Dotted grey lines mark "
                   "the numbered corners (from the cached circuit map). Why: a direct "
                   "comparison of driving inputs — where each driver brakes, gets on "
                   "throttle and shifts through each corner.")),
        card(html.Span([
                "Corner Analysis (Braking Point · Entry / Apex / Exit Speed)",
                html.Span(
                    "  ·  per numbered corner  ·  select laps in the Best Lap "
                    "Leaderboard above to compare them",
                    style={"color":TEXT_DIM,"fontWeight":"400","fontSize":"0.72rem","marginLeft":"6px"},
                ),
             ]),
             html.Div([
                 dbc.Row([
                     dbc.Col(dcc.Graph(id="corner-speed-graph", config=GFX), md=6),
                     dbc.Col(dcc.Graph(id="corner-brake-graph", config=GFX), md=6),
                 ]),
                 dash_table.DataTable(
                     id="corner-analysis-table", data=[], columns=[], **TABLE_STYLE,
                 ),
             ]),
             info=("Data: for each lap you select in the Best Lap Leaderboard, the "
                   "lap is split into one zone per numbered corner (from the cached "
                   "circuit map). The apex is the slowest point in each zone; the "
                   "braking point is where the brake first comes on before it; the "
                   "exit speed is where the driver is back on full throttle. One lap "
                   "shows its full entry/apex/exit profile, several laps overlay apex "
                   "speed for comparison. Why: isolates exactly which corners — and "
                   "which phase, braking, apex or exit — a driver gains or loses in.")),
        card(html.Span([
                "Delta Decomposition by Mini-Sector",
                html.Span(
                    "  ·  cumulative time gap vs distance  ·  select 2+ laps in the "
                    "Best Lap Leaderboard above",
                    style={"color":TEXT_DIM,"fontWeight":"400","fontSize":"0.72rem","marginLeft":"6px"},
                ),
             ]),
             html.Div([
                 dcc.Graph(id="delta-trace-graph", config=GFX),
                 dcc.Graph(id="delta-sector-graph", config=GFX),
             ]),
             info=(f"Data: the fastest of the laps you select is the reference (the "
                   "zero line); every other lap is plotted as the running time gap "
                   "to it, against distance from the start line (time integrated from "
                   "the telemetry, lined up corner-for-corner). The lower chart splits "
                   f"that gap into {MINI_SECTORS} equal-distance mini-sectors, each bar "
                   "showing the time gained or lost through that stretch. Dotted grey "
                   "lines mark corners; faint bands mark the mini-sectors. Why: shows "
                   "not just who is faster but exactly where on the lap the time is won "
                   "or lost — a rising line (or a bar above zero) means that lap is "
                   "losing time through that stretch.")),
        card(html.Span([
                "Racing Line",
                html.Span(
                    "  ·  actual driven line (X/Y)  ·  one lap = speed-coloured, "
                    "several = overlaid to compare",
                    style={"color":TEXT_DIM,"fontWeight":"400","fontSize":"0.72rem","marginLeft":"6px"},
                ),
             ]),
             dcc.Graph(id="racing-line-graph", config=GFX),
             info=("Data: the actual X/Y track position of each lap you select in the "
                   "Best Lap Leaderboard, drawn in the circuit's orientation with corner "
                   "numbers. Position comes from the car-position telemetry stream merged "
                   "into the pipeline. Select one lap to see it coloured by speed; select "
                   "several to overlay their lines team-coloured. Why: shows the line each "
                   "driver actually takes — turn-in point, apex, how much track they use "
                   "on exit — which lap-time and speed traces alone can't reveal.")),
    ])


# ── Telemetry Channels overlay — driven by leaderboard selection ──
@app.callback(
    Output("laptel-channels-graph", "figure"),
    Input("laptel-best-table", "selected_rows"),
    State("laptel-best-table", "data"),
)
def update_laptel_channels(selected_rows, data):
    if not data or not selected_rows:
        return _empty_channel_fig(
            "Select one or more laps in the Best Lap Leaderboard to view telemetry.")
    specs = []
    for i in selected_rows:
        if i is None or i >= len(data):
            continue
        row = data[i]
        try:
            specs.append((row.get("Session"), row.get("Driver"), int(row.get("Lap #"))))
        except (TypeError, ValueError):
            continue
    if not specs:
        return _empty_channel_fig("Could not resolve the selected lap(s).")
    return _laptel_channel_fig(specs)


# ── Corner Analysis — driven by the same leaderboard selection ──
@app.callback(
    Output("corner-speed-graph", "figure"),
    Output("corner-brake-graph", "figure"),
    Output("corner-analysis-table", "data"),
    Output("corner-analysis-table", "columns"),
    Input("laptel-best-table", "selected_rows"),
    State("laptel-best-table", "data"),
)
def update_corner_analysis(selected_rows, data):
    if not data or not selected_rows:
        empty = _empty_channel_fig(
            "Select one or more laps in the Best Lap Leaderboard to view corner analysis.")
        return empty, empty, [], []
    specs = []
    for i in selected_rows:
        if i is None or i >= len(data):
            continue
        row = data[i]
        try:
            specs.append((row.get("Session"), row.get("Driver"), int(row.get("Lap #"))))
        except (TypeError, ValueError):
            continue
    if not specs:
        empty = _empty_channel_fig("Could not resolve the selected lap(s).")
        return empty, empty, [], []
    return _corner_analysis(specs)


# ── Delta decomposition — driven by the same leaderboard selection ──
@app.callback(
    Output("delta-trace-graph", "figure"),
    Output("delta-sector-graph", "figure"),
    Input("laptel-best-table", "selected_rows"),
    State("laptel-best-table", "data"),
)
def update_delta_decomposition(selected_rows, data):
    if not data or not selected_rows:
        empty = _empty_channel_fig(
            "Select two or more laps in the Best Lap Leaderboard to compare deltas.")
        return empty, empty
    specs = []
    for i in selected_rows:
        if i is None or i >= len(data):
            continue
        row = data[i]
        try:
            specs.append((row.get("Session"), row.get("Driver"), int(row.get("Lap #"))))
        except (TypeError, ValueError):
            continue
    if len(specs) < 2:
        empty = _empty_channel_fig(
            "Select at least two laps to compare deltas.")
        return empty, empty
    return _delta_decomposition(specs)


# ── Racing line — driven by the same leaderboard selection ──
@app.callback(
    Output("racing-line-graph", "figure"),
    Input("laptel-best-table", "selected_rows"),
    State("laptel-best-table", "data"),
)
def update_racing_line(selected_rows, data):
    if not data or not selected_rows:
        return _empty_channel_fig(
            "Select one or more laps in the Best Lap Leaderboard to view the racing line.")
    specs = []
    for i in selected_rows:
        if i is None or i >= len(data):
            continue
        row = data[i]
        try:
            specs.append((row.get("Session"), row.get("Driver"), int(row.get("Lap #"))))
        except (TypeError, ValueError):
            continue
    if not specs:
        return _empty_channel_fig("Could not resolve the selected lap(s).")
    return _racing_line_fig(specs)

# ══════════════════════════════════════════════════════════════
# TAB 4 – STINTS
# ══════════════════════════════════════════════════════════════

# Track flag visual config: (fill_rgba, line_hex)
_FLAG_STYLE = {
    "Yellow":       ("rgba(255,215,  0,0.10)", "#B8860B"),
    "DoubleYellow": ("rgba(255,140,  0,0.15)", "#CC6600"),
    "SafetyCar":    ("rgba(  0,220, 80,0.12)", "#007700"),
    "VSC":          ("rgba(  0,150,255,0.10)", "#0055BB"),
    "VSCEnding":    ("rgba(  0,150,255,0.07)", "#0055BB"),
    "RedFlag":      ("rgba(225,  6,  0,0.18)", "#AA0000"),
}


def _add_flag_bands(fig, df_sess):
    if "TrackStatus_Flag" not in df_sess.columns:
        return
    flag_laps = (
        df_sess[df_sess["TrackStatus_Flag"].isin(_FLAG_STYLE)]
        .sort_values("LapNo")[["LapNo", "TrackStatus_Flag"]]
        .drop_duplicates()
    )
    if flag_laps.empty:
        return
    groups = []
    for _, row in flag_laps.iterrows():
        lap, flag = int(row["LapNo"]), row["TrackStatus_Flag"]
        if groups and groups[-1]["flag"] == flag and lap == groups[-1]["end"] + 1:
            groups[-1]["end"] = lap
        else:
            groups.append({"flag": flag, "start": lap, "end": lap})
    seen = set()
    for grp in groups:
        flag = grp["flag"]
        fill, line_clr = _FLAG_STYLE[flag]
        show = flag not in seen
        seen.add(flag)
        fig.add_vrect(
            x0=grp["start"] - 0.5, x1=grp["end"] + 0.5,
            fillcolor=fill,
            line=dict(color=line_clr, width=1, dash="dot"),
            layer="below",
            annotation_text=flag if show else "",
            annotation_position="top left",
            annotation_font=dict(size=9, color=line_clr),
        )


def _rain_lap_groups(per_lap: pd.DataFrame) -> list[tuple[int, int]]:
    """Return contiguous (start_lap, end_lap) ranges where it was raining,
    from a per-lap frame carrying a boolean-ish 'Rainfall' column."""
    if "Rainfall" not in per_lap.columns or "LapNo" not in per_lap.columns:
        return []
    wet = per_lap[per_lap["Rainfall"].fillna(False).astype(bool)].sort_values("LapNo")
    if wet.empty:
        return []
    groups: list[tuple[int, int]] = []
    for lap in wet["LapNo"].astype(int):
        if groups and lap == groups[-1][1] + 1:
            groups[-1] = (groups[-1][0], lap)
        else:
            groups.append((lap, lap))
    return groups


def _add_rain_bands(fig, df_sess, row=None, col=None):
    """Shade laps run in the rain as blue vertical bands, mirroring the
    SC/flag bands from _add_flag_bands. No-op when there is no Rainfall data
    or the race was dry. Pass row/col to target one panel of a subplot."""
    if "Rainfall" not in df_sess.columns or "LapNo" not in df_sess.columns:
        return
    per_lap = df_sess.groupby("LapNo")["Rainfall"].max().reset_index()
    groups = _rain_lap_groups(per_lap)
    rc = dict(row=row, col=col) if row is not None else {}
    for i, (start, end) in enumerate(groups):
        fig.add_vrect(
            x0=start - 0.5, x1=end + 0.5,
            fillcolor="rgba(0,120,255,0.12)",
            line=dict(color="#0066CC", width=1, dash="dot"),
            layer="below",
            annotation_text=("\U0001f327 rain" if i == 0 else ""),
            annotation_position="bottom left",
            annotation_font=dict(size=9, color="#4DA3FF"),
            **rc,
        )


def _lap_evolution_fig(sv, title, height=540):
    """Per-driver lap-time line chart for a SINGLE session: one line per driver,
    markers tinted by compound, track-flag periods shaded behind. Shared by the
    Stints tab (any session) and the Race tab (race only)."""
    fig = go.Figure()
    for drv in sorted(sv["Driver_Short"].dropna().unique()):
        dv = sv[sv["Driver_Short"] == drv].sort_values("LapNo")
        if dv.empty:
            continue
        clr = TEAM_COLORS.get(dv["Team"].iloc[0], "#808080")
        # Build x/y/compound lists; insert None to break the line at lap gaps
        x_vals, y_vals, c_vals, f_vals = [], [], [], []
        prev_lap = None
        for _, row in dv.iterrows():
            if prev_lap is not None and row["LapNo"] - prev_lap > 1:
                x_vals.append(None); y_vals.append(None)
                c_vals.append(None); f_vals.append(None)
            x_vals.append(row["LapNo"])
            y_vals.append(row["LapTime_s"] if pd.notna(row["LapTime_s"]) else None)
            c_vals.append(row.get("Compound") or "?")
            f_vals.append(row.get("TrackStatus_Flag") or "Clear")
            prev_lap = row["LapNo"]

        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode="lines+markers",
            name=drv,
            line=dict(color=clr, width=1.5),
            marker=dict(
                size=6,
                color=[COMPOUND_COLORS.get(c, clr) if c else clr for c in c_vals],
                line=dict(color=clr, width=1),
            ),
            customdata=list(zip(c_vals, f_vals)),
            hovertemplate=(
                f"<b>{drv}</b><br>"
                "Lap %{x}  |  %{y:.3f} s<br>"
                "Compound: %{customdata[0]}<br>"
                "Flag: %{customdata[1]}<extra></extra>"
            ),
        ))

    _add_flag_bands(fig, sv)
    _add_rain_bands(fig, sv)
    theme(fig, height, title)
    fig.update_layout(
        xaxis_title="Lap Number",
        yaxis_title="Lap Time (s)",
        legend=dict(
            bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1,
            orientation="v",
        ),
    )
    return fig


# ══════════════════════════════════════════════════════════════
#  PRACTICE / WEEKEND CONSTRUCTION + SANDBAGGING
# ══════════════════════════════════════════════════════════════
#  Designed to be useful mid-weekend: it works with practice sessions
#  alone (after FP1/FP2, after FP3) and gains a confirmation layer once
#  qualifying is loaded. The practice-native sandbag signal is "pace in
#  hand" (one-lap gap% − long-run gap%, both vs the field); when quali
#  exists it is corroborated by "pace unlocked" (practice → quali).
# ══════════════════════════════════════════════════════════════
_TEAM_ABBR = {
    "Ferrari": "FER", "Red Bull Racing": "RBR", "Mercedes": "MER",
    "McLaren": "MCL", "Aston Martin": "AST", "Alpine": "ALP",
    "Williams": "WIL", "Racing Bulls": "RB", "RB": "RB", "AlphaTauri": "RB",
    "Haas F1 Team": "HAAS", "Audi": "AUD", "Cadillac": "CAD",
    "Sauber": "SAU", "Kick Sauber": "SAU", "Alfa Romeo": "SAU",
    "Alfa Romeo Racing": "SAU",
}
_COMPOUND_RANK = {"SOFT": 0, "MEDIUM": 1, "HARD": 2, "INTER": 3, "WET": 4}

# Sandbagging flag thresholds (each crossed threshold = one 🚩)
_SB_HAND_THRESH = 0.30   # % one-lap gap worse than long-run gap (pace in hand)
_SB_BANK_THRESH = 0.40   # s of unassembled (banked) practice lap time
_SB_PACE_THRESH = 0.30   # % more relative pace unlocked Friday→Quali (needs quali)
_SB_TRAP_THRESH = 3.0    # km/h trap-speed gain Quali vs practice (needs quali)
_LONGRUN_MIN_LAPS = 5    # min non-quali-sim laps for a long-run pace estimate


def _abbr(team) -> str:
    return _TEAM_ABBR.get(team, str(team)[:3].upper())


def _practice_analysis(wl):
    """
    Build per-team weekend-construction / sandbagging evidence for the loaded
    event. Adapts to whatever sessions are present so it is meaningful after
    FP1/FP2 and after FP3, before qualifying has run.

    Every signal uses only clean laps (ValidLap & not Perturbed) so traffic,
    track-status and sector anomalies are never mistaken for hidden pace.

    Returns a dict with keys: team_df, banked_df, prog_df, has_quali,
    n_prac_sessions, event_label, flag_cols.
    """
    clean = wl[wl["ValidLap"] & ~wl["Perturbed_Lap"] & wl["LapTime_s"].notna()].copy()

    # Human-readable event label: "Practice 2_Australian Grand Prix_2026"
    event_label = ""
    if not wl.empty:
        parts = str(wl["session_name"].iloc[0]).split("_")
        if len(parts) >= 3:
            event_label = f"{parts[1]} {parts[2]}"

    prac = clean[clean["session_name"].str.startswith("Practice")]
    qual = clean[clean["session_name"].str.startswith("Qualifying")]
    pqs  = prac[prac["Is_Quali_Sim"]]
    has_quali = not qual.empty
    n_prac_sessions = prac["session_name"].nunique()

    # Long-run pool: clean practice laps that are NOT one-lap quali-sims and not
    # in/out laps — a proxy for race-run pace, fuel-corrected.
    lr = prac[~prac["Is_Quali_Sim"]].copy()
    for pit in ("PitOut", "PitIn"):
        if pit in lr.columns:
            lr = lr[~lr[pit].astype("boolean").fillna(False)]

    teams = sorted(clean["Team"].dropna().unique())
    rows = []
    for t in teams:
        pt  = prac[prac["Team"] == t]
        pqt = pqs[pqs["Team"] == t]
        qt  = qual[qual["Team"] == t]
        lrt = lr[lr["Team"] == t]
        prac_src = pqt if not pqt.empty else pt          # fall back if no quali-sim

        prac_best = prac_src["LapTime_s"].min() if not prac_src.empty else np.nan
        prac_trap = prac_src["Speed_ST"].max()  if not prac_src.empty else np.nan
        qual_best = qt["LapTime_s"].min()        if not qt.empty else np.nan
        qual_trap = qt["Speed_ST"].max()         if not qt.empty else np.nan

        longrun = (lrt["LapTime_FuelCorrected"].median()
                   if len(lrt) >= _LONGRUN_MIN_LAPS else np.nan)

        comps = [c for c in pqt["Compound"].dropna().unique()]
        softest = min(comps, key=lambda c: _COMPOUND_RANK.get(str(c).upper(), 9)) if comps else "—"
        ran_soft_qs = any(str(c).upper() == "SOFT" for c in comps)

        rows.append({
            "Team": t,
            "prac_best": prac_best, "qual_best": qual_best,
            "prac_trap": prac_trap, "qual_trap": qual_trap,
            "longrun": longrun, "n_qs": int(len(pqt)),
            "softest": softest, "ran_soft_qs": ran_soft_qs,
        })
    tdf = pd.DataFrame(rows)

    # ── Gaps to the field (self-cancels track evolution) ──
    field_prac = tdf["prac_best"].min(skipna=True) if not tdf.empty else np.nan
    field_lr   = tdf["longrun"].min(skipna=True)   if not tdf.empty else np.nan
    pole       = tdf["qual_best"].min(skipna=True) if has_quali else np.nan
    tdf["prac_gap_pct"]    = (tdf["prac_best"] / field_prac - 1) * 100 if pd.notna(field_prac) else np.nan
    tdf["longrun_gap_pct"] = (tdf["longrun"] / field_lr - 1) * 100     if pd.notna(field_lr) else np.nan
    tdf["qual_gap_pct"]    = (tdf["qual_best"] / pole - 1) * 100       if pd.notna(pole) else np.nan
    # Practice-native sandbag signal: relatively worse one-lap than race pace
    # ⇒ likely sitting on qualifying pace.
    tdf["pace_in_hand"] = tdf["prac_gap_pct"] - tdf["longrun_gap_pct"]
    # Quali confirmation (only when quali present)
    tdf["pace_unlocked"] = tdf["prac_gap_pct"] - tdf["qual_gap_pct"]
    tdf["trap_delta"]    = tdf["qual_trap"] - tdf["prac_trap"]

    # ── Banked time: best assembled lap vs sum of best sectors (practice) ──
    if not prac.empty:
        bp = (prac.groupby(["Driver_Short", "Team"])
              .agg(s1=("Sector1Time", "min"), s2=("Sector2Time", "min"),
                   s3=("Sector3Time", "min"), actual=("LapTime_s", "min"))
              .reset_index())
        bp["theo"]   = bp["s1"] + bp["s2"] + bp["s3"]
        bp["banked"] = (bp["actual"] - bp["theo"]).round(3)
        bp = bp[bp["theo"].notna() & (bp["banked"] >= 0)].sort_values("banked", ascending=False)
    else:
        bp = pd.DataFrame(columns=["Driver_Short", "Team", "theo", "actual", "banked"])

    team_bank = bp.groupby("Team")["banked"].max() if not bp.empty else pd.Series(dtype=float)
    tdf["team_banked"] = tdf["Team"].map(team_bank)

    # ── Flags ── practice-native always apply; quali flags add when present ──
    any_soft = bool(tdf["ran_soft_qs"].any())
    tdf["flag_hand"]   = tdf["pace_in_hand"] > _SB_HAND_THRESH
    tdf["flag_bank"]   = tdf["team_banked"]  > _SB_BANK_THRESH
    # "Hasn't shown one-lap pace": no soft-tyre quali-sim yet, but only counts
    # once at least one team has (i.e. the session is mature enough).
    tdf["flag_noshow"] = any_soft & (~tdf["ran_soft_qs"])
    flag_cols = ["flag_hand", "flag_bank", "flag_noshow"]
    if has_quali:
        tdf["flag_pace"] = tdf["pace_unlocked"] > _SB_PACE_THRESH
        tdf["flag_trap"] = tdf["trap_delta"]    > _SB_TRAP_THRESH
        flag_cols += ["flag_pace", "flag_trap"]
    tdf["flags"] = tdf[flag_cols].fillna(False).sum(axis=1).astype(int)

    # ── Pace progression (best quali-sim lap gap to that session's field) ──
    prog_rows = []
    for sess in ["Practice 1", "Practice 2", "Practice 3", "Qualifying"]:
        sd = clean[clean["session_name"].str.startswith(sess)]
        if sd.empty:
            continue
        src = sd[sd["Is_Quali_Sim"]] if sess != "Qualifying" else sd
        if src.empty:
            src = sd
        best  = src.groupby("Team")["LapTime_s"].min()
        field = best.min()
        for t, v in best.items():
            prog_rows.append({"session": sess, "Team": t,
                              "gap_pct": (v / field - 1) * 100})
    prog = pd.DataFrame(prog_rows)

    return {
        "team_df": tdf, "banked_df": bp, "prog_df": prog,
        "has_quali": has_quali, "n_prac_sessions": n_prac_sessions,
        "event_label": event_label, "flag_cols": flag_cols,
    }


def _sb_div_bar(df, valcol, xaxis_title, *, suffix="%", decimals=2, flags=True):
    """Team-coloured horizontal diverging bar with outside labels and headroom
    so the longest labels never clip. Returns None if no data."""
    d = df.dropna(subset=[valcol]).sort_values(valcol)
    if d.empty:
        return None
    fcol = d["flags"] if (flags and "flags" in d.columns) else [0] * len(d)
    ylabels = [f"{_abbr(t)}{'  🚩' if f >= 2 else ''}" for t, f in zip(d["Team"], fcol)]
    fig = go.Figure(go.Bar(
        x=d[valcol], y=ylabels, orientation="h",
        marker_color=[TEAM_COLORS.get(t, "#808080") for t in d["Team"]],
        text=[f"{v:+.{decimals}f}{suffix}" for v in d[valcol]],
        textposition="outside", textfont=dict(size=9, color=TEXT_MAIN),
        customdata=d["Team"],
        hovertemplate="%{customdata}: %{x:+." + str(decimals) + "f}" + suffix + "<extra></extra>"))
    theme(fig, max(240, len(d) * 40 + 110), "")
    fig.add_vline(x=0, line_color=TEXT_DIM, line_width=1)
    vmax = d[valcol].abs().max() or 1
    fig.update_layout(showlegend=False, xaxis_title=xaxis_title,
        margin=dict(l=110, r=95, t=20, b=44),
        xaxis_range=[d[valcol].min() - vmax * 0.55, d[valcol].max() + vmax * 0.55])
    return fig


def _sb_quadrant(df, xcol, ycol, xtitle, ytitle, below_note):
    """Team-coloured scatter against a y=x parity line."""
    qd = df.dropna(subset=[xcol, ycol])
    fig = go.Figure()
    if not qd.empty:
        m = float(max(qd[xcol].max(), qd[ycol].max(), 0.1)) * 1.12
        fig.add_trace(go.Scatter(x=[0, m], y=[0, m], mode="lines",
            line=dict(color=TEXT_DIM, dash="dash"), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=qd[xcol], y=qd[ycol], mode="markers+text",
            text=[_abbr(t) for t in qd["Team"]], textposition="top center",
            textfont=dict(size=10, color=TEXT_MAIN),
            marker=dict(size=14, color=[TEAM_COLORS.get(t, "#808080") for t in qd["Team"]],
                        line=dict(width=1, color="#000")),
            customdata=qd["Team"],
            hovertemplate="%{customdata}<br>+%{x:.2f}%  /  +%{y:.2f}%<extra></extra>"))
        fig.add_annotation(x=m * 0.72, y=m * 0.16, text=below_note,
            showarrow=False, font=dict(color=ACCENT, size=11))
    theme(fig, 430, "")
    fig.update_layout(showlegend=False, xaxis_title=xtitle, yaxis_title=ytitle,
        margin=dict(l=60, r=30, t=20, b=44))
    return fig


def tab_practice(wl):
    if wl is None or wl.empty:
        return html.P("No lap data for the current selection.",
                      style={"color": TEXT_DIM})

    a = _practice_analysis(wl)
    tdf, bp, prog = a["team_df"], a["banked_df"], a["prog_df"]
    has_quali, event_label = a["has_quali"], a["event_label"]
    phase = ("Full weekend (quali loaded)" if has_quali
             else f"Practice in progress · {a['n_prac_sessions']} session(s) so far")

    intro = html.P([
        html.B("Practice construction & sandbagging.  "),
        "Built to work mid-weekend — after FP1/FP2 and after FP3, before qualifying. ",
        "All metrics use clean laps only (valid; traffic/flag-perturbed laps removed) and "
        "are expressed as a gap to the field, which cancels out track evolution. ",
        "The practice-native sandbag signal is ", html.B("pace in hand"),
        " (one-lap gap minus race-run gap); once qualifying is loaded it is "
        "confirmed by ", html.B("pace unlocked"), ". Inferential by nature — "
        "these are corroborating signals, not verdicts.",
    ], style={"color": TEXT_DIM, "fontSize": "0.8rem", "marginBottom": "14px",
              "lineHeight": "1.5"})

    # ── KPI strip (adapts to phase) ─────────────────────────────
    kpis = []
    if tdf["pace_in_hand"].notna().any():
        toph = tdf.loc[tdf["pace_in_hand"].idxmax()]
        kpis.append(kpi("MOST PACE IN HAND", f"{_abbr(toph['Team'])}  +{toph['pace_in_hand']:.2f}%",
                        tooltip="Largest gap between a team's one-lap deficit and its race-run deficit — relatively stronger on long runs than on a single lap, i.e. likely sitting on qualifying pace."))
    if has_quali and tdf["pace_unlocked"].notna().any():
        topu = tdf.loc[tdf["pace_unlocked"].idxmax()]
        kpis.append(kpi("MOST PACE UNLOCKED", f"{_abbr(topu['Team'])}  +{topu['pace_unlocked']:.2f}%",
                        color="#FFD700",
                        tooltip="Largest relative one-lap improvement from practice quali-sims to qualifying — confirms hidden pace."))
    if not bp.empty:
        topb = bp.iloc[0]
        kpis.append(kpi("MOST BANKED TIME", f"{topb['Driver_Short']}  {topb['banked']:.2f}s",
                        color="#39B54A",
                        tooltip="Largest gap between a driver's best practice lap and the sum of their best sectors — pace available but never assembled."))
    n_flagged = int((tdf["flags"] >= 2).sum())
    kpis.append(kpi("FLAGGED TEAMS", f"{n_flagged}  ·  {event_label}",
                    color=ACCENT if n_flagged else TEXT_MAIN,
                    tooltip="Teams crossing ≥2 sandbag signals (pace in hand, banked time, no soft-tyre run shown" + (", pace unlocked, trap gain" if has_quali else "") + ")."))
    kpi_row = dbc.Row(kpis, className="mb-2")

    phase_pill = html.Div(html.Span(phase, style={
        "background": (ACCENT if has_quali else "#0055BB"), "color": "#fff",
        "borderRadius": "4px", "padding": "3px 10px", "fontSize": "0.72rem",
        "fontWeight": "700", "letterSpacing": "0.5px"}),
        style={"marginBottom": "14px"})

    body = [intro, kpi_row, phase_pill]

    # ── Headline: pace in hand + one-lap-vs-long-run quadrant ───
    fig_hand = _sb_div_bar(tdf, "pace_in_hand",
        "Pace in hand  (%)   ·   + = relatively faster on race runs than one lap")
    fig_olr = _sb_quadrant(tdf, "prac_gap_pct", "longrun_gap_pct",
        "Best one-lap gap to field  (%)", "Race-run gap to field  (%)",
        "below line = one-lap pace in hand")
    head_cols = []
    if fig_hand is not None:
        head_cols.append(dbc.Col(card("SANDBAG SCOREBOARD · PACE IN HAND",
            dcc.Graph(figure=fig_hand, config=GFX),
            info="One-lap gap to field minus race-run gap to field. Positive = the team is relatively further back on a single lap than on long runs, a classic sign of qualifying pace held in reserve. 🚩 = ≥2 sandbag signals."), md=6))
    head_cols.append(dbc.Col(card("ONE-LAP vs RACE-RUN",
        dcc.Graph(figure=fig_olr, config=GFX),
        info="Each team's best practice one-lap gap (x) vs its fuel-corrected race-run gap (y), both relative to the field. Markers below the parity line are stronger on long runs than on one lap — one-lap pace likely in hand."),
        md=6 if fig_hand is not None else 12))
    body.append(dbc.Row(head_cols))

    # ── Banked time (per driver) ────────────────────────────────
    if not bp.empty:
        bb = bp.head(24)
        fig_b = go.Figure(go.Bar(
            x=bb["banked"], y=bb["Driver_Short"], orientation="h",
            marker_color=[TEAM_COLORS.get(t, "#808080") for t in bb["Team"]],
            text=[f"{v:.2f}s" for v in bb["banked"]],
            textposition="outside", textfont=dict(size=9, color=TEXT_MAIN),
            customdata=bb["Team"],
            hovertemplate="%{y} (%{customdata})<br>banked %{x:.2f}s<extra></extra>"))
        theme(fig_b, max(260, len(bb) * 26 + 110), "")
        fig_b.update_layout(showlegend=False,
            xaxis_title="Unassembled practice lap time  (s)  =  best lap − sum of best sectors",
            margin=dict(l=60, r=70, t=20, b=44),
            xaxis_range=[0, (bb["banked"].max() or 0.5) * 1.18])
        fig_b.update_yaxes(autorange="reversed")
        body.append(dbc.Row([dbc.Col(card("BANKED TIME · PRACTICE (per driver)",
            dcc.Graph(figure=fig_b, config=GFX),
            info="Best assembled practice lap minus the sum of the driver's best sectors. Large values mean the pace was there but never put together on one lap — sometimes deliberate."), md=12)]))

    # ── Pace progression across the sessions present ────────────
    if not prog.empty:
        order = [s for s in ["Practice 1", "Practice 2", "Practice 3", "Qualifying"]
                 if s in prog["session"].unique()]
        fig_p = go.Figure()
        for t in sorted(prog["Team"].unique()):
            sub = (prog[prog["Team"] == t].set_index("session")
                   .reindex(order).reset_index())
            fig_p.add_trace(go.Scatter(
                x=sub["session"], y=sub["gap_pct"], mode="lines+markers",
                name=_abbr(t), connectgaps=True,
                line=dict(color=TEAM_COLORS.get(t, "#808080"), width=2),
                marker=dict(size=7),
                hovertemplate=f"{_abbr(t)} · %{{x}}<br>+%{{y:.2f}}%<extra></extra>"))
        theme(fig_p, 460, "")
        fig_p.update_layout(
            xaxis_title="", yaxis_title="Gap to session-best  (%)  ·  lower = faster",
            legend=dict(orientation="h", x=0, y=1.12, bgcolor="rgba(0,0,0,0)"),
            margin=dict(l=60, r=30, t=40, b=30))
        fig_p.update_yaxes(autorange="reversed")
        body.append(dbc.Row([dbc.Col(card("PACE PROGRESSION",
            dcc.Graph(figure=fig_p, config=GFX),
            info="Each team's best quali-sim lap per session (best valid lap in qualifying), as a gap to that session's fastest. Y-axis inverted so rising lines = relative improvement. Shows the build trajectory across the weekend."), md=12)]))

    # ── Quali confirmation layer (only once qualifying is loaded) ──
    if has_quali:
        fig_sc = _sb_div_bar(tdf, "pace_unlocked",
            "Pace unlocked Friday → Quali  (%)   ·   + = hid pace in practice")
        fig_q = _sb_quadrant(tdf, "prac_gap_pct", "qual_gap_pct",
            "Practice quali-sim gap to field  (%)", "Qualifying gap to pole  (%)",
            "below line = hid pace")
        conf_cols = []
        if fig_sc is not None:
            conf_cols.append(dbc.Col(card("CONFIRMATION · PACE UNLOCKED",
                dcc.Graph(figure=fig_sc, config=GFX),
                info="Practice quali-sim gap% minus qualifying gap%, both vs the field. Positive = the team was relatively further back in practice than in qualifying — hidden pace, now confirmed."), md=6))
        conf_cols.append(dbc.Col(card("PRACTICE vs QUALIFYING",
            dcc.Graph(figure=fig_q, config=GFX),
            info="Each team's best practice quali-sim gap (x) vs its qualifying gap to pole (y). Markers below the parity line qualified relatively better than they ran in practice."),
            md=6 if fig_sc is not None else 12))
        body.append(dbc.Row(conf_cols))

        td = tdf.dropna(subset=["trap_delta"]).sort_values("trap_delta")
        if not td.empty:
            fig_t = go.Figure(go.Bar(
                x=td["trap_delta"], y=[_abbr(t) for t in td["Team"]], orientation="h",
                marker_color=[TEAM_COLORS.get(t, "#808080") for t in td["Team"]],
                text=[f"{v:+.1f}" for v in td["trap_delta"]],
                textposition="outside", textfont=dict(size=9, color=TEXT_MAIN),
                customdata=td["Team"], hovertemplate="%{customdata}: %{x:+.1f} km/h<extra></extra>"))
            theme(fig_t, max(240, len(td) * 40 + 110), "")
            fig_t.add_vline(x=0, line_color=TEXT_DIM, line_width=1)
            _tmax = td["trap_delta"].abs().max() or 1
            fig_t.update_layout(showlegend=False,
                xaxis_title="Top-speed gain Quali vs Practice  (km/h)   ·   + = held PU back Friday",
                margin=dict(l=90, r=80, t=20, b=44),
                xaxis_range=[td["trap_delta"].min() - _tmax * 0.32,
                             td["trap_delta"].max() + _tmax * 0.3])
            body.append(dbc.Row([dbc.Col(card("ENGINE-MODE EVIDENCE · SPEED TRAP",
                dcc.Graph(figure=fig_t, config=GFX),
                info="Max speed-trap reading in qualifying minus the max on practice quali-sim laps. A large positive gap suggests the team ran reduced power modes in practice."), md=12)]))

    # ── Evidence table (columns adapt to phase) ─────────────────
    tt = tdf.sort_values("flags", ascending=False).copy()
    def _fmt(v, suf="", plus=False):
        if pd.isna(v):
            return "—"
        return (f"{v:+.2f}{suf}" if plus else f"{v:.2f}{suf}")
    recs = []
    for _, r in tt.iterrows():
        rec = {
            "Team": r["Team"],
            "One-lap gap%":  _fmt(r["prac_gap_pct"], "%"),
            "Race-run gap%": _fmt(r["longrun_gap_pct"], "%"),
            "Pace in hand":  _fmt(r["pace_in_hand"], "%", plus=True),
            "Banked (s)":    _fmt(r["team_banked"], "s"),
            "# quali-sims":  int(r["n_qs"]),
            "Softest":       r["softest"],
        }
        if has_quali:
            rec["Quali gap%"]    = _fmt(r["qual_gap_pct"], "%")
            rec["Pace unlocked"] = _fmt(r["pace_unlocked"], "%", plus=True)
            rec["Δ trap (km/h)"] = _fmt(r["trap_delta"], "", plus=True)
        rec["Flags"] = "🚩" * int(r["flags"]) if r["flags"] else "—"
        recs.append(rec)
    table = dash_table.DataTable(
        data=recs,
        columns=[{"name": c, "id": c} for c in recs[0].keys()] if recs else [],
        **TABLE_STYLE,
        style_data_conditional=[
            {"if": {"filter_query": "{Flags} contains '🚩🚩'"},
             "backgroundColor": ACCENT + "22", "fontWeight": "700"},
        ],
    )
    _thresh = ("pace in hand >0.30%, banked >0.40s, no soft-tyre run shown"
               + (", pace unlocked >0.30%, trap gain >3 km/h" if has_quali else ""))
    body.append(card("EVIDENCE TABLE", table,
        info=f"All signals per team. Flags fire at {_thresh}. Sortable — click a header."))

    return html.Div(body)


def _best_stint_laps(fl, stints_df):
    """Return laps that belong to the best valid stint per driver x compound
    (session-agnostic: Stint_Rank_Across_Sessions == 1).
    Falls back to all valid laps if stints_df is empty or ranking unavailable.

    Note: analyze_stints() does not carry Stint_key, so we match on the
    three component columns (session_name, Driver_Short, Stint) instead.
    """
    if stints_df is None or stints_df.empty or "Stint_Rank_Across_Sessions" not in stints_df.columns:
        return fl[fl["ValidLap"]].copy()

    best = stints_df[
        stints_df["Valid_Stint"] & (stints_df["Stint_Rank_Across_Sessions"] == 1)
    ][["session_name", "Driver_Short", "Stint"]].drop_duplicates()

    # Build a merge key on the laps side then filter
    fl_valid = fl[fl["ValidLap"]].copy()
    merged = fl_valid.merge(
        best.assign(_keep=True),
        on=["session_name", "Driver_Short", "Stint"],
        how="left",
    )
    return merged[merged["_keep"] == True].drop(columns=["_keep"]).copy()


def tab_stints(fl, fs):
    # 1. Lap Time Evolution layout (dynamic via callback)
    avail_sessions = sorted(fl["session_name"].unique())
    default_sess   = avail_sessions[0] if avail_sessions else None

    flag_pills = [
        html.Span("Track flags: ",
                  style={"color": TEXT_DIM, "fontSize": "0.72rem"}),
    ]
    for label, bg in [
        ("Yellow", "#B8860B"), ("Dbl Yellow", "#CC6600"),
        ("Safety Car", "#007700"), ("VSC", "#0055BB"), ("Red Flag", "#AA0000"),
    ]:
        flag_pills.append(html.Span(label, style={
            "background": bg, "color": "#fff", "borderRadius": "3px",
            "padding": "2px 7px", "fontSize": "0.68rem", "fontWeight": "700",
            "marginRight": "5px",
        }))

    evo_layout = html.Div([
        html.Div(
            dcc.RadioItems(
                id="stints-evo-session",
                options=[{"label": s, "value": s} for s in avail_sessions],
                value=default_sess,
                inline=True,
                inputStyle={"marginRight": "6px", "accentColor": ACCENT},
                labelStyle={
                    "marginRight": "18px", "fontSize": "0.78rem",
                    "color": TEXT_MAIN, "cursor": "pointer",
                },
            ),
            style={"marginBottom": "10px"},
        ),
        html.Div(flag_pills, style={"marginBottom": "8px"}),
        dcc.Graph(id="stints-evo-graph", config=GFX),
    ])

    # 2. Violin per compound – laps from best stint only (session-agnostic)
    best_laps = _best_stint_laps(fl, fs)
    v_note = html.P(
        "ℹ️  Each violin uses only laps from the single best valid stint "
        "per driver × compound across all selected sessions "
        "(Stint_Rank_Across_Sessions = 1).",
        style={"color": TEXT_DIM, "fontSize": "0.75rem", "marginBottom": "6px",
               "fontStyle": "italic"},
    )
    team_order = (
        best_laps.groupby("Team")["LapTime_s"].min().sort_values().index.tolist()
        if not best_laps.empty else []
    )

    violin_cards = []
    for compound in COMPOUNDS:
        df_comp = best_laps[best_laps["Compound"] == compound]
        if df_comp.empty:
            continue
        fig_v = go.Figure()
        anns  = []
        for team in team_order:
            df_team = df_comp[df_comp["Team"] == team]
            if df_team.empty:
                continue
            drivers = sorted(df_team["Driver_Short"].dropna().unique())
            clr  = TEAM_COLORS.get(team, "#808080")
            rgba = "rgba({},{},{},0.27)".format(
                int(clr[1:3], 16), int(clr[3:5], 16), int(clr[5:7], 16)
            )
            for i, driver in enumerate(drivers[:2]):
                df_drv = df_team[df_team["Driver_Short"] == driver]
                if df_drv.empty:
                    continue
                lap_count = len(df_drv)
                ymax      = df_drv["LapTime_s"].max()
                ymin      = df_drv["LapTime_s"].min()
                margin    = (ymax - ymin) * 0.2 if ymax != ymin else 0.5
                side      = "negative" if i == 0 else "positive"
                pointpos  = -0.8      if i == 0 else 0.8
                fig_v.add_trace(go.Violin(
                    x=[team] * lap_count,
                    y=df_drv["LapTime_s"],
                    legendgroup=driver,
                    scalegroup=team,
                    name=driver,
                    side=side,
                    pointpos=pointpos,
                    line_color=clr,
                    fillcolor=rgba,
                    meanline_visible=True,
                    points="all",
                    jitter=0.05,
                    scalemode="count",
                    showlegend=True,
                ))
                anns.append(dict(
                    x=team, y=ymax + margin / 2,
                    text=f"{driver} ({lap_count})",
                    showarrow=False,
                    xshift=-25 if side == "negative" else 25,
                    yshift=10,
                    font=dict(size=11, color=clr),
                ))
        theme(fig_v, 650,
              f"Lap Time Distribution – {compound} (best stint per driver, all sessions)")
        fig_v.update_layout(
            violingap=0, violingroupgap=0, violinmode="overlay",
            xaxis=dict(categoryorder="array", categoryarray=team_order,
                       gridcolor=GRID_CLR, zeroline=False),
            yaxis_title="Lap Time (s)",
            annotations=anns,
        )
        violin_cards.append(card(
            f"Distribution – {compound}",
            html.Div([v_note, dcc.Graph(figure=fig_v, config=GFX)]),
            info=(f"Data: lap times from each driver's single best valid {compound} "
                  "stint across all selected sessions (split-violin per teammate "
                  "pair, point count shown). Why: compares teams on equal tyre, "
                  "showing both typical pace (the body) and consistency (the spread)."),
        ))

    # 3. Tyre Degradation – per compound:
    #    (a) Ranked horizontal bar: Stint_Deg_Rate from the stint with best R²
    #        (most statistically reliable regression, not necessarily fastest stint)
    #        Source: analyze_stints() which uses LapTime_FuelCorrected and ValidLap.
    #        Additional filter: exclude Perturbed_Lap laps fed into the viz.
    #    (b) Normalised evolution: LapTime_FuelCorrected delta from lap-1 baseline,
    #        using the LONGEST valid non-perturbed stint per driver x compound
    #        (more laps = better shape; fuel-corrected so car weight doesn’t mask deg).
    deg_cards = []
    valid_stints = fs[fs["Valid_Stint"]].copy() if not fs.empty else pd.DataFrame()

    # Build a clean laps pool: ValidLap AND not Perturbed_Lap (if column exists)
    _perturb_mask = fl["Perturbed_Lap"] if "Perturbed_Lap" in fl.columns else pd.Series(False, index=fl.index)
    clean_laps = fl[fl["ValidLap"] & ~_perturb_mask].copy()

    for compound in COMPOUNDS:
        comp_stints = (
            valid_stints[valid_stints["Compound"] == compound].copy()
            if not valid_stints.empty else pd.DataFrame()
        )

        # --- (a) Deg rate bar: best-R² stint per driver ---
        fig_bar = None
        df_deg  = pd.DataFrame()
        if not comp_stints.empty and "Stint_Deg_Rate" in comp_stints.columns:
            has_r2 = comp_stints["Stint_Deg_R2"].notna()
            # Pick the stint with the highest R² for each driver; fall back to
            # highest lap count when R² is unavailable for all stints of that driver.
            best_r2 = (
                comp_stints[has_r2]
                .sort_values("Stint_Deg_R2", ascending=False)
                .groupby("Driver_Short", sort=False)
                .first()
                .reset_index()
            )
            # Drivers whose stints all have NaN R² → fall back to longest stint
            drivers_with_r2 = set(best_r2["Driver_Short"])
            fallback = (
                comp_stints[~comp_stints["Driver_Short"].isin(drivers_with_r2)]
                .sort_values("Stint_Laps_Count", ascending=False)
                .groupby("Driver_Short", sort=False)
                .first()
                .reset_index()
            )
            df_deg = pd.concat([best_r2, fallback], ignore_index=True)
            df_deg = df_deg[df_deg["Stint_Deg_Rate"].notna()].copy()

        if not df_deg.empty:
            df_deg = df_deg.sort_values("Stint_Deg_Rate", ascending=False)
            df_deg["Color"]   = df_deg["Team"].map(TEAM_COLORS).fillna("#808080")
            df_deg["DegFmt"]  = df_deg["Stint_Deg_Rate"].apply(
                lambda x: f"+{x:.4f}" if x >= 0 else f"{x:.4f}"
            )
            df_deg["R2Fmt"]   = df_deg["Stint_Deg_R2"].apply(
                lambda x: f"R²={x:.2f}" if pd.notna(x) else "R²=n/a"
            )
            df_deg["R2Color"] = df_deg["Stint_Deg_R2"].apply(
                lambda x: ("#00D2BE" if x >= 0.50 else ("#FF8700" if x >= 0.20 else "#E10600"))
                if pd.notna(x) else "#808080"
            )
            max_abs = df_deg["Stint_Deg_Rate"].abs().max() * 1.4 or 0.05

            fig_bar = go.Figure(go.Bar(
                y=df_deg["Driver_Short"],
                x=df_deg["Stint_Deg_Rate"],
                orientation="h",
                marker=dict(
                    color=df_deg["Color"],
                    line=dict(color=GRID_CLR, width=0.5),
                ),
                customdata=df_deg[["Team", "DegFmt", "R2Fmt", "R2Color",
                                   "Stint_Laps_Count", "session_name"]].values,
                hovertemplate=(
                    "<b>%{y}</b>  Team: %{customdata[0]}<br>"
                    "Deg rate: %{customdata[1]} s/lap<br>"
                    "<span style='color:%{customdata[3]}'>%{customdata[2]}</span><br>"
                    "Laps in stint: %{customdata[4]}<br>"
                    "Session: %{customdata[5]}<extra></extra>"
                ),
                text=df_deg["DegFmt"],
                textposition="outside",
                textfont=dict(size=10, color=TEXT_MAIN),
            ))
            fig_bar.add_vline(x=0, line=dict(color="white", width=1, dash="dash"))
            fig_bar.add_vrect(x0=-max_abs, x1=0,
                fillcolor="rgba(0,200,100,0.05)", line_width=0, layer="below")
            fig_bar.add_vrect(x0=0, x1=max_abs,
                fillcolor="rgba(225,6,0,0.05)", line_width=0, layer="below")
            ht = max(300, 28 * len(df_deg) + 80)
            theme(fig_bar, ht,
                  f"{compound} – Degradation Rate (best-R² stint, fuel-corrected)")
            fig_bar.update_layout(
                xaxis=dict(
                    title="s/lap  ← better tyre management",
                    range=[-max_abs, max_abs],
                    gridcolor=GRID_CLR, zeroline=False,
                ),
                yaxis=dict(gridcolor=GRID_CLR, zeroline=False, autorange="reversed"),
                bargap=0.25, showlegend=False,
                annotations=[dict(
                    text="🟢 R²≥0.50 good  🟠 0.20–0.50  🔴 <0.20 / n/a",
                    xref="paper", yref="paper", x=1, y=1.02,
                    xanchor="right", showarrow=False,
                    font=dict(size=9, color=TEXT_DIM),
                )],
            )

        # --- (b) Normalised evolution: longest clean stint per driver ---
        # Group clean laps by (driver, stint) and pick the stint with most laps
        comp_clean = clean_laps[clean_laps["Compound"] == compound].copy()
        _age_col = "TyreAge" if "TyreAge" in comp_clean.columns else "LapInStint"

        fig_norm = go.Figure()
        if not comp_clean.empty:
            stint_lens = (
                comp_clean.groupby(["Driver_Short", "session_name", "Stint"])
                .size()
                .reset_index(name="_n_laps")
                .sort_values("_n_laps", ascending=False)
            )
            # Best stint = longest; one per driver
            best_per_drv = (
                stint_lens.groupby("Driver_Short", sort=False)
                .first()
                .reset_index()
            )
            for _, brow in best_per_drv.iterrows():
                drv  = brow["Driver_Short"]
                sess = brow["session_name"]
                snt  = brow["Stint"]
                n    = int(brow["_n_laps"])
                if n < 2:
                    continue
                df_drv = (
                    comp_clean[
                        (comp_clean["Driver_Short"] == drv)
                        & (comp_clean["session_name"] == sess)
                        & (comp_clean["Stint"] == snt)
                    ]
                    .sort_values(_age_col)
                )
                baseline = df_drv.iloc[0]["LapTime_FuelCorrected"]
                if pd.isna(baseline) or baseline <= 0:
                    continue
                clr   = TEAM_COLORS.get(df_drv["Team"].iloc[0], "#808080")
                delta = df_drv["LapTime_FuelCorrected"] - baseline
                sess_label = sess.split("_")[0]
                fig_norm.add_trace(go.Scatter(
                    x=df_drv[_age_col],
                    y=delta,
                    mode="lines+markers",
                    name=f"{drv} ({n} laps, {sess_label})",
                    line=dict(color=clr, width=2),
                    marker=dict(size=6, color=clr),
                    hovertemplate=(
                        f"<b>{drv}</b><br>"
                        "Tyre age: %{x} laps<br>"
                        "Δ fuel-corrected from stint start: %{y:+.3f} s"
                        "<extra></extra>"
                    ),
                ))
            if fig_norm.data:
                fig_norm.add_hline(y=0, line=dict(color="white", width=1, dash="dash"))
                fig_norm.add_hrect(y0=0, y1=999,
                    fillcolor="rgba(225,6,0,0.03)", line_width=0, layer="below")
                fig_norm.add_hrect(y0=-999, y1=0,
                    fillcolor="rgba(0,200,100,0.03)", line_width=0, layer="below")

        theme(fig_norm, 460,
              f"{compound} – Normalised Deg (Δ fuel-corrected vs stint start, longest clean stint)")
        fig_norm.update_layout(
            xaxis_title="Tyre Age (laps)",
            yaxis_title="Δ Fuel-corrected lap time (s)  ↓ better",
            legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1),
            annotations=[dict(
                text="Perturbed laps (yellow / SC / VSC / red) excluded",
                xref="paper", yref="paper", x=1, y=1.02,
                xanchor="right", showarrow=False,
                font=dict(size=9, color=TEXT_DIM),
            )],
        )

        _deg_info = (
            f"Data ({compound}): left bar = degradation rate (s/lap) from a linear "
            "fit on each driver's most reliable stint — the one with the highest R² "
            "(fit quality colour-coded), fuel-corrected; right line = lap-time delta "
            "from the start of each driver's longest clean stint. Perturbed laps "
            "(yellow/SC/VSC/red flags) are excluded. Why: isolates how much the tyre "
            "slows down with age — lower/flatter = better tyre management."
        )
        if fig_bar is not None:
            deg_cards.append(card(
                f"Tyre Degradation – {compound}",
                dbc.Row([
                    dbc.Col(dcc.Graph(figure=fig_bar,  config=GFX), md=5),
                    dbc.Col(dcc.Graph(figure=fig_norm, config=GFX), md=7),
                ]),
                info=_deg_info,
            ))
        else:
            deg_cards.append(card(
                f"Tyre Degradation – {compound}",
                dcc.Graph(figure=fig_norm, config=GFX),
                info=_deg_info,
            ))

    # 4. Stint Lap Inspector
    avail_drivers = sorted(fl["Driver_Short"].dropna().unique())
    first_driver  = avail_drivers[0] if avail_drivers else None

    stint_inspector = html.Div([
        html.P(
            "Select a driver then a pre-ranked stint to inspect its laps.",
            style={"color": TEXT_DIM, "fontSize": "0.8rem", "marginBottom": "10px"},
        ),
        dbc.Row([
            dbc.Col([
                html.Label("Driver",
                           style={"color": TEXT_DIM, "fontSize": "0.75rem",
                                  "letterSpacing": "1px"}),
                dcc.Dropdown(
                    id="stint-insp-driver",
                    options=[{"label": d, "value": d} for d in avail_drivers],
                    value=first_driver,
                    clearable=False,
                    style={"backgroundColor": "#111", "fontSize": "0.82rem"},
                ),
            ], md=3),
            dbc.Col([
                html.Label("Stint (ranked)",
                           style={"color": TEXT_DIM, "fontSize": "0.75rem",
                                  "letterSpacing": "1px"}),
                dcc.Dropdown(
                    id="stint-insp-key",
                    options=[],
                    value=None,
                    clearable=False,
                    style={"backgroundColor": "#111", "fontSize": "0.82rem"},
                ),
            ], md=9),
        ], className="mb-3"),
        html.Div(id="stint-insp-table"),
    ])

    tyre_usage_fig = _tyre_history_chart(fl)

    return html.Div([
        card("Lap Time Evolution – All Laps", evo_layout,
             info=("Data: every lap (valid or not) for the selected session, one line "
                   "per driver, markers tinted by compound, with track-flag periods "
                   "shaded behind (yellow / SC / VSC / red). Why: the full story of a "
                   "session — stint lengths, pit stops, degradation and how "
                   "interruptions reshaped the running order.")),
        *violin_cards,
        *deg_cards,
        card(
            "Tyre Compound Usage — Current Meeting",
            dcc.Graph(figure=tyre_usage_fig, config=GFX)
            if tyre_usage_fig.data else
            html.P("No compound data available.", style={"color": TEXT_DIM}),
            info=("Data: number of valid laps run on each compound, stacked per "
                  "session, for the currently loaded meeting. Why: shows how teams "
                  "spread their tyre allocation across the weekend and which "
                  "compounds saw real running."),
        ),
        card("Stint Lap Inspector", stint_inspector),
    ])

# ══════════════════════════════════════════════════════════════
# TAB – RACE
# ══════════════════════════════════════════════════════════════
# The Race tab is meeting-centric and self-contained: it loads the *race*
# session for the currently-selected meeting, falling back to the previous
# season's race when the current season's race hasn't happened / isn't
# available yet. It does NOT use the sidebar session/driver filters because
# the race shown may be a different season (different driver line-up) than
# what is otherwise loaded.

_RACE_DATA_CACHE: dict[tuple, dict | None] = {}   # (season, meeting) → enriched data | None


def _enrich_race_laps(data: dict) -> pd.DataFrame:
    """Run the same lap-enrichment pipeline as rebuild_state() on a single
    race session's raw frames. Returns the enriched laps frame."""
    _laps = clean_and_enrich_laps(data["laps"])
    _laps["stint_key"] = (
        _laps["Stint"].astype("string") + "_" + _laps["session_name"]
    )
    _laps = enrich_weather(_laps, data["weather"])
    _laps = enrich_track_limits(_laps, data["race_control"])
    _laps = enrich_blue_flags(_laps, data["race_control"])
    _laps = identify_quali_sim_laps(_laps)
    _laps = flag_perturbed_laps(_laps, rcm=data["race_control"])
    _laps = enrich_session_results(_laps, data["results"])
    _laps = flag_position_changes(_laps)
    return _laps


def _load_one_race(season: int, meeting: str) -> dict | None:
    """Load + enrich the Race session for (season, meeting). Returns
    {laps, stints, season, meeting} or None when no lap data is available."""
    info = [{"SEASON": str(season), "MEETING": meeting, "SESSION": "Race"}]
    try:
        data = load_sessions(info)
    except Exception as exc:           # network / FastF1 failure
        print(f"  [race] load failed {season} {meeting}: {exc}", flush=True)
        return None
    lr = data.get("laps")
    if lr is None or lr.empty:
        return None
    try:
        rl = _enrich_race_laps(data)
        rs = analyze_stints(rl)
    except Exception as exc:
        print(f"  [race] enrich failed {season} {meeting}: {exc}", flush=True)
        return None
    return {"laps": rl, "stints": rs, "season": season, "meeting": meeting}


def _resolve_race_data(season: int, meeting: str) -> dict | None:
    """Get race data for the meeting, preferring the current season and falling
    back to the previous one. Cached data is preferred over a live fetch so the
    tab stays fast and works offline. Memoized per (season, meeting)."""
    key = (int(season), meeting)
    if key in _RACE_DATA_CACHE:
        return _RACE_DATA_CACHE[key]

    candidates = [int(season), int(season) - 1]
    result: dict | None = None
    # Pass 1 – cached years only (fast, offline-safe), current season first
    for yr in candidates:
        if is_cached(str(yr), meeting, "Race"):
            result = _load_one_race(yr, meeting)
            if result:
                break
    # Pass 2 – nothing cached: attempt a live fetch, current season first
    if result is None:
        for yr in candidates:
            result = _load_one_race(yr, meeting)
            if result:
                break

    _RACE_DATA_CACHE[key] = result
    return result


def _position_changes_fig(rl: pd.DataFrame, title: str, height: int = 640) -> go.Figure:
    """Broadcast-style race position chart: each driver's on-track position by
    lap, team-coloured (teammates solid vs dashed), driver code labelled at the
    end of the line, grid position shown at lap 0, points-paying top-10 zone
    shaded, and track-flag periods banded behind. Y-axis inverted (P1 on top)."""
    fig = go.Figure()
    if rl.empty or "Position" not in rl.columns or rl["Position"].notna().sum() == 0:
        theme(fig, height, title)
        fig.add_annotation(
            text="No per-lap position data available for this race.",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(color=TEXT_DIM, size=13),
        )
        return fig

    n_laps    = int(rl["LapNo"].max())
    n_drivers = int(rl["Driver_Short"].nunique())
    y_bottom  = max(20, n_drivers) + 0.5

    # Points-paying zone (top 10)
    fig.add_hrect(y0=0.5, y1=10.5, fillcolor="rgba(0,210,190,0.05)",
                  line_width=0, layer="below")

    end_labels: list[tuple] = []   # (x, y, code, color)
    for team in sorted(rl["Team"].dropna().unique()):
        drv_team = (
            rl[rl["Team"] == team]
            .sort_values("DriverNo")["Driver_Short"].dropna().unique().tolist()
        )
        clr = TEAM_COLORS.get(team, "#808080")
        for i, drv in enumerate(drv_team):
            dv = rl[(rl["Driver_Short"] == drv) & rl["Position"].notna()] \
                .sort_values("LapNo")
            if dv.empty:
                continue
            dash = "solid" if i == 0 else "dash"
            x = dv["LapNo"].tolist()
            y = dv["Position"].tolist()
            # Prepend starting grid slot at lap 0 so the start is visible
            grid = dv["Grid_Position"].iloc[0] if "Grid_Position" in dv.columns else np.nan
            if pd.notna(grid) and grid > 0:
                x = [0] + x
                y = [float(grid)] + y
            fig.add_trace(go.Scatter(
                x=x, y=y, mode="lines", name=drv,
                line=dict(color=clr, width=2.2, dash=dash),
                hovertemplate=(
                    f"<b>{drv}</b> · {team}<br>"
                    "Lap %{x}  →  P%{y}<extra></extra>"
                ),
                showlegend=False,
            ))
            end_labels.append((x[-1], y[-1], drv, clr))

    # Track-flag bands (SC / VSC / yellow / red) behind the lines
    _add_flag_bands(fig, rl)
    _add_rain_bands(fig, rl)

    theme(fig, height, title)

    # Driver-code labels at the end of each line (replaces a crowded legend)
    for xe, ye, drv, clr in end_labels:
        fig.add_annotation(
            x=xe, y=ye, text=f"  {drv}", showarrow=False, xanchor="left",
            font=dict(size=10, color=clr, family="Inter, sans-serif"),
        )
    fig.add_annotation(
        x=0.0, y=10.5, xref="x", yref="y", text="points ▲", showarrow=False,
        xanchor="left", yanchor="bottom",
        font=dict(size=9, color="#00D2BE"),
    )

    fig.update_layout(
        showlegend=False,
        xaxis=dict(title="Lap", range=[-1.5, n_laps + 3.5],
                   gridcolor=GRID_CLR, zeroline=False),
        yaxis=dict(title="Position", range=[y_bottom, 0.5],
                   tickvals=[1, 5, 10, 15, 20],
                   gridcolor=GRID_CLR, zeroline=False),
    )
    return fig


def _weather_race_fig(rl: pd.DataFrame, title: str, height: int = 480) -> go.Figure:
    """Lap-aligned weather strip for a race: track & air temperature (with rain
    periods shaded) stacked directly above the field's median lap pace, sharing
    the lap x-axis so conditions can be read straight down onto their effect on
    pace. Returns an empty Figure when no usable weather data is present."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.55, 0.45], vertical_spacing=0.07,
    )

    has_temp = any(
        c in rl.columns and rl[c].notna().any() for c in ("TrackTemp", "AirTemp")
    )
    if rl.empty or "LapNo" not in rl.columns or not has_temp:
        return go.Figure()

    # ── Per-lap weather (one value per lap, averaged across cars on track) ──
    agg: dict[str, tuple] = {}
    for col, how in (("TrackTemp", "mean"), ("AirTemp", "mean"),
                     ("Humidity", "mean"), ("WindSpeed", "mean"),
                     ("Rainfall", "max")):
        if col in rl.columns:
            agg[col] = (col, how)
    per_lap = rl.groupby("LapNo").agg(**agg).reset_index().sort_values("LapNo")

    # ── Field pace per lap (median of racing laps; spikes show SC/rain) ──
    racing = rl[~rl.get("PitLap", False) & rl["LapTime_s"].notna()
                & (rl["LapTime_s"] > 0)]
    pace = (racing.groupby("LapNo")["LapTime_s"].median().reset_index()
            .sort_values("LapNo")) if not racing.empty else pd.DataFrame()

    # ── Row 1: temperatures ──────────────────────────────────
    if "TrackTemp" in per_lap.columns:
        fig.add_trace(go.Scatter(
            x=per_lap["LapNo"], y=per_lap["TrackTemp"], mode="lines",
            name="Track temp", line=dict(color="#FF8700", width=2.2),
            hovertemplate="Lap %{x}<br>Track %{y:.1f} °C<extra></extra>",
        ), row=1, col=1)
    if "AirTemp" in per_lap.columns:
        fig.add_trace(go.Scatter(
            x=per_lap["LapNo"], y=per_lap["AirTemp"], mode="lines",
            name="Air temp", line=dict(color="#00D2BE", width=2.0, dash="dot"),
            hovertemplate="Lap %{x}<br>Air %{y:.1f} °C<extra></extra>",
        ), row=1, col=1)

    # ── Row 2: field pace ────────────────────────────────────
    if not pace.empty:
        fig.add_trace(go.Scatter(
            x=pace["LapNo"], y=pace["LapTime_s"], mode="lines",
            name="Field median lap", line=dict(color=TEXT_MAIN, width=1.8),
            hovertemplate="Lap %{x}<br>Median %{y:.3f} s<extra></extra>",
        ), row=2, col=1)

    # ── Rain bands across both rows ──────────────────────────
    rain_groups = _rain_lap_groups(per_lap)
    for i, (start, end) in enumerate(rain_groups):
        for r in (1, 2):
            fig.add_vrect(
                x0=start - 0.5, x1=end + 0.5,
                fillcolor="rgba(0,120,255,0.12)", line_width=0, layer="below",
                annotation_text=("\U0001f327 rain" if (i == 0 and r == 1) else ""),
                annotation_position="top left",
                annotation_font=dict(size=9, color="#4DA3FF"),
                row=r, col=1,
            )

    theme(fig, height, title)
    fig.update_yaxes(title_text="Temp (°C)", row=1, col=1)
    fig.update_yaxes(title_text="Lap Time (s)", row=2, col=1)
    fig.update_xaxes(title_text="Lap Number", row=2, col=1)
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="left", x=0, bgcolor="rgba(0,0,0,0)",
                    bordercolor=GRID_CLR, borderwidth=1),
    )
    return fig


def tab_race(sel_drivers=None, sel_teams=None):
    cur = LOADED_SESSION_INFO[0] if LOADED_SESSION_INFO else None
    if not cur:
        return html.P("No meeting loaded — pick a session in the Data tab.",
                      style={"color": TEXT_DIM})

    season  = int(cur["SEASON"])
    meeting = cur["MEETING"]
    data    = _resolve_race_data(season, meeting)

    if data is None:
        return html.Div([
            html.H3(f"{meeting}", style={"color": TEXT_MAIN, "fontWeight": "800"}),
            html.P(
                f"No race data is available for {meeting} in {season} or {season - 1} "
                "(neither cached locally nor fetchable). Load the race in the Data tab.",
                style={"color": TEXT_DIM, "fontSize": "0.9rem"},
            ),
        ])

    rl          = data["laps"]
    shown_year  = data["season"]
    is_fallback = shown_year != season

    # ── Sidebar filters: only Driver and Team apply to the Race tab ──
    # Apply a filter only when the user has actually narrowed it. A full
    # selection is treated as "no filter" so a fallback season (whose team
    # names / line-up may differ from the loaded one) still shows the whole
    # grid instead of silently dropping drivers on stale team names.
    if sel_teams and set(sel_teams) != set(TEAMS):
        rl = rl[rl["Team"].isin(sel_teams)]
    if sel_drivers and set(sel_drivers) != set(DRIVERS):
        rl = rl[rl["Driver_Short"].isin(sel_drivers)]

    # ── Year banner (makes the displayed season unmistakable) ──
    banner_bits = [
        html.Span("RACE", style={
            "background": ACCENT, "color": "#fff", "borderRadius": "4px",
            "padding": "3px 10px", "fontWeight": "800", "letterSpacing": "2px",
            "fontSize": "0.8rem", "marginRight": "12px",
        }),
        html.Span(f"{meeting}", style={
            "color": TEXT_MAIN, "fontWeight": "800", "fontSize": "1.15rem",
            "marginRight": "10px",
        }),
        html.Span(str(shown_year), style={
            "color": "#fff", "background": "#005AFF" if not is_fallback else "#B8860B",
            "borderRadius": "4px", "padding": "3px 12px", "fontWeight": "800",
            "fontSize": "1.0rem", "letterSpacing": "1px",
        }),
    ]
    if is_fallback:
        banner_bits.append(html.Span(
            f"  ⚠  {season} race not available yet — showing {shown_year} data",
            style={"color": "#E0B040", "fontSize": "0.8rem", "marginLeft": "12px",
                   "fontStyle": "italic"},
        ))
    banner = html.Div(
        banner_bits,
        style={"display": "flex", "alignItems": "center", "flexWrap": "wrap",
               "padding": "12px 16px", "marginBottom": "18px",
               "background": CARD_BG, "border": f"1px solid {GRID_CLR}",
               "borderLeft": f"4px solid {ACCENT}", "borderRadius": "8px"},
    )

    if rl.empty:
        return html.Div([
            banner,
            html.P("No race laps match the current Driver / Team filter "
                   "(note: a fallback season may have a different line-up).",
                   style={"color": TEXT_DIM, "fontSize": "0.9rem"}),
        ])

    evo_fig = _lap_evolution_fig(
        rl, f"Lap Time Evolution – All Laps – Race {shown_year}"
    )
    pos_fig = _position_changes_fig(
        rl, f"Race Position by Lap – {meeting} {shown_year}"
    )
    strat_fig = _tyre_strategy_chart(
        rl, title=f"Race Tyre Strategy – {meeting} {shown_year}",
        already_race=True,
    )
    wx_fig = _weather_race_fig(
        rl, f"Weather & Race Pace – {meeting} {shown_year}"
    )

    return html.Div([
        banner,
        card(
            "Lap Time Evolution – All Laps (Race)",
            dcc.Graph(figure=evo_fig, config=GFX),
            info=("Data: every race lap (valid or not), one line per driver, markers "
                  "tinted by compound, with track-flag periods shaded behind (yellow / "
                  "SC / VSC / red). Why: the full story of the race — stint lengths, pit "
                  "stops, degradation and how interruptions reshaped the pace."),
        ),
        card(
            "Position Changes During the Race",
            dcc.Graph(figure=pos_fig, config=GFX),
            info=("Data: each driver's on-track position at every lap (grid slot shown "
                  "at lap 0), team-coloured with teammates split solid/dashed, driver "
                  "code labelled at the line end. The shaded band marks the points-paying "
                  "top 10; flag periods are banded behind. Why: shows overtakes, pit-stop "
                  "shuffles and Safety-Car bunching at a glance."),
        ),
        card(
            "Race Tyre Strategy",
            dcc.Graph(figure=strat_fig, config=GFX)
            if strat_fig.data else
            html.P("No stint data available for this race.", style={"color": TEXT_DIM}),
            info=("Data: each driver's stints, one bar split into compound-coloured "
                  "segments sized by stint length (laps), ordered by finishing position; "
                  "diamonds mark pit stops and show pit-lane time (s). Why: the strategic "
                  "shape of the race — who ran which tyres, stint lengths and stop timing."),
        ),
        card(
            "Weather & Race Pace",
            dcc.Graph(figure=wx_fig, config=GFX)
            if wx_fig.data else
            html.P("No weather data available for this race.", style={"color": TEXT_DIM}),
            info=("Data: track and air temperature per lap (averaged across cars), "
                  "stacked above the field's median lap time, on a shared lap axis; "
                  "rain periods are shaded blue. Why: reading conditions straight down "
                  "onto pace shows how the weather shaped the race — a cooling track, "
                  "a rain shower or the grip swing that triggered the pit cascade."),
        ),
    ])

# ══════════════════════════════════════════════════════════════
# TAB 7 – TEAMMATE COMPARISON
# ══════════════════════════════════════════════════════════════

def tab_teammates(fl, fs):
    """
    Head-to-head teammate comparison across multiple performance dimensions.
    Wrapped in a top-level try/except so any crash shows in the UI rather
    than killing the Dash server callback.
    """
    try:
        return _tab_teammates_inner(fl, fs)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        return html.Div([
            dbc.Alert(
                [html.B("Teammate tab error: "), str(exc)],
                color="danger", style={"fontSize": "0.82rem"},
            ),
            html.Pre(tb, style={
                "color": TEXT_DIM, "fontSize": "0.7rem",
                "background": "#09091A", "padding": "12px",
                "borderRadius": "6px", "overflowX": "auto",
            }),
        ])


def _hex_to_rgba(hex_color: str, alpha: float = 1.0) -> str:
    """Convert a '#RRGGBB' hex string to 'rgba(r,g,b,a)' for Plotly."""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    else:
        r, g, b = 128, 128, 128
    return f"rgba({r},{g},{b},{alpha})"


def _tab_teammates_inner(fl, fs):

    # ── 0. Pools & session-type detection ────────────────────
    sess_names = fl["session_name"].unique().tolist()
    race_sess  = [s for s in sess_names
                  if (s.startswith("Race") or s.startswith("Sprint"))
                  and "Qualifying" not in s]
    quali_sess = [s for s in sess_names if "Qualifying" in s]
    has_race   = bool(race_sess)
    has_quali  = bool(quali_sess)

    v         = fl[fl["ValidLap"]].copy()
    _pert     = (fl["Perturbed_Lap"] if "Perturbed_Lap" in fl.columns
                 else pd.Series(False, index=fl.index))
    v_clean   = fl[fl["ValidLap"] & ~_pert].copy()
    v_race    = v_clean[v_clean["session_name"].isin(race_sess)] if has_race  else pd.DataFrame()
    v_quali   = v[v["session_name"].isin(quali_sess)]            if has_quali else pd.DataFrame()

    # ── 1. Build teammate pairs (alphabetical within team) ───
    pairs: dict[str, list[str]] = {}
    for team, grp in v.groupby("Team"):
        if team in ("Unknown", ""):
            continue
        drvs = sorted(grp["Driver_Short"].dropna().unique().tolist())
        if len(drvs) >= 2:
            pairs[team] = drvs[:2]

    if not pairs:
        return html.P(
            "No complete teammate pairs in current filter — widen driver / team selection.",
            style={"color": TEXT_DIM},
        )
    # Order teams by current championship standing (leader first). This flows into
    # the scoreboard cards and every head-to-head gap chart, which otherwise had no
    # inherently meaningful team order (they were alphabetical).
    teams_sorted = _order_teams_by_champ(pairs.keys())

    # ── 2. Generic metric helpers ─────────────────────────────

    def _val(pool: pd.DataFrame, driver: str, agg_fn) -> float:
        sub = pool[pool["Driver_Short"] == driver]
        if sub.empty:
            return float("nan")
        try:
            return float(agg_fn(sub))
        except Exception:
            return float("nan")

    def _metric_rows(pool: pd.DataFrame, agg_fn) -> list[dict]:
        rows = []
        for team in teams_sorted:
            if team not in pairs:
                continue
            drv_a, drv_b = pairs[team]
            va, vb = _val(pool, drv_a, agg_fn), _val(pool, drv_b, agg_fn)
            if not (np.isnan(va) and np.isnan(vb)):
                rows.append(dict(team=team, drv_a=drv_a, drv_b=drv_b,
                                 val_a=va, val_b=vb))
        return rows

    # ── 3. Chart builders ─────────────────────────────────────

    def _gap_chart(rows: list[dict], title: str, xlabel: str,
                   fmt_fn=None, lower_is_better: bool = True,
                   note: str = "", unit: str = "") -> go.Figure:
        """
        One horizontal bar per team, coloured by TEAM_COLORS.
        Bar extends LEFT when Driver A wins, RIGHT when Driver B wins.
        Text inside the bar: ★ DrvA  val_a | val_b  DrvB ★
        """
        rows = [r for r in rows
                if not (np.isnan(r["val_a"]) and np.isnan(r["val_b"]))]
        if not rows:
            return go.Figure()

        fmt_fn = fmt_fn or (lambda v: f"{v:.3f}")

        raw_gaps = [
            (r["val_a"] - r["val_b"])
            if not (np.isnan(r["val_a"]) or np.isnan(r["val_b"])) else 0.0
            for r in rows
        ]
        disp_gaps = [g if lower_is_better else -g for g in raw_gaps]
        # Team color for bar fill; winner side indicated by direction
        bar_colors = [TEAM_COLORS.get(r["team"], "#808080") for r in rows]

        bar_texts, hover_data = [], []
        for r, dg in zip(rows, disp_gaps):
            va_s = fmt_fn(r["val_a"]) if not np.isnan(r["val_a"]) else "—"
            vb_s = fmt_fn(r["val_b"]) if not np.isnan(r["val_b"]) else "—"
            gap_s = (
                f"{abs(r['val_a'] - r['val_b']):.3f} {unit}"
                if not (np.isnan(r["val_a"]) or np.isnan(r["val_b"])) else "—"
            )
            w_a = "★ " if dg <= 0 else ""
            w_b = " ★" if dg >  0 else ""
            bar_texts.append(f"{w_a}{r['drv_a']}  {va_s}  |  {vb_s}  {r['drv_b']}{w_b}")
            hover_data.append([r["drv_a"], va_s, r["drv_b"], vb_s, gap_s])

        fig = go.Figure(go.Bar(
            y=[r["team"] for r in rows],
            x=disp_gaps,
            orientation="h",
            marker=dict(color=bar_colors, line=dict(color=GRID_CLR, width=0.8)),
            text=bar_texts,
            textposition="auto",
            textfont=dict(size=10, color="#fff"),
            customdata=hover_data,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "%{customdata[0]}: <b>%{customdata[1]}</b><br>"
                "%{customdata[2]}: <b>%{customdata[3]}</b><br>"
                "Gap: %{customdata[4]}"
                "<extra></extra>"
            ),
        ))
        fig.add_vline(x=0, line=dict(color=TEXT_MAIN, width=1.5))
        theme(fig, max(220, len(rows) * 58 + 130), title)
        fig.update_layout(
            xaxis_title=xlabel,
            bargap=0.35,
            showlegend=False,
            margin=dict(l=160, r=20, t=70, b=55),
        )
        fig.add_annotation(
            text=(
                "◀ left driver faster / better  ·  right driver faster / better ▶"
            ),
            xref="paper", yref="paper", x=0.5, y=1.07,
            xanchor="center", showarrow=False,
            font=dict(size=9, color=TEXT_DIM),
        )
        if note:
            fig.add_annotation(
                text=note, xref="paper", yref="paper",
                x=1.0, y=-0.16, xanchor="right", showarrow=False,
                font=dict(size=9, color=TEXT_DIM),
            )
        # rows arrive in championship order (leader first) → show leader on top
        fig.update_yaxes(autorange="reversed")
        return fig

    # Butterfly removed — all charts now use the same diverging gap style.
    # For "higher is better" metrics (laps, overtakes) lower_is_better=False
    # so the bar extends LEFT when Driver A has the higher value.

    # ── 4. Win counter ────────────────────────────────────────

    def _wins(va, vb, lower_is_better=True):
        if np.isnan(va) or np.isnan(vb):
            return 0, 0
        return (1, 0) if (va < vb if lower_is_better else va > vb) else (0, 1)

    # ══════════════════════════════════════════════════════════
    # COMPUTE ALL METRICS
    # ══════════════════════════════════════════════════════════

    # ── Race pace per compound ────────────────────────────────
    # Use the best valid stint per driver × compound across ALL sessions
    # (same logic as Stints tab: Stint_Rank_Across_Sessions = 1).
    # Falls back to all clean valid laps for that driver × compound if
    # stints_df is unavailable.
    pace_rows: dict[str, list[dict]] = {}
    for cmp in COMPOUNDS:
        cmp_rows: list[dict] = []
        for team in teams_sorted:
            if team not in pairs:
                continue
            drv_a, drv_b = pairs[team]

            def _best_stint_median(driver: str, compound: str) -> float:
                # Try to find the best valid stint from analyze_stints
                if fs is not None and not fs.empty and "Stint_Rank_Across_Sessions" in fs.columns:
                    best = fs[
                        (fs["Driver_Short"] == driver)
                        & (fs["Compound"] == compound)
                        & fs["Valid_Stint"]
                        & (fs["Stint_Rank_Across_Sessions"] == 1)
                    ]
                    if not best.empty and "Stint_FuelCorr" in best.columns:
                        v_ = pd.to_numeric(best["Stint_FuelCorr"], errors="coerce").dropna()
                        if not v_.empty:
                            return float(v_.iloc[0])
                # Fallback: trimmed median of fuel-corrected laps
                sub = v_clean[
                    (v_clean["Driver_Short"] == driver)
                    & (v_clean["Compound"] == compound)
                    & v_clean["LapTime_FuelCorrected"].notna()
                ]
                if sub.empty:
                    return float("nan")
                t = sub["LapTime_FuelCorrected"]
                lo, hi = t.quantile(0.10), t.quantile(0.90)
                trimmed = t[t.between(lo, hi)]
                return float(trimmed.median() if not trimmed.empty else t.median())

            va = _best_stint_median(drv_a, cmp)
            vb = _best_stint_median(drv_b, cmp)
            if not (np.isnan(va) and np.isnan(vb)):
                cmp_rows.append(dict(team=team, drv_a=drv_a, drv_b=drv_b,
                                     val_a=va, val_b=vb))
        if cmp_rows:
            pace_rows[cmp] = cmp_rows

    # ── Quali sim / single-lap pace ───────────────────────────
    # Best quali-sim lap across ALL sessions (not just quali sessions).
    # Falls back to best valid lap if Is_Quali_Sim is absent.
    if "Is_Quali_Sim" in fl.columns and fl["Is_Quali_Sim"].any():
        qs_pool  = fl[fl["ValidLap"] & (fl["Is_Quali_Sim"] == True)]
        qs_label = "Quali Sim Best Lap (all sessions)"
    else:
        qs_pool  = v
        qs_label = "Best Valid Lap (no Is_Quali_Sim)"
    qs_rows = _metric_rows(qs_pool, lambda s: s["LapTime_s"].min()) if not qs_pool.empty else []

    # Total valid laps
    laps_rows = _metric_rows(v, lambda s: float(len(s)))

    # Consistency — IQR/Median × 100 (lower = better)
    def _consistency(s: pd.DataFrame) -> float:
        t = s["LapTime_s"].dropna()
        if len(t) < 4:
            return float("nan")
        q25, q75, med = t.quantile(0.25), t.quantile(0.75), t.median()
        return (q75 - q25) / med * 100.0 if med > 0 else float("nan")
    cons_rows = _metric_rows(v_clean, _consistency)

    # Average pit stop duration (race/sprint only)
    pit_rows: list[dict] = []
    if has_race:
        _race_all = fl[fl["session_name"].isin(race_sess)].sort_values(
            ["session_name", "DriverNo", "LapNo"]
        )
        _pit_data: list[dict] = []
        for (sess, drv_no), grp in _race_all.groupby(["session_name", "DriverNo"]):
            grp_s   = grp.sort_values("LapNo")
            in_laps = grp_s[grp_s["InLap"]  & grp_s["PitIn"].notna()]
            out_laps = grp_s[grp_s["OutLap"] & grp_s["PitOut"].notna()]
            # Build a dict LapNo → first PitOut value (avoid duplicate-index issue)
            out_dict = {}
            for _, orow in out_laps.iterrows():
                ln = int(orow["LapNo"])
                if ln not in out_dict:
                    out_dict[ln] = float(orow["PitOut"])
            for _, inrow in in_laps.iterrows():
                nxt = int(inrow["LapNo"]) + 1
                try:
                    pit_in_s = float(inrow["PitIn"])
                    if nxt in out_dict and np.isfinite(pit_in_s) and np.isfinite(out_dict[nxt]):
                        dur = out_dict[nxt] - pit_in_s
                        if 1.5 < dur < 65.0:
                            _pit_data.append({
                                "Driver_Short": inrow["Driver_Short"],
                                "Team":         inrow["Team"],
                                "dur":          dur,
                            })
                except Exception:
                    pass
        if _pit_data:
            _pit_df  = pd.DataFrame(_pit_data)
            pit_rows = _metric_rows(_pit_df, lambda s: s["dur"].mean())

    # Race finish position & positions gained
    finish_rows: list[dict] = []
    pgain_rows:  list[dict] = []
    if has_race and "Classified_Position" in fl.columns:
        _rr_base = fl[fl["session_name"].isin(race_sess)].copy()
        # Convert to numeric safely (handles "DNF", "DSQ", etc.)
        _rr_base["_fin_num"]  = pd.to_numeric(_rr_base["Classified_Position"], errors="coerce")
        _rr_base["_grid_num"] = pd.to_numeric(
            _rr_base.get("Grid_Position", pd.Series(dtype=float)), errors="coerce"
        ) if "Grid_Position" in _rr_base.columns else np.nan
        _rr = (
            _rr_base.groupby("Driver_Short")
            .agg(
                Team      =("Team",       "first"),
                Finish_num=("_fin_num",   "first"),
                Grid_num  =("_grid_num",  "first"),
            )
            .reset_index()
        )
        _rr["Gained"] = _rr["Grid_num"] - _rr["Finish_num"]

        def _rr_rows(val_col):
            out = []
            for team in teams_sorted:
                if team not in pairs:
                    continue
                drv_a, drv_b = pairs[team]
                sa = _rr[_rr["Driver_Short"] == drv_a]
                sb = _rr[_rr["Driver_Short"] == drv_b]
                if sa.empty and sb.empty:
                    continue
                va = float(sa[val_col].iloc[0]) if (not sa.empty and sa[val_col].notna().any()) else float("nan")
                vb = float(sb[val_col].iloc[0]) if (not sb.empty and sb[val_col].notna().any()) else float("nan")
                out.append(dict(team=team, drv_a=drv_a, drv_b=drv_b, val_a=va, val_b=vb))
            return out

        finish_rows = _rr_rows("Finish_num")
        pgain_rows  = _rr_rows("Gained")

    # Overtakes (race/sprint only; requires flag_position_changes)
    overtake_rows: list[dict] = []
    if has_race and "Overtook" in fl.columns:
        _ov_pool  = fl[fl["session_name"].isin(race_sess)]
        overtake_rows = _metric_rows(_ov_pool, lambda s: float(s["Overtook"].sum()))

    # Championship points (sum across all race/sprint sessions in filter)
    # Race_Points is repeated on every lap row — deduplicate to one value
    # per driver × session before summing, then aggregate across sessions.
    champ_rows: list[dict] = []
    if has_race and "Race_Points" in fl.columns:
        _pts_dedup = (
            fl[fl["session_name"].isin(race_sess)]
            .groupby(["session_name", "Driver_Short", "Team"])["Race_Points"]
            .first()                                          # one value per session
            .reset_index()
        )
        _pts_dedup["Race_Points"] = pd.to_numeric(_pts_dedup["Race_Points"], errors="coerce")
        _pts_pool = (
            _pts_dedup
            .groupby(["Driver_Short", "Team"])["Race_Points"]
            .sum()
            .reset_index(name="pts")
        )
        for team in teams_sorted:
            if team not in pairs:
                continue
            drv_a, drv_b = pairs[team]
            ra = _pts_pool[_pts_pool["Driver_Short"] == drv_a]
            rb = _pts_pool[_pts_pool["Driver_Short"] == drv_b]
            va = float(ra["pts"].iloc[0]) if not ra.empty else float("nan")
            vb = float(rb["pts"].iloc[0]) if not rb.empty else float("nan")
            if not (np.isnan(va) and np.isnan(vb)):
                champ_rows.append(dict(team=team, drv_a=drv_a, drv_b=drv_b,
                                       val_a=va, val_b=vb))

    # Qualifying best time (Q3 → Q2 → Q1 cascade from results, else best lap in quali)
    quali_time_rows: list[dict] = []
    if has_quali:
        q_cols_avail = [c for c in ("Q3_s", "Q2_s", "Q1_s") if c in fl.columns]
        if q_cols_avail:
            _q_pool = fl[fl["session_name"].isin(quali_sess)]
            for team in teams_sorted:
                if team not in pairs:
                    continue
                drv_a, drv_b = pairs[team]
                def _best_q_time(driver):
                    sub = _q_pool[_q_pool["Driver_Short"] == driver]
                    if sub.empty:
                        return float("nan")
                    for qc in q_cols_avail:
                        v_ = pd.to_numeric(sub[qc], errors="coerce").dropna()
                        if not v_.empty:
                            return float(v_.iloc[0])
                    return float("nan")
                va, vb = _best_q_time(drv_a), _best_q_time(drv_b)
                if not (np.isnan(va) and np.isnan(vb)):
                    quali_time_rows.append(
                        dict(team=team, drv_a=drv_a, drv_b=drv_b, val_a=va, val_b=vb)
                    )
        if not quali_time_rows and not v_quali.empty:
            quali_time_rows = _metric_rows(v_quali, lambda s: s["LapTime_s"].min())

    # ══════════════════════════════════════════════════════════
    # SCOREBOARD  — tally wins per team
    # ══════════════════════════════════════════════════════════

    def _get_vals(rows_list, team):
        for r in rows_list:
            if r["team"] == team:
                return r["val_a"], r["val_b"]
        return float("nan"), float("nan")

    sb_items = []
    for team in teams_sorted:
        if team not in pairs:
            continue
        drv_a, drv_b = pairs[team]
        score_a, score_b = 0, 0
        metric_pills_data = []

        all_metrics_def = [
            *[(f"Pace {c}",   pace_rows.get(c, []),   True,  format_lap_time)
              for c in COMPOUNDS if c in pace_rows],
            (qs_label,        qs_rows,                 True,  format_lap_time),
            ("Consistency",   cons_rows,               True,  lambda v: f"{v:.2f}%"),
            ("Total Laps",    laps_rows,               False, lambda v: str(int(v)) if not np.isnan(v) else "—"),
            *([("Avg Pit Stop",  pit_rows,      True,  lambda v: f"{v:.2f}s")] if pit_rows  else []),
            *([("Race Finish",   finish_rows,   True,  lambda v: f"P{int(v)}"  if not np.isnan(v) else "—")] if finish_rows  else []),
            *([("Pos. Gained",   pgain_rows,    False, lambda v: (f"+{int(v)}" if v > 0 else str(int(v))) if not np.isnan(v) else "—")] if pgain_rows   else []),
            *([("Overtakes",     overtake_rows, False, lambda v: str(int(v))   if not np.isnan(v) else "—")] if overtake_rows else []),
            *([("Champ. Pts",    champ_rows,    False, lambda v: f"{int(v)} pts" if not np.isnan(v) else "—")] if champ_rows    else []),
            *([("Quali Time",    quali_time_rows, True, format_lap_time)] if quali_time_rows else []),
        ]

        for label, rows_list, lib, fmt in all_metrics_def:
            va, vb = _get_vals(rows_list, team)
            wa, wb = _wins(va, vb, lower_is_better=lib)
            score_a += wa; score_b += wb
            try:
                a_str = fmt(va) if not np.isnan(va) else "—"
                b_str = fmt(vb) if not np.isnan(vb) else "—"
            except Exception:
                a_str = "—"; b_str = "—"
            winner = drv_a if wa else (drv_b if wb else None)
            metric_pills_data.append((label, a_str, b_str, winner))

        clr   = TEAM_COLORS.get(team, "#808080")
        total = max(score_a + score_b, 1)
        pct_a = score_a / total * 100

        # Progress bar
        bar_el = html.Div(
            html.Div([
                html.Div(style={
                    "width": f"{pct_a:.1f}%", "height": "100%",
                    "background": "#00D2BE", "display": "inline-block",
                    "borderRadius": "3px 0 0 3px" if pct_a > 0 and pct_a < 100 else "3px",
                }),
                html.Div(style={
                    "width": f"{100 - pct_a:.1f}%", "height": "100%",
                    "background": "#FF8700", "display": "inline-block",
                    "borderRadius": "0 3px 3px 0" if pct_a > 0 and pct_a < 100 else "3px",
                }),
            ], style={"display": "flex", "height": "100%"}),
            style={"height": "7px", "borderRadius": "4px", "margin": "6px 0",
                   "background": GRID_CLR},
        )

        # Metric detail pills
        pills = []
        for label, a_str, b_str, winner in metric_pills_data:
            bg = "#00D2BE" if winner == drv_a else ("#FF8700" if winner == drv_b else "#333")
            pills.append(html.Span(
                f"{label}: {a_str} | {b_str}",
                style={
                    "background": bg + "28",
                    "border": f"1px solid {bg}",
                    "borderRadius": "3px", "padding": "2px 7px",
                    "fontSize": "0.68rem", "marginRight": "5px",
                    "marginBottom": "4px", "display": "inline-block",
                    "color": TEXT_MAIN,
                },
                title=f"Winner: {winner or '—'}",
            ))

        sb_items.append(dbc.Col(
            dbc.Card(dbc.CardBody([
                html.Div([
                    html.Span("● ", style={"color": clr, "fontSize": "1.1rem"}),
                    html.Span(team, style={
                        "fontWeight": "700", "fontSize": "0.88rem",
                        "color": TEXT_MAIN, "letterSpacing": "0.5px",
                    }),
                ]),
                html.Div([
                    html.Span(drv_a, style={
                        "color": "#00D2BE", "fontWeight": "800", "fontSize": "1.25rem",
                    }),
                    html.Span(f"  {score_a} – {score_b}  ", style={
                        "color": TEXT_DIM, "fontSize": "0.95rem", "fontWeight": "600",
                    }),
                    html.Span(drv_b, style={
                        "color": "#FF8700", "fontWeight": "800", "fontSize": "1.25rem",
                    }),
                ], style={"margin": "5px 0"}),
                bar_el,
                html.Div(pills, style={"marginTop": "8px", "lineHeight": "2.0"}),
            ]), style={
                "background": CARD_BG,
                "border": f"1px solid {_hex_to_rgba(clr, 0.27)}",
                "borderRadius": "8px",
            }),
            md=6, lg=4, className="mb-3",
        ))

    scoreboard = card(
        html.Span([
            "Head-to-Head Scoreboard",
            html.Span(
                " — drivers sorted alphabetically within each team (teal = A, orange = B)",
                style={"color": TEXT_DIM, "fontWeight": "400",
                       "fontSize": "0.75rem", "marginLeft": "8px"},
            ),
        ]),
        dbc.Row(sb_items),
        info=("Data: for each team, the two teammates are compared across every "
              "metric below (pace per compound, quali, consistency, laps, pit stops, "
              "finish, positions gained, overtakes, points). Each metric counts as one "
              "'win'; the score and bar tally those wins. Why: the fairest way to rate "
              "drivers — against the one person in identical machinery."),
    )

    # ══════════════════════════════════════════════════════════
    # SECTION: RACE PACE PER COMPOUND
    # ══════════════════════════════════════════════════════════
    pace_col_items = []
    if pace_rows:
        n_cmp = len(pace_rows)
        col_w = 12 if n_cmp == 1 else 6 if n_cmp == 2 else 4
        for cmp, rows_ in pace_rows.items():
            fig = _gap_chart(
                rows_,
                title=f"Race Pace – {cmp}",
                xlabel="Gap (s)  ·  negative = left driver faster",
                fmt_fn=format_lap_time,
                lower_is_better=True,
                note="Stint_FuelCorr (fuel-corrected trimmed median) of best valid stint across all sessions. Falls back to trimmed median of fuel-corrected laps.",
                unit="s",
            )
            pace_col_items.append(dbc.Col(card(
                html.Span([
                    "Race Pace – ",
                    html.Span(cmp, style={
                        "color": COMPOUND_COLORS.get(cmp, "#fff"),
                        "fontWeight": "800",
                    }),
                ]),
                dcc.Graph(figure=fig, config=GFX),
            ), md=col_w))
    else:
        pace_col_items = [dbc.Col(html.P(
            "No race / sprint race sessions in current selection.",
            style={"color": TEXT_DIM, "fontStyle": "italic"},
        ), md=12)]

    race_pace_section = card(
        html.Span([
            "Race Pace by Compound",
            html.Span(" — best valid stint per driver × compound across all sessions",
                      style={"color": TEXT_DIM, "fontWeight": "400",
                             "fontSize": "0.75rem", "marginLeft": "8px"}),
        ]),
        dbc.Row(pace_col_items),
        info=("Data: each teammate's fuel-corrected pace on their best valid stint per "
              "compound (all sessions). One diverging bar per team — it points left "
              "when the left/teal driver is faster, right when the right/orange driver "
              "is. Why: compares teammates on equal tyres, the cleanest race-pace duel."),
    )

    # ══════════════════════════════════════════════════════════
    # SECTION: CONSISTENCY + TOTAL LAPS
    # ══════════════════════════════════════════════════════════
    cons_fig = _gap_chart(
        cons_rows,
        title="Consistency — IQR / Median × 100%",
        xlabel="Gap (%)  ·  negative = left driver more consistent",
        fmt_fn=lambda v: f"{v:.2f}%",
        lower_is_better=True,
        note="Valid non-perturbed laps. IQR = P75 − P25 of lap-time distribution. Lower % = tighter.",
        unit="%",
    )
    laps_fig = _gap_chart(
        laps_rows,
        title="Total Valid Laps  (all sessions)",
        xlabel="Gap (laps)  ·  negative = left driver ran more laps",
        fmt_fn=lambda v: str(int(v)) if not np.isnan(v) else "—",
        lower_is_better=False,
        note="ValidLap=True count across all sessions in current filter.",
        unit="laps",
    )
    consistency_section = card(
        "Consistency & Volume",
        dbc.Row([
            dbc.Col(dcc.Graph(figure=cons_fig, config=GFX), md=7),
            dbc.Col(dcc.Graph(figure=laps_fig, config=GFX), md=5),
        ]),
        info=("Data: left = lap-time consistency (IQR ÷ median × 100 of valid "
              "non-perturbed laps; lower = tighter, more repeatable); right = total "
              "valid laps each teammate ran. Why: consistency is a key driver skill, "
              "and lap volume tells you how solid the comparison is."),
    )

    # ══════════════════════════════════════════════════════════
    # SECTION: QUALIFYING (conditional)
    # ══════════════════════════════════════════════════════════
    quali_col_items = []
    if has_quali:
        if qs_rows:
            qs_fig = _gap_chart(
                qs_rows,
                title=qs_label,
                xlabel="Gap (s)  ·  negative = left driver faster",
                fmt_fn=format_lap_time,
                lower_is_better=True,
                note=(
                    "Lap within 0.5% of personal best on tyre age ≤ 4."
                    if "Is_Quali_Sim" in fl.columns and fl["Is_Quali_Sim"].any()
                    else "Is_Quali_Sim absent — best valid lap used."
                ),
                unit="s",
            )
            quali_col_items.append(
                dbc.Col(card(qs_label, dcc.Graph(figure=qs_fig, config=GFX)), md=6)
            )
        if quali_time_rows:
            qt_fig = _gap_chart(
                quali_time_rows,
                title="Qualifying Classification Time",
                xlabel="Gap (s)  ·  negative = left driver faster",
                fmt_fn=format_lap_time,
                lower_is_better=True,
                note="Best of Q3 / Q2 / Q1 from session results (enrich_session_results).",
                unit="s",
            )
            quali_col_items.append(
                dbc.Col(card("Qualifying Classification Time", dcc.Graph(figure=qt_fig, config=GFX)), md=6)
            )

    # ══════════════════════════════════════════════════════════
    # SECTION: RACE / SPRINT (conditional)
    # ══════════════════════════════════════════════════════════
    race_col_items = []
    if has_race:
        if pit_rows:
            pit_fig = _gap_chart(
                pit_rows,
                title="Average Pit Stop Duration",
                xlabel="Gap (s)  ·  negative = left driver faster pit",
                fmt_fn=lambda v: f"{v:.2f}s",
                lower_is_better=True,
                note="PitOut − PitIn for matched in/out lap pairs. Range filter: 1.5 – 65 s.",
                unit="s",
            )
            race_col_items.append(
                dbc.Col(card("Pit Stop Duration", dcc.Graph(figure=pit_fig, config=GFX)), md=6)
            )

        if finish_rows:
            fin_fig = _gap_chart(
                finish_rows,
                title="Race Finish Position  (lower position = better)",
                xlabel="Gap  ·  negative = left driver finished higher",
                fmt_fn=lambda v: f"P{int(v)}" if not np.isnan(v) else "—",
                lower_is_better=True,
                note="Classified_Position from session results. DNF / DSQ → shown as —.",
                unit="pos",
            )
            race_col_items.append(
                dbc.Col(card("Race Finish Position", dcc.Graph(figure=fin_fig, config=GFX)), md=6)
            )

        if pgain_rows:
            pg_fig = _gap_chart(
                pgain_rows,
                title="Positions Gained / Lost  (Grid → Classified Finish)",
                xlabel="Gap  ·  negative = left driver gained more",
                fmt_fn=lambda v: (f"+{int(v)}" if v > 0 else str(int(v))) if not np.isnan(v) else "—",
                lower_is_better=False,   # higher gain is better
                note="Positions gained = Grid_Position − Classified_Position. Positive = moved up.",
                unit="pos",
            )
            race_col_items.append(
                dbc.Col(card("Positions Gained / Lost", dcc.Graph(figure=pg_fig, config=GFX)), md=6)
            )

        if overtake_rows:
            ov_fig = _gap_chart(
                overtake_rows,
                title="Overtakes Made  (race/sprint sessions)",
                xlabel="Gap (overtakes)  ·  negative = left driver made more",
                fmt_fn=lambda v: str(int(v)) if not np.isnan(v) else "—",
                lower_is_better=False,
                note="Overtook = position gained ≥ 1 on a non-pit lap (flag_position_changes).",
                unit="overtakes",
            )
            race_col_items.append(
                dbc.Col(card("Overtakes", dcc.Graph(figure=ov_fig, config=GFX)), md=6)
            )

        if champ_rows:
            champ_fig = _gap_chart(
                champ_rows,
                title="Championship Points Scored",
                xlabel="Gap (pts)  ·  negative = left driver scored more",
                fmt_fn=lambda v: f"{int(v)} pts" if not np.isnan(v) else "—",
                lower_is_better=False,
                note="Sum of Race_Points across all race/sprint sessions in current filter.",
                unit="pts",
            )
            # KPI pills: one per team showing A pts vs B pts
            champ_kpis = []
            for r in champ_rows:
                clr = TEAM_COLORS.get(r["team"], "#808080")
                va_s = f"{int(r['val_a'])} pts" if not np.isnan(r["val_a"]) else "—"
                vb_s = f"{int(r['val_b'])} pts" if not np.isnan(r["val_b"]) else "—"
                winner = (
                    r["drv_a"] if (not np.isnan(r["val_a"]) and not np.isnan(r["val_b"]) and r["val_a"] >= r["val_b"])
                    else (r["drv_b"] if not np.isnan(r["val_b"]) else None)
                )
                champ_kpis.append(dbc.Col(
                    dbc.Card(dbc.CardBody([
                        html.P(
                            html.Span([
                                "● ", html.Span(r["team"],
                                    style={"fontWeight":"700","fontSize":"0.78rem"})
                            ], style={"color": clr}),
                            style={"marginBottom": "4px", "fontSize": "0.72rem"},
                        ),
                        html.Div([
                            html.Span(r["drv_a"],
                                style={"color": "#00D2BE" if winner == r["drv_a"] else TEXT_DIM,
                                       "fontWeight": "800", "fontSize": "1.05rem"}),
                            html.Span(f"  {va_s}  ·  {vb_s}  ",
                                style={"color": TEXT_DIM, "fontSize": "0.85rem"}),
                            html.Span(r["drv_b"],
                                style={"color": "#FF8700" if winner == r["drv_b"] else TEXT_DIM,
                                       "fontWeight": "800", "fontSize": "1.05rem"}),
                        ]),
                    ]), style={"background": CARD_BG,
                               "border": f"1px solid {_hex_to_rgba(clr, 0.35)}",
                               "borderRadius": "8px"}),
                    xs=6, md=4, lg=3, className="mb-2",
                ))
            race_col_items.append(dbc.Col(card(
                html.Span([
                    "Championship Points",
                    html.Span(" — race/sprint sessions in current filter",
                              style={"color": TEXT_DIM, "fontWeight": "400",
                                     "fontSize": "0.75rem", "marginLeft": "8px"}),
                ]),
                html.Div([
                    dbc.Row(champ_kpis, className="mb-3"),
                    dcc.Graph(figure=champ_fig, config=GFX),
                ]),
            ), md=12))

    # ══════════════════════════════════════════════════════════
    # ASSEMBLE FULL LAYOUT
    # ══════════════════════════════════════════════════════════
    sections = [scoreboard, race_pace_section, consistency_section]

    if quali_col_items:
        sections.append(card(
            "Qualifying", dbc.Row(quali_col_items),
            info=("Data: teammate single-lap qualifying comparison — best quali-sim "
                  "lap and/or the classified Q3→Q2→Q1 time. Bars diverge toward the "
                  "faster driver. Why: qualifying pace decides grid position and is a "
                  "clean low-fuel speed test."),
        ))

    if race_col_items:
        sections.append(card(
            html.Span([
                "Race / Sprint Performance",
                html.Span(
                    f" — {', '.join(s.split('_')[0] for s in race_sess)}",
                    style={"color": TEXT_DIM, "fontWeight": "400",
                           "fontSize": "0.75rem", "marginLeft": "8px"},
                ),
            ]),
            dbc.Row(race_col_items),
            info=("Data: teammate race-day comparison from race/sprint sessions — pit "
                  "stop time, finish position, positions gained, overtakes and "
                  "championship points. Each bar diverges toward the better driver. "
                  "Why: separates race-craft, strategy and results from pure pace."),
        ))

    return html.Div(sections)


# ══════════════════════════════════════════════════════════════
# TAB 8 – TRACK INFO
# ══════════════════════════════════════════════════════════════

# ── Score → colour mapping ────────────────────────────────────
def _score_color(score: int) -> str:
    return {1: "#2ECC71", 2: "#F1C40F", 3: "#E67E22", 4: "#E74C3C"}.get(score, "#808080")

def _score_badge(label: str, score: int) -> html.Span:
    bg = _score_color(score)
    return html.Span(label, style={
        "background": bg, "color": "#000" if score <= 2 else "#fff",
        "borderRadius": "4px", "padding": "2px 9px",
        "fontSize": "0.72rem", "fontWeight": "700", "letterSpacing": "0.3px",
    })

# ── Stat pill ─────────────────────────────────────────────────
def _stat_pill(label, value, color=None):
    return html.Div([
        html.P(label, style={"color": TEXT_DIM, "fontSize": "0.65rem",
                              "letterSpacing": "1px", "marginBottom": "2px",
                              "fontWeight": "600"}),
        html.P(value, style={"color": color or TEXT_MAIN, "fontSize": "0.95rem",
                              "fontWeight": "800", "marginBottom": 0}),
    ], style={
        "background": CARD_BG, "border": f"1px solid {GRID_CLR}",
        "borderRadius": "6px", "padding": "8px 14px", "textAlign": "center",
        "flex": "1",
    })

# ── FastF1 circuit meta (lap record, circuit length, corners) ──
_FF1_CIRCUIT_META: dict = {
    # circuit_key → {lap_record, lap_record_driver, lap_record_year,
    #                length_km, corners, drs_zones}
    "italie":          {"length_km": 5.793, "corners": 11, "drs_zones": 2, "lap_record": "1:21.046", "lap_record_driver": "Rubens Barrichello", "lap_record_year": 2004},
    "monaco":          {"length_km": 3.337, "corners": 19, "drs_zones": 1, "lap_record": "1:12.909", "lap_record_driver": "Lewis Hamilton",      "lap_record_year": 2021},
    "grande_bretagne": {"length_km": 5.891, "corners": 18, "drs_zones": 2, "lap_record": "1:27.097", "lap_record_driver": "Max Verstappen",      "lap_record_year": 2020},
    "belgique":        {"length_km": 7.004, "corners": 19, "drs_zones": 2, "lap_record": "1:46.286", "lap_record_driver": "Valtteri Bottas",     "lap_record_year": 2018},
    "japon":           {"length_km": 5.807, "corners": 18, "drs_zones": 1, "lap_record": "1:30.983", "lap_record_driver": "Lewis Hamilton",      "lap_record_year": 2019},
    "singapour":       {"length_km": 5.063, "corners": 23, "drs_zones": 3, "lap_record": "1:35.867", "lap_record_driver": "Kevin Magnussen",     "lap_record_year": 2018},
    "azerbaidjan":     {"length_km": 6.003, "corners": 20, "drs_zones": 2, "lap_record": "1:43.009", "lap_record_driver": "Charles Leclerc",     "lap_record_year": 2019},
    "arabie_saoudite": {"length_km": 6.174, "corners": 27, "drs_zones": 3, "lap_record": "1:30.734", "lap_record_driver": "Lewis Hamilton",      "lap_record_year": 2021},
    "hongrie":         {"length_km": 4.381, "corners": 14, "drs_zones": 1, "lap_record": "1:16.627", "lap_record_driver": "Lewis Hamilton",      "lap_record_year": 2020},
    "espagne":         {"length_km": 4.675, "corners": 16, "drs_zones": 2, "lap_record": "1:18.149", "lap_record_driver": "Max Verstappen",      "lap_record_year": 2021},
    "autriche":        {"length_km": 4.318, "corners": 10, "drs_zones": 3, "lap_record": "1:05.619", "lap_record_driver": "Carlos Sainz",        "lap_record_year": 2020},
    "pays_bas":        {"length_km": 4.259, "corners": 14, "drs_zones": 2, "lap_record": "1:11.097", "lap_record_driver": "Lewis Hamilton",      "lap_record_year": 2021},
    "qatar":           {"length_km": 5.419, "corners": 16, "drs_zones": 1, "lap_record": "1:24.319", "lap_record_driver": "Max Verstappen",      "lap_record_year": 2023},
    "canada":          {"length_km": 4.361, "corners": 14, "drs_zones": 2, "lap_record": "1:13.078", "lap_record_driver": "Valtteri Bottas",     "lap_record_year": 2019},
    "etats_unis":      {"length_km": 5.513, "corners": 20, "drs_zones": 2, "lap_record": "1:36.169", "lap_record_driver": "Charles Leclerc",     "lap_record_year": 2019},
    "mexique":         {"length_km": 4.304, "corners": 17, "drs_zones": 3, "lap_record": "1:17.774", "lap_record_driver": "Valtteri Bottas",     "lap_record_year": 2021},
    "bresil":          {"length_km": 4.309, "corners": 15, "drs_zones": 2, "lap_record": "1:10.540", "lap_record_driver": "Valtteri Bottas",     "lap_record_year": 2018},
    "abu_dhabi":       {"length_km": 5.281, "corners": 16, "drs_zones": 2, "lap_record": "1:26.103", "lap_record_driver": "Max Verstappen",      "lap_record_year": 2021},
    "australie":       {"length_km": 5.278, "corners": 14, "drs_zones": 4, "lap_record": "1:19.813", "lap_record_driver": "Charles Leclerc",     "lap_record_year": 2024},
    "bahrein":         {"length_km": 5.412, "corners": 15, "drs_zones": 3, "lap_record": "1:31.447", "lap_record_driver": "Pedro de la Rosa",    "lap_record_year": 2005},
    "chine":           {"length_km": 5.451, "corners": 16, "drs_zones": 2, "lap_record": "1:32.238", "lap_record_driver": "Michael Schumacher",  "lap_record_year": 2004},
    "emilie_romagne":  {"length_km": 4.909, "corners": 19, "drs_zones": 2, "lap_record": "1:15.484", "lap_record_driver": "Lewis Hamilton",      "lap_record_year": 2020},
    "miami":           {"length_km": 5.412, "corners": 19, "drs_zones": 3, "lap_record": "1:29.708", "lap_record_driver": "Max Verstappen",      "lap_record_year": 2023},
    "las_vegas":       {"length_km": 6.201, "corners": 17, "drs_zones": 2, "lap_record": "1:35.490", "lap_record_driver": "Oscar Piastri",       "lap_record_year": 2023},
}

# ── Notable corners by circuit ────────────────────────────────
_NOTABLE_CORNERS: dict = {
    "italie":          ["T1 Prima Variante (chicane)", "T4 Seconda Variante (chicane)", "T11 Parabolica (Curva Alboreto)"],
    "monaco":          ["T1 Sainte-Dévote", "T6 Massenet", "T10 Casino", "T17 Mirabeau", "T19 Fairmont Hairpin", "T23 Rascasse", "T25 Antony Noghes"],
    "grande_bretagne": ["T3 Vale", "T6 Maggotts", "T7 Becketts", "T8 Chapel", "T13 Stowe", "T15 Club"],
    "belgique":        ["T1 La Source", "T7 Eau Rouge", "T8 Raidillon", "T14 Pouhon", "T18 Bus Stop chicane"],
    "japon":           ["T1 First Curve", "T2 S Curves", "T11 Degner 1", "T15 Hairpin", "T16 Spoon", "T18 130R", "T20 Casio"],
    "singapour":       ["T1 Turn 1", "T10 Singapore Sling", "T18 Raffles Boulevard", "T23 Anderson Bridge"],
    "azerbaidjan":     ["T8 Castle corner", "T15 Station Hairpin", "T20 Turn 20"],
    "arabie_saoudite": ["T4 Turn 4", "T13 Turn 13", "T22 Turn 22", "T27 Final"],
    "hongrie":         ["T1 Turn 1", "T4 Turns 4-5", "T11 Hairpin"],
    "espagne":         ["T1 Turn 1", "T3 Renault (S-bend)", "T5 Seat", "T10 La Caixa", "T14 Campsa", "T16 Final chicane"],
    "autriche":        ["T2 Remus (hairpin)", "T4 Schlossgold", "T6 Rindt"],
    "pays_bas":        ["T3 Tarzanbocht", "T10 Scheivlak", "T12 Hugenholtz", "T14 Mastersbocht (banked)"],
    "qatar":           ["T1 Turn 1", "T12 Turn 12", "T14 Turn 14"],
    "canada":          ["T1 Senna S", "T10 Wall of Champions hairpin", "T13 Casino"],
    "etats_unis":      ["T1 Big Red Braking Zone", "T11 Back straight chicane", "T15 Thunder hairpin"],
    "mexique":         ["T1 Peraltada modified", "T4 Esses", "T12 Stadium S"],
    "bresil":          ["T1 Curva do Sol", "T2 Senna S", "T6 Ferradura", "T11 Junção", "T13 Subida dos Boxes"],
    "abu_dhabi":       ["T7 Hairpin", "T9 Marina", "T11 Bab Al Shams", "T13 Turn 13"],
    "australie":       ["T1-T3 opening complex", "T6 fast left", "T9-T10 sweepers", "T11-T12 high speed", "T13 final corner"],
    "bahrein":         ["T1 heavy braking", "T4 hairpin", "T8 left-hander", "T10 hairpin", "T11-T13 esses"],
    "chine":           ["T1-T4 snail spiral", "T6 hairpin", "T11-T13 long hairpin", "T14 onto back straight"],
    "emilie_romagne":  ["T2-T3 Tamburello chicane", "T5 Villeneuve", "T7-T8 Acque Minerali", "T9-T10 Variante Alta", "T14-T15 Rivazza"],
    "miami":           ["T1 Turn 1", "T4-T6 esses", "T7-T8 sweepers", "T11-T16 technical sector", "T17 final corner"],
    "las_vegas":       ["T1-T2 opening", "T5-T7 chicane", "T9 hairpin", "T12 Sphere corner", "T14 onto the Strip", "T16-T17 final"],
}


def _corner_name_map(circuit_key) -> dict[int, str]:
    """Parse _NOTABLE_CORNERS ('T7 Eau Rouge', 'T1-T3 opening complex', …) into
    {corner_number: name} so named corners can be labelled on the track map."""
    import re
    out: dict[int, str] = {}
    for item in _NOTABLE_CORNERS.get(circuit_key, []):
        m = re.match(r"\s*T(\d+)(?:\s*[-–]\s*T?(\d+))?\s+(.*)", str(item))
        if not m:
            continue
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        name = m.group(3).strip()
        for n in range(a, b + 1):
            out.setdefault(n, name)
    return out

# ── Radar chart for circuit demand profile ────────────────────
def _radar_chart(row: pd.Series) -> go.Figure:
    dims   = ["Avg Speed", "Full Throttle", "Lateral Load", "Tyre Deg", "Tyre Difficulty"]
    scores = [
        row["avg_speed_score"], row["full_throttle_score"],
        row["lateral_load_score"], row["tyre_deg_score"],
        row["tyre_difficulty_score"],
    ]
    # Close the polygon
    dims_c   = dims + [dims[0]]
    scores_c = scores + [scores[0]]
    fig = go.Figure(go.Scatterpolar(
        r=scores_c, theta=dims_c,
        fill="toself",
        fillcolor="rgba(225,6,0,0.18)",
        line=dict(color=ACCENT, width=2),
        marker=dict(size=6, color=ACCENT),
        hovertemplate="%{theta}: %{r}/4<extra></extra>",
    ))
    fig.update_layout(
        polar=dict(
            bgcolor=CARD_BG,
            radialaxis=dict(
                visible=True, range=[0, 4], tickvals=[1, 2, 3, 4],
                tickfont=dict(size=8, color=TEXT_DIM),
                gridcolor=GRID_CLR, linecolor=GRID_CLR,
            ),
            angularaxis=dict(
                tickfont=dict(size=9, color=TEXT_MAIN),
                gridcolor=GRID_CLR, linecolor=GRID_CLR,
            ),
        ),
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
        height=280, margin=dict(l=40, r=40, t=30, b=30),
        showlegend=False,
    )
    return fig

# ── Historical leaderboard chart ──────────────────────────────
def _hist_leaderboard(df_res: pd.DataFrame, session_type: str, year: int) -> go.Figure:
    sub = df_res[
        (df_res["session_type"] == session_type) &
        (df_res["season"] == year)
    ].copy()
    if sub.empty:
        return go.Figure()

    # Normalise position column
    pos_col = next((c for c in ("ClassifiedPosition","Position","Q") if c in sub.columns), None)
    if pos_col:
        sub["_pos"] = pd.to_numeric(sub[pos_col], errors="coerce")
    else:
        sub["_pos"] = range(1, len(sub)+1)

    sub = sub.sort_values("_pos").head(20).reset_index(drop=True)

    # Driver label
    abbr_col = next((c for c in ("Abbreviation","Driver","DriverId") if c in sub.columns), None)
    team_col = next((c for c in ("TeamName","ConstructorName","Team") if c in sub.columns), None)
    sub["_drv"]  = sub[abbr_col].astype(str).str.strip() if abbr_col else sub.index.astype(str)
    sub["_team"] = sub[team_col].astype(str).str.strip() if team_col else "Unknown"
    sub["_color"]= sub["_team"].map(TEAM_COLORS).fillna("#808080")

    # Time/gap column
    time_col = next((c for c in ("Time","Q1","FastestLap","FastestLapTime") if c in sub.columns), None)
    if time_col:
        sub["_time_s"] = pd.to_numeric(sub[time_col], errors="coerce")
        leader = sub["_time_s"].dropna().iloc[0] if sub["_time_s"].notna().any() else None
        if leader:
            sub["_gap"] = (sub["_time_s"] - leader).apply(
                lambda x: "—" if x == 0 or pd.isna(x) else f"+{x:.3f}s"
            )
            sub["_label"] = sub["_time_s"].apply(format_lap_time)
        else:
            sub["_gap"]   = "—"
            sub["_label"] = "—"
    else:
        sub["_gap"]   = "—"
        sub["_label"] = "—"

    fig = go.Figure(go.Bar(
        x=sub["_pos"],
        y=[1]*len(sub),
        orientation="v",
        marker_color=sub["_color"],
        text=sub["_drv"],
        textposition="inside",
        textfont=dict(size=9, color="#fff"),
        customdata=sub[["_drv","_team","_label","_gap","_pos"]].values,
        hovertemplate=(
            "P%{customdata[4]}  <b>%{customdata[0]}</b>  (%{customdata[1]})<br>"
            "Time: %{customdata[2]}  Gap: %{customdata[3]}<extra></extra>"
        ),
    ))
    theme(fig, 200, f"{session_type} – {year}")
    fig.update_layout(
        showlegend=False,
        xaxis=dict(title="Position", tickvals=sub["_pos"].tolist(),
                   gridcolor=GRID_CLR, zeroline=False),
        yaxis=dict(visible=False),
        margin=dict(l=10, r=10, t=50, b=40),
        bargap=0.05,
    )
    return fig


def _hist_table(df_res: pd.DataFrame, session_type: str, year: int) -> dash_table.DataTable:
    sub = df_res[
        (df_res["session_type"] == session_type) &
        (df_res["season"] == year)
    ].copy()
    if sub.empty:
        return html.P("No data available.", style={"color": TEXT_DIM})

    pos_col  = next((c for c in ("ClassifiedPosition","Position","Q") if c in sub.columns), None)
    abbr_col = next((c for c in ("Abbreviation","DriverId","Driver") if c in sub.columns), None)
    team_col = next((c for c in ("TeamName","ConstructorName","Team") if c in sub.columns), None)
    time_col = next((c for c in ("Time","Q1","FastestLap","FastestLapTime") if c in sub.columns), None)
    pts_col  = "Points" if "Points" in sub.columns else None

    keep: dict = {}
    if pos_col:  keep["Pos"]    = sub[pos_col].apply(lambda v: pd.to_numeric(v, errors="coerce"))
    if abbr_col: keep["Driver"] = sub[abbr_col].astype(str).str.strip()
    if team_col: keep["Team"]   = sub[team_col].astype(str).str.strip()
    if time_col:
        t_s = pd.to_numeric(sub[time_col], errors="coerce")
        keep["Time"]  = t_s.apply(format_lap_time)
        leader = t_s.dropna().iloc[0] if t_s.notna().any() else None
        keep["Gap"]   = (t_s - leader).apply(
            lambda x: "—" if (pd.isna(x) or x == 0) else f"+{x:.3f}s"
        ) if leader else "—"
    if pts_col:  keep["Pts"]   = pd.to_numeric(sub[pts_col], errors="coerce")

    out = pd.DataFrame(keep)
    if "Pos" in out.columns:
        out = out.sort_values("Pos").reset_index(drop=True)

    return dash_table.DataTable(
        data=out.to_dict("records"),
        columns=[{"name": c, "id": c} for c in out.columns],
        **TABLE_STYLE,
        style_data_conditional=[
            {"if": {"row_index": 0}, "backgroundColor": ACCENT+"22", "fontWeight": "700"},
            {"if": {"row_index": 1}, "backgroundColor": "#88888822"},
            {"if": {"row_index": 2}, "backgroundColor": "#88441122"},
        ],
    )


# ── Sector heatmap from laps data (current loaded meeting) ────
def _sector_heatmap(laps_df: pd.DataFrame) -> go.Figure:
    """Mini-sector dominance map: each driver's best lap split into MINI_SECTORS
    equal-distance segments, coloured by % gap to the fastest driver in that
    mini-sector (green = quickest there). Far finer than the three timing
    sectors — it shows exactly which stretches of track each driver owns."""
    if telemetry is None or telemetry.empty or laps_df.empty:
        return go.Figure()
    blt = _best_lap_telemetry_frame(laps_df)
    if blt.empty or not {"Distance", "t_rel", "Driver_Short"}.issubset(blt.columns):
        return go.Figure()

    n = MINI_SECTORS
    times, teams = {}, {}
    for drv, g in blt.groupby("Driver_Short"):
        g = g.sort_values("Distance")
        dist = pd.to_numeric(g["Distance"], errors="coerce").to_numpy()
        trel = pd.to_numeric(g["t_rel"], errors="coerce").to_numpy()
        ok = np.isfinite(dist) & np.isfinite(trel)
        dist, trel = dist[ok], trel[ok]
        if dist.size < n + 1:
            continue
        keep = np.concatenate([[True], np.diff(dist) > 0])      # strictly increasing
        dist, trel = dist[keep], trel[keep]
        mt = _minisector_times(dist, trel, n)
        if np.all(np.isnan(mt)):
            continue
        times[drv] = mt
        teams[drv] = g["Team"].iloc[0] if "Team" in g.columns else None
    if not times:
        return go.Figure()

    cols = [str(i + 1) for i in range(n)]
    mat = pd.DataFrame(times, index=cols).T                     # drivers × mini-sectors
    mat = mat.reindex(mat.sum(axis=1).sort_values().index)      # fastest lap on top

    gap_pct = mat.copy()
    for col in gap_pct.columns:
        leader = gap_pct[col].min()
        gap_pct[col] = (gap_pct[col] - leader) / leader * 100 if leader and np.isfinite(leader) else np.nan

    # Colour by each mini-sector's OWN range (fastest=0 → slowest=1), so the
    # within-mini-sector ranking is legible everywhere. With a shared scale the
    # mini-sectors with the biggest spread dominate and tightly-matched ones all
    # wash out to the same green.
    znorm = gap_pct.copy()
    for col in znorm.columns:
        cmax = znorm[col].max()
        znorm[col] = znorm[col] / cmax if (cmax and np.isfinite(cmax) and cmax > 0) else 0.0

    text_annot = mat.applymap(lambda v: f"{v:.3f}s" if pd.notna(v) else "—")

    fig = go.Figure(go.Heatmap(
        z=znorm.values, x=cols, y=list(gap_pct.index),
        colorscale=[[0, "#2ECC71"], [0.5, "#F1C40F"], [1, "#E74C3C"]],
        zmin=0, zmax=1,
        text=text_annot.values, customdata=gap_pct.values,
        hovertemplate=("Driver: %{y}<br>Mini-sector: %{x}<br>"
                       "Time: %{text}<br>Gap: +%{customdata:.3f}%<extra></extra>"),
        colorbar=dict(title=dict(text="rank in<br>mini-sector", font=dict(color=TEXT_MAIN)),
                      tickvals=[0, 1], ticktext=["fastest", "slowest"],
                      tickfont=dict(color=TEXT_MAIN)),
    ))
    h = max(300, len(mat) * 26 + 100)
    theme(fig, h, "Mini-Sector Dominance — green = fastest through that stretch")
    fig.update_layout(
        xaxis_title="Mini-sector  (1 = start/finish → lap end)",
        margin=dict(l=80, r=80, t=60, b=40),
        yaxis=dict(autorange="reversed"),
    )
    return fig


# ── Tyre usage history chart ───────────────────────────────────
def _tyre_history_chart(laps_df: pd.DataFrame) -> go.Figure:
    v = laps_df[laps_df["ValidLap"] & laps_df["Compound"].notna()].copy()
    if v.empty:
        return go.Figure()

    usage = (
        v.groupby(["session_name", "Compound"])
        .agg(Laps=("LapTime_s","count"), AvgLapTime=("LapTime_s","median"))
        .reset_index()
    )

    fig = go.Figure()
    for cmp in COMPOUNDS:
        sub = usage[usage["Compound"] == cmp]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            x=sub["session_name"].apply(lambda s: s.split("_")[0]),
            y=sub["Laps"],
            name=cmp,
            marker_color=COMPOUND_COLORS.get(cmp, "#808080"),
            hovertemplate=f"{cmp}<br>Session: %{{x}}<br>Valid laps: %{{y}}<extra></extra>",
        ))

    theme(fig, 280, "Tyre Compound Usage — Valid Laps by Session")
    fig.update_layout(
        barmode="stack",
        xaxis_title="Session",
        yaxis_title="Laps",
        legend=dict(orientation="h", x=0, y=1.14, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=50, r=20, t=60, b=40),
    )
    return fig


# Text colour that stays readable on each compound's bar colour.
_COMPOUND_TEXT = {"SOFT": "#FFFFFF", "MEDIUM": "#111111", "HARD": "#111111",
                  "INTER": "#FFFFFF", "WET": "#FFFFFF"}


def _pit_durations(race: pd.DataFrame, lap_col: str) -> dict:
    """Pit-lane time loss per (driver, stint-just-ended), in seconds.

    Uses the session-time stamps already normalised to seconds in the laps
    frame: PitIn lands on the in-lap, PitOut on the following out-lap, so the
    difference is the full pit-lane transit time (~20–30 s). Anomalies
    (red-flag stops, garage time) are filtered with a sanity bound.
    """
    if "PitIn" not in race.columns or "PitOut" not in race.columns:
        return {}
    out: dict = {}
    for drv, g in race.groupby("Driver_Short"):
        g = g.sort_values(lap_col).reset_index(drop=True)
        pit_out = g[g["PitOut"].notna()]
        for _, row in g[g["PitIn"].notna()].iterrows():
            nxt = pit_out[pit_out[lap_col] > row[lap_col]]
            if nxt.empty:
                continue
            dur = float(nxt.iloc[0]["PitOut"]) - float(row["PitIn"])
            if 0 < dur < 120:
                out[(drv, int(row["Stint"]))] = dur
    return out


def _tyre_strategy_chart(laps_df: pd.DataFrame, results: pd.DataFrame | None = None,
                         title: str = "Race Tyre Strategy",
                         already_race: bool = False) -> go.Figure:
    """Per-driver tyre strategy for a race: one horizontal bar per driver, split
    into stint segments coloured by compound and sized by stint length (laps),
    ordered by finishing position (P1 on top). Compound + lap count are printed
    inside wide segments, and each pit stop is marked at the stint boundary with
    its pit-lane time. Recreates the FastF1 'Tyre strategies during a race'
    example, dressed up to match the rest of the dashboard.

    Accepts either the in-memory enriched laps (with Driver_Short /
    Classified_Position) or raw cache-loaded race laps (with Driver / DriverNo),
    optionally with a *results* frame for the finishing order.
    """
    race = laps_df.copy()
    if not already_race and "session_name" in race.columns:
        race = race[race["session_name"].astype(str).str.startswith("Race_")].copy()
    if race.empty:
        return go.Figure()

    lap_col = "LapNo" if "LapNo" in race.columns else "LapNumber"

    # Driver short code: prefer the enriched column, else derive from "Driver".
    if "Driver_Short" not in race.columns or race["Driver_Short"].isna().all():
        race["Driver_Short"] = (race["Driver"].astype(str)
                                .str.split("-").str[0].str.strip())
    race = race.dropna(subset=["Driver_Short", "Stint", "Compound"])
    race = race[race["Driver_Short"].astype(str).str.len() > 0]
    if race.empty:
        return go.Figure()

    pit = _pit_durations(race, lap_col)

    # Stint length = number of laps per driver × stint × compound.
    seg = (race.groupby(["Driver_Short", "Stint", "Compound"])[lap_col]
              .count().reset_index().rename(columns={lap_col: "StintLength"}))
    seg["_stint"] = pd.to_numeric(seg["Stint"], errors="coerce")

    # Finishing order (P1 first); unclassified drivers fall to the bottom.
    if "Classified_Position" in race.columns and race["Classified_Position"].notna().any():
        order = (race.groupby("Driver_Short")["Classified_Position"].first()
                    .sort_values(na_position="last").index.tolist())
    elif (results is not None and not results.empty
          and {"Abbreviation", "ClassifiedPosition"}.issubset(results.columns)):
        res = results.copy()
        res["_p"] = pd.to_numeric(res["ClassifiedPosition"], errors="coerce")
        res["_abbr"] = res["Abbreviation"].astype(str).str.strip()
        pos = (res.dropna(subset=["_p"]).drop_duplicates("_abbr")
                  .set_index("_abbr")["_p"].to_dict())
        drivers = list(seg["Driver_Short"].unique())
        order = sorted(drivers, key=lambda d: (pos.get(d, 1e9), d))
    else:
        order = (race.groupby("Driver_Short")[lap_col].max()
                    .sort_values(ascending=False).index.tolist())

    fig = go.Figure()
    seen_comp: set = set()
    pit_x, pit_y, pit_txt, pit_hover = [], [], [], []   # pit-stop markers
    for drv in order:
        d = seg[seg["Driver_Short"] == drv].sort_values("_stint")
        left = 0
        n_stints = len(d)
        for i, (_, r) in enumerate(d.iterrows()):
            cmp = str(r["Compound"]).upper()
            length = int(r["StintLength"])
            stint_no = int(r["_stint"]) if pd.notna(r["_stint"]) else None
            clr = COMPOUND_COLORS.get(cmp, "#808080")
            # Compound + laps printed inside the bar when there's room.
            seg_text = f"{cmp[0]} · {length}" if length >= 4 else (
                cmp[0] if length >= 2 else "")
            fig.add_trace(go.Bar(
                y=[drv], x=[length], base=left, orientation="h",
                name=cmp, legendgroup=cmp, showlegend=(cmp not in seen_comp),
                marker=dict(color=clr, line=dict(color="#000", width=1)),
                text=[seg_text], textposition="inside", insidetextanchor="middle",
                textfont=dict(color=_COMPOUND_TEXT.get(cmp, "#111111"), size=10),
                hovertemplate=(f"<b>{drv}</b> · {cmp}<br>"
                               f"Laps {left + 1}–{left + length} "
                               f"({length} laps)<extra></extra>"),
            ))
            seen_comp.add(cmp)
            left += length
            # Pit stop at the end of this stint (not after the final stint).
            if stint_no is not None and i < n_stints - 1 and (drv, stint_no) in pit:
                dur = pit[(drv, stint_no)]
                pit_x.append(left)
                pit_y.append(drv)
                pit_txt.append(f"{dur:.1f}")
                pit_hover.append(f"<b>{drv}</b><br>Pit stop · lap {left}<br>"
                                 f"Pit-lane time: {dur:.1f} s<extra></extra>")

    # Pit-stop markers + times overlaid at the stint boundaries.
    if pit_x:
        fig.add_trace(go.Scatter(
            x=pit_x, y=pit_y, mode="markers+text",
            marker=dict(symbol="diamond", size=9, color="#FFFFFF",
                        line=dict(color="#111", width=1)),
            text=pit_txt, textposition="top center",
            textfont=dict(size=8, color=TEXT_DIM),
            hovertemplate=pit_hover, name="Pit stop", showlegend=True,
            cliponaxis=False,
        ))

    theme(fig, max(360, 26 * len(order) + 150), title)
    fig.update_layout(
        barmode="stack",
        xaxis_title="Lap Number",
        yaxis_title="",
        bargap=0.28,
        legend=dict(orientation="h", x=0, y=1.06, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=60, r=20, t=70, b=40),
        annotations=[dict(
            text="◆ pit stop · number = pit-lane time (s)",
            xref="paper", yref="paper", x=1, y=1.04, xanchor="right",
            showarrow=False, font=dict(size=9, color=TEXT_DIM),
        )],
    )
    fig.update_yaxes(autorange="reversed")     # P1 at the top
    fig.update_xaxes(rangemode="tozero")
    return fig


# ══════════════════════════════════════════════════════════════
# TRACK MAP — circuit layout, corner annotations, gear-shift map
# (recreates the FastF1 examples in Plotly; data fetched on demand
#  from a fast lap and cached to data/track_maps/ for instant reuse)
# ══════════════════════════════════════════════════════════════
import json as _json

TRACK_MAPS_DIR = Path("data/track_maps")

# Distinct colours for gears 1–8 (readable on the dark theme).
GEAR_COLORS = {
    1: "#3B82F6", 2: "#22D3EE", 3: "#10B981", 4: "#A3E635",
    5: "#FACC15", 6: "#FB923C", 7: "#EF4444", 8: "#E879F9",
}


def _rotate(x, y, angle):
    """Rotate point(s) (x, y) by *angle* radians — matches FastF1's example."""
    ca, sa = np.cos(angle), np.sin(angle)
    return x * ca - y * sa, x * sa + y * ca


def _track_map_slug(text: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_").lower()


def _track_map_paths(season, event_name, session_id):
    base = TRACK_MAPS_DIR / f"{season}_{_track_map_slug(event_name)}_{session_id}"
    return {
        "line":    base.with_suffix(".parquet"),
        "corners": Path(str(base) + "_corners.parquet"),
        "meta":    base.with_suffix(".json"),
    }


# Columns the cached track-map *line* must carry for every plot (layout, gears,
# sectors, DRS). Caches written before sectors/DRS were added lack the last two;
# get_track_map treats those as a miss and re-fetches to upgrade them.
_TRACK_LINE_COLS = {"X", "Y", "gear", "Speed", "sector", "drs", "z"}


def _read_track_map_cache(paths) -> dict | None:
    """Load a cached track map from disk without any network access. Returns
    None when the cache is absent (callers check columns for completeness)."""
    if not (paths["line"].exists() and paths["meta"].exists()):
        return None
    line = pd.read_parquet(paths["line"])
    corners = (pd.read_parquet(paths["corners"])
               if paths["corners"].exists() else pd.DataFrame())
    with open(paths["meta"], "r", encoding="utf-8") as fh:
        meta = _json.load(fh)
    return {"line": line, "corners": corners, **meta}


def get_track_map(season, event_name, session_id="Q", force=False) -> dict | None:
    """
    Return {line: DataFrame[X,Y,gear,Speed,sector,drs], corners: DataFrame,
            rotation, driver, laptime, event, session} for the fastest lap of the
    given session. Cached to data/track_maps/. Returns None if no lap/telemetry.
    """
    paths = _track_map_paths(season, event_name, session_id)

    if not force:
        cached = _read_track_map_cache(paths)
        if cached is not None and _TRACK_LINE_COLS.issubset(cached["line"].columns):
            return cached
        # else: cache missing or pre-dates sectors/DRS → (re)fetch to upgrade.

    import fastf1
    fastf1.Cache.enable_cache(str(Path(FASTF1_CACHE_DIR)))
    sess = fastf1.get_session(int(season), event_name, session_id)
    sess.load(laps=True, telemetry=True, weather=False, messages=False)

    lap = sess.laps.pick_fastest()
    if lap is None or (hasattr(lap, "empty") and getattr(lap, "empty", False)):
        return None
    tel = lap.get_telemetry()
    if tel is None or tel.empty or not {"X", "Y", "nGear"}.issubset(tel.columns):
        return None

    keep = ["X", "Y", "nGear", "Speed"] + [c for c in ("Z", "DRS", "SessionTime")
                                           if c in tel.columns]
    line = (tel[keep]
            .rename(columns={"nGear": "gear", "Z": "z"})
            .dropna(subset=["X", "Y"])
            .reset_index(drop=True))
    line["gear"] = line["gear"].fillna(0).astype(int)
    if "z" not in line.columns:           # altitude unavailable → no elevation map
        line["z"] = np.nan

    # DRS / active-aero open: FastF1 DRS codes 10/12/14 mean the flap is open.
    if "DRS" in line.columns:
        line["drs"] = line["DRS"].isin([10, 12, 14]).astype(int)
        line = line.drop(columns=["DRS"])
    else:
        line["drs"] = 0

    # Timing sectors (1/2/3) from the lap's cumulative sector session-times.
    def _lapval(k):
        try:
            return lap[k]
        except Exception:
            return None
    s1, s2 = _lapval("Sector1SessionTime"), _lapval("Sector2SessionTime")
    if "SessionTime" in line.columns and pd.notna(s1) and pd.notna(s2):
        st = line["SessionTime"]
        line["sector"] = np.where(st <= s1, 1, np.where(st <= s2, 2, 3)).astype(int)
    else:                                   # fallback: split the lap into thirds
        n = len(line); idx = np.arange(n)
        line["sector"] = np.where(idx < n / 3, 1,
                                  np.where(idx < 2 * n / 3, 2, 3)).astype(int)
    if "SessionTime" in line.columns:
        line = line.drop(columns=["SessionTime"])

    rotation = 0.0
    corners = pd.DataFrame()
    try:
        ci = sess.get_circuit_info()
        rotation = float(ci.rotation)
        _corner_cols = [c for c in ["Number", "Letter", "X", "Y", "Angle", "Distance"]
                        if c in ci.corners.columns]
        corners = ci.corners[_corner_cols].copy()
    except Exception as exc:
        logging.warning("circuit_info unavailable for %s %s: %s", season, event_name, exc)

    laptime = lap["LapTime"]
    laptime_s = laptime.total_seconds() if pd.notna(laptime) else float("nan")
    meta = {
        "rotation": rotation,
        "driver":   str(lap.get("Driver", "")),
        "laptime":  format_lap_time(laptime_s),
        "event":    event_name,
        "season":   int(season),
        "session":  session_id,
    }

    TRACK_MAPS_DIR.mkdir(parents=True, exist_ok=True)
    line.to_parquet(paths["line"], index=False)
    if not corners.empty:
        corners.to_parquet(paths["corners"], index=False)
    with open(paths["meta"], "w", encoding="utf-8") as fh:
        _json.dump(meta, fh)

    return {"line": line, "corners": corners, **meta}


def _track_map_layout(fig: go.Figure, title: str, height: int = 480) -> go.Figure:
    fig.update_layout(
        title=title, height=height,
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
        margin=dict(l=20, r=20, t=60, b=20),
        showlegend=True,
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1),
    )
    axkw = dict(showgrid=False, zeroline=False, visible=False)
    fig.update_xaxes(**axkw)
    fig.update_yaxes(scaleanchor="x", scaleratio=1, **axkw)
    return fig


def _finish_line(xr, yr, length: float = 1100.0):
    """A short segment perpendicular to the track at the start/finish point
    (the fastest lap's telemetry begins on the start/finish line)."""
    dx = float(xr[1] - xr[0]); dy = float(yr[1] - yr[0])
    n  = (dx * dx + dy * dy) ** 0.5 or 1.0
    px, py = -dy / n, dx / n          # unit perpendicular to track direction
    h = length / 2.0
    return ([xr[0] - px * h, xr[0] + px * h],
            [yr[0] - py * h, yr[0] + py * h])


def _fig_track_map(tm: dict, corner_names: dict[int, str] | None = None) -> go.Figure:
    """Circuit layout coloured by timing sector, with the start/finish line and
    the numbered corner markers (corner names shown on hover)."""
    line = tm["line"]
    ang  = tm["rotation"] / 180.0 * np.pi
    xr, yr = _rotate(line["X"].to_numpy(), line["Y"].to_numpy(), ang)
    corner_names = corner_names or {}

    fig = go.Figure()

    # Track line coloured by timing sector (plain white if sectors absent).
    if "sector" in line.columns:
        sec = line["sector"].to_numpy()
        for s in (1, 2, 3):
            xs, ys = _track_segments(xr, yr, sec == s)
            if not xs:
                continue
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines",
                line=dict(color=SECTOR_COLORS[s], width=4),
                name=f"Sector {s}", connectgaps=False,
                hovertemplate=f"Sector {s}<extra></extra>",
            ))
    else:
        fig.add_trace(go.Scatter(
            x=xr, y=yr, mode="lines", line=dict(color=TEXT_MAIN, width=2),
            name="Track", hoverinfo="skip", showlegend=False,
        ))

    # Start / finish line.
    if len(xr) > 1:
        fx, fy = _finish_line(xr, yr)
        fig.add_trace(go.Scatter(
            x=fx, y=fy, mode="lines",
            line=dict(color="#FFFFFF", width=5),
            name="Start / Finish", hovertemplate="Start / Finish<extra></extra>",
        ))

    # Numbered corner markers (name on hover).
    corners = tm.get("corners")
    if corners is not None and not corners.empty:
        OFFSET = 600.0  # distance to push the label off the track (track units)
        conn_x, conn_y, mk_x, mk_y, labels, hovers = [], [], [], [], [], []
        for _, c in corners.iterrows():
            off_ang = c["Angle"] / 180.0 * np.pi
            ox, oy  = _rotate(OFFSET, 0.0, off_ang)
            tx, ty  = _rotate(c["X"] + ox, c["Y"] + oy, ang)   # label position
            cx, cy  = _rotate(c["X"], c["Y"], ang)             # on-track position
            conn_x += [cx, tx, None]; conn_y += [cy, ty, None]
            mk_x.append(tx); mk_y.append(ty)
            num    = int(c["Number"])
            letter = "" if pd.isna(c["Letter"]) else str(c["Letter"])
            labels.append(f"{num}{letter}")
            name = corner_names.get(num)
            hovers.append(f"Turn {num}{letter} — {name}" if name else f"Turn {num}{letter}")

        fig.add_trace(go.Scatter(
            x=conn_x, y=conn_y, mode="lines",
            line=dict(color=TEXT_DIM, width=1), hoverinfo="skip", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=mk_x, y=mk_y, mode="markers+text",
            marker=dict(size=20, color="#444", line=dict(color=TEXT_DIM, width=1)),
            text=labels, textfont=dict(color=TEXT_MAIN, size=9),
            textposition="middle center", hoverinfo="text", hovertext=hovers,
            name="Corners", showlegend=False,
        ))

    title = f"Layout, Corners & Sectors — {tm['event']} {tm['season']}"
    fig = _track_map_layout(fig, title)
    fig.update_layout(legend=dict(
        title=dict(text="Sector", font=dict(color=TEXT_MAIN, size=10)),
        bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1,
        orientation="v",
    ))
    return fig


def _fig_gear_map(tm: dict) -> go.Figure:
    line = tm["line"]
    ang  = tm["rotation"] / 180.0 * np.pi
    xr, yr = _rotate(line["X"].to_numpy(), line["Y"].to_numpy(), ang)
    gear = line["gear"].to_numpy()

    fig = go.Figure()
    for g in range(1, 9):
        xs, ys = [], []
        for i in range(len(gear) - 1):
            if gear[i] == g:
                xs += [xr[i], xr[i + 1], None]
                ys += [yr[i], yr[i + 1], None]
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines",
            line=dict(color=GEAR_COLORS.get(g, "#808080"), width=4),
            name=f"Gear {g}", connectgaps=False,
            hovertemplate=f"Gear {g}<extra></extra>",
        ))

    drv = f" — {tm['driver']} {tm['laptime']}" if tm.get("driver") else ""
    title = f"Gear Shifts on Track{drv}"
    fig = _track_map_layout(fig, title)
    fig.update_layout(legend=dict(
        title=dict(text="Gear", font=dict(color=TEXT_MAIN, size=10)),
        bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1,
        orientation="v",
    ))
    return fig


# Distinct, dark-theme-readable colours for the three timing sectors.
SECTOR_COLORS = {1: "#E10600", 2: "#00B4D8", 3: "#FFD700"}


def _track_segments(xr, yr, mask):
    """Build disjoint line segments (with None breaks) for the points where
    *mask* is True — used to colour parts of the track line."""
    xs, ys = [], []
    n = len(mask)
    for i in range(n - 1):
        if mask[i]:
            xs += [xr[i], xr[i + 1], None]
            ys += [yr[i], yr[i + 1], None]
    return xs, ys


def _fig_elevation_map(tm: dict) -> go.Figure | None:
    """Track coloured by elevation (relief). FastF1 position units are 1/10 m,
    so Z is converted to metres relative to the lap's lowest point."""
    line = tm["line"]
    if "z" not in line.columns or line["z"].isna().all():
        return None
    ang = tm["rotation"] / 180.0 * np.pi
    xr, yr = _rotate(line["X"].to_numpy(), line["Y"].to_numpy(), ang)
    z = line["z"].to_numpy(dtype=float)
    rel = (z - np.nanmin(z)) / 10.0           # metres above the lowest point

    fig = go.Figure(go.Scatter(
        x=xr, y=yr, mode="markers",
        marker=dict(
            size=6, color=rel, colorscale="Turbo", showscale=True,
            colorbar=dict(
                title=dict(text="Δ elev (m)", font=dict(color=TEXT_MAIN, size=10)),
                tickfont=dict(color=TEXT_DIM, size=9), thickness=12, len=0.7,
            ),
        ),
        customdata=rel,
        hovertemplate="Elevation: +%{customdata:.1f} m<extra></extra>",
        showlegend=False,
    ))
    rng = float(np.nanmax(rel)) if rel.size else 0.0
    fig = _track_map_layout(fig, f"Track Elevation / Relief (range ≈ {rng:.0f} m)")
    fig.update_layout(showlegend=False)
    return fig


def _fig_drs_map(tm: dict) -> go.Figure | None:
    line = tm["line"]
    if "drs" not in line.columns:
        return None
    ang = tm["rotation"] / 180.0 * np.pi
    xr, yr = _rotate(line["X"].to_numpy(), line["Y"].to_numpy(), ang)
    drs = line["drs"].to_numpy().astype(int)

    fig = go.Figure()
    # Closed first (thin, dim) so the bright open zones sit on top.
    for state, clr, width, nm in [
        (0, TEXT_DIM,  2, "Closed"),
        (1, "#39FF14", 5, "DRS / active-aero open"),
    ]:
        xs, ys = _track_segments(xr, yr, drs == state)
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines",
            line=dict(color=clr, width=width),
            name=nm, connectgaps=False,
            hovertemplate=f"{nm}<extra></extra>",
        ))
    fig = _track_map_layout(fig, "DRS / Active-Aero Zones (fastest lap)")
    if drs.sum() == 0:                      # no open data (e.g. 2026 feed)
        fig.add_annotation(
            text="No DRS / active-aero activation recorded for this lap",
            xref="paper", yref="paper", x=0.5, y=0.02, showarrow=False,
            font=dict(size=10, color=TEXT_DIM),
        )
    fig.update_layout(legend=dict(
        bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1,
        orientation="v",
    ))
    return fig


def _resolve_track_event(circuit_key: str, year):
    """Map a Track-Info circuit slug + year to a (season, event_name) FastF1
    can fetch, using the historical results table. Prefers the requested
    year, else the most recent season available for that circuit."""
    hist_keys = HIST_CIRCUIT_KEY_MAP.get(circuit_key, [circuit_key])
    if HIST_RACE.empty or "circuit_key" not in HIST_RACE.columns:
        return None, None
    sub = HIST_RACE[HIST_RACE["circuit_key"].isin(hist_keys)]
    if sub.empty:
        return None, None
    if year is not None and (sub["season"] == year).any():
        sub = sub[sub["season"] == year]
    row = sub.sort_values("season").iloc[-1]
    return int(row["season"]), str(row["event_name"])


# ── Main track tab layout builder ────────────────────────────
# ── UPGRADES tab ─────────────────────────────────────────────
_UPGRADE_CAT_COLORS = {
    "performance":     ACCENT,
    "circuit specific":"#FFB000",
    "reliability":     "#0067FF",
    "driver comfort":  "#9B59B6",
    "repairs":         "#7A7A7A",
}

def _upgrade_cat_color(cat: str) -> str:
    return _UPGRADE_CAT_COLORS.get(str(cat).strip().casefold(), "#7A7A7A")


def _upgrade_meeting_block(season, meeting) -> html.Div:
    sub = _upgrades_for(season, meeting)
    title = f"{meeting}" + (f"  ·  {season}" if season else "")

    if sub.empty:
        return html.Div([
            html.H4(title, style={"color": TEXT_MAIN, "fontWeight": "800",
                                  "letterSpacing": "1px", "fontSize": "1.05rem",
                                  "marginBottom": "8px"}),
            dbc.Alert(
                f"No upgrades recorded for this event yet. Add rows to "
                f"data/upgrades.csv with event = \"{meeting}\" and season = "
                f"{season or '<year>'}.",
                color="secondary",
                style={"background": CARD_BG, "border": f"1px solid {GRID_CLR}",
                       "color": TEXT_DIM},
            ),
        ], className="mb-4")

    # ── Summary KPIs ─────────────────────────────────────────
    n_total = len(sub)
    n_teams = sub["team"].nunique()
    cat_counts = sub["category"].str.strip().str.title().value_counts()
    top_cat = cat_counts.index[0] if not cat_counts.empty else "—"
    kpis = dbc.Row([
        kpi("UPGRADES", str(n_total), tooltip="Total upgrade items logged for this event."),
        kpi("TEAMS DEVELOPING", str(n_teams),
            tooltip="Teams that brought at least one upgrade here."),
        kpi("MOST COMMON", top_cat, color="#FFB000",
            tooltip="Most frequent upgrade category for this event."),
        kpi("PERFORMANCE ITEMS",
            str(int(cat_counts.get("Performance", 0))), color=ACCENT,
            tooltip="Upgrades flagged as pure performance (not circuit-specific)."),
    ], className="g-2 mb-2")

    # ── One card per team, ordered by championship rank if known ─
    rank = _team_champ_rank()
    teams = sorted(sub["team"].unique(),
                   key=lambda t: (rank.get(t, 999), t))
    team_cards = []
    for tname in teams:
        rows = sub[sub["team"] == tname]
        colr = TEAM_COLORS.get(tname, "#808080")
        items = []
        for _, r in rows.iterrows():
            ccolor = _upgrade_cat_color(r["category"])
            items.append(html.Div([
                html.Div([
                    html.Span(r["component"] or "—",
                              style={"fontWeight": "700", "color": TEXT_MAIN,
                                     "fontSize": "0.85rem"}),
                    _badge((r["category"] or "—").title(), ccolor),
                ], style={"marginBottom": "2px"}),
                html.Div(r["description"] or "",
                         style={"color": TEXT_DIM, "fontSize": "0.78rem",
                                "lineHeight": "1.35"}),
            ], style={"padding": "8px 0",
                      "borderBottom": f"1px solid {GRID_CLR}"}))
        header = html.Div([
            html.Span(style={"display": "inline-block", "width": "10px",
                             "height": "10px", "borderRadius": "2px",
                             "background": colr, "marginRight": "8px"}),
            html.Span(tname, style={"fontWeight": "800", "letterSpacing": "0.5px"}),
            _badge(f"{len(rows)}", colr),
        ])
        team_cards.append(dbc.Col(
            dbc.Card([dbc.CardHeader(header),
                      dbc.CardBody(items, style={"paddingTop": "4px"})],
                     className="mb-3",
                     style={"background": CARD_BG,
                            "border": f"1px solid {GRID_CLR}",
                            "borderLeft": f"3px solid {colr}",
                            "borderRadius": "8px"}),
            md=6))

    return html.Div([
        html.H4(title, style={"color": TEXT_MAIN, "fontWeight": "800",
                              "letterSpacing": "1px", "fontSize": "1.05rem",
                              "marginBottom": "10px"}),
        kpis,
        dbc.Row(team_cards, className="g-3"),
    ], className="mb-4")


def tab_upgrades() -> html.Div:
    """What technical evolution each team brought to the loaded meeting(s)."""
    if upgrades_df().empty:
        return html.Div([dbc.Alert(
            [html.Strong("No upgrade data found. "),
             "Create ", html.Code("data/upgrades.csv"),
             " with columns: ",
             html.Code("season, event, team, component, category, "
                       "description, source"),
             ". The ", html.Code("event"), " value must match the meeting name "
             "(e.g. \"Austrian Grand Prix\") and ", html.Code("team"),
             " a known team name."],
            color="warning")])

    meetings = _loaded_meetings()
    if not meetings:
        return html.Div([dbc.Alert(
            "No session loaded. Load a meeting in the DATA & QUALITY tab to see "
            "the upgrades each team brought to it.", color="secondary",
            style={"background": CARD_BG, "border": f"1px solid {GRID_CLR}",
                   "color": TEXT_DIM})])

    legend = html.Div(
        [html.Span("Category:", style={"color": TEXT_DIM, "fontSize": "0.72rem",
                                       "marginRight": "8px"})]
        + [_badge(c.title(), col) for c, col in _UPGRADE_CAT_COLORS.items()],
        style={"marginBottom": "16px"})

    blocks = [_upgrade_meeting_block(season, meeting)
              for season, meeting in meetings]

    return html.Div([
        html.P("Technical upgrades each team brought to the loaded event(s), "
               "in the style of the FIA Car Presentation documents. "
               "Maintained in data/upgrades.csv.",
               style={"color": TEXT_DIM, "fontSize": "0.8rem",
                      "marginBottom": "10px"}),
        legend,
        *blocks,
    ])


def tab_track_info() -> html.Div:
    if CIRCUIT_CHARS.empty:
        return html.Div([
            dbc.Alert(
                "Circuit characteristics data not found. "
                "Run write_circuit_characteristics.py and place the CSV in data/.",
                color="warning",
            )
        ])

    # Build dropdown options — sorted alphabetically by name so the list
    # stays navigable as new circuits are appended to the CSV.
    options = sorted(
        [{"label": row["grand_prix_fr"], "value": row["circuit_key"]}
         for _, row in CIRCUIT_CHARS.iterrows()],
        key=lambda o: o["label"],
    )
    # Default to the circuit of the meeting currently loaded in the Data tab,
    # so the tab opens on data the user is actually looking at.
    loaded_key  = _loaded_circuit_key()
    default_key = loaded_key if loaded_key else (options[0]["value"] if options else None)

    # Historical year options
    avail_years = sorted(set(
        list(HIST_RACE["season"].unique() if "season" in HIST_RACE.columns else []) +
        list(HIST_QUALI["season"].unique() if "season" in HIST_QUALI.columns else [])
    ), reverse=True)
    year_opts = [{"label": str(y), "value": int(y)} for y in avail_years]

    # Default season for the *selected* circuit: the current season when that
    # GP has already run, else the previous season (N-1). The whole page (incl.
    # the race tyre-strategy plot) follows this, and it re-syncs when the circuit
    # dropdown changes (see _sync_track_year).
    default_year = _circuit_display_season(default_key, avail_years)
    if default_year is None:
        default_year = year_opts[0]["value"] if year_opts else None

    return html.Div([
        # ── Selectors row ─────────────────────────────────────
        dbc.Row([
            dbc.Col([
                html.Label("Circuit", style={"color": TEXT_DIM, "fontSize": "0.72rem",
                                              "letterSpacing": "1px", "fontWeight": "600"}),
                dcc.Dropdown(
                    id="track-circuit-select",
                    options=options,
                    value=default_key,
                    clearable=False,
                    style={"backgroundColor": "#111", "fontSize": "0.85rem"},
                ),
            ], md=5),
            dbc.Col([
                html.Label("Historical Season", style={"color": TEXT_DIM, "fontSize": "0.72rem",
                                                        "letterSpacing": "1px", "fontWeight": "600"}),
                dcc.Dropdown(
                    id="track-year-select",
                    options=year_opts,
                    value=default_year,
                    clearable=False,
                    style={"backgroundColor": "#111", "fontSize": "0.85rem"},
                ),
            ], md=3),
        ], className="mb-3"),

        # ── Dynamic content area ─────────────────────────────
        html.Div(id="track-content"),
    ])


def _track_map_children(tm: dict, season, event_name, circuit_key=None) -> html.Div:
    """Rendered track-map block: note + layout/sectors, gears, elevation, DRS.
    Shared by the pre-load path and the on-demand button callback."""
    note = html.P(
        f"Fastest lap: {tm.get('driver','?')} · {tm.get('laptime','?')} · "
        f"{event_name} {season} {tm.get('session','')} qualifying",
        style={"color": TEXT_DIM, "fontSize": "0.74rem", "marginBottom": "8px"},
    )
    corner_names = _corner_name_map(circuit_key) if circuit_key else {}
    rows = [dbc.Row([
        dbc.Col(dcc.Graph(figure=_fig_track_map(tm, corner_names), config=GFX), md=6),
        dbc.Col(dcc.Graph(figure=_fig_gear_map(tm),                config=GFX), md=6),
    ])]
    elev_fig = _fig_elevation_map(tm)
    drs_fig  = _fig_drs_map(tm)
    second = []
    if elev_fig is not None:
        second.append(dbc.Col(dcc.Graph(figure=elev_fig, config=GFX), md=6))
    if drs_fig is not None:
        second.append(dbc.Col(dcc.Graph(figure=drs_fig, config=GFX), md=6))
    if second:
        rows.append(dbc.Row(second))
    return html.Div([note, *rows])


def _cached_track_map(circuit_key, year):
    """Return (children, season, event_name) for a track map *already cached* on
    disk (with all plot columns), without triggering a FastF1 download.
    (None, …) when not pre-cached or the cache pre-dates the sector/DRS data."""
    season, event_name = _resolve_track_event(circuit_key, year)
    if not event_name:
        return None, season, event_name
    for sid in ("Q", "R"):
        paths = _track_map_paths(season, event_name, sid)
        cached = _read_track_map_cache(paths)
        if cached is not None and _TRACK_LINE_COLS.issubset(cached["line"].columns):
            return (_track_map_children(cached, season, event_name, circuit_key),
                    season, event_name)
    return None, season, event_name


def _track_season_banner(hist_year, current_season, display_season,
                         is_loaded_circuit) -> html.Div:
    """Prominent banner stating which season the whole tab is showing, and why."""
    if current_season is not None and hist_year == current_season:
        note = "Current season — this Grand Prix has already run."
    elif (current_season is not None and display_season == hist_year
          and hist_year == current_season - 1):
        note = (f"The {current_season} race hasn't run yet, so the last "
                f"completed season ({hist_year}) is shown.")
    else:
        note = "Season manually selected."
    if is_loaded_circuit:
        note += "  This is the event loaded in the Data tab."
    return html.Div([
        html.Span("SHOWING SEASON", style={
            "color": TEXT_DIM, "fontSize": "0.62rem", "letterSpacing": "2px",
            "fontWeight": "700", "marginRight": "10px"}),
        html.Span(str(hist_year), style={
            "color": TEXT_MAIN, "fontSize": "1.25rem", "fontWeight": "900",
            "letterSpacing": "1px"}),
        html.Span("  ·  " + note, style={
            "color": TEXT_DIM, "fontSize": "0.78rem", "marginLeft": "8px"}),
    ], style={
        "background": CARD_BG, "border": f"1px solid {GRID_CLR}",
        "borderLeft": f"4px solid {ACCENT}", "borderRadius": "4px",
        "padding": "10px 14px", "marginBottom": "16px",
        "display": "flex", "alignItems": "baseline", "flexWrap": "wrap",
    })


# ── Track content callback ────────────────────────────────────
@app.callback(
    Output("track-content", "children"),
    Input("track-circuit-select", "value"),
    Input("track-year-select",    "value"),
)
def update_track_content(circuit_key: str, hist_year: int):
    if not circuit_key or CIRCUIT_CHARS.empty:
        return html.P("Select a circuit.", style={"color": TEXT_DIM})

    row = CIRCUIT_CHARS[CIRCUIT_CHARS["circuit_key"] == circuit_key]
    if row.empty:
        return html.P("Circuit not found.", style={"color": TEXT_DIM})
    row = row.iloc[0]

    meta = _FF1_CIRCUIT_META.get(circuit_key, {})
    corners_list = _NOTABLE_CORNERS.get(circuit_key, [])

    # ── Section 0: Season banner (which season this tab shows) ─
    _avail_years = _track_avail_years()
    current_season = max(_avail_years) if _avail_years else None
    display_season = _circuit_display_season(circuit_key, _avail_years)
    is_loaded_circuit = (_loaded_circuit_key() == circuit_key)
    season_banner = _track_season_banner(hist_year, current_season, display_season,
                                         is_loaded_circuit)

    # ── Section 1: Header ─────────────────────────────────────
    header = html.Div([
        html.H3(row["grand_prix_fr"],
                style={"color": TEXT_MAIN, "fontWeight": "900", "letterSpacing": "2px",
                       "marginBottom": "2px", "fontSize": "1.15rem"}),
        html.Span(row["circuit_type_en"],
                  style={"color": ACCENT, "fontWeight": "700", "fontSize": "0.82rem",
                         "letterSpacing": "1px"}),
        html.Span(f"  ·  Overall demand: {row['overall_demand_score']}/4",
                  style={"color": TEXT_DIM, "fontSize": "0.78rem", "marginLeft": "8px"}),
    ], style={"marginBottom": "16px"})

    # ── Section 2: Stats pills row ────────────────────────────
    stats_pills = html.Div([
        _stat_pill("LENGTH",    f"{meta.get('length_km','—')} km"),
        _stat_pill("CORNERS",   str(meta.get("corners", "—"))),
        _stat_pill("DRS ZONES", str(meta.get("drs_zones", "—")), "#00D2BE"),
        _stat_pill("LAP RECORD",
                   f"{meta.get('lap_record','—')}  ({meta.get('lap_record_driver','—')}, {meta.get('lap_record_year','—')})",
                   "#FFD700"),
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"})

    # ── Section 3: Characteristics grid + radar ───────────────
    dims = [
        ("Average Speed",     row["avg_speed_label"],       row["avg_speed_score"]),
        ("Full Throttle",     row["full_throttle_label"],   row["full_throttle_score"]),
        ("Lateral Load",      row["lateral_load_label"],    row["lateral_load_score"]),
        ("Tyre Degradation",  row["tyre_deg_label"],        row["tyre_deg_score"]),
        ("Tyre Difficulty",   row["tyre_difficulty_label"], row["tyre_difficulty_score"]),
    ]
    chars_rows = [
        html.Div([
            html.Span(label, style={"color": TEXT_DIM, "fontSize": "0.75rem",
                                     "width": "160px", "display": "inline-block",
                                     "fontWeight": "600"}),
            _score_badge(val, score),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "8px"})
        for label, val, score in dims
    ]
    if row.get("notes"):
        chars_rows.append(html.P(
            f"Note: {row['notes']}",
            style={"color": TEXT_DIM, "fontSize": "0.7rem", "marginTop": "6px",
                   "fontStyle": "italic"},
        ))

    radar_fig = _radar_chart(row)

    chars_block = dbc.Row([
        dbc.Col([
            html.P("CIRCUIT CHARACTERISTICS",
                   style={"color": TEXT_DIM, "fontSize": "0.65rem", "letterSpacing": "2px",
                           "fontWeight": "700", "marginBottom": "12px"}),
            html.Div(chars_rows),
        ], md=6),
        dbc.Col([
            html.P("DEMAND PROFILE",
                   style={"color": TEXT_DIM, "fontSize": "0.65rem", "letterSpacing": "2px",
                           "fontWeight": "700", "marginBottom": "4px"}),
            dcc.Graph(figure=radar_fig, config=GFX),
        ], md=6),
    ])

    # ── Section 4: Notable corners ────────────────────────────
    if corners_list:
        corner_pills = html.Div(
            [html.Span(c, style={
                "background": CARD_BG, "border": f"1px solid {GRID_CLR}",
                "borderRadius": "4px", "padding": "3px 10px",
                "fontSize": "0.72rem", "marginRight": "6px",
                "marginBottom": "6px", "display": "inline-block",
                "color": TEXT_MAIN,
            }) for c in corners_list],
            style={"marginTop": "6px"},
        )
        corners_section = card(
            "Notable Corners",
            corner_pills,
        )
    else:
        corners_section = html.Div()


    # ── Section 6: Track map (corner layout + gear shifts) ───
    # (Race tyre strategy moved to the dedicated RACE tab.)
    # Pre-load the map when it is already cached on disk (the loaded meeting's
    # map is warmed at data-load time), so it appears without a button click.
    preloaded_map, _tm_season, _tm_event = _cached_track_map(circuit_key, hist_year)
    track_map_section = card(
        "Track Map — Layout, Sectors, Gears, Elevation & DRS",
        info=("Data: the fastest qualifying lap's telemetry line for this circuit "
              "(FastF1) shown four ways — layout with numbered corners (names on "
              "hover), the start/finish line and timing sectors; gear per point; "
              "elevation/relief from the line's altitude; and DRS / active-aero "
              "zones. Note: elevation is the racing-line altitude, so it shows "
              "relief and gradient (climbs/descents) but not lateral banking."),
        children=html.Div([
            html.P([
                "Circuit layout (corners + sectors + start/finish), gears, "
                "elevation/relief and DRS / active-aero zones, built from the "
                "fastest qualifying lap (FastF1 telemetry). "
                + ("Pre-loaded from cache below."
                   if preloaded_map is not None else
                   "The first build for a circuit downloads telemetry (1–3 min); "
                   "it is cached afterwards for instant reuse."),
            ], style={"color": TEXT_DIM, "fontSize": "0.8rem", "marginBottom": "10px"}),
            dbc.Button("Regenerate track map" if preloaded_map is not None
                       else "Generate track map",
                       id="track-map-btn",
                       color="info", outline=True, size="sm",
                       style={"fontWeight": "700"}),
            dcc.Loading(
                type="circle", color=ACCENT,
                children=html.Div(preloaded_map, id="track-map-content",
                                  style={"marginTop": "12px"}),
            ),
        ]),
    )

    # ── Section 7: Historical leaderboards ───────────────────
    hist_blocks = []
    if hist_year and not HIST_RACE.empty and not HIST_QUALI.empty:
        hist_keys = HIST_CIRCUIT_KEY_MAP.get(circuit_key, [circuit_key])

        def _filter_circuit(df):
            if df.empty or "circuit_key" not in df.columns:
                return pd.DataFrame()
            return df[df["circuit_key"].isin(hist_keys)].copy()

        race_df  = _filter_circuit(HIST_RACE)
        quali_df = _filter_circuit(HIST_QUALI)

        avail_years_race  = sorted(race_df["season"].unique(), reverse=True)  if not race_df.empty  else []
        avail_years_quali = sorted(quali_df["season"].unique(), reverse=True) if not quali_df.empty else []

        for sess_type, df_h, avail_y in [
            ("Race",        race_df,  avail_years_race),
            ("Qualifying",  quali_df, avail_years_quali),
        ]:
            year_to_show = hist_year if hist_year in avail_y else (avail_y[0] if avail_y else None)
            if year_to_show is None:
                hist_blocks.append(card(
                    f"Historical {sess_type} Results",
                    html.P(f"No historical {sess_type.lower()} data for this circuit yet. "
                           "Run fetch_historical_results.py to populate.",
                           style={"color": TEXT_DIM, "fontStyle": "italic"}),
                ))
                continue

            tbl = _hist_table(df_h, sess_type, year_to_show)
            bar = _hist_leaderboard(df_h, sess_type, year_to_show)

            year_selector = dbc.Row([
                dbc.Col(
                    html.Div([
                        html.Span("Season: ", style={"color": TEXT_DIM, "fontSize": "0.72rem"}),
                        *[html.Span(
                            str(y),
                            style={
                                "color": ACCENT if y == year_to_show else TEXT_DIM,
                                "fontWeight": "700" if y == year_to_show else "400",
                                "fontSize": "0.78rem", "marginLeft": "8px",
                                "cursor": "default",
                                "borderBottom": f"2px solid {ACCENT}" if y == year_to_show else "none",
                            }
                        ) for y in avail_y],
                    ]),
                    md=12,
                ),
            ], className="mb-2")

            hist_blocks.append(card(
                f"Historical {sess_type} Results  —  {circuit_key.replace('_',' ').title()}  ({year_to_show})",
                html.Div([
                    year_selector,
                    dcc.Graph(figure=bar, config=GFX) if bar.data else html.Div(),
                    html.Div(style={"height": "8px"}),
                    tbl,
                ]),
                info=(f"Data: the official {sess_type.lower()} classification for this "
                      "circuit in the selected season, from the historical results "
                      "archive (fetch_historical_results.py). Bars are ordered by "
                      "finishing/grid position and team-coloured; hover for time and "
                      "gap. Why: historical context for how this circuit usually "
                      "races and who has gone well here."),
            ))
    elif HIST_RACE.empty and HIST_QUALI.empty:
        hist_blocks.append(dbc.Alert(
            "Historical results not loaded. Run fetch_historical_results.py first.",
            color="secondary",
            style={"fontSize": "0.8rem"},
        ))

    # ── Assemble ──────────────────────────────────────────────
    return html.Div([
        season_banner,
        header,
        stats_pills,
        card("Circuit Profile", chars_block,
             info=("Data: the circuit's demand ratings (average speed, full throttle, "
                   "lateral load, tyre degradation, tyre difficulty), each scored 1–4 "
                   "from data/circuit_characteristics.csv and drawn as a radar. Why: a "
                   "fingerprint of what a track demands — useful context for why pace "
                   "and tyre behaviour differ between venues.")),
        corners_section,
        track_map_section,
        *hist_blocks,
    ])


# ── Keep the season selector in step with the circuit ────────
@app.callback(
    Output("track-year-select", "value"),
    Input("track-circuit-select", "value"),
)
def _sync_track_year(circuit_key):
    """When the circuit changes, pick the season the whole page should show:
    current if that GP has run, else N-1 — so every plot stays aligned."""
    season = _circuit_display_season(circuit_key)
    return season if season is not None else no_update


# ── Track-map callback (on-demand FastF1 fetch + render) ─────
@app.callback(
    Output("track-map-content", "children"),
    Input("track-map-btn",      "n_clicks"),
    State("track-circuit-select", "value"),
    State("track-year-select",    "value"),
    prevent_initial_call=True,
)
def render_track_map(_n, circuit_key, year):
    if not circuit_key:
        return dbc.Alert("Select a circuit first.", color="warning",
                         style={"fontSize": "0.8rem"})

    season, event_name = _resolve_track_event(circuit_key, year)
    if not event_name:
        return dbc.Alert(
            "Couldn't map this circuit to a FastF1 event (no historical entry). "
            "Track maps need a season with results for this circuit.",
            color="warning", style={"fontSize": "0.8rem"})

    tm = None
    last_exc = None
    for sess_id in ("Q", "R"):           # quali gives the cleanest fast lap; fall back to race
        try:
            tm = get_track_map(season, event_name, sess_id)
            if tm is not None:
                break
        except Exception as exc:
            last_exc = exc
    if tm is None:
        msg = f"No telemetry available for {event_name} {season}."
        if last_exc:
            msg += f"  ({last_exc})"
        return dbc.Alert(msg, color="danger", style={"fontSize": "0.8rem"})

    return _track_map_children(tm, season, event_name, circuit_key)


if __name__=="__main__":
    import os
    _port = int(os.environ.get("PORT", "8050"))
    app.run(debug=True, host="0.0.0.0", port=_port)