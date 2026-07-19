"""
Global sidebar — event picker + team / driver / session filters.

Extracted from app.py after the beta feedback round: the filter dropdowns
gained All/None quick-select buttons (the 20-chip driver list was painful to
edit one chip at a time), the team filter gained Top/Mid/Back tier buttons
driven by the loaded season's championship standings, and the event picker is
now available here so switching events no longer requires the DATA tab.

build_sidebar() returns the dbc.Col. The quick-select and event-picker
callbacks live here; the actual event load stays in tabs/data.py
(load_selected), which listens to both the DATA-tab and the sidebar buttons.
"""
from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import html, dcc, callback, ctx, no_update, Input, Output, State

import f1lib.state as state
from f1lib.config import ACCENT, TEXT_DIM, GRID_CLR, CURRENT_SEASON
from f1lib.data_loader import season_meetings
from f1lib.standings import _season_team_tiers
from tabs.data import _event_option_label, SELECTABLE_SEASONS

_LBL = {"color": TEXT_DIM, "fontSize": "0.68rem", "letterSpacing": "2px"}
_DD  = {"backgroundColor": "#111", "fontSize": "0.78rem"}
_HR  = {"borderColor": GRID_CLR}
_BTN = {"fontSize": "0.6rem", "padding": "1px 7px", "letterSpacing": "1px"}


def _mini_btn(label: str, bid: str) -> dbc.Button:
    return dbc.Button(label, id=bid, size="sm", outline=True, color="secondary",
                      style=_BTN)


def _btn_row(*buttons) -> html.Div:
    return html.Div(list(buttons),
                    style={"display": "flex", "flexWrap": "wrap",
                           "gap": "4px", "margin": "6px 0 0"})


def _tip(bid: str, text: str) -> dbc.Tooltip:
    # dbc.Tooltip, never title= — see assets/tooltips.css (Safari/touch).
    return dbc.Tooltip(text, target=bid, placement="bottom",
                       delay={"show": 250, "hide": 50}, class_name="app-tooltip")


def _loaded_event() -> tuple[int, str | None]:
    if state.LOADED_SESSION_INFO:
        info = state.LOADED_SESSION_INFO[0]
        return int(info["SEASON"]), info["MEETING"]
    return CURRENT_SEASON, None


def build_sidebar(logo_src: str) -> dbc.Col:
    season, meeting = _loaded_event()
    if season not in SELECTABLE_SEASONS:
        season = SELECTABLE_SEASONS[0]
    try:
        meetings = season_meetings(season)
    except Exception:
        meetings = [meeting] if meeting else []

    return dbc.Col([html.Div([
        html.Img(src=logo_src, style={"height": "34px", "marginBottom": "18px"}),
        html.Hr(style=_HR),

        # ── Event picker (same load pipeline as the DATA tab) ─
        html.P("EVENT", style=_LBL),
        dcc.Dropdown(id="side-season-select",
            options=[{"label": str(y), "value": y} for y in SELECTABLE_SEASONS],
            value=season, clearable=False, style=_DD),
        dcc.Dropdown(id="side-event-select",
            options=[{"label": _event_option_label(m), "value": m} for m in meetings],
            value=meeting if meeting in meetings else (meetings[-1] if meetings else None),
            clearable=False, optionHeight=26,
            style={**_DD, "marginTop": "6px"}),
        dbc.Button("⟳  LOAD EVENT", id="side-load-btn", color="danger", size="sm",
                   style={"fontWeight": "700", "width": "100%", "marginTop": "8px",
                          "fontSize": "0.7rem", "letterSpacing": "1px"}),
        _tip("side-load-btn",
             "Load every available session of the selected event (practice, "
             "quali, sprint, race). Cached events load instantly; new ones "
             "fetch from FastF1 (1–3 min per session). Full details and cache "
             "status live in the DATA tab."),
        dcc.Loading(html.Div(
            html.Div(f"● {meeting} {season}" if meeting else "● no event loaded",
                     style={"color": "#00D2BE", "fontSize": "0.68rem"}),
            id="side-load-status", style={"marginTop": "6px"}),
            type="dot", color=ACCENT),
        html.Hr(style=_HR),

        # ── Team filter + quick selects ───────────────────────
        html.P("TEAMS", style=_LBL),
        dcc.Dropdown(id="team-filter",
            options=[{"label": t, "value": t} for t in state.TEAMS],
            value=list(state.TEAMS), multi=True, placeholder="Type to search…",
            style=_DD),
        _btn_row(_mini_btn("ALL",  "team-all-btn"),
                 _mini_btn("NONE", "team-none-btn"),
                 _mini_btn("TOP",  "team-top-btn"),
                 _mini_btn("MID",  "team-mid-btn"),
                 _mini_btn("BACK", "team-back-btn")),
        _tip("team-none-btn",
             "Clear the selection to hand-pick teams. While nothing is "
             "selected, tabs show the full field."),
        _tip("team-top-btn",
             "Show only the top-field teams — the leading third of the loaded "
             "season's constructor championship (season-wide standings, not "
             "this event). Click again to restore all teams."),
        _tip("team-mid-btn",
             "Show only the midfield teams of the loaded season's constructor "
             "championship (season-wide standings, not this event). Click "
             "again to restore all teams."),
        _tip("team-back-btn",
             "Show only the backfield teams — the bottom third of the loaded "
             "season's constructor championship (season-wide standings, not "
             "this event). Click again to restore all teams."),
        html.Hr(style=_HR),

        # ── Driver filter + quick selects ─────────────────────
        html.P("DRIVERS", style=_LBL),
        dcc.Dropdown(id="driver-filter",
            options=[{"label": d, "value": d} for d in state.DRIVERS],
            value=list(state.DRIVERS), multi=True, placeholder="Type to search…",
            style=_DD),
        _btn_row(_mini_btn("ALL",  "drv-all-btn"),
                 _mini_btn("NONE", "drv-none-btn")),
        _tip("drv-none-btn",
             "Clear the selection, then type in the box above to search and "
             "add drivers one by one. While nothing is selected, tabs show "
             "the full field."),
        html.Hr(style=_HR),

        # SESSIONS is the least-frequently changed filter, so it sits at the
        # bottom of the panel below the teams/drivers selectors.
        html.P("SESSIONS", style=_LBL),
        dcc.Checklist(id="session-filter",
            options=[{"label": s, "value": s} for s in state.SESSIONS],
            value=list(state.SESSIONS),
            inputStyle={"marginRight": "8px", "accentColor": ACCENT},
            labelStyle={"display": "block", "marginBottom": "8px",
                        "fontSize": "0.78rem"}),
    ], style={"padding": "16px", "height": "100vh", "overflowY": "auto",
              "background": "#09091A", "borderRight": f"1px solid {GRID_CLR}"})],
    width=2, style={"padding": "0"})


# ── Sidebar event picker: season switch rebuilds the event list ──
@callback(
    Output("side-event-select", "options"),
    Output("side-event-select", "value"),
    Input("side-season-select", "value"),
    prevent_initial_call=True,
)
def side_update_events(season):
    try:
        meetings = season_meetings(int(season))
    except Exception:
        meetings = []
    return ([{"label": _event_option_label(m), "value": m} for m in meetings],
            meetings[-1] if meetings else None)


# ── Driver quick select (All / None) ─────────────────────────
@callback(
    Output("driver-filter", "value", allow_duplicate=True),
    Input("drv-all-btn",  "n_clicks"),
    Input("drv-none-btn", "n_clicks"),
    State("driver-filter", "options"),
    prevent_initial_call=True,
)
def driver_quick_select(_a, _n, options):
    if ctx.triggered_id == "drv-none-btn":
        return []
    return [o["value"] for o in (options or [])]


# ── Team quick select (All / None / championship tiers) ──────
@callback(
    Output("team-filter", "value", allow_duplicate=True),
    Input("team-all-btn",  "n_clicks"),
    Input("team-none-btn", "n_clicks"),
    Input("team-top-btn",  "n_clicks"),
    Input("team-mid-btn",  "n_clicks"),
    Input("team-back-btn", "n_clicks"),
    State("team-filter", "options"),
    State("team-filter", "value"),
    prevent_initial_call=True,
)
def team_quick_select(_a, _n, _t, _m, _b, options, value):
    all_teams = [o["value"] for o in (options or [])]
    trig = ctx.triggered_id
    if trig == "team-all-btn":
        return all_teams
    if trig == "team-none-btn":
        return []
    tier_key = {"team-top-btn": "top", "team-mid-btn": "mid",
                "team-back-btn": "back"}[trig]
    tier = [t for t in _season_team_tiers().get(tier_key, []) if t in all_teams]
    if not tier:
        return no_update       # no standings for the loaded season
    # Tier click narrows to that tier; a second click on the same tier
    # restores the full field (add extra teams via the dropdown itself).
    if set(value or []) == set(tier):
        return all_teams
    return [t for t in all_teams if t in tier]
