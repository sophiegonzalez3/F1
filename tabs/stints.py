"""
STINTS tab — stint aggregation, degradation, cliffs, compound offsets,
plus the interactive Lap Evolution overlay and per-driver Stint Inspector.
Extracted from app.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import html, dcc, dash_table, callback, Input, Output, State
import dash_bootstrap_components as dbc

import f1lib.state as state
from f1lib.components import (
    theme, card, kpi, GFX, TABLE_STYLE, styled_table,
    badge as _badge, abbr as _abbr, hex_to_rgba as _hex_to_rgba,
)
from f1lib.glossary import gloss
from f1lib.config import (
    TEAM_COLORS, COMPOUND_COLORS,
    ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
    MIN_LAPS_MEDIUM,
)
from f1lib.processing import (
    field_deg_curves, detect_stint_cliffs, compound_offsets, format_lap_time,
)
from f1lib.figures import _add_flag_bands, _add_rain_bands, _lap_evolution_fig
from f1lib.tyre_allocations import _allocation_chips, _laps_event

# mirror the mutable data state so bare `laps`, `stints`, SESSIONS, DRIVERS,
# TEAMS, COMPOUNDS reads inside the moved bodies keep working across reloads
state.register(globals())

# Max slope standard error (s/lap) for a per-stint degradation-rate fit to be
# trusted on the Degradation Rate bars. Above this the fit is noise — a real
# deg slope is pinned down far more tightly — so it is dropped rather than
# plotted as a physically implausible outlier that blows the axis wide open.
MAX_DEG_SE = 0.5

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

    _fb_col = (stints["Fallback_Stint"] if "Fallback_Stint" in stints.columns
               else False)
    drv_stints = stints[
        (stints["Driver_Short"] == driver)
        & stints["session_name"].isin(ss)
        & stints["Team"].isin(st)
        & (stints["Valid_Stint"] | _fb_col)
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
        fb_tag   = ("  ⚠ fallback" if bool(row.get("Fallback_Stint", False))
                    else "")
        opts.append({
            "label": f"{label}  {icon}{compound}  {pace_fmt}  ({laps_n} laps, {sess}){fb_tag}",
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


# ── Field Degradation Curves — full-screen modal toggle ──────
@callback(
    Output("field-curves-modal", "is_open"),
    Input("field-curves-enlarge", "n_clicks"),
    Input("field-curves-close",   "n_clicks"),
    State("field-curves-modal",   "is_open"),
    prevent_initial_call=True,
)
def toggle_field_curves_modal(_open_click, _close_click, is_open):
    return not is_open


@callback(
    Output("stint-insp-table", "data"),
    Output("stint-insp-table", "columns"),
    Output("stint-insp-msg",   "children"),
    Input("stint-insp-driver", "value"),
    Input("stint-insp-key",    "value"),
)
def render_stint_table(driver, stint_key):
    # The table is mounted once (see layout); here we only feed it data/columns
    # and surface any empty-state text through the sibling message Div.
    if not driver or not stint_key:
        return [], [], html.P("Select a driver and stint key.", style={"color": TEXT_DIM})
    sub = laps[
        (laps["Driver_Short"] == driver) & (laps["Stint_key"] == stint_key)
    ].sort_values("LapNo")
    if sub.empty:
        return [], [], html.P("No laps found for this selection.", style={"color": TEXT_DIM})
    cols_want  = ["Stint_key", "LapNo", "LapTime_s", "Compound", "TyreAge", "LapInStint"]
    cols_avail = [c for c in cols_want if c in sub.columns]
    sub = sub[cols_avail].copy()
    if "LapTime_s" in sub.columns:
        pos = sub.columns.get_loc("LapTime_s") + 1
        sub.insert(pos, "LapTime", sub["LapTime_s"].apply(format_lap_time))
    return (
        sub.to_dict("records"),
        [{"name": c, "id": c} for c in sub.columns],
        "",
    )


def _best_stint_laps(fl, stints_df):
    """Return laps that belong to the best valid stint per driver x compound
    (session-agnostic: Stint_Rank_Across_Sessions == 1), plus — where a
    driver x compound has NO valid stint at all — the laps of its flagged
    Fallback_Stint (longest stint of ≥5 clean laps), marked _fallback=True
    so callers can render them visibly second-class.
    Falls back to all valid laps if stints_df is empty or ranking unavailable.

    Note: analyze_stints() does not carry Stint_key, so we match on the
    three component columns (session_name, Driver_Short, Stint) instead.
    """
    if stints_df is None or stints_df.empty or "Stint_Rank_Across_Sessions" not in stints_df.columns:
        out = fl[fl["ValidLap"]].copy()
        out["_fallback"] = False
        return out

    fb = (stints_df["Fallback_Stint"]
          if "Fallback_Stint" in stints_df.columns else False)
    sel = stints_df[
        (stints_df["Valid_Stint"]
         & (stints_df["Stint_Rank_Across_Sessions"] == 1)) | fb
    ][["session_name", "Driver_Short", "Stint", "Valid_Stint"]].drop_duplicates()
    sel["_fallback"] = ~sel.pop("Valid_Stint")

    # Build a merge key on the laps side then filter
    fl_valid = fl[fl["ValidLap"]].copy()
    merged = fl_valid.merge(
        sel.assign(_keep=True),
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
        "(Stint_Rank_Across_Sessions = 1). Hollow violins marked ✱ are "
        "FALLBACK stints: the driver had no stint reaching this compound's "
        "lap minimum, so their longest run of ≥5 clean laps stands in — "
        "read those with care.",
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
                is_fb = bool(df_drv.get("_fallback", pd.Series(False)).any())
                lap_count = len(df_drv)
                ymax      = df_drv["LapTime_s"].max()
                ymin      = df_drv["LapTime_s"].min()
                margin    = (ymax - ymin) * 0.2 if ymax != ymin else 0.5
                side      = "negative" if i == 0 else "positive"
                pointpos  = -0.8      if i == 0 else 0.8
                # Fallback stints render visibly second-class: hollow body
                # (no fill), open-cross points, dimmed trace.
                fig_v.add_trace(go.Violin(
                    x=[team] * lap_count,
                    y=df_drv["LapTime_s"],
                    legendgroup=driver,
                    scalegroup=team,
                    name=driver + (" ✱" if is_fb else ""),
                    side=side,
                    pointpos=pointpos,
                    line_color=clr,
                    fillcolor="rgba(0,0,0,0)" if is_fb else rgba,
                    opacity=0.6 if is_fb else 1.0,
                    marker=dict(symbol="x-thin-open" if is_fb else "circle"),
                    meanline_visible=True,
                    points="all",
                    jitter=0.05,
                    scalemode="count",
                    showlegend=True,
                    hovertext=(f"{driver} — FALLBACK stint (below the "
                               "compound's valid-lap minimum)") if is_fb else None,
                ))
                anns.append(dict(
                    x=team, y=ymax + margin / 2,
                    text=f"{driver} ({lap_count}{'✱' if is_fb else ''})",
                    showarrow=False,
                    xshift=-25 if side == "negative" else 25,
                    yshift=10,
                    font=dict(size=11, color=clr),
                ))
        theme(fig_v, 650)
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
                  "pair, point count shown). Drivers with no valid stint on this "
                  "compound contribute their longest ≥5-clean-lap run instead, "
                  "drawn hollow with ✱ and x-shaped points — a flagged fallback, "
                  "not a valid stint. Why: compares teams on equal tyre, "
                  "showing both typical pace (the body) and consistency (the spread)."),
        ))

    # 3. Tyre Degradation — the per-compound charts are collected here and then
    #    laid out three-across in a handful of merged cards (one row of SOFT /
    #    MEDIUM / HARD per view) rather than a separate card per compound:
    #       • deg_bar_figs   – per-driver degradation RATE (longest valid stint,
    #                          fuel- & track-corrected, ±95% CI whiskers)
    #       • field_cur_data – pooled field degradation curve inputs
    #       • field_dev_figs – per-driver deg vs the field curve
    valid_stints = fs[fs["Valid_Stint"]].copy() if not fs.empty else pd.DataFrame()
    # valid + flagged fallbacks — the deg-rate bars accept a driver's fallback
    # stint (hatched) where they have no valid stint on that compound
    if not fs.empty and "Fallback_Stint" in fs.columns:
        usable_stints = fs[fs["Valid_Stint"] | fs["Fallback_Stint"]].copy()
    else:
        usable_stints = valid_stints.copy()
        if not usable_stints.empty:
            usable_stints["Fallback_Stint"] = False

    # Cliff detection across all compounds (feeds the dedicated Cliff card).
    cliffs_df = detect_stint_cliffs(fl)

    deg_bar_figs:   dict[str, go.Figure] = {}
    field_cur_data: dict[str, dict]      = {}
    field_dev_figs: dict[str, go.Figure] = {}

    for compound in COMPOUNDS:
        comp_stints = (
            usable_stints[usable_stints["Compound"] == compound].copy()
            if not usable_stints.empty else pd.DataFrame()
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
            # Drop fits too imprecise to plot: short/noisy stints produce
            # slope estimates with a huge standard error (e.g. SE 1–6 s/lap)
            # and physically implausible rates (−3.7 or +2.3 s/lap) that are
            # indistinguishable from noise and stretch the axis so the real,
            # tightly-fitted bars become unreadable. A real deg slope is
            # pinned down far better than this. NaN SE (can't judge) is kept.
            if "Stint_Deg_SE" in df_deg.columns:
                _se = pd.to_numeric(df_deg["Stint_Deg_SE"], errors="coerce")
                df_deg = df_deg[~(_se > MAX_DEG_SE)].copy()

        if not df_deg.empty:
            df_deg = df_deg.sort_values("Stint_Deg_Rate", ascending=False)
            df_deg["Color"]   = df_deg["Team"].map(TEAM_COLORS).fillna("#808080")
            df_deg["DegFmt"]  = df_deg["Stint_Deg_Rate"].apply(
                lambda x: f"+{x:.3f}" if x >= 0 else f"{x:.3f}"
            )
            _has_se = "Stint_Deg_SE" in df_deg.columns
            df_deg["CI95"] = (
                (1.96 * pd.to_numeric(df_deg["Stint_Deg_SE"], errors="coerce"))
                if _has_se else np.nan
            )
            df_deg["CIFmt"] = df_deg["CI95"].apply(
                lambda x: f"±{x:.3f}" if pd.notna(x) else "±n/a"
            )
            df_deg["R2Fmt"] = df_deg["Stint_Deg_R2"].apply(
                lambda x: f"R²={x:.2f}" if pd.notna(x) else "R²=n/a"
            )
            # Fit the x-axis tightly to the bar VALUES instead of a symmetric
            # ±max range, which left the mostly-unused negative half empty. The
            # range is driven by the deg rates themselves (not rate ± CI): a few
            # short, noisy stints have huge slope SEs whose whiskers would
            # otherwise blow the axis wide open. Keep 0 in view so the green/red
            # zones + zeroline still read, and leave headroom past the bar tips
            # for the outside value labels (more on the positive side).
            _rate    = df_deg["Stint_Deg_Rate"].astype(float)
            _lo_data = float(_rate.min())
            _hi_data = float(_rate.max())
            _lo   = min(0.0, _lo_data)
            _hi   = max(0.0, _hi_data)
            _span = (_hi - _lo) or 0.05
            x_lo  = _lo - (_span * 0.12 if _lo_data < 0 else _span * 0.04)
            x_hi  = _hi + _span * 0.20
            # Clip the CI whiskers so an outlier SE can't overrun the plot.
            _ci      = df_deg["CI95"].fillna(0).astype(float)
            _ci_disp = np.clip(
                np.minimum.reduce([_ci.values,
                                   (x_hi - _rate.values),
                                   (_rate.values - x_lo)]),
                0.0, None,
            )

            # Fallback stints (no valid stint for that driver on this
            # compound) get a hatched texture so they read as second-class.
            _fb = (df_deg["Fallback_Stint"].fillna(False).astype(bool)
                   if "Fallback_Stint" in df_deg.columns
                   else pd.Series(False, index=df_deg.index))
            df_deg["FbTag"] = np.where(
                _fb, "<br>⚠ FALLBACK stint — below the compound's valid minimum", "")
            fig_bar = go.Figure(go.Bar(
                y=df_deg["Driver_Short"],
                x=df_deg["Stint_Deg_Rate"],
                orientation="h",
                marker=dict(
                    color=df_deg["Color"],
                    line=dict(color=GRID_CLR, width=0.5),
                    pattern=dict(
                        shape=["/" if f else "" for f in _fb],
                        fgcolor="rgba(13,13,13,0.65)",
                        size=5, solidity=0.4,
                    ),
                ),
                error_x=dict(
                    type="data",
                    array=_ci_disp,
                    color="rgba(255,255,255,0.55)",
                    thickness=1.2, width=4,
                ) if _has_se else None,
                customdata=df_deg[["Team", "DegFmt", "CIFmt", "R2Fmt",
                                   "Stint_Laps_Count", "session_name",
                                   "FbTag"]].values,
                hovertemplate=(
                    "<b>%{y}</b>  Team: %{customdata[0]}<br>"
                    "Deg rate: %{customdata[1]} %{customdata[2]} s/lap (95% CI)<br>"
                    "%{customdata[3]}<br>"
                    "Laps in stint: %{customdata[4]}<br>"
                    "Session: %{customdata[5]}"
                    "%{customdata[6]}<extra></extra>"
                ),
                text=df_deg["DegFmt"],
                textposition="outside",
                textfont=dict(size=10, color=TEXT_MAIN),
            ))
            fig_bar.add_vline(x=0, line=dict(color="white", width=1, dash="dash"))
            fig_bar.add_vrect(x0=x_lo, x1=0,
                fillcolor="rgba(0,200,100,0.05)", line_width=0, layer="below")
            fig_bar.add_vrect(x0=0, x1=x_hi,
                fillcolor="rgba(225,6,0,0.05)", line_width=0, layer="below")
            ht = max(300, 28 * len(df_deg) + 80)
            theme(fig_bar, ht, compound)
            fig_bar.update_layout(
                xaxis=dict(
                    title="s/lap of tyre age",
                    range=[x_lo, x_hi],
                    gridcolor=GRID_CLR, zeroline=False,
                ),
                yaxis=dict(gridcolor=GRID_CLR, zeroline=False, autorange="reversed"),
                bargap=0.25, showlegend=False,
                margin=dict(l=8, r=8, t=44, b=44),
            )
            deg_bar_figs[compound] = fig_bar

        # --- (b) Field degradation: pooled curve inputs + deg-vs-field bar ---
        # Pools EVERY clean stint on this compound (not just each driver's
        # longest), so it borrows statistical strength from the whole field.
        # The curves themselves are drawn together, three-across, in a single
        # subplot figure after the loop (so the team legend appears once); here
        # we only keep the data and build the compact per-driver deviation bar.
        fd = field_deg_curves(fl, compound)
        if fd is None:
            continue
        field_cur_data[compound] = fd

        dev = fd["driver_dev"]
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
            fig_dev.add_vrect(x0=-_dmax, x1=0,
                fillcolor="rgba(0,200,100,0.05)", line_width=0, layer="below")
            fig_dev.add_vrect(x0=0, x1=_dmax,
                fillcolor="rgba(225,6,0,0.05)", line_width=0, layer="below")
            ht_dev = max(300, 24 * len(dev_s) + 80)
            theme(fig_dev, ht_dev, compound)
            fig_dev.update_layout(
                xaxis=dict(title="s vs field median",
                           range=[-_dmax, _dmax],
                           gridcolor=GRID_CLR, zeroline=False),
                yaxis=dict(gridcolor=GRID_CLR, zeroline=False, autorange="reversed"),
                bargap=0.25, showlegend=False,
                margin=dict(l=8, r=8, t=44, b=44),
            )
            field_dev_figs[compound] = fig_dev

    # ── Assemble the merged degradation cards (SOFT / MEDIUM / HARD across) ──
    def _deg_columns(figs: dict, empty_msg: str):
        """One dbc.Row with a column per compound; a note where data is thin."""
        cols = []
        for comp in COMPOUNDS:
            fig = figs.get(comp)
            body = (
                dcc.Graph(figure=fig, config=GFX) if fig is not None
                else html.Div(
                    [html.Div(comp, style={"fontWeight": "700",
                                           "color": COMPOUND_COLORS.get(comp, TEXT_DIM)}),
                     html.Div(empty_msg, style={"fontSize": "0.72rem"})],
                    style={"color": TEXT_DIM, "textAlign": "center",
                           "padding": "60px 8px"},
                )
            )
            cols.append(dbc.Col(body, md=4))
        return dbc.Row(cols)

    # Equalise heights so the three plots line up neatly side by side.
    if deg_bar_figs:
        _h = max(f.layout.height for f in deg_bar_figs.values())
        for f in deg_bar_figs.values():
            f.update_layout(height=_h)
    if field_dev_figs:
        _h = max(f.layout.height for f in field_dev_figs.values())
        for f in field_dev_figs.values():
            f.update_layout(height=_h)

    # (a) Merged degradation-rate bars
    _deg_plain = None
    if not valid_stints.empty and "Stint_Deg_Rate" in valid_stints.columns:
        _med = (valid_stints.dropna(subset=["Stint_Deg_Rate"])
                .groupby("Compound")["Stint_Deg_Rate"].median())
        if not _med.empty:
            _deg_plain = (
                "Every tyre slowly loses grip the longer it runs — that's "
                "'degradation', measured as seconds lost per lap. Of the tyres "
                f"used here the {str(_med.idxmax()).title()} wears fastest, so "
                "cars on it fade soonest and have to pit earlier.")
    deg_rate_card = card(
        ["Tyre ", *gloss("degradation", "Degradation"), " Rate — by ",
         *gloss("compound", "Compound")],
        _deg_columns(deg_bar_figs, "no stint of ≥5 clean laps on this compound"),
        info=("Data: degradation rate (s/lap of tyre age) from a linear fit on "
              "each driver's longest valid stint per compound, corrected for "
              "fuel burn AND field-wide track evolution; whiskers = 95% "
              "confidence interval of the fitted slope. Bars are coloured by "
              "team and sorted worst→best. Hatched bars are FALLBACK stints: "
              "the driver had no stint reaching this compound's lap minimum, "
              "so their longest ≥5-clean-lap run stands in — treat those fits "
              "as indicative only. The green half is negative "
              "(tyre gains as it ages / holds on), the red half positive. Why: "
              "with fuel and track-grip trends removed, what remains is the tyre "
              "itself — lower/flatter = less degradation."),
        plain=_deg_plain,
    )

    # (b) Merged field degradation curves — one subplot figure, shared legend
    fig_curves = None
    cur_comps = [c for c in COMPOUNDS if c in field_cur_data]
    if cur_comps:
        fig_curves = make_subplots(
            rows=1, cols=len(cur_comps), shared_yaxes=True,
            subplot_titles=cur_comps, horizontal_spacing=0.035,
        )
        _seen: set[str] = set()   # each legend entry appears once across subplots

        def _show(key: str) -> bool:
            if key in _seen:
                return False
            _seen.add(key)
            return True

        for j, comp in enumerate(cur_comps, start=1):
            fd = field_cur_data[comp]
            curve, tcurves = fd["curve"], fd["team_curves"]
            # IQR band (q25–q75) behind everything
            fig_curves.add_trace(go.Scatter(
                x=curve["_age"], y=curve["q75"], mode="lines",
                line=dict(width=0), showlegend=False, hoverinfo="skip",
            ), row=1, col=j)
            fig_curves.add_trace(go.Scatter(
                x=curve["_age"], y=curve["q25"], mode="lines",
                line=dict(width=0), fill="tonexty",
                fillcolor="rgba(255,255,255,0.09)",
                name="field IQR", legendgroup="field IQR",
                showlegend=_show("field IQR"), hoverinfo="skip",
            ), row=1, col=j)
            # Per-team median curves
            for team in sorted(tcurves["Team"].dropna().unique()):
                tg = tcurves[tcurves["Team"] == team].sort_values("_age")
                if len(tg) < 3:
                    continue
                clr = TEAM_COLORS.get(team, "#808080")
                fig_curves.add_trace(go.Scatter(
                    x=tg["_age"], y=tg["median"], mode="lines",
                    name=_abbr(team), legendgroup=team, showlegend=_show(team),
                    line=dict(color=clr, width=1.4),
                    hovertemplate=(
                        f"<b>{team}</b> · {comp}<br>"
                        "Tyre age: %{x} laps<br>"
                        "Δ vs stint start: %{y:+.3f} s<extra></extra>"
                    ),
                ), row=1, col=j)
            # Field median on top
            fig_curves.add_trace(go.Scatter(
                x=curve["_age"], y=curve["median"], mode="lines",
                name="FIELD", legendgroup="FIELD", showlegend=_show("FIELD"),
                line=dict(color="#FFFFFF", width=3, dash="dot"),
                customdata=curve[["n_stints"]].values,
                hovertemplate=(
                    f"<b>Field median</b> · {comp}<br>"
                    "Tyre age: %{x} laps<br>"
                    "Δ vs stint start: %{y:+.3f} s<br>"
                    "Stints contributing: %{customdata[0]}<extra></extra>"
                ),
            ), row=1, col=j)
            fig_curves.add_hline(y=0, line=dict(color="white", width=1, dash="dash"),
                                 row=1, col=j)
            fig_curves.update_xaxes(title_text="Tyre Age (laps)", row=1, col=j,
                                    gridcolor=GRID_CLR, zeroline=False)
        theme(fig_curves, 470)
        fig_curves.update_yaxes(title_text="Δ Corrected lap time vs stint start (s)",
                                row=1, col=1, gridcolor=GRID_CLR, zeroline=False)
        fig_curves.update_layout(
            legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR,
                        borderwidth=1, font=dict(size=9)),
            margin=dict(l=8, r=8, t=44, b=44),
        )

    if fig_curves is not None:
        # A taller copy (with the modebar enabled) opens in a full-screen modal
        # so the three side-by-side curves can be read clearly when needed.
        fig_curves_big = go.Figure(fig_curves)
        fig_curves_big.update_layout(height=None, margin=dict(l=40, r=20, t=40, b=50))
        curve_body = html.Div([
            html.Div(
                dbc.Button("⤢  Open in big window", id="field-curves-enlarge",
                           size="sm", color="secondary", outline=True,
                           n_clicks=0, style={"fontSize": "0.72rem"}),
                style={"textAlign": "right", "marginBottom": "4px"},
            ),
            dcc.Graph(figure=fig_curves, config=GFX),
            dbc.Modal([
                dbc.ModalHeader(dbc.ModalTitle(
                    "Field Degradation Curves — by Compound")),
                dbc.ModalBody(
                    dcc.Graph(
                        figure=fig_curves_big,
                        config={"displayModeBar": True, "displaylogo": False},
                        style={"height": "82vh"},
                    ),
                    style={"padding": "8px"},
                ),
                dbc.ModalFooter(
                    dbc.Button("Close", id="field-curves-close",
                               size="sm", color="secondary", n_clicks=0)),
            ], id="field-curves-modal", is_open=False, fullscreen=True,
               scrollable=True),
        ])
    else:
        curve_body = html.P("Not enough clean stints to build a field curve for "
                            "the loaded sessions.", style={"color": TEXT_DIM})

    field_curve_card = card(
        "Field Degradation Curves — by Compound",
        curve_body,
        info=("Data: every clean stint of ≥5 laps contributes its corrected "
              "lap-time delta vs its own early-stint baseline; the white dotted "
              "line is the field median at each tyre age, the grey band the "
              "25–75% spread, coloured lines the per-team medians. Perturbed "
              "laps and laps in dirty air (<2 s behind another car) are "
              "excluded. Why: pooling all stints is far more robust than any "
              "single-stint fit. Tip: use “Open in big window” for a "
              "full-screen, zoomable view."),
    )

    # (c) Merged deg-vs-field bars
    field_dev_card = card(
        "Degradation vs the Field — by Compound",
        _deg_columns(field_dev_figs, "not enough clean laps to rank"),
        info=("Data: each driver's average gap to the pooled field degradation "
              "curve at equal tyre age (from the curves above). Negative "
              "(green) = the tyre degrades LESS than the field average, i.e. "
              "better tyre management; positive (red) = worse. Perturbed and "
              "dirty-air laps excluded. Why: deviation from the pooled curve is "
              "the cleanest tyre-management signal this data can give."),
    )

    deg_cards = [deg_rate_card, field_curve_card, field_dev_card]

    # 3b. Cliff timeline — each detected cliff as a tyre-life bar. The old
    #     scatter (extra-deg vs cliff-age) left a big empty canvas around one or
    #     two points; a horizontal "plateau → over the cliff" bar per cliff
    #     stays legible no matter how few cliffs there are and reads directly as
    #     "how long the tyre held, then how hard it fell".
    if not cliffs_df.empty:
        cm = cliffs_df.copy()
        cm["Extra"]   = (cm["Cliff_Slope"] - cm["Base_Slope"]).round(3)
        cm["SessLbl"] = cm["session_name"].astype(str).str.split("_").str[0]
        cm["Tail_Laps"] = pd.to_numeric(cm["Tail_Laps"], errors="coerce").fillna(1)
        # longest-lasting tyres at the top
        cm = cm.sort_values("Cliff_Age", ascending=False).reset_index(drop=True)
        ypos   = list(range(len(cm)))
        labels = [f"{r.Driver_Short}  ·  {r.Compound}"
                  + (f"  ({r.SessLbl})" if cm["SessLbl"].nunique() > 1 else "")
                  for r in cm.itertuples()]
        plateau_clr = [_hex_to_rgba(COMPOUND_COLORS.get(c, "#808080"), 0.45)
                       for c in cm["Compound"]]
        cd = cm[["Driver_Short", "Team", "SessLbl", "Base_Slope",
                 "Cliff_Slope", "Extra", "N_Laps"]].values

        fig_cliff = go.Figure()
        # Plateau: tyre age 0 → cliff onset (compound-tinted)
        fig_cliff.add_trace(go.Bar(
            y=ypos, x=cm["Cliff_Age"], base=0, orientation="h",
            marker=dict(color=plateau_clr,
                        line=dict(color=GRID_CLR, width=0.5)),
            name="Plateau (by compound)",
            customdata=cd,
            hovertemplate=(
                "<b>%{customdata[0]}</b> · %{customdata[1]} "
                "(%{customdata[2]})<br>"
                "Plateau: tyre age 0 → %{x:.0f} laps<br>"
                "Base deg: %{customdata[3]:+.3f} s/lap<extra></extra>"
            ),
        ))
        # Over the cliff: cliff onset → end of the observed stint
        fig_cliff.add_trace(go.Bar(
            y=ypos, x=cm["Tail_Laps"], base=cm["Cliff_Age"], orientation="h",
            marker=dict(color="#E10600", line=dict(color="#000", width=0.5)),
            name="Over the cliff",
            text=[f"+{e:.2f} s/lap" for e in cm["Extra"]],
            textposition="outside", textfont=dict(size=10, color="#E10600"),
            customdata=cd,
            hovertemplate=(
                "<b>%{customdata[0]}</b> · %{customdata[1]} "
                "(%{customdata[2]})<br>"
                "Cliff from tyre age %{base:.0f} laps<br>"
                "Deg: %{customdata[3]:+.3f} → %{customdata[4]:+.3f} s/lap "
                "(+%{customdata[5]:.2f} extra)<br>"
                "Stint length: %{customdata[6]} laps<extra></extra>"
            ),
        ))
        # Cliff-onset marker
        fig_cliff.add_trace(go.Scatter(
            y=ypos, x=cm["Cliff_Age"], mode="markers",
            marker=dict(symbol="diamond", size=9, color="#FFD700",
                        line=dict(color="#000", width=1)),
            showlegend=False, hoverinfo="skip",
        ))
        ht = max(220, 46 * len(cm) + 90)
        theme(fig_cliff, ht)
        fig_cliff.update_layout(
            barmode="overlay",
            xaxis=dict(title="Tyre age (laps)", gridcolor=GRID_CLR, zeroline=False),
            yaxis=dict(tickvals=ypos, ticktext=labels, autorange="reversed",
                       gridcolor=GRID_CLR, zeroline=False),
            bargap=0.35,
            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                        xanchor="right", x=1, bgcolor="rgba(0,0,0,0)"),
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
              "two-segment fit on corrected lap times; a cliff is flagged when "
              "the late-stint deg rate breaks sharply upward from the earlier "
              "trend (statistically better than a straight line, ≥+0.10 s/lap "
              "extra). Each bar is one cliff: the compound-tinted part is the "
              "tyre's plateau (age 0 → the gold cliff-onset diamond), the red "
              "part the laps run after it fell off, labelled with the extra "
              "deg. Why: the cliff, not the average deg rate, is what forces a "
              "pit stop — knowing at what age each compound cliffs at this "
              "circuit is the single most valuable strategy number."),
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
        theme(fig_off, 400)
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
        info=("Data: race/sprint laps only, fuel- and track-corrected. For "
              "every stint a line is fitted to corrected lap time vs tyre age "
              "and read off at a common low reference age, so each compound is "
              "compared on an equal fresh-tyre footing (clean laps preferred, "
              "falling back to all laps when a stint has too few). Each driver "
              "who ran both compounds contributes their personal pace "
              "difference (which cancels out car and driver speed); the bar is "
              "the field median, the whiskers the driver-to-driver spread. "
              "Why: the compound offset sets the strategy crossover — how many "
              "laps of tyre advantage a fresh soft buys over a hard determines "
              "whether an extra stop pays for itself."),
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
        html.Div(id="stint-insp-msg",
                 children=html.P("Select a driver and stint key.",
                                 style={"color": TEXT_DIM})),
        # Mounted once and updated via .data/.columns. Swapping a whole
        # DataTable in and out of a Div's children (the old approach) made the
        # dash-renderer log "object provided as children / reading 'type'" while
        # it reconciled the outgoing table's derived_virtual_data.
        dash_table.DataTable(
            id="stint-insp-table",
            data=[], columns=[],
            **TABLE_STYLE,
            style_data_conditional=[
                {"if": {"filter_query": "{LapInStint} = 1"},
                 "borderLeft": f"3px solid {ACCENT}"},
            ],
        ),
    ])

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
        card([*gloss("stint", "Stint"), " Lap Inspector"], stint_inspector,
             info=("Data: the individual laps of any stint, picked from a "
                   "dropdown that pre-ranks each driver's stints by pace — "
                   "times, tyre age, flags and validity per lap. Why: the "
                   "drill-down behind the stint aggregates above; use it to "
                   "check what a suspicious deg rate or stint average is "
                   "actually made of.")),
    ])
