"""
DATA tab — session selection (load/unload at runtime) plus the Data-Quality
inspection page. Extracted from app.py + tabs/stints.py.

Public: tab_data_selection() and tab_data_quality(fl, fs); the two callbacks
(update_session_controls, load_selected) are @callback-registered on import.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import (
    html, dcc, dash_table, callback, ctx, no_update, ALL,
    Input, Output, State,
)
import dash_bootstrap_components as dbc

import state
from state import rebuild_state
from components import (
    theme, card, kpi, GFX, TABLE_STYLE, styled_table,
    badge as _badge, abbr as _abbr,
)
from config import (
    TEAM_COLORS, COMPOUND_COLORS, get_min_laps_for_compound,
    ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
    FASTF1_CACHE_DIR,
    MIN_LAPS_SOFT, MIN_LAPS_MEDIUM, MIN_LAPS_HARD,
)
from data_loader import is_cached, list_cached_sessions
from processing import format_lap_time

# mirror the mutable data state so bare `laps`, `laps_raw`, `stints`,
# SESSIONS, DRIVERS, TEAMS reads inside the moved bodies keep working
state.register(globals())

# ── Available-session discovery (for the Data Selection tab) ──
AVAILABLE_SEASON  = 2026
SELECTABLE_SEASONS = [2026, 2025, 2024, 2023, 2022, 2021]
_SCHEDULE_CACHE: dict[int, list[dict]] = {}   # season → memoized session list


def _sess_value(season, meeting, session) -> str:
    """Encode a session triple as a single checklist value."""
    return f"{season}|||{meeting}|||{session}"


def _parse_sess_value(value: str) -> dict:
    """Decode a checklist value back into a SESSION_INFO_LIST dict."""
    season, meeting, session = value.split("|||")
    return {"SEASON": season, "MEETING": meeting, "SESSION": session}


def get_available_sessions(season: int = AVAILABLE_SEASON, refresh: bool = False) -> list[dict]:
    """
    Return every session of *season* that has already taken place (date in
    the past), each annotated with whether it is cached locally.

    Source of truth is FastF1's event schedule. If FastF1 is unavailable or
    the network fails, fall back to whatever is in the local Parquet cache so
    the tab still works offline.

    Each item: {round, meeting, session, fmt, season, cached, value}
    Result is memoized per-season in _SCHEDULE_CACHE (refresh=True rebuilds).
    """
    season = int(season)
    if season in _SCHEDULE_CACHE and not refresh:
        # Refresh only the cheap 'cached' flags (files may have appeared)
        for it in _SCHEDULE_CACHE[season]:
            it["cached"] = is_cached(str(it["season"]), it["meeting"], it["session"])
        return _SCHEDULE_CACHE[season]

    items: list[dict] = []
    try:
        import fastf1
        from datetime import datetime, timezone
        fastf1.Cache.enable_cache(str(Path(FASTF1_CACHE_DIR)))
        sched = fastf1.get_event_schedule(season, include_testing=False)
        now = pd.Timestamp(datetime.now(timezone.utc).replace(tzinfo=None))
        for _, e in sched.iterrows():
            rnd  = int(e.get("RoundNumber", 0))
            name = str(e.get("EventName", "")).strip()
            fmt  = str(e.get("EventFormat", "conventional"))
            if not name:
                continue
            for i in range(1, 6):
                sn = e.get(f"Session{i}")
                sd = e.get(f"Session{i}DateUtc")
                if pd.isna(sn) or not str(sn).strip():
                    continue
                try:
                    is_past = pd.to_datetime(sd) <= now
                except Exception:
                    is_past = False
                if not is_past:
                    continue
                items.append({
                    "round": rnd, "meeting": name, "session": str(sn).strip(),
                    "fmt": fmt, "season": season,
                    "cached": is_cached(str(season), name, str(sn).strip()),
                    "value": _sess_value(season, name, str(sn).strip()),
                })
    except Exception as exc:
        print(f"  [schedule] FastF1 unavailable for {season} ({exc}); using local cache", flush=True)

    if not items:
        # Offline fallback: enumerate this season's sessions from the Parquet cache
        for s in list_cached_sessions():
            if str(s.get("season")) != str(season):
                continue
            meeting = s.get("meeting", "?"); session = s.get("session", "?")
            items.append({
                "round": 0, "meeting": meeting, "session": session,
                "fmt": "conventional", "season": season, "cached": True,
                "value": _sess_value(season, meeting, session),
            })

    items.sort(key=lambda x: (x["round"], x["meeting"], x["session"]))
    _SCHEDULE_CACHE[season] = items
    return items


# ── Session-type grouping helpers (for shortcut selectors) ────
def _session_type(session: str) -> str:
    """Bucket a session name into Practice / Qualifying / Sprint / Race."""
    s = session.lower()
    if "sprint" in s:        return "Sprint"      # Sprint + Sprint Qualifying
    if "practice" in s:      return "Practice"
    if "qualifying" in s:    return "Qualifying"
    if "race" in s:          return "Race"
    return "Other"


def _season_meetings(season: int) -> list[str]:
    """Ordered list of unique circuit/meeting names available for *season*."""
    seen, out = set(), []
    for it in get_available_sessions(season):
        if it["meeting"] not in seen:
            seen.add(it["meeting"]); out.append(it["meeting"])
    return out


def _session_option_label(it: dict) -> str:
    tag = "● cached" if it["cached"] else "○ fetch (~1–3 min)"
    rnd = f"R{it['round']}" if it["round"] else "—"
    spr = "  ⚡" if it["session"] in ("Sprint", "Sprint Qualifying") else ""
    return f"{rnd} · {it['meeting']} · {it['session']}{spr}   [{tag}]"


def _session_options(season: int) -> list[dict]:
    return [{"label": _session_option_label(it), "value": it["value"]}
            for it in get_available_sessions(season)]


def _list_summary(season: int) -> str:
    av = get_available_sessions(season)
    n_cached = sum(1 for it in av if it["cached"])
    return f"Season {season} · {len(av)} sessions available · {n_cached} cached · {len(av)-n_cached} to fetch"


def _circuit_buttons(season: int) -> list:
    """One click-to-add button per circuit for *season* (pattern-matching IDs)."""
    btn_style = {"fontSize": "0.72rem", "marginRight": "6px", "marginBottom": "6px"}
    out = []
    for m in _season_meetings(season):
        short = m.replace(" Grand Prix", "")
        out.append(dbc.Button(
            f"+ {short}",
            id={"type": "data-circuit-btn", "index": m},
            size="sm", color="info", outline=True, style=btn_style,
        ))
    return out


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
    season = AVAILABLE_SEASON
    avail  = get_available_sessions(season)
    loaded_values = {
        _sess_value(i["SEASON"], i["MEETING"], i["SESSION"]) for i in LOADED_SESSION_INFO
    }
    pre_selected = [it["value"] for it in avail if it["value"] in loaded_values]

    status_banner = (
        dbc.Alert(LAST_LOAD_MSG, color="info",
                  style={"fontSize": "0.8rem", "borderRadius": "6px", "marginBottom": "12px"})
        if LAST_LOAD_MSG else html.Div()
    )

    sc_style  = {"fontSize": "0.72rem", "marginRight": "6px", "marginBottom": "6px"}
    lbl_style = {"color": TEXT_DIM, "fontSize": "0.65rem", "letterSpacing": "1px",
                 "fontWeight": "700", "marginBottom": "4px", "display": "block"}

    return html.Div([
        html.H4("Session Data Selection",
                style={"color": TEXT_MAIN, "fontWeight": "800", "letterSpacing": "1px",
                       "marginBottom": "6px", "fontSize": "1.05rem"}),
        html.P([
            "Pick which sessions to load into the dashboard. Pick a season, then "
            "use the shortcuts or tick individual sessions. Sessions already "
            "downloaded are marked ",
            html.Span("● cached", style={"color": "#00D2BE", "fontWeight": "700"}),
            "; selecting an ",
            html.Span("○ fetch", style={"color": "#FF8700", "fontWeight": "700"}),
            " session downloads it from FastF1 the first time (1–3 min each).",
        ], style={"color": TEXT_DIM, "fontSize": "0.82rem", "marginBottom": "10px"}),

        status_banner,

        dbc.Row([
            kpi("CURRENTLY LOADED", str(len(SESSIONS)), ACCENT,
                tooltip="Sessions currently active in the dashboard."),
        ]),

        card("Select Sessions", info=(
            "Data: every session of the chosen season that has already taken "
            "place, with a cache indicator (green = stored locally, instant "
            "load). Why: this controls what every other tab analyses — swap "
            "events or add sessions here without restarting the app."
        ), children=html.Div([
            # ── Season selector ───────────────────────────────
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
            ], className="mb-3"),

            # ── Add all sessions for one circuit (one click each) ──
            html.Label("ADD ALL SESSIONS FOR A CIRCUIT", style=lbl_style),
            html.Div(_circuit_buttons(season), id="data-circuit-btns",
                     style={"marginBottom": "8px"}),

            # ── Shortcut buttons by session type ──────────────
            html.Label("QUICK SELECT BY TYPE  (adds to current selection)", style=lbl_style),
            html.Div([
                dbc.Button("+ All Practice",   id="data-sel-practice", size="sm", color="secondary", outline=True, style=sc_style),
                dbc.Button("+ All Qualifying", id="data-sel-quali",    size="sm", color="secondary", outline=True, style=sc_style),
                dbc.Button("+ All Sprint",     id="data-sel-sprint",   size="sm", color="secondary", outline=True, style=sc_style),
                dbc.Button("+ All Race",       id="data-sel-race",     size="sm", color="secondary", outline=True, style=sc_style),
            ], style={"marginBottom": "8px"}),

            html.Label("WHOLE LIST", style=lbl_style),
            html.Div([
                dbc.Button("Select all",         id="data-sel-all",    size="sm", color="secondary", outline=True, style=sc_style),
                dbc.Button("Select cached only", id="data-sel-cached", size="sm", color="secondary", outline=True, style=sc_style),
                dbc.Button("Clear",              id="data-sel-clear",  size="sm", color="secondary", outline=True, style=sc_style),
            ], style={"marginBottom": "10px"}),

            html.Div(_list_summary(season), id="data-list-summary",
                     style={"color": TEXT_DIM, "fontSize": "0.72rem", "marginBottom": "8px"}),

            # ── The scrollable session checklist ──────────────
            html.Div(
                dcc.Checklist(
                    id="data-session-select",
                    options=_session_options(season),
                    value=pre_selected,
                    inputStyle={"marginRight": "8px", "accentColor": ACCENT},
                    labelStyle={"display": "block", "marginBottom": "6px",
                                "fontSize": "0.8rem", "color": TEXT_MAIN},
                ),
                style={"maxHeight": "360px", "overflowY": "auto",
                       "border": f"1px solid {GRID_CLR}", "borderRadius": "6px",
                       "padding": "10px", "background": "#0E0E1C"},
            ),

            html.Hr(style={"borderColor": GRID_CLR}),
            dbc.Button("⟳  Load Selected Sessions", id="data-load-btn",
                       color="danger", style={"fontWeight": "700"}),
            dcc.Loading(
                type="circle", color=ACCENT,
                children=html.Div(id="data-load-status", style={"marginTop": "12px"}),
            ),
        ])),
    ])


# ── Session selector: season switch + shortcut buttons ───────
@callback(
    Output("data-session-select", "options"),
    Output("data-session-select", "value"),
    Output("data-list-summary",   "children"),
    Output("data-circuit-btns",   "children"),
    Input("data-season-select",   "value"),
    Input("data-sel-all",      "n_clicks"),
    Input("data-sel-cached",   "n_clicks"),
    Input("data-sel-clear",    "n_clicks"),
    Input("data-sel-practice", "n_clicks"),
    Input("data-sel-quali",    "n_clicks"),
    Input("data-sel-sprint",   "n_clicks"),
    Input("data-sel-race",     "n_clicks"),
    Input({"type": "data-circuit-btn", "index": ALL}, "n_clicks"),
    State("data-session-select", "value"),
    prevent_initial_call=True,
)
def update_session_controls(season, _a, _c, _z, _p, _q, _s, _r, _circ, cur_value):
    trig    = ctx.triggered_id
    season  = int(season) if season else AVAILABLE_SEASON
    avail   = get_available_sessions(season)
    options = _session_options(season)
    summary = _list_summary(season)

    # Season switch → rebuild list + per-circuit buttons, preselect loaded sessions
    if trig == "data-season-select":
        loaded_values = {
            _sess_value(i["SEASON"], i["MEETING"], i["SESSION"]) for i in LOADED_SESSION_INFO
        }
        value = [it["value"] for it in avail if it["value"] in loaded_values]
        return options, value, summary, _circuit_buttons(season)

    # All other triggers keep the same season → buttons untouched
    cur = list(cur_value or [])
    seen = set(cur)

    def _union(pred):
        for it in avail:
            if pred(it) and it["value"] not in seen:
                cur.append(it["value"]); seen.add(it["value"])
        return cur

    if isinstance(trig, dict) and trig.get("type") == "data-circuit-btn":
        # Pattern-matching button can fire on (re)creation with n_clicks=None;
        # ignore those no-op triggers.
        if not any((ctx.triggered[0]["value"],)):
            value = cur
        else:
            value = _union(lambda it: it["meeting"] == trig["index"])
    elif trig == "data-sel-all":      value = [it["value"] for it in avail]
    elif trig == "data-sel-cached":   value = [it["value"] for it in avail if it["cached"]]
    elif trig == "data-sel-clear":    value = []
    elif trig == "data-sel-practice": value = _union(lambda it: _session_type(it["session"]) == "Practice")
    elif trig == "data-sel-quali":    value = _union(lambda it: it["session"] == "Qualifying")
    elif trig == "data-sel-sprint":   value = _union(lambda it: _session_type(it["session"]) == "Sprint")
    elif trig == "data-sel-race":     value = _union(lambda it: it["session"] == "Race")
    else:                             value = cur

    return options, value, summary, no_update


# ── Load selected sessions (rebuilds app state) ──────────────
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
    State("data-session-select", "value"),
    prevent_initial_call=True,
)
def load_selected(_n, selected):
    if not selected:
        warn = dbc.Alert("Select at least one session before loading.",
                         color="warning", style={"fontSize": "0.8rem"})
        return (warn, *([no_update] * 7))

    info = [_parse_sess_value(v) for v in selected]
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
