"""
F1 Dashboard – app.py 
Run:   python app.py
Open:  http://127.0.0.1:8050
"""
from __future__ import annotations
import logging, warnings, re
# Silence the known-noisy categories from the pandas/fastf1 stack only.
# Anything else (RuntimeWarning, SettingWithCopyWarning, …) should surface:
# it usually points at a real bug rather than upstream churn.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

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
from radio_loader import load_race_radio, race_radio_available, radio_cached
from pitstops_loader import load_pitstops
from processing import (
    clean_and_enrich_laps, analyze_stints,
    identify_quali_sim_laps, best_laps_table,
    format_lap_time, enrich_telemetry, flag_perturbed_laps,
    enrich_track_evolution, field_deg_curves,
    detect_stint_cliffs, compound_offsets, flag_dirty_air,
    enrich_weather, enrich_track_limits,
    enrich_blue_flags, enrich_session_results,
    flag_position_changes, clipped_range,
    detect_wet_crossover, dirty_air_penalty, traffic_exposure_curve,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

# ── Application data state ────────────────────────────────────
# state.py owns the loaded-session data and the enrichment pipeline.
# register(globals()) mirrors the state names (laps, stints, SESSIONS, …)
# into this module on every rebuild, so the existing bare-name references
# below keep working. New code should read state.laps etc. directly.
import state
from state import rebuild_state, SESSION_INFO_LIST
state.register(globals())

# ── Initial load (default sessions) ──────────────────────────
print("Loading sessions (cache-first)…")
rebuild_state(SESSION_INFO_LIST)


# ── Circuit characteristics reference table ───────────────────
_CIRCUIT_CHARS_PATH = Path("data/circuit_characteristics.csv")
try:
    CIRCUIT_CHARS = pd.read_csv(_CIRCUIT_CHARS_PATH, encoding="utf-8-sig")
    print(f"Circuit characteristics: {len(CIRCUIT_CHARS)} circuits loaded")
except FileNotFoundError:
    CIRCUIT_CHARS = pd.DataFrame()
    print("WARNING: data/circuit_characteristics.csv not found — Track Info tab will be limited")

# Overlay telemetry-measured scores where available (written by
# compute_circuit_characteristics.py). Speed / throttle / lateral / deg become
# measured values; tyre difficulty and circuit type stay hand-scored.
_CIRCUIT_COMPUTED_PATH = Path("data/circuit_characteristics_computed.csv")
if not CIRCUIT_CHARS.empty and _CIRCUIT_COMPUTED_PATH.exists():
    try:
        _comp = pd.read_csv(_CIRCUIT_COMPUTED_PATH)
        _ovr_cols = ["avg_speed_label", "avg_speed_score",
                     "full_throttle_label", "full_throttle_score",
                     "lateral_load_label", "lateral_load_score",
                     "tyre_deg_label", "tyre_deg_score"]
        _sc_cols = ["avg_speed_score", "full_throttle_score",
                    "lateral_load_score", "tyre_deg_score",
                    "tyre_difficulty_score"]
        _n_applied = 0
        for _, _crow in _comp.iterrows():
            _mask = CIRCUIT_CHARS["circuit_key"] == _crow["circuit_key"]
            if not _mask.any():
                continue
            for _c in _ovr_cols:
                if _c in _comp.columns and pd.notna(_crow.get(_c)):
                    CIRCUIT_CHARS.loc[_mask, _c] = _crow[_c]
            CIRCUIT_CHARS.loc[_mask, "overall_demand_score"] = round(
                CIRCUIT_CHARS.loc[_mask, _sc_cols].astype(float).mean(axis=1).iloc[0], 1)
            _prov = (f"speed/throttle/lateral/deg measured from "
                     f"{int(_crow['season'])} telemetry")
            _old_note = str(CIRCUIT_CHARS.loc[_mask, "notes"].iloc[0] or "")
            if "measured from" not in _old_note:
                CIRCUIT_CHARS.loc[_mask, "notes"] = (
                    (_old_note + "; " if _old_note and _old_note != "nan" else "")
                    + _prov)
            _n_applied += 1
        print(f"Circuit characteristics: measured scores applied to "
              f"{_n_applied} circuits")
    except Exception as _exc:
        print(f"Circuit characteristics: computed overlay failed ({_exc})")

# ── DATA tab (selection + quality + their two callbacks) ─────
from tabs.data import tab_data_selection, tab_data_quality

# ── Historical archive & championship standings (standings.py) ──
from standings import (
    HIST_RACE, HIST_QUALI, HIST_SPRINT, HIST_STANDINGS, HIST_DRIVER_STANDINGS,
    _loaded_meeting_season_round, _standings_after_round, _round_points_for,
    _prev_round, _team_champ_rank, _order_teams_by_champ, _dense_rank_by_pts,
    _driver_standings_after_round, _driver_round_points,
    _standings_leaderboard_body, _driver_standings_widget,
    _constructor_standings_widget, _season_standings_row,
    _championship_rank, _order_by_champ,
)

# ── Team car-development upgrades (per event) ─────────────────
# Curated table mirroring the FIA "Car Presentation" documents. Loader, column
# docs, and the UPGRADES tab live in tabs/upgrades.py (the extraction template
# for splitting further tabs out of this file — see tabs/__init__.py).
from tabs.upgrades import tab_upgrades, upgrades_df
from tabs.season import tab_season
from tabs.qualifying import tab_quali
from tabs.fingerprints import fingerprint_section
print(f"Team upgrades           : {len(upgrades_df()):,} rows")

# circuit_characteristics.csv uses French slugs (e.g. "monaco", "etats_unis")
# while fetch_historical_results.py slugifies the official English event name
# (e.g. "monaco_grand_prix", "united_states_grand_prix"). The bridge map lives
# in config.py so compute_circuit_characteristics.py can share it.
from config import HIST_CIRCUIT_KEY_MAP
from standings import (
    _slugify_event, _loaded_event, _loaded_circuit_key,
    _track_avail_years, _circuit_race_years, _circuit_display_season,
)


# ── Theme & shared UI building blocks (components.py) ────────
# Pure presentation helpers live in components.py so tab modules can import
# them without touching app.py. The aliases keep existing call sites working.
from components import (
    BASE, theme, card, kpi, GFX, TABLE_STYLE, styled_table,
    badge as _badge, abbr as _abbr, hex_to_rgba as _hex_to_rgba,
    TEAM_ABBR as _TEAM_ABBR,
)

# ── Shared chart builders & aggregations (figures.py) ────────
# (team_metrics / tmgaps are imported directly by the tab modules)
from figures import (
    _add_flag_bands, _rain_lap_groups, _add_rain_bands, _lap_evolution_fig,
)

# ── App layout ───────────────────────────────────────────────
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG],
                title="F1 Dashboard", suppress_callback_exceptions=True)

# ── Serve cached team-radio mp3s (so html.Audio can play them) ──
from flask import send_from_directory, abort
from config import RADIO_DIR as _RADIO_DIR
_RADIO_ABS = Path(_RADIO_DIR).resolve()

@app.server.route("/radio/<path:clip>")
def _serve_radio(clip):
    # clip is "<season>__<meeting>__Race/<file>.mp3"; keep it inside RADIO_DIR
    target = (_RADIO_ABS / clip).resolve()
    if not str(target).startswith(str(_RADIO_ABS)) or not target.exists():
        abort(404)
    return send_from_directory(target.parent, target.name)

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
    dbc.Tab(label="DATA",           tab_id="tab-data"),
    dbc.Tab(label="BRIEF",          tab_id="tab-brief"),
    dbc.Tab(label="TRACK",          tab_id="tab-track"),
    dbc.Tab(label="SEASON",         tab_id="tab-season"),
    dbc.Tab(label="TEAM ANALYSIS",  tab_id="tab-teams"),
    dbc.Tab(label="TELEMETRY",      tab_id="tab-laps"),
    dbc.Tab(label="STINTS",         tab_id="tab-stints"),
    dbc.Tab(label="PRACTICE",       tab_id="tab-practice"),
    dbc.Tab(label="QUALI",          tab_id="tab-quali"),
    dbc.Tab(label="RACE",           tab_id="tab-race"),
    dbc.Tab(label="TEAMMATES",      tab_id="tab-teammates"),
], id="tabs", active_tab="tab-data",
   style={"borderBottom":f"2px solid {ACCENT}","marginBottom":"16px"})

MAIN = dbc.Col([
    html.H2("F1 SESSION ANALYSIS",
            style={"color":ACCENT,"fontWeight":"900","letterSpacing":"3px","marginBottom":"4px","fontSize":"1.3rem"}),
    html.P(" | ".join(SESSIONS), id="main-subtitle",
           style={"color":TEXT_DIM,"marginBottom":"18px","fontSize":"0.78rem"}),
    TABS,
    dcc.Loading(html.Div(id="tab-content"), type="default",
                color=ACCENT, delay_show=250),
], width=10, style={"padding":"24px","background":DARK_BG,"minHeight":"100vh"})

app.layout = dbc.Container(dbc.Row([SIDEBAR,MAIN],className="g-0"),
    fluid=True, style={"background":DARK_BG,"fontFamily":"Inter, sans-serif"})

# ── Routing callback ─────────────────────────────────────────
# Tab layouts are memoized per (tab, filters, data generation): switching back
# to an already-visited tab is instant instead of rebuilding every figure.
# DATA_GENERATION is bumped by rebuild_state so a session reload invalidates
# everything. tab-data is never memoized (it shows live load/cache status).
from collections import OrderedDict as _OrderedDict
_TAB_RENDER_MEMO: _OrderedDict = _OrderedDict()
_TAB_MEMO_MAX = 12


def _render_tab(tab, ss, sd, st):
    """Build a tab layout from scratch (the uncached path)."""
    fl   = laps[laps["session_name"].isin(ss)].copy()
    fl_d = fl[fl["Driver_Short"].isin(sd) & fl["Team"].isin(st)].copy()
    fs   = stints[stints["session_name"].isin(ss)].copy()
    fs_d = fs[fs["Driver_Short"].isin(sd) & fs["Team"].isin(st)].copy()
    if tab=="tab-data":
        return html.Div([
            tab_data_selection(),
            html.Hr(style={"borderColor": GRID_CLR, "margin": "28px 0 20px"}),
            html.H3("DATA QUALITY",
                    style={"color": TEXT_MAIN, "fontWeight": "900",
                           "letterSpacing": "3px", "textAlign": "center",
                           "marginBottom": "20px", "fontSize": "1.5rem",
                           "borderBottom": f"2px solid {ACCENT}",
                           "paddingBottom": "10px"}),
            tab_data_quality(fl_d, fs_d),
        ])
    if tab=="tab-laps":
        # the 2M+-row telemetry slice is only needed here —
        # filtering it lazily keeps every other tab switch cheap
        dnos = fl_d["DriverNo"].unique()
        ft   = (telemetry[telemetry["DriverNo"].isin(dnos)
                          & telemetry["session_name"].isin(ss)].copy()
                if not telemetry.empty else telemetry)
        # merged view: the session overview cards first, telemetry below
        return html.Div([tab_overview(fl_d, fs_d, ft), tab_laps(fl_d, ft)])
    if tab=="tab-teams":      return tab_teams(fl_d, fs_d)
    if tab=="tab-stints":     return tab_stints(fl_d,fs_d)
    if tab=="tab-practice":
        # Practice construction / sandbagging adapts to whichever sessions are
        # selected, so unchecking Qualifying/Race lets you preview the mid-event
        # ("after FP2" / "after FP3") picture even on a fully-cached weekend.
        wl = laps[laps["session_name"].isin(ss) & laps["Driver_Short"].isin(sd)
                  & laps["Team"].isin(st)].copy()
        return tab_practice(wl)
    if tab=="tab-quali":      return tab_quali()
    if tab=="tab-brief":      return tab_brief(sd, st)
    if tab=="tab-race":       return tab_race(sd, st)
    if tab=="tab-teammates":  return tab_teammates(fl_d,fs_d)
    if tab=="tab-track":      return tab_track_info()
    if tab=="tab-season":
        return tab_season(
            standings=_season_standings_row(fl_d),
            upgrades=tab_upgrades(team_rank=_team_champ_rank()),
        )
    return html.P("Select a tab.")


@app.callback(Output("tab-content","children"),
              Input("tabs","active_tab"),
              Input("session-filter","value"),
              Input("driver-filter","value"),
              Input("team-filter","value"))
def render(tab, ss, sd, st):
    from time import perf_counter
    t0 = perf_counter()
    ss=ss or SESSIONS; sd=sd or DRIVERS; st=st or TEAMS
    if tab == "tab-data":
        return _render_tab(tab, ss, sd, st)
    key = (tab, tuple(ss), tuple(sd), tuple(st), DATA_GENERATION)
    hit = key in _TAB_RENDER_MEMO
    if hit:
        _TAB_RENDER_MEMO.move_to_end(key)
        out = _TAB_RENDER_MEMO[key]
    else:
        out = _render_tab(tab, ss, sd, st)
        _TAB_RENDER_MEMO[key] = out
        while len(_TAB_RENDER_MEMO) > _TAB_MEMO_MAX:
            _TAB_RENDER_MEMO.popitem(last=False)
    print(f"render {tab}: {'memo hit' if hit else 'built'} "
          f"in {(perf_counter()-t0)*1000:.0f} ms", flush=True)
    return out

from tabs.overview import tab_overview
from tabs.teams import tab_teams
from tabs.telemetry import tab_laps, _prewarm_track_maps
from tabs.practice import tab_practice
from tabs.stints import tab_stints
from tabs.teammates import tab_teammates

from tabs.race import tab_race
from tabs.brief import tab_brief

from tabs.track import tab_track_info, get_track_map
import tabs.track as _track_mod
_track_mod.sync_circuit_chars(CIRCUIT_CHARS)

if __name__=="__main__":
    import os, sys
    _port  = int(os.environ.get("PORT", "8050"))
    # debug mode is opt-in: the reloader imports the app twice (two full data
    # loads at startup) and the dev server is slower. Normal use gets a
    # threaded server so long callbacks don't block the whole UI.
    _debug = "--debug" in sys.argv or os.environ.get("DASH_DEBUG") == "1"
    app.run(debug=_debug, threaded=True, host="0.0.0.0", port=_port)