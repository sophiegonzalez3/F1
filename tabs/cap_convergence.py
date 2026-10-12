"""CONTEXT tab card "Did the Cap Level the Field?" — sits under the budget-cap
compliance ledger.

Answers the media claim that the cost cap hasn't let small teams catch up
because the big four (McLaren, Mercedes, Red Bull, Ferrari) now take a larger
points share (The Race, Oct 2026: 77.4% in 2011-20 → 83.5% in 2021-25). Three
stacked panels over 2011→now, cap era shaded:

  1. points share — the season's REAL top four vs the fixed big four. The
     fixed definition is hindsight: the pre-cap gap between the lines is the
     McLaren-2015-18 / Williams / Lotus / Force India effect.
  2. one-lap spread (session-normalised, f1lib/quali_norm) — the convergence
     itself.
  3. retirement rate, big four vs the rest — the reliability channel that
     hands the midfield its opportunistic points.

Data: data/cap_convergence.csv + _meta.json from
scripts/compute_cap_convergence.py (after_race chain). Every axis passed the
split-half bar (≥0.6) and the scores are printed on the card.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import html, dcc
import dash_bootstrap_components as dbc

from f1lib.components import card, theme, GFX, kpi
from f1lib.config import (ACCENT, TEXT_DIM, TEXT_MAIN, NEUTRAL, NEUTRAL_ALT,
                          SERIES_1, SERIES_2, STATUS_OK, CURRENT_SEASON)

_CSV = Path("data/cap_convergence.csv")
_META = Path("data/cap_convergence_meta.json")
_CACHE: dict = {"mtime": None, "df": pd.DataFrame(), "meta": {}}
CAP_START = 2021


def _load() -> tuple[pd.DataFrame, dict]:
    try:
        mtime = (_CSV.stat().st_mtime, _META.stat().st_mtime)
    except OSError:
        return pd.DataFrame(), {}
    if mtime != _CACHE["mtime"]:
        try:
            _CACHE["df"] = pd.read_csv(_CSV)
            _CACHE["meta"] = json.loads(_META.read_text())
        except Exception as _exc:
            print(f"Cap convergence         : failed to read ({_exc})")
            _CACHE["df"], _CACHE["meta"] = pd.DataFrame(), {}
        _CACHE["mtime"] = mtime
    return _CACHE["df"], _CACHE["meta"]


def _era(df: pd.DataFrame, col: str, lo: int, hi: int) -> float:
    return float(df.loc[df["season"].between(lo, hi), col].mean())


def _figure(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07,
        subplot_titles=("Points share of the top four teams",
                        "One-lap gap to the fastest team (quali, normalised)",
                        "Retirement rate"))
    x = df["season"]
    live = df["season"] == CURRENT_SEASON
    # season in progress → hollow marker
    sym = ["circle-open" if v else "circle" for v in live]

    def line(row, col, name, color, dash=None, fmt="%{y:.1f}%", extra=""):
        fig.add_trace(go.Scatter(
            x=x, y=df[col], name=name, mode="lines+markers",
            line=dict(color=color, width=2.4, dash=dash),
            marker=dict(size=7, symbol=sym, color=color),
            customdata=df[["top4_teams", "rounds"]],
            legendgroup=str(row),
            hovertemplate=f"<b>%{{x}}</b> · {name}<br>{fmt}{extra}<extra></extra>"),
            row=row, col=1)

    line(1, "top4_share", "That season's real top four", ACCENT,
         extra="<br>top four: %{customdata[0]}")
    line(1, "big4_share", "Fixed big four (The Race)", NEUTRAL, dash="dash")
    line(2, "spread_pct", "Fastest → slowest team", SERIES_1, fmt="%{y:.2f}%")
    line(2, "mid_gap_pct", "Typical non-big-four team", SERIES_2,
         fmt="%{y:.2f}%")
    line(3, "big4_dnf_pct", "Big-four cars", ACCENT)
    line(3, "other_dnf_pct", "Rest of the field", NEUTRAL_ALT, dash="dot")

    last = int(df["season"].max())
    fig.add_vrect(x0=CAP_START - 0.5, x1=last + 0.5, fillcolor=ACCENT,
                  opacity=0.07, line_width=0, row="all", col=1)
    fig.add_annotation(x=CAP_START - 0.4, y=1.0, xref="x", yref="paper",
                       text="cost cap →", showarrow=False, xanchor="left",
                       yanchor="bottom", font=dict(size=10, color=ACCENT))
    theme(fig, 820)
    fig.update_yaxes(ticksuffix="%")
    fig.update_yaxes(range=[60, 95], row=1, col=1)
    fig.update_yaxes(rangemode="tozero", row=2, col=1)
    fig.update_yaxes(rangemode="tozero", row=3, col=1)
    fig.update_xaxes(range=[int(df["season"].min()) - 0.5, last + 0.5])
    fig.update_xaxes(dtick=1, tickangle=-45, row=3, col=1)
    for a in fig.layout.annotations[:3]:
        a.update(font=dict(size=11, color=TEXT_DIM), x=0, xanchor="left")
    fig.update_layout(margin=dict(l=50, r=20, t=50, b=120),
                      legend=dict(orientation="h", y=-0.09, yanchor="top", x=0,
                                  font=dict(size=10)),
                      hovermode="x unified")
    return fig


def cap_convergence_card() -> dbc.Card | None:
    df, meta = _load()
    if df.empty or not meta:
        return None
    df = df.sort_values("season")
    last = int(df["season"].max())
    cap_hi = min(CAP_START + 4, last)
    pre, cap = (2011, CAP_START - 1), (CAP_START, cap_hi)
    big4 = (_era(df, "big4_share", *pre), _era(df, "big4_share", *cap))
    top4 = (_era(df, "top4_share", *pre), _era(df, "top4_share", *cap))
    spread = (_era(df, "spread_pct", *pre), _era(df, "spread_pct", *cap))
    dnf = (_era(df, "big4_dnf_pct", *pre), _era(df, "big4_dnf_pct", *cap))
    sh = meta.get("split_half", {})
    era_txt = f"{pre[0]}-{str(pre[1])[2:]} → {cap[0]}-{str(cap[1])[2:]}"

    kpis = dbc.Row([
        kpi("FIXED BIG FOUR SHARE %", f"{big4[0]:.1f}→{big4[1]:.1f}", NEUTRAL,
            tooltip=f"{era_txt}. The Race's measure: McLaren + Mercedes + Red "
                    "Bull + Ferrari, in every season. Reproduced to within "
                    "~1pp of their graphic."),
        kpi("REAL TOP FOUR SHARE %", f"{top4[0]:.1f}→{top4[1]:.1f}", ACCENT,
            tooltip=f"{era_txt}. The four best constructors of EACH season. "
                    "Almost flat: most of the big-four rise is the fixed "
                    "definition counting McLaren 2015-18 instead of Williams, "
                    "Lotus or Force India."),
        kpi("ONE-LAP SPREAD %", f"{spread[0]:.1f}→{spread[1]:.1f}", SERIES_1,
            tooltip=f"{era_txt}. Median gap fastest → slowest team in "
                    "qualifying, session-normalised. The field more than "
                    f"halved. Split-half reliability {sh.get('spread_pct')}."),
        kpi("BIG-FOUR DNF RATE %", f"{dnf[0]:.1f}→{dnf[1]:.1f}", STATUS_OK,
            tooltip=f"{era_txt}. Share of big-four starts ending in "
                    "retirement. Fewer big-team failures = fewer free points "
                    f"for the midfield. Split-half {sh.get('big4_dnf_pct')}."),
    ])

    by_out = meta.get("mid_share_by_big4_out", {}).get("cap_2021_25", {})
    intro = html.P([
        "The Race found the big four now take more of the points than before "
        "the cap. That holds — but ", html.Strong("points share is a ranking "
        "measure, not a gap measure"), ": if the top eight cars finish in the "
        "same order 0.1s or 30s apart, the points are identical. Below it next "
        "to what actually changed: the one-lap spread ",
        html.Strong("more than halved"), ", while the real top four's share "
        f"barely moved ({top4[0]:.1f}% → {top4[1]:.1f}%)."],
        style={"color": TEXT_DIM, "fontSize": "0.78rem", "marginBottom": "10px"})

    reliab = html.P([
        html.Strong("Reliability is the midfield's real loss. ", style={"color": TEXT_MAIN}),
        "In the cap era a race with no big-four retirement gives the rest of "
        f"the field {by_out.get('0', '–')}% of the race points; one retirement "
        f"{by_out.get('1', '–')}%, two or more {by_out.get('2', '–')}%. Big-four "
        f"cars retired {meta['big4_out_per_race']['pre_cap']} times per race "
        f"before the cap and {meta['big4_out_per_race']['cap_2021_25']} after. "
        "At pre-cap reliability the midfield's 2021-25 share would have been "
        f"{meta['cap_mid_share_pre_cap_reliability']}% instead of "
        f"{meta['cap_mid_share_actual']}%."],
        style={"color": TEXT_DIM, "fontSize": "0.76rem", "marginTop": "6px"})

    return card(
        "Did the Cap Level the Field?",
        html.Div([intro, kpis, dcc.Graph(figure=_figure(df), config=GFX),
                  reliab]),
        measure=("one-lap", "result"),
        info=("Data: data/cap_convergence.csv (scripts/compute_cap_convergence"
              ".py) — 2011-18 from Jolpica, 2019+ from the results archive; "
              "race + sprint points as scored (fastest-lap point included). "
              "One-lap gap = each team's best qualifying lap with Q1/Q2/Q3 "
              "track evolution removed (f1lib/quali_norm), median over the "
              "season. Retirement = not classified as Finished / lapped. "
              f"{last} is in progress (hollow markers) and a new-regulation "
              "year, which always reopens the gaps. Split-half reliability "
              "(odd vs even rounds): " + ", ".join(
                  f"{k.replace('_pct', '').replace('_', ' ')} {v}"
                  for k, v in sh.items()) + "."),
        plain=("Since the cost cap the cars are much closer in raw speed, but "
               "the same four teams still finish at the front, and their cars "
               "break down less often — so the smaller teams get fewer "
               "lucky points when a big team's car retires."),
    )
