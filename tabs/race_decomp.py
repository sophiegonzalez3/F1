"""RACE tab card: where the points went (weekend decomposition).

Renders data/weekend_decomp.csv (built by scripts/compute_weekend_decomp.py,
mechanics in f1lib/weekend_decomp.py) for one Grand Prix: each team's actual
points minus the pace model's pre-race expectation, split into quali, start,
pit crew, SC timing, incidents and the on-track remainder.

One figure, all teams: a diverging stacked bar per team (components sum to the
team's total surprise) with the total marked. Colour identifies the COMPONENT
— fixed assignment, validated for colour-vision deficiency against the card
surface — never the team; the team is the row label.
"""
from __future__ import annotations

import pandas as pd
from dash import dcc, html
import plotly.graph_objects as go

from f1lib.components import card, theme, GFX
from f1lib.config import CARD_BG, TEXT_MAIN, TEXT_DIM
from f1lib.weekend_decomp import decomp_df

# Fixed component order (chronological through the weekend) and colours —
# palette validated (CVD + contrast) against CARD_BG; the 2px surface gap
# between segments is the secondary encoding that backs it up.
_PARTS = [
    ("d_quali",     "Quali",     "#3987e5"),
    ("d_start",     "Start",     "#d95926"),
    ("d_pit",       "Pit crew",  "#199e70"),
    ("d_sc",        "SC timing", "#c98500"),
    ("d_incidents", "Incidents", "#d55181"),
    ("d_ontrack",   "On-track",  "#9085e9"),
]

_HOVER_EXTRA = {
    "d_pit": "pit crew: %{customdata[1]:>+.1f} s vs field-median stops",
    "d_sc": "stop timing: %{customdata[1]:>+.1f} s saved vs field",
    "d_incidents": "%{customdata[1]}",
}


def _fig(d: pd.DataFrame) -> go.Figure:
    d = d.copy()
    d["total"] = d["actual_points"] - d["exp_points"]
    d = d.sort_values("total")            # biggest overachiever on top
    teams = d["team"].tolist()

    fig = go.Figure()
    for col, label, clr in _PARTS:
        if col == "d_pit":
            extra = d["pit_delta_s"]
        elif col == "d_sc":
            extra = d["sc_saved_s"]
        elif col == "d_incidents":
            extra = d["retirements"].fillna("").replace("", "no retirement")
        else:
            extra = d["team"]             # unused slot, keeps customdata square
        hover = (f"<b>%{{y}}</b> · {label} %{{x:>+.1f}} pts"
                 + ("<br>" + _HOVER_EXTRA[col] if col in _HOVER_EXTRA else "")
                 + "<extra></extra>")
        fig.add_trace(go.Bar(
            y=teams, x=d[col], name=label, orientation="h",
            marker=dict(color=clr, line=dict(color=CARD_BG, width=2)),
            customdata=list(zip(d["team"], extra)),
            hovertemplate=hover,
        ))
    fig.add_trace(go.Scatter(
        y=teams, x=d["total"], mode="markers+text", name="Total",
        marker=dict(symbol="diamond", size=10, color=TEXT_MAIN,
                    line=dict(color=CARD_BG, width=1)),
        text=[f"{v:+.0f}" for v in d["total"]],
        textposition=["middle right" if v >= 0 else "middle left"
                      for v in d["total"]],
        textfont=dict(size=11, color=TEXT_MAIN),
        customdata=list(zip(d["exp_points"], d["actual_points"])),
        hovertemplate=("<b>%{y}</b> · total %{x:>+.1f} pts"
                       "<br>expected %{customdata[0]:.1f} → "
                       "scored %{customdata[1]:.0f}<extra></extra>"),
    ))
    fig.add_vline(x=0, line_color=TEXT_DIM, line_width=1)
    fig.update_layout(
        barmode="relative", bargap=0.35, height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis_title="points vs pre-race expectation",
    )
    theme(fig)
    return fig


def weekend_decomp_card(season, meeting) -> object:
    d = decomp_df()
    d = d[(d["season"] == int(season)) & (d["event"] == meeting)]
    if d.empty:
        body = html.P(
            ["No decomposition for this race yet — build it with ",
             html.Code("python scripts/compute_weekend_decomp.py "
                       f"--season {season}"),
             " (it needs the cached race laps and the season pace table)."],
            style={"color": TEXT_DIM, "fontSize": "0.85rem"})
    else:
        body = dcc.Graph(figure=_fig(d), config=GFX)
    return card(
        "Where the Points Went", body,
        info=("Data: each team's actual GP points minus the pace model's "
              "pre-race expectation (its post-practice posterior simulated "
              "through qualifying and the race), split by swapping in one "
              "fact at a time, in weekend order: the real grid (QUALI), the "
              "real lap-1 positions (START), then measured race pieces — "
              "summed stationary-time delta vs the field's median stop (PIT "
              "CREW, penalties and repairs excluded), seconds saved by "
              "stopping under SC/VSC vs the field (SC TIMING), and each "
              "retirement priced at that driver's own no-retirement "
              "simulations (INCIDENTS, cause from race control when known). "
              "ON-TRACK is the exact remainder: race pace, strategy calls, "
              "traffic — everything not measured above. Why: every other "
              "card shows one mechanism; this one adds them up, so 'they "
              "scored 8 fewer than the car was worth' becomes 'quali cost 3, "
              "a slow stop cost 2, the rest was pace'. Caveats: an "
              "accounting decomposition against a MODEL expectation, not a "
              "causal proof — terms depend on the stated order; pit and SC "
              "seconds are priced by the race's median inter-car gap and the "
              "points-table slope at the team's finishing spot (a "
              "backmarker's slow stop is correctly worth ~0 pts); sprint "
              "points are out of scope."),
        measure=["predicted", "result"])
