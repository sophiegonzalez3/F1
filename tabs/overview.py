"""Session OVERVIEW cards — rendered at the top of the TELEMETRY tab
(lap-time distribution, driver performance matrix, cornering speed).
Extracted from app.py."""
from __future__ import annotations

import plotly.graph_objects as go
from dash import html, dcc

import f1lib.state as state
from f1lib.components import theme, card, GFX
from f1lib.glossary import gloss
from f1lib.config import TEAM_COLORS, TEXT_MAIN
from tabs.corner_speed import corner_speed_section

# mirror the mutable data state (SESSIONS, DRIVERS, telemetry, …) so the
# moved bodies keep their bare-name reads — repopulated on every reload
state.register(globals())
from f1lib.figures import tmgaps
from f1lib.standings import (
    _driver_standings_after_round, _loaded_meeting_season_round,
)


def _laptime_plain(v):
    """Beginner reading of the lap-time violins: fastest single lap + who was
    the most consistent. `v` = valid laps (real drivers only)."""
    if v.empty:
        return None
    best = v.groupby("Driver_Short")["LapTime_s"].min()
    if best.empty:
        return None
    line = (f"Each shape is one driver's spread of lap times this session — "
            f"lower means quicker. {best.idxmin()} set the single fastest lap "
            "here.")
    counts = v.groupby("Driver_Short")["LapTime_s"].count()
    elig = counts[counts >= 5].index
    if len(elig):
        std = (v[v["Driver_Short"].isin(elig)]
               .groupby("Driver_Short")["LapTime_s"].std().dropna())
        if not std.empty:
            line += (f" A tightly bunched shape means very repeatable pace; "
                     f"{std.idxmin()} were the most consistent.")
    return line


def overview_pace_cards(fl):
    """The two headline pace cards — Lap Time Distribution (per-driver violins)
    and Driver Performance Matrix (best vs median lap). Returned as a list of
    cards so they can be reused outside the TELEMETRY overview (e.g. the WEEK
    END PRED practice-construction section)."""
    v = fl[fl["ValidLap"]]

    # Test drivers are already gone: the sidebar's driver filter excludes them
    # and Is_Race_Driver marks them in the lap data (f1lib.roster). This used
    # to filter on "is this driver in the championship standings?", which
    # happened to work mid-season and silently emptied the chart in pre-season
    # and at round 1, when nobody has scored yet. Kept as a belt-and-braces
    # guard for callers that pass unfiltered laps.
    if "Is_Race_Driver" in v.columns:
        v = v[v["Is_Race_Driver"]]

    _season, _, _ = _loaded_meeting_season_round()
    _ds = _driver_standings_after_round(_season, None)

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
    # tmgaps() aggregates the UNFILTERED laps, so re-apply the same race-driver
    # restriction the violins above use — otherwise this chart alone would show
    # the FP1 testers.
    tg = tmgaps(fl)
    if "Is_Race_Driver" in fl.columns:
        _race = set(fl.loc[fl["Is_Race_Driver"], "Driver_Short"].dropna())
        tg = tg[tg["Driver_Short"].isin(_race)]
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

    return [
        card([*gloss("lap time", "Lap Time"), " Distribution"],dcc.Graph(figure=fig_vio,config=GFX),
             info=("Data: every valid lap per driver, drawn as a "
                   "horizontal violin coloured by team. Why: shows "
                   "not just how fast a driver is but how consistent — "
                   "a tight violin means repeatable pace, a wide or "
                   "skewed one means scattered laps (traffic, errors, "
                   "mixed fuel/tyre runs). Drivers on a mandated rookie FP1 "
                   "outing are excluded — they are not measuring the same "
                   "thing as the race driver whose seat they took, and up to "
                   "six of them ran at once in 2026. The sidebar lists them "
                   "and can put them back."),
             plain=_laptime_plain(v)),
        card("Driver Performance Matrix",dcc.Graph(figure=fig_bub,config=GFX),
             info=("Data: each driver plotted by best lap (x) vs median lap (y); "
                   "bubble size = number of valid laps. Test drivers on their "
                   "mandated FP1 outing are excluded. Why: separates "
                   "one-lap speed from sustained race pace — bottom-left is fast "
                   "over both, and a big gap between a driver's x and y hints at "
                   "tyre management or traffic issues.")),
    ]


def tab_overview(fl, fs, ft=None):
    # ── Cornering speed by corner class (real corners + season-fixed bands) ──
    # Replaces an earlier heatmap that bucketed raw samples by their own speed
    # (a tautology, and polluted by pit/SC/out-lap samples). corner_speed.py
    # works from the circuit's actual corners and each driver's apex speed.
    return html.Div([
        corner_speed_section(fl),
    ])
