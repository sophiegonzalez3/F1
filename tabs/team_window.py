"""TEAM & TEAMATE tab shell — the "last N events" window slider.

Both halves of the tab (tabs/teams.py, tabs/teammates.py) read the per-event
KPI table (data/driver_event_kpis.csv, f1lib/driver_kpis.py), never the
loaded laps: the window ends at the event loaded in the sidebar and reaches
back N race weekends, stopping at round 1 of that season.

The slider lives in the tab layout; the body is (re)built by a callback, so
moving the slider never re-renders the rest of the app. `persistence` keeps
the chosen N when a sidebar filter rebuilds the tab.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd
from dash import html, dcc, callback, Input, Output, State

import f1lib.state as state
from f1lib.components import section_header
from f1lib.config import CURRENT_SEASON, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR, CARD_BG
from f1lib.driver_kpis import load_kpis, window_rounds
from f1lib.glossary import gloss
from tabs.pace_data import active_selection, event_short

DEFAULT_N = 3


@lru_cache(maxsize=1)
def _calendar() -> pd.DataFrame:
    try:
        return pd.read_csv("data/season_calendar.csv")
    except Exception:
        return pd.DataFrame(columns=["season", "round", "event"])


def loaded_season_round() -> tuple[int, int]:
    """(season, round) of the event loaded in the sidebar. The window ends at
    the latest round of the KPI table at or before it, so loading a weekend
    whose race has not run yet ends the window at the previous race."""
    season, meeting = CURRENT_SEASON, None
    if state.LOADED_SESSION_INFO:
        info = state.LOADED_SESSION_INFO[0]
        season, meeting = int(info["SEASON"]), info["MEETING"]
    cal = _calendar()
    hit = cal[(cal["season"] == season) & (cal["event"] == meeting)]
    if not hit.empty:
        return season, int(hit["round"].iloc[0])
    k = load_kpis()
    rs = k.loc[k["season"] == season, "round"] if not k.empty else []
    return season, int(max(rs)) if len(rs) else 0


def tab_team_window():
    season, rnd = loaded_season_round()
    rounds = window_rounds(load_kpis(), season, rnd, 0)
    if not rounds:
        return html.P(f"No completed race weekends for {season} in "
                      "data/driver_event_kpis.csv — run "
                      "scripts/compute_driver_event_kpis.py.",
                      style={"color": TEXT_DIM})
    n_max = len(rounds)
    marks = {i: {"label": str(i), "style": {"color": TEXT_DIM}}
             for i in range(1, n_max + 1)}
    slider = html.Div([
        html.Div([
            html.Span("WINDOW", style={"color": ACCENT, "fontWeight": "800",
                                       "letterSpacing": "2px", "fontSize": "0.8rem",
                                       "marginRight": "10px"}),
            html.Span(f"last N race weekends of {season}, ending at the event "
                      "loaded in the sidebar (never reaches back past round 1)",
                      style={"color": TEXT_DIM, "fontSize": "0.75rem"}),
        ], style={"marginBottom": "6px"}),
        dcc.Slider(id="tt-window", min=1, max=n_max, step=1,
                   value=min(DEFAULT_N, n_max), marks=marks,
                   persistence=True, persistence_type="session"),
        html.Div(id="tt-window-label",
                 style={"color": TEXT_MAIN, "fontSize": "0.8rem",
                        "textAlign": "center", "marginTop": "4px"}),
    ], style={"background": CARD_BG, "border": f"1px solid {GRID_CLR}",
              "borderRadius": "8px", "padding": "12px 18px 8px",
              "marginBottom": "22px", "position": "sticky", "top": "0",
              "zIndex": 5})
    return html.Div([
        slider,
        dcc.Loading(html.Div(id="tt-body"), type="dot", color=ACCENT),
    ])


def _window_frame(season: int, rnd: int, n: int, teams, drivers):
    k = load_kpis()
    rs = window_rounds(k, season, rnd, n)
    w = k[(k["season"] == season) & k["round"].isin(rs)].copy()
    if teams:
        w = w[w["team"].isin(teams)]
    if drivers:
        w = w[w["driver"].isin(drivers)]
    return w, rs


@callback(Output("tt-body", "children"), Output("tt-window-label", "children"),
          Input("tt-window", "value"),
          State("driver-filter", "value"), State("team-filter", "value"))
def _render_body(n, sd, st):
    from tabs.teams import tab_teams
    from tabs.teammates import tab_teammates
    season, rnd = loaded_season_round()
    teams = active_selection(st, state.TEAMS)
    drivers = active_selection(sd, state.DRIVERS)
    w, rs = _window_frame(season, rnd, int(n or DEFAULT_N), teams, drivers)
    if w.empty:
        return html.P("No data in this window for the current filter.",
                      style={"color": TEXT_DIM}), ""
    ev = (w.drop_duplicates("round").set_index("round")["event"].to_dict())
    first, last = min(rs), max(rs)
    label = (f"{len(rs)} event{'s' if len(rs) > 1 else ''}: "
             f"R{first} {event_short(ev.get(first, ''), season)}"
             + (f"  →  R{last} {event_short(ev.get(last, ''), season)}"
                if last != first else ""))
    body = html.Div([
        section_header(
            "TEAM COMPARISON",
            ["How the teams stack up across the window — ",
             *gloss("one-lap speed", "one-lap"), " and ", *gloss("race pace"),
             ", running, pit work and race-day gains. Each metric is shown "
             "twice: the left column takes the stronger of a team's two cars, "
             "the right column averages both, so the difference between the "
             "columns is the gap inside the garage."]),
        tab_teams(w, season),
        html.Hr(style={"borderColor": GRID_CLR, "margin": "40px 0 28px"}),
        section_header(
            "TEAMMATES COMPARISON",
            ["Now zoom inside each garage: the head-to-head duel between the "
             "two ", *gloss("teammate", "drivers sharing identical machinery"),
             ", over the weekends in the window where BOTH drove. Because the "
             "car is a constant, these gaps isolate the driver and the "
             "environment around them — crew, strategy, luck."]),
        tab_teammates(w, season),
    ])
    return body, label
