"""
DATA tab — session selection (load/unload at runtime) plus the Data-Quality
inspection page. Extracted from app.py + tabs/stints.py.

Public: tab_data_selection() and tab_data_quality(fl, fs); the two callbacks
(update_event_controls, load_selected) are @callback-registered on import.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import (
    html, dcc, dash_table, callback, ctx, no_update,
    Input, Output, State,
)
import dash_bootstrap_components as dbc

import f1lib.state as state
from f1lib.state import rebuild_state
from f1lib.components import (
    theme, card, kpi, GFX, TABLE_STYLE, styled_table,
    badge as _badge, abbr as _abbr,
)
from f1lib.config import (
    TEAM_COLORS, COMPOUND_COLORS, get_min_laps_for_compound,
    ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
    CURRENT_SEASON,
    MIN_LAPS_SOFT, MIN_LAPS_MEDIUM, MIN_LAPS_HARD,
)
from f1lib.data_loader import is_cached, season_meetings, sessions_for_meeting
from f1lib.processing import format_lap_time

# mirror the mutable data state so bare `laps`, `laps_raw`, `stints`,
# SESSIONS, DRIVERS, TEAMS reads inside the moved bodies keep working
state.register(globals())

# ── Event / session discovery (for the Data Selection tab) ───
# The heavy lifting (schedule fetch, offline cache fallback, canonical session
# ordering) lives in data_loader; here we only shape it for the UI.
AVAILABLE_SEASON   = CURRENT_SEASON
SELECTABLE_SEASONS = [CURRENT_SEASON - i for i in range(6)]


def _event_session_preview(season: int, meeting: str | None):
    """Read-only list of the sessions 'Load Event' will pull for *meeting*,
    each tagged cached / to-fetch."""
    sessions = sessions_for_meeting(season, meeting) if meeting else []
    if not sessions:
        return html.P("No sessions available for this event yet.",
                      style={"color": TEXT_DIM, "fontSize": "0.82rem"})

    flags = [is_cached(s["SEASON"], s["MEETING"], s["SESSION"]) for s in sessions]
    n_cached = sum(flags)
    rows = []
    for s, cached in zip(sessions, flags):
        tag = "● cached" if cached else "○ fetch (~1–3 min)"
        rows.append(html.Li([
            html.Span(s["SESSION"], style={"color": TEXT_MAIN}),
            html.Span(f"   {tag}", style={
                "color": "#00D2BE" if cached else "#FF8700",
                "fontSize": "0.72rem", "marginLeft": "8px"}),
        ], style={"marginBottom": "4px", "fontSize": "0.82rem"}))

    return html.Div([
        html.P(f"{len(sessions)} session(s) · {n_cached} cached · "
               f"{len(sessions) - n_cached} to fetch",
               style={"color": TEXT_DIM, "fontSize": "0.72rem", "marginBottom": "6px"}),
        html.Ul(rows, style={"listStyle": "none", "paddingLeft": "0",
                             "marginBottom": "0"}),
    ])


def _status_icon(ok: bool):
    return "✅" if ok else "❌"

def tab_data_quality(fl, fs):
    # ── 0. Global counts ────────────────────────────────────
    raw_rows      = len(laps_raw)
    enr_rows      = len(laps)
    row_match     = raw_rows == enr_rows

    total         = len(laps)
    has_laptime   = int(laps["LapTime_s"].notna().sum())
    pct_laptime   = has_laptime / total * 100 if total else 0
    valid_count   = int(laps["ValidLap"].sum())
    pct_valid     = valid_count / total * 100 if total else 0
    pit_count     = int(laps["PitLap"].sum())
    outlier_count = int((
        laps["LapTime_s"].notna()
        & (laps["LapTime_s"] > laps["LapTime_s"].median() * 1.25)
        & ~laps["PitLap"]
    ).sum())
    if "Perturbed_Lap" in laps.columns:
        perturbed_count = int(laps["Perturbed_Lap"].sum())
        pct_perturbed   = perturbed_count / total * 100 if total else 0
    else:
        perturbed_count = None
        pct_perturbed   = None

    # ── 1. Per-session overview ──────────────────────────────
    per_sess = (
        laps.groupby("session_name")
        .agg(
            Total_Laps   =("LapNo",       "count"),
            Valid_Laps   =("ValidLap",     "sum"),
            Pit_Laps     =("PitLap",       "sum"),
            With_LapTime =("LapTime_s",    lambda x: x.notna().sum()),
            Drivers      =("Driver_Short", "nunique"),
            Teams        =("Team",         "nunique"),
            Best_Lap_s   =("LapTime_s",    "min"),
            Median_Lap_s =("LapTime_s",    "median"),
            Stints       =("Stint",        "max"),
        )
        .reset_index()
    )
    per_sess["Valid_%"]   = (per_sess["Valid_Laps"]   / per_sess["Total_Laps"] * 100).round(1)
    per_sess["LapTime_%"] = (per_sess["With_LapTime"] / per_sess["Total_Laps"] * 100).round(1)
    per_sess["Best Lap"]  = per_sess["Best_Lap_s"].apply(format_lap_time)
    per_sess = per_sess.rename(columns={"session_name": "Session"})

    sess_tbl = styled_table(
        per_sess[[
            "Session", "Total_Laps", "Valid_Laps", "Valid_%", "Pit_Laps",
            "LapTime_%", "Drivers", "Teams", "Stints", "Best Lap",
        ]].to_dict("records"),
        [{"name": c, "id": c} for c in [
            "Session", "Total_Laps", "Valid_Laps", "Valid_%", "Pit_Laps",
            "LapTime_%", "Drivers", "Teams", "Stints", "Best Lap",
        ]],
    )

    # ── 3. LapTime coverage bar (per session) ───────────────
    fig_cov = go.Figure()
    for _, row in per_sess.iterrows():
        sess = row["Session"]
        fig_cov.add_trace(go.Bar(
            x=[sess], y=[row["Valid_%"]],  name="Valid",
            marker_color="#00D2BE", showlegend=(_ == 0),
        ))
        fig_cov.add_trace(go.Bar(
            x=[sess], y=[row["LapTime_%"]], name="Has LapTime",
            marker_color="#FF8700", showlegend=(_ == 0),
        ))
    theme(fig_cov, 300, "Coverage per Session (%)")
    fig_cov.update_layout(barmode="group", yaxis=dict(range=[0,105], gridcolor=GRID_CLR, zeroline=False),
                           xaxis_title="Session", yaxis_title="%")

    # ── 5. ValidLap breakdown donut per session ──────────────
    breakdown_cards = []
    for sess in SESSIONS:
        sub = laps[laps["session_name"] == sess]
        n_valid    = int(sub["ValidLap"].sum())
        n_pit      = int(sub["PitLap"].sum())
        n_no_time  = int(sub["LapTime_s"].isna().sum())
        n_outlier  = int((
            sub["LapTime_s"].notna()
            & (sub["LapTime_s"] > sub["LapTime_s"].median() * 1.25)
            & ~sub["PitLap"]
        ).sum())
        n_other    = len(sub) - n_valid - n_pit - n_no_time - n_outlier
        n_other    = max(n_other, 0)
        fig_d = px.pie(
            names=["Valid","Pit/OutLap","No LapTime","Outlier (>125%)","Other excluded"],
            values=[n_valid, n_pit, n_no_time, n_outlier, n_other],
            color_discrete_sequence=["#00D2BE","#FF8700","#FFC0CB","#E10600","#808080"],
            hole=0.55,
        )
        theme(fig_d, 260, sess)
        fig_d.update_traces(textinfo="percent+label", textfont_size=9)
        fig_d.update_layout(showlegend=False, margin=dict(l=10,r=10,t=40,b=10))
        breakdown_cards.append(dbc.Col(dcc.Graph(figure=fig_d, config=GFX), md=6))

    # ── 6. Multi-compound stints (integrity check on RAW labels) ─
    # Uses Compound_RAW so we measure the original data quality
    # independently of the cleaning step.
    _compound_col = "Compound_RAW" if "Compound_RAW" in laps.columns else "Compound"
    stint_comp = (
        laps.dropna(subset=[_compound_col])
        .groupby("Stint_key")[_compound_col]
        .nunique()
        .reset_index()
        .rename(columns={_compound_col: "N_Compounds"})
    )
    dirty = stint_comp[stint_comp["N_Compounds"] > 1].copy()
    n_dirty        = len(dirty)
    n_total_stints = len(stint_comp)
    dirty_pct      = n_dirty / n_total_stints * 100 if n_total_stints else 0
    if n_dirty > 0:
        dirty_detail = laps[laps["Stint_key"].isin(dirty["Stint_key"])].groupby(
            ["Stint_key","session_name","Driver_Short","Stint"]
        ).agg(
            Raw_Compounds   =(  _compound_col, lambda x: ", ".join(x.dropna().unique())),
            Clean_Compounds =("Compound",      lambda x: ", ".join(x.dropna().unique())),
        ).reset_index()
        dirty_rows = dirty_detail.to_dict("records")
        dirty_cols = [{"name": c, "id": c} for c in dirty_detail.columns]
    else:
        dirty_rows, dirty_cols = [], []

    dirty_status = _status_icon(n_dirty == 0)
    dirty_tbl    = styled_table(dirty_rows, dirty_cols) if n_dirty > 0 else html.P(
        "✅ All stints use a single compound.", style={"color":"#00D2BE","fontWeight":"700"}
    )

    # ── 6b. Valid stints after cleaning ──────────────────────
    # How many stints pass the minimum-laps threshold on the CLEAN compound?
    # Mirrors analyze_stints logic: count valid laps per driver×stint×compound,
    # compare against the per-compound minimum.
    _stint_laps = (
        laps[laps["ValidLap"]]
        .groupby(["session_name", "Driver_Short", "Stint", "Compound"])
        .size()
        .reset_index(name="_laps")
    )
    _stint_laps["_min_req"] = _stint_laps["Compound"].apply(get_min_laps_for_compound)
    _stint_laps["_passes"]  = _stint_laps["_laps"] >= _stint_laps["_min_req"]
    n_stints_total = len(_stint_laps)
    n_stints_valid = int(_stint_laps["_passes"].sum())
    pct_stints_valid = n_stints_valid / n_stints_total * 100 if n_stints_total else 0

    # ── 7. PseudoTyreAge vs TyreAge comparison ───────────────
    has_tyre_col = "TyreAge" in laps.columns
    if has_tyre_col:
        _pool  = laps[laps["TyreAge"].notna() & laps["PseudoTyreAge"].notna()]
        sample = _pool.sample(min(2000, len(_pool)), random_state=42)
        fig_tyre = go.Figure(go.Scatter(
            x=sample["TyreAge"], y=sample["PseudoTyreAge"],
            mode="markers", marker=dict(size=4, color=ACCENT, opacity=0.5),
            hovertemplate="TyreAge: %{x}<br>PseudoTyreAge: %{y}<extra></extra>",
        ))
        mn = min(sample["TyreAge"].min(), sample["PseudoTyreAge"].min())
        mx = max(sample["TyreAge"].max(), sample["PseudoTyreAge"].max())
        fig_tyre.add_trace(go.Scatter(x=[mn,mx], y=[mn,mx], mode="lines",
            line=dict(color="#00D2BE", dash="dash", width=1), name="Perfect match"))
        theme(fig_tyre, 380, "PseudoTyreAge vs TyreAge (should be on the diagonal)")
        fig_tyre.update_layout(xaxis_title="TyreAge (raw)", yaxis_title="PseudoTyreAge (computed)")
        delta = (sample["PseudoTyreAge"] - sample["TyreAge"]).abs().mean()
        tyre_note = f"Mean absolute deviation: {delta:.2f} laps"
    else:
        fig_tyre = None
        tyre_note = "TyreAge column not present in dataset — PseudoTyreAge cannot be cross-validated."

    # ── 8. Unknown teams ────────────────────────────────────
    unknown_drvs = sorted(laps[laps["Team"] == "Unknown"]["Driver_Short"].unique())

    # ── 9. Column schema table ───────────────────────────────
    schema = pd.DataFrame({
        "Column":     laps.columns.tolist(),
        "DType":      [str(laps[c].dtype) for c in laps.columns],
        "Non-Null":   [int(laps[c].notna().sum()) for c in laps.columns],
        "NaN Count":  [int(laps[c].isna().sum())  for c in laps.columns],
        "NaN %":      [(laps[c].isna().sum() / total * 100).round(1) for c in laps.columns],
        "Unique Vals":[int(laps[c].nunique(dropna=False)) for c in laps.columns],
        "Sample":     [str(laps[c].dropna().iloc[0]) if laps[c].notna().any() else "—"
                       for c in laps.columns],
    })
    # highlight high-nan columns in red
    schema_tbl = dash_table.DataTable(
        data=schema.to_dict("records"),
        columns=[{"name": c, "id": c} for c in schema.columns],
        **TABLE_STYLE,
        style_data_conditional=[
            {"if": {"filter_query": "{NaN %} > 50"}, "backgroundColor": "#3D0A0A", "color": "#FF9999"},
            {"if": {"filter_query": "{NaN %} > 20 && {NaN %} <= 50"}, "backgroundColor": "#2D200A"},
            {"if": {"filter_query": "{NaN %} = 0"}, "color": "#00D2BE"},
        ],
    )

    # ── 10. Compound distribution heat (driver × compound × session) ─
    comp_counts = (
        fl[fl["ValidLap"]]
        .groupby(["session_name","Driver_Short","Compound"])
        .size()
        .reset_index(name="Laps")
    )
    if not comp_counts.empty:
        pivot_cc = comp_counts.pivot_table(
            index="Driver_Short", columns=["session_name","Compound"],
            values="Laps", fill_value=0
        )
        pivot_cc.columns = [f"{s}|{c}" for s, c in pivot_cc.columns]
        fig_comp_heat = go.Figure(go.Heatmap(
            z=pivot_cc.values,
            x=list(pivot_cc.columns),
            y=list(pivot_cc.index),
            colorscale="Blues",
            text=pivot_cc.values,
            texttemplate="%{text}",
            textfont={"size": 9},
            hovertemplate="Driver: %{y}<br>Session|Compound: %{x}<br>Valid Laps: %{z}<extra></extra>",
            colorbar=dict(title=dict(text="Laps", font=dict(color=TEXT_MAIN)), tickfont=dict(color=TEXT_MAIN)),
        ))
        theme(fig_comp_heat, max(300, 26 * len(pivot_cc) + 120),
              "Valid Laps per Driver × Session × Compound")
        fig_comp_heat.update_layout(
            margin=dict(l=80,r=60,t=60,b=120),
            xaxis=dict(tickangle=45, gridcolor=GRID_CLR, zeroline=False),
        )
    else:
        fig_comp_heat = None

    # ── Build layout ─────────────────────────────────────────
    return html.Div([
        # ── KPI row 1 ────────────────────────────────────────
        dbc.Row([
            kpi("TOTAL LAPS (raw)",      f"{raw_rows:,}", "#808080",
                tooltip="Raw row count from FastF1 before any enrichment or cleaning."),
            kpi("TOTAL LAPS (enriched)", f"{enr_rows:,}",
                "#00D2BE" if row_match else ACCENT,
                tooltip="Row count after clean_and_enrich_laps(). Should match raw — a mismatch indicates a pipeline bug."),
            kpi("HAS LAP TIME",          f"{pct_laptime:.1f}%", "#FF8700",
                tooltip="% of laps with a non-null LapTime_s. Laps without a time are excluded from all pace analysis."),
            kpi("VALID LAPS",            f"{pct_valid:.1f}%", "#00D2BE",
                tooltip="% of laps passing ALL validity checks: non-pit, non-deleted, has LapTime, and within 125% of compound/team/session median."),
        ]),
        dbc.Row([
            kpi("ROW COUNT MATCH",  f"{_status_icon(row_match)} {'OK' if row_match else 'MISMATCH'}",
                "#00D2BE" if row_match else ACCENT,
                tooltip="Confirms clean_and_enrich_laps() preserved the exact row count. Any change indicates unintended row creation or deletion."),
            kpi("PIT / OUT LAPS",   f"{pit_count:,}", "#FFC0CB",
                tooltip="Laps where the driver entered or exited the pit lane. Excluded from pace and degradation analysis."),
            kpi("OUTLIERS REMOVED", f"{outlier_count:,}", ACCENT,
                tooltip="Laps slower than 125% of the per-session/compound/team median (excluding pit laps). Does NOT use flag_perturbed_laps — see PERTURBED LAPS below."),
            kpi("DIRTY STINTS (raw)",
                f"{dirty_status} {dirty_pct:.1f}% ({n_dirty}/{n_total_stints})",
                "#00D2BE" if n_dirty == 0 else ACCENT,
                tooltip="Based on Compound_RAW: % of stints where more than one raw compound label was recorded. Includes UNKNOWN/NaN that were later cleaned. Non-zero is expected — see the Stint Compound Integrity table below."),
            kpi("VALID STINTS (clean)",
                f"{pct_stints_valid:.1f}% ({n_stints_valid}/{n_stints_total})",
                "#00D2BE" if pct_stints_valid >= 50 else ACCENT,
                tooltip=f"After compound cleaning: % of driver×stint×compound groups meeting the minimum lap threshold (SOFT≥{MIN_LAPS_SOFT}, MEDIUM≥{MIN_LAPS_MEDIUM}, HARD≥{MIN_LAPS_HARD}). These are the stints usable for race pace and degradation analysis."),
        ]),
        *([dbc.Row([
            kpi("PERTURBED LAPS", f"{pct_perturbed:.1f}% ({perturbed_count:,})", "#FFC0CB",
                tooltip="Laps flagged by flag_perturbed_laps(): either TrackStatus indicates Yellow/SC/VSC/RedFlag, OR a sector time anomaly (>2.5× IQR above 75th pct for that driver/session/compound) was detected. These laps are NOT automatically excluded by ValidLap — filter on Perturbed_Lap=False for clean pace analysis."),
        ])] if perturbed_count is not None else []),

        # ── Pipeline check alerts ─────────────────────────────
        *([dbc.Alert(
            f"⚠️  Row count mismatch: raw={raw_rows:,} → enriched={enr_rows:,} "
            f"({enr_rows-raw_rows:+,} rows). Check clean_and_enrich_laps().",
            color="danger", style={"fontSize":"0.8rem","borderRadius":"6px"},
        )] if not row_match else []),
        *([dbc.Alert(
            f"⚠️  Unknown team detected for: {', '.join(unknown_drvs)}. "
            "The Driver column format may not contain '-TeamName'.",
            color="warning", style={"fontSize":"0.8rem","borderRadius":"6px"},
        )] if unknown_drvs else []),

        # ── Coverage & breakdown ─────────────────────────────
        card("Session Coverage (%)", dcc.Graph(figure=fig_cov, config=GFX),
             info=("Data: every enriched lap, grouped by session. Bars show the "
                   "share of laps that are Valid (teal) and that carry a recorded "
                   "LapTime (orange). Why: a quick completeness check — low coverage "
                   "means that session's pace analysis rests on few usable laps.")),
        card("Lap Breakdown by Session", dbc.Row(breakdown_cards),
             info=("Data: all laps per session, classified into Valid, Pit/Out-lap, "
                   "No LapTime, Outlier (>125% of median) and Other-excluded. Why: "
                   "shows exactly why laps are dropped before analysis, so you can "
                   "judge how representative the surviving 'valid' laps are.")),

        # ── Per-session table ────────────────────────────────
        card("Per-Session Statistics", sess_tbl,
             info=("Data: one row per loaded session — total/valid/pit lap "
                   "counts, lap-time coverage, driver/team/stint counts and the "
                   "session's best lap. Why: a health check of what actually "
                   "loaded; a session with low valid % or missing lap times "
                   "will produce weak numbers everywhere else.")),

        # ── Compound × Driver heatmap (sidebar-filtered) ─────
        *([card("Valid Laps: Driver × Session × Compound",
                dcc.Graph(figure=fig_comp_heat, config=GFX),
                info=("Data: count of valid laps per driver × session × compound "
                      "(respects the sidebar filters). Why: a sample-size map — "
                      "darker cells mean more laps, so you can see which "
                      "driver/compound/session combinations have enough data to "
                      "trust the pace and degradation numbers elsewhere."))]
          if fig_comp_heat else []),

        # ── Multi-compound stints ────────────────────────────
        card(
            html.Span([
                f"{dirty_status} Stint Compound Integrity (Compound_RAW)",
                _badge(f"{n_dirty} dirty stints ({dirty_pct:.1f}%)", "#00D2BE" if n_dirty==0 else ACCENT),
                _badge("Raw labels before cleaning — non-zero is expected", "#444"),
            ]),
            dirty_tbl,
            info=("Data: stints whose raw feed carried more than one compound "
                  "label (before cleaning reassigned them to the stint's "
                  "dominant compound). Why: transparency on how much the "
                  "compound-cleaning step had to fix — a high dirty share for "
                  "a session means compound-split charts there rest on "
                  "reconstructed labels."),
        ),

        # ── TyreAge cross-validation ─────────────────────────
        card(
            "PseudoTyreAge vs TyreAge Cross-Validation",
            html.Div([
                html.P(tyre_note, style={"color": TEXT_DIM, "fontSize": "0.8rem", "marginBottom": "8px"}),
                dcc.Graph(figure=fig_tyre, config=GFX) if fig_tyre else html.Div(),
            ]),
            info=("Data: a random sample of up to 2000 laps that have both the raw "
                  "TyreAge (from the source feed) and the pipeline-computed "
                  "PseudoTyreAge. Why: each point should sit on the dashed diagonal "
                  "if our stint/tyre-age reconstruction is correct — drift off the "
                  "line flags a bug in the tyre-age logic."),
        ),

        # ── Column schema ────────────────────────────────────
        card(
            html.Span([
                "Column Schema",
                _badge("green = 0% NaN  |  yellow = <50%  |  red = >50%", "#444"),
            ]),
            schema_tbl,
            info=("Data: every column in the enriched laps frame with its dtype "
                  "and NaN percentage, colour-coded. Why: shows which signals "
                  "are actually available for the loaded sessions — a red "
                  "column (mostly NaN) silently disables the analyses that "
                  "depend on it."),
        ),
    ])


from tabs.overview import tab_overview

from tabs.teams import tab_teams


def tab_data_selection() -> html.Div:
    try:
        return _tab_data_selection_inner()
    except Exception as exc:
        import traceback
        return html.Div([
            dbc.Alert([html.B("Data Selection error: "), str(exc)],
                      color="danger", style={"fontSize": "0.82rem"}),
            html.Pre(traceback.format_exc(), style={
                "color": TEXT_DIM, "fontSize": "0.7rem", "background": "#09091A",
                "padding": "12px", "borderRadius": "6px", "overflowX": "auto",
            }),
        ])


def _tab_data_selection_inner() -> html.Div:
    # Default the pickers to the currently-loaded event.
    if LOADED_SESSION_INFO:
        loaded_season  = int(LOADED_SESSION_INFO[0]["SEASON"])
        loaded_meeting = LOADED_SESSION_INFO[0]["MEETING"]
    else:
        loaded_season, loaded_meeting = AVAILABLE_SEASON, None

    season   = loaded_season if loaded_season in SELECTABLE_SEASONS else AVAILABLE_SEASON
    meetings = season_meetings(season)
    meeting  = loaded_meeting if loaded_meeting in meetings else (
        meetings[-1] if meetings else None)

    status_banner = (
        dbc.Alert(LAST_LOAD_MSG, color="info",
                  style={"fontSize": "0.8rem", "borderRadius": "6px", "marginBottom": "12px"})
        if LAST_LOAD_MSG else html.Div()
    )

    lbl_style = {"color": TEXT_DIM, "fontSize": "0.65rem", "letterSpacing": "1px",
                 "fontWeight": "700", "marginBottom": "4px", "display": "block"}

    return html.Div([
        html.H4("Event Data Selection",
                style={"color": TEXT_MAIN, "fontWeight": "800", "letterSpacing": "1px",
                       "marginBottom": "6px", "fontSize": "1.05rem"}),
        html.P([
            "Pick a season and an event — loading pulls every available session "
            "for that event (practice, qualifying, sprint, race). Sessions already "
            "downloaded are marked ",
            html.Span("● cached", style={"color": "#00D2BE", "fontWeight": "700"}),
            "; anything marked ",
            html.Span("○ fetch", style={"color": "#FF8700", "fontWeight": "700"}),
            " is downloaded from FastF1 the first time (1–3 min each).",
        ], style={"color": TEXT_DIM, "fontSize": "0.82rem", "marginBottom": "10px"}),

        status_banner,

        dbc.Row([
            kpi("CURRENTLY LOADED", str(len(SESSIONS)), ACCENT,
                tooltip="Sessions currently active in the dashboard."),
        ]),

        card("Select Event", info=(
            "Data: every event of the chosen season that has already run, and "
            "the sessions available for it (green = stored locally, instant "
            "load). Why: this controls what every other tab analyses — switch "
            "events here without restarting the app."
        ), children=html.Div([
            # ── Season + event selectors ──────────────────────
            dbc.Row([
                dbc.Col([
                    html.Label("SEASON", style=lbl_style),
                    dcc.Dropdown(
                        id="data-season-select",
                        options=[{"label": str(y), "value": y} for y in SELECTABLE_SEASONS],
                        value=season, clearable=False,
                        style={"backgroundColor": "#111", "fontSize": "0.82rem"},
                    ),
                ], md=3),
                dbc.Col([
                    html.Label("EVENT", style=lbl_style),
                    dcc.Dropdown(
                        id="data-event-select",
                        options=[{"label": m.replace(" Grand Prix", ""), "value": m}
                                 for m in meetings],
                        value=meeting, clearable=False,
                        style={"backgroundColor": "#111", "fontSize": "0.82rem"},
                    ),
                ], md=6),
            ], className="mb-3"),

            # ── Read-only preview of what "Load Event" will pull ──
            html.Label("SESSIONS THAT WILL LOAD", style=lbl_style),
            html.Div(
                _event_session_preview(season, meeting),
                id="data-event-sessions",
                style={"border": f"1px solid {GRID_CLR}", "borderRadius": "6px",
                       "padding": "10px", "background": "#0E0E1C",
                       "marginBottom": "4px"},
            ),

            html.Hr(style={"borderColor": GRID_CLR}),
            dbc.Button("⟳  Load Event", id="data-load-btn",
                       color="danger", style={"fontWeight": "700"}),
            dcc.Loading(
                type="circle", color=ACCENT,
                children=html.Div(id="data-load-status", style={"marginTop": "12px"}),
            ),
        ])),
    ])


# ── Event picker: season switch rebuilds events, event change re-previews ──
@callback(
    Output("data-event-select",   "options"),
    Output("data-event-select",   "value"),
    Output("data-event-sessions", "children"),
    Input("data-season-select",   "value"),
    Input("data-event-select",    "value"),
    prevent_initial_call=True,
)
def update_event_controls(season, meeting):
    trig    = ctx.triggered_id
    season  = int(season) if season else AVAILABLE_SEASON
    meetings = season_meetings(season)
    options  = [{"label": m.replace(" Grand Prix", ""), "value": m} for m in meetings]

    # Season switch → rebuild event list, default to that season's most recent event.
    if trig == "data-season-select":
        meeting = meetings[-1] if meetings else None
        return options, meeting, _event_session_preview(season, meeting)

    # Event change → refresh the session preview only.
    return no_update, no_update, _event_session_preview(season, meeting)


# ── Load the selected event's sessions (rebuilds app state) ──
@callback(
    Output("data-load-status",  "children"),
    Output("session-filter",    "options"),
    Output("session-filter",    "value"),
    Output("team-filter",       "options"),
    Output("team-filter",       "value"),
    Output("driver-filter",     "options"),
    Output("driver-filter",     "value"),
    Output("main-subtitle",     "children"),
    Input("data-load-btn",      "n_clicks"),
    State("data-season-select", "value"),
    State("data-event-select",  "value"),
    prevent_initial_call=True,
)
def load_selected(_n, season, meeting):
    if not meeting:
        warn = dbc.Alert("Pick an event before loading.",
                         color="warning", style={"fontSize": "0.8rem"})
        return (warn, *([no_update] * 7))

    info = sessions_for_meeting(int(season) if season else AVAILABLE_SEASON, meeting)
    if not info:
        warn = dbc.Alert("No sessions available for that event yet.",
                         color="warning", style={"fontSize": "0.8rem"})
        return (warn, *([no_update] * 7))

    try:
        msg = rebuild_state(info)
        ok  = msg.startswith("Loaded")
    except Exception as exc:
        import traceback
        return (
            dbc.Alert([html.B("Load failed: "), str(exc),
                       html.Pre(traceback.format_exc(),
                                style={"fontSize": "0.68rem", "marginTop": "8px",
                                       "whiteSpace": "pre-wrap"})],
                      color="danger", style={"fontSize": "0.8rem"}),
            *([no_update] * 7),
        )

    status = dbc.Alert(("✅ " if ok else "⚠️ ") + msg,
                       color="success" if ok else "warning",
                       style={"fontSize": "0.82rem"})
    if not ok:
        return (status, *([no_update] * 7))

    sess_opts = [{"label": s, "value": s} for s in SESSIONS]
    team_opts = [{"label": t, "value": t} for t in TEAMS]
    drv_opts  = [{"label": d, "value": d} for d in DRIVERS]
    subtitle  = " | ".join(SESSIONS)
    return (status,
            sess_opts, SESSIONS,
            team_opts, TEAMS,
            drv_opts,  DRIVERS,
            subtitle)
