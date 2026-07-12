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

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc
import dash_bootstrap_components as dbc

import state
from components import theme, card, kpi, GFX, abbr as _abbr
from config import TEAM_COLORS, TEXT_DIM, TEXT_MAIN, GRID_CLR, ACCENT
from pace_model import PaceModel, canon
from race_forecast import RaceForecaster

_KIND_LABEL = {"onelap": "Qualifying (one-lap)", "longrun": "Race (long-run)"}
_STAGE_SHORT = {"prior": "Prior", "after FP1": "FP1", "after FP2": "FP2",
                "after FP3": "FP3", "after SprintQuali": "SQ",
                "after Sprint": "Sprint"}
# progression x-axis order (whichever stages actually exist this weekend)
_STAGE_SEQUENCE = ["prior", "after FP1", "after FP2", "after FP3",
                   "after SprintQuali", "after Sprint"]

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

def _order_fig(stage: pd.DataFrame, kind: str) -> go.Figure:
    """Predicted gap to field mean with ±1sd bars, best at top. Axes fit
    whatever teams are in `stage` (so the sidebar filter zooms the view)."""
    d = stage[stage["kind"] == kind].sort_values("mean")
    fig = go.Figure()
    if d.empty:
        theme(fig, 300, "")
        return fig
    fig.add_trace(go.Bar(
        x=d["mean"], y=[_abbr(t) for t in d["team"]], orientation="h",
        marker_color=[_clr(t) for t in d["team"]],
        error_x=dict(type="data", array=d["sd"], color=TEXT_DIM, thickness=1,
                     width=3),
        text=[f"{v:+.1f}%" for v in d["mean"]], textposition="outside",
        textfont=dict(size=9, color=TEXT_MAIN),
        customdata=np.stack([d["team"], d["sd"]], axis=-1),
        hovertemplate="%{customdata[0]}: %{x:+.2f}%  ±%{customdata[1]:.2f}"
                      "<extra></extra>"))
    theme(fig, max(300, len(d) * 34 + 120), "")
    fig.add_vline(x=0, line_color=TEXT_DIM, line_width=1)
    vmax = float(d["mean"].abs().max() or 1) + float(d["sd"].max() or 0)
    fig.update_layout(showlegend=False,
        xaxis_title="Predicted gap to field mean (%)  ·  faster ← → slower",
        margin=dict(l=64, r=80, t=16, b=44),
        xaxis_range=[d["mean"].min() - vmax * 0.5, d["mean"].max() + vmax * 0.5])
    fig.update_yaxes(autorange="reversed")
    return fig


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
    fig = go.Figure()
    for t in teams:
        xs, ys = [], []
        for st in order:
            row = stages[st][(stages[st]["team"] == t)
                             & (stages[st]["kind"] == kind)]
            if not row.empty:
                xs.append(_STAGE_SHORT[st])
                ys.append(row["mean"].iloc[0])
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers", name=_abbr(t),
            line=dict(color=_clr(t), width=2), marker=dict(size=7),
            hovertemplate=f"{_abbr(t)} · %{{x}}<br>%{{y:+.2f}}%<extra></extra>"))
    theme(fig, 440, "")
    fig.update_layout(
        yaxis_title="Predicted gap to field mean (%)",
        legend=dict(orientation="h", x=0, y=1.12, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=60, r=20, t=40, b=30))
    fig.update_yaxes(autorange="reversed")
    return fig


def _driver_order_fig(dpred: pd.DataFrame) -> go.Figure:
    """Per-driver predicted race pace, teammates adjacent, ±1sd bars."""
    d = dpred.sort_values("mean")
    fig = go.Figure()
    if d.empty:
        theme(fig, 360, "")
        return fig
    labels = [f"{r['driver']}" for _, r in d.iterrows()]
    fig.add_trace(go.Bar(
        x=d["mean"], y=labels, orientation="h",
        marker_color=[_clr(t) for t in d["team"]],
        error_x=dict(type="data", array=d["sd"], color=TEXT_DIM, thickness=1,
                     width=3),
        text=[f"{v:+.1f}%" for v in d["mean"]], textposition="outside",
        textfont=dict(size=9, color=TEXT_MAIN),
        customdata=np.stack([d["team"], d["effect"], d["sd"]], axis=-1),
        hovertemplate="%{y} (%{customdata[0]})<br>%{x:+.2f}%  ±%{customdata[2]:.2f}"
                      "  ·  driver effect %{customdata[1]:+.2f}%<extra></extra>"))
    theme(fig, max(360, len(d) * 22 + 120), "")
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


def _scatter_ledger(pv: pd.Series, av: pd.Series, colors: dict,
                    show: set | None, x_title: str, y_title: str,
                    label_size: int) -> go.Figure:
    """Shared predicted-vs-actual scatter. pv/av are centered on the FULL
    field (so positions are truthful); `show` filters which points are drawn
    and the axes zoom to them."""
    keys = list(pv.index)
    if show is not None:
        keys = [k for k in keys if k in show] or keys
    fig = go.Figure()
    if keys:
        pvv = pv[keys]
        avv = av[keys]
        lo = float(min(pvv.min(), avv.min())) - 0.3
        hi = float(max(pvv.max(), avv.max())) + 0.3
        fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines",
            line=dict(color=TEXT_DIM, dash="dash"), showlegend=False,
            hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=pvv.values, y=avv.values, mode="markers+text",
            text=[colors[k][2] for k in keys], textposition="top center",
            textfont=dict(size=label_size, color=TEXT_MAIN),
            marker=dict(size=12, color=[colors[k][1] for k in keys],
                        line=dict(width=1, color="#000")),
            customdata=[colors[k][2] for k in keys],
            hovertemplate="%{customdata}<br>pred %{x:+.2f}%  ·  actual %{y:+.2f}%"
                          "<extra></extra>"))
    theme(fig, 440, "")
    fig.update_layout(showlegend=False, xaxis_title=x_title,
        yaxis_title=y_title, margin=dict(l=60, r=20, t=16, b=44))
    return fig


def _ledger_fig(pred: pd.DataFrame, actual: pd.Series, kind: str,
                show: set | None = None) -> go.Figure:
    """Predicted vs actual team gap, parity line, zoomed to `show` teams."""
    p = pred[pred["kind"] == kind].set_index("team")["mean"]
    common = [t for t in p.index if t in actual.index]
    if not common:
        return _scatter_ledger(pd.Series(dtype=float), pd.Series(dtype=float),
                               {}, None, "", "", 9)
    pv = (p[common] - p[common].mean())
    av = (actual[common] - actual[common].mean())
    # colors[key] = (team, colour, label) — team used for the show-filter
    colors = {t: (t, _clr(t), _abbr(t)) for t in common}
    return _scatter_ledger(pv, av, colors, show,
                           "Predicted gap to field mean (%)",
                           "Actual gap to field mean (%)", 9)


def _driver_ledger_fig(dpred: pd.DataFrame, actual: pd.Series,
                       show: set | None = None) -> go.Figure:
    """Predicted vs actual per-driver race pace, zoomed to `show` drivers."""
    p = dpred.set_index("driver")["mean"]
    teams = dpred.set_index("driver")["team"]
    common = [d for d in p.index if d in actual.index]
    if not common:
        return _scatter_ledger(pd.Series(dtype=float), pd.Series(dtype=float),
                               {}, None, "", "", 8)
    pv = (p[common] - p[common].mean())
    av = (actual[common] - actual[common].mean())
    colors = {d: (d, _clr(teams[d]), d) for d in common}
    return _scatter_ledger(pv, av, colors, show,
                           "Predicted race-pace gap (%)",
                           "Actual race-pace gap (%)", 8)


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

    try:
        stages = _model().predict_weekend(season, event)
    except ValueError:
        return html.Div(dbc.Alert(
            [f"No season pace table entry for {season} {event}. Generate it "
             "with ", html.Code("python compute_team_pace.py"),
             f" --season {season}."], color="warning"))

    stage_names = list(stages)
    final_name = stage_names[-1]
    final = stages[final_name]
    has_practice = final_name != "prior"

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
    probs = _model().outcome_probs(final, "onelap")
    kpis = []
    if not probs.empty:
        top = probs.iloc[0]
        kpis.append(kpi("PREDICTED QUALI PACE", f"{_abbr(top['team'])}",
            tooltip="Team with the fastest predicted one-lap pace at the "
                    "current stage of the weekend."))
        kpis.append(kpi("P(POLE-PACE TEAM)", f"{top['p_best']*100:.0f}%",
            color="#FFD700",
            tooltip="Monte-Carlo probability this team has the field's fastest "
                    "one-lap pace, given the model's uncertainty and event-day "
                    "execution noise. Team-level, not driver-level."))
    # biggest mover since previous stage
    if len(stage_names) >= 2:
        prev = stages[stage_names[-2]].set_index(["team", "kind"])["mean"]
        cur = final.set_index(["team", "kind"])["mean"]
        d = (cur - prev).dropna()
        d = d[[i for i in d.index if i[1] == "onelap"]]
        if not d.empty:
            mover = d.abs().idxmax()
            delta = d[mover]
            kpis.append(kpi(f"BIGGEST MOVE · {_STAGE_SHORT.get(final_name, final_name)}",
                f"{_abbr(mover[0])} {delta:+.2f}%",
                color=ACCENT,
                tooltip=f"Largest change in predicted one-lap gap from "
                        f"{_STAGE_SHORT.get(stage_names[-2], stage_names[-2])} "
                        f"to {_STAGE_SHORT.get(final_name, final_name)}. "
                        "Negative = gained pace."))
    stage_pill_txt = ("Pre-weekend prior" if not has_practice
                      else f"Updated through {_STAGE_SHORT.get(final_name, final_name)}")
    kpis.append(kpi("WEEKEND STAGE", stage_pill_txt,
        color=ACCENT if has_practice else TEXT_MAIN,
        tooltip="How far into the weekend the prediction reflects. Each "
                "practice session with clean pace data sharpens it."))
    body = [intro, dbc.Row(kpis, className="mb-2")]

    # ── Predicted order (one-lap + long-run) ────────────────────
    final_show = _show_teams(final)
    body.append(dbc.Row([
        dbc.Col(card(f"PREDICTED ORDER · {_KIND_LABEL['onelap'].upper()}",
            dcc.Graph(figure=_order_fig(final_show, "onelap"), config=GFX),
            info="Predicted qualifying pace as a gap to the field mean at the "
                 "current stage. Whiskers are ±1sd. Team pace = the team's "
                 "faster driver."), md=6),
        dbc.Col(card(f"PREDICTED ORDER · {_KIND_LABEL['longrun'].upper()}",
            dcc.Graph(figure=_order_fig(final_show, "longrun"), config=GFX),
            info="Predicted race pace as a gap to the field mean. Long-run "
                 "practice is a weak, fuel/mode-polluted signal, so this "
                 "leans on season race form more than the one-lap chart — "
                 "treat its ordering as indicative."), md=6),
    ]))

    # ── Progression across the weekend ──────────────────────────
    if has_practice:
        body.append(dbc.Row([dbc.Col(card("PREDICTION PROGRESSION · ONE-LAP",
            dcc.Graph(figure=_progression_fig(stages, "onelap", teams_sel),
                      config=GFX),
            info="Each team's predicted one-lap gap at every stage, prior → "
                 "FP3 (plus Sprint sessions on a sprint weekend). Lines "
                 "converging and reordering show what each session taught the "
                 "model. Y-axis inverted: up = faster."), md=12)]))

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
        from components import TABLE_STYLE
        body.append(card("QUALIFYING PACE PROBABILITIES",
            dash_table.DataTable(data=rows,
                columns=[{"name": c, "id": c} for c in rows[0]], **TABLE_STYLE),
            info="Monte-Carlo probability each team has the fastest / a top-3 "
                 "one-lap pace, from the predicted gaps, their uncertainty and "
                 "an event-day execution-noise term. Team pace, not driver — "
                 "it does not model qualifying mistakes or grid penalties."))

    # ── Driver race-pace outlook (team latent × driver rating) ──
    roster = (state.laps.dropna(subset=["Driver_Short", "Team"])
              [["Driver_Short", "Team"]].drop_duplicates()
              .rename(columns={"Driver_Short": "driver", "Team": "team"})
              if state.laps is not None else pd.DataFrame())
    round_ = _model().round_of(season, event)
    dpred = _model().driver_predictions(final, roster, "longrun",
                                        as_of=(season, round_) if round_ else None)
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
        from components import TABLE_STYLE
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
                         "Bar colour = team; teammates share the car so their "
                         "difference is the driver rating. Whiskers ±1sd combine "
                         "car and driver-rating uncertainty."), md=6),
                dbc.Col(card("RACE-PACE PROBABILITIES (per driver)",
                    dash_table.DataTable(data=drows,
                        columns=[{"name": c, "id": c} for c in drows[0]],
                        **TABLE_STYLE),
                    info="Monte-Carlo P(fastest race pace) and P(top-3 race "
                         "pace) per driver. Teammates share their car's draw "
                         "(a strong car lifts both), so their odds move "
                         "together. Pace only — not race-day strategy, "
                         "reliability or incidents."), md=6),
            ]),
        ]))

    # ── Race result forecast (pace × grid × overtaking difficulty) ──
    rf = _forecaster()
    if not dpred.empty and rf is not None:
        qpred = _model().driver_predictions(
            final, roster, "onelap", as_of=(season, round_) if round_ else None)
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
            from components import TABLE_STYLE
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
                             "simulated pace, so their odds move together."),
                        md=7),
                    dbc.Col(card("FORECAST TABLE",
                        dash_table.DataTable(data=frows,
                            columns=[{"name": c, "id": c} for c in frows[0]],
                            **TABLE_STYLE),
                        info="Expected finishing position and win/podium/points/"
                             "DNF probabilities per driver."), md=5),
                ]),
            ]))

    # ── Prediction ledger (once quali / race is loaded) ─────────
    laps = state.laps
    aq = _model().actual_quali_gap(laps)
    ar = _model().actual_race_gap(laps)
    ledger_cards = []
    if not aq.empty:
        p = final[final["kind"] == "onelap"].set_index("team")["mean"]
        common = [t for t in p.index if t in aq.index]
        if common:
            pv = p[common] - p[common].mean()
            av = (aq[common] - aq[common].mean())
            mae = float(np.mean(np.abs(pv.values - av.values)))
            from scipy.stats import spearmanr
            rho = spearmanr(pv.values, av.values).correlation
            ledger_cards.append(dbc.Col(card(
                f"LEDGER · ONE-LAP  (MAE {mae:.2f}% · ρ {rho:.2f})",
                dcc.Graph(figure=_ledger_fig(final, aq, "onelap", teams_sel),
                          config=GFX),
                info="Predicted vs actual qualifying gap (both to the field "
                     "mean). Points on the dashed line were predicted exactly; "
                     "MAE / ρ in the title are the model's full-field score "
                     "(the sidebar filter only zooms the view). This is the "
                     "model keeping score on itself."), md=6))
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
                     "the full-field score; the filter only zooms the view."),
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
                         "ρ are full-field, the filter only zooms the view."),
                    md=6))
    if ledger_cards:
        body.append(html.Div([
            html.H4("PREDICTION LEDGER", style={
                "color": TEXT_MAIN, "fontWeight": "800", "letterSpacing": "2px",
                "fontSize": "1.0rem", "marginTop": "8px", "marginBottom": "10px",
                "borderBottom": f"2px solid {ACCENT}", "paddingBottom": "6px"}),
            dbc.Row(ledger_cards),
        ]))

    return html.Div(body)
