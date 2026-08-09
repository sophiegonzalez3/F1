"""
WEEKEND BRIEF — the progressive pace prediction, in one page.

Answers the question the other ten tabs make you assemble by hand: given
everything seen so far this weekend, who will be quick? It starts from an
era-aware season-form prior (pace_model.py) and sharpens after each practice
session, showing the predicted qualifying order WITH uncertainty, how it has
moved session to session, and win/podium probabilities. Once qualifying (or
the race) is loaded it keeps score against what actually happened.

All modelling lives in pace_model.py / pace_features.py; this module only
renders the loaded event. See backtest_pace_model.py for the validation that
justifies trusting it (and its limits — long-run race pace is a much weaker
read than one-lap).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import html, dcc, callback, Input, Output, State
import dash_bootstrap_components as dbc

import f1lib.state as state
from f1lib.components import (
    theme, theme_axes, card, kpi, GFX, abbr as _abbr, BASE, BASE_NO_AXES,
)
from f1lib.config import (
    TEAM_COLORS, TEXT_DIM, TEXT_MAIN, GRID_CLR, ACCENT, CARD_BG,
)
from f1lib.pace_model import PaceModel, canon
from f1lib.race_forecast import RaceForecaster
from tabs import outcome

_KIND_LABEL = {"onelap": "Qualifying (one-lap)", "longrun": "Race (long-run)"}
_STAGE_SHORT = {"prior": "Prior", "after FP1": "FP1", "after FP2": "FP2",
                "after FP3": "FP3", "after SprintQuali": "SQ",
                "after Sprint": "Sprint", "after Quali": "Quali"}
# progression x-axis order (whichever stages actually exist this weekend).
# "after Quali" is deliberately absent: it only moves the long-run latent,
# so drawing it on the ONE-LAP progression would be a flat, misleading step.
_STAGE_SEQUENCE = ["prior", "after FP1", "after FP2", "after FP3",
                   "after SprintQuali", "after Sprint"]
# Stages that count when SCORING a weekend. "after Quali" belongs here and not
# in the sequence above: the progression chart is a one-lap story and freezes
# pre-quali on purpose, but the sharpest LONG-RUN prediction available before
# the race is the post-qualifying one — it is what the RACE order card
# actually shows, so leaving it out understated the model on every scored
# chart. There is no one-lap "after Quali" row to worry about: the backtest
# refuses to emit one, because scoring qualifying against a prediction that
# used qualifying is circular.
_SCORED_STAGES = _STAGE_SEQUENCE + ["after Quali"]

# ── Season track record (scripts/backtest_pace_model.py) ─────
# The per-event LEDGER below scores this weekend. That tells you whether the
# model got THIS one right, which is not the same as whether to trust it on
# Friday — for that you need its record over the season, which is what the
# backtest writes and what _track_record_card renders. The CSV existed for a
# long time with nothing reading it.
_BACKTEST_PATH = Path("data/backtest_pace_model.csv")
_BASELINE_STAGES = {"raw-FP"}


def _backtest_df() -> pd.DataFrame:
    if not _BACKTEST_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(_BACKTEST_PATH)
    except Exception:
        return pd.DataFrame()

# One model instance for the process (reads the pace CSV once).
_MODEL: PaceModel | None = None
_FORECASTER: RaceForecaster | None = None


def _model() -> PaceModel:
    global _MODEL
    if _MODEL is None:
        _MODEL = PaceModel()
    return _MODEL


def _forecaster() -> RaceForecaster | None:
    global _FORECASTER
    if _FORECASTER is None:
        try:
            _FORECASTER = RaceForecaster()
        except Exception:
            _FORECASTER = False
    return _FORECASTER or None


def _loaded_event() -> tuple[int, str] | None:
    info = state.LOADED_SESSION_INFO or []
    for s in info:
        if str(s.get("SESSION", "")).startswith(("Practice", "Qualifying",
                                                 "Race", "Sprint")):
            return int(s["SEASON"]), str(s["MEETING"])
    return None


def _clr(team: str) -> str:
    return TEAM_COLORS.get(team, "#808080")


# ─────────────────────────────────────────────────────────────
# Figures
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# "How this model works" — a worked example, collapsed by default
# ─────────────────────────────────────────────────────────────
#
# One real weekend, all the way through, because the abstract description
# ("era-aware Bayesian blend") tells a reader nothing about what the numbers
# on this page actually mean.
#
# NUMBERS ARE FROM A REAL RUN, not illustrative — Ferrari's one-lap latent at
# the 2026 Belgian Grand Prix. Regenerate after any change to the prior or to
# base_noise with:
#     python -c "from f1lib.pace_model import PaceModel; \
#                from f1lib.pace_features import event_measurements; \
#                m=PaceModel(); meas,_=event_measurements(2026,'Belgian Grand Prix'); \
#                [print(k, d[(d.team=='Ferrari')&(d.kind=='onelap')][['mean','sd']].round(3).to_dict('records')) \
#                 for k,d in m.predict_weekend(2026,'Belgian Grand Prix',measurements=meas,round_=10).items()]"
_WALK = {
    "event": "Belgian Grand Prix 2026",
    "lap_s": 105.0,                     # ~1% of a Spa lap = 1.05 s
    # stage label, estimate, sd, what that session's laps actually said
    "ladder": [("Prior", -1.138, 0.321, None, None),
               ("after FP1", -1.123, 0.307, -0.961, 0.08),
               ("after FP2", -1.108, 0.289, -1.004, 0.12),
               ("after FP3", -1.070, 0.266, -0.893, 0.16)],
    "actual": -0.884,
    "drivers": [("LEC", -0.982, -0.220), ("HAM", -0.823, -0.062)],
}

# ── the OUTCOME half of the same weekend ─────────────────────
#
# The walkthrough above stops at "how fast is the car", which is only half of
# what this page shows. Everything below turns that into a finishing position,
# and the numbers are again from a real run of the same event.
#
#     python -c "from f1lib.race_forecast import RaceForecaster as R; r=R(); \
#                print(r.passability('Belgian Grand Prix'), \
#                      r.dnf_multiplier('Belgian Grand Prix'), r.p['race_noise'])"
_RACE = {
    "pull": 0.407,            # Spa passability; field average 0.456
    "pull_avg": 0.456,
    "dnf": 0.098,             # 0.12 base x 0.814 circuit multiplier
    "dnf_corr": 0.19,
    "n_sims": 20000,
    # Leclerc's finishing-position distribution from grid 4, P1..P12
    "lec_dist": [0.165, 0.232, 0.222, 0.154, 0.077, 0.033, 0.015, 0.005,
                 0.001, 0.0, 0.0, 0.0],
    "lec_tail": 0.096,        # P13+, i.e. essentially the retirement mass
    "lec_actual": 2,
    "ant_pwin": 0.465,        # from pole, with the fastest car
    "nor_grid": 13, "nor_ppodium": 0.025, "nor_actual": 7,
}

# Measured by scripts/backtest_race_forecast.py. Kept here as literals so the
# explainer cannot silently drift from the file it describes; RE-READ
# data/backtest_race_forecast.csv after any model change or data backfill.
#
# These moved once already: the first version was scored on 105 races because
# the replay needs practice laps and 2019-2021 had none cached, so those events
# were silently skipped. Backfilling them took it to 161 races and CHANGED the
# verdict — p_podium went from "not significant against the grid baseline" to
# significant. A sample that grows can overturn a conclusion, so the sample
# size is quoted alongside every claim below.
_SCORE = {
    "races": 161, "rows": 2699,
    "brier": {"win": 0.0376, "podium": 0.0712, "points": 0.1481},
    "vs_clim": {"win": 0.324, "podium": 0.501, "points": 0.411},
    "vs_grid": {"win": 0.013, "podium": 0.079, "points": 0.061},
    # Does the gap clear a race-clustered bootstrap? Only these two do.
    "beats_grid": {"win": False, "podium": True, "points": True},
    "mae_finish": 2.86,
    "slope_win": 1.201,
}


def _walkthrough_fig() -> go.Figure:
    """Ferrari's estimate converging across a weekend, with the error bar
    shrinking and the eventual truth drawn as a reference line.

    The point of the picture is the BAR, not the dot: the model's claim is an
    interval, and the interval narrowing is the whole mechanism.
    """
    lad = _WALK["ladder"]
    ys = [r[0] for r in lad]
    xs = [r[1] for r in lad]
    sd = [r[2] for r in lad]
    fig = go.Figure()
    fig.add_vline(x=_WALK["actual"], line_color=ACCENT, line_width=2,
                  line_dash="dot")
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers+text", orientation="h",
        error_x=dict(type="data", array=sd, color=TEXT_DIM, thickness=2,
                     width=6),
        marker=dict(size=13, color="#FF8A3D",
                    line=dict(width=1, color="#000")),
        text=[f"{v:+.2f} ±{s:.2f}" for v, s in zip(xs, sd)],
        textposition="top center", textfont=dict(size=10, color=TEXT_MAIN),
        customdata=[[r[3] if r[3] is not None else float("nan"),
                     r[4] if r[4] is not None else float("nan")] for r in lad],
        hovertemplate="%{y}<br>estimate %{x:>+.3f}%"
                      "<br>that session measured %{customdata[0]:>+.3f}%"
                      "<br>moved %{customdata[1]:.0%} of the way"
                      "<extra></extra>"))
    theme(fig, 300, "")
    fig.update_layout(
        showlegend=False,
        xaxis_title="Ferrari one-lap speed, % gap to the mid-grid car  ·  faster ← → slower",
        margin=dict(l=90, r=40, t=30, b=44))
    fig.add_annotation(x=_WALK["actual"], y=-0.45, yref="paper" if False else "y",
                       text="what qualifying<br>actually showed", showarrow=False,
                       font=dict(size=10, color=ACCENT), yshift=-6)
    fig.update_yaxes(autorange="reversed")
    return fig


def _outcome_fig() -> go.Figure:
    """Leclerc's whole finishing distribution, with what happened marked.

    This is the picture the outcome half needs, because the thing people carry
    away from "P4 predicted" is a position, and the model never had one. It
    had a spread over every position, and the bar at the far right is the
    ~10% of simulations where the car stops.
    """
    dist = _RACE["lec_dist"]
    xs = [f"P{i}" for i in range(1, len(dist) + 1)] + ["DNF /<br>lapped"]
    ys = dist + [_RACE["lec_tail"]]
    colors = ["#FF8A3D"] * len(dist) + [TEXT_DIM]
    act = _RACE["lec_actual"] - 1
    colors[act] = ACCENT
    fig = go.Figure(go.Bar(
        x=xs, y=ys, marker_color=colors,
        text=[f"{v:.0%}" if v >= 0.02 else "" for v in ys],
        textposition="outside", textfont=dict(size=10, color=TEXT_DIM),
        hovertemplate="%{x}: %{y:.1%} of 20,000 races<extra></extra>"))
    theme(fig, 260, "")
    fig.update_layout(showlegend=False, bargap=0.25,
                      margin=dict(l=50, r=20, t=34, b=36),
                      yaxis_title="share of simulations")
    fig.update_yaxes(tickformat=".0%", range=[0, max(ys) * 1.28])
    fig.add_annotation(x=act, y=ys[act], yshift=26, showarrow=False,
                       text="actually finished here",
                       font=dict(size=10, color=ACCENT))
    return fig


def _hiw_toggle_button():
    return dbc.Button(
        "How this model works  ▾", id="brief-hiw-toggle", n_clicks=0, size="sm",
        color="link", style={
            "color": ACCENT, "fontWeight": "700", "fontSize": "0.85rem",
            "textDecoration": "none", "padding": "2px 8px",
            "border": f"1px solid {ACCENT}", "borderRadius": "6px"})


def _step(n, title, body):
    """One numbered step of the walkthrough."""
    return html.Div([
        html.Div([
            html.Span(str(n), style={
                "display": "inline-block", "width": "20px", "height": "20px",
                "lineHeight": "20px", "textAlign": "center",
                "borderRadius": "50%", "background": ACCENT, "color": "#fff",
                "fontSize": "0.72rem", "fontWeight": "800",
                "marginRight": "8px"}),
            html.Span(title, style={"color": TEXT_MAIN, "fontWeight": "700",
                                    "fontSize": "0.88rem"}),
        ], style={"marginBottom": "5px"}),
        html.Div(body, style={"color": TEXT_DIM, "fontSize": "0.83rem",
                              "lineHeight": "1.6", "paddingLeft": "28px"}),
    ], style={"marginBottom": "14px"})


def _ci_s(mean_pct: float, sd_pct: float) -> str:
    """A ±1sd interval rendered in SECONDS, in bracket notation.

    "roughly a third of a percent" is not a quantity anyone can picture. The
    interval in seconds at this circuit is, and it is also the honest form of
    the model's claim — a range, not a point.
    """
    lap = _WALK["lap_s"]
    lo = (mean_pct - sd_pct) * lap / 100.0
    hi = (mean_pct + sd_pct) * lap / 100.0
    return f"[{lo:+.2f} s, {hi:+.2f} s]"


def _num(v, unit="%"):
    return html.Span(f"{v}{unit}", style={
        "color": "#FF8A3D", "fontWeight": "700",
        "fontFamily": "ui-monospace, SFMono-Regular, Menlo, monospace"})


def _how_it_works():
    """The collapsed explainer body: one real weekend, end to end."""
    lap = _WALK["lap_s"]
    sec = lambda pct: f"{abs(pct) * lap / 100:.2f} s"
    return html.Div([
        html.Div([
            "Everything on this page is built from ", html.B("two numbers per team"),
            " — how fast one flat-out lap will be (qualifying), and how fast a "
            "typical race lap will be (Sunday). Both are expressed as a ",
            html.B("% gap to the mid-grid car"), ", because a tenth means "
            "something different at Monaco than at Spa. Negative = faster.",
        ], style={"color": TEXT_MAIN, "fontSize": "0.86rem",
                  "lineHeight": "1.65", "marginBottom": "14px"}),

        html.Div(f"Worked example — Ferrari at the {_WALK['event']}. "
                 f"At this track 1.00% ≈ {lap/100:.2f} s a lap.",
                 style={"color": ACCENT, "fontWeight": "700",
                        "fontSize": "0.8rem", "letterSpacing": "0.5px",
                        "marginBottom": "12px"}),

        _step(1, "Thursday: what we believe before anything runs", [
            "The model averages Ferrari's nine previous races this season, "
            "weighting recent ones more (every 4 races, half the weight). It "
            "refuses to look at 2025 or earlier — new regulations reset who is "
            "fast, so the old order is worse than no information. That gives ",
            _num("−1.138"), " ± ", _num("0.321"),
            f" — about {sec(-1.138)} a lap quicker than a mid-grid car, and we "
            "would not be surprised by anything in ",
            _num(_ci_s(-1.138, 0.321), ""),
            " (negative = quicker than the mid-grid car).",
        ]),
        _step(2, "Friday–Saturday: what practice actually said", [
            "Practice laps are not comparable as they stand — different tyres, "
            "different fuel, and a track that gets faster all afternoon. So "
            "each session is fitted with a small regression that adjusts for "
            "compound and tyre age, and the leftover per-driver figure is that "
            "session's estimate. For Ferrari: FP1 said ", _num("−0.961"),
            ", FP2 ", _num("−1.004"), ", FP3 ", _num("−0.893"), ".",
        ]),
        _step(3, "The blend: how far to move toward what we just saw", [
            "Each session gets a share of the move, and the share depends on "
            "two things — how unsure we already were, and how trustworthy that "
            "session is. FP1 runs on a green track with everyone still finding "
            "the circuit, so it barely counts; FP3 runs an hour before "
            "qualifying in near-qualifying trim, so it counts most. Ferrari "
            "moved ", _num("8", "%"), " of the way toward FP1, ",
            _num("12", "%"), " toward FP2 and ", _num("16", "%"),
            " toward FP3. Notice the ± shrinking at every step: that is the "
            "model becoming more certain, and it is the part worth watching.",
        ]),
        dcc.Graph(figure=_walkthrough_fig(), config=GFX),
        _step(4, "Splitting the car into two drivers", [
            "The number so far describes the ", html.B("car"),
            ". Drivers are separated the only honest way — by comparing "
            "team-mates, who share a car, across every event on record. On "
            "that scale Leclerc is worth ", _num("−0.220"),
            " and Hamilton ", _num("−0.062"), " against an average driver, "
            "so Ferrari's ", _num("−1.070"), " becomes ",
            html.B("LEC "), _num("−0.982"), " and ", html.B("HAM "),
            _num("−0.823"), f" — a predicted gap of {sec(0.159)} between them.",
        ]),
        _step(5, "What actually happened", [
            "Ferrari qualified at ", _num("−0.884"), ", so the car estimate "
            f"was {sec(-1.070 + 0.884)} out after three practice sessions — "
            "and the truth landed inside the ± band. Leclerc did out-qualify "
            "Hamilton, but by 0.002 s rather than the predicted "
            f"{sec(0.159)}: the direction was right and the size was not. "
            "That is the honest resolution of most weekends, and it is why "
            "every number here carries a ± rather than pretending to a "
            "decimal it has not earned.",
        ]),
        html.Div("Part two — turning speed into a finishing position",
                 style={"color": ACCENT, "fontWeight": "700",
                        "fontSize": "0.8rem", "letterSpacing": "0.5px",
                        "borderTop": f"1px solid {GRID_CLR}",
                        "paddingTop": "12px", "marginBottom": "12px"}),

        html.Div([
            "Being quickest does not win races. Everything above answers ",
            html.I("how fast"), "; the probabilities on this page answer ",
            html.I("where they finish"), ", and that needs three more things.",
        ], style={"color": TEXT_MAIN, "fontSize": "0.86rem",
                  "lineHeight": "1.65", "marginBottom": "14px"}),

        _step(6, "Where you start, and how much the circuit lets you undo it", [
            "Grid position is the single biggest thing after speed. How much "
            "it can be overturned is measured per circuit, from how strongly "
            "the starting order has predicted the finishing order there "
            "historically. Spa scores ", _num(f"{_RACE['pull']:.2f}", ""),
            " against a field average of ", _num(f"{_RACE['pull_avg']:.2f}", ""),
            " — slightly stickier than typical, so a quick car buried in the "
            "pack recovers a little less than it would elsewhere. Monaco is "
            "far stickier still; Bahrain lets race pace through.",
        ]),
        _step(7, "Cars that do not finish", [
            "About ", _num(f"{_RACE['dnf']:.1%}", ""), " of starts end early "
            "here — a measured base rate scaled by how hard each circuit is on "
            "cars. Team mates are retired together more often than chance, "
            "because the cause often is shared (a bad batch, a first-lap "
            "incident that takes both cars), so the draw is correlated rather "
            "than independent. A per-DRIVER retirement rate was tested and "
            "dropped: it is indistinguishable from noise.",
        ]),
        _step(8, "Run the race 20,000 times", [
            "Each simulated race draws a speed for every car from its ± band, "
            "blends it with the grid by the circuit's stickiness, adds "
            "race-day shuffle for strategy and traffic, and retires the cars "
            "that stop. Counting the outcomes gives the probabilities. "
            "Leclerc started 4th at Spa and came out at ",
            _num("16.5", "%"), " to win, ", _num("62", "%"),
            " for a podium — and the chart below is the part a single "
            "predicted position hides: the model never picked P4, it spread "
            "itself across the whole field.",
        ]),
        dcc.Graph(figure=_outcome_fig(), config=GFX),
        html.Div([
            "Two things worth noticing. Even ", html.B("from pole in the "
            "fastest car"), ", the winner was only ",
            _num(f"{_RACE['ant_pwin']:.0%}", ""), " — a race is not a "
            "procession. And Norris, starting ", _num(str(_RACE["nor_grid"]), ""),
            "th, was given ", _num(f"{_RACE['nor_ppodium']:.0%}", ""),
            " for a podium and finished ", _num(f"P{_RACE['nor_actual']}", ""),
            ": a long shot that did not come in, which is exactly what a ",
            _num(f"{_RACE['nor_ppodium']:.0%}", ""), " claim should look like "
            "most of the time.",
        ], style={"color": TEXT_DIM, "fontSize": "0.82rem",
                  "lineHeight": "1.6", "marginBottom": "14px"}),

        html.Div("How good is it, honestly",
                 style={"color": ACCENT, "fontWeight": "700",
                        "fontSize": "0.8rem", "letterSpacing": "0.5px",
                        "borderTop": f"1px solid {GRID_CLR}",
                        "paddingTop": "12px", "marginBottom": "10px"}),
        html.Div([
            f"Replaying {_SCORE['races']} races "
            f"({_SCORE['rows']:,} driver-races, 2019–2026) with only what was "
            "known beforehand, the finishing position lands ",
            _num(f"{_SCORE['mae_finish']:.1f}", ""), " places out on average. "
            "Against simply knowing how many cars started, it removes ",
            _num(f"{_SCORE['vs_clim']['podium']:.0%}", ""),
            " of the podium error. The harder test is a reference that already "
            "knows the grid — ", html.I("what usually happens from that "
            "starting slot"), ". Against that, the podium and points "
            "predictions are reliably better, but the ",
            html.B("win prediction is not"),
            ": its small edge sits inside the margin of error. Most of what "
            "this model knows about who WINS, it knows from the grid; what it "
            "adds is further down the order.",
        ], style={"color": TEXT_DIM, "fontSize": "0.82rem",
                  "lineHeight": "1.6", "marginBottom": "10px"}),
        html.Div([
            html.B("Where it is weakest. "),
            "Rain. Dry races are well calibrated; wet ones are not, and the "
            "damage sits almost entirely in rain ", html.I("nobody forecast"),
            " — an anticipated wet race is about as predictable as a dry one. "
            "Pit strategy and mid-race weather changes are not modelled at "
            "all. The probabilities are also slightly ",
            html.I("under-confident"), ": strong cars deserve a bit more than "
            "they are given, weak ones a bit less.",
        ], style={"color": TEXT_DIM, "fontSize": "0.82rem",
                  "lineHeight": "1.6", "marginBottom": "10px"}),

        html.Div([
            html.B("How to read the rest of this page: "),
            "treat the ± as the real claim. Two teams whose bands overlap are "
            "not ranked — the model is saying it cannot separate them. The "
            "probabilities come from the 20,000 simulated races described "
            "above, which is why a team can lead the predicted order and still "
            "only win it half the time.",
        ], style={"color": TEXT_DIM, "fontSize": "0.82rem",
                  "lineHeight": "1.6", "borderTop": f"1px solid {GRID_CLR}",
                  "paddingTop": "10px", "marginTop": "4px"}),
    ], style={"background": CARD_BG, "border": f"1px solid {GRID_CLR}",
              "borderLeft": f"4px solid {ACCENT}", "borderRadius": "10px",
              "padding": "18px 22px", "marginBottom": "14px"})


@callback(Output("brief-hiw", "is_open"),
          Input("brief-hiw-toggle", "n_clicks"),
          State("brief-hiw", "is_open"),
          prevent_initial_call=True)
def _toggle_hiw(n, is_open):
    return not is_open


_KIND_CLR = {"onelap": "#FF8A3D", "longrun": "#3DD6C4"}


def _track_record_fig(b: pd.DataFrame, height: int = 360) -> go.Figure:
    """How the season has gone, as two TRAJECTORIES rather than bars.

    This was three panels of grouped bars — roughly 42 of them across seven
    stages, two kinds and three metrics, each metric wanting a different rule
    held in mind ("lower is better" / "higher is better" / "closer to 68").
    The thing being shown is a PROGRESSION though: the error falls as the
    weekend supplies more evidence. A line shows that and a bar chart buries
    it, so the baseline it has to beat became just another bar rather than a
    reference.

    Panel 2 also stops reporting Spearman rho. The same information as
    "% of team pairs put in the right order" (Kendall tau, converted) needs no
    statistics to read: "gets 83% of head-to-heads right" lands where
    "rho = 0.81" does not.

    Calibration moved out entirely — see _calibration_strip_fig.
    """
    order = [s for s in _SCORED_STAGES if s in set(b["stage"])]
    has_tau = "tau" in b.columns and b["tau"].notna().any()
    fig = make_subplots(
        rows=1, cols=2, horizontal_spacing=0.13,
        subplot_titles=("Typical miss, as the weekend unfolds",
                        "Head-to-heads called right"))
    for kind, clr in _KIND_CLR.items():
        d = b[b["kind"] == kind]
        if d.empty:
            continue
        g = d.groupby("stage").agg(mae=("mae", "mean"), rho=("rho", "mean"),
                                   tau=("tau", "mean") if has_tau
                                   else ("rho", "mean"),
                                   n=("event", "nunique"))
        xs = [s for s in order if s in g.index]
        if not xs:
            continue
        lbl = [_STAGE_SHORT.get(s, s) for s in xs]
        cd = [[int(g.loc[s, "n"]), _STAGE_SHORT.get(s, s)] for s in xs]
        fig.add_trace(go.Scatter(
            x=lbl, y=[g.loc[s, "mae"] for s in xs], mode="lines+markers",
            name=_KIND_LABEL[kind], legendgroup=kind,
            line=dict(color=clr, width=2.5), marker=dict(size=8),
            customdata=cd,
            hovertemplate=(f"<b>{_KIND_LABEL[kind]}</b> · %{{customdata[1]}}"
                           "<br>typically out by %{y:.2f}% of a lap"
                           "<br>%{customdata[0]} events<extra></extra>"),
        ), row=1, col=1)
        # pairs correct = (1 + tau) / 2, the plain-English form of a rank score
        pairs = [50 * (1 + g.loc[s, "tau"]) for s in xs]
        fig.add_trace(go.Scatter(
            x=lbl, y=pairs, mode="lines+markers",
            name=_KIND_LABEL[kind], legendgroup=kind, showlegend=False,
            line=dict(color=clr, width=2.5), marker=dict(size=8),
            customdata=cd,
            hovertemplate=(f"<b>{_KIND_LABEL[kind]}</b> · %{{customdata[1]}}"
                           "<br>%{y:.0f}% of head-to-heads right"
                           "<extra></extra>"),
        ), row=1, col=2)
        # the baseline is a REFERENCE, so it is a line across the panel rather
        # than a hollow bar competing with the progression
        base = d[d["stage"] == "raw-FP"]
        if not base.empty:
            fig.add_hline(y=float(base["mae"].mean()), line_color=clr,
                          line_width=1, line_dash="dash", opacity=0.55,
                          row=1, col=1)
            if has_tau and base["tau"].notna().any():
                fig.add_hline(y=50 * (1 + float(base["tau"].mean())),
                              line_color=clr, line_width=1, line_dash="dash",
                              opacity=0.55, row=1, col=2)
    # The baseline is a LEGEND ENTRY, not a floating caption. A caption
    # pinned above the axes collided with the subplot titles on a wide screen,
    # and a dashed line in the legend explains itself anyway.
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="lines",
        line=dict(color=TEXT_DIM, width=1.5, dash="dash"),
        name="just reading the practice timing screen",
        hoverinfo="skip"), row=1, col=1)
    fig.update_layout(**BASE_NO_AXES, height=height)
    theme_axes(fig)
    fig.update_xaxes(gridcolor=GRID_CLR)
    fig.update_yaxes(title_text="% of a lap", gridcolor=GRID_CLR,
                     rangemode="tozero", row=1, col=1)
    fig.update_yaxes(title_text="% correct", gridcolor=GRID_CLR,
                     range=[40, 100], row=1, col=2)
    # legend BELOW the plot: above it there is nowhere to sit that does not
    # run into a subplot title once the card is full width
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.16,
                                  xanchor="center", x=0.5, font=dict(size=10)),
                      margin=dict(l=60, r=20, t=46, b=72))
    for a in fig.layout.annotations:
        a.font.size = 11
        a.font.color = TEXT_MAIN
    return fig


_CALENDAR_PATH = Path("data/season_calendar.csv")
_calendar_cache: dict = {"mtime": None, "map": {}}


def _calendar_labels() -> dict:
    """{(season, event, 'label'|'sprint'): value} from the season calendar.

    Country reads far better on an axis than "R7" — nobody remembers which
    round Barcelona was — and the calendar already carries the sprint flag,
    which matters because a sprint weekend gives the model a timed session
    before qualifying and is therefore not comparable with a normal one.
    """
    try:
        mtime = _CALENDAR_PATH.stat().st_mtime
    except OSError:
        return {}
    if _calendar_cache["mtime"] != mtime:
        out = {}
        try:
            c = pd.read_csv(_CALENDAR_PATH)
            for _, r in c.iterrows():
                k = (int(r["season"]), str(r["event"]))
                out[k + ("label",)] = str(r.get("country") or r["event"])
                out[k + ("sprint",)] = bool(r.get("sprint", False))
        except Exception:
            return {}          # labels are cosmetic; fall back to round numbers
        _calendar_cache.update(mtime=mtime, map=out)
    return _calendar_cache["map"]


def _per_event_fig(b: pd.DataFrame, height: int = 300) -> go.Figure:
    """Weekend by weekend: how far out was the model at each event?

    The trajectory charts answer "does practice help, on average"; they cannot
    answer "which weekends did it actually get right", which is the question
    anyone reading a prediction wants settled before trusting the next one.
    A season mean of 0.28% hides that some events came in at 0.15 and one at
    0.60 — and the outliers are usually explicable (see the hand-curated
    review card), so seeing them individually is what makes the average
    trustworthy rather than mysterious.

    Scored at the SHARPEST pre-outcome stage each weekend reached, which is
    the number that was actually on screen before qualifying.
    """
    fig = go.Figure()
    rank = {s: i for i, s in enumerate(_SCORED_STAGES)}
    rows = []
    for kind in ("onelap", "longrun"):
        d = b[(b["kind"] == kind) & b["stage"].isin(_SCORED_STAGES)]
        if d.empty:
            continue
        d = d.assign(_r=d["stage"].map(rank))
        # last stage each event reached = the final pre-outcome read
        idx = d.groupby(["season", "round", "event"])["_r"].idxmax()
        rows.append(d.loc[idx].assign(kind=kind))
    if not rows:
        theme(fig, height, "")
        return fig
    e = pd.concat(rows, ignore_index=True).sort_values("round")
    cal = _calendar_labels()
    e["label"] = [cal.get((int(s), str(ev), "label"), f"R{int(r)}")
                  for s, ev, r in zip(e["season"], e["event"], e["round"])]
    e["is_sprint"] = [bool(cal.get((int(s), str(ev), "sprint"), False))
                      for s, ev in zip(e["season"], e["event"])]
    order_x = list(dict.fromkeys(e.sort_values("round")["label"]))
    for kind, clr in _KIND_CLR.items():
        g = e[e["kind"] == kind].sort_values("round")
        if g.empty:
            continue
        fig.add_trace(go.Scatter(
            x=g["label"], y=g["mae"], mode="lines+markers",
            name=_KIND_LABEL[kind],
            line=dict(color=clr, width=2),
            # a sprint weekend is a different animal — it hands the model a
            # timed session before qualifying — so it gets its own marker
            # rather than being averaged in silently
            marker=dict(size=[11 if s else 8 for s in g["is_sprint"]],
                        symbol=["diamond" if s else "circle"
                                for s in g["is_sprint"]],
                        color=clr, line=dict(width=1, color="#000")),
            customdata=np.stack([g["event"], g["stage"].map(
                lambda s: _STAGE_SHORT.get(s, s)),
                np.where(g["is_sprint"], "sprint weekend", "normal weekend")],
                axis=-1),
            hovertemplate=("<b>%{customdata[0]}</b> (%{customdata[2]})"
                           "<br>out by %{y:.2f}% of a lap"
                           "<br>sharpest read available: %{customdata[1]}"
                           "<extra></extra>")))
        # THE REFERENCE IS THE BASELINE, NOT THE SEASON MEAN.
        # It was the mean, which made roughly half the events sit above the
        # line by construction — a tautology that reads as "half our weekends
        # are bad". The useful comparison is against simply reading the
        # practice timing screen, where above the line genuinely means the
        # model added nothing.
        base = b[(b["kind"] == kind) & (b["stage"] == "raw-FP")]
        if not base.empty and base["mae"].notna().any():
            fig.add_hline(y=float(base["mae"].mean()), line_color=clr,
                          line_width=1.5, line_dash="dash", opacity=0.65)
    theme(fig, height, "")
    fig.update_layout(
        yaxis_title="% of a lap out",
        legend=dict(orientation="h", x=1, xanchor="right", y=1.02,
                    yanchor="bottom", bgcolor="rgba(0,0,0,0)",
                    font=dict(size=10)),
        margin=dict(l=56, r=20, t=54, b=70))
    fig.update_xaxes(categoryorder="array", categoryarray=order_x,
                     tickangle=-45)
    fig.update_yaxes(rangemode="tozero")
    fig.add_annotation(x=0, y=1.02, xref="paper", yref="paper",
                       xanchor="left", yanchor="bottom",
                       text="dashed = just reading the practice timing screen"
                            "  ·  ◆ = sprint weekend",
                       showarrow=False, font=dict(size=9, color=TEXT_DIM))
    return fig


def _calibration_strip_fig(b: pd.DataFrame, height: int = 150) -> go.Figure:
    """Are the error bars honest? One marker per kind on a 0-100% track, with
    the band a well-calibrated model should land in shaded.

    A bar chart cannot carry this: 68% means nothing without being told it is
    the target, and there is nowhere in a bar to say so. Shading the acceptable
    zone makes the chart self-explaining — inside the band is fine, left of it
    is over-confident, right of it is over-cautious.
    """
    fig = go.Figure()
    rows = []
    for kind in ("onelap", "longrun"):
        d = b[(b["kind"] == kind)
              & (b["stage"].isin(_SCORED_STAGES))]
        if d.empty or "cov68" not in d.columns or d["cov68"].isna().all():
            continue
        rows.append((_KIND_LABEL[kind], 100 * float(d["cov68"].mean()),
                     _KIND_CLR[kind]))
    if not rows:
        theme(fig, height, "")
        return fig
    # Two markers on a 0-100 axis across a full-width card left the data lost
    # in whitespace. Narrowed to 30-100 (below 30 the model would be broken,
    # not miscalibrated) and sat in a narrow column beside the per-event
    # recap, so the width is carrying information instead of padding.
    labels = [r[0] for r in rows]
    fig.add_vrect(x0=58, x1=78, fillcolor=ACCENT, opacity=0.12, line_width=0)
    fig.add_vline(x=68, line_color=ACCENT, line_width=2, line_dash="dot")
    fig.add_trace(go.Scatter(
        x=[r[1] for r in rows], y=labels, mode="markers+text",
        marker=dict(size=16, color=[r[2] for r in rows],
                    line=dict(width=1, color="#000")),
        text=[f"{r[1]:.0f}%" for r in rows], textposition="top center",
        textfont=dict(size=12, color=TEXT_MAIN), showlegend=False,
        hovertemplate="%{y}<br>truth landed inside the ±1sd band "
                      "%{x:.0f}% of the time<extra></extra>"))
    theme(fig, height, "")
    fig.update_layout(
        xaxis_title="% of outcomes inside the model's own error bar",
        margin=dict(l=110, r=24, t=30, b=44))
    fig.update_xaxes(range=[30, 100], gridcolor=GRID_CLR,
                     tickvals=[40, 68, 90],
                     ticktext=["40", "68<br>target", "90"])
    fig.add_annotation(x=68, y=1.0, yref="paper", text="honest",
                       showarrow=False, font=dict(size=9, color=ACCENT),
                       yshift=8)
    fig.add_annotation(x=41, y=1.0, yref="paper", text="over-confident",
                       showarrow=False, font=dict(size=9, color=TEXT_DIM),
                       yshift=8, xanchor="left")
    fig.add_annotation(x=97, y=1.0, yref="paper", text="over-cautious",
                       showarrow=False, font=dict(size=9, color=TEXT_DIM),
                       yshift=8, xanchor="right")
    return fig


_RETENTION_PATH = Path("data/lap_retention.csv")
_SESSION_ORDER = ["Practice 1", "Practice 2", "Practice 3", "Sprint Qualifying",
                  "Sprint Shootout", "Sprint", "Qualifying", "Race"]
# low retention = the model saw little of that session, and that is the alarming
# end, so the scale runs warm-at-the-bottom rather than the usual cool-at-zero.
_KEEP_SCALE = [[0.0, "#8B2F33"], [0.30, "#A8632F"], [0.55, "#3D5A80"],
               [1.0, "#1C8A7A"]]


def _retention_df() -> pd.DataFrame:
    if not _RETENTION_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(_RETENTION_PATH)
    except Exception:
        return pd.DataFrame()


def _retention_heatmap_fig(r: pd.DataFrame, height: int = 320) -> go.Figure:
    """Share of laps the model could use, per session and event."""
    fig = go.Figure()
    if r.empty:
        theme(fig, height, "")
        return fig
    cal = _calendar_labels()
    r = r.copy()
    r["label"] = [cal.get((int(s), str(e), "label"), str(e)[:12])
                  for s, e in zip(r["season"], r["event"])]
    order = (r.drop_duplicates(["event"]).sort_values("round")["label"]
             .drop_duplicates().tolist())
    sess = [s for s in _SESSION_ORDER if s in set(r["session"])]
    piv = (r.pivot_table(index="session", columns="label", values="keep",
                         aggfunc="median")
           .reindex(index=sess, columns=order))
    n_piv = (r.pivot_table(index="session", columns="label", values="driver",
                           aggfunc="count")
             .reindex(index=sess, columns=order))
    fig.add_trace(go.Heatmap(
        z=piv.values * 100, x=piv.columns, y=piv.index,
        customdata=n_piv.values,
        colorscale=_KEEP_SCALE, zmin=0, zmax=100,
        xgap=2, ygap=2,
        colorbar=dict(title=dict(text="% kept", side="right"),
                      thickness=12, len=0.75, tickvals=[0, 25, 50, 75, 100]),
        hovertemplate=("<b>%{y}</b> · %{x}<br>%{z:.0f}% of laps usable"
                       "<br>%{customdata:.0f} drivers<extra></extra>"),
    ))
    fig.update_layout(
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
        height=height, margin=dict(l=110, r=20, t=46, b=70),
        title=dict(text="Share of laps surviving the model's cleaning · "
                        "redder = the model saw less of it",
                   font=dict(size=13)))
    fig.update_xaxes(tickfont=dict(size=9), showgrid=False, tickangle=-45)
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=10),
                     showgrid=False)
    return fig


def _retention_spread_fig(r: pd.DataFrame, height: int = 320) -> go.Figure:
    """Race retention driver by driver — the spread is the point.

    The heatmap shows a weekend's typical retention; this shows how unevenly it
    lands. A car 20 points below its own field median had a materially thinner
    read than everybody else that Sunday, which is the shape that has already
    produced two `measurement_artifact` verdicts.
    """
    fig = go.Figure()
    d = r[r["session"] == "Race"] if not r.empty else r
    if d.empty:
        theme(fig, height, "")
        return fig
    cal = _calendar_labels()
    d = d.copy()
    d["label"] = [cal.get((int(s), str(e), "label"), str(e)[:12])
                  for s, e in zip(d["season"], d["event"])]
    order = (d.drop_duplicates(["event"]).sort_values("round")["label"]
             .drop_duplicates().tolist())
    med = d.groupby("label")["keep"].median().reindex(order)
    fig.add_trace(go.Scatter(
        x=order, y=med.values * 100, mode="lines", name="field median",
        line=dict(color=TEXT_DIM, width=2, dash="dot"), hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=d["label"], y=d["keep"] * 100, mode="markers", name="driver",
        marker=dict(size=6, opacity=0.75,
                    color=[TEAM_COLORS.get(canon(t), ACCENT)
                           for t in d["team"]]),
        customdata=np.stack([d["driver"], d["n_kept"], d["n_total"]], axis=-1),
        hovertemplate=("<b>%{customdata[0]}</b> · %{x}<br>"
                       "%{y:.0f}% kept (%{customdata[1]:.0f} of "
                       "%{customdata[2]:.0f} laps)<extra></extra>")))
    theme(fig, height, "Race day, driver by driver — how evenly the "
                       "cleaning lands")
    fig.update_layout(margin=dict(l=52, r=16, t=46, b=70), showlegend=False,
                      title=dict(font=dict(size=13)))
    fig.update_xaxes(tickangle=-45, tickfont=dict(size=9),
                     categoryorder="array", categoryarray=order)
    fig.update_yaxes(title="% of laps usable", range=[0, 100])
    return fig


def _retention_card(season: int | None = None):
    """What share of each session the model could actually use.

    Not a diagnostic footnote. Every actual the model is scored against is a
    subset of the laps run, and the review has twice found the subset moving a
    driver further than the miss it was trying to explain. Showing it beside
    the track record puts the model's error next to the amount of evidence it
    had to work with.
    """
    r = _retention_df()
    if r.empty:
        return None
    if season is not None and (r["season"] == season).any():
        r = r[r["season"] == season]
    shown = int(r["season"].max())
    r = r[r["season"] == shown]
    if r.empty:
        return None

    race = r[r["session"] == "Race"]
    med_race = float(race["keep"].median()) if not race.empty else float("nan")
    by_sess = r.groupby("session")["keep"].median()
    worst_sess = by_sess.idxmin() if len(by_sess) else None

    # The individual weekends where one car was starved relative to its field.
    # Restricted to cars that actually went the distance: a driver who retired
    # on lap 3 trivially scores 0% and would crowd the list with retirements,
    # which is a different problem from "ran the whole race and the model still
    # could not see it".
    thin = pd.DataFrame()
    if not race.empty:
        full = race.groupby("event")["n_total"].transform("max")
        ran = race[race["n_total"] >= 0.75 * full]
        if not ran.empty:
            fieldmed = ran.groupby("event")["keep"].transform("median")
            thin = ran.assign(_gap=ran["keep"] - fieldmed).nsmallest(5, "_gap")

    body = [dcc.Graph(figure=_retention_heatmap_fig(r), config=GFX),
            dcc.Graph(figure=_retention_spread_fig(r), config=GFX)]
    if not thin.empty:
        cal = _calendar_labels()
        items = ", ".join(
            f"{x['driver']} {cal.get((shown, str(x['event']), 'label'), x['event'])} "
            f"({100 * x['keep']:.0f}%)" for _, x in thin.iterrows())
        body.append(html.Div(
            [html.Span("Thinnest race reads of the season, against their own "
                       "field that day: ", style={"color": TEXT_DIM}),
             html.Span(items, style={"color": TEXT_MAIN})],
            style={"fontSize": "0.74rem", "lineHeight": "1.5",
                   "borderTop": f"1px solid {GRID_CLR}", "paddingTop": "8px",
                   "marginTop": "4px"}))

    return card(
        f"HOW MUCH THE MODEL ACTUALLY SEES · {shown}",
        html.Div(body),
        measure="measured",
        plain=(f"Every number the model is judged on is built from a SUBSET of "
               f"the laps run — only the clean-air ones. On race day it "
               f"typically keeps {100 * med_race:.0f}% of a driver's laps"
               + (f", and {worst_sess} is thinner still at "
                  f"{100 * by_sess.min():.0f}%." if worst_sess else ".")
               + " That is a deliberate choice — it is how you compare cars "
                 "rather than traffic — but it means a driver who spent his "
                 "afternoon stuck behind someone is scored on a small and "
                 "unrepresentative slice of it."),
        info=("Data: scripts/compute_lap_retention.py, which replays every "
              "cached session through the same cleaning the pace model uses "
              "(ValidLap & not dirty-air & not perturbed) and records how many "
              "laps survive per driver. The heatmap is the median driver at "
              "each session; the scatter is every driver on race day, so a car "
              "sitting well below its own field median that weekend stands "
              "out. Two 2026 review rows have already been re-classified as "
              "`measurement_artifact` because this subset, not the model, "
              "explained the miss."))


def _track_record_card(season: int | None = None):
    """How the pace model has actually done — over the season, not this event.

    Returns None when the backtest has never been run.
    """
    b = _backtest_df()
    if b.empty:
        return None
    if season is not None and (b["season"] == season).any():
        b = b[b["season"] == season]
    season_shown = int(b["season"].max())
    b = b[b["season"] == season_shown]
    if b.empty:
        return None
    n_events = int(b["event"].nunique())
    rounds = sorted(b["round"].dropna().unique())
    last_round = int(rounds[-1]) if len(rounds) else None

    # headline: best pre-quali stage vs the "just read the timing screen" baseline
    one = b[b["kind"] == "onelap"]
    verdict = None
    if not one.empty:
        agg = one.groupby("stage").agg(mae=("mae", "mean"),
                                       n=("event", "nunique"))
        by_stage = agg["mae"]
        # Judge the headline on a NORMAL weekend's practice progression only.
        # Sprint weekends hand the model a timed session before qualifying, so
        # quoting their stage as "at its sharpest" would flatter it — and they
        # are a handful of events, so the mean is thin as well.
        model_stages = [s for s in ("prior", "after FP1", "after FP2",
                                    "after FP3")
                        if s in agg.index and agg.loc[s, "n"] >= 4]
        if model_stages and "raw-FP" in by_stage.index:
            best = min(model_stages, key=lambda s: by_stage[s])
            gain = (by_stage["raw-FP"] - by_stage[best]) / by_stage["raw-FP"] * 100
            verdict = (
                f"At its sharpest ({_STAGE_SHORT.get(best, best)}) the model's "
                f"one-lap error is {by_stage[best]:.2f}% — "
                + (f"{gain:.0f}% better than" if gain > 2 else
                   f"about the same as" if gain > -2 else
                   f"{abs(gain):.0f}% WORSE than")
                + " simply taking the fastest practice session at face value.")

    body = [dcc.Graph(figure=_track_record_fig(b), config=GFX)]
    # Weekend-by-weekend beside the calibration strip: the strip needs only a
    # narrow column, and the per-event recap answers the question the season
    # averages above cannot — WHICH weekends it got right.
    has_cov = "cov68" in b.columns and b["cov68"].notna().any()
    body.append(dbc.Row([
        dbc.Col(dcc.Graph(figure=_per_event_fig(b), config=GFX), md=7),
        dbc.Col(dcc.Graph(figure=_calibration_strip_fig(b, height=300),
                          config=GFX), md=5)
        if has_cov else dbc.Col(),
    ]))
    if verdict:
        body.append(html.Div(verdict, style={
            "color": TEXT_MAIN, "fontSize": "0.8rem", "marginTop": "8px",
            "borderLeft": f"3px solid {ACCENT}", "background": "#0E0E1F",
            "padding": "8px 12px", "borderRadius": "4px"}))
    body.append(html.Div(
        f"{season_shown} season · {n_events} events replayed"
        + (f", through round {last_round}" if last_round else ""),
        style={"color": TEXT_DIM, "fontSize": "0.72rem", "marginTop": "6px"}))

    # plain reading: does practice help, and can the +/- be believed?
    plain = None
    if not one.empty:
        agg2 = one.groupby("stage").agg(mae=("mae", "mean"),
                                        cov=("cov68", "mean")
                                        if "cov68" in one.columns
                                        else ("mae", "size"))
        pri = agg2.loc["prior", "mae"] if "prior" in agg2.index else None
        fin = min((agg2.loc[s, "mae"] for s in ("after FP3", "after FP2",
                                                "after FP1")
                   if s in agg2.index), default=None)
        bits = []
        if pri is not None and fin is not None:
            better = pri - fin
            bits.append(
                f"Over {n_events} weekends this season, practice moved the "
                f"typical qualifying miss from {pri:.2f}% of a lap to "
                f"{fin:.2f}%"
                + (" — so the sessions genuinely add something."
                   if better > 0.01 else
                   " — so this season practice has barely helped."))
        if "cov68" in one.columns and one["cov68"].notna().any():
            cov = 100 * float(one["cov68"].mean())
            bits.append(
                f"The truth landed inside the model's own error bar {cov:.0f}% "
                f"of the time; 68% is what an honest error bar should manage, "
                + ("so the ± can be taken at face value."
                   if 58 <= cov <= 78 else
                   "so the ± is currently too narrow — treat close calls as "
                   "closer than they look." if cov < 58 else
                   "so the ± is on the cautious side."))
        plain = " ".join(bits) or None

    return card(
        f"MODEL TRACK RECORD · {season_shown} SEASON",
        html.Div(body),
        plain=plain,
        measure="predicted",
        info=("Data: scripts/backtest_pace_model.py replays every cached "
              "weekend of the season — freezing the prediction at the prior "
              "and after each practice session, then scoring it against what "
              "actually happened. MAE is the average error in pace-gap "
              "percentage points; Spearman ρ is whether the ORDER was right, "
              "which is what a preview really cares about. Solid bars are the "
              "model at each stage; the HOLLOW bar is the 'raw-FP' baseline — "
              "the latest practice session taken literally, with no prior and "
              "no blending. If the solid bars don't beat the hollow one, the "
              "machinery is not earning its keep. Why: the ledger above scores "
              "THIS weekend, which is a sample of one; this is the record that "
              "tells you how much to trust Friday's call. Both the model's "
              "prior and this scorecard read the session-normalised pace "
              "columns, so the error shown is real prediction error rather "
              "than Q1→Q3 track evolution the model could never have seen. "
              "Caveat: 2026 is a NEW FORMULA — its numbers are not expected "
              "to match the ground-effect seasons, and the comparison that "
              "travels across eras is the model-vs-baseline gap, not the raw "
              "error."),
    )


def _order_fig(stage: pd.DataFrame, kind: str) -> go.Figure:
    """Predicted gap to field mean with ±1sd bars, best at top. Axes fit
    whatever teams are in `stage` (so the sidebar filter zooms the view)."""
    d = stage[stage["kind"] == kind].sort_values("mean")
    fig = go.Figure()
    if d.empty:
        theme(fig, 300, "")
        return fig
    labels = [_abbr(t) for t in d["team"]]
    # A DOT with a visible range band, not a bar. A diverging bar puts all the
    # visual weight on the mean and renders the +/- as a hairline whisker —
    # exactly backwards for a model whose actual claim IS the interval. The
    # wide bar is +/-1sd (about a 2-in-3 chance), the thin one +/-2sd, so
    # overlap between two teams is readable at a glance.
    fig.add_trace(go.Scatter(
        x=d["mean"], y=labels, mode="markers", showlegend=False,
        error_x=dict(type="data", array=d["sd"] * 2, color=GRID_CLR,
                     thickness=5, width=0),
        marker=dict(size=1, color="rgba(0,0,0,0)"), hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=d["mean"], y=labels, mode="markers+text", showlegend=False,
        # error_x has NO opacity property — softness has to come from an rgba
        # colour, and passing opacity here raises and takes the whole tab down
        error_x=dict(type="data", array=d["sd"], color="rgba(170,170,170,0.6)",
                     thickness=9, width=0),
        marker=dict(size=11, color=[_clr(t) for t in d["team"]],
                    line=dict(width=1, color="#000")),
        text=[f"{v:+.1f}%" for v in d["mean"]], textposition="middle right",
        textfont=dict(size=9, color=TEXT_MAIN),
        customdata=np.stack([d["team"], d["sd"]], axis=-1),
        hovertemplate="%{customdata[0]}: %{x:>+.2f}%  ±%{customdata[1]:.2f}"
                      "<extra></extra>"))
    theme(fig, max(300, len(d) * 30 + 120), "")
    fig.add_vline(x=0, line_color=TEXT_DIM, line_width=1)
    vmax = float(d["mean"].abs().max() or 1) + float(d["sd"].max() or 0)
    fig.update_layout(showlegend=False,
        xaxis_title="Predicted gap to field mean (%)  ·  faster ← → slower",
        margin=dict(l=64, r=80, t=16, b=44),
        xaxis_range=[d["mean"].min() - vmax * 0.5, d["mean"].max() + vmax * 0.5])
    fig.update_yaxes(autorange="reversed")
    return fig


def _order_plain(stage: pd.DataFrame, kind: str, what: str):
    """Plain reading of a predicted order: who leads, and — the part the chart
    exists for — whether the model is actually willing to call that order."""
    d = stage[stage["kind"] == kind].sort_values("mean")
    if len(d) < 3:
        return None
    top, second = d.iloc[0], d.iloc[1]
    gap = float(second["mean"] - top["mean"])
    line = (f"{_abbr(top['team'])} is predicted quickest {what}, {gap:.2f}% of "
            f"a lap clear of {_abbr(second['team'])}. ")
    if gap < float(top["sd"]) + float(second["sd"]):
        line += ("But their ranges overlap, so the model is NOT calling that "
                 "order — on the day either could come out ahead. ")
    else:
        line += ("Their ranges don't overlap, which is the model saying it is "
                 "reasonably sure of that order. ")
    line += ("The dot is the best guess; the shaded bar around it is where the "
             "truth usually lands, and the faint outer bar is the rarer case. "
             "Wide bar means the model is guessing.")
    return line


def _driver_order_plain(dpred: pd.DataFrame):
    """Plain reading of the per-driver order, leading on the team-mate split
    because that is the bit only this chart shows."""
    if len(dpred) < 4:
        return None
    d = dpred.sort_values("mean")
    top = d.iloc[0]
    mates = d[d["team"] == top["team"]]
    line = (f"{top['driver']} is predicted the quickest car-and-driver "
            f"combination on race pace. ")
    if len(mates) == 2:
        other = mates.iloc[1]
        line += (f"Within {_abbr(top['team'])}, {top['driver']} is put "
                 f"{abs(float(other['mean'] - top['mean'])):.2f}% a lap ahead "
                 f"of {other['driver']} — that split comes from years of "
                 f"team-mate comparisons, not from this weekend. ")
    line += ("Team-mates sit in the same colour, so the distance between two "
             "same-coloured dots is the driver, and the distance between "
             "colours is the car.")
    return line


def _progression_fig(stages: dict[str, pd.DataFrame], kind: str,
                     show_teams: set | None = None) -> go.Figure:
    order = [s for s in _STAGE_SEQUENCE if s in stages]
    teams = sorted(stages[order[-1]]["team"].unique(),
                   key=lambda t: stages[order[-1]].set_index(["team", "kind"])
                   .loc[(t, kind), "mean"] if (t, kind) in
                   stages[order[-1]].set_index(["team", "kind"]).index else 0)
    if show_teams is not None:
        sel = [t for t in teams if t in show_teams]
        teams = sel or teams
    # Eleven equal-weight lines is spaghetti, and the question the chart is
    # asked is "who CHANGED". So the biggest movers keep their team colour and
    # a label; everyone else drops to a thin grey line that still shows the
    # shape of the field without competing for attention.
    series = {}
    for t in teams:
        xs, ys = [], []
        for st in order:
            row = stages[st][(stages[st]["team"] == t)
                             & (stages[st]["kind"] == kind)]
            if not row.empty:
                xs.append(_STAGE_SHORT[st])
                ys.append(float(row["mean"].iloc[0]))
        if xs:
            series[t] = (xs, ys)
    moved = {t: abs(v[1][-1] - v[1][0]) for t, v in series.items()}
    n_hi = 3 if show_teams is None else len(series)
    movers = set(sorted(moved, key=moved.get, reverse=True)[:n_hi])

    fig = go.Figure()
    for t, (xs, ys) in series.items():
        hi = t in movers
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers+text" if hi else "lines",
            name=_abbr(t), showlegend=hi,
            line=dict(color=_clr(t) if hi else GRID_CLR, width=2.5 if hi else 1),
            marker=dict(size=7),
            text=[""] * (len(xs) - 1) + [_abbr(t)] if hi else None,
            textposition="middle right",
            textfont=dict(size=10, color=_clr(t)),
            hovertemplate=f"{_abbr(t)} · %{{x}}<br>%{{y:>+.2f}}%<extra></extra>"))
    theme(fig, 440, "")
    fig.update_layout(
        yaxis_title="Predicted gap to field mean (%)  ·  faster ↑",
        legend=dict(orientation="h", x=0, y=1.12, bgcolor="rgba(0,0,0,0)",
                    font=dict(size=10)),
        margin=dict(l=60, r=70, t=40, b=30))
    fig.update_yaxes(autorange="reversed")
    return fig


def _progression_plain(stages: dict[str, pd.DataFrame], kind: str):
    """Plain reading: who practice actually changed the model's mind about."""
    order = [s for s in _STAGE_SEQUENCE if s in stages]
    if len(order) < 2:
        return None
    first, last = stages[order[0]], stages[order[-1]]
    f = first[first["kind"] == kind].set_index("team")
    l = last[last["kind"] == kind].set_index("team")
    common = [t for t in f.index if t in l.index]
    if len(common) < 3:
        return None
    move = (l.loc[common, "mean"] - f.loc[common, "mean"])
    t = move.abs().idxmax()
    d = float(move[t])
    tighter = float(f.loc[common, "sd"].mean() - l.loc[common, "sd"].mean())
    line = (f"Each line is a team, tracked from the pre-weekend guess to the "
            f"latest read. {_abbr(t)} moved most: "
            f"{'faster' if d < 0 else 'slower'} by {abs(d):.2f}% of a lap "
            f"since Thursday. ")
    if tighter > 0.005:
        line += (f"Across the field the model also got {tighter:.2f}% more "
                 f"certain — flat lines that stop wandering are the sign it "
                 f"has settled. ")
    line += "Greyed-out teams are the ones practice barely changed."
    return line


def _driver_order_fig(dpred: pd.DataFrame) -> go.Figure:
    """Per-driver predicted race pace, teammates adjacent, ±1sd bars."""
    d = dpred.sort_values("mean")
    fig = go.Figure()
    if d.empty:
        theme(fig, 360, "")
        return fig
    labels = [f"{r['driver']}" for _, r in d.iterrows()]
    fig.add_trace(go.Scatter(
        x=d["mean"], y=labels, mode="markers", showlegend=False,
        error_x=dict(type="data", array=d["sd"] * 2, color=GRID_CLR,
                     thickness=4, width=0),
        marker=dict(size=1, color="rgba(0,0,0,0)"), hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=d["mean"], y=labels, mode="markers+text", showlegend=False,
        error_x=dict(type="data", array=d["sd"], color="rgba(170,170,170,0.6)",
                     thickness=7, width=0),
        marker=dict(size=9, color=[_clr(t) for t in d["team"]],
                    line=dict(width=1, color="#000")),
        text=[f"{v:+.1f}%" for v in d["mean"]], textposition="middle right",
        textfont=dict(size=9, color=TEXT_MAIN),
        customdata=np.stack([d["team"], d["effect"], d["sd"]], axis=-1),
        hovertemplate="%{y} (%{customdata[0]})<br>%{x:>+.2f}%  ±%{customdata[2]:.2f}"
                      "  ·  driver effect %{customdata[1]:>+.2f}%<extra></extra>"))
    theme(fig, max(360, len(d) * 24 + 120), "")
    fig.add_vline(x=0, line_color=TEXT_DIM, line_width=1)
    vmax = float(d["mean"].abs().max() or 1) + float(d["sd"].max() or 0)
    fig.update_layout(showlegend=False,
        xaxis_title="Predicted race-pace gap to field mean (%)  ·  faster ← → slower",
        margin=dict(l=54, r=80, t=16, b=44),
        xaxis_range=[d["mean"].min() - vmax * 0.5, d["mean"].max() + vmax * 0.5])
    fig.update_yaxes(autorange="reversed")
    return fig


def _forecast_fig(fc: pd.DataFrame) -> go.Figure:
    """Stacked win / podium / points probability bars per driver, ordered by
    expected finish."""
    d = fc.sort_values("e_finish")
    labels = list(d["driver"])
    fig = go.Figure()
    # podium-but-not-win and points-but-not-podium as lighter segments
    p_win = d["p_win"].values * 100
    p_pod_only = (d["p_podium"] - d["p_win"]).clip(lower=0).values * 100
    p_pts_only = (d["p_points"] - d["p_podium"]).clip(lower=0).values * 100
    cols = [_clr(t) for t in d["team"]]
    fig.add_trace(go.Bar(y=labels, x=p_win, orientation="h", name="Win",
        marker_color=cols, marker_line=dict(width=0),
        hovertemplate="%{y} · P(win) %{x:.0f}%<extra></extra>"))
    fig.add_trace(go.Bar(y=labels, x=p_pod_only, orientation="h", name="Podium",
        marker_color=cols, marker_opacity=0.55, marker_line=dict(width=0),
        hovertemplate="%{y} · P(podium) adds %{x:.0f}%<extra></extra>"))
    fig.add_trace(go.Bar(y=labels, x=p_pts_only, orientation="h", name="Points",
        marker_color=cols, marker_opacity=0.28, marker_line=dict(width=0),
        hovertemplate="%{y} · P(points) adds %{x:.0f}%<extra></extra>"))
    theme(fig, max(360, len(d) * 22 + 130), "")
    fig.update_layout(barmode="stack", showlegend=True,
        legend=dict(orientation="h", x=0, y=1.06, bgcolor="rgba(0,0,0,0)"),
        xaxis_title="Probability (%)  ·  solid = win, mid = podium, faint = points",
        margin=dict(l=54, r=20, t=44, b=44))
    fig.update_yaxes(autorange="reversed")
    return fig


def _scatter_ledger(pv: pd.Series, sd: pd.Series, av: pd.Series, colors: dict,
                    show: set | None, x_title: str,
                    label_size: int) -> go.Figure:
    """Predicted-vs-actual as a DUMBBELL, one row per entrant.

    This replaced a predicted-vs-actual scatter with a parity line, which has
    a structural flaw for this data: both axes carry the same units and the
    same range, so every point hugs the diagonal and the quantity you actually
    want — the MISS — is the smallest dimension on the chart. It also had
    nowhere to show the model's own +/- , so a forgivable miss inside the
    error bar looked identical to a real failure.

    Here the miss is a horizontal distance you read directly, and the error
    bar sits on the prediction so "did it know it was unsure?" is answerable
    at a glance. Rows are ordered by the ACTUAL result, fastest at the top,
    so the chart also reads as the real classification.

    pv/sd/av are centered on the FULL field (positions stay truthful); `show`
    filters which rows are drawn and the axis zooms to them.
    """
    keys = [k for k in av.sort_values().index if k in pv.index]
    if show is not None:
        keys = [k for k in keys if k in show] or keys
    fig = go.Figure()
    if keys:
        labels = [colors[k][2] for k in keys]
        for k, lab in zip(keys, labels):
            # DOTTED, not solid. The connector and the error bar share a row,
            # so a solid connector reads as part of the bar — and the case you
            # most need to see (reality landing OUTSIDE the bar) is exactly
            # where the two overlap and become one indistinguishable line.
            fig.add_trace(go.Scatter(
                x=[pv[k], av[k]], y=[lab, lab], mode="lines",
                line=dict(color=TEXT_DIM, width=1, dash="dot"),
                showlegend=False, hoverinfo="skip"))
        miss = [float(av[k] - pv[k]) for k in keys]
        cd = [[colors[k][2], float(sd.get(k, float("nan"))), m,
               "inside" if abs(m) <= float(sd.get(k, 0) or 0) else "outside"]
              for k, m in zip(keys, miss)]
        fig.add_trace(go.Scatter(
            x=[float(pv[k]) for k in keys], y=labels, mode="markers",
            name="predicted (± its own range)",
            error_x=dict(type="data", array=[float(sd.get(k, 0) or 0)
                                             for k in keys],
                         color=TEXT_DIM, thickness=1.5, width=5),
            marker=dict(size=11, symbol="circle-open",
                        color=[colors[k][1] for k in keys],
                        line=dict(width=2, color=[colors[k][1] for k in keys])),
            customdata=cd,
            hovertemplate="%{customdata[0]}<br>predicted %{x:>+.2f}%"
                          " ± %{customdata[1]:.2f}<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=[float(av[k]) for k in keys], y=labels, mode="markers",
            name="what actually happened",
            marker=dict(size=11, symbol="circle",
                        color=[colors[k][1] for k in keys],
                        line=dict(width=1, color="#000")),
            customdata=cd,
            hovertemplate="%{customdata[0]}<br>actual %{x:>+.2f}%"
                          "<br>out by %{customdata[2]:>+.2f}%"
                          " — %{customdata[3]} the error bar<extra></extra>"))
    theme(fig, max(320, len(keys) * 26 + 130), "")
    fig.add_vline(x=0, line_color=TEXT_DIM, line_width=1)
    fig.update_layout(
        xaxis_title=x_title,
        legend=dict(orientation="h", x=0, y=1.10, bgcolor="rgba(0,0,0,0)",
                    font=dict(size=10)),
        margin=dict(l=64, r=30, t=44, b=44))
    fig.update_yaxes(autorange="reversed")
    return fig


def _ledger_plain(pv: pd.Series, sd: pd.Series, av: pd.Series,
                  label_of, noun: str):
    """Plain reading of a ledger: did it call the right winner, and did its
    error bars actually hold?"""
    keys = [k for k in pv.index if k in av.index]
    if len(keys) < 3:
        return None
    err = (av[keys] - pv[keys]).abs()
    band = sd.reindex(keys).fillna(0.0)
    inside = int((err <= band).sum())
    n = len(keys)
    want = round(0.68 * n)
    pred_best, act_best = label_of(pv[keys].idxmin()), label_of(av[keys].idxmin())
    worst = err.idxmax()
    line = (f"The model expected {pred_best} to be quickest; "
            + (f"{act_best} was." if pred_best != act_best
               else "that is what happened.")
            + f" The hollow marker is what it predicted and the bar is how "
              f"unsure it was; the solid marker is what {noun} actually did. ")
    line += (f"{inside} of {n} landed inside their own error bar — about "
             f"{want} is what a well-calibrated model should manage. ")
    line += (f"Biggest miss: {label_of(worst)}, out by {err[worst]:.2f}% "
             f"of a lap.")
    return line


_REVIEW_PATH = Path("data/model_review.csv")
_REVIEW_KIND = {"onelap": "qualifying", "longrun": "race pace"}


def _model_review_card(season: int, event: str):
    """Hand-written notes on why the model missed, for this event.

    Everything else on this page is computed and falsifiable. This card is
    NOT — it is hand-curated judgement, written after watching the race, and it is
    styled differently so it can never be mistaken for model output.

    It exists because the ledger can prove the model was wrong and can never
    say why: only a person knows a car ran the second half with damage, or
    pitted out of sequence under a safety car. Those are the causes the pace
    model explicitly does not simulate, so this is the record of the gap it
    already admits to — and, over a season, of which unmodelled factor costs
    the most.

    Rows are seeded automatically by scripts/seed_model_review.py (every
    driver who finished outside their own +/-1sd band); a person supplies only
    `category` and `note`. Returns None when the file has nothing for this
    event, so an unreviewed weekend simply shows no card.
    """
    if not _REVIEW_PATH.exists():
        return None
    try:
        r = pd.read_csv(_REVIEW_PATH)
    except Exception:
        return None
    ev = r[(r["season"] == season) & (r["event"] == event)]
    if ev.empty:
        return None

    def _entry(x):
        # NOT `x.get("note") or ""` — an empty CSV cell arrives as NaN, and
        # float('nan') is TRUTHY, so that idiom yields the string "nan" and
        # every unreviewed row renders as though somebody wrote "nan" in it.
        note = "" if pd.isna(x.get("note")) else str(x.get("note")).strip()
        cat = "" if pd.isna(x.get("category")) else str(x.get("category")).strip()
        return html.Div([
            html.Div([
                html.Span(str(x["driver"]), style={
                    "color": _clr(str(x.get("team", ""))), "fontWeight": "800",
                    "fontSize": "0.86rem", "marginRight": "8px"}),
                html.Span(f"out by {abs(float(x['miss'])):.2f}%",
                          style={"color": TEXT_MAIN, "fontSize": "0.76rem",
                                 "marginRight": "8px"}),
                (html.Span(cat, style={
                    "background": GRID_CLR, "color": TEXT_MAIN,
                    "borderRadius": "3px", "padding": "1px 6px",
                    "fontSize": "0.68rem", "letterSpacing": "0.5px"})
                 if cat else html.Span("unreviewed", style={
                     "color": TEXT_DIM, "fontSize": "0.68rem",
                     "fontStyle": "italic"})),
            ], style={"marginBottom": "3px"}),
            html.Div(note or "— no note written yet —", style={
                "color": TEXT_MAIN if note else TEXT_DIM,
                "fontSize": "0.79rem", "lineHeight": "1.45",
                "fontStyle": "normal" if note else "italic"}),
        ], style={"borderLeft": f"2px solid {GRID_CLR}",
                  "paddingLeft": "10px", "marginBottom": "10px"})

    # Split by KIND into two columns. A single list interleaved qualifying and
    # race rows for the same driver, which reads as duplication — the same
    # name twice with different numbers — when they are two separate misses
    # about two separate sessions.
    def _column(kind, title):
        sub = ev[ev["kind"] == kind].sort_values("driver")
        head = html.Div(title, style={
            "color": _KIND_CLR.get(kind, ACCENT), "fontWeight": "800",
            "fontSize": "0.72rem", "letterSpacing": "1px",
            "marginBottom": "8px"})
        if sub.empty:
            return dbc.Col([head, html.Div(
                "Every driver inside the error bar here.",
                style={"color": TEXT_DIM, "fontSize": "0.78rem",
                       "fontStyle": "italic"})], md=6)
        return dbc.Col([head] + [_entry(x) for _, x in sub.iterrows()], md=6)

    rows = [dbc.Row([_column("onelap", "QUALIFYING"),
                     _column("longrun", "RACE PACE")])]

    # season tally — the reason `category` is a fixed vocabulary rather than
    # free text: it turns a pile of anecdotes into "how much of our error is
    # something we chose not to model?"
    season_rows = r[r["season"] == season]
    tally = (season_rows["category"].fillna("").str.strip()
             .replace("", np.nan).dropna().value_counts())
    foot = None
    if len(tally):
        total = int(tally.sum())
        model_share = int(tally.get("model_miss", 0))
        foot = html.Div([
            html.Span(f"{season} so far: ", style={"color": TEXT_DIM}),
            html.Span(" · ".join(f"{k} {v}" for k, v in tally.items()),
                      style={"color": TEXT_MAIN}),
            html.Span(f"  —  {100 * model_share / total:.0f}% of reviewed "
                      f"misses were the model itself rather than something "
                      f"it never claimed to simulate.",
                      style={"color": TEXT_DIM}),
        ], style={"fontSize": "0.74rem", "lineHeight": "1.5",
                  "borderTop": f"1px solid {GRID_CLR}", "paddingTop": "8px",
                  "marginTop": "4px"})

    n_open = int((ev["note"].fillna("").str.strip() == "").sum())
    return card(
        "WHY THE MODEL MISSED · HAND-CURATED",
        html.Div([
            html.Div("Hand-curated after the race — not model output. "
                     "Every driver here finished outside the model's own error "
                     "bar.",
                     style={"color": TEXT_DIM, "fontSize": "0.74rem",
                            "fontStyle": "italic", "marginBottom": "10px"}),
            *rows,
            *([foot] if foot is not None else []),
        ]),
        info="Seeded by scripts/seed_model_review.py, which lists every driver "
             "whose actual result fell outside ±1sd of the prediction and "
             "fills in the numbers; the cause and the note are written by "
             "hand afterwards. Categories come from a fixed vocabulary so a "
             "season of notes can be counted, which is what answers 'how much "
             "of our error is unmodelled incident versus genuine model error?'",
        plain=(f"The model got {len(ev)} driver-result{'s' if len(ev) != 1 else ''} "
               f"wrong by more than its own error bar this weekend"
               + (f", and {n_open} of them still need a note writing."
                  if n_open else
                  " — each one explained above by someone who watched the "
                  "race.")))


def _ledger_parts(pred: pd.DataFrame, actual: pd.Series, kind: str):
    """(pv, sd, av, colors) for a team ledger, or None when nothing lines up."""
    p = pred[pred["kind"] == kind].set_index("team")
    common = [t for t in p.index if t in actual.index]
    if not common:
        return None
    pv = p.loc[common, "mean"] - p.loc[common, "mean"].mean()
    sd = p.loc[common, "sd"] if "sd" in p.columns else pd.Series(0.0, index=common)
    av = actual[common] - actual[common].mean()
    # colors[key] = (team, colour, label) — team used for the show-filter
    return pv, sd, av, {t: (t, _clr(t), _abbr(t)) for t in common}


def _ledger_fig(pred: pd.DataFrame, actual: pd.Series, kind: str,
                show: set | None = None) -> go.Figure:
    parts = _ledger_parts(pred, actual, kind)
    if parts is None:
        e = pd.Series(dtype=float)
        return _scatter_ledger(e, e, e, {}, None, "", 9)
    pv, sd, av, colors = parts
    return _scatter_ledger(pv, sd, av, colors, show,
                           "Gap to field mean (%)  ·  faster ← → slower", 9)


def _driver_ledger_parts(dpred: pd.DataFrame, actual: pd.Series):
    p = dpred.set_index("driver")
    common = [d for d in p.index if d in actual.index]
    if not common:
        return None
    pv = p.loc[common, "mean"] - p.loc[common, "mean"].mean()
    sd = p.loc[common, "sd"] if "sd" in p.columns else pd.Series(0.0, index=common)
    av = actual[common] - actual[common].mean()
    return pv, sd, av, {d: (d, _clr(p.loc[d, "team"]), d) for d in common}


def _driver_ledger_fig(dpred: pd.DataFrame, actual: pd.Series,
                       show: set | None = None) -> go.Figure:
    parts = _driver_ledger_parts(dpred, actual)
    if parts is None:
        e = pd.Series(dtype=float)
        return _scatter_ledger(e, e, e, {}, None, "", 8)
    pv, sd, av, colors = parts
    return _scatter_ledger(pv, sd, av, colors, show,
                           "Race-pace gap to field mean (%)  ·  faster ← → slower",
                           8)


# ─────────────────────────────────────────────────────────────
# Tab
# ─────────────────────────────────────────────────────────────

def tab_brief(sel_drivers=None, sel_teams=None):
    ev = _loaded_event()
    if ev is None:
        return html.P("No event loaded.", style={"color": TEXT_DIM})
    season, event = ev

    # Sidebar filters. The model is always computed on the FULL field (so gaps,
    # probabilities and ledger scores stay correct); the filters only choose
    # which teams/drivers each chart DISPLAYS, and the axes zoom to them. A
    # filter that matches nothing falls back to the full field rather than
    # blanking the page. `None` = show everything.
    teams_sel = ({canon(t) for t in sel_teams} if sel_teams else None)
    drivers_sel = (set(sel_drivers) if sel_drivers else None)

    # Actual qualifying gaps (Qualifying session only — Sprint Quali is
    # already a model input) feed the optional post-quali long-run update.
    laps = state.laps
    q_gap = pd.Series(dtype=float)
    if laps is not None and not laps.empty and "session" in laps.columns:
        q_gap = _model().actual_quali_gap(laps[laps["session"] == "Qualifying"])

    try:
        stages = _model().predict_weekend(
            season, event, quali_gap=q_gap if not q_gap.empty else None)
    except ValueError:
        return html.Div(dbc.Alert(
            [f"No season pace table entry for {season} {event}. Generate it "
             "with ", html.Code("python compute_team_pace.py"),
             f" --season {season}."], color="warning"))

    stage_names = list(stages)
    final_name = stage_names[-1]
    final = stages[final_name]
    # The last outcome-blind snapshot: everything one-lap (predicted quali
    # order, probabilities, the one-lap ledger) is pinned to THIS stage, so
    # the quali prediction is guaranteed to be the one made before quali ran.
    # Only the long-run (race) prediction reads `final`, which may include
    # the "after Quali" update.
    pq_names = [n for n in stage_names if n != "after Quali"]
    pre_quali_name = pq_names[-1]
    pre_quali = stages[pre_quali_name]
    has_practice = pre_quali_name != "prior"

    def _show_teams(df):
        if teams_sel is None:
            return df
        out = df[df["team"].isin(teams_sel)]
        return out if not out.empty else df

    def _show_drivers(df):
        out = df
        if teams_sel is not None:
            out = out[out["team"].isin(teams_sel)]
        if drivers_sel is not None:
            out = out[out["driver"].isin(drivers_sel)]
        return out if not out.empty else df

    intro = html.P([
        html.B("Progressive weekend prediction.  "),
        "Starts from an era-aware season-form prior and sharpens after every "
        "practice session. Bars are the predicted gap to the field mean; "
        "whiskers are ±1 standard deviation — the model's own uncertainty. ",
        "One-lap (qualifying) prediction is strong; long-run (race) pace is a "
        "weaker read and leans more on season form — see ",
        html.Code("backtest_pace_model.py"), " for the validation.",
    ], style={"color": TEXT_DIM, "fontSize": "0.8rem", "lineHeight": "1.5",
              "marginBottom": "14px"})

    # ── KPI strip ───────────────────────────────────────────────
    probs = _model().outcome_probs(pre_quali, "onelap")
    kpis = []
    if not probs.empty:
        top = probs.iloc[0]
        kpis.append(kpi("PREDICTED ONE-LAP SPEED", f"{_abbr(top['team'])}",
            tooltip="Team with the fastest predicted one-lap speed at the "
                    "current stage of the weekend."))
        kpis.append(kpi("P(POLE-PACE TEAM)", f"{top['p_best']*100:.0f}%",
            color="#FFD700",
            tooltip="Monte-Carlo probability this team has the field's fastest "
                    "one-lap speed, given the model's uncertainty and event-day "
                    "execution noise. Team-level, not driver-level."))
    # biggest mover since previous PRE-QUALI stage (the quali stage never
    # moves the one-lap latent, so comparing against it would show 0.00)
    if len(pq_names) >= 2:
        prev = stages[pq_names[-2]].set_index(["team", "kind"])["mean"]
        cur = pre_quali.set_index(["team", "kind"])["mean"]
        d = (cur - prev).dropna()
        d = d[[i for i in d.index if i[1] == "onelap"]]
        if not d.empty:
            mover = d.abs().idxmax()
            delta = d[mover]
            kpis.append(kpi(f"BIGGEST MOVE · {_STAGE_SHORT.get(pre_quali_name, pre_quali_name)}",
                f"{_abbr(mover[0])} {delta:+.2f}%",
                color=ACCENT,
                tooltip=f"Largest change in predicted one-lap gap from "
                        f"{_STAGE_SHORT.get(pq_names[-2], pq_names[-2])} "
                        f"to {_STAGE_SHORT.get(pre_quali_name, pre_quali_name)}. "
                        "Negative = gained pace."))
    stage_pill_txt = ("Pre-weekend prior" if not has_practice
                      else f"Updated through {_STAGE_SHORT.get(final_name, final_name)}")
    kpis.append(kpi("WEEKEND STAGE", stage_pill_txt,
        color=ACCENT if has_practice else TEXT_MAIN,
        tooltip="How far into the weekend the prediction reflects. Each "
                "practice session with clean pace data sharpens it. Once "
                "qualifying is in, the real quali result sharpens the RACE "
                "(long-run) prediction only — the qualifying prediction and "
                "its ledger stay frozen at the last pre-quali session, so "
                "the model is always scored on what it said beforehand."))
    body = [intro,
            # collapsed by default: regulars skip it, first-timers get the
            # whole model in one worked weekend rather than a glossary
            html.Div(_hiw_toggle_button(), style={"marginBottom": "8px"}),
            dbc.Collapse(_how_it_works(), id="brief-hiw", is_open=False),
            dbc.Row(kpis, className="mb-2")]

    # ── Predicted order (one-lap + long-run) ────────────────────
    # one-lap from the pre-quali snapshot (a true prediction of qualifying);
    # long-run from the final stage (sharpened by the real quali result once
    # it is loaded).
    pre_quali_show = _show_teams(pre_quali)
    final_show = _show_teams(final)
    body.append(dbc.Row([
        dbc.Col(card(f"PREDICTED ORDER · {_KIND_LABEL['onelap'].upper()}",
            dcc.Graph(figure=_order_fig(pre_quali_show, "onelap"), config=GFX),
            info="Predicted one-lap speed as a gap to the field mean, at "
                 "the last PRE-quali stage — this chart never uses the quali "
                 "result itself, so it stays an honest prediction. Whiskers "
                 "are ±1sd. Team pace = the team's faster driver. This is "
                 "ONE-LAP SPEED: a single flat-out lap, not race pace.",
            plain=_order_plain(pre_quali_show, "onelap", "over one flat-out lap"),
            measure="predicted"), md=6),
        dbc.Col(card(f"PREDICTED ORDER · {_KIND_LABEL['longrun'].upper()}",
            dcc.Graph(figure=_order_fig(final_show, "longrun"), config=GFX),
            info="Predicted race pace as a gap to the field mean. Long-run "
                 "practice is a weak, fuel/mode-polluted signal, so this "
                 "leans on season race form more than the one-lap chart — "
                 "treat its ordering as indicative. Once qualifying is "
                 "loaded, the real quali gaps sharpen it further (quali is "
                 "hard evidence of car pace, translated to race pace with "
                 "extra uncertainty).",
            plain=_order_plain(final_show, "longrun", "over a race stint"),
            measure="predicted"), md=6),
    ]))

    # ── Progression across the weekend ──────────────────────────
    if has_practice:
        body.append(dbc.Row([dbc.Col(card("PREDICTION PROGRESSION · ONE-LAP SPEED",
            dcc.Graph(figure=_progression_fig(stages, "onelap", teams_sel),
                      config=GFX),
            info="Each team's predicted one-lap gap at every stage, prior → "
                 "FP3 (plus Sprint sessions on a sprint weekend). Lines "
                 "converging and reordering show what each session taught the "
                 "model. Y-axis inverted: up = faster. The three biggest "
                 "movers keep their team colour; the rest are greyed so the "
                 "chart answers 'who changed' rather than showing eleven "
                 "equal lines.",
            plain=_progression_plain(stages, "onelap"),
            measure="predicted"), md=12)]))

    # ── Win / podium probabilities ──────────────────────────────
    if not probs.empty:
        rows = [{"Team": r["team"], "Pred gap %": f"{r['mean']:+.2f}",
                 "±sd": f"{r['sd']:.2f}",
                 "P(fastest)": f"{r['p_best']*100:.0f}%",
                 "P(top 3)": f"{r['p_top3']*100:.0f}%"}
                for _, r in probs.iterrows()
                if teams_sel is None or r["team"] in teams_sel]
        if not rows:
            rows = [{"Team": r["team"], "Pred gap %": f"{r['mean']:+.2f}",
                     "±sd": f"{r['sd']:.2f}",
                     "P(fastest)": f"{r['p_best']*100:.0f}%",
                     "P(top 3)": f"{r['p_top3']*100:.0f}%"}
                    for _, r in probs.iterrows()]
        from dash import dash_table
        from f1lib.components import TABLE_STYLE
        body.append(card("ONE-LAP SPEED PROBABILITIES",
            dash_table.DataTable(data=rows,
                columns=[{"name": c, "id": c} for c in rows[0]], **TABLE_STYLE),
            info="Monte-Carlo probability each team has the fastest / a top-3 "
                 "one-lap speed, from the predicted gaps, their uncertainty and "
                 "an event-day execution-noise term. Team pace, not driver — "
                 "it does not model qualifying mistakes or grid penalties."))

    # ── Driver race-pace outlook (team latent × driver rating) ──
    roster = (state.laps.dropna(subset=["Driver_Short", "Team"])
              [["Driver_Short", "Team"]].drop_duplicates()
              .rename(columns={"Driver_Short": "driver", "Team": "team"})
              if state.laps is not None else pd.DataFrame())
    round_ = _model().round_of(season, event) or _model().next_round_of(season)
    dpred = _model().driver_predictions(final, roster, "longrun",
                                        as_of=(season, round_))
    # ONE-LAP per driver comes off the PRE-quali snapshot, never `final` — the
    # post-quali stage feeds the real result into the long-run latent, and
    # scoring one-lap after that would be qualifying predicting qualifying.
    dpred_onelap = _model().driver_predictions(pre_quali, roster, "onelap",
                                               as_of=(season, round_))
    # set below when the long-run block runs; the one-lap ledger can render
    # without it, and None simply means "no sidebar zoom"
    drivers_show = None
    if not dpred.empty:
        dprobs = _model().driver_outcome_probs(dpred)          # full field
        dprobs_show = _show_drivers(dprobs)
        dpred_show = _show_drivers(dpred)
        drivers_show = set(dpred_show["driver"])
        drows = [{"Driver": r["driver"], "Team": _abbr(r["team"]),
                  "Pred gap %": f"{r['mean']:+.2f}", "±sd": f"{r['sd']:.2f}",
                  "P(fastest)": f"{r['p_best']*100:.0f}%",
                  "P(top 3)": f"{r['p_top3']*100:.0f}%"}
                 for _, r in dprobs_show.iterrows()]
        from dash import dash_table
        from f1lib.components import TABLE_STYLE
        body.append(html.Div([
            html.H4("DRIVER RACE-PACE OUTLOOK", style={
                "color": TEXT_MAIN, "fontWeight": "800", "letterSpacing": "2px",
                "fontSize": "1.0rem", "marginTop": "8px", "marginBottom": "4px",
                "borderBottom": f"2px solid {ACCENT}", "paddingBottom": "6px"}),
            html.P([
                "The team's predicted race pace, split between its drivers by a ",
                html.B("teammate-relative driver rating"),
                " (driver_ratings.py) — a fixed-effects estimate of how much "
                "each driver adds to or subtracts from their car, fitted across "
                "all eras with recency weighting (driver skill, unlike car pace, "
                "carries across regulation changes). Backtested, the split "
                "improves per-driver race-pace error on ~2/3 of events; the car "
                "still dominates, so treat it as a refinement, strongest for "
                "standout drivers.",
            ], style={"color": TEXT_DIM, "fontSize": "0.78rem",
                      "lineHeight": "1.5", "marginBottom": "12px"}),
            dbc.Row([
                dbc.Col(card("PREDICTED DRIVER RACE PACE",
                    dcc.Graph(figure=_driver_order_fig(dpred_show), config=GFX),
                    info="Per-driver predicted race-pace gap to the field mean. "
                         "Dot colour = team; teammates share the car so their "
                         "difference is the driver rating. The shaded band is "
                         "±1sd and combines car and driver-rating uncertainty. "
                         "RACE pace = the median of clean green-flag laps on "
                         "race fuel — not a qualifying lap.",
                    plain=_driver_order_plain(dpred_show),
                    measure="predicted"), md=6),
                dbc.Col(card("RACE-PACE PROBABILITIES (per driver)",
                    dash_table.DataTable(data=drows,
                        columns=[{"name": c, "id": c} for c in drows[0]],
                        **TABLE_STYLE),
                    info="Monte-Carlo P(fastest race pace) and P(top-3 race "
                         "pace) per driver. Teammates share their car's draw "
                         "(a strong car lifts both), so their odds move "
                         "together. Pace only — not race-day strategy, "
                         "reliability or incidents.",
                    measure="predicted"), md=6),
            ]),
        ]))

    # ── Race result forecast (pace × grid × overtaking difficulty) ──
    rf = _forecaster()
    if not dpred.empty and rf is not None:
        qpred = _model().driver_predictions(
            pre_quali, roster, "onelap", as_of=(season, round_))
        # real grid once qualifying is loaded, else sample it from the one-lap
        # prediction (so the pre-quali forecast carries grid uncertainty)
        grid = None
        if state.laps is not None and "Grid_Position" in state.laps.columns:
            gser = (state.laps.dropna(subset=["Grid_Position"])
                    .drop_duplicates("Driver_Short")
                    .set_index("Driver_Short")["Grid_Position"])
            gser = gser[gser > 0]
            if len(gser) >= 8:
                grid = gser.astype(int).to_dict()
        fc = rf.forecast(dpred, event=event, grid=grid,
                         quali_pred=None if grid else qpred)
        if not fc.empty:
            grid_note = ("using the actual qualifying grid" if grid
                         else "grid sampled from the one-lap prediction "
                              "(pre-qualifying)")
            pull = rf.passability(event)
            pass_lbl = ("hard to pass — grid sticks" if pull < 0.4
                        else "easy to pass — pace wins" if pull > 0.65
                        else "moderate")
            win = fc.loc[fc["p_win"].idxmax()]
            fkpis = [
                kpi("PREDICTED WINNER", f"{win['driver']}  ·  {win['p_win']*100:.0f}%",
                    color="#FFD700",
                    tooltip="Driver with the highest win probability in the "
                            "race simulation. Pace + grid + overtaking "
                            "difficulty; not strategy or incidents."),
                kpi("OVERTAKING DIFFICULTY",
                    f"{pass_lbl}  ({pull:.2f})",
                    tooltip="Circuit passability from history (grid↔finish "
                            "stickiness). Low = pace can't overcome grid "
                            "(Monaco); high = pace wins through (Monza)."),
                kpi("GRID SOURCE", "Actual" if grid else "Predicted",
                    color=ACCENT if grid else TEXT_MAIN,
                    tooltip="Whether the forecast uses the real qualifying grid "
                            "or a grid sampled from the one-lap prediction."),
            ]
            fc_show = _show_drivers(fc)
            frows = [{"Driver": r["driver"], "Team": _abbr(r["team"]),
                      "E[finish]": f"{r['e_finish']:.1f}",
                      "P(win)": f"{r['p_win']*100:.0f}%",
                      "P(podium)": f"{r['p_podium']*100:.0f}%",
                      "P(points)": f"{r['p_points']*100:.0f}%",
                      "P(DNF)": f"{r['p_dnf']*100:.0f}%"}
                     for _, r in fc_show.iterrows()]
            from dash import dash_table
            from f1lib.components import TABLE_STYLE
            body.append(html.Div([
                html.H4("RACE RESULT FORECAST", style={
                    "color": TEXT_MAIN, "fontWeight": "800",
                    "letterSpacing": "2px", "fontSize": "1.0rem",
                    "marginTop": "8px", "marginBottom": "4px",
                    "borderBottom": f"2px solid {ACCENT}", "paddingBottom": "6px"}),
                html.P([
                    "Simulated finishing order (", html.B("20,000 races"),
                    f") from predicted race pace, the {grid_note}, and this "
                    "circuit's ", html.B("overtaking difficulty"),
                    " — measured from how much the grid order historically "
                    "survives to the flag. A base retirement rate adds spread. ",
                    html.B("Pace and track only"),
                    ": it does not model pit strategy, weather, per-team "
                    "reliability or specific incidents, so treat podium/points "
                    "odds as a pace-based prior, not a bet.",
                ], style={"color": TEXT_DIM, "fontSize": "0.78rem",
                          "lineHeight": "1.5", "marginBottom": "12px"}),
                dbc.Row(fkpis, className="mb-2"),
                dbc.Row([
                    dbc.Col(card("WIN · PODIUM · POINTS PROBABILITY",
                        dcc.Graph(figure=_forecast_fig(fc_show), config=GFX),
                        info="Per-driver probability of winning (solid), a "
                             "podium (mid) and points (faint), ordered by "
                             "expected finish. Teammates share their car's "
                             "simulated pace, so their odds move together.",
                        measure="predicted"),
                        md=7),
                    dbc.Col(card("FORECAST TABLE",
                        dash_table.DataTable(data=frows,
                            columns=[{"name": c, "id": c} for c in frows[0]],
                            **TABLE_STYLE),
                        info="Expected finishing position and win/podium/points/"
                             "DNF probabilities per driver.",
                        measure="predicted"), md=5),
                ]),
            ]))

            # The three cards above collapse each driver to a bar. These say
            # what the model actually produced (a distribution), and put it
            # against the one external reference that exists before the race.
            # Each returns None when its data is absent, which is the normal
            # case for most events — odds coverage is very uneven.
            sim = None
            try:
                sim = rf.simulate(dpred, event=event, grid=grid,
                                  quali_pred=None if grid else qpred)
            except Exception:
                sim = None
            extra = [c for c in (
                outcome.distribution_card(sim, fc_show),
                outcome.driver_picker_card(sim, fc_show),
                outcome.market_card(season, event, fc),
                outcome.movement_card(season, event),
            ) if c is not None]
            for i in range(0, len(extra), 2):
                body.append(dbc.Row([dbc.Col(c, md=6)
                                     for c in extra[i:i + 2]], className="mb-2"))

    # ── Prediction ledger (once quali / race is loaded) ─────────
    aq = _model().actual_quali_gap(laps)
    ar = _model().actual_race_gap(laps)
    ledger_cards = []
    if not aq.empty:
        # scored against the PRE-quali prediction — guaranteed outcome-blind
        p = pre_quali[pre_quali["kind"] == "onelap"].set_index("team")["mean"]
        common = [t for t in p.index if t in aq.index]
        if common:
            pv = p[common] - p[common].mean()
            av = (aq[common] - aq[common].mean())
            mae = float(np.mean(np.abs(pv.values - av.values)))
            from scipy.stats import spearmanr
            rho = spearmanr(pv.values, av.values).correlation
            ledger_cards.append(dbc.Col(card(
                f"LEDGER · ONE-LAP SPEED  (MAE {mae:.2f}% · ρ {rho:.2f})",
                dcc.Graph(figure=_ledger_fig(pre_quali, aq, "onelap", teams_sel),
                          config=GFX),
                info="Predicted vs actual qualifying gap (both to the field "
                     "mean). The prediction is the PRE-quali one — frozen at "
                     f"{_STAGE_SHORT.get(pre_quali_name, pre_quali_name)}, "
                     "before qualifying ran — so this is a genuine "
                     "before-the-fact score. MAE / ρ in the title are the "
                     "model's full-field score (the sidebar filter only zooms "
                     "the view).",
                plain=(lambda pt: _ledger_plain(pt[0], pt[1], pt[2],
                                                lambda k: _abbr(k), "the car")
                       if pt else None)(_ledger_parts(pre_quali, aq, "onelap")),
                measure="one-lap"), md=6))
    if not ar.empty:
        p = final[final["kind"] == "longrun"].set_index("team")["mean"]
        common = [t for t in p.index if t in ar.index]
        if common:
            pv = p[common] - p[common].mean()
            av = (ar[common] - ar[common].mean())
            mae = float(np.mean(np.abs(pv.values - av.values)))
            from scipy.stats import spearmanr
            rho = spearmanr(pv.values, av.values).correlation
            ledger_cards.append(dbc.Col(card(
                f"LEDGER · LONG-RUN  (MAE {mae:.2f}% · ρ {rho:.2f})",
                dcc.Graph(figure=_ledger_fig(final, ar, "longrun", teams_sel),
                          config=GFX),
                info="Predicted vs actual race pace (best driver's median "
                     "clean-air corrected lap, to the field mean). MAE / ρ are "
                     "the full-field score; the filter only zooms the view.",
                plain=(lambda pt: _ledger_plain(pt[0], pt[1], pt[2],
                                                lambda k: _abbr(k), "the car")
                       if pt else None)(_ledger_parts(final, ar, "longrun")),
                measure="race"),
                md=6))
    # Driver ONE-LAP ledger, left of the race-pace one. The per-driver
    # qualifying score is scored against the PRE-quali driver prediction, so
    # like its team twin it stays a genuine before-the-fact score.
    if not dpred_onelap.empty:
        adq = _model().actual_driver_quali_gap(laps)
        if not adq.empty:
            p = dpred_onelap.set_index("driver")["mean"]
            common = [d for d in p.index if d in adq.index]
            if len(common) >= 4:
                pv = p[common] - p[common].mean()
                av = adq[common] - adq[common].mean()
                mae = float(np.mean(np.abs(pv.values - av.values)))
                from scipy.stats import spearmanr
                rho = spearmanr(pv.values, av.values).correlation
                ledger_cards.append(dbc.Col(card(
                    f"LEDGER · DRIVER ONE-LAP SPEED  (MAE {mae:.2f}% · ρ {rho:.2f})",
                    dcc.Graph(figure=_driver_ledger_fig(dpred_onelap, adq,
                                                        drivers_show),
                              config=GFX),
                    info="Predicted vs actual per-driver qualifying speed, "
                         "against the PRE-quali prediction so it stays an "
                         "honest before-the-fact score. Actuals are session-"
                         "normalised across Q1/Q2/Q3 — a raw best-of-three "
                         "would flatter whoever reached Q3 and punish whoever "
                         "was knocked out on a green track.",
                    plain=(lambda pt: _ledger_plain(pt[0], pt[1], pt[2],
                                                   lambda k: str(k), "the driver")
                           if pt else None)(_driver_ledger_parts(dpred_onelap, adq)),
                    measure="one-lap"),
                    md=6))
    if not dpred.empty:
        adr = _model().actual_driver_race_gap(laps)
        if not adr.empty:
            p = dpred.set_index("driver")["mean"]
            common = [d for d in p.index if d in adr.index]
            if len(common) >= 4:
                pv = p[common] - p[common].mean()
                av = adr[common] - adr[common].mean()
                mae = float(np.mean(np.abs(pv.values - av.values)))
                from scipy.stats import spearmanr
                rho = spearmanr(pv.values, av.values).correlation
                ledger_cards.append(dbc.Col(card(
                    f"LEDGER · DRIVER RACE PACE  (MAE {mae:.2f}% · ρ {rho:.2f})",
                    dcc.Graph(figure=_driver_ledger_fig(dpred, adr,
                                                        drivers_show),
                              config=GFX),
                    info="Predicted vs actual per-driver race pace (each "
                         "driver's median clean-air corrected lap, to the field "
                         "mean). The finest-grained score the model keeps; MAE / "
                         "ρ are full-field, the filter only zooms the view.",
                    plain=(lambda pt: _ledger_plain(pt[0], pt[1], pt[2],
                                                   lambda k: str(k), "the driver")
                           if pt else None)(_driver_ledger_parts(dpred, adr)),
                    measure="race"),
                    md=6))
    review = _model_review_card(season, event)
    if review is not None:
        # full width: it carries two columns of its own (qualifying / race)
        ledger_cards.append(dbc.Col(review, md=12))
    if ledger_cards:
        body.append(html.Div([
            html.H4("PREDICTION LEDGER · THIS EVENT", style={
                "color": TEXT_MAIN, "fontWeight": "800", "letterSpacing": "2px",
                "fontSize": "1.0rem", "marginTop": "8px", "marginBottom": "10px",
                "borderBottom": f"2px solid {ACCENT}", "paddingBottom": "6px"}),
            dbc.Row(ledger_cards),
        ]))

    # The season-long scorecard closes the tab: the ledger above is a sample of
    # one, and this is what says how much to trust the prediction at the top.
    ev = _loaded_event()
    tr = _track_record_card(ev[0] if ev else None)
    # Retention sits directly under the scorecard on purpose: the error above
    # and the amount of evidence behind it are the same conversation, and
    # reading either alone is how a measurement limit gets mistaken for the
    # model being wrong.
    ret = _retention_card(ev[0] if ev else None)
    # The outcome half gets the same treatment as the pace half: a record over
    # many races, and a calibration curve, because a Brier score and "does a
    # stated 60% happen 60% of the time" are different questions with
    # different fixes.
    orec = outcome.record_card(ev[0] if ev else None)
    ocal = outcome.calibration_card("podium")
    outcome_row = [c for c in (orec, ocal) if c is not None]
    section = [c for c in (tr, ret) if c is not None]
    if outcome_row:
        section.append(dbc.Row([dbc.Col(c, md=6) for c in outcome_row],
                               className="mb-2"))
    if section:
        body.append(html.Div([
            html.H4("TRACK RECORD · THE WHOLE SEASON", style={
                "color": TEXT_MAIN, "fontWeight": "800", "letterSpacing": "2px",
                "fontSize": "1.0rem", "marginTop": "18px", "marginBottom": "10px",
                "borderBottom": f"2px solid {ACCENT}", "paddingBottom": "6px"}),
            *section,
        ]))

    return html.Div(body)
