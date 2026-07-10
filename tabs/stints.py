"""
STINTS tab — stint aggregation, degradation, cliffs, compound offsets,
plus the interactive Lap Evolution overlay and per-driver Stint Inspector.
Extracted from app.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, dash_table, callback, Input, Output, State
import dash_bootstrap_components as dbc

import state
from components import (
    theme, card, kpi, GFX, TABLE_STYLE, styled_table,
    badge as _badge, abbr as _abbr, hex_to_rgba as _hex_to_rgba,
)
from config import (
    TEAM_COLORS, COMPOUND_COLORS,
    ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
    MIN_LAPS_MEDIUM,
)
from processing import (
    field_deg_curves, detect_stint_cliffs, compound_offsets, format_lap_time,
)
from figures import _add_flag_bands, _add_rain_bands, _lap_evolution_fig, _tyre_history_chart
from tyre_allocations import _allocation_chips, _laps_event

# mirror the mutable data state so bare `laps`, `stints`, SESSIONS, DRIVERS,
# TEAMS, COMPOUNDS reads inside the moved bodies keep working across reloads
state.register(globals())

# ── Stints – Lap Evolution graph callback ────────────────────
@callback(
    Output("stints-evo-graph", "figure"),
    Input("stints-evo-session",  "value"),
    State("driver-filter",       "value"),
    State("team-filter",         "value"),
)
def update_stints_evo(session, sd, st):
    sd = sd or DRIVERS
    st = st or TEAMS

    if not session:
        return go.Figure()

    sv = laps[
        (laps["session_name"] == session)
        & laps["Driver_Short"].isin(sd)
        & laps["Team"].isin(st)
    ].copy()

    sess_label = session.split("_")[0]
    return _lap_evolution_fig(
        sv, f"Lap Time Evolution \u2013 All Laps \u2013 {sess_label}"
    )


# ── Stint Lap Inspector callbacks ────────────────────────────
# Compound emoji map for dropdown labels
_COMPOUND_ICON = {"SOFT": "🔴", "MEDIUM": "🟡", "HARD": "⚪", "INTER": "🟢", "WET": "🔵"}


@callback(
    Output("stint-insp-key", "options"),
    Output("stint-insp-key", "value"),
    Input("stint-insp-driver", "value"),
    State("session-filter",   "value"),
    State("team-filter",      "value"),
)
def update_stint_key_options(driver, ss, st):
    """Build human-readable ranked-stint options for the inspector dropdown."""
    if not driver:
        return [], None
    ss = ss or SESSIONS
    st = st or TEAMS

    drv_stints = stints[
        (stints["Driver_Short"] == driver)
        & stints["session_name"].isin(ss)
        & stints["Team"].isin(st)
        & stints["Valid_Stint"]
    ].copy()

    if drv_stints.empty:
        return [], None

    # Reconstruct Stint_key (analyze_stints doesn't carry it)
    drv_stints["Stint_key"] = (
        drv_stints["Stint"].astype("string")
        + "_" + drv_stints["Driver_Short"]
        + "_" + drv_stints["session_name"]
    )

    opts: list[dict] = []
    seen_keys: set[str] = set()

    def _add(label: str, row: pd.Series) -> None:
        key = row["Stint_key"]
        if pd.isna(key) or key in seen_keys:
            return
        seen_keys.add(key)
        compound = row.get("Compound", "?")
        icon     = _COMPOUND_ICON.get(compound, "⬜")
        pace_fmt = format_lap_time(row.get("Stint_Rep_Lap", float("nan")))
        laps_n   = int(row.get("Stint_Laps_Count", 0))
        sess     = str(row.get("session_name", "")).split("_")[0]
        opts.append({
            "label": f"{label}  {icon}{compound}  {pace_fmt}  ({laps_n} laps, {sess})",
            "value": key,
        })

    # ── 1. Best overall (lowest Stint_Rep_Lap across all valid stints) ──
    if "Stint_Rank_Overall" in drv_stints.columns:
        best_overall = drv_stints.sort_values("Stint_Rep_Lap").iloc[0]
        _add("Best overall", best_overall)

    # ── 2. Best per session (Stint_Rank_No_Compound = 1 in that session) ──
    for sess in sorted(drv_stints["session_name"].unique()):
        sess_label = sess.split("_")[0]
        sub = drv_stints[drv_stints["session_name"] == sess].sort_values("Stint_Rep_Lap")
        if not sub.empty:
            _add(f"Best in {sess_label}", sub.iloc[0])

    # ── 3. Best per compound (Stint_Rank_Across_Sessions = 1) ──
    for compound in COMPOUNDS:
        sub = drv_stints[drv_stints["Compound"] == compound].sort_values("Stint_Rep_Lap")
        if sub.empty:
            continue
        icon = _COMPOUND_ICON.get(compound, "⬜")
        _add(f"{icon} Best on {compound}", sub.iloc[0])

    # ── 4. Any remaining valid stints not yet listed ──
    for _, row in drv_stints.sort_values("Stint_Rep_Lap").iterrows():
        if row["Stint_key"] not in seen_keys:
            _add(f"   Stint {int(row['Stint'])}", row)

    first_val = opts[0]["value"] if opts else None
    return opts, first_val


@callback(
    Output("stint-insp-table", "children"),
    Input("stint-insp-driver", "value"),
    Input("stint-insp-key",    "value"),
)
def render_stint_table(driver, stint_key):
    if not driver or not stint_key:
        return html.P("Select a driver and stint key.", style={"color": TEXT_DIM})
    sub = laps[
        (laps["Driver_Short"] == driver) & (laps["Stint_key"] == stint_key)
    ].sort_values("LapNo")
    if sub.empty:
        return html.P("No laps found for this selection.", style={"color": TEXT_DIM})
    cols_want  = ["Stint_key", "LapNo", "LapTime_s", "Compound", "TyreAge", "LapInStint"]
    cols_avail = [c for c in cols_want if c in sub.columns]
    sub = sub[cols_avail].copy()
    if "LapTime_s" in sub.columns:
        pos = sub.columns.get_loc("LapTime_s") + 1
        sub.insert(pos, "LapTime", sub["LapTime_s"].apply(format_lap_time))
    return dash_table.DataTable(
        data=sub.to_dict("records"),
        columns=[{"name": c, "id": c} for c in sub.columns],
        **TABLE_STYLE,
        style_data_conditional=[
            {"if": {"filter_query": "{LapInStint} = 1"},
             "borderLeft": f"3px solid {ACCENT}"},
        ],
    )


def _best_stint_laps(fl, stints_df):
    """Return laps that belong to the best valid stint per driver x compound
    (session-agnostic: Stint_Rank_Across_Sessions == 1).
    Falls back to all valid laps if stints_df is empty or ranking unavailable.

    Note: analyze_stints() does not carry Stint_key, so we match on the
    three component columns (session_name, Driver_Short, Stint) instead.
    """
    if stints_df is None or stints_df.empty or "Stint_Rank_Across_Sessions" not in stints_df.columns:
        return fl[fl["ValidLap"]].copy()

    best = stints_df[
        stints_df["Valid_Stint"] & (stints_df["Stint_Rank_Across_Sessions"] == 1)
    ][["session_name", "Driver_Short", "Stint"]].drop_duplicates()

    # Build a merge key on the laps side then filter
    fl_valid = fl[fl["ValidLap"]].copy()
    merged = fl_valid.merge(
        best.assign(_keep=True),
        on=["session_name", "Driver_Short", "Stint"],
        how="left",
    )
    return merged[merged["_keep"] == True].drop(columns=["_keep"]).copy()


def tab_stints(fl, fs):
    # 1. Lap Time Evolution layout (dynamic via callback)
    avail_sessions = sorted(fl["session_name"].unique())
    default_sess   = avail_sessions[0] if avail_sessions else None

    flag_pills = [
        html.Span("Track flags: ",
                  style={"color": TEXT_DIM, "fontSize": "0.72rem"}),
    ]
    for label, bg in [
        ("Yellow", "#B8860B"), ("Dbl Yellow", "#CC6600"),
        ("Safety Car", "#007700"), ("VSC", "#0055BB"), ("Red Flag", "#AA0000"),
    ]:
        flag_pills.append(html.Span(label, style={
            "background": bg, "color": "#fff", "borderRadius": "3px",
            "padding": "2px 7px", "fontSize": "0.68rem", "fontWeight": "700",
            "marginRight": "5px",
        }))

    evo_layout = html.Div([
        html.Div(
            dcc.RadioItems(
                id="stints-evo-session",
                options=[{"label": s, "value": s} for s in avail_sessions],
                value=default_sess,
                inline=True,
                inputStyle={"marginRight": "6px", "accentColor": ACCENT},
                labelStyle={
                    "marginRight": "18px", "fontSize": "0.78rem",
                    "color": TEXT_MAIN, "cursor": "pointer",
                },
            ),
            style={"marginBottom": "10px"},
        ),
        html.Div(flag_pills, style={"marginBottom": "8px"}),
        dcc.Graph(id="stints-evo-graph", config=GFX),
    ])

    # 2. Violin per compound – laps from best stint only (session-agnostic)
    best_laps = _best_stint_laps(fl, fs)
    v_note = html.P(
        "ℹ️  Each violin uses only laps from the single best valid stint "
        "per driver × compound across all selected sessions "
        "(Stint_Rank_Across_Sessions = 1).",
        style={"color": TEXT_DIM, "fontSize": "0.75rem", "marginBottom": "6px",
               "fontStyle": "italic"},
    )
    team_order = (
        best_laps.groupby("Team")["LapTime_s"].min().sort_values().index.tolist()
        if not best_laps.empty else []
    )

    violin_cards = []
    for compound in COMPOUNDS:
        df_comp = best_laps[best_laps["Compound"] == compound]
        if df_comp.empty:
            continue
        fig_v = go.Figure()
        anns  = []
        for team in team_order:
            df_team = df_comp[df_comp["Team"] == team]
            if df_team.empty:
                continue
            drivers = sorted(df_team["Driver_Short"].dropna().unique())
            clr  = TEAM_COLORS.get(team, "#808080")
            rgba = "rgba({},{},{},0.27)".format(
                int(clr[1:3], 16), int(clr[3:5], 16), int(clr[5:7], 16)
            )
            for i, driver in enumerate(drivers[:2]):
                df_drv = df_team[df_team["Driver_Short"] == driver]
                if df_drv.empty:
                    continue
                lap_count = len(df_drv)
                ymax      = df_drv["LapTime_s"].max()
                ymin      = df_drv["LapTime_s"].min()
                margin    = (ymax - ymin) * 0.2 if ymax != ymin else 0.5
                side      = "negative" if i == 0 else "positive"
                pointpos  = -0.8      if i == 0 else 0.8
                fig_v.add_trace(go.Violin(
                    x=[team] * lap_count,
                    y=df_drv["LapTime_s"],
                    legendgroup=driver,
                    scalegroup=team,
                    name=driver,
                    side=side,
                    pointpos=pointpos,
                    line_color=clr,
                    fillcolor=rgba,
                    meanline_visible=True,
                    points="all",
                    jitter=0.05,
                    scalemode="count",
                    showlegend=True,
                ))
                anns.append(dict(
                    x=team, y=ymax + margin / 2,
                    text=f"{driver} ({lap_count})",
                    showarrow=False,
                    xshift=-25 if side == "negative" else 25,
                    yshift=10,
                    font=dict(size=11, color=clr),
                ))
        theme(fig_v, 650,
              f"Lap Time Distribution – {compound} (best stint per driver, all sessions)")
        fig_v.update_layout(
            violingap=0, violingroupgap=0, violinmode="overlay",
            xaxis=dict(categoryorder="array", categoryarray=team_order,
                       gridcolor=GRID_CLR, zeroline=False),
            yaxis_title="Lap Time (s)",
            annotations=anns,
        )
        violin_cards.append(card(
            f"Distribution – {compound}",
            html.Div([v_note, dcc.Graph(figure=fig_v, config=GFX)]),
            info=(f"Data: lap times from each driver's single best valid {compound} "
                  "stint across all selected sessions (split-violin per teammate "
                  "pair, point count shown). Why: compares teams on equal tyre, "
                  "showing both typical pace (the body) and consistency (the spread)."),
        ))

    # 3. Tyre Degradation – per compound:
    #    (a) Ranked horizontal bar: Stint_Deg_Rate from each driver's LONGEST
    #        valid stint (ties → lowest slope standard error). Selecting by
    #        best R² — the previous approach — is biased: R² scales with
    #        |slope|, so it systematically picked each driver's most-degrading
    #        stint and hid flat (well-managed) ones. Error bars show ±1.96×SE.
    #        Source: analyze_stints(), fuel- AND track-evolution-corrected.
    #    (b) Normalised evolution: track-corrected lap-time delta from a
    #        baseline of the stint's first 3 clean laps (median — a single
    #        lap-1 baseline is the noisiest lap of the stint), using the
    #        LONGEST valid non-perturbed stint per driver × compound.
    deg_cards = []
    valid_stints = fs[fs["Valid_Stint"]].copy() if not fs.empty else pd.DataFrame()

    # Build a clean laps pool: ValidLap AND not Perturbed_Lap (if column exists)
    _perturb_mask = fl["Perturbed_Lap"] if "Perturbed_Lap" in fl.columns else pd.Series(False, index=fl.index)
    clean_laps = fl[fl["ValidLap"] & ~_perturb_mask].copy()

    # Cliff detection across all compounds (markers on the evolution charts
    # below + the dedicated Cliff Map card after the per-compound cards)
    cliffs_df = detect_stint_cliffs(fl)

    for compound in COMPOUNDS:
        comp_stints = (
            valid_stints[valid_stints["Compound"] == compound].copy()
            if not valid_stints.empty else pd.DataFrame()
        )

        # --- (a) Deg rate bar: longest valid stint per driver ---
        # Longest stint = most degradation signal. Ties broken by lowest
        # slope standard error (most consistent laps).
        fig_bar = None
        df_deg  = pd.DataFrame()
        if not comp_stints.empty and "Stint_Deg_Rate" in comp_stints.columns:
            _se_sort = (comp_stints["Stint_Deg_SE"]
                        if "Stint_Deg_SE" in comp_stints.columns
                        else pd.Series(np.nan, index=comp_stints.index))
            df_deg = (
                comp_stints.assign(_se=_se_sort.fillna(np.inf))
                .sort_values(["Stint_Laps_Count", "_se"],
                             ascending=[False, True])
                .groupby("Driver_Short", sort=False)
                .first()
                .reset_index()
                .drop(columns=["_se"])
            )
            df_deg = df_deg[df_deg["Stint_Deg_Rate"].notna()].copy()

        if not df_deg.empty:
            df_deg = df_deg.sort_values("Stint_Deg_Rate", ascending=False)
            df_deg["Color"]   = df_deg["Team"].map(TEAM_COLORS).fillna("#808080")
            df_deg["DegFmt"]  = df_deg["Stint_Deg_Rate"].apply(
                lambda x: f"+{x:.4f}" if x >= 0 else f"{x:.4f}"
            )
            _has_se = "Stint_Deg_SE" in df_deg.columns
            df_deg["CI95"] = (
                (1.96 * pd.to_numeric(df_deg["Stint_Deg_SE"], errors="coerce"))
                if _has_se else np.nan
            )
            df_deg["CIFmt"] = df_deg["CI95"].apply(
                lambda x: f"±{x:.4f}" if pd.notna(x) else "±n/a"
            )
            df_deg["R2Fmt"] = df_deg["Stint_Deg_R2"].apply(
                lambda x: f"R²={x:.2f}" if pd.notna(x) else "R²=n/a"
            )
            max_abs = (
                (df_deg["Stint_Deg_Rate"].abs() + df_deg["CI95"].fillna(0))
                .max() * 1.3 or 0.05
            )

            fig_bar = go.Figure(go.Bar(
                y=df_deg["Driver_Short"],
                x=df_deg["Stint_Deg_Rate"],
                orientation="h",
                marker=dict(
                    color=df_deg["Color"],
                    line=dict(color=GRID_CLR, width=0.5),
                ),
                error_x=dict(
                    type="data",
                    array=df_deg["CI95"].fillna(0),
                    color="rgba(255,255,255,0.55)",
                    thickness=1.2, width=4,
                ) if _has_se else None,
                customdata=df_deg[["Team", "DegFmt", "CIFmt", "R2Fmt",
                                   "Stint_Laps_Count", "session_name"]].values,
                hovertemplate=(
                    "<b>%{y}</b>  Team: %{customdata[0]}<br>"
                    "Deg rate: %{customdata[1]} %{customdata[2]} s/lap (95% CI)<br>"
                    "%{customdata[3]}<br>"
                    "Laps in stint: %{customdata[4]}<br>"
                    "Session: %{customdata[5]}<extra></extra>"
                ),
                text=df_deg["DegFmt"],
                textposition="outside",
                textfont=dict(size=10, color=TEXT_MAIN),
            ))
            fig_bar.add_vline(x=0, line=dict(color="white", width=1, dash="dash"))
            fig_bar.add_vrect(x0=-max_abs, x1=0,
                fillcolor="rgba(0,200,100,0.05)", line_width=0, layer="below")
            fig_bar.add_vrect(x0=0, x1=max_abs,
                fillcolor="rgba(225,6,0,0.05)", line_width=0, layer="below")
            ht = max(300, 28 * len(df_deg) + 80)
            theme(fig_bar, ht,
                  f"{compound} – Degradation Rate (longest stint, fuel- & track-corrected)")
            fig_bar.update_layout(
                xaxis=dict(
                    title="s/lap of tyre age  ·  lower = less degradation",
                    range=[-max_abs, max_abs],
                    gridcolor=GRID_CLR, zeroline=False,
                ),
                yaxis=dict(gridcolor=GRID_CLR, zeroline=False, autorange="reversed"),
                bargap=0.25, showlegend=False,
                annotations=[dict(
                    text="whiskers = 95% confidence interval of the fitted slope",
                    xref="paper", yref="paper", x=1, y=1.02,
                    xanchor="right", showarrow=False,
                    font=dict(size=9, color=TEXT_DIM),
                )],
            )

        # --- (b) Normalised evolution: longest clean stint per driver ---
        # Group clean laps by (driver, stint) and pick the stint with most laps
        comp_clean = clean_laps[clean_laps["Compound"] == compound].copy()
        _age_col = "TyreAge" if "TyreAge" in comp_clean.columns else "LapInStint"

        fig_norm = go.Figure()
        if not comp_clean.empty:
            stint_lens = (
                comp_clean.groupby(["Driver_Short", "session_name", "Stint"])
                .size()
                .reset_index(name="_n_laps")
                .sort_values("_n_laps", ascending=False)
            )
            # Best stint = longest; one per driver
            best_per_drv = (
                stint_lens.groupby("Driver_Short", sort=False)
                .first()
                .reset_index()
            )
            for _, brow in best_per_drv.iterrows():
                drv  = brow["Driver_Short"]
                sess = brow["session_name"]
                snt  = brow["Stint"]
                n    = int(brow["_n_laps"])
                if n < 2:
                    continue
                df_drv = (
                    comp_clean[
                        (comp_clean["Driver_Short"] == drv)
                        & (comp_clean["session_name"] == sess)
                        & (comp_clean["Stint"] == snt)
                    ]
                    .sort_values(_age_col)
                )
                _y_col = ("LapTime_TrackCorrected"
                          if "LapTime_TrackCorrected" in df_drv.columns
                          else "LapTime_FuelCorrected")
                # Baseline = median of the stint's first 3 clean laps. A
                # single-lap baseline (the old approach) anchored every
                # subsequent point to the noisiest lap of the stint.
                baseline = df_drv[_y_col].head(3).median()
                if pd.isna(baseline) or baseline <= 0:
                    continue
                clr   = TEAM_COLORS.get(df_drv["Team"].iloc[0], "#808080")
                delta = df_drv[_y_col] - baseline
                sess_label = sess.split("_")[0]
                fig_norm.add_trace(go.Scatter(
                    x=df_drv[_age_col],
                    y=delta,
                    mode="lines+markers",
                    name=f"{drv} ({n} laps, {sess_label})",
                    line=dict(color=clr, width=2),
                    marker=dict(size=6, color=clr),
                    hovertemplate=(
                        f"<b>{drv}</b><br>"
                        "Tyre age: %{x} laps<br>"
                        "Δ fuel-corrected from stint start: %{y:+.3f} s"
                        "<extra></extra>"
                    ),
                ))
                # Star marker where this stint's deg cliff was detected
                if not cliffs_df.empty:
                    cl = cliffs_df[
                        (cliffs_df["Driver_Short"] == drv)
                        & (cliffs_df["session_name"] == sess)
                        & (cliffs_df["Stint"] == snt)
                    ]
                    if not cl.empty:
                        c_age = float(cl["Cliff_Age"].iloc[0])
                        ages  = pd.to_numeric(df_drv[_age_col], errors="coerce")
                        j     = (ages - c_age).abs().idxmin()
                        fig_norm.add_trace(go.Scatter(
                            x=[df_drv.loc[j, _age_col]],
                            y=[float(delta.loc[j])],
                            mode="markers",
                            marker=dict(symbol="star", size=14, color="#FFD700",
                                        line=dict(color="#000", width=1)),
                            showlegend=False,
                            hovertemplate=(
                                f"<b>{drv} — tyre cliff</b><br>"
                                f"From age {c_age:.0f}: "
                                f"{cl['Cliff_Slope'].iloc[0]:+.2f} s/lap "
                                f"(was {cl['Base_Slope'].iloc[0]:+.2f} before)"
                                "<extra></extra>"
                            ),
                        ))
            if fig_norm.data:
                fig_norm.add_hline(y=0, line=dict(color="white", width=1, dash="dash"))
                fig_norm.add_hrect(y0=0, y1=999,
                    fillcolor="rgba(225,6,0,0.03)", line_width=0, layer="below")
                fig_norm.add_hrect(y0=-999, y1=0,
                    fillcolor="rgba(0,200,100,0.03)", line_width=0, layer="below")

        theme(fig_norm, 460,
              f"{compound} – Normalised Deg (Δ fuel- & track-corrected vs early-stint baseline, longest clean stint)")
        fig_norm.update_layout(
            xaxis_title="Tyre Age (laps)",
            yaxis_title="Δ Corrected lap time (s)  ↓ better",
            legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1),
            annotations=[dict(
                text="Perturbed laps (yellow / SC / VSC / red) excluded",
                xref="paper", yref="paper", x=1, y=1.02,
                xanchor="right", showarrow=False,
                font=dict(size=9, color=TEXT_DIM),
            )],
        )

        _deg_info = (
            f"Data ({compound}): left bar = degradation rate (s/lap of tyre age) "
            "from a linear fit on each driver's longest valid stint, corrected for "
            "fuel burn AND field-wide track evolution; whiskers show the 95% "
            "confidence interval of the slope. Right line = corrected lap-time "
            "delta from an early-stint baseline (median of the first 3 clean laps) "
            "for each driver's longest clean stint, with a gold star where a deg "
            "cliff was detected. Perturbed laps (yellow/SC/VSC/red flags) are "
            "excluded, and the fits also drop laps run in dirty air (<2 s behind "
            "another car). Why: with fuel, track-grip trends and traffic removed, "
            "what remains is the tyre itself — lower/flatter = less degradation."
        )
        if fig_bar is not None:
            deg_cards.append(card(
                f"Tyre Degradation – {compound}",
                dbc.Row([
                    dbc.Col(dcc.Graph(figure=fig_bar,  config=GFX), md=5),
                    dbc.Col(dcc.Graph(figure=fig_norm, config=GFX), md=7),
                ]),
                info=_deg_info,
            ))
        else:
            deg_cards.append(card(
                f"Tyre Degradation – {compound}",
                dcc.Graph(figure=fig_norm, config=GFX),
                info=_deg_info,
            ))

        # --- (c) Field degradation curve + driver deviation ranking ---
        # Pools EVERY clean stint on this compound (not just each driver's
        # longest), so it borrows statistical strength from the whole field.
        fd = field_deg_curves(fl, compound)
        if fd is not None:
            curve, tcurves, dev = fd["curve"], fd["team_curves"], fd["driver_dev"]

            fig_field = go.Figure()
            # IQR band (q25–q75) behind everything
            fig_field.add_trace(go.Scatter(
                x=curve["_age"], y=curve["q75"], mode="lines",
                line=dict(width=0), showlegend=False, hoverinfo="skip",
            ))
            fig_field.add_trace(go.Scatter(
                x=curve["_age"], y=curve["q25"], mode="lines",
                line=dict(width=0), fill="tonexty",
                fillcolor="rgba(255,255,255,0.09)",
                name="field IQR", showlegend=True, hoverinfo="skip",
            ))
            # Per-team median curves
            for team in sorted(tcurves["Team"].dropna().unique()):
                tg = tcurves[tcurves["Team"] == team].sort_values("_age")
                if len(tg) < 3:
                    continue
                clr = TEAM_COLORS.get(team, "#808080")
                fig_field.add_trace(go.Scatter(
                    x=tg["_age"], y=tg["median"], mode="lines",
                    name=_abbr(team),
                    line=dict(color=clr, width=1.4),
                    hovertemplate=(
                        f"<b>{team}</b><br>"
                        "Tyre age: %{x} laps<br>"
                        "Δ vs stint start: %{y:+.3f} s<extra></extra>"
                    ),
                ))
            # Field median on top
            fig_field.add_trace(go.Scatter(
                x=curve["_age"], y=curve["median"], mode="lines",
                name="FIELD",
                line=dict(color="#FFFFFF", width=3, dash="dot"),
                customdata=curve[["n_stints"]].values,
                hovertemplate=(
                    "<b>Field median</b><br>"
                    "Tyre age: %{x} laps<br>"
                    "Δ vs stint start: %{y:+.3f} s<br>"
                    "Stints contributing: %{customdata[0]}<extra></extra>"
                ),
            ))
            fig_field.add_hline(y=0, line=dict(color="white", width=1, dash="dash"))
            theme(fig_field, 480,
                  f"{compound} – Field Degradation Curve (all clean stints, corrected)")
            fig_field.update_layout(
                xaxis_title="Tyre Age (laps)",
                yaxis_title="Δ Corrected lap time vs stint start (s)",
                legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR,
                            borderwidth=1, font=dict(size=9)),
            )

            fig_dev = None
            if not dev.empty:
                dev_s = dev.sort_values("Avg_Dev_s")
                dev_s["Color"]  = dev_s["Team"].map(TEAM_COLORS).fillna("#808080")
                dev_s["DevFmt"] = dev_s["Avg_Dev_s"].apply(lambda x: f"{x:+.3f}")
                _dmax = max(dev_s["Avg_Dev_s"].abs().max() * 1.35, 0.05)
                fig_dev = go.Figure(go.Bar(
                    y=dev_s["Driver_Short"], x=dev_s["Avg_Dev_s"],
                    orientation="h",
                    marker=dict(color=dev_s["Color"],
                                line=dict(color=GRID_CLR, width=0.5)),
                    customdata=dev_s[["Team", "N_Laps"]].values,
                    hovertemplate=(
                        "<b>%{y}</b>  Team: %{customdata[0]}<br>"
                        "Avg vs field at equal tyre age: %{x:+.3f} s<br>"
                        "Clean laps used: %{customdata[1]}<extra></extra>"
                    ),
                    text=dev_s["DevFmt"], textposition="outside",
                    textfont=dict(size=10, color=TEXT_MAIN),
                ))
                fig_dev.add_vline(x=0, line=dict(color="white", width=1, dash="dash"))
                ht_dev = max(300, 24 * len(dev_s) + 80)
                theme(fig_dev, ht_dev, f"{compound} – Deg vs Field")
                fig_dev.update_layout(
                    xaxis=dict(title="s vs field median  ·  negative = degrades less",
                               range=[-_dmax, _dmax],
                               gridcolor=GRID_CLR, zeroline=False),
                    yaxis=dict(gridcolor=GRID_CLR, zeroline=False),
                    bargap=0.25, showlegend=False,
                )

            _field_info = (
                f"Data ({compound}): every clean stint of ≥5 laps contributes its "
                "corrected lap-time delta vs its own early-stint baseline; the "
                "white dotted line is the field median at each tyre age, the grey "
                "band the 25–75% spread, coloured lines the per-team medians. "
                "Right bar (when enough data): each driver's average gap to the "
                "field curve at equal tyre age — negative = manages tyres better "
                "than the field. Perturbed laps and laps in dirty air (<2 s "
                "behind another car) are excluded. "
                "Why: pooling all stints is far more robust than "
                "any single-stint fit, and deviations from the pooled curve are "
                "the cleanest tyre-management signal this data can give."
            )
            deg_cards.append(card(
                f"Field Degradation – {compound}",
                dbc.Row([
                    dbc.Col(dcc.Graph(figure=fig_field, config=GFX),
                            md=7 if fig_dev is not None else 12),
                ] + ([dbc.Col(dcc.Graph(figure=fig_dev, config=GFX), md=5)]
                     if fig_dev is not None else [])),
                info=_field_info,
            ))

    # 3b. Cliff Map — all detected cliffs across compounds in one view
    if not cliffs_df.empty:
        cm = cliffs_df.copy()
        cm["Extra"]   = cm["Cliff_Slope"] - cm["Base_Slope"]
        cm["SessLbl"] = cm["session_name"].astype(str).str.split("_").str[0]
        fig_cliff = go.Figure()
        for comp in COMPOUNDS:
            sub = cm[cm["Compound"] == comp]
            if sub.empty:
                continue
            fig_cliff.add_trace(go.Scatter(
                x=sub["Cliff_Age"], y=sub["Extra"],
                mode="markers+text",
                name=comp,
                text=sub["Driver_Short"],
                textposition="top center",
                textfont=dict(size=9, color=TEXT_DIM),
                marker=dict(
                    size=10,
                    color=COMPOUND_COLORS.get(comp, "#808080"),
                    line=dict(color="#000", width=1),
                    symbol="star",
                ),
                customdata=sub[["Driver_Short", "Team", "SessLbl",
                                "Base_Slope", "Cliff_Slope", "N_Laps"]].values,
                hovertemplate=(
                    "<b>%{customdata[0]}</b> · %{customdata[1]} "
                    "(%{customdata[2]})<br>"
                    "Cliff from tyre age %{x:.0f} laps<br>"
                    "Deg before: %{customdata[3]:+.3f} s/lap → after: "
                    "%{customdata[4]:+.3f} s/lap<br>"
                    "Stint length: %{customdata[5]} laps<extra></extra>"
                ),
            ))
        theme(fig_cliff, 440, "Tyre Cliff Map — every detected cliff")
        fig_cliff.update_layout(
            xaxis_title="Tyre age at cliff onset (laps)",
            yaxis_title="Extra deg after cliff (s/lap on top of base rate)",
            legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR,
                        borderwidth=1),
        )
        cliff_body = dcc.Graph(figure=fig_cliff, config=GFX)
    else:
        cliff_body = html.P(
            "No degradation cliffs detected in the loaded sessions "
            "(needs clean stints of ≥10 laps with a clear late break in the "
            "deg trend).", style={"color": TEXT_DIM})
    cliff_card = card(
        "Tyre Cliff Detection",
        cliff_body,
        info=("Data: every clean stint of ≥10 laps is tested with a "
              "two-segment fit on corrected lap times; a star appears when "
              "the late-stint deg rate breaks sharply upward from the earlier "
              "trend (statistically better than a straight line, ≥+0.10 s/lap "
              "extra). Position on the chart: further right = the tyre lasted "
              "longer before falling off; higher = the harder it fell. Why: "
              "the cliff, not the average deg rate, is what forces a pit stop "
              "— knowing at what age each compound cliffs at this circuit is "
              "the single most valuable strategy number."),
    )

    # 3c. Compound pace offsets (race sessions only — comparable fuel)
    co = compound_offsets(fl)
    if not co.empty:
        err_plus  = (co["Q75"] - co["Offset_s"]).clip(lower=0)
        err_minus = (co["Offset_s"] - co["Q25"]).clip(lower=0)
        fig_off = go.Figure(go.Bar(
            x=co["Pair"], y=co["Offset_s"],
            marker=dict(
                color=[COMPOUND_COLORS.get(p.split(" → ")[1], "#808080")
                       for p in co["Pair"]],
                line=dict(color=GRID_CLR, width=0.5),
            ),
            error_y=dict(type="data", array=err_plus, arrayminus=err_minus,
                         color="rgba(255,255,255,0.6)", thickness=1.2, width=5),
            customdata=co[["N_Drivers", "Q25", "Q75"]].values,
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Median offset: %{y:+.2f} s/lap (+ = second compound slower)"
                "<br>Driver spread (IQR): %{customdata[1]:+.2f} … "
                "%{customdata[2]:+.2f} s<br>"
                "Drivers compared: %{customdata[0]}<extra></extra>"
            ),
            text=co["Offset_s"].apply(lambda v: f"{v:+.2f}s"),
            textposition="outside",
            textfont=dict(size=11, color=TEXT_MAIN),
        ))
        fig_off.add_hline(y=0, line=dict(color="white", width=1, dash="dash"))
        theme(fig_off, 400, "Compound Pace Offsets — race laps, corrected")
        fig_off.update_layout(
            xaxis_title="Compound pair",
            yaxis_title="s/lap  ·  positive = second compound slower",
            showlegend=False, bargap=0.45,
        )
        _off_season, _off_meeting = _laps_event(fl)
        offset_body = html.Div([
            _allocation_chips(_off_season, _off_meeting) or html.Div(),
            dcc.Graph(figure=fig_off, config=GFX),
        ])
    else:
        offset_body = html.P(
            "Compound offsets need race or sprint laps (practice fuel loads "
            "are unknown, which would contaminate the comparison). Load a "
            "race session in the Data tab.", style={"color": TEXT_DIM})
    offset_card = card(
        "Compound Pace Offsets",
        offset_body,
        info=("Data: race/sprint laps only, tyre age ≤ 10, fuel- and "
              "track-corrected. Each driver who ran both compounds "
              "contributes their personal pace difference (which cancels out "
              "car and driver speed); the bar is the field median, the "
              "whiskers the driver-to-driver spread. Why: the compound offset "
              "sets the strategy crossover — how many laps of tyre advantage "
              "a fresh soft buys over a hard determines whether an extra stop "
              "pays for itself."),
    )

    # 4. Stint Lap Inspector
    avail_drivers = sorted(fl["Driver_Short"].dropna().unique())
    first_driver  = avail_drivers[0] if avail_drivers else None

    stint_inspector = html.Div([
        html.P(
            "Select a driver then a pre-ranked stint to inspect its laps.",
            style={"color": TEXT_DIM, "fontSize": "0.8rem", "marginBottom": "10px"},
        ),
        dbc.Row([
            dbc.Col([
                html.Label("Driver",
                           style={"color": TEXT_DIM, "fontSize": "0.75rem",
                                  "letterSpacing": "1px"}),
                dcc.Dropdown(
                    id="stint-insp-driver",
                    options=[{"label": d, "value": d} for d in avail_drivers],
                    value=first_driver,
                    clearable=False,
                    style={"backgroundColor": "#111", "fontSize": "0.82rem"},
                ),
            ], md=3),
            dbc.Col([
                html.Label("Stint (ranked)",
                           style={"color": TEXT_DIM, "fontSize": "0.75rem",
                                  "letterSpacing": "1px"}),
                dcc.Dropdown(
                    id="stint-insp-key",
                    options=[],
                    value=None,
                    clearable=False,
                    style={"backgroundColor": "#111", "fontSize": "0.82rem"},
                ),
            ], md=9),
        ], className="mb-3"),
        html.Div(id="stint-insp-table"),
    ])

    tyre_usage_fig = _tyre_history_chart(fl)

    return html.Div([
        card("Lap Time Evolution – All Laps", evo_layout,
             info=("Data: every lap (valid or not) for the selected session, one line "
                   "per driver, markers tinted by compound, with track-flag periods "
                   "shaded behind (yellow / SC / VSC / red). Why: the full story of a "
                   "session — stint lengths, pit stops, degradation and how "
                   "interruptions reshaped the running order.")),
        *violin_cards,
        *deg_cards,
        cliff_card,
        offset_card,
        card(
            "Tyre Compound Usage — Current Meeting",
            dcc.Graph(figure=tyre_usage_fig, config=GFX)
            if tyre_usage_fig.data else
            html.P("No compound data available.", style={"color": TEXT_DIM}),
            info=("Data: number of valid laps run on each compound, stacked per "
                  "session, for the currently loaded meeting. Why: shows how teams "
                  "spread their tyre allocation across the weekend and which "
                  "compounds saw real running."),
        ),
        card("Stint Lap Inspector", stint_inspector,
             info=("Data: the individual laps of any stint, picked from a "
                   "dropdown that pre-ranks each driver's stints by pace — "
                   "times, tyre age, flags and validity per lap. Why: the "
                   "drill-down behind the stint aggregates above; use it to "
                   "check what a suspicious deg rate or stint average is "
                   "actually made of.")),
    ])
