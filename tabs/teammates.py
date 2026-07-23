"""TEAMMATES tab — head-to-head teammate comparison.
Extracted from app.py."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc

import f1lib.state as state
from f1lib.components import (
    theme, card, kpi, GFX, TABLE_STYLE, styled_table,
    badge as _badge, abbr as _abbr, hex_to_rgba as _hex_to_rgba,
    TEAM_ABBR as _TEAM_ABBR,
)
from f1lib.glossary import gloss
from f1lib.config import (
    TEAM_COLORS, COMPOUND_COLORS, get_driver_color,
    DARK_BG, CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
    SPEED_PERCENTILE,
)
from f1lib.processing import format_lap_time

# mirror the mutable data state (SESSIONS, DRIVERS, telemetry, …) so the
# moved bodies keep their bare-name reads — repopulated on every reload
state.register(globals())
from f1lib.standings import _order_teams_by_champ



def tab_teammates(fl, fs):
    """
    Head-to-head teammate comparison across multiple performance dimensions.
    Wrapped in a top-level try/except so any crash shows in the UI rather
    than killing the Dash server callback.
    """
    try:
        return _tab_teammates_inner(fl, fs)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        return html.Div([
            dbc.Alert(
                [html.B("Teammate tab error: "), str(exc)],
                color="danger", style={"fontSize": "0.82rem"},
            ),
            html.Pre(tb, style={
                "color": TEXT_DIM, "fontSize": "0.7rem",
                "background": "#09091A", "padding": "12px",
                "borderRadius": "6px", "overflowX": "auto",
            }),
        ])


# (_hex_to_rgba now lives in components.py as hex_to_rgba)


def _tab_teammates_inner(fl, fs):

    # ── 0. Pools & session-type detection ────────────────────
    sess_names = fl["session_name"].unique().tolist()
    race_sess  = [s for s in sess_names
                  if (s.startswith("Race") or s.startswith("Sprint"))
                  and "Qualifying" not in s]
    quali_sess = [s for s in sess_names if "Qualifying" in s]
    has_race   = bool(race_sess)
    has_quali  = bool(quali_sess)

    v         = fl[fl["ValidLap"]].copy()
    _pert     = (fl["Perturbed_Lap"] if "Perturbed_Lap" in fl.columns
                 else pd.Series(False, index=fl.index))
    v_clean   = fl[fl["ValidLap"] & ~_pert].copy()
    v_race    = v_clean[v_clean["session_name"].isin(race_sess)] if has_race  else pd.DataFrame()
    v_quali   = v[v["session_name"].isin(quali_sess)]            if has_quali else pd.DataFrame()

    # ── 1. Build teammate pairs (alphabetical within team) ───
    pairs: dict[str, list[str]] = {}
    for team, grp in v.groupby("Team"):
        if team in ("Unknown", ""):
            continue
        drvs = sorted(grp["Driver_Short"].dropna().unique().tolist())
        if len(drvs) >= 2:
            pairs[team] = drvs[:2]

    if not pairs:
        return html.P(
            "No complete teammate pairs in current filter — widen driver / team selection.",
            style={"color": TEXT_DIM},
        )
    # Order teams by current championship standing (leader first). This flows into
    # the scoreboard cards and every head-to-head gap chart, which otherwise had no
    # inherently meaningful team order (they were alphabetical).
    teams_sorted = _order_teams_by_champ(pairs.keys())

    # ── 2. Generic metric helpers ─────────────────────────────

    def _val(pool: pd.DataFrame, driver: str, agg_fn) -> float:
        sub = pool[pool["Driver_Short"] == driver]
        if sub.empty:
            return float("nan")
        try:
            return float(agg_fn(sub))
        except Exception:
            return float("nan")

    def _metric_rows(pool: pd.DataFrame, agg_fn) -> list[dict]:
        rows = []
        for team in teams_sorted:
            if team not in pairs:
                continue
            drv_a, drv_b = pairs[team]
            va, vb = _val(pool, drv_a, agg_fn), _val(pool, drv_b, agg_fn)
            if not (np.isnan(va) and np.isnan(vb)):
                rows.append(dict(team=team, drv_a=drv_a, drv_b=drv_b,
                                 val_a=va, val_b=vb))
        return rows

    # ── 3. Chart builders ─────────────────────────────────────

    def _gap_chart(rows: list[dict], title: str, xlabel: str,
                   fmt_fn=None, lower_is_better: bool = True,
                   note: str = "", unit: str = "") -> go.Figure:
        """
        One horizontal bar per team, coloured by TEAM_COLORS.
        Bar extends LEFT when Driver A wins, RIGHT when Driver B wins.
        Text inside the bar: ★ DrvA  val_a | val_b  DrvB ★
        """
        rows = [r for r in rows
                if not (np.isnan(r["val_a"]) and np.isnan(r["val_b"]))]
        if not rows:
            return go.Figure()

        fmt_fn = fmt_fn or (lambda v: f"{v:.3f}")

        raw_gaps = [
            (r["val_a"] - r["val_b"])
            if not (np.isnan(r["val_a"]) or np.isnan(r["val_b"])) else 0.0
            for r in rows
        ]
        disp_gaps = [g if lower_is_better else -g for g in raw_gaps]
        # Team color for bar fill; winner side indicated by direction
        bar_colors = [TEAM_COLORS.get(r["team"], "#808080") for r in rows]

        bar_texts, hover_data = [], []
        for r, dg in zip(rows, disp_gaps):
            va_s = fmt_fn(r["val_a"]) if not np.isnan(r["val_a"]) else "—"
            vb_s = fmt_fn(r["val_b"]) if not np.isnan(r["val_b"]) else "—"
            gap_s = (
                f"{abs(r['val_a'] - r['val_b']):.3f} {unit}"
                if not (np.isnan(r["val_a"]) or np.isnan(r["val_b"])) else "—"
            )
            w_a = "★ " if dg <= 0 else ""
            w_b = " ★" if dg >  0 else ""
            bar_texts.append(f"{w_a}{r['drv_a']}  {va_s}  |  {vb_s}  {r['drv_b']}{w_b}")
            hover_data.append([r["drv_a"], va_s, r["drv_b"], vb_s, gap_s])

        fig = go.Figure(go.Bar(
            y=[r["team"] for r in rows],
            x=disp_gaps,
            orientation="h",
            marker=dict(color=bar_colors, line=dict(color=GRID_CLR, width=0.8)),
            text=bar_texts,
            textposition="auto",
            textfont=dict(size=10, color="#fff"),
            customdata=hover_data,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "%{customdata[0]}: <b>%{customdata[1]}</b><br>"
                "%{customdata[2]}: <b>%{customdata[3]}</b><br>"
                "Gap: %{customdata[4]}"
                "<extra></extra>"
            ),
        ))
        fig.add_vline(x=0, line=dict(color=TEXT_MAIN, width=1.5))
        theme(fig, max(220, len(rows) * 58 + 130))
        fig.update_layout(
            xaxis_title=xlabel,
            bargap=0.35,
            showlegend=False,
            margin=dict(l=160, r=20, t=45, b=55),
        )
        fig.add_annotation(
            text=(
                "◀ left driver faster / better  ·  right driver faster / better ▶"
            ),
            xref="paper", yref="paper", x=0.5, y=1.07,
            xanchor="center", showarrow=False,
            font=dict(size=9, color=TEXT_DIM),
        )
        if note:
            fig.add_annotation(
                text=note, xref="paper", yref="paper",
                x=1.0, y=-0.16, xanchor="right", showarrow=False,
                font=dict(size=9, color=TEXT_DIM),
            )
        # rows arrive in championship order (leader first) → show leader on top
        fig.update_yaxes(autorange="reversed")
        return fig

    # Butterfly removed — all charts now use the same diverging gap style.
    # For "higher is better" metrics (laps, overtakes) lower_is_better=False
    # so the bar extends LEFT when Driver A has the higher value.

    # ── 4. Win counter ────────────────────────────────────────

    def _wins(va, vb, lower_is_better=True):
        if np.isnan(va) or np.isnan(vb):
            return 0, 0
        return (1, 0) if (va < vb if lower_is_better else va > vb) else (0, 1)

    # ══════════════════════════════════════════════════════════
    # COMPUTE ALL METRICS
    # ══════════════════════════════════════════════════════════

    # ── Race pace per compound ────────────────────────────────
    # Use the best valid stint per driver × compound across ALL sessions
    # (same logic as Stints tab: Stint_Rank_Across_Sessions = 1).
    # Falls back to all clean valid laps for that driver × compound if
    # stints_df is unavailable.
    pace_rows: dict[str, list[dict]] = {}
    for cmp in COMPOUNDS:
        cmp_rows: list[dict] = []
        for team in teams_sorted:
            if team not in pairs:
                continue
            drv_a, drv_b = pairs[team]

            def _best_stint_median(driver: str, compound: str) -> float:
                # Try to find the best valid stint from analyze_stints
                if fs is not None and not fs.empty and "Stint_Rank_Across_Sessions" in fs.columns:
                    best = fs[
                        (fs["Driver_Short"] == driver)
                        & (fs["Compound"] == compound)
                        & fs["Valid_Stint"]
                        & (fs["Stint_Rank_Across_Sessions"] == 1)
                    ]
                    if not best.empty and "Stint_FuelCorr" in best.columns:
                        v_ = pd.to_numeric(best["Stint_FuelCorr"], errors="coerce").dropna()
                        if not v_.empty:
                            return float(v_.iloc[0])
                # Fallback: trimmed median of fuel-corrected laps
                sub = v_clean[
                    (v_clean["Driver_Short"] == driver)
                    & (v_clean["Compound"] == compound)
                    & v_clean["LapTime_FuelCorrected"].notna()
                ]
                if sub.empty:
                    return float("nan")
                t = sub["LapTime_FuelCorrected"]
                lo, hi = t.quantile(0.10), t.quantile(0.90)
                trimmed = t[t.between(lo, hi)]
                return float(trimmed.median() if not trimmed.empty else t.median())

            va = _best_stint_median(drv_a, cmp)
            vb = _best_stint_median(drv_b, cmp)
            if not (np.isnan(va) and np.isnan(vb)):
                cmp_rows.append(dict(team=team, drv_a=drv_a, drv_b=drv_b,
                                     val_a=va, val_b=vb))
        if cmp_rows:
            pace_rows[cmp] = cmp_rows

    # ── Quali sim / single-lap pace ───────────────────────────
    # Best quali-sim lap across ALL sessions (not just quali sessions).
    # Falls back to best valid lap if Is_Quali_Sim is absent.
    if "Is_Quali_Sim" in fl.columns and fl["Is_Quali_Sim"].any():
        qs_pool  = fl[fl["ValidLap"] & (fl["Is_Quali_Sim"] == True)]
        qs_label = "Quali Sim Best Lap (all sessions)"
    else:
        qs_pool  = v
        qs_label = "Best Valid Lap (no Is_Quali_Sim)"
    qs_rows = _metric_rows(qs_pool, lambda s: s["LapTime_s"].min()) if not qs_pool.empty else []

    # Total valid laps
    laps_rows = _metric_rows(v, lambda s: float(len(s)))

    # Consistency — IQR/Median × 100 (lower = better)
    def _consistency(s: pd.DataFrame) -> float:
        t = s["LapTime_s"].dropna()
        if len(t) < 4:
            return float("nan")
        q25, q75, med = t.quantile(0.25), t.quantile(0.75), t.median()
        return (q75 - q25) / med * 100.0 if med > 0 else float("nan")
    cons_rows = _metric_rows(v_clean, _consistency)

    # Average pit stop duration (race/sprint only)
    pit_rows: list[dict] = []
    if has_race:
        _race_all = fl[fl["session_name"].isin(race_sess)].sort_values(
            ["session_name", "DriverNo", "LapNo"]
        )
        _pit_data: list[dict] = []
        for (sess, drv_no), grp in _race_all.groupby(["session_name", "DriverNo"]):
            grp_s   = grp.sort_values("LapNo")
            in_laps = grp_s[grp_s["InLap"]  & grp_s["PitIn"].notna()]
            out_laps = grp_s[grp_s["OutLap"] & grp_s["PitOut"].notna()]
            # Build a dict LapNo → first PitOut value (avoid duplicate-index issue)
            out_dict = {}
            for _, orow in out_laps.iterrows():
                ln = int(orow["LapNo"])
                if ln not in out_dict:
                    out_dict[ln] = float(orow["PitOut"])
            for _, inrow in in_laps.iterrows():
                nxt = int(inrow["LapNo"]) + 1
                try:
                    pit_in_s = float(inrow["PitIn"])
                    if nxt in out_dict and np.isfinite(pit_in_s) and np.isfinite(out_dict[nxt]):
                        dur = out_dict[nxt] - pit_in_s
                        if 1.5 < dur < 65.0:
                            _pit_data.append({
                                "Driver_Short": inrow["Driver_Short"],
                                "Team":         inrow["Team"],
                                "dur":          dur,
                            })
                except Exception:
                    pass
        if _pit_data:
            _pit_df  = pd.DataFrame(_pit_data)
            pit_rows = _metric_rows(_pit_df, lambda s: s["dur"].mean())

    # Race finish position & positions gained
    finish_rows: list[dict] = []
    pgain_rows:  list[dict] = []
    if has_race and "Classified_Position" in fl.columns:
        _rr_base = fl[fl["session_name"].isin(race_sess)].copy()
        # Convert to numeric safely (handles "DNF", "DSQ", etc.)
        _rr_base["_fin_num"]  = pd.to_numeric(_rr_base["Classified_Position"], errors="coerce")
        _rr_base["_grid_num"] = pd.to_numeric(
            _rr_base.get("Grid_Position", pd.Series(dtype=float)), errors="coerce"
        ) if "Grid_Position" in _rr_base.columns else np.nan
        _rr = (
            _rr_base.groupby("Driver_Short")
            .agg(
                Team      =("Team",       "first"),
                Finish_num=("_fin_num",   "first"),
                Grid_num  =("_grid_num",  "first"),
            )
            .reset_index()
        )
        _rr["Gained"] = _rr["Grid_num"] - _rr["Finish_num"]

        def _rr_rows(val_col):
            out = []
            for team in teams_sorted:
                if team not in pairs:
                    continue
                drv_a, drv_b = pairs[team]
                sa = _rr[_rr["Driver_Short"] == drv_a]
                sb = _rr[_rr["Driver_Short"] == drv_b]
                if sa.empty and sb.empty:
                    continue
                va = float(sa[val_col].iloc[0]) if (not sa.empty and sa[val_col].notna().any()) else float("nan")
                vb = float(sb[val_col].iloc[0]) if (not sb.empty and sb[val_col].notna().any()) else float("nan")
                out.append(dict(team=team, drv_a=drv_a, drv_b=drv_b, val_a=va, val_b=vb))
            return out

        finish_rows = _rr_rows("Finish_num")
        pgain_rows  = _rr_rows("Gained")

    # Overtakes (race/sprint only; requires flag_position_changes)
    overtake_rows: list[dict] = []
    if has_race and "Overtook" in fl.columns:
        _ov_pool  = fl[fl["session_name"].isin(race_sess)]
        overtake_rows = _metric_rows(_ov_pool, lambda s: float(s["Overtook"].sum()))

    # Championship points (sum across all race/sprint sessions in filter)
    # Race_Points is repeated on every lap row — deduplicate to one value
    # per driver × session before summing, then aggregate across sessions.
    champ_rows: list[dict] = []
    if has_race and "Race_Points" in fl.columns:
        _pts_dedup = (
            fl[fl["session_name"].isin(race_sess)]
            .groupby(["session_name", "Driver_Short", "Team"])["Race_Points"]
            .first()                                          # one value per session
            .reset_index()
        )
        _pts_dedup["Race_Points"] = pd.to_numeric(_pts_dedup["Race_Points"], errors="coerce")
        _pts_pool = (
            _pts_dedup
            .groupby(["Driver_Short", "Team"])["Race_Points"]
            .sum()
            .reset_index(name="pts")
        )
        for team in teams_sorted:
            if team not in pairs:
                continue
            drv_a, drv_b = pairs[team]
            ra = _pts_pool[_pts_pool["Driver_Short"] == drv_a]
            rb = _pts_pool[_pts_pool["Driver_Short"] == drv_b]
            va = float(ra["pts"].iloc[0]) if not ra.empty else float("nan")
            vb = float(rb["pts"].iloc[0]) if not rb.empty else float("nan")
            if not (np.isnan(va) and np.isnan(vb)):
                champ_rows.append(dict(team=team, drv_a=drv_a, drv_b=drv_b,
                                       val_a=va, val_b=vb))

    # Qualifying best time (Q3 → Q2 → Q1 cascade from results, else best lap in quali)
    quali_time_rows: list[dict] = []
    if has_quali:
        q_cols_avail = [c for c in ("Q3_s", "Q2_s", "Q1_s") if c in fl.columns]
        if q_cols_avail:
            _q_pool = fl[fl["session_name"].isin(quali_sess)]
            for team in teams_sorted:
                if team not in pairs:
                    continue
                drv_a, drv_b = pairs[team]
                def _best_q_time(driver):
                    sub = _q_pool[_q_pool["Driver_Short"] == driver]
                    if sub.empty:
                        return float("nan")
                    for qc in q_cols_avail:
                        v_ = pd.to_numeric(sub[qc], errors="coerce").dropna()
                        if not v_.empty:
                            return float(v_.iloc[0])
                    return float("nan")
                va, vb = _best_q_time(drv_a), _best_q_time(drv_b)
                if not (np.isnan(va) and np.isnan(vb)):
                    quali_time_rows.append(
                        dict(team=team, drv_a=drv_a, drv_b=drv_b, val_a=va, val_b=vb)
                    )
        if not quali_time_rows and not v_quali.empty:
            quali_time_rows = _metric_rows(v_quali, lambda s: s["LapTime_s"].min())

    # ══════════════════════════════════════════════════════════
    # SCOREBOARD  — tally wins per team
    # ══════════════════════════════════════════════════════════

    def _get_vals(rows_list, team):
        for r in rows_list:
            if r["team"] == team:
                return r["val_a"], r["val_b"]
        return float("nan"), float("nan")

    sb_items = []
    for team in teams_sorted:
        if team not in pairs:
            continue
        drv_a, drv_b = pairs[team]
        score_a, score_b = 0, 0
        metric_pills_data = []

        all_metrics_def = [
            *[(f"Pace {c}",   pace_rows.get(c, []),   True,  format_lap_time)
              for c in COMPOUNDS if c in pace_rows],
            (qs_label,        qs_rows,                 True,  format_lap_time),
            ("Consistency",   cons_rows,               True,  lambda v: f"{v:.2f}%"),
            ("Total Laps",    laps_rows,               False, lambda v: str(int(v)) if not np.isnan(v) else "—"),
            *([("Avg Pit Stop",  pit_rows,      True,  lambda v: f"{v:.2f}s")] if pit_rows  else []),
            *([("Race Finish",   finish_rows,   True,  lambda v: f"P{int(v)}"  if not np.isnan(v) else "—")] if finish_rows  else []),
            *([("Pos. Gained",   pgain_rows,    False, lambda v: (f"+{int(v)}" if v > 0 else str(int(v))) if not np.isnan(v) else "—")] if pgain_rows   else []),
            *([("Overtakes",     overtake_rows, False, lambda v: str(int(v))   if not np.isnan(v) else "—")] if overtake_rows else []),
            *([("Champ. Pts",    champ_rows,    False, lambda v: f"{int(v)} pts" if not np.isnan(v) else "—")] if champ_rows    else []),
            *([("Quali Time",    quali_time_rows, True, format_lap_time)] if quali_time_rows else []),
        ]

        for label, rows_list, lib, fmt in all_metrics_def:
            va, vb = _get_vals(rows_list, team)
            wa, wb = _wins(va, vb, lower_is_better=lib)
            score_a += wa; score_b += wb
            try:
                a_str = fmt(va) if not np.isnan(va) else "—"
                b_str = fmt(vb) if not np.isnan(vb) else "—"
            except Exception:
                a_str = "—"; b_str = "—"
            winner = drv_a if wa else (drv_b if wb else None)
            metric_pills_data.append((label, a_str, b_str, winner))

        clr   = TEAM_COLORS.get(team, "#808080")
        total = max(score_a + score_b, 1)
        pct_a = score_a / total * 100

        # Progress bar
        bar_el = html.Div(
            html.Div([
                html.Div(style={
                    "width": f"{pct_a:.1f}%", "height": "100%",
                    "background": "#00D2BE", "display": "inline-block",
                    "borderRadius": "3px 0 0 3px" if pct_a > 0 and pct_a < 100 else "3px",
                }),
                html.Div(style={
                    "width": f"{100 - pct_a:.1f}%", "height": "100%",
                    "background": "#FF8700", "display": "inline-block",
                    "borderRadius": "0 3px 3px 0" if pct_a > 0 and pct_a < 100 else "3px",
                }),
            ], style={"display": "flex", "height": "100%"}),
            style={"height": "7px", "borderRadius": "4px", "margin": "6px 0",
                   "background": GRID_CLR},
        )

        # Metric detail pills
        pills = []
        for label, a_str, b_str, winner in metric_pills_data:
            bg = "#00D2BE" if winner == drv_a else ("#FF8700" if winner == drv_b else "#333")
            pills.append(html.Span(
                f"{label}: {a_str} | {b_str}",
                style={
                    "background": bg + "28",
                    "border": f"1px solid {bg}",
                    "borderRadius": "3px", "padding": "2px 7px",
                    "fontSize": "0.68rem", "marginRight": "5px",
                    "marginBottom": "4px", "display": "inline-block",
                    "color": TEXT_MAIN,
                },
                title=f"Winner: {winner or '—'}",
            ))

        sb_items.append(dbc.Col(
            dbc.Card(dbc.CardBody([
                html.Div([
                    html.Span("● ", style={"color": clr, "fontSize": "1.1rem"}),
                    html.Span(team, style={
                        "fontWeight": "700", "fontSize": "0.88rem",
                        "color": TEXT_MAIN, "letterSpacing": "0.5px",
                    }),
                ]),
                html.Div([
                    html.Span(drv_a, style={
                        "color": "#00D2BE", "fontWeight": "800", "fontSize": "1.25rem",
                    }),
                    html.Span(f"  {score_a} – {score_b}  ", style={
                        "color": TEXT_DIM, "fontSize": "0.95rem", "fontWeight": "600",
                    }),
                    html.Span(drv_b, style={
                        "color": "#FF8700", "fontWeight": "800", "fontSize": "1.25rem",
                    }),
                ], style={"margin": "5px 0"}),
                bar_el,
                html.Div(pills, style={"marginTop": "8px", "lineHeight": "2.0"}),
            ]), style={
                "background": CARD_BG,
                "border": f"1px solid {_hex_to_rgba(clr, 0.27)}",
                "borderRadius": "8px",
            }),
            md=6, lg=4, className="mb-3",
        ))

    scoreboard = card(
        html.Span([
            "Head-to-Head Scoreboard",
            html.Span(
                " — drivers sorted alphabetically within each team (teal = A, orange = B)",
                style={"color": TEXT_DIM, "fontWeight": "400",
                       "fontSize": "0.75rem", "marginLeft": "8px"},
            ),
        ]),
        dbc.Row(sb_items),
        info=("Data: for each team, the two teammates are compared across every "
              "metric below (pace per compound, quali, consistency, laps, pit stops, "
              "finish, positions gained, overtakes, points). Each metric counts as one "
              "'win'; the score and bar tally those wins. Why: the fairest way to rate "
              "drivers — against the one person in identical machinery."),
    )

    # ══════════════════════════════════════════════════════════
    # SECTION: RACE PACE PER COMPOUND
    # ══════════════════════════════════════════════════════════
    pace_col_items = []
    if pace_rows:
        n_cmp = len(pace_rows)
        col_w = 12 if n_cmp == 1 else 6 if n_cmp == 2 else 4
        for cmp, rows_ in pace_rows.items():
            fig = _gap_chart(
                rows_,
                title=f"Race Pace – {cmp}",
                xlabel="Gap (s)  ·  negative = left driver faster",
                fmt_fn=format_lap_time,
                lower_is_better=True,
                note="Stint_FuelCorr (fuel-corrected trimmed median) of best valid stint across all sessions. Falls back to trimmed median of fuel-corrected laps.",
                unit="s",
            )
            pace_col_items.append(dbc.Col(card(
                html.Span([
                    "Race Pace – ",
                    html.Span(cmp, style={
                        "color": COMPOUND_COLORS.get(cmp, "#fff"),
                        "fontWeight": "800",
                    }),
                ]),
                dcc.Graph(figure=fig, config=GFX),
                info=(f"Data: teammates' fuel-corrected representative pace on "
                      f"their best valid {cmp} stint (trimmed median). Why: "
                      "same car, same compound — the cleanest possible "
                      "race-pace comparison between two drivers."),
            ), md=col_w))
    else:
        pace_col_items = [dbc.Col(html.P(
            "No race / sprint race sessions in current selection.",
            style={"color": TEXT_DIM, "fontStyle": "italic"},
        ), md=12)]

    race_pace_section = card(
        html.Span([
            "Race Pace by Compound",
            html.Span(" — best valid stint per driver × compound across all sessions",
                      style={"color": TEXT_DIM, "fontWeight": "400",
                             "fontSize": "0.75rem", "marginLeft": "8px"}),
        ]),
        dbc.Row(pace_col_items),
        info=("Data: each teammate's fuel-corrected pace on their best valid stint per "
              "compound (all sessions). One diverging bar per team — it points left "
              "when the left/teal driver is faster, right when the right/orange driver "
              "is. Why: compares teammates on equal tyres, the cleanest race-pace duel."),
    )

    # ══════════════════════════════════════════════════════════
    # SECTION: CONSISTENCY + TOTAL LAPS
    # ══════════════════════════════════════════════════════════
    cons_fig = _gap_chart(
        cons_rows,
        title="Consistency — IQR / Median × 100%",
        xlabel="Gap (%)  ·  negative = left driver more consistent",
        fmt_fn=lambda v: f"{v:.2f}%",
        lower_is_better=True,
        note="Valid non-perturbed laps. IQR = P75 − P25 of lap-time distribution. Lower % = tighter.",
        unit="%",
    )
    laps_fig = _gap_chart(
        laps_rows,
        title="Total Valid Laps  (all sessions)",
        xlabel="Gap (laps)  ·  negative = left driver ran more laps",
        fmt_fn=lambda v: str(int(v)) if not np.isnan(v) else "—",
        lower_is_better=False,
        note="ValidLap=True count across all sessions in current filter.",
        unit="laps",
    )
    _sub_label = {"color": TEXT_DIM, "fontSize": "0.72rem", "fontWeight": "700",
                  "letterSpacing": "1px", "marginBottom": "2px"}
    consistency_section = card(
        "Consistency & Volume",
        dbc.Row([
            dbc.Col([html.P("CONSISTENCY · IQR / MEDIAN", style=_sub_label),
                     dcc.Graph(figure=cons_fig, config=GFX)], md=7),
            dbc.Col([html.P("TOTAL VALID LAPS", style=_sub_label),
                     dcc.Graph(figure=laps_fig, config=GFX)], md=5),
        ]),
        info=("Data: left = lap-time consistency (IQR ÷ median × 100 of valid "
              "non-perturbed laps; lower = tighter, more repeatable); right = total "
              "valid laps each teammate ran. Why: consistency is a key driver skill, "
              "and lap volume tells you how solid the comparison is."),
    )

    # ══════════════════════════════════════════════════════════
    # SECTION: QUALIFYING (conditional)
    # ══════════════════════════════════════════════════════════
    quali_col_items = []
    if has_quali:
        if qs_rows:
            qs_fig = _gap_chart(
                qs_rows,
                title=qs_label,
                xlabel="Gap (s)  ·  negative = left driver faster",
                fmt_fn=format_lap_time,
                lower_is_better=True,
                note=(
                    "Lap within 0.5% of personal best on tyre age ≤ 4."
                    if "Is_Quali_Sim" in fl.columns and fl["Is_Quali_Sim"].any()
                    else "Is_Quali_Sim absent — best valid lap used."
                ),
                unit="s",
            )
            quali_col_items.append(
                dbc.Col(card(
                    qs_label, dcc.Graph(figure=qs_fig, config=GFX),
                    info=("Data: each teammate's best one-lap effort — quali-sim "
                          "laps (within 0.5% of personal best, tyre age ≤ 4) when "
                          "identified, else the best valid lap. Why: isolates "
                          "single-lap speed from race pace; a driver can win one "
                          "duel and lose the other."),
                ), md=6)
            )
        if quali_time_rows:
            qt_fig = _gap_chart(
                quali_time_rows,
                title="Qualifying Classification Time",
                xlabel="Gap (s)  ·  negative = left driver faster",
                fmt_fn=format_lap_time,
                lower_is_better=True,
                note="Best of Q3 / Q2 / Q1 from session results (enrich_session_results).",
                unit="s",
            )
            quali_col_items.append(
                dbc.Col(card(
                    [*gloss("qualifying", "Qualifying"), " Classification Time"],
                    dcc.Graph(figure=qt_fig, config=GFX),
                    info=("Data: the official best quali lap from the "
                          "classification (Q3, else Q2, else Q1). Why: the "
                          "teammate duel as it counted on Saturday — unlike the "
                          "practice-based one-lap estimate, this is the result "
                          "that set the grid."),
                ), md=6)
            )

    # ══════════════════════════════════════════════════════════
    # SECTION: RACE / SPRINT (conditional)
    # ══════════════════════════════════════════════════════════
    race_col_items = []
    if has_race:
        if pit_rows:
            pit_fig = _gap_chart(
                pit_rows,
                title="Average Pit Stop Duration",
                xlabel="Gap (s)  ·  negative = left driver faster pit",
                fmt_fn=lambda v: f"{v:.2f}s",
                lower_is_better=True,
                note="PitOut − PitIn for matched in/out lap pairs. Range filter: 1.5 – 65 s.",
                unit="s",
            )
            race_col_items.append(
                dbc.Col(card(
                    [*gloss("pit stop", "Pit Stop"), " Duration"],
                    dcc.Graph(figure=pit_fig, config=GFX),
                    info=("Data: average pit-lane transit time (PitOut − PitIn) "
                          "per driver across matched stops. Why: mostly a team/"
                          "crew metric, but consistent differences between "
                          "teammates reveal pit-entry/exit driving and box-stop "
                          "discipline."),
                ), md=6)
            )

        if finish_rows:
            fin_fig = _gap_chart(
                finish_rows,
                title="Race Finish Position  (lower position = better)",
                xlabel="Gap  ·  negative = left driver finished higher",
                fmt_fn=lambda v: f"P{int(v)}" if not np.isnan(v) else "—",
                lower_is_better=True,
                note="Classified_Position from session results. DNF / DSQ → shown as —.",
                unit="pos",
            )
            race_col_items.append(
                dbc.Col(card(
                    "Race Finish Position",
                    dcc.Graph(figure=fin_fig, config=GFX),
                    info=("Data: official classified finishing position per "
                          "race (DNF/DSQ shown as —). Why: the bottom line of "
                          "the teammate comparison — pace only matters if it "
                          "converts into results."),
                ), md=6)
            )

        if pgain_rows:
            pg_fig = _gap_chart(
                pgain_rows,
                title="Positions Gained / Lost  (Grid → Classified Finish)",
                xlabel="Gap  ·  negative = left driver gained more",
                fmt_fn=lambda v: (f"+{int(v)}" if v > 0 else str(int(v))) if not np.isnan(v) else "—",
                lower_is_better=False,   # higher gain is better
                note="Positions gained = Grid_Position − Classified_Position. Positive = moved up.",
                unit="pos",
            )
            race_col_items.append(
                dbc.Col(card(
                    "Positions Gained / Lost",
                    dcc.Graph(figure=pg_fig, config=GFX),
                    info=("Data: grid position minus classified finish "
                          "(positive = moved forward). Why: race-day execution "
                          "— starts, restarts, strategy and racecraft — "
                          "independent of where qualifying put the car."),
                ), md=6)
            )

        if overtake_rows:
            ov_fig = _gap_chart(
                overtake_rows,
                title="Overtakes Made  (race/sprint sessions)",
                xlabel="Gap (overtakes)  ·  negative = left driver made more",
                fmt_fn=lambda v: str(int(v)) if not np.isnan(v) else "—",
                lower_is_better=False,
                note="Overtook = position gained ≥ 1 on a non-pit lap (flag_position_changes).",
                unit="overtakes",
            )
            race_col_items.append(
                dbc.Col(card(
                    "Overtakes",
                    dcc.Graph(figure=ov_fig, config=GFX),
                    info=("Data: count of on-track positions gained on non-pit "
                          "laps (pit-cycle shuffles excluded). Why: a proxy for "
                          "wheel-to-wheel racecraft rather than pace — who "
                          "actually passes cars on track."),
                ), md=6)
            )

        if champ_rows:
            champ_fig = _gap_chart(
                champ_rows,
                title="Championship Points Scored",
                xlabel="Gap (pts)  ·  negative = left driver scored more",
                fmt_fn=lambda v: f"{int(v)} pts" if not np.isnan(v) else "—",
                lower_is_better=False,
                note="Sum of Race_Points across all race/sprint sessions in current filter.",
                unit="pts",
            )
            # KPI pills: one per team showing A pts vs B pts
            champ_kpis = []
            for r in champ_rows:
                clr = TEAM_COLORS.get(r["team"], "#808080")
                va_s = f"{int(r['val_a'])} pts" if not np.isnan(r["val_a"]) else "—"
                vb_s = f"{int(r['val_b'])} pts" if not np.isnan(r["val_b"]) else "—"
                winner = (
                    r["drv_a"] if (not np.isnan(r["val_a"]) and not np.isnan(r["val_b"]) and r["val_a"] >= r["val_b"])
                    else (r["drv_b"] if not np.isnan(r["val_b"]) else None)
                )
                champ_kpis.append(dbc.Col(
                    dbc.Card(dbc.CardBody([
                        html.P(
                            html.Span([
                                "● ", html.Span(r["team"],
                                    style={"fontWeight":"700","fontSize":"0.78rem"})
                            ], style={"color": clr}),
                            style={"marginBottom": "4px", "fontSize": "0.72rem"},
                        ),
                        html.Div([
                            html.Span(r["drv_a"],
                                style={"color": "#00D2BE" if winner == r["drv_a"] else TEXT_DIM,
                                       "fontWeight": "800", "fontSize": "1.05rem"}),
                            html.Span(f"  {va_s}  ·  {vb_s}  ",
                                style={"color": TEXT_DIM, "fontSize": "0.85rem"}),
                            html.Span(r["drv_b"],
                                style={"color": "#FF8700" if winner == r["drv_b"] else TEXT_DIM,
                                       "fontWeight": "800", "fontSize": "1.05rem"}),
                        ]),
                    ]), style={"background": CARD_BG,
                               "border": f"1px solid {_hex_to_rgba(clr, 0.35)}",
                               "borderRadius": "8px"}),
                    xs=6, md=4, lg=3, className="mb-2",
                ))
            race_col_items.append(dbc.Col(card(
                html.Span([
                    "Championship Points",
                    html.Span(" — race/sprint sessions in current filter",
                              style={"color": TEXT_DIM, "fontWeight": "400",
                                     "fontSize": "0.75rem", "marginLeft": "8px"}),
                ]),
                html.Div([
                    dbc.Row(champ_kpis, className="mb-3"),
                    dcc.Graph(figure=champ_fig, config=GFX),
                ]),
                info=("Data: championship points each teammate scored in the "
                      "race/sprint sessions of the current filter, as KPI tiles "
                      "plus the head-to-head gap. Why: the currency the team "
                      "actually cares about — the intra-team points split often "
                      "decides careers."),
            ), md=12))

    # ══════════════════════════════════════════════════════════
    # ASSEMBLE FULL LAYOUT
    # ══════════════════════════════════════════════════════════
    sections = [scoreboard, race_pace_section, consistency_section]

    if quali_col_items:
        sections.append(card(
            "Qualifying", dbc.Row(quali_col_items),
            info=("Data: teammate single-lap qualifying comparison — best quali-sim "
                  "lap and/or the classified Q3→Q2→Q1 time. Bars diverge toward the "
                  "faster driver. Why: qualifying pace decides grid position and is a "
                  "clean low-fuel speed test."),
        ))

    if race_col_items:
        sections.append(card(
            html.Span([
                "Race / Sprint Performance",
                html.Span(
                    f" — {', '.join(s.split('_')[0] for s in race_sess)}",
                    style={"color": TEXT_DIM, "fontWeight": "400",
                           "fontSize": "0.75rem", "marginLeft": "8px"},
                ),
            ]),
            dbc.Row(race_col_items),
            info=("Data: teammate race-day comparison from race/sprint sessions — pit "
                  "stop time, finish position, positions gained, overtakes and "
                  "championship points. Each bar diverges toward the better driver. "
                  "Why: separates race-craft, strategy and results from pure pace."),
        ))

    return html.Div(sections)


# ══════════════════════════════════════════════════════════════
# TAB 8 – TRACK INFO
# ══════════════════════════════════════════════════════════════
