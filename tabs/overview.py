"""Session OVERVIEW cards — rendered at the top of the TELEMETRY tab
(kpis, pace heatmap, cornering speed, distributions, team/driver
matrices). Extracted from app.py."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc

import state
from components import (
    theme, card, kpi, GFX, TABLE_STYLE, styled_table,
    badge as _badge, abbr as _abbr, hex_to_rgba as _hex_to_rgba,
    TEAM_ABBR as _TEAM_ABBR,
)
from config import (
    TEAM_COLORS, COMPOUND_COLORS, get_driver_color,
    DARK_BG, CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
    SPEED_PERCENTILE,
)
from processing import format_lap_time

# mirror the mutable data state (SESSIONS, DRIVERS, telemetry, …) so the
# moved bodies keep their bare-name reads — repopulated on every reload
state.register(globals())
from figures import team_metrics, tmgaps


def tab_overview(fl, fs, ft=None):
    v = fl[fl["ValidLap"]]
    best = format_lap_time(v["LapTime_s"].min()) if len(v) else "—"

    fig_vio = go.Figure()
    for drv in sorted(v["Driver_Short"].dropna().unique()):
        sub  = v[v["Driver_Short"]==drv]["LapTime_s"]
        team = fl[fl["Driver_Short"]==drv]["Team"].iloc[0]
        clr  = TEAM_COLORS.get(team,"#808080")
        fig_vio.add_trace(go.Violin(x=sub, name=drv,
            line_color=clr, fillcolor="rgba({},{},{},0.27)".format(
    int(clr[1:3],16), int(clr[3:5],16), int(clr[5:7],16)
), meanline_visible=True,
            orientation="h", points="all", jitter=0.05, pointpos=0,
            marker=dict(size=3,color=clr)))
    theme(fig_vio,420,"Lap Time Distribution by Driver")
    fig_vio.update_layout(violinmode="overlay",showlegend=False,xaxis_title="Lap Time (s)")

    cc = fl["Compound"].value_counts().reset_index()
    cc.columns=["Compound","Count"]
    fig_pie = px.pie(cc,names="Compound",values="Count",
                     color="Compound",color_discrete_map=COMPOUND_COLORS,hole=0.55)
    theme(fig_pie,300,"Compound Distribution")

    tm = team_metrics(fl)
    tm["Best Lap"] = tm["Best_Lap_s"].apply(format_lap_time)
    tm["Gap"]      = tm["Gap_to_Best_s"].apply(lambda x:f"+{x:.3f}" if x>0 else "—")
    tbl = styled_table(
        tm[["Team","Best Lap","Gap","Median_Lap_s","Lap_Std_s","Consistency","Avg_Speed","Laps"]].rename(columns={
            "Median_Lap_s":"Median (s)","Lap_Std_s":"Std Dev","Consistency":"Consistency %","Avg_Speed":"Avg Speed"
        }).to_dict("records"),
        [{"name":c,"id":c} for c in ["Team","Best Lap","Gap","Median (s)","Std Dev","Consistency %","Avg Speed","Laps"]]
    )
    # ── Driver Performance Matrix ─────────────────────────────
    tg = tmgaps(fl)
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
    theme(fig_bub, 520, "Driver Performance Matrix – Best Lap vs Race Pace (bubble = lap count)")
    fig_bub.update_layout(xaxis_title="Best Lap Time (s)", yaxis_title="Median Lap Time (s)")

    # ── Pace heatmap (Driver × Session) ───────────────────────
    heatmap_cards = []
    pivot = (v.groupby(["Driver_Short", "session_name"])["LapTime_s"]
              .median().unstack(fill_value=np.nan))
    if not pivot.empty:
        norm = pivot.copy()
        for col in norm.columns:
            lo, hi = norm[col].min(), norm[col].max()
            norm[col] = (norm[col] - lo) / (hi - lo) if hi > lo else 0.5
        ss  = [s.split("_")[0] for s in pivot.columns]
        avg = pivot.mean(axis=0); dvs = list(pivot.index)
        fp = make_subplots(rows=2, cols=1, row_heights=[0.08, 0.92],
                           vertical_spacing=0.02, shared_xaxes=True)
        fp.add_trace(go.Heatmap(z=[avg.values], x=ss, y=["Avg"], colorscale="RdYlGn_r",
            showscale=False,
            text=[avg.round(3).values], texttemplate="%{text}", textfont={"size": 10},
            hovertemplate="Session: %{x}<br>Avg: %{z:.3f} s<extra></extra>"), row=1, col=1)
        fp.add_trace(go.Heatmap(z=norm.values, x=ss, y=dvs, colorscale="RdYlGn_r",
            showscale=True,
            text=pivot.round(3).values, texttemplate="%{text}", textfont={"size": 9},
            customdata=pivot.values,
            hovertemplate="Driver: %{y}<br>Session: %{x}<br>Median: %{customdata:.3f} s<extra></extra>",
            colorbar=dict(title=dict(text="Norm", font=dict(color=TEXT_MAIN)),
                          tickfont=dict(color=TEXT_MAIN))), row=2, col=1)
        fp.update_layout(
            title="Pace Heatmap: Driver × Session (column-normalized, red=slower)",
            height=max(300, 80 + 26 * len(dvs)),
            paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
            font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
            margin=dict(l=80, r=100, t=60, b=40))
        heatmap_cards.append(card("Driver × Session Pace Heatmap",
                                  dcc.Graph(figure=fp, config=GFX),
                                  info=("Data: median valid lap time per driver in "
                                        "each session, normalised within each "
                                        "session column (0 = fastest, red = slowest); "
                                        "the top 'Avg' strip shows each session's raw "
                                        "average. Why: lets you compare relative pace "
                                        "across sessions even when absolute lap times "
                                        "differ (fuel, track evolution, conditions).")))

    # ── Cornering Speed heatmap (Driver × speed-band region) ──
    # No TrackRegion column exists in the telemetry pipeline, so derive
    # one here: keep only off-throttle / braking samples (i.e. the car is
    # in a corner phase) and bucket them by speed.
    if (ft is not None and not ft.empty
            and "Speed" in ft.columns and "Driver_Short" in ft.columns):
        tv = ft[ft["Speed"].notna()].copy()
        corner_mask = pd.Series(True, index=tv.index)
        if "Throttle" in tv.columns:
            corner_mask &= tv["Throttle"].fillna(100) < 50
        elif "Brake" in tv.columns:
            corner_mask &= tv["Brake"].fillna(False).astype(bool)
        tv = tv[corner_mask]

        region_order = ["Slow Corners (<130 km/h)",
                        "Medium Corners (130–200)",
                        "Fast Corners (>200)"]
        def _bucket(s):
            if s < 130: return region_order[0]
            if s < 200: return region_order[1]
            return region_order[2]
        tv["TrackRegion"] = tv["Speed"].apply(_bucket)

        if not tv.empty:
            cp = (tv.groupby(["Driver_Short", "TrackRegion"])["Speed"]
                    .mean().unstack(fill_value=np.nan))
            present = [r for r in region_order if r in cp.columns]
            cp = cp.sort_index().reindex(present, axis=1)
            cn = cp.copy()
            for col in cn.columns:
                lo, hi = cn[col].min(), cn[col].max()
                cn[col] = (cn[col] - lo) / (hi - lo) if hi > lo else 0.5
            ravg = cp.mean(axis=0); dc = list(cp.index); rg = list(cp.columns)
            fc = make_subplots(rows=2, cols=1, row_heights=[0.1, 0.9],
                               vertical_spacing=0.03, shared_xaxes=True)
            fc.add_trace(go.Heatmap(z=[ravg.values], x=rg, y=["Avg"], colorscale="RdYlGn",
                showscale=False,
                text=[np.round(ravg.values, 1)], texttemplate="%{text}", textfont={"size": 10},
                hovertemplate="Region: %{x}<br>Avg Speed: %{z:.1f} km/h<extra></extra>"),
                row=1, col=1)
            fc.add_trace(go.Heatmap(z=cn.values, x=rg, y=dc, colorscale="RdYlGn",
                showscale=False,
                text=np.round(cp.values, 1), texttemplate="%{text}", textfont={"size": 9},
                customdata=cp.values,
                hovertemplate="Driver: %{y}<br>Region: %{x}<br>Avg Speed: %{customdata:.1f} km/h<extra></extra>"),
                row=2, col=1)
            fc.update_layout(
                title="Cornering Speed by Track Region<br><sup>Columns normalized for comparison</sup>",
                height=max(900, 30 * len(dc) + 200),
                paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
                margin=dict(l=80, r=40, t=70, b=50))
            fc.update_yaxes(title_text="Driver", row=2, col=1,
                            gridcolor=GRID_CLR, zeroline=False)
            fc.update_xaxes(title_text="Track Region", row=2, col=1,
                            gridcolor=GRID_CLR, zeroline=False)
            heatmap_cards.append(card("Cornering Speed by Track Region",
                                      dcc.Graph(figure=fc, config=GFX),
                                      info=("Data: telemetry speed samples taken only "
                                            "while the car is in a corner phase "
                                            "(throttle <50% or braking), averaged per "
                                            "driver and bucketed into slow (<130 km/h), "
                                            "medium (130–200) and fast (>200) corners; "
                                            "columns normalised for comparison. Why: "
                                            "reveals where each driver carries speed — "
                                            "low-speed traction vs high-speed commitment.")))

    return html.Div([
        dbc.Row([kpi("BEST LAP",best,ACCENT), kpi("VALID LAPS",f"{len(v):,}","#00D2BE"),
                 kpi("DRIVERS",str(fl["Driver_Short"].nunique()),"#FF8700"),
                 kpi("SESSIONS",str(fl["session_name"].nunique()),"#FFC0CB")]),
        dbc.Row([dbc.Col(card("Lap Time Distribution",dcc.Graph(figure=fig_vio,config=GFX),
                              info=("Data: every valid lap per driver, drawn as a "
                                    "horizontal violin coloured by team. Why: shows "
                                    "not just how fast a driver is but how consistent — "
                                    "a tight violin means repeatable pace, a wide or "
                                    "skewed one means scattered laps (traffic, errors, "
                                    "mixed fuel/tyre runs).")),md=8),
                 dbc.Col(card("Compound Mix",dcc.Graph(figure=fig_pie,config=GFX),
                              info=("Data: share of laps run on each tyre compound "
                                    "across the current filter. Why: context for the "
                                    "pace figures — a field that ran mostly softs is "
                                    "not directly comparable to one on hards.")),md=4)]),
        card("Team Performance Overview",tbl,
             info=("Data: per-team aggregates over valid laps in the current "
                   "filter — best/average/median lap, consistency (std ÷ median), "
                   "fuel-corrected median, gap to the fastest team, lap and stint "
                   "counts. Why: the one-table summary of the competitive order "
                   "and how much data sits behind it.")),
        card("Driver Performance Matrix",dcc.Graph(figure=fig_bub,config=GFX),
             info=("Data: each driver plotted by best lap (x) vs median lap (y); "
                   "bubble size = number of valid laps. Why: separates one-lap "
                   "qualifying pace from sustained race pace — bottom-left is fast "
                   "over both, and a big gap between a driver's x and y hints at "
                   "tyre management or traffic issues.")),
        *heatmap_cards,
    ])
