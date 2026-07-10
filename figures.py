"""
F1 Dashboard – shared chart builders & lap-frame aggregations
=============================================================
Figure helpers used by several tabs (lap-time evolution with flag/rain
bands) and the team-level aggregation frames (team_metrics / tmgaps).
Extracted from app.py so tab modules can import them directly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from components import theme
from config import (
    TEAM_COLORS, COMPOUND_COLORS, get_driver_color,
    ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
)

# ── Helpers ──────────────────────────────────────────────────
def team_metrics(df):
    v = df[df["ValidLap"]].copy()
    ts = v.groupby("Team").agg(
        Avg_Lap_s=("LapTime_s","mean"), Median_Lap_s=("LapTime_s","median"),
        Lap_Std_s=("LapTime_s","std"),  Best_Lap_s=("LapTime_s","min"),
        Laps=("LapTime_s","count"),     FuelCorr_Median=("LapTime_FuelCorrected","median"),
        Avg_Speed=("PseudoSpeed","mean"),Stints=("Stint","max"),
        Drivers=("Driver_Short","nunique"),
    ).round(3)
    ts["Consistency"] = (ts["Lap_Std_s"]/ts["Median_Lap_s"]*100).round(2)
    f = ts["Best_Lap_s"].min()
    ts["Gap_to_Best_s"]   = (ts["Best_Lap_s"]-f).round(3)
    ts["Gap_to_Best_pct"] = ((ts["Best_Lap_s"]/f-1)*100).round(2)
    return ts.sort_values("Best_Lap_s").reset_index()

def tmgaps(df):
    v = df[df["ValidLap"]].copy()
    b = v.groupby(["Driver_Short","Team"])["LapTime_s"].min().reset_index()
    b.columns = ["Driver_Short","Team","Best_Lap"]
    r = v.groupby(["Driver_Short","Team"])["LapTime_s"].median().reset_index()
    r.columns = ["Driver_Short","Team","Race_Median"]
    s = v.groupby(["Driver_Short","Team"])["LapTime_s"].std().reset_index()
    s.columns = ["Driver_Short","Team","Race_Lap_Std_s"]
    lc= v.groupby(["Driver_Short","Team"])["LapTime_s"].count().reset_index()
    lc.columns=["Driver_Short","Team","Laps_count"]
    m = b.merge(r,on=["Driver_Short","Team"]).merge(s,on=["Driver_Short","Team"]).merge(lc,on=["Driver_Short","Team"])
    m = m.sort_values(["Team","Best_Lap"])
    out=[]
    for _,g in m.groupby("Team"):
        rows=g.to_dict("records"); n=len(rows)
        for i,d in enumerate(rows):
            qg=rg=None
            if n>=2:
                j=1-i if n==2 else None
                if j is not None:
                    o=rows[j]
                    qg=round(d["Best_Lap"]-o["Best_Lap"],3)
                    rg=round(d["Race_Median"]-o["Race_Median"],3)
            out.append({**d,"Quali_Gap_to_Teammate_s":qg,"Race_Gap_to_Teammate_s":rg})
    return pd.DataFrame(out)


# Track flag visual config: (fill_rgba, line_hex)
_FLAG_STYLE = {
    "Yellow":       ("rgba(255,215,  0,0.10)", "#B8860B"),
    "DoubleYellow": ("rgba(255,140,  0,0.15)", "#CC6600"),
    "SafetyCar":    ("rgba(  0,220, 80,0.12)", "#007700"),
    "VSC":          ("rgba(  0,150,255,0.10)", "#0055BB"),
    "VSCEnding":    ("rgba(  0,150,255,0.07)", "#0055BB"),
    "RedFlag":      ("rgba(225,  6,  0,0.18)", "#AA0000"),
}


def _add_flag_bands(fig, df_sess):
    if "TrackStatus_Flag" not in df_sess.columns:
        return
    flag_laps = (
        df_sess[df_sess["TrackStatus_Flag"].isin(_FLAG_STYLE)]
        .sort_values("LapNo")[["LapNo", "TrackStatus_Flag"]]
        .drop_duplicates()
    )
    if flag_laps.empty:
        return
    groups = []
    for _, row in flag_laps.iterrows():
        lap, flag = int(row["LapNo"]), row["TrackStatus_Flag"]
        if groups and groups[-1]["flag"] == flag and lap == groups[-1]["end"] + 1:
            groups[-1]["end"] = lap
        else:
            groups.append({"flag": flag, "start": lap, "end": lap})
    seen = set()
    for grp in groups:
        flag = grp["flag"]
        fill, line_clr = _FLAG_STYLE[flag]
        show = flag not in seen
        seen.add(flag)
        fig.add_vrect(
            x0=grp["start"] - 0.5, x1=grp["end"] + 0.5,
            fillcolor=fill,
            line=dict(color=line_clr, width=1, dash="dot"),
            layer="below",
            annotation_text=flag if show else "",
            annotation_position="top left",
            annotation_font=dict(size=9, color=line_clr),
        )


def _rain_lap_groups(per_lap: pd.DataFrame) -> list[tuple[int, int]]:
    """Return contiguous (start_lap, end_lap) ranges where it was raining,
    from a per-lap frame carrying a boolean-ish 'Rainfall' column."""
    if "Rainfall" not in per_lap.columns or "LapNo" not in per_lap.columns:
        return []
    wet = per_lap[per_lap["Rainfall"].fillna(False).astype(bool)].sort_values("LapNo")
    if wet.empty:
        return []
    groups: list[tuple[int, int]] = []
    for lap in wet["LapNo"].astype(int):
        if groups and lap == groups[-1][1] + 1:
            groups[-1] = (groups[-1][0], lap)
        else:
            groups.append((lap, lap))
    return groups


def _add_rain_bands(fig, df_sess, row=None, col=None):
    """Shade laps run in the rain as blue vertical bands, mirroring the
    SC/flag bands from _add_flag_bands. No-op when there is no Rainfall data
    or the race was dry. Pass row/col to target one panel of a subplot."""
    if "Rainfall" not in df_sess.columns or "LapNo" not in df_sess.columns:
        return
    per_lap = df_sess.groupby("LapNo")["Rainfall"].max().reset_index()
    groups = _rain_lap_groups(per_lap)
    rc = dict(row=row, col=col) if row is not None else {}
    for i, (start, end) in enumerate(groups):
        fig.add_vrect(
            x0=start - 0.5, x1=end + 0.5,
            fillcolor="rgba(0,120,255,0.12)",
            line=dict(color="#0066CC", width=1, dash="dot"),
            layer="below",
            annotation_text=("\U0001f327 rain" if i == 0 else ""),
            annotation_position="bottom left",
            annotation_font=dict(size=9, color="#4DA3FF"),
            **rc,
        )


def _lap_evolution_fig(sv, title, height=540):
    """Per-driver lap-time line chart for a SINGLE session: one line per driver,
    markers tinted by compound, track-flag periods shaded behind. Shared by the
    Stints tab (any session) and the Race tab (race only)."""
    fig = go.Figure()
    for drv in sorted(sv["Driver_Short"].dropna().unique()):
        dv = sv[sv["Driver_Short"] == drv].sort_values("LapNo")
        if dv.empty:
            continue
        clr = TEAM_COLORS.get(dv["Team"].iloc[0], "#808080")
        # Build x/y/compound lists; insert None to break the line at lap gaps
        x_vals, y_vals, c_vals, f_vals = [], [], [], []
        prev_lap = None
        for _, row in dv.iterrows():
            if prev_lap is not None and row["LapNo"] - prev_lap > 1:
                x_vals.append(None); y_vals.append(None)
                c_vals.append(None); f_vals.append(None)
            x_vals.append(row["LapNo"])
            y_vals.append(row["LapTime_s"] if pd.notna(row["LapTime_s"]) else None)
            c_vals.append(row.get("Compound") or "?")
            f_vals.append(row.get("TrackStatus_Flag") or "Clear")
            prev_lap = row["LapNo"]

        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode="lines+markers",
            name=drv,
            line=dict(color=clr, width=1.5),
            marker=dict(
                size=6,
                color=[COMPOUND_COLORS.get(c, clr) if c else clr for c in c_vals],
                line=dict(color=clr, width=1),
            ),
            customdata=list(zip(c_vals, f_vals)),
            hovertemplate=(
                f"<b>{drv}</b><br>"
                "Lap %{x}  |  %{y:.3f} s<br>"
                "Compound: %{customdata[0]}<br>"
                "Flag: %{customdata[1]}<extra></extra>"
            ),
        ))

    _add_flag_bands(fig, sv)
    _add_rain_bands(fig, sv)
    theme(fig, height, title)
    fig.update_layout(
        xaxis_title="Lap Number",
        yaxis_title="Lap Time (s)",
        legend=dict(
            bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1,
            orientation="v",
        ),
    )
    return fig


# ── Tyre usage history chart (shared: STINTS + TRACK) ────────
def _tyre_history_chart(laps_df: pd.DataFrame) -> go.Figure:
    """Stacked bar of valid laps per session broken down by compound."""
    v = laps_df[laps_df["ValidLap"] & laps_df["Compound"].notna()].copy()
    fig = go.Figure()
    if v.empty:
        return fig

    usage = (
        v.groupby(["session_name", "Compound"])
        .agg(Laps=("LapTime_s", "count"), AvgLapTime=("LapTime_s", "median"))
        .reset_index()
    )

    for cmp in ("SOFT", "MEDIUM", "HARD", "INTER", "WET"):
        sub = usage[usage["Compound"] == cmp]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            x=sub["session_name"].apply(lambda s: s.split("_")[0]),
            y=sub["Laps"],
            name=cmp,
            marker_color=COMPOUND_COLORS.get(cmp, "#808080"),
            hovertemplate=f"{cmp}<br>Session: %{{x}}<br>Valid laps: %{{y}}<extra></extra>",
        ))

    theme(fig, 280, "Tyre Compound Usage — Valid Laps by Session")
    fig.update_layout(
        barmode="stack",
        xaxis_title="Session",
        yaxis_title="Laps",
        legend=dict(orientation="h", x=0, y=1.14, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=50, r=20, t=60, b=40),
    )
    return fig
