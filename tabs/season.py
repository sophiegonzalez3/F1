"""
SEASON tab — championship-long form view.

Answers "who's trending up?" across a whole season instead of one weekend:
team one-lap speed gap and race pace gap round by round, the cumulative
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

from f1lib.components import (
    theme, theme_axes, card, GFX, abbr, BASE, BASE_NO_AXES,
    hex_to_rgba as _hex_to_rgba,
)
from f1lib.glossary import gloss
from f1lib.config import TEAM_COLORS, TEXT_DIM, TEXT_MAIN, GRID_CLR, ACCENT
from tabs.pace_data import team_pace_df, seasons, event_short, season_calendar_df
from tabs.regulations import regulations_block
from tabs.finance import finance_block, compliance_card
from tabs.hr import hr_section
from tabs.infrastructure import infrastructure_section
from tabs.reliability import reliability_card, contact_card
from tabs.pu_pool import pu_pool_card
from tabs.gearbox_pool import gearbox_pool_card
from tabs.driver_market import driver_market_card
from tabs.season_ops import (
    chaos_timeline_card, pit_league_card, lap1_league_card,
    engine_championship_card, affinity_card, testing_card, penalties_card,
    session_weather_card,
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
               height: int = 480, median_ref: bool = False) -> go.Figure:
    """Per-round trend, one line per team.

    Rounds with no measurement are kept on the axis as NaN rather than filtered
    out, so Plotly BREAKS the line there (connectgaps defaults to False). The
    old behaviour dropped them and joined the surviving points with a straight
    segment, which drew an interpolated guess in the same ink as measured data.

    `median_ref=True` marks the y=0 line as "the median car" — the baseline for
    the field-median-relative pace measures, where negative means faster.
    """
    fig = go.Figure()
    rounds, labels = _round_axis(s)
    ev_by_round = (s.drop_duplicates("round").set_index("round")["event"]
                   .map(event_short))
    for team in _team_order(s):
        g = s[s["team"] == team].sort_values("round")
        if g[ycol].notna().sum() == 0:
            continue
        # reindex onto every round of the season so missing ones stay as holes
        g = (g.set_index("round").reindex(rounds).reset_index()
             .rename(columns={"index": "round"}))
        clr = TEAM_COLORS.get(team, "#808080")
        fig.add_trace(go.Scatter(
            x=rounds, y=g[ycol], mode="lines+markers", name=abbr(team),
            line=dict(color=clr, width=2), marker=dict(size=6, color=clr),
            connectgaps=False,
            customdata=np.stack([[ev_by_round.get(r, "") for r in rounds]],
                                axis=-1),
            hovertemplate=(f"<b>{abbr(team)}</b> · %{{customdata[0]}}<br>"
                           f"{ytitle}: %{{y:.2f}}<extra></extra>"),
        ))
    theme(fig, height)
    if median_ref:
        fig.add_hline(y=0, line=dict(color=TEXT_DIM, width=1, dash="dot"))
        fig.add_annotation(x=1, xref="paper", y=0, yshift=9, xanchor="right",
                           text="median car", showarrow=False,
                           font=dict(size=9, color=TEXT_DIM))
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


def _half_split(s: pd.DataFrame) -> tuple[list[int], list[int]]:
    """Split the rounds run so far into an early and a late half.

    The whole point of a mid-season review is 'has this changed?', which a
    season average cannot answer — so anything that wants to show movement
    splits here rather than collapsing the year into one number.
    """
    rounds = sorted(int(r) for r in s["round"].dropna().unique())
    if len(rounds) < 4:
        return rounds, []
    mid = len(rounds) // 2
    return rounds[:mid], rounds[mid:]


def _character_fig(s: pd.DataFrame, height: int = 520) -> go.Figure:
    """One-lap speed vs race pace per team, drawn as an ARROW from the first
    half of the season to the second. The diagonal is 'same car Saturday and
    Sunday'; below it = stronger over a stint than over one lap. A season
    average would hide exactly the thing worth seeing at the break — a team
    whose character changed."""
    early, late = _half_split(s)
    cols = ["onelap_speed_pct", "race_pace_pct"]
    avg = s.groupby("team")[cols].mean().dropna()
    e = s[s["round"].isin(early)].groupby("team")[cols].mean() if early else None
    l = s[s["round"].isin(late)].groupby("team")[cols].mean() if late else None

    fig = go.Figure()
    if avg.empty:
        theme(fig, height)
        return fig
    pts = [avg]
    if e is not None:
        pts.append(e.dropna())
    if l is not None:
        pts.append(l.dropna())
    allv = pd.concat(pts)
    lo = float(min(allv.min().min(), 0)) - 0.4
    hi = float(max(allv.max().max(), 0)) + 0.4
    fig.add_trace(go.Scatter(
        x=[lo, hi], y=[lo, hi], mode="lines",
        line=dict(color=TEXT_DIM, width=1, dash="dot"),
        hoverinfo="skip", showlegend=False))

    have_arrows = e is not None and l is not None and len(late) >= 2
    for team in avg.index:
        clr = TEAM_COLORS.get(team, "#808080")
        if have_arrows and team in e.index and team in l.index \
                and e.loc[team].notna().all() and l.loc[team].notna().all():
            x0, y0 = float(e.loc[team, cols[0]]), float(e.loc[team, cols[1]])
            x1, y1 = float(l.loc[team, cols[0]]), float(l.loc[team, cols[1]])
            # faint tail = where they were, solid head = where they are now
            fig.add_trace(go.Scatter(
                x=[x0, x1], y=[y0, y1], mode="lines",
                line=dict(color=_hex_to_rgba(clr, 0.5), width=2),
                hoverinfo="skip", showlegend=False))
            fig.add_trace(go.Scatter(
                x=[x0], y=[y0], mode="markers",
                marker=dict(size=6, color=_hex_to_rgba(clr, 0.35),
                            line=dict(width=0)),
                showlegend=False,
                hovertemplate=(f"<b>{abbr(team)}</b> · first half<br>"
                               "one-lap %{x:>+.2f}% · race %{y:>+.2f}%"
                               "<extra></extra>")))
            fig.add_annotation(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y",
                               axref="x", ayref="y", showarrow=True,
                               arrowhead=2, arrowsize=1.1, arrowwidth=2,
                               arrowcolor=clr, text="")
            hx, hy = x1, y1
        else:
            hx, hy = float(avg.loc[team, cols[0]]), float(avg.loc[team, cols[1]])
        fig.add_trace(go.Scatter(
            x=[hx], y=[hy], mode="markers+text", text=[abbr(team)],
            textposition="top center", textfont=dict(size=10, color=clr),
            marker=dict(size=13, color=clr, line=dict(width=1, color="#000")),
            name=abbr(team), showlegend=False,
            hovertemplate=(f"<b>{abbr(team)}</b>"
                           + (" · second half" if have_arrows else "") +
                           "<br>one-lap speed: %{x:>+.2f}% vs median<br>"
                           "race pace: %{y:>+.2f}% vs median<extra></extra>"),
        ))
    fig.add_annotation(x=hi, y=lo + (hi - lo) * 0.06,
                       text="stronger over a stint ↓", showarrow=False,
                       font=dict(size=10, color=TEXT_DIM), xanchor="right")
    if have_arrows:
        fig.add_annotation(x=lo, y=hi, text="faint dot → arrow = first half → second",
                           showarrow=False, xanchor="left", yanchor="top",
                           font=dict(size=9, color=TEXT_DIM))
    theme(fig, height)
    fig.update_xaxes(title_text="ONE-LAP SPEED vs field median (%) · left = faster")
    fig.update_yaxes(title_text="RACE pace vs field median (%) · down = faster")
    return fig


# ── Momentum: what changed, not where things stand ───────────

# Rounds averaged either side of the comparison. Three is the smallest window
# that survives one scruffy weekend; it is NOT free — see _momentum_noise().
MOMENTUM_WINDOW = 3


def _momentum_window(s: pd.DataFrame) -> tuple[list[int], list[int]]:
    """The two blocks of rounds the card compares: the last W against the W
    before them.

    NOT a first-half/second-half split. A half-split cannot answer "who is
    moving NOW": with 11 rounds it averages six of them into the recent number,
    so a fresh result moves the answer by a sixth and the card is structurally
    ~3 races behind. That is how Aston Martin's biggest upgrade of the season
    (Hungary, 16 items, the best single step on the 2026 upgrade board) still
    left them reading as the grid's biggest loser.

    Shrinks the window rather than refusing when the season is young.
    """
    rounds = sorted(int(r) for r in s["round"].dropna().unique())
    w = min(MOMENTUM_WINDOW, len(rounds) // 2)
    if w < 2:
        return [], []
    return rounds[-2 * w:-w], rounds[-w:]


def _momentum_noise(s: pd.DataFrame, w: int) -> float:
    """Smallest |d_pace| worth reading, in pp.

    A team's one-lap speed wanders round to round on setup, traffic and track
    state. Comparing two w-round means, that wander shows up as sd·sqrt(2/w) of
    pure noise. Shorter window = more responsive AND noisier, and the card says
    so instead of letting every dot look meaningful: at 2026's spread the
    3-round floor is ~0.31 pp against ~0.23 pp for a half-season split.
    """
    sd = s.groupby("team")["onelap_speed_pct"].std().dropna()
    if sd.empty or w < 1:
        return 0.0
    return float(sd.median()) * float(np.sqrt(2.0 / w))


def _momentum_headline_floor(s: pd.DataFrame, w: int,
                             alpha: float = 0.05) -> float:
    """The bar a team must clear to be NAMED as the field's biggest mover.

    Higher than _momentum_noise, for a reason that is easy to miss: that floor
    is right for reading ONE dot, but the headline sentence reports the EXTREME
    of the whole grid. Judge the winner of eleven noisy draws against a
    one-team floor and you name a mover every round whether or not anything
    happened.

    Bonferroni across the field (two-sided, family-wise alpha), not the
    expected maximum — the expected max is exceeded by half of all trendless
    seasons by construction, and this sentence is the plain-English headline a
    newcomer reads as fact. ~2.8x the single-team floor with eleven teams.
    """
    n = int(s["team"].nunique())
    floor = _momentum_noise(s, w)
    if n < 2 or floor <= 0:
        return floor
    from statistics import NormalDist
    return floor * float(NormalDist().inv_cdf(1.0 - alpha / (2.0 * n)))


def _window_character(s: pd.DataFrame, rounds: list[int]) -> float | None:
    """Mean circuit speed-character (1 = slow/technical … 3 = power) of a block
    of rounds, or None when the circuits can't be resolved."""
    if not rounds:
        return None
    try:
        from tabs.season_ops import _EVENT_TO_CIRCUIT, _slugify
        chars = pd.read_csv("data/circuit_characteristics.csv",
                            encoding="utf-8-sig").set_index("circuit_key")
    except Exception:
        return None
    ev = (s[s["round"].isin(rounds)].drop_duplicates("round")["event"])
    vals = []
    for e in ev:
        key = _EVENT_TO_CIRCUIT.get(_slugify(e))
        if key in chars.index:
            v = pd.to_numeric(chars.loc[key, "avg_speed_score"], errors="coerce")
            if pd.notna(v):
                vals.append(float(v))
    return float(np.mean(vals)) if vals else None


def _momentum_confound_note(s: pd.DataFrame) -> str:
    """One line naming the calendar confound, when there is one to name.

    The circuit effect is NOT corrected out. A per-team circuit-affinity
    adjustment was built and measured: fitting each team's slope on the odd
    rounds and testing it on the even ones REDUCED accuracy in 2024 (-3.6%) and
    2025 (-13.6%) even with empirical-Bayes shrinkage, and only helped in 2026
    (+17.1%). Circuit affinity is not a stable enough team property to correct
    with, so the confound is named here rather than silently removed — a wrong
    correction is worse than a stated caveat.
    """
    early, late = _momentum_window(s)
    ce, cl = _window_character(s, early), _window_character(s, late)
    if ce is None or cl is None:
        return ""
    swing = cl - ce
    if abs(swing) < 0.4:
        return (f"Both blocks average a similar circuit character "
                f"({ce:.1f} → {cl:.1f} on a 1-3 speed scale), so the comparison "
                f"is close to like-for-like.")
    faster = "faster, more power-hungry" if swing > 0 else "slower, more technical"
    return (f"Heads up: the recent block ran on {faster} circuits than the one "
            f"before it ({ce:.1f} → {cl:.1f} on a 1-3 speed scale). A car with a "
            f"strong circuit preference can move here without changing at all.")


def _momentum_frame(s: pd.DataFrame) -> pd.DataFrame:
    """Per team: how one-lap speed and scoring moved over the last W rounds
    against the W before them.

    Scoring is a SHARE of the points the whole field took in that block, not
    points per round. Sprints are not spread evenly through a season — three
    of 2026's first four fell in rounds 1-5 — so the pot per round differs
    between blocks. Points-per-round therefore drags every team downwards in a
    sprint-poor block for pure scheduling reasons, which would read as the
    entire grid losing momentum at once. A share of the pot normalises that
    away by construction, and sums to zero across teams, which is what a
    momentum measure should do.
    """
    early, late = _momentum_window(s)
    if not late or not early:
        return pd.DataFrame()
    e, l = s[s["round"].isin(early)], s[s["round"].isin(late)]
    pot_e, pot_l = e["points"].sum(), l["points"].sum()
    if not (pot_e > 0 and pot_l > 0):
        return pd.DataFrame()
    rows = []
    for team in sorted(s["team"].unique()):
        te, tl = e[e["team"] == team], l[l["team"] == team]
        if te.empty or tl.empty:
            continue
        pace_e, pace_l = te["onelap_speed_pct"].mean(), tl["onelap_speed_pct"].mean()
        pts_e, pts_l = te["points"].sum(), tl["points"].sum()
        share_e, share_l = pts_e / pot_e * 100, pts_l / pot_l * 100
        rows.append({
            "team": team,
            "d_pace": (pace_l - pace_e) if np.isfinite(pace_l) and np.isfinite(pace_e) else np.nan,
            "d_share": share_l - share_e, "share_e": share_e, "share_l": share_l,
            # kept for the hover — points are what you actually think in
            "ppr_e": pts_e / max(len(te), 1), "ppr_l": pts_l / max(len(tl), 1),
            "pace_e": pace_e, "pace_l": pace_l,
        })
    return pd.DataFrame(rows).dropna(subset=["d_pace"])


def _momentum_fig(s: pd.DataFrame, height: int = 520) -> go.Figure:
    """Change in one-lap speed against change in points share, over the last W
    rounds versus the W before. Quadrants say what kind of change it is; the
    shaded band says when the change is too small to call."""
    d = _momentum_frame(s)
    fig = go.Figure()
    if d.empty:
        theme(fig, height)
        return fig
    early, late = _momentum_window(s)
    floor = _momentum_noise(s, len(late))
    xr = max(float(d["d_pace"].abs().max()) * 1.45, floor * 1.6, 0.3)
    yr = max(float(d["d_share"].abs().max()) * 1.45, 1.0)

    # Everything inside ±floor is indistinguishable from a team standing still.
    # Drawn, not just described: without it every dot looks like a finding, and
    # on a 3-round window most of them are not.
    if floor > 0:
        fig.add_vrect(x0=-floor, x1=floor, fillcolor=TEXT_DIM, opacity=0.09,
                      line_width=0, layer="below")
        fig.add_annotation(x=0, y=-yr * 0.99, yanchor="bottom",
                           text=f"±{floor:.2f} pp — inside the noise floor",
                           showarrow=False,
                           font=dict(size=8.5, color=TEXT_DIM))
    fig.add_vline(x=0, line=dict(color=TEXT_DIM, width=1))
    fig.add_hline(y=0, line=dict(color=TEXT_DIM, width=1))
    # quadrant labels — x is NEGATIVE when the car got faster, so "improving"
    # is the left half of the chart
    for x, y, txt, xa, ya in (
            (-xr * 0.96, yr * 0.93, "CAR FASTER · BIGGER SHARE", "left", "top"),
            (xr * 0.96, yr * 0.93, "CAR SLOWER · BIGGER SHARE", "right", "top"),
            (-xr * 0.96, -yr * 0.93, "CAR FASTER · SMALLER SHARE", "left", "bottom"),
            (xr * 0.96, -yr * 0.93, "CAR SLOWER · SMALLER SHARE", "right", "bottom")):
        fig.add_annotation(x=x, y=y, text=txt, showarrow=False, xanchor=xa,
                           yanchor=ya, font=dict(size=9, color=TEXT_DIM))
    for r in d.itertuples():
        clr = TEAM_COLORS.get(r.team, "#808080")
        fig.add_trace(go.Scatter(
            x=[r.d_pace], y=[r.d_share], mode="markers+text", text=[abbr(r.team)],
            textposition="top center", textfont=dict(size=10, color=clr),
            marker=dict(size=14, color=clr, line=dict(width=1, color="#000")),
            showlegend=False,
            customdata=[[r.pace_e, r.pace_l, r.share_e, r.share_l,
                         r.ppr_e, r.ppr_l]],
            hovertemplate=(
                f"<b>{abbr(r.team)}</b><br>"
                "one-lap speed %{customdata[0]:>+.2f}% → %{customdata[1]:>+.2f}% "
                "(%{x:>+.2f})<br>"
                "share of points %{customdata[2]:.1f}% → %{customdata[3]:.1f}% "
                "(%{y:>+.1f}pp)<br>"
                "<span style='opacity:.7'>raw %{customdata[4]:.1f} → "
                "%{customdata[5]:.1f} pts/round</span><extra></extra>"),
        ))
    theme(fig, height)
    fig.update_xaxes(title_text="change in ONE-LAP SPEED (pp) · "
                                "left = the car got faster",
                     range=[-xr, xr])
    fig.update_yaxes(title_text="change in share of the points scored (pp)",
                     range=[-yr, yr])
    return fig


def _form_fig(s: pd.DataFrame, height: int = 560) -> go.Figure:
    """Two panels: rolling points-per-round (are they scoring NOW?) and the
    points gap to the championship leader (is the title fight closing?)."""
    from plotly.subplots import make_subplots
    rounds, labels = _round_axis(s)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.09,
                        subplot_titles=("Points per round · 3-round rolling",
                                        "Points behind the leader"))
    lead = (s.groupby("round")["cum_points"].max()
            if "cum_points" in s.columns else None)
    for team in _team_order(s):
        g = s[s["team"] == team].sort_values("round")
        if g.empty:
            continue
        clr = TEAM_COLORS.get(team, "#808080")
        roll = g["points"].rolling(3, min_periods=1).mean()
        fig.add_trace(go.Scatter(
            x=g["round"], y=roll, mode="lines", name=abbr(team),
            line=dict(color=clr, width=2), legendgroup=team,
            customdata=np.stack([g["event"].map(event_short), g["points"]], axis=-1),
            hovertemplate=(f"<b>{abbr(team)}</b> · %{{customdata[0]}}<br>"
                           "rolling %{y:.1f} pts/round "
                           "(scored %{customdata[1]:.0f})<extra></extra>"),
        ), row=1, col=1)
        if lead is not None:
            behind = g["round"].map(lead).to_numpy(float) - g["cum_points"].to_numpy(float)
            fig.add_trace(go.Scatter(
                x=g["round"], y=behind, mode="lines", name=abbr(team),
                line=dict(color=clr, width=2), legendgroup=team,
                showlegend=False,
                customdata=np.stack([g["event"].map(event_short)], axis=-1),
                hovertemplate=(f"<b>{abbr(team)}</b> · %{{customdata[0]}}<br>"
                               "%{y:.0f} pts behind the leader<extra></extra>"),
            ), row=2, col=1)
    # BASE_NO_AXES + theme_axes rather than BASE: layout.xaxis only reaches
    # panel 1 of a subplot figure, so the shared styling (and the house hover
    # rounding) has to go on through update_*axes.
    fig.update_layout(**BASE_NO_AXES, height=height)
    theme_axes(fig)
    fig.update_xaxes(tickmode="array", tickvals=rounds, ticktext=labels,
                     tickangle=-40, gridcolor=GRID_CLR, row=2, col=1)
    fig.update_xaxes(gridcolor=GRID_CLR, row=1, col=1)
    fig.update_yaxes(title_text="pts / round", gridcolor=GRID_CLR, row=1, col=1)
    fig.update_yaxes(title_text="pts behind", gridcolor=GRID_CLR,
                     autorange="reversed", row=2, col=1)
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.06,
                                  xanchor="left", x=0))
    for a in fig.layout.annotations:
        a.font.size = 11
        a.font.color = TEXT_MAIN
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
    fastest = _fastest_team(s, "onelap_speed_pct")
    if fastest is None:
        return None
    return (f"Over a single flat-out lap this season, {_fmt_team(fastest)} have "
            "been the quickest car on average — the strongest qualifiers, so "
            "they tend to line up near the front for the race. This is "
            "one-lap speed only; how quick they are over a full stint is the "
            "next chart down, and it can tell a different story.")


def _race_plain(s: pd.DataFrame, quali_fastest):
    fastest = _fastest_team(s, "race_pace_pct")
    if fastest is None:
        return None
    if quali_fastest is not None and fastest != quali_fastest:
        tail = (f" — a different car than the one-lap speedsetter "
                f"({_fmt_team(quali_fastest)}), so watch them recover ground "
                "over a race.")
    else:
        tail = (" — the same car that tops one-lap speed, the mark of an "
                "all-round-strong package.")
    return (f"Over long runs on wearing tyres, {_fmt_team(fastest)} have the "
            f"best race pace on average{tail}")


def _momentum_plain(s: pd.DataFrame):
    d = _momentum_frame(s)
    if d.empty:
        return None
    early, late = _momentum_window(s)
    # Only call a move that clears the FIELD-WIDE bar. The old threshold was a
    # flat 0.1 pp, well inside the per-team noise floor (~0.31 pp on a 3-round
    # window in 2026), so this line named a riser and a faller every round
    # regardless. The per-team floor is not enough either, because this
    # sentence reports the extreme of eleven teams — see the docstring.
    floor = _momentum_headline_floor(s, len(late))
    riser = d.sort_values("d_pace").iloc[0]          # biggest speed gain
    faller = d.sort_values("d_pace").iloc[-1]        # biggest speed loss
    span = (f"the last {len(late)} races against the {len(early)} before them")
    bits = []
    got_riser = riser["d_pace"] < -floor
    if got_riser:
        # "pp" not "points": championship points appear in the same sentence
        bits.append(f"{_fmt_team(riser['team'])} have found the most lap time "
                    f"over {span}, {abs(riser['d_pace']):.2f}pp of it")
    if faller["d_pace"] > floor:
        # "the other way" only reads as English when a riser was named first
        lead = ("have gone the other way, giving up" if got_riser
                else f"have lost the most lap time over {span},")
        bits.append(f"{_fmt_team(faller['team'])} {lead} "
                    f"{faller['d_pace']:.2f}pp")
    if not bits:
        return (f"Nobody has moved by more than the {floor:.2f}pp this "
                f"measurement can actually resolve over {span} — the pecking "
                "order is holding. That is a real answer, not a missing one.")
    return (". ".join(bits) +
            ". Teams on the left of the chart are building; the higher up they "
            "sit, the more of that gain is actually turning into points.")


def _momentum_title(s: pd.DataFrame):
    """Card title carrying the window, so 'who is moving' can never be read as
    'since the start of the season'."""
    early, late = _momentum_window(s)
    if not late:
        return "Momentum — who is actually moving"
    def _span(r):
        return f"R{r[0]}" if len(r) == 1 else f"R{r[0]}–{r[-1]}"
    return (f"Momentum — who is actually moving  ·  "
            f"{_span(late)} vs {_span(early)}")


def _momentum_footnotes(s: pd.DataFrame):
    """The two things the scatter cannot say for itself: what the calendar was
    doing under the comparison, and where the biggest single-round move came
    from (which is usually an upgrade, and lives on another card)."""
    notes = []
    confound = _momentum_confound_note(s)
    if confound:
        notes.append(confound)

    # Cross-link: the largest single-round improvement inside the recent block,
    # matched against the upgrade table. The Momentum dot is an average of
    # three rounds, so a genuine step change is visible here and nowhere else
    # on this card.
    try:
        from tabs.upgrades import _upgrade_rounds
        _, late = _momentum_window(s)
        g = s[s["round"].isin(late)].copy()
        prev = (s.sort_values("round").groupby("team")["onelap_speed_pct"]
                .shift(1))
        g["step"] = g["onelap_speed_pct"] - prev.reindex(g.index)
        g = g.dropna(subset=["step"])
        if not g.empty:
            best = g.loc[g["step"].idxmin()]
            if best["step"] < -0.5:
                ups = _upgrade_rounds(int(s["season"].iloc[0]))
                hit = ups[(ups["team"] == best["team"])
                          & (ups["round"] == int(best["round"]))]
                extra = (f" — the round they brought {int(hit['n_items'].iloc[0])} "
                         f"upgrade item(s); see the Upgrade Impact board"
                         if not hit.empty else "")
                notes.append(
                    f"Biggest single-round step in this window: "
                    f"{abbr(best['team'])} {best['step']:+.2f} pp at "
                    f"{event_short(best['event'])}{extra}.")
    except Exception:
        pass

    if not notes:
        return None
    return html.Div(
        [html.Div(n, style={"marginBottom": "4px"}) for n in notes],
        style={"color": TEXT_DIM, "fontSize": "0.74rem", "lineHeight": "1.45",
               "borderTop": f"1px solid {GRID_CLR}", "paddingTop": "8px",
               "marginTop": "2px"})


def _character_plain(s: pd.DataFrame):
    avg = (s.groupby("team")[["onelap_speed_pct", "race_pace_pct"]]
           .mean().dropna())
    if avg.empty:
        return None
    gain = (avg["onelap_speed_pct"] - avg["race_pace_pct"]).sort_values(
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
    n_race = s["race_pace_pct"].notna().sum()
    quali_fastest = _fastest_team(s, "onelap_speed_pct")
    # The season-calendar ribbon now lives at the top of the tab, above the
    # championship standings (see tab_season) — not here in SEASON FORM.
    return html.Div([
        card(
            [*gloss("one-lap speed", "One-Lap Speed"), " by Round"],
            dcc.Graph(figure=_trend_fig(
                s, "onelap_speed_pct", "vs field median (%) · lower = faster",
                median_ref=True), config=GFX),
            measure="one-lap",
            info=("Data: every team's best qualifying lap in EVERY Q-session "
                  "it ran, fitted with a two-way "
                  "fixed-effects model (team + Q-session) on log lap time. The "
                  "session term absorbs the track evolution between Q1 and Q3 "
                  "— about 1% of lap time in 2026, and up to 1.5% at Monaco — "
                  "so a team knocked out in Q1 is compared on the same track "
                  "state as the pole car instead of being charged for it. "
                  "Expressed vs the FIELD MEDIAN, not vs pole, so one team's "
                  "off weekend doesn't shift everyone else's line. Negative = "
                  "faster than the median car. Why: this is the momentum "
                  "series — it isolates CAR one-lap speed from where the team "
                  "happened to finish on Saturday. For the Saturday result "
                  "itself (which mixes pace with session progression, traffic "
                  "and penalties) use the grid in the QUALI tab."),
            plain=_quali_plain(s),
        ),
        card(
            [*gloss("race pace", "Race Pace"), " by Round"],
            dcc.Graph(figure=_trend_fig(
                s, "race_pace_pct", "vs field median (%) · lower = faster",
                median_ref=True), config=GFX)
            if n_race else
            html.P("No cached race laps for this season — run "
                   "fetch_previous_races.py, then compute_team_pace.py.",
                   style={"color": TEXT_DIM}),
            measure="race",
            info=("Data: each team's best driver's MEDIAN race lap — fuel- "
                  "and track-evolution-corrected — over clean racing laps "
                  "only: valid, out of dirty air, and NOT under a safety car, "
                  "VSC or yellow (≥10 such laps required). The caution-lap "
                  "exclusion matters more than it sounds: leaving those laps "
                  "in moved a team's figure by up to 0.46 pp in a single "
                  "event, which is the same size as most of the effects the "
                  "upgrade board is trying to detect. Fuel correction is "
                  "era-aware — 2026 cut the race fuel load sharply, so a "
                  "single constant would over-correct every lap of this "
                  "season by about half. Expressed as % vs the field median; "
                  "negative = faster than the median car. A round the laps "
                  "don't support leaves a BREAK in the line rather than an "
                  "interpolated segment. Why: sustained Sunday pace on race "
                  "fuel and wearing tyres — a completely different measure "
                  "from the one-lap chart above, and often a different "
                  "pecking order. Reading them together is the point: a car "
                  "above its one-lap position here is a race car."),
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
            # Both axes are pace measures, and they are different ones —
            # the whole point of the chart is the gap between them.
            measure=("one-lap", "race"),
            info=("Data: season-average ONE-LAP SPEED (x) vs season-average "
                  "RACE pace (y) per team, both as % vs the field median; the "
                  "dotted diagonal means 'same relative pace both days'. Why: "
                  "teams below the line are stronger over a stint than over "
                  "one lap (tyre-gentle, heavy-fuel strong) — expect them to "
                  "gain on Sundays; above the line is a one-lap car that goes "
                  "backwards in races. Caveat: these are WHOLE-SEASON "
                  "averages, so at this point they blend the March car with "
                  "the July one — a team whose character changed mid-season "
                  "shows here as a single blurred dot."),
            plain=_character_plain(s),
        ),
        card(
            _momentum_title(s),
            html.Div([
                dcc.Graph(figure=_momentum_fig(s), config=GFX),
                _momentum_footnotes(s),
            ]),
            measure="one-lap",
            info=("Data: each team's average session-normalised ONE-LAP SPEED, "
                  "and its SHARE of all the points the field scored, over the "
                  f"last {MOMENTUM_WINDOW} rounds against the "
                  f"{MOMENTUM_WINDOW} before them. The dot is the change. "
                  "A ROLLING window, not first-half-vs-second: a half-split "
                  "averages six rounds into the recent number, so one new "
                  "result moves it by a sixth and the card sits ~3 races behind "
                  "reality — which is how Aston Martin's 16-item Hungary "
                  "package, the best single step on the 2026 upgrade board, "
                  "still left them reading as the biggest loser on the grid. "
                  "Share of the pot rather than points per round on purpose: "
                  "sprints are not spread evenly through a season, so "
                  "points-per-round would drag every team down in a "
                  "sprint-poor block for pure scheduling reasons. Shares sum "
                  "to zero across teams, which is what a momentum measure "
                  "should do. The shaded band is the noise floor — two "
                  "3-round means of a series that wanders this much differ by "
                  "that amount on nothing at all, so a dot inside it has not "
                  "moved. Why: every other chart here shows where teams stand; "
                  "this shows which way they are going. The quadrants matter — "
                  "a car that got faster while taking a smaller share is being "
                  "let down by reliability, strategy or luck, and the opposite "
                  "corner is a team out-executing its car. Caveat: circuit "
                  "character is NOT corrected out. A per-team affinity "
                  "adjustment was built and tested out-of-sample; it helped in "
                  "2026 (+17%) but made 2024 and 2025 worse, so the confound is "
                  "named under the chart instead of silently removed."),
            plain=_momentum_plain(s),
        ),
        card(
            "Form Guide — recent scoring and the gap to the front",
            dcc.Graph(figure=_form_fig(s), config=GFX),
            info=("Data: top — points scored per round on a 3-round rolling "
                  "mean, so a single big score doesn't dominate. Bottom — how "
                  "far each team is behind the championship leader after every "
                  "round, axis inverted so higher on the chart is closer to "
                  "the front. Why: the cumulative points chart above is "
                  "monotonic, which makes recent form nearly invisible — by "
                  "round 11 a team scoring 40 points in three rounds and one "
                  "scoring 4 look almost identical on it. These two panels are "
                  "the derivative view: who is scoring NOW, and whether the "
                  "gap to the front is opening or closing."),
        ),
    ] + [c for c in (affinity_card(season), chaos_timeline_card(season),
                      # next to affinity and chaos on purpose: those two ask
                      # what a circuit does to the racing, and the weather is
                      # the other half of that question
                      session_weather_card(season),
                      pit_league_card(season), lap1_league_card(season),
                      testing_card(season),
                      reliability_card(season), contact_card(season),
                      penalties_card(season),
                      pu_pool_card(season), gearbox_pool_card(season),
                      engine_championship_card(season))
         if c is not None])


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


def tab_context() -> html.Div:
    """CONTEXT tab — the rulebook and the paddock.

    Everything here is read-once reference: the budget cap, ATR, technical
    directives, team finances, factories, the staff transfer market and the
    newcomer primer. It used to sit inside SEASON, which meant ~18 cards of
    material you have already read stood between you and the four charts that
    change when a race happens. Splitting it costs nothing — the content is
    unchanged — and gives SEASON back its job.
    """
    yrs = seasons()
    parts = []
    if yrs:
        parts.append(season_intro_block(max(yrs)))
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
    parts += [
        _section_header("HR & PERSONNEL",
                        "the technical & management transfer market — who moved "
                        "where, and the gardening-leave gaps the budget-cap era "
                        "turned into a long-term form lever"),
        hr_section(),
    ]
    if yrs:
        dm_card = driver_market_card(max(yrs))
        if dm_card is not None:
            parts.append(dm_card)
    parts += [
        _section_header("INFRASTRUCTURE & GOVERNANCE",
                        "where each team designs its car — factory and "
                        "wind-tunnel capability — and the FIA technical "
                        "directives that reshape the rules mid-season"),
        infrastructure_section(),
    ]
    return html.Div(parts)


def tab_season(standings=None, upgrades=None) -> html.Div:
    """SEASON tab: only what moves when a race happens — the calendar, the
    championship standings, the season form and momentum charts, the race-ops
    league tables and the car-upgrade payoff. The static reference material
    (regulations, finance, HR, infrastructure) lives in CONTEXT."""
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
    if upgrades is not None:
        parts += [
            _section_header("CAR UPGRADES",
                            "did the development pay off? — each team's pace "
                            "trend and the measured effect of every upgrade "
                            "package (per-event detail lives in WEEK END PRED)"),
            upgrades,
        ]
    parts.append(html.P(
        ["The budget cap, wind-tunnel allowances, technical directives, team "
         "finances, factories and the staff transfer market now live in the ",
         html.B("CONTEXT"), " tab — they change once a season, not once a "
         "race."],
        style={"color": TEXT_DIM, "fontSize": "0.78rem", "textAlign": "center",
               "marginTop": "34px", "paddingTop": "16px",
               "borderTop": f"1px solid {GRID_CLR}"}))
    return html.Div(parts)


@callback(Output("season-content", "children"),
          Input("season-select", "value"),
          prevent_initial_call=True)
def _update_season(season):
    return _season_content(int(season))
