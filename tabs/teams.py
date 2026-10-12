"""TEAM COMPARISON half of the TEAM & TEAMATE tab — over a window of events.

Input is the slice of data/driver_event_kpis.csv for the window (one row per
round x driver, see f1lib/driver_kpis.py). Every metric is shown twice:
BEST OF 2 DRIVERS (left) and AVERAGE OF 2 DRIVERS (right), so the columns
compare teams and the difference between them is the intra-team gap.

How a team value is built, by metric family
  % gaps (pace, speed, best lap)  per event: best / mean of the team's cars,
                                  then the mean over the window's events.
  counts (laps, positions)        per driver: sum over the window. Best = the
                                  higher driver, average = team total per car.
  pit stops                       pooled: sum of stop deltas / number of stops,
                                  per driver (best) or over the team (average).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc
import dash_bootstrap_components as dbc

from f1lib.components import theme, card, GFX, reliability_badge
from f1lib.config import team_color, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR
from f1lib.driver_kpis import LAP_BUCKETS, load_reliability
from f1lib.standings import _order_teams_by_champ

LAP_BUCKET_LABEL = {"fp": "Practice", "q": "Quali / SQ", "sprint": "Sprint",
                    "race": "Race"}
LAP_BUCKET_COLOR = {"fp": "#7F8C8D", "q": "#9B59B6", "sprint": "#F39C12",
                    "race": "#1ABC9C"}


def tab_teams(w: pd.DataFrame, season: int):
    try:
        return _tab_teams_inner(w, season)
    except Exception as exc:
        import traceback
        return html.Div([
            dbc.Alert([html.B("Team Analysis – error: "), str(exc)],
                      color="danger", style={"fontSize": "0.82rem"}),
            html.Pre(traceback.format_exc(), style={
                "color": TEXT_DIM, "fontSize": "0.7rem", "background": "#09091A",
                "padding": "12px", "borderRadius": "6px", "overflowX": "auto"}),
        ])


# ─────────────────────────────────────────────────────────────
# Window aggregation
# ─────────────────────────────────────────────────────────────

def _pct_metric(w, col, lower_is_better=True):
    """(best, avg, n_events) per team for a per-event % gap column."""
    d = w.dropna(subset=[col])
    if d.empty:
        return {}, {}, {}
    g = d.groupby(["round", "team"])[col]
    per_ev = pd.DataFrame({"best": g.min() if lower_is_better else g.max(),
                           "avg": g.mean()}).reset_index()
    agg = per_ev.groupby("team").agg(best=("best", "mean"), avg=("avg", "mean"),
                                     n=("round", "nunique"))
    return agg["best"].to_dict(), agg["avg"].to_dict(), agg["n"].to_dict()


def _cars_per_team(w):
    """Mean cars per event — 2 normally; the 'per car' divisor for averages."""
    ent = w.groupby("team").size()
    ev = w.groupby("team")["round"].nunique()
    return (ent / ev).to_dict()


def _count_metric(w, col_or_series, higher_is_better=True):
    s = (w[col_or_series] if isinstance(col_or_series, str) else col_or_series)
    d = w.assign(_v=s).dropna(subset=["_v"])
    if d.empty:
        return {}, {}
    per_drv = d.groupby(["team", "driver"])["_v"].sum()
    best = (per_drv.groupby("team").max() if higher_is_better
            else per_drv.groupby("team").min())
    cars = _cars_per_team(w)
    avg = {t: float(v) / max(cars.get(t, 1.0), 1.0)
           for t, v in d.groupby("team")["_v"].sum().items()}
    return best.to_dict(), avg


def _pit_metric(w):
    d = w[w["pit_n"] > 0]
    if d.empty:
        return {}, {}, {}
    per_drv = d.groupby(["team", "driver"]).agg(s=("pit_lane_delta_sum", "sum"),
                                                n=("pit_n", "sum"))
    per_drv["v"] = per_drv["s"] / per_drv["n"]
    best = per_drv.groupby("team")["v"].min().to_dict()
    team = d.groupby("team").agg(s=("pit_lane_delta_sum", "sum"),
                                 n=("pit_n", "sum"), slow=("pit_slow_n", "sum"),
                                 st=("pit_stat_sum", "sum"),
                                 stn=("pit_stat_n", "sum"))
    avg = (team["s"] / team["n"]).to_dict()
    extra = {t: dict(n=int(r.n), slow=int(r.slow),
                     stat=(r.st / r.stn if r.stn else np.nan))
             for t, r in team.iterrows()}
    return best, avg, extra


def _pooled_metric(w, num, den, scale=1.0, lower_is_better=True):
    """Rate = sum(num) / sum(den): per driver (best) and over the team (avg)."""
    d = w.dropna(subset=[num, den])
    d = d[d[den] > 0]
    if d.empty:
        return {}, {}
    per = d.groupby(["team", "driver"])[[num, den]].sum()
    v = per[num] / per[den] * scale
    best = (v.groupby("team").min() if lower_is_better
            else v.groupby("team").max()).to_dict()
    t = d.groupby("team")[[num, den]].sum()
    return best, (t[num] / t[den] * scale).to_dict()


DNF_FAMILIES = (("dnf_car", "Car", "#E74C3C"), ("dnf_driver", "Driver", "#F1C40F"),
                ("dnf_collision", "Collision", "#E67E22"), ("dnf_dsq", "DSQ", "#95A5A6"),
                ("dnf_unknown", "Not yet classified", "#555555"))


def _dnf_bar(w, teams_order, per_car):
    if "dnf_car" not in w.columns or w["dnf_car"].isna().all():
        return go.Figure()
    cars = _cars_per_team(w)
    fig = go.Figure()
    for col, label, clr in DNF_FAMILIES:
        if col not in w.columns:
            continue
        s = w.groupby("team")[col].sum()
        if per_car:
            s = s / pd.Series(cars).reindex(s.index).clip(lower=1)
        if s.sum() == 0:
            continue
        fig.add_trace(go.Bar(
            y=list(teams_order), x=[s.get(t, 0) for t in teams_order],
            name=label, orientation="h", marker_color=clr,
            hovertemplate=("<b>%{y}</b> – " + label + ": %{x:."
                           + ("1" if per_car else "0") + "f}<extra></extra>")))
    if not fig.data:
        # every car finished every race in the window — say so, not blank
        fig.add_annotation(text="No retirements in this window", showarrow=False,
                           xref="paper", yref="paper", x=0.5, y=0.5,
                           font=dict(color=TEXT_DIM, size=12))
        fig.add_trace(go.Bar(x=[0], y=[teams_order[0]], orientation="h",
                             marker_color="rgba(0,0,0,0)", hoverinfo="skip",
                             showlegend=False))
    theme(fig, max(220, len(teams_order) * 34 + 110))
    fig.update_layout(barmode="stack", showlegend=True,
                      xaxis_title="retirements" + (" per car" if per_car else ""),
                      margin=dict(l=140, r=40, t=50, b=40),
                      legend=dict(orientation="h", x=0, y=1.12, bgcolor="rgba(0,0,0,0)"))
    fig.update_yaxes(autorange="reversed", categoryorder="array",
                     categoryarray=list(teams_order))
    return fig


def _decomp_metric(w, season):
    """Team actual − expected points over the window (weekend_decomp.csv),
    keyed to the window's team spelling (the decomp uses lineage names)."""
    from f1lib.pace_features import canon
    try:
        d = pd.read_csv("data/weekend_decomp.csv")
    except Exception:
        return {}, {}
    d = d[(d["season"] == season) & d["round"].isin(w["round"].unique())]
    if d.empty:
        return {}, {}
    name = {canon(t): t for t in w["team"].unique()}
    d = d.assign(team=d["team"].map(lambda t: name.get(canon(t))))
    d = d.dropna(subset=["team"])
    parts = ["d_quali", "d_start", "d_pit", "d_sc", "d_incidents", "d_ontrack"]
    g = d.groupby("team")[["actual_points", "exp_points", *parts]].sum()
    delta = (g["actual_points"] - g["exp_points"]).to_dict()
    lbl = {"d_quali": "quali", "d_start": "start", "d_pit": "pit", "d_sc": "SC",
           "d_incidents": "incidents", "d_ontrack": "on track"}
    hover = {t: (f"<br>{r.actual_points:.0f} scored vs {r.exp_points:.1f} expected<br>"
                 + " · ".join(f"{lbl[c]} {r[c]:+.1f}" for c in parts))
             for t, r in g.iterrows()}
    return delta, hover


# ─────────────────────────────────────────────────────────────
# Charts
# ─────────────────────────────────────────────────────────────

def _hbar(data_d, season, fmt_fn, lower_is_better=True, mode="pp",
          xlabel="", hover_extra=None):
    """Horizontal bars, leader on top.
    mode 'pp'  : values are already % gaps -> x = gap to leader in % points
    mode 'pct' : raw values -> x = % gap to leader (counts: laps)
    mode 'raw' : x = the value itself (signed quantities)"""
    items = [(t, v) for t, v in data_d.items() if pd.notna(v) and np.isfinite(v)]
    if not items:
        return go.Figure()
    items.sort(key=lambda x: x[1], reverse=not lower_is_better)
    leader = items[0][1]
    if mode == "pp":
        xs = [abs(v - leader) for _, v in items]
        text = [fmt_fn(v) if i == 0 else f"{fmt_fn(v)}  +{x:.2f} pp"
                for i, ((_, v), x) in enumerate(zip(items, xs))]
        xtitle = "gap to best team (% points of lap time · 0 = best)"
    elif mode == "pct" and abs(leader) > 1e-9:
        xs = [abs(leader - v) / abs(leader) * 100 for _, v in items]
        text = [fmt_fn(v) if i == 0 else f"{fmt_fn(v)}  −{x:.1f}%"
                for i, ((_, v), x) in enumerate(zip(items, xs))]
        xtitle = "% short of the leader (0 = most)"
    else:
        xs = [v for _, v in items]
        text = [fmt_fn(v) for _, v in items]
        xtitle = xlabel
    ts = [t for t, _ in items]
    hover = [hover_extra.get(t, "") if hover_extra else "" for t in ts]
    fig = go.Figure(go.Bar(
        x=xs, y=ts, orientation="h",
        marker_color=[team_color(t, season) for t in ts],
        text=text, textposition="outside",
        textfont=dict(size=9, color=TEXT_MAIN),
        customdata=hover,
        hovertemplate="<b>%{y}</b>: %{text}%{customdata}<extra></extra>",
    ))
    theme(fig, max(200, len(items) * 40 + 90))
    fig.update_layout(xaxis_title=xtitle, showlegend=False,
                      margin=dict(l=140, r=150, t=30, b=40))
    # headroom so the outside labels ("value  +gap") never clip at the edge
    lo, hi = min(min(xs), 0.0), max(max(xs), 0.0)
    span = (hi - lo) or 1.0
    fig.update_xaxes(range=[lo - (0.45 * span if lo < 0 else 0), hi + 0.45 * span])
    if mode == "raw":
        fig.add_vline(x=0, line=dict(color=GRID_CLR, width=1))
    fig.update_yaxes(autorange="reversed")
    return fig


def _laps_bucket_bar(per_bucket, teams_order):
    """Grouped bars: valid laps per session type, raw counts."""
    fig = go.Figure()
    for b in LAP_BUCKETS:
        d = per_bucket.get(b) or {}
        ys = [t for t in teams_order if pd.notna(d.get(t, np.nan)) and d.get(t, 0) > 0]
        if not ys:
            continue
        fig.add_trace(go.Bar(
            y=ys, x=[d[t] for t in ys], name=LAP_BUCKET_LABEL[b], orientation="h",
            marker_color=LAP_BUCKET_COLOR[b],
            text=[f"{d[t]:.0f}" for t in ys], textposition="outside",
            textfont=dict(size=8, color=TEXT_MAIN),
            hovertemplate=f"<b>%{{y}}</b> – {LAP_BUCKET_LABEL[b]}: %{{x:.1f}} laps<extra></extra>",
        ))
    theme(fig, max(240, len(teams_order) * 56 + 130))
    fig.update_layout(barmode="group", showlegend=True, xaxis_title="valid laps",
                      margin=dict(l=140, r=60, t=50, b=40),
                      legend=dict(orientation="h", x=0, y=1.12, bgcolor="rgba(0,0,0,0)"))
    fig.update_yaxes(autorange="reversed", categoryorder="array",
                     categoryarray=list(teams_order))
    return fig


def _col_header(title, subtitle):
    return html.Div([
        html.H5(title, style={"color": ACCENT, "fontWeight": "800",
                              "letterSpacing": "2px", "marginBottom": "2px",
                              "fontSize": "0.92rem", "textAlign": "center"}),
        html.P(subtitle, style={"color": TEXT_DIM, "fontSize": "0.70rem",
                                "textAlign": "center", "marginBottom": "14px"}),
        html.Hr(style={"borderColor": GRID_CLR, "marginBottom": "12px"}),
    ])


def _maybe_card(title, fig, info=None, measure=None, rel=None):
    """`rel` = KPI key in the reliability JSON: badges the title with how
    repeatable a DRIVER's own value is (the reading this half makes)."""
    if fig is not None and fig.data:
        if rel:
            r = load_reliability().get(rel, {}).get("driver")
            title = [title, *reliability_badge(r, "a driver's own value")]
        return [card(title, dcc.Graph(figure=fig, config=GFX), info=info,
                     measure=measure)]
    return []


def _fmt_pct(v):
    return f"{v:+.2f}%"


def _n_note(n_d, team_order):
    """' · n events' hover suffix when a team's value rests on fewer events."""
    if not n_d:
        return {}
    full = max(n_d.values())
    return {t: (f"<br>{n_d[t]} of {full} events" if n_d.get(t, full) < full else "")
            for t in team_order}


# ─────────────────────────────────────────────────────────────
# Tab
# ─────────────────────────────────────────────────────────────

def _tab_teams_inner(w: pd.DataFrame, season: int):
    teams_all = _order_teams_by_champ(sorted(w["team"].dropna().unique()))
    if not teams_all:
        return html.P("No teams in this window.", style={"color": TEXT_DIM})

    rp_b, rp_a, rp_n = _pct_metric(w, "race_gap_pct")
    qs_b, qs_a, qs_n = _pct_metric(w, "quali_gap_pct")
    bl_b, bl_a, bl_n = _pct_metric(w, "best_lap_pct")

    lap_cols = [f"laps_{b}" for b in LAP_BUCKETS]
    laps_tot = w[lap_cols].sum(axis=1, min_count=1)
    lt_b, lt_a = _count_metric(w, laps_tot)
    per_bucket_b, per_bucket_a = {}, {}
    for b in LAP_BUCKETS:
        per_bucket_b[b], per_bucket_a[b] = _count_metric(w, f"laps_{b}")

    pit_b, pit_a, pit_x = _pit_metric(w)
    pit_hover = {t: (f"<br>{x['n']} stops · {x['slow']} slow (>1 s over median)"
                     + (f" · stationary {x['stat']:.2f} s" if pd.notna(x['stat']) else ""))
                 for t, x in pit_x.items()}

    gained = w["race_gained"].fillna(0) + w["spr_gained"].fillna(0)
    gained = gained.where(w["race_gained"].notna() | w["spr_gained"].notna())
    pg_b, pg_a = _count_metric(w, gained)

    def _col(c):
        return w[c] if c in w.columns else pd.Series(np.nan, index=w.index)

    mk_b, mk_a = _pooled_metric(w, "mk_n", "mk_laps", scale=100)
    delr_b, delr_a = _count_metric(w, _col("deleted_race"), higher_is_better=False)
    delq_b, delq_a = _count_metric(w, _col("deleted_quali"), higher_is_better=False)
    bw_team = w.groupby("team")["bw_flags"].sum(min_count=1) if "bw_flags" in w.columns \
        else pd.Series(dtype=float)
    bw_hover = {t: f"<br>{v:.0f} black-and-white flag{'s' if v != 1 else ''} (team)"
                for t, v in bw_team.dropna().items()}
    pen_b, pen_a = _count_metric(w, _col("pen_n"), higher_is_better=False)
    purple = _col("purple_quali").fillna(0) + _col("purple_race").fillna(0)
    purple = purple.where(_col("purple_quali").notna() | _col("purple_race").notna())
    pu_b, pu_a = _count_metric(w, purple)
    fl_b, fl_a, fl_n = _pct_metric(w, "race_fl_rank")
    l1_b, l1_a = _count_metric(w, _col("lap1_gain"))
    xp_d, xp_hover = _decomp_metric(w, season)
    cars = _cars_per_team(w)
    xp_avg = {t: v / max(cars.get(t, 1.0), 1.0) for t, v in xp_d.items()}

    n_ev = w["round"].nunique()
    ev_txt = f"{n_ev} event{'s' if n_ev > 1 else ''}"

    INFO = {
        "race": ("Data: each driver's median clean-air race lap, fuel- and "
                 "track-evolution-corrected, as % vs that race's field median "
                 "(GP races; under 10 clean laps = no value). Per event the "
                 "team takes its better car (left) or the mean of both "
                 "(right); the window value is the mean over events. Why: "
                 "sustained race-day pace, comparable across circuits."),
        "quali": ("Data: each driver's best qualifying lap, corrected for "
                  "Q1→Q3 track evolution, as % vs the field median — so a Q2 "
                  "exit and a Q3 runner are measured on the same track state. "
                  "Mean over the window's events. Why: low-fuel single-lap "
                  "speed of car + driver."),
        "best": ("Data: the fastest lap each driver set at any point of the "
                 "weekend (practice, quali, sprint or race; deleted and pit "
                 "laps excluded), as % gap to the weekend's fastest lap. Mean "
                 "over events. Why: the raw, uncorrected ultimate lap."),
        "laps": ("Data: valid laps over every session of the window. Left = "
                 "the busier driver's total, right = team total per car. Why: "
                 "track time is part of a driver's environment — fewer laps "
                 "means less preparation, and often a reliability problem."),
        "lapsb": ("Data: the same valid laps split by session type (practice, "
                  "qualifying + sprint qualifying, sprint, race). Why: shows "
                  "WHERE track time was lost — a short practice programme "
                  "versus a race cut short."),
        "pit": ("Data: every pit stop's pit-lane time minus that event's "
                "median stop (so circuits with long pit lanes compare), "
                "averaged over the window's stops. Red-flag pit-lane waits and "
                "repairs (>15 s off the median) are excluded; a botched wheel "
                "change stays in. Left = the driver with the quicker average, "
                "right = all the team's stops. Hover shows slow stops and the "
                "stationary time where the feed has it. Why: the crew is part "
                "of a driver's race — a consistently slow side of the garage "
                "costs real places."),
        "gain": ("Data: grid minus finish, summed over race and sprint starts "
                 "in the window, only races where the driver took the flag — "
                 "every retirement (even one classified on distance) and "
                 "disqualification is left out, the DNF cards count them; a "
                 "pit-lane start counts from the back. "
                 "Left = the better driver, right = team total per car. Why: "
                 "race-day execution — starts, strategy, racecraft."),
    }

    INFO.update({
        "mk": ("Data: micro-mistakes (a lift, a re-application of the brake or "
               "a slow corner against the driver's own norm — the DUEL tab's "
               "definition) per 100 clean laps, in qualifying, sprint and race "
               "sessions; pooled over the window (all mistakes ÷ all laps). "
               "Left = the cleaner driver, right = both cars. 2023 onwards."),
        "delr": ("Data: race and sprint laps deleted by race control — "
                 "almost all track-limit strikes. The third earns a black-"
                 "and-white flag, the next a penalty; hover shows the team's "
                 "black-and-white flags (2023 onwards). Left = the driver with "
                 "fewer, right = per car, so a garage with one serial "
                 "offender shows on the RIGHT, not the left."),
        "delq": ("Data: qualifying and sprint-qualifying laps deleted by race "
                 "control. Kept apart from race deletions: in quali it is a "
                 "lap pushed past the limit and costs a grid slot, not a step "
                 "towards a penalty. Left = fewer, right = per car."),
        "pen": ("Data: penalties handed to the team's drivers by the stewards "
                "(time penalties, drive-throughs, stop-and-go) — from the race "
                "control register. Left = fewer, right = per car. 2023 onwards."),
        "purple": ("Data: progressive purple sectors — each time a driver beat "
                   "the session's best sector time SO FAR, as the timing "
                   "screen paints it (the session's first time in a sector is "
                   "not counted), in quali-type and race-type sessions. Left = "
                   "the busier driver, right = per car. Why: who is setting "
                   "the reference, sector by sector."),
        "fl": ("Data: rank of each driver's fastest GP-race lap in the field "
               "(1 = fastest lap of the race), per event best / mean of the "
               "two cars, averaged over the window. Why: race peak speed, "
               "without the fuel and traffic noise of a median."),
        "l1": ("Data: places gained from the grid to the end of lap 1 (pit-"
               "lane starters left out), summed over the window's races. "
               "Left = the better starter, right = per car."),
        "dnf": ("Data: race retirements by cause family from the DNF "
                "register (car imputable, driver imputable, collision, "
                "disqualified; 'not yet classified' = waiting for review). "
                "Left = team total, right = per car. Why: reliability is part "
                "of the environment a driver races in. 2023 onwards."),
        "xp": ("Data: points actually scored minus points EXPECTED from the "
               "team's pace that weekend (RACE tab 'Where the Points Went'), "
               "summed over the window. Hover shows where the difference "
               "came from: quali, start, pit, safety car, incidents, on-track. "
               "Left = team total, right = per car. Positive = scored more "
               "than the car's pace was worth. 2023 onwards."),
    })

    def build(col_title, col_sub, which):
        b = which == "best"
        pick = (lambda bd, ad: bd if b else ad)
        out = [_col_header(col_title, col_sub)]
        out += _maybe_card(
            f"Race Pace ({ev_txt})",
            _hbar(pick(rp_b, rp_a), season, _fmt_pct,
                  hover_extra=_n_note(rp_n, teams_all)),
            info=INFO["race"], rel="race", measure="race")
        out += _maybe_card(
            f"Qualifying One-Lap Speed ({ev_txt})",
            _hbar(pick(qs_b, qs_a), season, _fmt_pct,
                  hover_extra=_n_note(qs_n, teams_all)),
            info=INFO["quali"], rel="quali", measure="one-lap")
        out += _maybe_card(
            f"Best Lap of the Weekend ({ev_txt})",
            _hbar(pick(bl_b, bl_a), season, lambda v: f"+{v:.2f}%",
                  hover_extra=_n_note(bl_n, teams_all)),
            info=INFO["best"], rel="best", measure="one-lap")
        out += _maybe_card(
            "Total Valid Laps" if b else "Valid Laps per Car",
            _hbar(pick(lt_b, lt_a), season,
                  (lambda v: f"{v:.0f}") if b else (lambda v: f"{v:.1f}"),
                  lower_is_better=False, mode="pct"),
            info=INFO["laps"], rel="laps")
        out += _maybe_card(
            "Laps per Session Type" + ("" if b else " (per car)"),
            _laps_bucket_bar(per_bucket_b if b else per_bucket_a, teams_all),
            info=INFO["lapsb"])
        out += _maybe_card(
            "Pit Stop vs Event Median",
            _hbar(pick(pit_b, pit_a), season, lambda v: f"{v:+.2f} s",
                  mode="raw", xlabel="pit-lane time vs event median (s · lower = quicker)",
                  hover_extra=pit_hover),
            info=INFO["pit"], rel="pit")
        out += _maybe_card(
            "Lap-1 Gain" + ("" if b else " (per car)"),
            _hbar(pick(l1_b, l1_a), season,
                  (lambda v: f"{v:+.0f}") if b else (lambda v: f"{v:+.1f}"),
                  lower_is_better=False, mode="raw",
                  xlabel="places gained on lap 1"),
            info=INFO["l1"], rel="l1")
        out += _maybe_card(
            "Points vs Expected" + ("" if b else " (per car)"),
            _hbar(xp_d if b else xp_avg, season, lambda v: f"{v:+.1f}",
                  lower_is_better=False, mode="raw",
                  xlabel="actual − expected points", hover_extra=xp_hover),
            info=INFO["xp"])
        out += _maybe_card(
            "Micro-Mistakes per 100 Laps",
            _hbar(pick(mk_b, mk_a), season, lambda v: f"{v:.1f}", mode="raw",
                  xlabel="mistakes per 100 clean laps (lower = cleaner)"),
            info=INFO["mk"], rel="mk")
        out += _maybe_card(
            "Track-Limit Deletions — Race" + ("" if b else " (per car)"),
            _hbar(pick(delr_b, delr_a), season,
                  (lambda v: f"{v:.0f}") if b else (lambda v: f"{v:.1f}"),
                  mode="raw", xlabel="deleted race / sprint laps (lower = better)",
                  hover_extra=bw_hover),
            info=INFO["delr"], rel="delr")
        out += _maybe_card(
            "Deleted Quali Laps" + ("" if b else " (per car)"),
            _hbar(pick(delq_b, delq_a), season,
                  (lambda v: f"{v:.0f}") if b else (lambda v: f"{v:.1f}"),
                  mode="raw", xlabel="deleted quali laps (lower = better)"),
            info=INFO["delq"], rel="delq")
        out += _maybe_card(
            "Penalties" + ("" if b else " (per car)"),
            _hbar(pick(pen_b, pen_a), season,
                  (lambda v: f"{v:.0f}") if b else (lambda v: f"{v:.1f}"),
                  mode="raw", xlabel="penalties (lower = better)"),
            info=INFO["pen"], rel="pen")
        out += _maybe_card(
            "Retirements by Cause" + ("" if b else " (per car)"),
            _dnf_bar(w, teams_all, per_car=not b), info=INFO["dnf"])
        out += _maybe_card(
            "Purple Sectors" + ("" if b else " (per car)"),
            _hbar(pick(pu_b, pu_a), season,
                  (lambda v: f"{v:.0f}") if b else (lambda v: f"{v:.1f}"),
                  lower_is_better=False, mode="pct"),
            info=INFO["purple"], rel="purple", measure="one-lap")
        out += _maybe_card(
            "Fastest Race Lap — Rank",
            _hbar(pick(fl_b, fl_a), season, lambda v: f"P{v:.1f}", mode="raw",
                  xlabel="mean rank of the fastest race lap (1 = fastest)",
                  hover_extra=_n_note(fl_n, teams_all)),
            info=INFO["fl"], rel="fl", measure="race")
        out += _maybe_card(
            "Positions Gained / Lost" + ("" if b else " (per car)"),
            _hbar(pick(pg_b, pg_a), season,
                  (lambda v: f"{v:+.0f}") if b else (lambda v: f"{v:+.1f}"),
                  lower_is_better=False, mode="raw",
                  xlabel="positions gained (+) / lost (−)"),
            info=INFO["gain"], rel="gain")
        return out

    left = build("BEST OF 2 DRIVERS", "each metric uses the stronger driver per team",
                 "best")
    right = build("AVERAGE OF 2 DRIVERS",
                  "both cars — a missing driver falls back to the other, never to 0",
                  "avg")
    return html.Div([
        html.Hr(style={"borderColor": GRID_CLR, "margin": "8px 0 16px 0"}),
        dbc.Row([
            dbc.Col(html.Div(left), md=6,
                    style={"borderRight": f"2px solid {GRID_CLR}", "paddingRight": "14px"}),
            dbc.Col(html.Div(right), md=6, style={"paddingLeft": "14px"}),
        ], className="g-0"),
    ])
