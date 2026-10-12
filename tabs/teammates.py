"""TEAMMATES COMPARISON half of the TEAM & TEAMATE tab — over a window.

Input is the window slice of data/driver_event_kpis.csv. A team's pair is
its two drivers with the most events in the window (a one-off substitute
does not unseat a race driver); every comparison uses only the PAIRED
events — weekends where both drove — so one driver missing a round cannot
win or lose the duel by absence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc
import dash_bootstrap_components as dbc

from f1lib.components import (theme, card, GFX, reliability_badge,
                              hex_to_rgba as _hex_to_rgba)
from f1lib.glossary import gloss
from f1lib.config import (
    team_color, CARD_BG, TEXT_MAIN, TEXT_DIM, GRID_CLR, SERIES_1, SERIES_2,
)
from f1lib.driver_kpis import LAP_BUCKETS, load_reliability
from f1lib.standings import _order_teams_by_champ


def tab_teammates(w: pd.DataFrame, season: int):
    try:
        return _tab_teammates_inner(w, season)
    except Exception as exc:
        import traceback
        return html.Div([
            dbc.Alert([html.B("Teammate tab error: "), str(exc)],
                      color="danger", style={"fontSize": "0.82rem"}),
            html.Pre(traceback.format_exc(), style={
                "color": TEXT_DIM, "fontSize": "0.7rem", "background": "#09091A",
                "padding": "12px", "borderRadius": "6px", "overflowX": "auto"}),
        ])


# ─────────────────────────────────────────────────────────────
# Pairing + per-metric reducers (each: paired frame of ONE driver -> value)
# ─────────────────────────────────────────────────────────────

def _pairs(w: pd.DataFrame) -> dict[str, tuple[str, str, list[int]]]:
    out = {}
    for team, g in w.groupby("team"):
        cnt = g.groupby("driver")["round"].nunique().sort_values(ascending=False)
        if len(cnt) < 2:
            continue
        a, b = sorted(cnt.index[:2])
        ra = set(g.loc[g["driver"] == a, "round"])
        rb = set(g.loc[g["driver"] == b, "round"])
        paired = sorted(ra & rb)
        if paired:
            out[team] = (a, b, paired)
    return out


def _mean_both(col):
    """Mean of `col` over paired events where BOTH drivers have a value —
    so the A−B difference is the mean per-event teammate delta."""
    def f(da, db):
        m = da.set_index("round")[col].dropna()
        n = db.set_index("round")[col].dropna()
        common = m.index.intersection(n.index)
        if common.empty:
            return np.nan, np.nan, 0
        return float(m[common].mean()), float(n[common].mean()), len(common)
    return f


def _sum_each(series_fn):
    def f(da, db):
        sa, sb = series_fn(da), series_fn(db)
        if sa.notna().sum() == 0 and sb.notna().sum() == 0:
            return np.nan, np.nan, 0
        return float(sa.sum()), float(sb.sum()), int(max(sa.notna().sum(), sb.notna().sum()))
    return f


def _pit(da, db):
    def one(d):
        n = d["pit_n"].sum()
        return float(d["pit_lane_delta_sum"].sum() / n) if n else np.nan
    va, vb = one(da), one(db)
    return va, vb, int(da["pit_n"].sum() + db["pit_n"].sum())


def _h2h(col):
    """Head-to-head count: events where each driver's `col` was lower."""
    def f(da, db):
        m = da.set_index("round")[col]
        n = db.set_index("round")[col]
        common = m.dropna().index.intersection(n.dropna().index)
        if common.empty:
            return np.nan, np.nan, 0
        return (float((m[common] < n[common]).sum()),
                float((n[common] < m[common]).sum()), len(common))
    return f


def _pooled(num, den, scale=100.0):
    """sum(num) / sum(den) per driver over the paired events."""
    def f(da, db):
        def one(d):
            if num not in d.columns or den not in d.columns:
                return np.nan
            x = d.dropna(subset=[num, den])
            x = x[x[den] > 0]
            return float(x[num].sum() / x[den].sum() * scale) if len(x) else np.nan
        return one(da), one(db), int(min(len(da), len(db)))
    return f


def _col(c):
    return lambda d: d[c] if c in d.columns else pd.Series(np.nan, index=d.index)


def _purple(d):
    q, r = _col("purple_quali")(d), _col("purple_race")(d)
    return (q.fillna(0) + r.fillna(0)).where(q.notna() | r.notna())


def _gained(d):
    g = d["race_gained"].fillna(0) + d["spr_gained"].fillna(0)
    return g.where(d["race_gained"].notna() | d["spr_gained"].notna())


def _laps(d):
    return d[[f"laps_{b}" for b in LAP_BUCKETS]].sum(axis=1, min_count=1)


def _points(d):
    return d["race_points"].fillna(0) + d["spr_points"].fillna(0)


# key, label, reducer, lower_is_better, value fmt, draw tolerance, unit
_PCT = lambda v: f"{v:+.2f}%"
METRICS = [
    ("race",  "Race Pace",      _mean_both("race_gap_pct"),  True,  _PCT,                    0.05, "pp"),
    ("quali", "One-Lap Speed",  _mean_both("quali_gap_pct"), True,  _PCT,                    0.05, "pp"),
    ("best",  "Best Lap",       _mean_both("best_lap_pct"),  True,  lambda v: f"+{v:.2f}%",  0.05, "pp"),
    ("cons",  "Consistency",    _mean_both("cons_pct"),      True,  lambda v: f"{v:.2f}%",   0.02, "pp"),
    ("laps",  "Valid Laps",     _sum_each(_laps),            False, lambda v: f"{v:.0f}",    0,    "laps"),
    ("pit",   "Pit Stop",       _pit,                        True,  lambda v: f"{v:+.2f}s",  0.05, "s"),
    ("qh2h",  "Quali H2H",      _h2h("quali_pos"),           False, lambda v: f"{v:.0f}",    0,    ""),
    ("rh2h",  "Race H2H",       _h2h("race_pos"),            False, lambda v: f"{v:.0f}",    0,    ""),
    ("gain",  "Pos. Gained",    _sum_each(_gained),          False, lambda v: f"{v:+.0f}",   0,    "pos"),
    ("pass",  "Overtakes",      _sum_each(lambda d: d["passes_made"]), False, lambda v: f"{v:.0f}", 0, ""),
    ("pts",   "Points",         _sum_each(_points),          False, lambda v: f"{v:.0f} pts", 0,   "pts"),
    ("mk",    "Mistakes /100 laps", _pooled("mk_n", "mk_laps"),  True, lambda v: f"{v:.1f}",  1.0,  "/100 laps"),
    ("delr",  "Race Track Limits", _sum_each(_col("deleted_race")),  True, lambda v: f"{v:.0f}", 0, "laps"),
    ("delq",  "Deleted Quali Laps", _sum_each(_col("deleted_quali")), True, lambda v: f"{v:.0f}", 0, "laps"),
    ("pen",   "Penalties",      _sum_each(_col("pen_n")),    True,  lambda v: f"{v:.0f}",    0,    ""),
    ("purple", "Purple Sectors", _sum_each(_purple),          False, lambda v: f"{v:.0f}",    0,    ""),
    ("fl",    "Fastest-Lap Rank", _mean_both("race_fl_rank"), True, lambda v: f"P{v:.1f}",   0.5,  "places"),
    ("l1",    "Lap-1 Gain",     _sum_each(_col("lap1_gain")), False, lambda v: f"{v:+.0f}",  0,    "pos"),
    ("dnfc",  "Car DNFs",       _sum_each(_col("dnf_car")),  True,  lambda v: f"{v:.0f}",    0,    ""),
    ("dnfd",  "Driver DNFs",    _sum_each(_col("dnf_driver")), True, lambda v: f"{v:.0f}",   0,    ""),
    # chart-only (the H2H rows above carry these in the scoreboard)
    ("mkp",   "Errors under pressure /100 laps", _pooled("mk_n_p", "mk_laps_p"), True, lambda v: f"{v:.1f}", None, "/100 laps"),
    ("bw",    "Black & White Flags", _sum_each(_col("bw_flags")), True, lambda v: f"{v:.0f}", None, "flags"),
    ("inc",   "Incidents",      _sum_each(_col("inc_n")),    True,  lambda v: f"{v:.0f}",    None, ""),
    ("qpos",  "Avg Quali Position",  _mean_both("quali_pos"), True, lambda v: f"P{v:.1f}",   None, "pos"),
    ("rpos",  "Avg Race Position",   _mean_both("race_pos"),  True, lambda v: f"P{v:.1f}",   None, "pos"),
]
_BY_KEY = {m[0]: m for m in METRICS}


def _winner(va, vb, lower_is_better, tol):
    """'a' / 'b' / 'draw' / None (missing). A gap within `tol` is a draw."""
    if np.isnan(va) or np.isnan(vb):
        return None
    if abs(va - vb) <= tol + 1e-12:
        return "draw"
    return "a" if ((va < vb) if lower_is_better else (va > vb)) else "b"


# ─────────────────────────────────────────────────────────────
# Chart
# ─────────────────────────────────────────────────────────────

def _gap_chart(rows, season, xlabel, fmt_fn, lower_is_better=True, note="",
               unit=""):
    """One bar per team: LEFT when driver A is better, RIGHT when B is."""
    rows = [r for r in rows if not (np.isnan(r["val_a"]) and np.isnan(r["val_b"]))]
    if not rows:
        return go.Figure()
    raw = [(r["val_a"] - r["val_b"]) if not (np.isnan(r["val_a"]) or np.isnan(r["val_b"]))
           else 0.0 for r in rows]
    disp = [g if lower_is_better else -g for g in raw]
    texts, hover = [], []
    for r, dg in zip(rows, disp):
        va_s = fmt_fn(r["val_a"]) if not np.isnan(r["val_a"]) else "—"
        vb_s = fmt_fn(r["val_b"]) if not np.isnan(r["val_b"]) else "—"
        gap_s = (f"{abs(r['val_a'] - r['val_b']):.2f} {unit}"
                 if not (np.isnan(r["val_a"]) or np.isnan(r["val_b"])) else "—")
        w_a = "★ " if dg < 0 else ""
        w_b = " ★" if dg > 0 else ""
        texts.append(f"{w_a}{r['drv_a']}  {va_s}  |  {vb_s}  {r['drv_b']}{w_b}")
        hover.append([r["drv_a"], va_s, r["drv_b"], vb_s, gap_s, r["n"]])
    fig = go.Figure(go.Bar(
        y=[r["team"] for r in rows], x=disp, orientation="h",
        marker=dict(color=[team_color(r["team"], season) for r in rows],
                    line=dict(color=GRID_CLR, width=0.8)),
        text=texts, textposition="auto", textfont=dict(size=10, color="#fff"),
        customdata=hover,
        hovertemplate=("<b>%{y}</b><br>%{customdata[0]}: <b>%{customdata[1]}</b><br>"
                       "%{customdata[2]}: <b>%{customdata[3]}</b><br>"
                       "Gap: %{customdata[4]} · over %{customdata[5]}<extra></extra>"),
    ))
    fig.add_vline(x=0, line=dict(color=TEXT_MAIN, width=1.5))
    theme(fig, max(220, len(rows) * 52 + 130))
    fig.update_layout(xaxis_title=xlabel, bargap=0.35, showlegend=False,
                      margin=dict(l=160, r=20, t=45, b=55))
    fig.add_annotation(text="◀ left driver better  ·  right driver better ▶",
                       xref="paper", yref="paper", x=0.5, y=1.07, xanchor="center",
                       showarrow=False, font=dict(size=9, color=TEXT_DIM))
    if note:
        fig.add_annotation(text=note, xref="paper", yref="paper", x=1.0, y=-0.16,
                           xanchor="right", showarrow=False,
                           font=dict(size=9, color=TEXT_DIM))
    fig.update_yaxes(autorange="reversed")
    return fig


# ─────────────────────────────────────────────────────────────
# Tab
# ─────────────────────────────────────────────────────────────

def _tab_teammates_inner(w: pd.DataFrame, season: int):
    pairs = _pairs(w)
    if not pairs:
        return html.P("No complete teammate pairs in this window / filter — "
                      "widen the driver or team selection.",
                      style={"color": TEXT_DIM})
    teams = _order_teams_by_champ(pairs.keys())

    # rows[key] = [{team, drv_a, drv_b, val_a, val_b, n}]
    rows: dict[str, list[dict]] = {m[0]: [] for m in METRICS}
    for team in teams:
        a, b, paired = pairs[team]
        g = w[(w["team"] == team) & w["round"].isin(paired)]
        da, db = g[g["driver"] == a], g[g["driver"] == b]
        for key, _lbl, fn, *_ in METRICS:
            va, vb, n = fn(da, db)
            rows[key].append(dict(team=team, drv_a=a, drv_b=b, val_a=va,
                                  val_b=vb, n=f"{n} " + ("stops" if key == "pit" else
                                                         "events")))

    # ── scoreboard ─────────────────────────────────────────────
    sb_keys = [m[0] for m in METRICS if m[5] is not None]
    sb_items = []
    for team in teams:
        a, b, paired = pairs[team]
        score_a = score_b = 0
        pills = []
        for key in sb_keys:
            _, label, _, lib, fmt, tol, _u = _BY_KEY[key]
            r = next(x for x in rows[key] if x["team"] == team)
            win = _winner(r["val_a"], r["val_b"], lib, tol)
            if win is None:
                continue
            score_a += win == "a"
            score_b += win == "b"
            bg = SERIES_1 if win == "a" else SERIES_2 if win == "b" else "#555"
            pills.append(html.Span(
                f"{label}: {fmt(r['val_a'])} | {fmt(r['val_b'])}"
                + ("  =" if win == "draw" else ""),
                style={"background": bg + "28", "border": f"1px solid {bg}",
                       "borderRadius": "3px", "padding": "2px 7px",
                       "fontSize": "0.68rem", "marginRight": "5px",
                       "marginBottom": "4px", "display": "inline-block",
                       "color": TEXT_MAIN}))
        clr = team_color(team, season)
        total = max(score_a + score_b, 1)
        pct_a = score_a / total * 100
        bar_el = html.Div(html.Div([
            html.Div(style={"width": f"{pct_a:.1f}%", "height": "100%",
                            "background": SERIES_1}),
            html.Div(style={"width": f"{100 - pct_a:.1f}%", "height": "100%",
                            "background": SERIES_2}),
        ], style={"display": "flex", "height": "100%", "borderRadius": "3px",
                  "overflow": "hidden"}),
            style={"height": "7px", "borderRadius": "4px", "margin": "6px 0",
                   "background": GRID_CLR})
        sb_items.append(dbc.Col(dbc.Card(dbc.CardBody([
            html.Div([html.Span("● ", style={"color": clr, "fontSize": "1.1rem"}),
                      html.Span(team, style={"fontWeight": "700", "fontSize": "0.88rem",
                                             "color": TEXT_MAIN, "letterSpacing": "0.5px"}),
                      html.Span(f"  · {len(paired)} shared event"
                                f"{'s' if len(paired) > 1 else ''}",
                                style={"color": TEXT_DIM, "fontSize": "0.72rem"})]),
            html.Div([
                html.Span(a, style={"color": SERIES_1, "fontWeight": "800", "fontSize": "1.25rem"}),
                html.Span(f"  {score_a} – {score_b}  ", style={"color": TEXT_DIM,
                          "fontSize": "0.95rem", "fontWeight": "600"}),
                html.Span(b, style={"color": SERIES_2, "fontWeight": "800", "fontSize": "1.25rem"}),
            ], style={"margin": "5px 0"}),
            bar_el,
            html.Div(pills, style={"marginTop": "8px", "lineHeight": "2.0"}),
        ]), style={"background": CARD_BG, "border": f"1px solid {_hex_to_rgba(clr, 0.27)}",
                   "borderRadius": "8px"}), md=6, lg=4, className="mb-3"))

    scoreboard = card(
        html.Span(["Head-to-Head Scoreboard",
                   html.Span(" — drivers alphabetical within each team (teal = left, "
                             "orange = right); grey pill = draw",
                             style={"color": TEXT_DIM, "fontWeight": "400",
                                    "fontSize": "0.75rem", "marginLeft": "8px"})]),
        dbc.Row(sb_items),
        info=("Data: the two teammates compared on every metric below over the "
              "weekends in the window where both drove. Each metric is one win; "
              "a gap inside the metric's draw band (0.05 pp for pace, 0.02 pp "
              "for consistency, 0.05 s for pit stops, 1 per 100 laps for "
              "mistakes, 0.5 places for fastest-lap rank, exact tie otherwise) is a "
              "draw and scores for nobody. Quali and race finishes count as "
              "head-to-head records. Why: the fairest way to rate drivers — "
              "against the one person in identical machinery, including the "
              "environment (crew, strategy) that comes with their side of the "
              "garage."),
    )

    def chart_card(key, title, xlabel, info, note="", measure=None, md=6,
                   rel=None):
        _, _lbl, _fn, lib, fmt, _tol, unit = _BY_KEY[key]
        fig = _gap_chart(rows[key], season, xlabel, fmt, lower_is_better=lib,
                         note=note, unit=unit)
        if not fig.data:
            return None
        r = load_reliability().get(rel or key, {}).get("teammate")
        title = [*(title if isinstance(title, list) else [title]),
                 *reliability_badge(r, "the gap to the teammate")]
        return dbc.Col(card(title, dcc.Graph(figure=fig, config=GFX), info=info,
                            measure=measure), md=md)

    pace_cols = [c for c in [
        chart_card("race", "Race Pace", "teammate gap (% points of lap time)",
                   ("Data: each teammate's clean-air, fuel- and evolution-"
                    "corrected median race lap as % vs the field median, "
                    "averaged over the shared GP races where both have a value. "
                    "The gap is therefore the mean per-race teammate delta. "
                    "Why: same car, same race — the cleanest race-pace duel."),
                   note="Mean of per-event values; hover shows how many events.",
                   measure="race", md=4),
        chart_card("quali", "Qualifying One-Lap Speed",
                   "teammate gap (% points of lap time)",
                   ("Data: best qualifying lap corrected for Q1→Q3 track "
                    "evolution, % vs field median, averaged over shared events. "
                    "A teammate knocked out in Q2 is measured on the same track "
                    "state as one who reached Q3. Why: one-lap speed without "
                    "the segment artefact."),
                   measure="one-lap", md=4),
        chart_card("best", "Best Lap of the Weekend",
                   "teammate gap (% points of lap time)",
                   ("Data: each teammate's fastest lap of the weekend (any "
                    "session), % gap to the weekend's fastest lap, averaged "
                    "over shared events. Uncorrected — includes track evolution "
                    "and who ran on the best track. Why: the raw ultimate lap."),
                   measure="one-lap", md=4),
    ] if c is not None]

    cons_cols = [c for c in [
        chart_card("cons", "Consistency — In-Stint Lap Spread",
                   "teammate gap (% points · negative = left more consistent)",
                   ("Data: inside each GP race stint the fuel-corrected lap is "
                    "detrended on tyre age, and the robust spread of what is "
                    "left (1.4826 × MAD) is taken as % of the stint median; "
                    "stints pooled by laps, then averaged over shared events. "
                    "Clean laps only (no SC/VSC/yellow, no in/out laps). Why: "
                    "how repeatably the driver laps once fuel, tyres and the run "
                    "plan are taken out."), md=7),
        chart_card("laps", "Total Valid Laps",
                   "teammate gap (laps · negative = left ran more)",
                   ("Data: valid laps over every session of the shared events. "
                    "Why: track time is part of the driver's environment — less "
                    "running means less preparation, often a reliability "
                    "issue on that side of the garage."), md=5),
    ] if c is not None]

    quali_cols = [c for c in [
        chart_card("qpos", "Average Qualifying Position",
                   "teammate gap (positions · negative = left qualified higher)",
                   ("Data: classified qualifying position averaged over shared "
                    "events; the scoreboard turns the same data into a "
                    "head-to-head record. Why: the duel as it set the grid."),
                   measure="result", md=12),
    ] if c is not None]

    race_cols = [c for c in [
        chart_card("pit", [*gloss("pit stop", "Pit Stop"), " vs Event Median"],
                   "teammate gap (s · negative = left's stops quicker)",
                   ("Data: each stop's pit-lane time minus that event's median "
                    "stop, averaged over each driver's stops in the shared "
                    "events (red-flag waits and repairs >15 s excluded). Why: "
                    "a crew that is consistently slower on one side of the "
                    "garage is part of that driver's race.")),
        chart_card("rpos", "Average Race Position",
                   "teammate gap (positions · negative = left finished higher)",
                   ("Data: finishing order (retirements ranked by laps "
                    "completed) averaged over shared GP races; the scoreboard "
                    "uses the head-to-head record. Why: pace only matters if "
                    "it converts into results.")),
        chart_card("l1", "Lap-1 Gain",
                   "teammate gap (places · negative = left gained more)",
                   ("Data: places gained from the grid to the end of lap 1, "
                    "summed over shared races (pit-lane starters left out).")),
        chart_card("gain", "Positions Gained / Lost",
                   "teammate gap (positions · negative = left gained more)",
                   ("Data: grid minus finish summed over race and sprint "
                    "starts where the driver took the flag — every retirement "
                    "(even one classified on distance) and disqualification is "
                    "left out, the DNF cards count them. A DNF event adds 0 "
                    "for that driver while the teammate's result still counts. "
                    "Pit-lane start = back of the grid. Why: race-day "
                    "execution independent of "
                    "where qualifying put the car.")),
        chart_card("pass", "Overtakes",
                   "teammate gap (passes · negative = left made more)",
                   ("Data: on-track passes in races and sprints — a swap in "
                    "the running order between two cars that were both under "
                    "green and neither pitting, so a place gained because a "
                    "rival pitted or retired does not count, and two passes "
                    "on one lap count as two. Why: wheel-to-wheel racecraft.")),
        chart_card("pts", "Championship Points",
                   "teammate gap (pts · negative = left scored more)",
                   ("Data: race + sprint points over the shared events. Why: "
                    "the currency the team actually cares about."), md=12),
    ] if c is not None]

    disc_cols = [c for c in [
        chart_card("mk", "Micro-Mistakes per 100 Laps",
                   "teammate gap (per 100 laps · negative = left cleaner)",
                   ("Data: micro-mistakes (a lift, a brake re-application or a "
                    "slow corner against the driver's own norm — the DUEL "
                    "tab's definition) per 100 clean laps in qualifying, "
                    "sprint and race sessions, pooled over the shared events. "
                    "Draw band ±1 per 100 laps. 2023 onwards.")),
        chart_card("mkp", "Errors Under Pressure",
                   "teammate gap (per 100 laps · negative = left cleaner)",
                   ("Data: the same mistakes counted only on race laps with a "
                    "car within striking distance behind, per 100 such laps. "
                    "Chart only — it overlaps the mistake rate, so it does not "
                    "score separately on the scoreboard.")),
        chart_card("delr", "Track-Limit Deletions — Race",
                   "teammate gap (laps · negative = left fewer)",
                   ("Data: race and sprint laps deleted by race control — "
                    "almost all track-limit strikes — over the shared events. "
                    "The third strike in a race earns a black-and-white flag, "
                    "the next one a penalty.")),
        chart_card("bw", "Black-and-White Flags",
                   "teammate gap (flags · negative = left fewer)",
                   ("Data: black-and-white (warning) flags shown to the driver "
                    "in races and sprints, from the race-control messages, any "
                    "reason — about 70% are track limits. Chart only: it is the "
                    "consequence of the race deletions, which already score. "
                    "2023 onwards.")),
        chart_card("delq", "Deleted Quali Laps",
                   "teammate gap (laps · negative = left fewer)",
                   ("Data: qualifying and sprint-qualifying laps deleted by "
                    "race control. Separate from race deletions: in quali it "
                    "costs a grid slot, not a step towards a penalty.")),
        chart_card("pen", "Penalties",
                   "teammate gap (penalties · negative = left fewer)",
                   ("Data: stewards' penalties (time penalties, drive-"
                    "throughs, stop-and-go) from the race-control register. "
                    "2023 onwards.")),
        chart_card("inc", "Incidents",
                   "teammate gap (incidents · negative = left fewer)",
                   ("Data: contact and off-track incidents race control "
                    "logged against the driver, whatever the outcome. Chart "
                    "only — penalties carry the verdict on the scoreboard."),
                   md=12),
    ] if c is not None]

    peak_cols = [c for c in [
        chart_card("purple", "Purple Sectors",
                   "teammate gap (sectors · negative = left set more)",
                   ("Data: progressive purple sectors — each time the driver "
                    "beat the session's best sector time so far — in quali-"
                    "type and race-type sessions of the shared events."),
                   measure="one-lap"),
        chart_card("fl", "Fastest Race Lap — Rank",
                   "teammate gap (places · negative = left quicker)",
                   ("Data: rank of each driver's fastest GP-race lap in the "
                    "field, averaged over shared races. Draw band ±0.5 "
                    "places."), measure="race"),
    ] if c is not None]

    rel_cols = [c for c in [
        chart_card("dnfc", "Car-Caused Retirements",
                   "teammate gap (DNFs · negative = left fewer)",
                   ("Data: retirements the DNF register classes as car "
                    "imputable (failures, team strategy calls). Not the "
                    "driver's fault — but part of their season, which is why "
                    "it scores.")),
        chart_card("dnfd", "Driver-Caused Retirements",
                   "teammate gap (DNFs · negative = left fewer)",
                   ("Data: retirements classed as driver imputable (crashes, "
                    "illness, unexplained floor damage). Collisions are a "
                    "separate family in the register and not counted here.")),
    ] if c is not None]

    sections = [scoreboard]
    if pace_cols:
        sections.append(card("Pace & Speed", dbc.Row(pace_cols),
                             info=("Teammate pace duels over the window, each a "
                                   "mean of per-event values on shared events."),
                             measure=("race", "one-lap")))
    if cons_cols:
        sections.append(card("Consistency & Volume", dbc.Row(cons_cols),
                             info="Lap repeatability and how much each teammate ran."))
    if quali_cols:
        sections.append(card([*gloss("qualifying", "Qualifying"), " Result"],
                             dbc.Row(quali_cols),
                             info="Where each teammate actually lined up."))
    if peak_cols:
        sections.append(card("Peak Speed", dbc.Row(peak_cols),
                             info="Who sets the reference times, sector by sector and lap by lap.",
                             measure=("one-lap", "race")))
    if disc_cols:
        sections.append(card("Mistakes & Discipline", dbc.Row(disc_cols),
                             info="Driving errors, track limits and the stewards' verdicts."))
    if rel_cols:
        sections.append(card("Reliability", dbc.Row(rel_cols),
                             info="Retirements on each side of the garage, by cause."))
    if race_cols:
        sections.append(card("Race / Sprint Performance", dbc.Row(race_cols),
                             info=("Race-day comparison: pit work, finishing "
                                   "positions, places gained, passes and points.")))
    return html.Div(sections)
