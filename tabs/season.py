"""
SEASON tab — championship-long form view.

Answers "who's trending up?" across a whole season instead of one weekend:
team qualifying pace gap and race pace gap round by round, the cumulative
points race, and each team's Saturday-vs-Sunday character. All of it reads
data/team_pace_by_event.csv (compute_team_pace.py); no session loads.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc

from f1lib.components import theme, card, GFX, abbr
from f1lib.config import TEAM_COLORS, TEXT_DIM, TEXT_MAIN, GRID_CLR, ACCENT
from tabs.pace_data import team_pace_df, seasons, event_short
from tabs.regulations import regulations_block
from tabs.finance import finance_block, compliance_card
from tabs.hr import hr_section
from tabs.infrastructure import infrastructure_section
from tabs.reliability import reliability_card
from tabs.pu_pool import pu_pool_card
from tabs.driver_market import driver_market_card
from tabs.season_ops import (
    chaos_timeline_card, pit_league_card, lap1_league_card,
    pu_points_card, affinity_card, testing_card, penalties_card,
)


def _team_order(s: pd.DataFrame) -> list[str]:
    """Teams ordered by final championship points (best first)."""
    last = s.sort_values("round").groupby("team")["cum_points"].last()
    return list(last.sort_values(ascending=False).index)


def _round_axis(s: pd.DataFrame) -> tuple[list[int], list[str]]:
    ev = s.drop_duplicates("round").sort_values("round")
    return ev["round"].tolist(), [event_short(e) for e in ev["event"]]


def _trend_fig(s: pd.DataFrame, ycol: str, ytitle: str, title: str,
               height: int = 480) -> go.Figure:
    fig = go.Figure()
    rounds, labels = _round_axis(s)
    for team in _team_order(s):
        g = s[(s["team"] == team) & s[ycol].notna()].sort_values("round")
        if g.empty:
            continue
        clr = TEAM_COLORS.get(team, "#808080")
        fig.add_trace(go.Scatter(
            x=g["round"], y=g[ycol], mode="lines+markers", name=abbr(team),
            line=dict(color=clr, width=2), marker=dict(size=6, color=clr),
            customdata=np.stack([g["event"].map(event_short)], axis=-1),
            hovertemplate=(f"<b>{abbr(team)}</b> · %{{customdata[0]}}<br>"
                           f"{ytitle}: %{{y:.2f}}<extra></extra>"),
        ))
    theme(fig, height, title)
    fig.update_xaxes(tickmode="array", tickvals=rounds, ticktext=labels,
                     tickangle=-40, title_text=None)
    fig.update_yaxes(title_text=ytitle)
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0))
    return fig


def _points_fig(s: pd.DataFrame, height: int = 480) -> go.Figure:
    fig = go.Figure()
    rounds, labels = _round_axis(s)
    for team in _team_order(s):
        g = s[s["team"] == team].sort_values("round")
        clr = TEAM_COLORS.get(team, "#808080")
        fig.add_trace(go.Scatter(
            x=g["round"], y=g["cum_points"], mode="lines", name=abbr(team),
            line=dict(color=clr, width=2),
            customdata=np.stack([g["event"].map(event_short), g["points"]], axis=-1),
            hovertemplate=(f"<b>{abbr(team)}</b> · %{{customdata[0]}}<br>"
                           "Total: %{y:.0f} pts (+%{customdata[1]:.0f})"
                           "<extra></extra>"),
        ))
    theme(fig, height, "Constructors' points race")
    fig.update_xaxes(tickmode="array", tickvals=rounds, ticktext=labels,
                     tickangle=-40)
    fig.update_yaxes(title_text="Cumulative points")
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0))
    return fig


def _character_fig(s: pd.DataFrame, height: int = 520) -> go.Figure:
    """Season-average quali gap vs race-pace gap per team. The diagonal is
    'same car Saturday and Sunday'; below it = stronger in the race."""
    avg = (s.groupby("team")[["quali_gap_pct", "race_pace_gap_pct"]]
           .mean().dropna())
    fig = go.Figure()
    if not avg.empty:
        lim = float(max(avg.max().max(), 0.5)) * 1.15
        fig.add_trace(go.Scatter(
            x=[0, lim], y=[0, lim], mode="lines",
            line=dict(color=TEXT_DIM, width=1, dash="dot"),
            hoverinfo="skip", showlegend=False))
        for team, r in avg.iterrows():
            clr = TEAM_COLORS.get(team, "#808080")
            fig.add_trace(go.Scatter(
                x=[r["quali_gap_pct"]], y=[r["race_pace_gap_pct"]],
                mode="markers+text", text=[abbr(team)],
                textposition="top center", textfont=dict(size=10, color=clr),
                marker=dict(size=13, color=clr, line=dict(width=1, color="#000")),
                name=abbr(team), showlegend=False,
                hovertemplate=(f"<b>{abbr(team)}</b><br>"
                               "Avg quali gap: %{x:.2f}%<br>"
                               "Avg race gap: %{y:.2f}%<extra></extra>"),
            ))
        fig.add_annotation(x=lim * 0.97, y=lim * 0.80, text="better on Sunday ↓",
                           showarrow=False, font=dict(size=10, color=TEXT_DIM),
                           xanchor="right")
    theme(fig, height, "Saturday vs Sunday character — season averages")
    fig.update_xaxes(title_text="Avg qualifying gap to pole (%)")
    fig.update_yaxes(title_text="Avg race-pace gap to best (%)")
    return fig


def _season_content(season: int) -> html.Div:
    df = team_pace_df()
    s = df[df["season"] == season]
    if s.empty:
        return html.P("No pace data for this season — run compute_team_pace.py.",
                      style={"color": TEXT_DIM})
    n_race = s["race_pace_gap_pct"].notna().sum()
    return html.Div([
        card(
            "Qualifying Pace Gap by Round",
            dcc.Graph(figure=_trend_fig(
                s, "quali_gap_pct", "Gap to pole (%)",
                f"Qualifying gap to pole – {season}"), config=GFX),
            info=("Data: each team's best single qualifying lap (best of "
                  "Q1/Q2/Q3 across both drivers) as % gap to pole, every "
                  "round of the season, from the results archive. Why: the "
                  "cleanest read of raw car pace over a season — development "
                  "trends, upgrades working (or not), and who is closing on "
                  "whom. Click the legend to isolate teams."),
        ),
        card(
            "Race Pace Gap by Round",
            dcc.Graph(figure=_trend_fig(
                s, "race_pace_gap_pct", "Gap to best (%)",
                f"Race pace gap – {season}"), config=GFX)
            if n_race else
            html.P("No cached race laps for this season — run "
                   "fetch_previous_races.py, then compute_team_pace.py.",
                   style={"color": TEXT_DIM}),
            info=("Data: each team's best driver's median race lap — fuel- "
                  "and track-evolution-corrected, valid clean-air laps only "
                  "(≥10 laps) — as % gap to the event's fastest team. Only "
                  "rounds whose race laps are cached locally appear. Why: "
                  "Sunday car performance, free of qualifying engine modes "
                  "and low-fuel glory runs; compare with the qualifying "
                  "chart to spot one-lap vs race-run cars."),
        ),
        card(
            "Constructors' Points Race",
            dcc.Graph(figure=_points_fig(s), config=GFX),
            info=("Data: cumulative constructor points (race + sprint) after "
                  "each round. Why: the championship story in one picture — "
                  "where gaps opened, and whether pace trends above are "
                  "converting into points."),
        ),
        card(
            "Saturday vs Sunday Character",
            dcc.Graph(figure=_character_fig(s), config=GFX),
            info=("Data: season-average qualifying gap (x) vs season-average "
                  "race-pace gap (y) per team; the dotted diagonal means "
                  "'same relative pace both days'. Why: teams below the line "
                  "race better than they qualify (tyre-gentle, heavy-fuel "
                  "strong) — expect them to gain on Sundays; above the line "
                  "is a quali car that goes backwards in races."),
        ),
    ] + [c for c in (affinity_card(season), chaos_timeline_card(season),
                      pit_league_card(season), lap1_league_card(season),
                      testing_card(season),
                      reliability_card(season), penalties_card(season),
                      pu_pool_card(season), pu_points_card(season),
                      driver_market_card(season)) if c is not None])


def _section_header(title: str, subtitle: str) -> html.Div:
    """Big centred divider between the tab's major sections."""
    return html.Div([
        html.H3(title, style={
            "color": TEXT_MAIN, "fontWeight": "900", "letterSpacing": "3px",
            "textAlign": "center", "fontSize": "1.4rem",
            "borderBottom": f"2px solid {ACCENT}",
            "paddingBottom": "8px", "marginBottom": "4px"}),
        html.P(subtitle, style={"color": TEXT_DIM, "fontSize": "0.78rem",
                                "textAlign": "center",
                                "marginBottom": "18px"}),
    ], style={"marginTop": "26px"})


def tab_season(standings=None, upgrades=None) -> html.Div:
    """SEASON tab: championship standings up top (passed in by the router),
    then the season-long form charts, then the car-upgrades section."""
    yrs = seasons()
    form_block = (
        html.Div(dbc.Alert(
            ["No season pace table found. Generate it with ",
             html.Code("python compute_team_pace.py"), "."],
            color="warning"))
        if not yrs else
        html.Div([
            html.Div([
                html.Span("Form view", style={
                    "color": TEXT_MAIN, "fontWeight": "800",
                    "fontSize": "1.0rem", "marginRight": "16px"}),
                dcc.Dropdown(id="season-select",
                             options=[{"label": str(y), "value": y} for y in yrs],
                             value=max(yrs), clearable=False,
                             style={"width": "110px", "backgroundColor": "#111",
                                    "fontSize": "0.85rem"}),
            ], style={"display": "flex", "alignItems": "center",
                      "marginBottom": "16px"}),
            dcc.Loading(html.Div(_season_content(max(yrs)), id="season-content"),
                        type="default"),
        ])
    )
    parts = []
    if standings is not None:
        parts += [
            _section_header("CHAMPIONSHIP STANDINGS",
                            "drivers' and constructors' tables for the loaded "
                            "season · rank arrows show this event's effect"),
            standings,
        ]
    parts += [
        _section_header("SEASON FORM",
                        "pace gaps, points race and race-day character, "
                        "round by round"),
        form_block,
    ]
    parts += [
        _section_header("REGULATIONS & FINANCE",
                        "the budget cap, crash costs, wind-tunnel limits and "
                        "2026 rules that shape every upgrade decision"),
        regulations_block(),
        finance_block(),
    ]
    cap_card = compliance_card()
    if cap_card is not None:
        parts.append(cap_card)
    if upgrades is not None:
        parts += [
            _section_header("CAR UPGRADES",
                            "did the development pay off? — each team's pace "
                            "trend and the measured effect of every upgrade "
                            "package (per-event detail lives in WEEK END PRED)"),
            upgrades,
        ]
    parts += [
        _section_header("HR & PERSONNEL",
                        "the technical & management transfer market — who moved "
                        "where, and the gardening-leave gaps the budget-cap era "
                        "turned into a long-term form lever"),
        hr_section(),
    ]
    parts += [
        _section_header("INFRASTRUCTURE & GOVERNANCE",
                        "where each team designs its car — factory and "
                        "wind-tunnel capability — and the FIA technical "
                        "directives that reshape the rules mid-season"),
        infrastructure_section(),
    ]
    return html.Div(parts)


@callback(Output("season-content", "children"),
          Input("season-select", "value"),
          prevent_initial_call=True)
def _update_season(season):
    return _season_content(int(season))
