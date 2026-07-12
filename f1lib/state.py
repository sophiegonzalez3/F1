"""
F1 Dashboard – application data state
=====================================
Single owner of the loaded-session data and the enrichment pipeline.

The Dash app is a set of modules that all read the same mutable dataset
(laps / stints / telemetry / …) which `rebuild_state` swaps out at runtime
from the Data Selection tab. Two ways to consume it:

1. **New code (preferred):** `import state` and read `state.laps`,
   `state.SESSIONS`, `state.DATA_GENERATION`, … — attribute access always
   sees the current data.

2. **Legacy code (app.py):** call `state.register(globals())` once at import
   time. The module's globals then receive the same names (`laps`, `stints`,
   `SESSIONS`, …) and are re-published on every rebuild, so the ~400 existing
   bare-name references keep working without a rename. Registration pushes
   the current snapshot immediately.

`DATA_GENERATION` increments on every successful rebuild — use it in cache
keys (the tab-render memo does) so a session reload invalidates them.
"""
from __future__ import annotations

import logging

from f1lib.config import CURRENT_SEASON
from f1lib.data_loader import load_sessions, most_recent_event
from f1lib.processing import (
    clean_and_enrich_laps, analyze_stints,
    identify_quali_sim_laps,
    enrich_telemetry, flag_perturbed_laps,
    enrich_track_evolution, flag_dirty_air,
    enrich_weather, enrich_track_limits,
    enrich_blue_flags, enrich_session_results,
    flag_position_changes,
)

logger = logging.getLogger(__name__)

# ── Sessions to load at startup ──────────────────────────────
# Preload every available session of the most recent event of the current
# season (even a mid-weekend one where only practice has run), discovered
# from the schedule rather than hard-coded. If discovery fails (offline with
# an empty cache), fall back to a known event so the app still boots.
_FALLBACK_SESSION_INFO = [
    {"SEASON": str(CURRENT_SEASON), "MEETING": "Australian Grand Prix", "SESSION": s}
    for s in ("Practice 1", "Practice 2", "Practice 3", "Qualifying", "Race")
]


def _default_session_info() -> list[dict]:
    try:
        season, meeting, info = most_recent_event(
            CURRENT_SEASON, fallback_seasons=(CURRENT_SEASON - 1, CURRENT_SEASON - 2))
        print(f"Startup event: {meeting} {season} — {len(info)} session(s)", flush=True)
        return info
    except Exception as exc:
        print(f"Startup event discovery failed ({exc}); using fallback event",
              flush=True)
        return list(_FALLBACK_SESSION_INFO)


SESSION_INFO_LIST = _default_session_info()

# ── Mutable application state ─────────────────────────────────
laps_raw = telemetry_raw = weather_raw = race_control_raw = results_raw = None
laps = stints = telemetry = None
SESSIONS = DRIVERS = COMPOUNDS = TEAMS = []
LOADED_SESSION_INFO: list[dict] = []        # the SESSION_INFO_LIST currently loaded
LAST_LOAD_MSG: str = ""                      # human-readable result of the last load
DATA_GENERATION: int = 0                     # bumped on every rebuild — cache keys

# Optional hook run after a successful rebuild (app.py sets this to the
# track-map prewarmer once that helper exists; None = skip).
post_load_hook = None

_PUBLISHED = ("laps_raw", "telemetry_raw", "weather_raw", "race_control_raw",
              "results_raw", "laps", "stints", "telemetry",
              "SESSIONS", "DRIVERS", "COMPOUNDS", "TEAMS",
              "LOADED_SESSION_INFO", "LAST_LOAD_MSG", "DATA_GENERATION")

_consumers: list[dict] = []


def register(module_globals: dict) -> None:
    """Mirror the published state names into a consumer module's globals,
    now and after every rebuild."""
    _consumers.append(module_globals)
    module_globals.update({k: globals()[k] for k in _PUBLISHED})


def _publish() -> None:
    snapshot = {k: globals()[k] for k in _PUBLISHED}
    for g in _consumers:
        g.update(snapshot)


def rebuild_state(session_info_list: list[dict], force_reload: bool = False) -> str:
    """
    Load the given sessions (cache-first) and run the full enrichment
    pipeline, reassigning the shared data state and republishing it to every
    registered consumer module.

    Returns a short human-readable status string (also stored in
    LAST_LOAD_MSG). Raises nothing — failures are reported in the string.
    """
    global laps_raw, telemetry_raw, weather_raw, race_control_raw, results_raw
    global laps, stints, telemetry
    global SESSIONS, DRIVERS, COMPOUNDS, TEAMS, LOADED_SESSION_INFO, LAST_LOAD_MSG
    global DATA_GENERATION

    if not session_info_list:
        LAST_LOAD_MSG = "No sessions selected — nothing loaded."
        _publish()
        return LAST_LOAD_MSG

    print(f"Loading {len(session_info_list)} session(s) (cache-first)…", flush=True)
    _data = load_sessions(session_info_list, force_reload=force_reload)
    _laps_raw = _data["laps"]
    if _laps_raw is None or _laps_raw.empty:
        LAST_LOAD_MSG = ("Load failed — no lap data returned for the selected "
                         "sessions (FastF1 fetch may have failed).")
        _publish()
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
    _laps = flag_dirty_air(_laps)
    _laps = enrich_track_evolution(_laps)
    _laps = enrich_session_results(_laps, _results_raw)
    _laps = flag_position_changes(_laps)
    _stints    = analyze_stints(_laps)
    _telemetry = enrich_telemetry(_telemetry_raw, _laps)

    # ── Commit + publish atomically (after all heavy work) ───
    laps_raw, telemetry_raw      = _laps_raw, _telemetry_raw
    weather_raw, race_control_raw, results_raw = _weather_raw, _race_control_raw, _results_raw
    laps, stints, telemetry      = _laps, _stints, _telemetry
    DATA_GENERATION += 1                      # invalidate generation-keyed caches
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
    _publish()

    # Warm the track-map / corner-marker cache for the loaded meeting(s) in
    # the background (hook is set by app.py once the helper exists; the very
    # first load runs before that, exactly as before the extraction).
    if post_load_hook is not None:
        post_load_hook(list(session_info_list))

    return LAST_LOAD_MSG
