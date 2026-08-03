"""
F1 Dashboard – app.py 
Run:   python app.py
Open:  http://127.0.0.1:8050
"""
from __future__ import annotations
import logging, sys, warnings, re

# Register this module under its import name immediately. The app runs as
# `python app.py`, so this module is "__main__" — without the alias, the lazy
# `import app` in f1lib/standings.py and tabs/telemetry.py RE-EXECUTES this
# whole file (second Dash instance, second initial_load()) the first time it
# runs, silently reloading the boot event over whatever the user had loaded.
sys.modules.setdefault("app", sys.modules[__name__])
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

from f1lib.config import (
    TEAM_COLORS, COMPOUND_COLORS,
    DARK_BG, CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
    SPEED_PERCENTILE, MINI_SECTORS, get_min_laps_for_compound,
    MIN_LAPS_SOFT, MIN_LAPS_MEDIUM, MIN_LAPS_HARD,
    HISTORICAL_DIR, FASTF1_CACHE_DIR,
)
from f1lib.data_loader import load_sessions, is_cached, list_cached_sessions
from f1lib.radio_loader import load_race_radio, race_radio_available, radio_cached
from f1lib.pitstops_loader import load_pitstops
from f1lib.processing import (
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
import f1lib.state as state
from f1lib.state import rebuild_state, SESSION_INFO_LIST
state.register(globals())

# ── Initial load (default sessions) ──────────────────────────
# initial_load falls back to the previous completed event when the newest
# one has no published data yet (live weekend) instead of crashing.
print("Loading sessions (cache-first)…")
state.initial_load()


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
from f1lib.standings import (
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
from tabs.upgrades import upgrade_impact_section, upgrade_event_detail, upgrades_df
from tabs.season import tab_season, tab_context
from tabs.qualifying import tab_quali
from tabs.fingerprints import fingerprint_section
print(f"Team upgrades           : {len(upgrades_df()):,} rows")

# circuit_characteristics.csv uses French slugs (e.g. "monaco", "etats_unis")
# while fetch_historical_results.py slugifies the official English event name
# (e.g. "monaco_grand_prix", "united_states_grand_prix"). The bridge map lives
# in config.py so compute_circuit_characteristics.py can share it.
from f1lib.config import HIST_CIRCUIT_KEY_MAP
from f1lib.standings import (
    _slugify_event, _loaded_event, _loaded_circuit_key,
    _track_avail_years, _circuit_race_years, _circuit_display_season,
)


# ── Theme & shared UI building blocks (components.py) ────────
# Pure presentation helpers live in components.py so tab modules can import
# them without touching app.py. The aliases keep existing call sites working.
from f1lib.components import (
    BASE, theme, card, kpi, GFX, TABLE_STYLE, styled_table,
    badge as _badge, abbr as _abbr, hex_to_rgba as _hex_to_rgba,
    TEAM_ABBR as _TEAM_ABBR,
)
from f1lib.glossary import gloss

# ── Shared chart builders & aggregations (figures.py) ────────
# (team_metrics / tmgaps are imported directly by the tab modules)
from f1lib.figures import (
    _add_flag_bands, _rain_lap_groups, _add_rain_bands, _lap_evolution_fig,
)

# ── App layout ───────────────────────────────────────────────
# compress=True (flask-compress): tab-layout responses reach ~5 MB of raw
# figure JSON — gzip/brotli cuts them ~10×, which is what remote users on the
# Tailscale funnel actually feel.
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG],
                title="F1 Dashboard", suppress_callback_exceptions=True,
                compress=True)

# ── Serve cached team-radio mp3s (so html.Audio can play them) ──
from flask import send_from_directory, abort
from f1lib.config import RADIO_DIR as _RADIO_DIR
_RADIO_ABS = Path(_RADIO_DIR).resolve()

@app.server.route("/radio/<path:clip>")
def _serve_radio(clip):
    # clip is "<season>__<meeting>__Race/<file>.mp3"; keep it inside RADIO_DIR
    target = (_RADIO_ABS / clip).resolve()
    if not str(target).startswith(str(_RADIO_ABS)) or not target.exists():
        abort(404)
    return send_from_directory(target.parent, target.name)

# Sidebar (event picker + team/driver/session filters + quick-select buttons)
# lives in tabs/sidebar.py; its callbacks register on import.
from tabs.sidebar import build_sidebar

# The main tab bar. "Optional / archived" tabs (currently only DATA QUALITY)
# are kept out of the primary row: they are still real dbc.Tabs — so they can
# be made active and rendered normally — but hidden from the bar with
# display:none and surfaced instead through the "+" dropdown after the last tab.
_ARCHIVED_TABS = [
    ("tab-data", "DATA QUALITY"),
]
_ARCHIVED_IDS = {tid for tid, _ in _ARCHIVED_TABS}

TABS = dbc.Tabs([
    dbc.Tab(label="SEASON",         tab_id="tab-season"),
    dbc.Tab(label="TRACK",          tab_id="tab-track"),
    dbc.Tab(label="WEEK END PRED",  tab_id="tab-weekend"),
    dbc.Tab(label="TELEMETRY",      tab_id="tab-laps"),
    dbc.Tab(label="STINTS",         tab_id="tab-stints"),
    dbc.Tab(label="QUALI",          tab_id="tab-quali"),
    dbc.Tab(label="RACE",           tab_id="tab-race"),
    dbc.Tab(label="DUEL",           tab_id="tab-duel"),
    dbc.Tab(label="TEAM & TEAMATE", tab_id="tab-teams"),
    dbc.Tab(label="CONTEXT",        tab_id="tab-context"),
    # Archived tabs live in the bar but are hidden; the "+" menu selects them.
    *[dbc.Tab(label=lbl, tab_id=tid, tab_style={"display": "none"})
      for tid, lbl in _ARCHIVED_TABS],
], id="tabs", active_tab="tab-season")

# "+" dropdown holding the optional / archived tabs, pinned after the last tab.
_MORE_MENU = dbc.DropdownMenu(
    label="+",
    id="more-tabs-menu",
    nav=False, in_navbar=False, right=True,
    toggle_style={"color": TEXT_DIM, "background": "transparent",
                  "border": "none", "fontSize": "1.2rem", "fontWeight": "700",
                  "padding": "2px 12px", "lineHeight": "1"},
    children=[
        dbc.DropdownMenuItem("OPTIONAL / ARCHIVED", header=True),
        *[dbc.DropdownMenuItem(lbl, id={"type": "more-tab", "tab": tid},
                               n_clicks=0)
          for tid, lbl in _ARCHIVED_TABS],
    ],
)

_TAB_BAR = html.Div(
    [html.Div(TABS, style={"flex": "1", "minWidth": "0"}), _MORE_MENU],
    style={"display": "flex", "alignItems": "flex-end",
           "borderBottom": f"2px solid {ACCENT}", "marginBottom": "16px"})

def _main_col() -> dbc.Col:
    return dbc.Col([
    html.Div([
        html.H2("F1 SESSION ANALYSIS",
                style={"color":ACCENT,"fontWeight":"900","letterSpacing":"3px","marginBottom":"4px","fontSize":"1.3rem"}),
        # Source / support links, pinned to the top-right of the dashboard.
        html.Div([
            html.A(html.Img(src=app.get_asset_url("github.svg"),
                            style={"height":"22px"}),
                   href="https://github.com/sophiegonzalez3/F1", target="_blank",
                   title="Source on GitHub",
                   style={"color":TEXT_DIM,"marginRight":"16px","display":"inline-flex"}),
            html.A(html.Img(src=app.get_asset_url("kofi.svg"),
                            style={"height":"22px"}),
                   href="https://ko-fi.com/sophiegonzalez3", target="_blank",
                   title="Support me on Ko-fi",
                   style={"display":"inline-flex"}),
        ], style={"display":"flex","alignItems":"center"}),
    ], style={"display":"flex","justifyContent":"space-between",
              "alignItems":"flex-start"}),
    html.P(" | ".join(state.SESSIONS), id="main-subtitle",
           style={"color":TEXT_DIM,"marginBottom":"18px","fontSize":"0.78rem"}),
    _TAB_BAR,
    dcc.Loading(html.Div(id="tab-content"), type="default",
                color=ACCENT, delay_show=250),
], width=10, style={"padding":"24px","background":DARK_BG,"minHeight":"100vh"})


def _layout():
    """Evaluated on every page load (Dash callable-layout), so the sidebar's
    event picker / filter values and the subtitle always reflect the currently
    loaded event — a static layout would show the boot event after a browser
    refresh that follows a runtime event switch."""
    return dbc.Container(
        dbc.Row([build_sidebar(app.get_asset_url("f1_logo.svg")), _main_col()],
                className="g-0"),
        fluid=True, style={"background": DARK_BG, "fontFamily": "Inter, sans-serif"})


app.layout = _layout

# ── Routing callback ─────────────────────────────────────────
# Tab layouts are memoized per (tab, filters, data generation): switching back
# to an already-visited tab is instant instead of rebuilding every figure.
# DATA_GENERATION is bumped by rebuild_state so a session reload invalidates
# everything. tab-data is never memoized (it shows live load/cache status).
from collections import OrderedDict as _OrderedDict
_TAB_RENDER_MEMO: _OrderedDict = _OrderedDict()
# Sized to hold one full prewarm sweep (9 tabs) plus a couple of
# filter-variant leftovers before LRU eviction kicks in.
_TAB_MEMO_MAX = 24


def _memo_key(tab, ss, sd, st):
    key = (tab, tuple(ss), tuple(sd), tuple(st), DATA_GENERATION)
    if tab == "tab-quali":
        # the 3D replay's default cars follow the last DUEL pair — a QUALI
        # layout memoized under an older pair must not be served
        import tabs.duel as _duel_mod
        key = key + (_duel_mod.LAST_PAIR,)
    return key


# ── Background tab prewarm ───────────────────────────────────
# First-visit builds measured at 0.7–4.3 s per tab (RACE 4.3 s, WEEK END
# PRED 3.7 s, TELEMETRY 3.4 s). After every render (page open, data load,
# filter change) a daemon thread quietly builds the not-yet-memoized tabs
# for the current filters, so by the time the user clicks one it is served
# from the memo. Heaviest tabs first; a newer schedule or a data reload
# cancels the sweep (results from a stale world are dropped).
_PREWARM_TABS = ("tab-race", "tab-weekend", "tab-laps", "tab-teams",
                 "tab-season", "tab-stints", "tab-quali", "tab-track",
                 "tab-duel", "tab-context")
_prewarm_seq = 0


def _schedule_tab_prewarm(ss, sd, st, skip=None, delay=0.75):
    global _prewarm_seq
    _prewarm_seq += 1
    my_seq = _prewarm_seq
    gen = state.DATA_GENERATION
    ss, sd, st = list(ss), list(sd), list(st)

    def _worker():
        from time import sleep, perf_counter
        sleep(delay)                       # let the interactive request finish
        for tab in _PREWARM_TABS:
            if my_seq != _prewarm_seq or gen != state.DATA_GENERATION:
                return                     # superseded — stop the sweep
            if tab == skip:
                continue
            key = _memo_key(tab, ss, sd, st)
            if key in _TAB_RENDER_MEMO:
                continue
            t0 = perf_counter()
            try:
                out = _render_tab(tab, ss, sd, st)
            except Exception as exc:
                print(f"prewarm {tab}: failed ({exc})", flush=True)
                continue
            if gen != state.DATA_GENERATION:
                return                     # data reloaded mid-build — drop it
            _TAB_RENDER_MEMO[key] = out
            while len(_TAB_RENDER_MEMO) > _TAB_MEMO_MAX:
                _TAB_RENDER_MEMO.popitem(last=False)
            print(f"prewarm {tab}: built in {(perf_counter()-t0)*1000:.0f} ms",
                  flush=True)
            sleep(0.1)                     # breathe between builds

    import threading
    threading.Thread(target=_worker, daemon=True, name="tab-prewarm").start()


def _section_header(title, intro):
    """A centered section title + intro paragraph, used to separate the two
    stacked halves of a merged tab (TEAM & TEAMATE, WEEK END PRED)."""
    return html.Div([
        html.H3(title,
                style={"color": TEXT_MAIN, "fontWeight": "900",
                       "letterSpacing": "3px", "textAlign": "center",
                       "marginBottom": "10px", "fontSize": "1.5rem",
                       "borderBottom": f"2px solid {ACCENT}",
                       "paddingBottom": "10px"}),
        # Div, not P: the intro may splice in gloss() tooltips (which render a
        # sibling block element) and a <div> inside a <p> is invalid HTML.
        html.Div(intro,
                 style={"color": TEXT_DIM, "fontSize": "0.82rem",
                        "textAlign": "center", "maxWidth": "780px",
                        "margin": "0 auto 22px", "lineHeight": "1.5"}),
    ])


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
    if tab=="tab-teams":
        # Merged TEAM & TEAMATE tab: team-analysis content first, then the
        # head-to-head teammate content stacked below, each under its own
        # section header + intro.
        return html.Div([
            _section_header(
                "TEAM COMPARISON AND MOMENTUM",
                ["How the teams stack up against each other across the loaded "
                 "sessions — ", *gloss("one-lap pace", "one-lap"), " and ",
                 *gloss("race pace"), ", ", *gloss("sector"), " strengths, and "
                 "which way each team's form is trending. Every metric takes the "
                 "stronger of a team's two cars, so this is the ",
                 *gloss("constructor"), "-vs-constructor view of the field's "
                 "pecking order and who is gaining or losing ground."]),
            tab_teams(fl_d, fs_d),
            html.Hr(style={"borderColor": GRID_CLR, "margin": "40px 0 28px"}),
            _section_header(
                "TEAMMATES COMPARISON AND MOMENTUM",
                ["Now zoom inside each garage: the head-to-head duel between the "
                 "two ", *gloss("teammate", "drivers sharing identical machinery"),
                 ". Because the car is a constant, these gaps isolate the "
                 "driver — ", *gloss("qualifying"), " pace, ",
                 *gloss("race pace"), ", and how momentum swings from one side "
                 "of the garage to the other across the weekend."]),
            tab_teammates(fl_d, fs_d),
        ])
    if tab=="tab-stints":     return tab_stints(fl_d,fs_d)
    if tab=="tab-weekend":
        # Merged WEEK END PRED tab: practice content first, then the pre-event
        # brief stacked below.
        # Practice construction / sandbagging adapts to whichever sessions are
        # selected, so unchecking Qualifying/Race lets you preview the mid-event
        # ("after FP2" / "after FP3") picture even on a fully-cached weekend.
        wl = laps[laps["session_name"].isin(ss) & laps["Driver_Short"].isin(sd)
                  & laps["Team"].isin(st)].copy()
        return html.Div([
            _section_header(
                "EVENT UPGRADES",
                ["What each team physically brought to this ",
                 *gloss("grand prix", "meeting"), " — the FIA Car Presentation "
                 "breakdown, component by component. The season-long 'did it "
                 "actually work?' analysis lives in the SEASON tab."]),
            upgrade_event_detail(team_rank=_team_champ_rank()),
            html.Hr(style={"borderColor": GRID_CLR, "margin": "40px 0 28px"}),
            _section_header(
                "PRACTICE CONSTRUCTION",
                ["How the weekend is being built. The ", *gloss("lap time",
                 "lap-time"), " distributions and one-lap-vs-race-pace matrix "
                 "show each driver's raw shape and consistency across the "
                 "sessions loaded, while pace progression tracks how the ",
                 *gloss("quali sim", "quali-sim"), " order firms up from FP1 to ",
                 *gloss("qualifying"), ". All from clean, valid laps."]),
            tab_practice_construction(wl),
            html.Hr(style={"borderColor": GRID_CLR, "margin": "40px 0 28px"}),
            _section_header(
                [*gloss("sandbagging", "SANDBAGGING"), " DETECTOR"],
                ["Who is holding pace back. Working from clean laps expressed as "
                 "a ", *gloss("gap to the field"), " — which cancels out track "
                 "evolution — it reads the 'pace in hand' between ",
                 *gloss("one-lap pace", "one-lap"), " and race runs, banked time "
                 "never assembled into a lap, and once qualifying loads how much "
                 "pace was actually unlocked. Inferential by nature: these are "
                 "corroborating signals, not verdicts."]),
            tab_sandbagging(wl),
            html.Hr(style={"borderColor": GRID_CLR, "margin": "40px 0 28px"}),
            _section_header(
                "WEEKEND PACE PREDICTION",
                ["The model's answer to 'who will be quick?'. Starting from an "
                 "era-aware season-form prior and sharpening after every ",
                 *gloss("practice"), " session, it projects the ",
                 *gloss("qualifying"), " order with uncertainty, tracks how that "
                 "call has moved session to session, and — once quali or the "
                 "race lands — keeps score against what actually happened."]),
            tab_brief(sd, st),
        ])
    if tab=="tab-quali":      return tab_quali()
    if tab=="tab-race":       return tab_race(sd, st)
    if tab=="tab-duel":       return tab_duel(sd, st)
    if tab=="tab-track":      return tab_track_info()
    if tab=="tab-season":
        return tab_season(
            standings=_season_standings_row(fl_d),
            upgrades=upgrade_impact_section(),
        )
    if tab=="tab-context":    return tab_context()
    return html.P("Select a tab.")


@app.callback(Output("tabs", "active_tab"),
              Input({"type": "more-tab", "tab": ALL}, "n_clicks"),
              prevent_initial_call=True)
def _select_archived_tab(_clicks):
    """Clicking an item in the '+' menu activates that hidden/archived tab."""
    trig = ctx.triggered_id
    if not trig or not any(_clicks):
        return no_update
    return trig["tab"]


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
        out = _render_tab(tab, ss, sd, st)
        _schedule_tab_prewarm(ss, sd, st)
        return out
    key = _memo_key(tab, ss, sd, st)
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
    _schedule_tab_prewarm(ss, sd, st, skip=tab)
    return out

from tabs.overview import tab_overview
from tabs.teams import tab_teams
from tabs.telemetry import tab_laps, _prewarm_track_maps
from tabs.practice import tab_practice_construction, tab_sandbagging
from tabs.stints import tab_stints
from tabs.teammates import tab_teammates

from tabs.race import tab_race
from tabs.brief import tab_brief
from tabs.duel import tab_duel

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