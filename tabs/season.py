"""
SEASON tab — championship-long form view.

Answers "who's trending up?" across a whole season instead of one weekend:
team qualifying pace gap and race pace gap round by round, the cumulative
points race, and each team's Saturday-vs-Sunday character. All of it reads
data/team_pace_by_event.csv (compute_team_pace.py); no session loads.
"""
from __future__ import annotations

import base64
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc

from f1lib.components import theme, card, GFX, abbr
from f1lib.glossary import gloss
from f1lib.config import TEAM_COLORS, TEXT_DIM, TEXT_MAIN, GRID_CLR, ACCENT
from tabs.pace_data import team_pace_df, seasons, event_short, season_calendar_df
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
from tabs.season_intro import season_intro_block


def _team_order(s: pd.DataFrame) -> list[str]:
    """Teams ordered by final championship points (best first)."""
    last = s.sort_values("round").groupby("team")["cum_points"].last()
    return list(last.sort_values(ascending=False).index)


def _round_axis(s: pd.DataFrame) -> tuple[list[int], list[str]]:
    ev = s.drop_duplicates("round").sort_values("round")
    return ev["round"].tolist(), [event_short(e) for e in ev["event"]]


def _trend_fig(s: pd.DataFrame, ycol: str, ytitle: str,
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
    theme(fig, height)
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
    theme(fig, height)
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
    theme(fig, height)
    fig.update_xaxes(title_text="Avg qualifying gap to pole (%)")
    fig.update_yaxes(title_text="Avg race-pace gap to best (%)")
    return fig


# ── Season calendar ribbon ───────────────────────────────────
_SPRINT_CLR = "#FFB300"          # gold — sprint weekends
_COUNTRY_ISO2 = {
    "Abu Dhabi": "AE", "United Arab Emirates": "AE", "Australia": "AU",
    "Austria": "AT", "Azerbaijan": "AZ", "Bahrain": "BH", "Belgium": "BE",
    "Brazil": "BR", "Canada": "CA", "China": "CN", "France": "FR",
    "Germany": "DE", "Great Britain": "GB", "United Kingdom": "GB",
    "Hungary": "HU", "Italy": "IT", "Japan": "JP", "Mexico": "MX",
    "Monaco": "MC", "Netherlands": "NL", "Portugal": "PT", "Qatar": "QA",
    "Russia": "RU", "Saudi Arabia": "SA", "Singapore": "SG", "Spain": "ES",
    "Turkey": "TR", "United States": "US",
}


_FLAG_DIR = Path("assets/flags")
_flag_uri_cache: dict[str, str | None] = {}


def _flag_uri(country: str) -> str | None:
    """data:-URI for a country's flag SVG (assets/flags/<iso2>.svg), so flags
    render identically on every OS — Windows Chrome has no flag-emoji glyphs.
    None when the country is unmapped or the asset is missing."""
    iso = _COUNTRY_ISO2.get(str(country))
    if not iso:
        return None
    iso = iso.lower()
    if iso not in _flag_uri_cache:
        p = _FLAG_DIR / f"{iso}.svg"
        if p.exists():
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
            _flag_uri_cache[iso] = f"data:image/svg+xml;base64,{b64}"
        else:
            _flag_uri_cache[iso] = None
    return _flag_uri_cache[iso]


def _calendar_fig(cal: pd.DataFrame, height: int = 210) -> go.Figure:
    """Horizontal Jan→Dec ribbon: one date-positioned marker per round.
    Solid = already run, outline = upcoming; red = Grand Prix, gold = sprint;
    a dotted line marks today. Detail lives in the hover card."""
    cal = cal.copy()
    cal["x"] = pd.to_datetime(cal["event_date"], errors="coerce")
    cal = cal[cal["x"].notna()].sort_values("round")
    fig = go.Figure()
    if cal.empty:
        theme(fig, height)
        return fig

    today = pd.Timestamp.now().normalize()
    is_past = cal["x"] < today
    is_sprint = cal["sprint"].astype(bool)
    base = np.where(is_sprint, _SPRINT_CLR, ACCENT)

    fill = np.where(is_past, base, "rgba(0,0,0,0)")
    line_w = np.where(is_past, 1.0, 2.0)
    fmt = np.where(is_sprint, "Sprint weekend", "Grand Prix")
    pretty = cal["x"].dt.strftime("%a %d %b %Y")

    customdata = np.stack([
        cal["round"].astype(int), cal["event"].map(event_short),
        cal["location"], cal["country"], pretty, fmt,
    ], axis=-1)

    fig.add_hline(y=0, line=dict(color=GRID_CLR, width=2))
    fig.add_trace(go.Scatter(
        x=cal["x"], y=np.zeros(len(cal)), mode="markers+text",
        text=cal["round"].astype(int), textposition="middle center",
        textfont=dict(size=10, color=TEXT_MAIN, family="Arial Black"),
        marker=dict(size=24, color=fill, line=dict(color=base, width=line_w)),
        customdata=customdata, showlegend=False,
        hovertemplate=("<b>R%{customdata[0]} · %{customdata[1]} GP</b><br>"
                       "%{customdata[2]}, %{customdata[3]}<br>"
                       "%{customdata[4]}<br>%{customdata[5]}<extra></extra>"),
    ))
    # Real flag image above each round, short event name below. A wide box +
    # sizing="contain" makes the flag height-limited, so every flag renders the
    # same height regardless of the season's date span.
    pad = pd.Timedelta(days=10)
    span_ms = (cal["x"].max() - cal["x"].min() + 2 * pad).total_seconds() * 1000
    for _, r in cal.iterrows():
        xs = r["x"].isoformat()
        uri = _flag_uri(r["country"])
        if uri:
            fig.add_layout_image(dict(
                source=uri, xref="x", yref="y", x=xs, y=0.72,
                sizex=span_ms * 0.035, sizey=0.42, xanchor="center",
                yanchor="middle", sizing="contain", layer="above"))
        fig.add_annotation(x=xs, y=0, yshift=-26, textangle=-45,
                           text=event_short(r["event"]), showarrow=False,
                           xanchor="right", font=dict(size=9, color=TEXT_DIM))

    if cal["x"].min() <= today <= cal["x"].max():
        fig.add_vline(x=today.isoformat(), line=dict(color=ACCENT, width=1.5,
                      dash="dot"))
        fig.add_annotation(x=today.isoformat(), y=1, yref="paper", yshift=6,
                           text="TODAY", showarrow=False, xanchor="center",
                           font=dict(size=9, color=ACCENT, family="Arial Black"))

    # Legend key (marker-only dummy traces).
    for name, clr, hollow in (("Grand Prix", ACCENT, False),
                              ("Sprint", _SPRINT_CLR, False),
                              ("Upcoming", TEXT_DIM, True)):
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name=name, hoverinfo="skip",
            marker=dict(size=11, line=dict(color=clr, width=2),
                        color="rgba(0,0,0,0)" if hollow else clr)))

    theme(fig, height)
    fig.update_xaxes(type="date", dtick="M1", tickformat="%b", title_text=None,
                     showgrid=True, gridcolor=GRID_CLR,
                     range=[(cal["x"].min() - pad).isoformat(),
                            (cal["x"].max() + pad).isoformat()])
    fig.update_yaxes(visible=False, range=[-1.3, 1.3], fixedrange=True)
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=40),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0,
                                  xanchor="right", x=1.0))
    return fig


def _calendar_ribbon(season: int):
    cal = season_calendar_df()
    cal = cal[cal["season"] == season] if not cal.empty else cal
    if cal.empty:
        return None
    return card(
        "Season Calendar",
        dcc.Graph(figure=_calendar_fig(cal), config=GFX),
        info=("Data: the full season schedule (round, circuit, date and "
              "sprint/normal format) from data/season_calendar.csv "
              "(scripts/fetch_calendar.py). Solid markers are rounds already "
              "run, outlines are still to come; gold marks a sprint weekend "
              "and the dotted line is today. Date-proportional spacing shows "
              "the season's rhythm — back-to-back triple-headers cluster, the "
              "summer break opens a gap. Hover a round for the detail."),
    )


# ── Plain-English "bottom line" readings (newcomer layer) ────
# Data-driven one-liners: they read the same season table the charts draw from
# and state, in plain words, what the picture is actually saying — for a viewer
# who can't yet read a pace-gap chart. See f1lib/glossary.py for the term layer.

def _fmt_team(t) -> str:
    t = str(t)
    for suf in (" F1 Team", " Racing"):
        if t.endswith(suf):
            t = t[: -len(suf)]
    return t


def _fastest_team(s: pd.DataFrame, col: str):
    """Team with the smallest average gap in `col` (= quickest). None if empty."""
    avg = s.groupby("team")[col].mean().dropna().sort_values()
    return None if avg.empty else avg.index[0]


def _points_plain(s: pd.DataFrame):
    last = (s.sort_values("round").groupby("team")["cum_points"].last()
            .sort_values(ascending=False))
    if last.empty:
        return None
    leader, pts = _fmt_team(last.index[0]), last.iloc[0]
    n = int(s["round"].max())
    tail = (" The team with the most points at the end of the year wins the "
            "Constructors' title.")
    if len(last) >= 2:
        margin, second = pts - last.iloc[1], _fmt_team(last.index[1])
        if margin >= 1:
            return (f"{n} rounds in, {leader} lead with {pts:.0f} points — "
                    f"{margin:.0f} ahead of {second}.{tail}")
        return (f"{n} rounds in, {leader} and {second} are locked together at "
                f"the top on about {pts:.0f} points.{tail}")
    return f"{leader} lead with {pts:.0f} points.{tail}"


def _quali_plain(s: pd.DataFrame):
    fastest = _fastest_team(s, "quali_gap_pct")
    if fastest is None:
        return None
    return (f"Over a single flat-out lap this season, {_fmt_team(fastest)} have "
            "been the quickest car on average — the strongest qualifiers, so "
            "they tend to line up near the front for the race.")


def _race_plain(s: pd.DataFrame, quali_fastest):
    fastest = _fastest_team(s, "race_pace_gap_pct")
    if fastest is None:
        return None
    if quali_fastest is not None and fastest != quali_fastest:
        tail = (f" — a different car than the one-lap pacesetter "
                f"({_fmt_team(quali_fastest)}), so watch them recover ground "
                "over a race.")
    else:
        tail = (" — the same car that tops one-lap pace, the mark of an "
                "all-round-strong package.")
    return (f"Over long runs on wearing tyres, {_fmt_team(fastest)} have the "
            f"best race pace on average{tail}")


def _character_plain(s: pd.DataFrame):
    avg = (s.groupby("team")[["quali_gap_pct", "race_pace_gap_pct"]]
           .mean().dropna())
    if avg.empty:
        return None
    gain = (avg["quali_gap_pct"] - avg["race_pace_gap_pct"]).sort_values(
        ascending=False)
    if gain.iloc[0] > 0.05:
        return (f"Teams below the dotted line race better than they qualify. "
                f"{_fmt_team(gain.index[0])} gain the most on Sundays — gentler "
                "on their tyres and stronger with a heavy fuel load than their "
                "Saturday pace suggests.")
    return ("Most teams sit close to the line — about as strong in the race as "
            "they are in qualifying.")


def _season_content(season: int) -> html.Div:
    df = team_pace_df()
    s = df[df["season"] == season]
    if s.empty:
        return html.P("No pace data for this season — run compute_team_pace.py.",
                      style={"color": TEXT_DIM})
    n_race = s["race_pace_gap_pct"].notna().sum()
    quali_fastest = _fastest_team(s, "quali_gap_pct")
    # The season-calendar ribbon now lives at the top of the tab, above the
    # championship standings (see tab_season) — not here in SEASON FORM.
    return html.Div([
        card(
            [*gloss("qualifying", "Qualifying"), " ",
             *gloss("one-lap pace", "Pace"), " Gap by Round"],
            dcc.Graph(figure=_trend_fig(
                s, "quali_gap_pct", "Gap to pole (%)"), config=GFX),
            info=("Data: each team's best single qualifying lap (best of "
                  "Q1/Q2/Q3 across both drivers) as % gap to pole, every "
                  "round of the season, from the results archive. Why: the "
                  "cleanest read of raw car pace over a season — development "
                  "trends, upgrades working (or not), and who is closing on "
                  "whom. Click the legend to isolate teams."),
            plain=_quali_plain(s),
        ),
        card(
            [*gloss("race pace", "Race Pace"), " Gap by Round"],
            dcc.Graph(figure=_trend_fig(
                s, "race_pace_gap_pct", "Gap to best (%)"), config=GFX)
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
            plain=_race_plain(s, quali_fastest),
        ),
        card(
            [*gloss("constructor", "Constructors'"), " ",
             *gloss("points", "Points"), " Race"],
            dcc.Graph(figure=_points_fig(s), config=GFX),
            info=("Data: cumulative constructor points (race + sprint) after "
                  "each round. Why: the championship story in one picture — "
                  "where gaps opened, and whether pace trends above are "
                  "converting into points."),
            plain=_points_plain(s),
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
            plain=_character_plain(s),
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
    # Newcomer front door (Option C): the season story + collapsible "New to
    # F1?" primer, pinned above everything. Always about the latest season.
    if yrs:
        parts.append(season_intro_block(max(yrs)))
    if standings is not None:
        # Season calendar ribbon sits just above the championship leaderboard —
        # the season's shape (when/where races happen, what's still to come)
        # before the table of who's currently winning it.
        cal_card = _calendar_ribbon(max(yrs)) if yrs else None
        parts += [
            *([cal_card] if cal_card is not None else []),
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
