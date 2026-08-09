"""OUTCOME MODEL cards for the BRIEF tab — the second half of the prediction.

`race_forecast.py` turns predicted race pace + the grid + a circuit's
overtaking difficulty into p_win / p_podium / p_points / e_finish / p_dnf.
Until now the tab rendered those five numbers and nothing about them: no
distribution, no track record, no calibration, and no comparison against the
one external reference that exists.

Five cards, in the order they answer a reader's questions:

  distribution   what the model ACTUALLY said (a spread, not a position)
  market         where it disagrees with the money, this weekend
  movement       what the market learned as the weekend ran
  record         has it been right, over 161 races
  calibration    does a stated 60% happen 60% of the time

WHY THE MARKET IS HERE AND NOT IN THE MODEL
-------------------------------------------
Betting prices are a well-calibrated probability reference available BEFORE
the race, which makes them the honest benchmark for an outcome model — and
disagreement with them is the most informative signal available about where
the outcome layer is wrong. They are rendered ALONGSIDE the forecast and never
fed into it: a model that consumed the market could no longer be scored
against it. `tests/test_odds.py` pins that structurally.

TWO FILTERS ARE MANDATORY ON EVERY ODDS READ
--------------------------------------------
`pre_lock` — Kalshi's close_time is SETTLEMENT, hours after the flag, so a
"last price" that ignores this is taken with the race half-run.
`overround` in 0.9-1.25 — a settled or half-empty book still quotes prices
(bid 0.00 / ask 1.00 has a plausible-looking 0.50 midpoint), and on the
Polymarket rows an untraded 12-hour candle reads as a flat 0.50.
`_usable_odds` applies both; nothing here reads the CSV directly.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html, callback, Input, Output, State
import dash_bootstrap_components as dbc

from f1lib.components import theme, card, GFX
from f1lib.config import TEAM_COLORS, TEXT_DIM, TEXT_MAIN, GRID_CLR, ACCENT

ODDS = Path("data/odds_snapshots.csv")
RECORD = Path("data/backtest_race_forecast.csv")
DETAIL = Path("data/backtest_race_forecast_detail.csv")

MODEL_CLR = "#3DD6C4"
MARKET_CLR = "#FF8A3D"
# Below this many priced drivers a market card is noise, not a thin signal:
# coverage is very uneven (Hungary 2026 has 155 podium snapshots, Miami has 1).
MIN_DRIVERS = 6
MIN_SNAPSHOTS = 8


def _clr(team: str) -> str:
    return TEAM_COLORS.get(team, "#808080")


def _read(path: Path, **kw) -> pd.DataFrame:
    try:
        return pd.read_csv(path, **kw)
    except Exception:
        return pd.DataFrame()


def _usable_odds(season: int, event: str, market: str) -> pd.DataFrame:
    """Every pre-race, sane-book price for one event and market.

    The two filters are not optional — see the module docstring. Returning an
    empty frame is the correct answer for most events; the cards render a
    stated "no usable prices" rather than a misleading sparse chart.
    """
    o = _read(ODDS, low_memory=False)
    if o.empty:
        return o
    need = {"season", "event", "market", "pre_lock", "overround",
            "p_devig_power", "driver", "hours_to_lock"}
    if not need.issubset(o.columns):
        return pd.DataFrame()
    return o[(o["season"] == season) & (o["event"] == event)
             & (o["market"] == market) & (o["pre_lock"] == True)
             & o["overround"].between(0.9, 1.25)
             & o["p_devig_power"].notna()
             & o["driver"].notna() & (o["driver"] != "FIELD")]


def _empty(msg: str):
    return html.Div(msg, style={"color": TEXT_DIM, "fontSize": "0.82rem",
                                "padding": "18px 4px", "lineHeight": "1.6"})


# ─────────────────────────────────────────────────────────────
# 1. Finishing-position distribution
# ─────────────────────────────────────────────────────────────

def distribution_card(sim: dict | None, fc: pd.DataFrame, top: int = 10):
    """Driver x finishing position, as a heatmap of simulation share.

    The tab's other forecast chart collapses each driver to three numbers.
    This is what those numbers are made of, and it shows the two things a
    summary hides: how WIDE a driver's plausible range is, and the retirement
    mass that piles up at the back.
    """
    if not sim or fc is None or fc.empty:
        return None
    drivers, finish = sim.get("drivers"), sim.get("finish")
    if drivers is None or finish is None:
        return None
    order = [d for d in fc.sort_values("e_finish")["driver"] if d in drivers][:top]
    if len(order) < 4:
        return None
    n = finish.shape[1]
    cols = list(range(1, min(n, 20) + 1))
    z, labels = [], []
    for d in order:
        col = finish[:, drivers.index(d)]
        z.append([float((col == p).mean()) for p in cols])
        labels.append(d)
    za = np.asarray(z)
    # CAP THE SCALE, do not stretch it to the maximum. A driver's row sums to
    # 1 over ~20 positions, so two thirds of the cells sit under 0.05 while a
    # single dominant cell can reach 0.35 — scaling to that maximum pushes the
    # entire body of the data into the bottom seventh of the ramp and the grid
    # reads as uniformly empty. Capping at the 95th percentile spends the ramp
    # where the values actually are; the few cells above it saturate, which
    # costs nothing because "very likely" is already the other two cards' job.
    cap = float(np.percentile(za[za > 0], 95)) if (za > 0).any() else 1.0
    cap = max(cap, 1.5 / len(cols))       # never tighter than ~1.5x uniform
    # Single-hue ramp starting at the card background, so an empty cell reads
    # as empty on a dark theme rather than glowing.
    scale = [[0.0, "rgba(61,214,196,0.03)"], [0.2, "rgba(61,214,196,0.22)"],
             [0.5, "rgba(61,214,196,0.55)"], [0.8, "rgba(61,214,196,0.85)"],
             [1.0, MODEL_CLR]]
    fig = go.Figure(go.Heatmap(
        z=z, x=[f"P{c}" for c in cols], y=labels, colorscale=scale,
        zmin=0, zmax=cap, showscale=False, xgap=1, ygap=1,
        hovertemplate="%{y} finishes %{x} in %{z:.1%} of races<extra></extra>"))
    theme(fig, max(300, len(order) * 26 + 120), "")
    fig.update_layout(margin=dict(l=54, r=20, t=30, b=44),
                      xaxis_title=f"finishing position  ·  brighter = more "
                                  f"likely, scale capped at {cap:.0%}")
    fig.update_yaxes(autorange="reversed")
    return card("FINISHING POSITION · FULL DISTRIBUTION",
                dcc.Graph(figure=fig, config=GFX),
                info="Share of the 20,000 simulated races in which each driver "
                     "finishes in each position. A wide band means the model "
                     "genuinely cannot separate outcomes; the weight at the "
                     "far right is retirements, which are classified behind "
                     "the finishers. The colour scale is capped at the 95th "
                     "percentile of the cells so the mid-range stays legible — "
                     "a few cells above the cap show at full brightness.",
                plain="The model never picks one position — it spreads itself "
                      "over the whole field. The wider a driver's row, the "
                      "less it is claiming.",
                measure="predicted")


# ─────────────────────────────────────────────────────────────
# 1b. One or two drivers, as bars
# ─────────────────────────────────────────────────────────────
#
# The heatmap answers "who is spread out"; it is poor at "what exactly does
# the model say about HIM". Same data, picked rather than scanned — the bar
# form used in the tab's own walkthrough, where it reads well.

DIST_STORE = "outcome-dist-store"
DIST_PICK = "outcome-dist-pick"
DIST_FIG = "outcome-dist-fig"
_BAR_CLRS = [MODEL_CLR, MARKET_CLR]


def _dist_payload(sim: dict | None, fc: pd.DataFrame, cap: int = 20) -> dict:
    if not sim or fc is None or fc.empty:
        return {}
    drivers, finish = sim.get("drivers"), sim.get("finish")
    if drivers is None or finish is None:
        return {}
    n = min(finish.shape[1], cap)
    out = {}
    for d in fc.sort_values("e_finish")["driver"]:
        if d not in drivers:
            continue
        col = finish[:, drivers.index(d)]
        out[d] = [round(float((col == p).mean()), 4) for p in range(1, n + 1)]
    return out


def driver_picker_card(sim: dict | None, fc: pd.DataFrame):
    """Dropdown + bar chart for one or two drivers, fed from a Store.

    The simulation is not re-run on selection: the distributions are computed
    once and parked in a dcc.Store, so switching driver is a redraw rather
    than 20,000 fresh races.
    """
    payload = _dist_payload(sim, fc)
    if len(payload) < 2:
        return None
    names = list(payload)
    default = names[:2]
    return card("COMPARE DRIVERS · FINISHING ODDS",
                html.Div([
                    dcc.Store(id=DIST_STORE, data=payload),
                    dcc.Dropdown(id=DIST_PICK, options=[{"label": d, "value": d}
                                                        for d in names],
                                 value=default, multi=True, clearable=False,
                                 style={"marginBottom": "10px"}),
                    dcc.Graph(id=DIST_FIG, figure=_pick_fig(payload, default),
                              config=GFX),
                ]),
                info="The same 20,000 simulated races as the heatmap, for the "
                     "drivers you choose. Pick two to see where their ranges "
                     "overlap — overlapping bars are the model saying it "
                     "cannot separate them, however far apart their expected "
                     "positions look.",
                plain="Tall early bars mean a confident front-runner; a long "
                      "flat spread means the model is genuinely unsure.",
                measure="predicted")


def _pick_fig(payload: dict, picked) -> go.Figure:
    picked = [p for p in (picked or []) if p in payload][:2]
    fig = go.Figure()
    if not picked:
        theme(fig, 300, "")
        fig.update_layout(margin=dict(l=54, r=20, t=30, b=44),
                          annotations=[dict(text="pick a driver", showarrow=False,
                                            font=dict(color=TEXT_DIM))])
        return fig
    xs = [f"P{i+1}" for i in range(len(payload[picked[0]]))]
    for i, d in enumerate(picked):
        ys = [v * 100 for v in payload[d]]
        fig.add_trace(go.Bar(
            x=xs, y=ys, name=d, marker_color=_BAR_CLRS[i % len(_BAR_CLRS)],
            opacity=0.85 if len(picked) > 1 else 1.0,
            hovertemplate=f"{d} · %{{x}} in %{{y:.1f}}%% of races<extra></extra>"))
    theme(fig, 300, "")
    fig.update_layout(
        barmode="group" if len(picked) > 1 else "relative", bargap=0.25,
        legend=dict(orientation="h", x=0, y=1.08, bgcolor="rgba(0,0,0,0)"),
        showlegend=len(picked) > 1,
        yaxis_title="share of simulations (%)",
        xaxis_title="finishing position",
        margin=dict(l=56, r=20, t=40, b=44))
    return fig


# ─────────────────────────────────────────────────────────────
# 2. Model vs market
# ─────────────────────────────────────────────────────────────

def market_card(season: int, event: str, fc: pd.DataFrame,
                market: str = "podium"):
    """Where the model and the betting market disagree, this weekend.

    The single most informative card about the outcome layer: the market is a
    well-calibrated reference that exists before the race, so a systematic gap
    is evidence about the model — available without waiting for a result.
    """
    if fc is None or fc.empty:
        return None
    o = _usable_odds(season, event, market)
    if o.empty:
        return card(f"MODEL vs MARKET · P({market.upper()})",
                    _empty("No usable market prices for this event. Coverage "
                           "is uneven — a race is normally listed about a week "
                           "ahead, and prices from a settled or empty book are "
                           "filtered out rather than shown."),
                    info="Market-implied probabilities from Kalshi/Polymarket, "
                         "de-vigged. Never an input to the model.")
    last = o.sort_values("hours_to_lock").groupby("driver", as_index=False).head(1)
    mkt = last.groupby("driver")["p_devig_power"].mean()
    col = {"podium": "p_podium", "win": "p_win"}.get(market, "p_podium")
    d = fc.assign(mkt=fc["driver"].map(mkt)).dropna(subset=["mkt"])
    if len(d) < MIN_DRIVERS:
        return None
    d = d.sort_values(col, ascending=False).head(12)
    d["gap"] = d[col] - d["mkt"]

    fig = go.Figure()
    for _, r in d.iterrows():                       # the connector = the gap
        fig.add_trace(go.Scatter(
            x=[r[col] * 100, r["mkt"] * 100], y=[r["driver"]] * 2,
            mode="lines", line=dict(color=GRID_CLR, width=2),
            hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(
        x=d[col] * 100, y=d["driver"], mode="markers", name="model",
        marker=dict(size=11, color=MODEL_CLR,
                    line=dict(width=1, color="#000")),
        hovertemplate="%{y} · model %{x:.0f}%<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=d["mkt"] * 100, y=d["driver"], mode="markers", name="market",
        marker=dict(size=11, color=MARKET_CLR, symbol="diamond",
                    line=dict(width=1, color="#000")),
        hovertemplate="%{y} · market %{x:.0f}%<extra></extra>"))
    theme(fig, max(320, len(d) * 26 + 130), "")
    fig.update_layout(
        legend=dict(orientation="h", x=0, y=1.06, bgcolor="rgba(0,0,0,0)"),
        xaxis_title=f"P({market}) %  ·  the bar between the dots IS the disagreement",
        margin=dict(l=54, r=24, t=44, b=44))
    fig.update_yaxes(autorange="reversed")

    hrs = float(last["hours_to_lock"].min())
    big = d.reindex(d["gap"].abs().sort_values(ascending=False).index).iloc[0]
    side = "higher" if big["gap"] > 0 else "lower"
    return card(f"MODEL vs MARKET · P({market.upper()})",
                dcc.Graph(figure=fig, config=GFX),
                info=f"Model probability against the last de-vigged market "
                     f"price before lights out ({hrs:.0f} h out), from "
                     f"{last['bookmaker'].nunique()} source(s). Prices are "
                     f"filtered to a live, sane book. The market is a "
                     f"BENCHMARK — it is never fed to the model, or the model "
                     f"could not be scored against it.",
                plain=f"Biggest disagreement: {big['driver']}, where the model "
                      f"is {abs(big['gap'])*100:.0f} points {side} than the "
                      f"money. Neither side is automatically right — that is "
                      f"the point of showing both.",
                measure="predicted")


# ─────────────────────────────────────────────────────────────
# 3. Market movement
# ─────────────────────────────────────────────────────────────

def movement_card(season: int, event: str, market: str = "podium",
                  top: int = 6):
    """How the market's opinion moved as the weekend ran.

    The reason the odds feed stores a TIMESTAMP and not just a price. The
    shape is usually flat for days and then steps hard when qualifying
    resolves the grid — which is the same information the model gets, so the
    two can be compared on when they learned, not just what they concluded.
    """
    o = _usable_odds(season, event, market)
    if o.empty or o["snapshot_ts"].nunique() < MIN_SNAPSHOTS:
        return None
    last = o.sort_values("hours_to_lock").groupby("driver").head(1)
    keep = list(last.nlargest(top, "p_devig_power")["driver"])
    d = o[o["driver"].isin(keep)].copy()
    d["h"] = d["hours_to_lock"].round(0)
    g = d.groupby(["driver", "h"], as_index=False)["p_devig_power"].mean()

    fig = go.Figure()
    teams = d.drop_duplicates("driver").set_index("driver")["team"].to_dict() \
        if "team" in d.columns else {}
    for drv in keep:
        s = g[g["driver"] == drv].sort_values("h", ascending=False)
        fig.add_trace(go.Scatter(
            x=s["h"], y=s["p_devig_power"] * 100, mode="lines", name=drv,
            line=dict(width=2, color=_clr(teams.get(drv, ""))),
            hovertemplate=f"{drv} · %{{y:.0f}}%% at %{{x:.0f}} h out<extra></extra>"))
    theme(fig, 320, "")
    fig.update_layout(
        legend=dict(orientation="h", x=0, y=1.06, bgcolor="rgba(0,0,0,0)"),
        xaxis_title="hours before lights out",
        yaxis_title=f"market P({market}) %",
        margin=dict(l=56, r=24, t=44, b=44))
    fig.update_xaxes(autorange="reversed")
    span = f"{o['hours_to_lock'].max():.0f}"
    return card(f"HOW THE MARKET MOVED · P({market.upper()})",
                dcc.Graph(figure=fig, config=GFX),
                info=f"Every de-vigged market price recorded for this event, "
                     f"from {span} h before the race to lights out "
                     f"({o['snapshot_ts'].nunique()} snapshots). This is why "
                     f"the feed stores a timestamp: a price is only observable "
                     f"while the market is open and cannot be reconstructed "
                     f"afterwards.",
                plain="Prices usually drift for days and then jump when "
                      "qualifying settles the grid. A line that moves BEFORE "
                      "qualifying is the market reacting to practice — the "
                      "same evidence the model is reading.",
                measure="predicted")


# ─────────────────────────────────────────────────────────────
# 4. Track record
# ─────────────────────────────────────────────────────────────

_TARGETS = [("win", "P(win)"), ("podium", "P(podium)"), ("points", "P(points)")]


def record_card(season: int | None = None):
    """Brier skill against the grid baseline, race by race this season.

    Per EVENT rather than per season: a season average answers "should I
    trust this model" but hides the thing a reader is usually looking at,
    which is how it did at the circuit in front of them. The two diverge
    sharply — over 2026 the podium skill runs from -30% at Monaco to +26% at
    Austria — and an average that smooth is a worse guide than the spread.

    Falls back to per-season when the requested season has no event rows.
    """
    b = _read(RECORD)
    if b.empty or "scope" not in b.columns:
        return None
    allrow = b[b["scope"] == "all"]
    if allrow.empty:
        return None
    ev = b[b["scope"] == "event"].copy()
    ev["season_n"] = pd.to_numeric(ev["season"], errors="coerce")
    per, xcol, xtitle = pd.DataFrame(), "season", "season"
    if season is not None and not ev.empty:
        per = ev[ev["season_n"] == int(season)].sort_values("round")
        xcol, xtitle = "event", f"{int(season)} season, round by round"
    if per.empty:                       # no event rows: fall back to seasons
        per = b[b["scope"] == "season"].copy()
        per["season"] = pd.to_numeric(per["season"], errors="coerce")
        per = per.dropna(subset=["season"]).sort_values("season")
        xcol, xtitle = "season", "season"
    if per.empty:
        return None

    fig = go.Figure()
    for (name, label), clr in zip(_TARGETS, ("#FF8A3D", MODEL_CLR, "#9B8CFF")):
        gcol, bcol = f"brier_grid_{name}", f"brier_{name}"
        if gcol not in per.columns or bcol not in per.columns:
            continue
        # PER EVENT, PLOT THE DIFFERENCE, NOT THE SKILL RATIO. Skill divides by
        # the reference's error, and over a single race that denominator can be
        # tiny — when the grid baseline happens to nail a Sunday, p_win skill
        # reads -172% and squashes every other race off the chart. The 2026
        # per-event range is -172%..+24% on win against -73%..+36% on podium,
        # which is arithmetic, not a model that got 172% worse. The difference
        # is stable and stays in Brier units, so races are comparable.
        adv = (per[gcol] - per[bcol]) if xcol == "event" else \
              (1 - per[bcol] / per[gcol]) * 100
        xs = (per[xcol].astype(str).str.replace(" Grand Prix", "", regex=False)
              if xcol == "event" else per[xcol])
        fig.add_trace(go.Scatter(
            x=xs, y=adv, mode="lines+markers", name=label,
            line=dict(width=2, color=clr), marker=dict(size=7),
            hovertemplate=(f"{label} · %{{y:>+.4f}} Brier better than the grid "
                           f"baseline at %{{x}}<extra></extra>" if xcol == "event"
                           else f"{label} · %{{y:.1f}}%% better in %{{x}}"
                                f"<extra></extra>")))
    fig.add_hline(y=0, line_color=TEXT_DIM, line_width=1, line_dash="dot")
    theme(fig, 340, "")
    ytitle = ("Brier advantage over the grid baseline" if xcol == "event"
              else "% of the grid baseline's error removed")
    fig.update_layout(
        legend=dict(orientation="h", x=0, y=1.06, bgcolor="rgba(0,0,0,0)"),
        yaxis_title=ytitle,
        xaxis_title=f"{xtitle}  ·  above 0 = better than knowing the grid",
        margin=dict(l=68, r=24, t=44, b=76))
    if xcol == "event":
        fig.update_xaxes(tickangle=-40, tickfont=dict(size=10))

    a = allrow.iloc[0]
    kpis = []
    for name, label in _TARGETS:
        try:
            sk = (1 - float(a[f"brier_{name}"]) / float(a[f"brier_grid_{name}"])) * 100
        except Exception:
            continue
        kpis.append(html.Div([
            html.Div(label, style={"color": TEXT_DIM, "fontSize": "0.72rem",
                                   "letterSpacing": "1px"}),
            html.Div(f"{sk:+.1f}%", style={
                "color": MODEL_CLR if sk > 0 else "#FF6B6B",
                "fontSize": "1.25rem", "fontWeight": "800"}),
        ], style={"marginRight": "26px"}))
    head = html.Div(kpis, style={"display": "flex", "marginBottom": "6px"})
    scope_lbl = ("RACE BY RACE" if xcol == "event" else "BY SEASON")
    return card(f"OUTCOME TRACK RECORD · vs THE GRID BASELINE · {scope_lbl}",
                html.Div([head, dcc.Graph(figure=fig, config=GFX)]),
                info=f"The line is this season race by race; the figures above "
                     f"it are the whole record — {int(a.get('races', 0))} races "
                     f"({int(a.get('rows', 0)):,} driver-races) from "
                     f"scripts/backtest_race_forecast.py, replaying each with "
                     f"only what was known beforehand. The reference is "
                     f"P(outcome | grid slot) fitted on EARLIER races only — a "
                     f"much harder bar than the field base rate.",
                plain="Above the dotted line, the model beat simply knowing "
                      "where each car started at that race. Individual races "
                      "swing hard either way, so judge it on the figures above "
                      "the chart — and there only podium and points clear the "
                      "bar. What this model knows about WINNING, it mostly "
                      "knows from the grid.",
                measure="predicted")


# ─────────────────────────────────────────────────────────────
# 5. Calibration
# ─────────────────────────────────────────────────────────────

_BINS = [0, .02, .05, .1, .2, .35, .5, .7, .9, 1.01]


def _curve(d: pd.DataFrame, pcol: str, ycol: str) -> pd.DataFrame:
    s = d.dropna(subset=[pcol, ycol])
    if s.empty:
        return pd.DataFrame()
    s = s.assign(b=pd.cut(s[pcol], _BINS))
    g = s.groupby("b", observed=True).agg(n=(ycol, "size"),
                                          pred=(pcol, "mean"),
                                          act=(ycol, "mean")).reset_index()
    return g[g["n"] >= 10]


def calibration_card(target: str = "podium"):
    """Does a stated 60% happen 60% of the time?

    Brier cannot answer this — a model can be sharp and biased, or calibrated
    and useless, and the two want opposite fixes. The market's curve is drawn
    alongside where prices exist, which is the comparison the odds feed was
    collected for.
    """
    d = _read(DETAIL, low_memory=False)
    ycol, pcol = f"{target}_actual", f"p_{target}"
    if d.empty or ycol not in d.columns or pcol not in d.columns:
        return None
    model = _curve(d, pcol, ycol)
    if model.empty:
        return None

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[0, 90], y=[0, 90], mode="lines",
                             line=dict(color=TEXT_DIM, width=1, dash="dot"),
                             name="perfect", hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=model["pred"] * 100, y=model["act"] * 100, mode="lines+markers",
        name="model", line=dict(width=2, color=MODEL_CLR),
        marker=dict(size=9), customdata=model["n"],
        hovertemplate="said %{x:.0f}%% · happened %{y:.0f}%%"
                      "<br>%{customdata} driver-races<extra></extra>"))
    mcol = "mkt_podium" if target == "podium" else "mkt_win"
    if mcol in d.columns:
        mk = _curve(d, mcol, ycol)
        if not mk.empty:
            fig.add_trace(go.Scatter(
                x=mk["pred"] * 100, y=mk["act"] * 100, mode="lines+markers",
                name="market", line=dict(width=2, color=MARKET_CLR, dash="dash"),
                marker=dict(size=9, symbol="diamond"), customdata=mk["n"],
                hovertemplate="market said %{x:.0f}%% · happened %{y:.0f}%%"
                              "<br>%{customdata} driver-races<extra></extra>"))
    theme(fig, 340, "")
    fig.update_layout(
        legend=dict(orientation="h", x=0, y=1.06, bgcolor="rgba(0,0,0,0)"),
        xaxis_title=f"P({target}) the model stated (%)",
        yaxis_title="how often it actually happened (%)",
        margin=dict(l=62, r=24, t=44, b=46))
    worst = float((model["act"] - model["pred"]).abs().max())
    return card(f"CALIBRATION · P({target.upper()})",
                dcc.Graph(figure=fig, config=GFX),
                info="Every driver-race in the backtest, grouped by the "
                     "probability the model gave it, against how often that "
                     "group's outcome actually occurred. On the dotted line = "
                     "the stated number means what it says. Brier score alone "
                     "cannot show this.",
                plain=f"Points above the line mean the model was too cautious, "
                      f"below it too confident. Worst gap here is "
                      f"{worst*100:.0f} points. The market curve rests on far "
                      f"fewer races, so read its wobble with that in mind.",
                measure="predicted")


@callback(Output(DIST_FIG, "figure"),
          Input(DIST_PICK, "value"),
          State(DIST_STORE, "data"),
          prevent_initial_call=True)
def _redraw_pick(picked, payload):
    """Redraw from the Store. Capped at two drivers: a third makes the bars
    too thin to compare, which is the one thing this card exists to do."""
    return _pick_fig(payload or {}, picked)
