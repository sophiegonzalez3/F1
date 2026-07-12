"""TEAM ANALYSIS tab — best-of-2-drivers vs team-average columns.
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


def tab_teams(fl, fs):
    try:
        return _tab_teams_inner2(fl, fs)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        return html.Div([
            dbc.Alert([html.B("Team Analysis – error: "), str(exc)],
                      color="danger", style={"fontSize": "0.82rem"}),
            html.Pre(tb, style={
                "color": TEXT_DIM, "fontSize": "0.7rem",
                "background": "#09091A", "padding": "12px",
                "borderRadius": "6px", "overflowX": "auto",
            }),
        ])


def _tab_teams_inner2(fl, fs):
    # ── Session detection ─────────────────────────────────────
    sess_names = fl["session_name"].unique().tolist()
    race_sess  = [s for s in sess_names
                  if (s.startswith("Race") or s.startswith("Sprint"))
                  and "Qualifying" not in s and "Shootout" not in s]
    quali_sess = [s for s in sess_names
                  if "Qualifying" in s or "Shootout" in s]
    has_race   = bool(race_sess)
    has_quali  = bool(quali_sess)

    v = fl[fl["ValidLap"]].copy()
    if v.empty:
        return html.P("No valid laps in current filter.", style={"color": TEXT_DIM})

    _pert   = fl["Perturbed_Lap"] if "Perturbed_Lap" in fl.columns else pd.Series(False, index=fl.index)
    v_clean = fl[fl["ValidLap"] & ~_pert].copy()

    # ── Build team → [driver1, driver2] mapping ───────────────
    pairs: dict = {}
    for team, grp in v.groupby("Team"):
        if str(team) in ("Unknown", "", "nan"):
            continue
        drvs = sorted(grp["Driver_Short"].dropna().unique().tolist())
        if drvs:
            pairs[team] = drvs[:2]

    if not pairs:
        return html.P("No teams found in current filter.", style={"color": TEXT_DIM})

    # Default team ordering = current championship standing (leader first). Charts
    # that rank by their own metric (% gap bars) re-sort and are unaffected; this
    # drives the order of the per-session laps bars and any team-categorical view.
    teams_all = _order_teams_by_champ(pairs.keys())

    # ── Generic helpers ───────────────────────────────────────
    def _drv_val(pool, driver, agg_fn):
        sub = pool[pool["Driver_Short"] == driver]
        if sub.empty:
            return np.nan
        try:
            r = agg_fn(sub)
            return float(r) if (r is not None and pd.notna(r)) else np.nan
        except Exception:
            return np.nan

    def _best_of(va, vb, lower_is_better=True):
        vals = [x for x in [va, vb] if pd.notna(x) and np.isfinite(x)]
        if not vals:
            return np.nan
        return min(vals) if lower_is_better else max(vals)

    def _avg_of(va, vb):
        vals = [x for x in [va, vb] if pd.notna(x) and np.isfinite(x)]
        return float(np.mean(vals)) if vals else np.nan

    def _team_dicts(pool, agg_fn, lower_is_better=True):
        """Return (best_d, avg_d): team → aggregated float."""
        best_d, avg_d = {}, {}
        for team in teams_all:
            drvs = pairs[team]
            va = _drv_val(pool, drvs[0], agg_fn)
            vb = _drv_val(pool, drvs[1], agg_fn) if len(drvs) > 1 else np.nan
            best_d[team] = _best_of(va, vb, lower_is_better)
            avg_d[team]  = _avg_of(va, vb)
        return best_d, avg_d

    # ── % gap to leader helper ────────────────────────────────
    def _pct_gap(value, leader, lower_is_better):
        """Return % gap from leader. Leader = 0%. Others = positive %."""
        if not np.isfinite(leader) or leader == 0:
            return float("nan")
        if lower_is_better:
            return (value - leader) / abs(leader) * 100.0
        else:
            return (leader - value) / abs(leader) * 100.0

    # ── Horizontal bar chart – % gap to leader ────────────────
    def _hbar(data_d, title, fmt_fn=None, lower_is_better=True, xlabel="", pct_gap=True):
        items = [(t, vv) for t, vv in data_d.items() if pd.notna(vv) and np.isfinite(vv)]
        if not items:
            return go.Figure()
        items.sort(key=lambda x: x[1], reverse=not lower_is_better)
        fmt    = fmt_fn or (lambda v: f"{v:.3f}")
        leader = items[0][1]

        if pct_gap and abs(leader) > 1e-9:
            gaps   = [_pct_gap(v, leader, lower_is_better) for _, v in items]
            x_vals = gaps
            # bar text: original value for leader, "value (+gap%)" for others
            bar_text = [
                fmt(v) if i == 0 else f"{fmt(v)}  +{g:.2f}%"
                for i, ((_, v), g) in enumerate(zip(items, gaps))
            ]
            x_title = "% gap to leader  (0 = best)"
        else:
            x_vals  = [v for _, v in items]
            bar_text = [fmt(v) for _, v in items]
            x_title = xlabel or title

        ts     = [i[0] for i in items]
        colors = [TEAM_COLORS.get(t, "#808080") for t in ts]
        fig = go.Figure(go.Bar(
            x=x_vals, y=ts, orientation="h",
            marker_color=colors,
            text=bar_text,
            textposition="outside",
            textfont=dict(size=9, color=TEXT_MAIN),
            hovertemplate="%{y}: %{text}<extra></extra>",
        ))
        h = max(200, len(items) * 44 + 90)
        theme(fig, h, title)
        fig.update_layout(
            xaxis_title=x_title,
            showlegend=False,
            margin=dict(l=140, r=140, t=50, b=40),
        )
        fig.update_xaxes(rangemode="tozero")
        fig.update_yaxes(autorange="reversed")
        return fig

    # ── Grouped compound bar – % gap per compound ─────────────
    def _compound_bars(compound_dicts, title, fmt_fn=None, lower_is_better=True):
        """compound_dicts: {compound: {team: value}}
        Each compound normalised independently to its own leader (0%)."""
        # Sort order by best overall value across compounds
        best_overall: dict = {}
        for cmp, d in compound_dicts.items():
            for t, vv in d.items():
                if pd.notna(vv) and np.isfinite(vv):
                    if t not in best_overall:
                        best_overall[t] = vv
                    else:
                        best_overall[t] = (
                            min(vv, best_overall[t]) if lower_is_better
                            else max(vv, best_overall[t])
                        )
        if not best_overall:
            return go.Figure()
        team_order = sorted(best_overall.keys(),
                            key=lambda t: best_overall[t],
                            reverse=not lower_is_better)
        fmt = fmt_fn or (lambda v: f"{v:.3f}")
        fig = go.Figure()
        for cmp, d in compound_dicts.items():
            raw_items = [(t, d[t]) for t in team_order
                         if pd.notna(d.get(t, np.nan)) and np.isfinite(d.get(t, np.nan))]
            if not raw_items:
                continue
            cmp_leader = min(v for _, v in raw_items) if lower_is_better else max(v for _, v in raw_items)
            y_teams = [t for t, _ in raw_items]
            gaps    = [_pct_gap(v, cmp_leader, lower_is_better) for _, v in raw_items]
            bar_text = [
                fmt(v) if i == 0 else f"{fmt(v)}  +{g:.2f}%"
                for i, ((_, v), g) in enumerate(zip(raw_items, gaps))
            ]
            fig.add_trace(go.Bar(
                x=gaps, y=y_teams, name=cmp,
                orientation="h",
                marker_color=COMPOUND_COLORS.get(cmp, "#808080"),
                text=bar_text,
                textposition="outside",
                textfont=dict(size=8, color=TEXT_MAIN),
                hovertemplate=f"<b>{{{{y}}}}</b> – {cmp}: %{{text}}<extra></extra>",
            ))
        h = max(220, len(team_order) * 58 + 130)
        theme(fig, h, title)
        fig.update_layout(
            barmode="group", showlegend=True,
            xaxis_title="% gap to compound leader  (0 = best per compound)",
            margin=dict(l=140, r=140, t=50, b=40),
            legend=dict(orientation="h", x=0, y=1.14, bgcolor="rgba(0,0,0,0)"),
        )
        fig.update_xaxes(rangemode="tozero")
        fig.update_yaxes(autorange="reversed", categoryorder="array",
                         categoryarray=list(reversed(team_order)))
        return fig

    # ── Laps per session grouped bar – % gap per session ──────
    def _session_laps_bar(laps_per_sess, title, fmt_fn=None):
        fig = go.Figure()
        for sess, d in laps_per_sess.items():
            items = [(t, vv) for t, vv in d.items() if pd.notna(vv) and vv > 0]
            if not items:
                continue
            # Higher laps = better; leader is the team with most laps this session
            leader_laps = max(v for _, v in items)
            ts = [i[0] for i in items]
            vs = [i[1] for i in items]
            gaps = [_pct_gap(v, leader_laps, lower_is_better=False) for v in vs]
            bar_text = [
                (fmt_fn(v) if fmt_fn else str(int(v))) if g == 0.0
                else ((fmt_fn(v) if fmt_fn else str(int(v))) + f"  +{g:.1f}%")
                for v, g in zip(vs, gaps)
            ]
            fig.add_trace(go.Bar(
                y=ts, x=gaps, name=sess.split("_")[0], orientation="h",
                text=bar_text,
                textposition="outside",
                textfont=dict(size=8, color=TEXT_MAIN),
                hovertemplate=f"<b>{{{{y}}}}</b> – {sess.split('_')[0]}: %{{text}}<extra></extra>",
            ))
        h = max(220, len(teams_all) * 50 + 130)
        theme(fig, h, title)
        fig.update_layout(
            barmode="group", showlegend=True,
            xaxis_title="% gap to session leader  (0 = most laps per session)",
            margin=dict(l=140, r=140, t=50, b=40),
            legend=dict(orientation="h", x=0, y=1.14, bgcolor="rgba(0,0,0,0)"),
        )
        fig.update_xaxes(rangemode="tozero")
        fig.update_yaxes(autorange="reversed")
        return fig

    # ═════════════════════════════════════════════════════════
    # COMPUTE ALL METRICS
    # ═════════════════════════════════════════════════════════

    # ── M1: Race pace per compound (best stint, all sessions) ─
    def _best_stint_for_driver(driver, compound):
        if fs is not None and not fs.empty and "Stint_Rank_Across_Sessions" in fs.columns:
            best_s = fs[
                (fs["Driver_Short"] == driver) &
                (fs["Compound"] == compound) &
                fs["Valid_Stint"] &
                (fs["Stint_Rank_Across_Sessions"] == 1)
            ]
            if not best_s.empty and "Stint_FuelCorr" in best_s.columns:
                v_ = pd.to_numeric(best_s["Stint_FuelCorr"], errors="coerce").dropna()
                if not v_.empty:
                    return float(v_.iloc[0])
        # Fallback: trimmed median of fuel-corrected (or raw) laps
        col = "LapTime_FuelCorrected" if "LapTime_FuelCorrected" in v_clean.columns else "LapTime_s"
        sub = v_clean[(v_clean["Driver_Short"] == driver) & (v_clean["Compound"] == compound)]
        if sub.empty:
            return np.nan
        t = sub[col].dropna()
        if t.empty:
            return np.nan
        lo, hi = t.quantile(0.10), t.quantile(0.90)
        trimmed = t[t.between(lo, hi)]
        return float(trimmed.median() if not trimmed.empty else t.median())

    race_pace_best_by_cmp: dict = {}
    race_pace_avg_by_cmp:  dict = {}
    for cmp in COMPOUNDS:
        bd, ad = {}, {}
        for team in teams_all:
            drvs = pairs[team]
            va = _best_stint_for_driver(drvs[0], cmp)
            vb = _best_stint_for_driver(drvs[1], cmp) if len(drvs) > 1 else np.nan
            b  = _best_of(va, vb, lower_is_better=True)
            a  = _avg_of(va, vb)
            if pd.notna(b):
                bd[team] = b
            if pd.notna(a):
                ad[team] = a
        if bd:
            race_pace_best_by_cmp[cmp] = bd
        if ad:
            race_pace_avg_by_cmp[cmp]  = ad

    # ── M2: Best lap overall (all sessions, all compounds) ────
    best_lap_best, best_lap_avg = _team_dicts(v, lambda s: s["LapTime_s"].min())

    # ── M3: NB laps – total ───────────────────────────────────
    laps_tot_best, laps_tot_avg = _team_dicts(
        v, lambda s: float(len(s)), lower_is_better=False)

    # ── M3b: NB laps – per session ────────────────────────────
    laps_per_sess_best: dict = {}
    laps_per_sess_avg:  dict = {}
    for sess in sorted(sess_names):
        pool = v[v["session_name"] == sess]
        if pool.empty:
            continue
        b, a = _team_dicts(pool, lambda s: float(len(s)), lower_is_better=False)
        laps_per_sess_best[sess] = b
        laps_per_sess_avg[sess]  = a

    # ── M4: Pit stop time (race/sprint only) ──────────────────
    pit_best: dict = {}
    pit_avg:  dict = {}
    if has_race and "PitIn" in fl.columns and "PitOut" in fl.columns:
        _race_laps = fl[fl["session_name"].isin(race_sess)].sort_values(
            ["session_name", "DriverNo", "LapNo"])
        _pit_rows: list = []
        for (sess, drv_no), grp in _race_laps.groupby(["session_name", "DriverNo"]):
            grp_s    = grp.sort_values("LapNo")
            in_laps  = grp_s[grp_s["InLap"]  & grp_s["PitIn"].notna()]
            out_laps = grp_s[grp_s["OutLap"] & grp_s["PitOut"].notna()]
            out_dict: dict = {}
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
                            _pit_rows.append({
                                "Driver_Short": inrow["Driver_Short"],
                                "Team":         inrow["Team"],
                                "dur":          dur,
                            })
                except Exception:
                    pass
        if _pit_rows:
            _pit_df = pd.DataFrame(_pit_rows)
            pit_best, pit_avg = _team_dicts(
                _pit_df, lambda s: s["dur"].mean(), lower_is_better=True)

    # ── M5: Qualifying performance ────────────────────────────
    quali_best: dict = {}
    quali_avg:  dict = {}
    if has_quali:
        _ql = fl[fl["session_name"].isin(quali_sess)]
        q_cols = [c for c in ("Q3_s", "Q2_s", "Q1_s") if c in fl.columns]

        def _best_q_for(driver):
            sub = _ql[_ql["Driver_Short"] == driver]
            if sub.empty:
                return np.nan
            for qc in q_cols:
                v_ = pd.to_numeric(sub[qc], errors="coerce").dropna()
                if not v_.empty:
                    return float(v_.iloc[0])
            bl = sub[sub["ValidLap"]]["LapTime_s"].dropna()
            return float(bl.min()) if not bl.empty else np.nan

        for team in teams_all:
            drvs = pairs[team]
            va = _best_q_for(drvs[0])
            vb = _best_q_for(drvs[1]) if len(drvs) > 1 else np.nan
            b  = _best_of(va, vb, lower_is_better=True)
            a  = _avg_of(va, vb)
            if pd.notna(b):
                quali_best[team] = b
            if pd.notna(a):
                quali_avg[team]  = a

    # ── M6: Race pace perf (race/sprint sessions only) ────────
    race_pace_perf_best: dict = {}
    race_pace_perf_avg:  dict = {}
    if has_race:
        v_race = v_clean[v_clean["session_name"].isin(race_sess)]

        def _race_perf_for(driver):
            if fs is not None and not fs.empty:
                fs_race = fs[
                    fs["session_name"].isin(race_sess) &
                    (fs["Driver_Short"] == driver) &
                    fs["Valid_Stint"]
                ]
                if not fs_race.empty and "Stint_Rep_Lap" in fs_race.columns:
                    best = fs_race["Stint_Rep_Lap"].dropna().min()
                    if pd.notna(best):
                        return float(best)
            sub = v_race[v_race["Driver_Short"] == driver]
            if sub.empty:
                return np.nan
            col = "LapTime_FuelCorrected" if "LapTime_FuelCorrected" in sub.columns else "LapTime_s"
            t   = sub[col].dropna()
            if t.empty:
                return np.nan
            lo, hi = t.quantile(0.10), t.quantile(0.90)
            trimmed = t[t.between(lo, hi)]
            return float(trimmed.median() if not trimmed.empty else t.median())

        for team in teams_all:
            drvs = pairs[team]
            va = _race_perf_for(drvs[0])
            vb = _race_perf_for(drvs[1]) if len(drvs) > 1 else np.nan
            b  = _best_of(va, vb, lower_is_better=True)
            a  = _avg_of(va, vb)
            if pd.notna(b):
                race_pace_perf_best[team] = b
            if pd.notna(a):
                race_pace_perf_avg[team]  = a

    # ── M7: Positions gained / lost (race/sprint only) ────────
    pgain_best: dict = {}
    pgain_avg:  dict = {}
    if has_race and "Classified_Position" in fl.columns:
        _rr = fl[fl["session_name"].isin(race_sess)].copy()
        _rr["_fin"]  = pd.to_numeric(_rr["Classified_Position"], errors="coerce")
        _rr["_grid"] = (
            pd.to_numeric(_rr["Grid_Position"], errors="coerce")
            if "Grid_Position" in _rr.columns else np.nan
        )
        _rr["_gain"] = _rr["_grid"] - _rr["_fin"]
        _rr_drv = (
            _rr.groupby(["session_name", "Driver_Short"])
            .agg(_gain=("_gain", "first"))
            .reset_index()
            .groupby("Driver_Short")["_gain"]
            .sum()
            .reset_index()
        )
        _drv_team_map = (
            fl[["Driver_Short", "Team"]].drop_duplicates("Driver_Short")
            .set_index("Driver_Short")["Team"].to_dict()
        )
        _rr_drv["Team"] = _rr_drv["Driver_Short"].map(_drv_team_map)

        for team in teams_all:
            drvs = pairs[team]
            sub_a = _rr_drv[_rr_drv["Driver_Short"] == drvs[0]]
            sub_b = (_rr_drv[_rr_drv["Driver_Short"] == drvs[1]]
                     if len(drvs) > 1 else pd.DataFrame())
            va = float(sub_a["_gain"].iloc[0]) if not sub_a.empty else np.nan
            vb = float(sub_b["_gain"].iloc[0]) if not sub_b.empty else np.nan
            b  = _best_of(va, vb, lower_is_better=False)   # higher gain = better
            a  = _avg_of(va, vb)
            if pd.notna(b):
                pgain_best[team] = b
            if pd.notna(a):
                pgain_avg[team]  = a


    # ─────────────────────────────────────────────────────────

    # ═════════════════════════════════════════════════════════
    # COLUMN HEADER HELPER
    # ═════════════════════════════════════════════════════════
    def _col_header(title, subtitle):
        return html.Div([
            html.H5(
                title,
                style={"color": ACCENT, "fontWeight": "800", "letterSpacing": "2px",
                       "marginBottom": "2px", "fontSize": "0.92rem", "textAlign": "center"},
            ),
            html.P(subtitle, style={"color": TEXT_DIM, "fontSize": "0.70rem",
                                     "textAlign": "center", "marginBottom": "14px"}),
            html.Hr(style={"borderColor": GRID_CLR, "marginBottom": "12px"}),
        ])

    def _maybe_card(title, fig, info=None):
        """Only add the card if the figure has at least one trace."""
        if fig and fig.data:
            return [card(title, dcc.Graph(figure=fig, config=GFX), info=info)]
        return []

    # ═════════════════════════════════════════════════════════
    # LEFT COLUMN  – best of 2 drivers
    # ═════════════════════════════════════════════════════════
    left_cards = [_col_header(
        "BEST OF 2 DRIVERS",
        "each metric uses the strongest driver per team",
    )]

    # Race pace per compound (all sessions)
    if race_pace_best_by_cmp:
        left_cards += _maybe_card(
            "Race Pace – Best Stint per Compound (all sessions)",
            _compound_bars(race_pace_best_by_cmp, "Race Pace – Best Stint",
                           fmt_fn=format_lap_time, lower_is_better=True),
            info=("Data: each team's stronger driver, fuel-corrected pace of their "
                  "best valid stint on each compound (all sessions). Bars show the % "
                  "gap to the fastest team on that compound. Why: the cleanest read "
                  "on true race-run pace, separated by tyre."),
        )

    # Best lap overall
    left_cards += _maybe_card(
        "Best Lap Overall (all sessions)",
        _hbar(best_lap_best, "Best Lap Time", fmt_fn=format_lap_time,
              lower_is_better=True, xlabel="Lap Time (s)"),
        info=("Data: the single fastest valid lap set by either driver of each team, "
              "across all sessions; bars show % gap to the fastest team. Why: a raw "
              "measure of ultimate one-lap car+driver performance."),
    )

    # NB laps – total
    left_cards += _maybe_card(
        "Total Valid Laps",
        _hbar(laps_tot_best, "Total Valid Laps",
              fmt_fn=lambda v: str(int(v)), lower_is_better=False, xlabel="Laps"),
        info=("Data: total valid laps completed by the team's busier driver. Why: a "
              "sample-size / reliability indicator — more laps means the other "
              "metrics for that team rest on more evidence."),
    )

    # NB laps – per session
    if laps_per_sess_best:
        _f = _session_laps_bar(laps_per_sess_best, "Valid Laps per Session")
        if _f and _f.data:
            left_cards.append(card("Laps per Session",
                                   dcc.Graph(figure=_f, config=GFX),
                                   info=("Data: valid laps per team (busier driver) "
                                         "broken down by session, as % gap to the team "
                                         "with most laps that session. Why: shows "
                                         "running programmes — who maximised track time "
                                         "in each practice / qualifying / race.")))

    if has_race:
        left_cards += _maybe_card(
            "Pit Stop Duration",
            _hbar(pit_best, "Avg Pit Stop", fmt_fn=lambda v: f"{v:.2f}s",
                  lower_is_better=True, xlabel="Avg Pit Stop (s)"),
            info=("Data: average stationary pit time (PitOut − PitIn of matched "
                  "in/out laps, 1.5–65 s) for the team's faster-stopping driver, "
                  "race/sprint only. Why: pit-crew performance, isolated from "
                  "on-track pace."),
        )

    if has_quali:
        left_cards += _maybe_card(
            "Qualifying Performance",
            _hbar(quali_best, "Best Quali Lap", fmt_fn=format_lap_time,
                  lower_is_better=True, xlabel="Best Quali Lap (s)"),
            info=("Data: best qualifying time (Q3→Q2→Q1 cascade) of the team's "
                  "quicker driver; bars show % gap to pole pace. Why: low-fuel, "
                  "max-attack single-lap performance — the purest car+driver speed."),
        )

    if has_race:
        left_cards += _maybe_card(
            "Race Pace (race/sprint sessions only)",
            _hbar(race_pace_perf_best, "Race Pace", fmt_fn=format_lap_time,
                  lower_is_better=True, xlabel="Race Pace (s)"),
            info=("Data: best representative stint pace of the team's stronger driver "
                  "in race/sprint sessions only (fuel-corrected). Why: actual race-day "
                  "pace, which can differ markedly from one-lap qualifying speed."),
        )
        left_cards += _maybe_card(
            "Positions Gained / Lost (race/sprint)",
            _hbar(pgain_best, "Positions Gained",
                  fmt_fn=lambda v: f"+{int(v)}" if v > 0 else str(int(v)),
                  lower_is_better=False, xlabel="Pos Gained (+) / Lost (−)",
                  pct_gap=False),
            info=("Data: grid position minus classified finish (summed over "
                  "race/sprint sessions), best result of the two drivers. Positive = "
                  "moved up. Why: captures race-craft and strategy, not just raw pace."),
        )

    # ═════════════════════════════════════════════════════════
    # RIGHT COLUMN  – average of 2 drivers
    # ═════════════════════════════════════════════════════════
    right_cards = [_col_header(
        "AVERAGE OF 2 DRIVERS",
        "NaN falls back to available driver — never forced to 0",
    )]

    if race_pace_avg_by_cmp:
        right_cards += _maybe_card(
            "Race Pace – Avg Best Stint per Compound",
            _compound_bars(race_pace_avg_by_cmp, "Race Pace – Avg Stint",
                           fmt_fn=format_lap_time, lower_is_better=True),
            info=("Same data as the left-column race-pace chart, but averaging both "
                  "drivers' best stint per compound instead of taking the best one. "
                  "Why: rewards teams with two strong cars, not just one standout; a "
                  "missing driver falls back to the available one (never forced to 0)."),
        )

    right_cards += _maybe_card(
        "Average Best Lap (all sessions)",
        _hbar(best_lap_avg, "Avg Best Lap", fmt_fn=format_lap_time,
              lower_is_better=True, xlabel="Avg Best Lap (s)"),
        info=("Data: mean of the two drivers' best valid laps per team. Why: a "
              "two-car measure of single-lap speed — penalises line-ups that lean "
              "on one quick driver."),
    )

    right_cards += _maybe_card(
        "Avg Valid Laps per Driver",
        _hbar(laps_tot_avg, "Avg Valid Laps",
              fmt_fn=lambda v: f"{v:.1f}", lower_is_better=False,
              xlabel="Avg Laps per Driver"),
        info=("Data: average number of valid laps per driver in the team. Why: "
              "shows typical track time per car (reliability / programme), not just "
              "the busier driver's total."),
    )

    if laps_per_sess_avg:
        _f = _session_laps_bar(laps_per_sess_avg, "Avg Laps per Session",
                               fmt_fn=lambda v: f"{v:.1f}")
        if _f and _f.data:
            right_cards.append(card("Avg Laps per Session",
                                    dcc.Graph(figure=_f, config=GFX),
                                    info=("Data: average valid laps per driver, split "
                                          "by session, as % gap to the busiest team. "
                                          "Why: per-session running programme on a "
                                          "two-car basis.")))

    if has_race:
        right_cards += _maybe_card(
            "Avg Pit Stop Duration",
            _hbar(pit_avg, "Avg Pit Stop", fmt_fn=lambda v: f"{v:.2f}s",
                  lower_is_better=True, xlabel="Avg Pit Stop (s)"),
            info=("Data: average stationary pit time across both drivers' stops "
                  "(race/sprint, 1.5–65 s window). Why: overall pit-crew consistency, "
                  "not just the single best stop."),
        )

    if has_quali:
        right_cards += _maybe_card(
            "Avg Qualifying Performance",
            _hbar(quali_avg, "Avg Quali Lap", fmt_fn=format_lap_time,
                  lower_is_better=True, xlabel="Avg Quali Lap (s)"),
            info=("Data: mean of both drivers' best qualifying times (Q3→Q2→Q1). "
                  "Why: a two-car view of single-lap speed."),
        )

    if has_race:
        right_cards += _maybe_card(
            "Avg Race Pace (race/sprint sessions only)",
            _hbar(race_pace_perf_avg, "Avg Race Pace", fmt_fn=format_lap_time,
                  lower_is_better=True, xlabel="Avg Race Pace (s)"),
            info=("Data: mean of both drivers' best representative race/sprint stint "
                  "pace (fuel-corrected). Why: sustained race pace measured across the "
                  "whole line-up."),
        )
        right_cards += _maybe_card(
            "Avg Positions Gained / Lost (race/sprint)",
            _hbar(pgain_avg, "Avg Pos Gained",
                  fmt_fn=lambda v: f"+{v:.1f}" if v > 0 else f"{v:.1f}",
                  lower_is_better=False, xlabel="Avg Pos Gained (+) / Lost (−)",
                  pct_gap=False),
            info=("Data: average grid-to-finish positions gained across both drivers. "
                  "Positive = the team typically moved up. Why: team-wide race-craft "
                  "and strategy outcome."),
        )

    # ═════════════════════════════════════════════════════════
    # ASSEMBLE LAYOUT
    # ═════════════════════════════════════════════════════════
    return html.Div([
        html.Hr(style={"borderColor": GRID_CLR, "margin": "8px 0 16px 0"}),
        dbc.Row([
            dbc.Col(
                html.Div(left_cards),
                md=6,
                style={
                    "borderRight": f"2px solid {GRID_CLR}",
                    "paddingRight": "14px",
                },
            ),
            dbc.Col(
                html.Div(right_cards),
                md=6,
                style={"paddingLeft": "14px"},
            ),
        ], className="g-0"),
    ])
