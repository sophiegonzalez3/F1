"""Session OVERVIEW cards — rendered at the top of the TELEMETRY tab
(lap-time distribution, driver performance matrix, cornering speed).
Extracted from app.py."""
from __future__ import annotations

import plotly.graph_objects as go
from dash import html, dcc

import f1lib.state as state
from f1lib.components import theme, card, GFX
from f1lib.config import TEAM_COLORS, TEXT_MAIN
from tabs.corner_speed import corner_speed_section

# mirror the mutable data state (SESSIONS, DRIVERS, telemetry, …) so the
# moved bodies keep their bare-name reads — repopulated on every reload
state.register(globals())
from f1lib.figures import tmgaps
from f1lib.standings import (
    _driver_standings_after_round, _loaded_meeting_season_round,
)


def tab_overview(fl, fs, ft=None):
    v = fl[fl["ValidLap"]]

    # Drop FP1 test/rookie drivers (the mandatory young-driver FP1 outings, two
    # per car per season): a real race driver is in the season's driver
    # standings, a one-off tester never is — so their laps would only add noise
    # to the pace charts. Empty standings (pre-season) → keep everyone.
    _season, _, _ = _loaded_meeting_season_round()
    _ds = _driver_standings_after_round(_season, None)
    _real = set(_ds)
    if _real:
        v = v[v["Driver_Short"].isin(_real)]

    # Drivers left→right in championship order (points leader first).
    drv_order = sorted(
        v["Driver_Short"].dropna().unique(),
        key=lambda d: (-_ds.get(d, {}).get("pts", -1.0), d))

    fig_vio = go.Figure()
    for drv in drv_order:
        sub  = v[v["Driver_Short"]==drv]["LapTime_s"]
        team = fl[fl["Driver_Short"]==drv]["Team"].iloc[0]
        clr  = TEAM_COLORS.get(team,"#808080")
        # explicit x = the driver category (same length as y) so each violin
        # sits centred on its axis tick — with name-only placement Plotly can
        # offset the violin from its label.
        fig_vio.add_trace(go.Violin(x=[drv]*len(sub), y=sub, name=drv,
            line_color=clr, fillcolor="rgba({},{},{},0.27)".format(
    int(clr[1:3],16), int(clr[3:5],16), int(clr[5:7],16)
), meanline_visible=True, width=0.9, spanmode="hard",
            orientation="v", points="all", jitter=0.35, pointpos=0,
            marker=dict(size=3,color=clr)))
    theme(fig_vio,460)
    fig_vio.update_layout(violinmode="overlay",showlegend=False,
                          yaxis_title="Lap Time (s)",
                          xaxis=dict(categoryorder="array", categoryarray=drv_order,
                                     tickangle=0))

    # ── Driver Performance Matrix ─────────────────────────────
    tg = tmgaps(fl)
    if _real:                              # same real-driver filter as the violins
        tg = tg[tg["Driver_Short"].isin(_real)]
    fig_bub = go.Figure()
    max_laps = max(tg["Laps_count"].max(), 1)
    for team in sorted(tg["Team"].unique()):
        g   = tg[tg["Team"] == team]
        clr = TEAM_COLORS.get(team, "#808080")
        fig_bub.add_trace(go.Scatter(
            x=g["Best_Lap"], y=g["Race_Median"],
            mode="markers+text", name=team,
            marker=dict(color=clr, size=g["Laps_count"],
                        sizemode="area", sizeref=2.*max_laps/(40.**2),
                        symbol="circle"),
            text=g["Driver_Short"], textposition="top center",
            textfont=dict(size=10, color=TEXT_MAIN),
            customdata=g[["Driver_Short","Race_Lap_Std_s",
                           "Quali_Gap_to_Teammate_s","Race_Gap_to_Teammate_s"]].values,
            hovertemplate=(
                "Team=%{fullData.name}<br>Best Lap (s)=%{x:.3f}<br>"
                "Median Lap (s)=%{y:.3f}<br>Laps=%{marker.size}<br>"
                "Driver=%{customdata[0]}<br>Std=%{customdata[1]:.3f}<extra></extra>"
            ),
        ))
    theme(fig_bub, 520)
    fig_bub.update_layout(xaxis_title="Best Lap Time (s)", yaxis_title="Median Lap Time (s)")

    # ── Cornering speed by corner class (real corners + season-fixed bands) ──
    # Replaces an earlier heatmap that bucketed raw samples by their own speed
    # (a tautology, and polluted by pit/SC/out-lap samples). corner_speed.py
    # works from the circuit's actual corners and each driver's apex speed.

    return html.Div([
        card("Lap Time Distribution",dcc.Graph(figure=fig_vio,config=GFX),
             info=("Data: every valid lap per driver, drawn as a "
                   "horizontal violin coloured by team. Why: shows "
                   "not just how fast a driver is but how consistent — "
                   "a tight violin means repeatable pace, a wide or "
                   "skewed one means scattered laps (traffic, errors, "
                   "mixed fuel/tyre runs).")),
        card("Driver Performance Matrix",dcc.Graph(figure=fig_bub,config=GFX),
             info=("Data: each driver plotted by best lap (x) vs median lap (y); "
                   "bubble size = number of valid laps. Why: separates one-lap "
                   "qualifying pace from sustained race pace — bottom-left is fast "
                   "over both, and a big gap between a driver's x and y hints at "
                   "tyre management or traffic issues.")),
        corner_speed_section(fl),
    ])
