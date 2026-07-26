"""PRACTICE tab — weekend construction & sandbagging evidence.
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
from tabs.overview import overview_pace_cards

# mirror the mutable data state (SESSIONS, DRIVERS, telemetry, …) so the
# moved bodies keep their bare-name reads — repopulated on every reload
state.register(globals())





# ══════════════════════════════════════════════════════════════
#  PRACTICE / WEEKEND CONSTRUCTION + SANDBAGGING
# ══════════════════════════════════════════════════════════════
#  Designed to be useful mid-weekend: it works with practice sessions
#  alone (after FP1/FP2, after FP3) and gains a confirmation layer once
#  qualifying is loaded. The practice-native sandbag signal is "pace in
#  hand" (one-lap gap% − long-run gap%, both vs the field); when quali
#  exists it is corroborated by "pace unlocked" (practice → quali).
# ══════════════════════════════════════════════════════════════
_COMPOUND_RANK = {"SOFT": 0, "MEDIUM": 1, "HARD": 2, "INTER": 3, "WET": 4}

# Sandbagging flag thresholds (each crossed threshold = one 🚩)
_SB_HAND_THRESH = 0.30   # % one-lap gap worse than long-run gap (pace in hand)
_SB_BANK_THRESH = 0.40   # s of unassembled (banked) practice lap time
_SB_PACE_THRESH = 0.30   # % more relative pace unlocked Friday→Quali (needs quali)
_SB_TRAP_THRESH = 3.0    # km/h trap-speed gain Quali vs practice (needs quali)
_LONGRUN_MIN_LAPS = 5    # min non-quali-sim laps for a long-run pace estimate


def _practice_analysis(wl):
    """
    Build per-team weekend-construction / sandbagging evidence for the loaded
    event. Adapts to whatever sessions are present so it is meaningful after
    FP1/FP2 and after FP3, before qualifying has run.

    Every signal uses only clean laps (ValidLap & not Perturbed) so traffic,
    track-status and sector anomalies are never mistaken for hidden pace.

    Returns a dict with keys: team_df, banked_df, prog_df, has_quali,
    n_prac_sessions, event_label, flag_cols.
    """
    clean = wl[wl["ValidLap"] & ~wl["Perturbed_Lap"] & wl["LapTime_s"].notna()].copy()

    # Human-readable event label: "Practice 2_Australian Grand Prix_2026"
    event_label = ""
    if not wl.empty:
        parts = str(wl["session_name"].iloc[0]).split("_")
        if len(parts) >= 3:
            event_label = f"{parts[1]} {parts[2]}"

    prac = clean[clean["session_name"].str.startswith("Practice")]
    qual = clean[clean["session_name"].str.startswith("Qualifying")]
    pqs  = prac[prac["Is_Quali_Sim"]]
    has_quali = not qual.empty
    n_prac_sessions = prac["session_name"].nunique()

    # Long-run pool: clean practice laps that are NOT one-lap quali-sims and not
    # in/out laps — a proxy for race-run pace, fuel-corrected.
    lr = prac[~prac["Is_Quali_Sim"]].copy()
    for pit in ("PitOut", "PitIn"):
        if pit in lr.columns:
            lr = lr[~lr[pit].astype("boolean").fillna(False)]

    teams = sorted(clean["Team"].dropna().unique())
    rows = []
    for t in teams:
        pt  = prac[prac["Team"] == t]
        pqt = pqs[pqs["Team"] == t]
        qt  = qual[qual["Team"] == t]
        lrt = lr[lr["Team"] == t]
        prac_src = pqt if not pqt.empty else pt          # fall back if no quali-sim

        prac_best = prac_src["LapTime_s"].min() if not prac_src.empty else np.nan
        prac_trap = prac_src["Speed_ST"].max()  if not prac_src.empty else np.nan
        qual_best = qt["LapTime_s"].min()        if not qt.empty else np.nan
        qual_trap = qt["Speed_ST"].max()         if not qt.empty else np.nan

        longrun = (lrt["LapTime_FuelCorrected"].median()
                   if len(lrt) >= _LONGRUN_MIN_LAPS else np.nan)

        comps = [c for c in pqt["Compound"].dropna().unique()]
        softest = min(comps, key=lambda c: _COMPOUND_RANK.get(str(c).upper(), 9)) if comps else "—"
        ran_soft_qs = any(str(c).upper() == "SOFT" for c in comps)

        rows.append({
            "Team": t,
            "prac_best": prac_best, "qual_best": qual_best,
            "prac_trap": prac_trap, "qual_trap": qual_trap,
            "longrun": longrun, "n_qs": int(len(pqt)),
            "softest": softest, "ran_soft_qs": ran_soft_qs,
        })
    tdf = pd.DataFrame(rows)

    # ── Gaps to the field (self-cancels track evolution) ──
    field_prac = tdf["prac_best"].min(skipna=True) if not tdf.empty else np.nan
    field_lr   = tdf["longrun"].min(skipna=True)   if not tdf.empty else np.nan
    pole       = tdf["qual_best"].min(skipna=True) if has_quali else np.nan
    tdf["prac_gap_pct"]    = (tdf["prac_best"] / field_prac - 1) * 100 if pd.notna(field_prac) else np.nan
    tdf["longrun_gap_pct"] = (tdf["longrun"] / field_lr - 1) * 100     if pd.notna(field_lr) else np.nan
    tdf["qual_gap_pct"]    = (tdf["qual_best"] / pole - 1) * 100       if pd.notna(pole) else np.nan
    # Practice-native sandbag signal: relatively worse one-lap than race pace
    # ⇒ likely sitting on qualifying pace.
    tdf["pace_in_hand"] = tdf["prac_gap_pct"] - tdf["longrun_gap_pct"]
    # Quali confirmation (only when quali present)
    tdf["pace_unlocked"] = tdf["prac_gap_pct"] - tdf["qual_gap_pct"]
    tdf["trap_delta"]    = tdf["qual_trap"] - tdf["prac_trap"]

    # ── Banked time: best assembled lap vs sum of best sectors (practice) ──
    if not prac.empty:
        # Sector columns are float seconds from the parquet cache, but a
        # server that live-fetched part of the weekend can hold timedeltas
        # or a mixed object column — coerce to seconds before aggregating.
        bp_src = prac[["Driver_Short", "Team", "LapTime_s"]].copy()
        for col in ("Sector1Time", "Sector2Time", "Sector3Time"):
            s = prac[col] if col in prac.columns else pd.Series(np.nan, index=prac.index)
            if pd.api.types.is_timedelta64_dtype(s):
                s = s.dt.total_seconds()
            elif s.dtype == object:
                s = s.map(lambda v: v.total_seconds()
                          if isinstance(v, pd.Timedelta) else v)
            bp_src[col] = pd.to_numeric(s, errors="coerce")
        bp = (bp_src.groupby(["Driver_Short", "Team"])
              .agg(s1=("Sector1Time", "min"), s2=("Sector2Time", "min"),
                   s3=("Sector3Time", "min"), actual=("LapTime_s", "min"))
              .reset_index())
        bp["theo"]   = bp["s1"] + bp["s2"] + bp["s3"]
        bp["banked"] = (bp["actual"] - bp["theo"]).round(3)
        bp = bp[bp["theo"].notna() & (bp["banked"] >= 0)].sort_values("banked", ascending=False)
    else:
        bp = pd.DataFrame(columns=["Driver_Short", "Team", "theo", "actual", "banked"])

    team_bank = bp.groupby("Team")["banked"].max() if not bp.empty else pd.Series(dtype=float)
    tdf["team_banked"] = tdf["Team"].map(team_bank)

    # ── Flags ── practice-native always apply; quali flags add when present ──
    any_soft = bool(tdf["ran_soft_qs"].any())
    tdf["flag_hand"]   = tdf["pace_in_hand"] > _SB_HAND_THRESH
    tdf["flag_bank"]   = tdf["team_banked"]  > _SB_BANK_THRESH
    # "Hasn't shown one-lap pace": no soft-tyre quali-sim yet, but only counts
    # once at least one team has (i.e. the session is mature enough).
    tdf["flag_noshow"] = any_soft & (~tdf["ran_soft_qs"])
    flag_cols = ["flag_hand", "flag_bank", "flag_noshow"]
    if has_quali:
        tdf["flag_pace"] = tdf["pace_unlocked"] > _SB_PACE_THRESH
        tdf["flag_trap"] = tdf["trap_delta"]    > _SB_TRAP_THRESH
        flag_cols += ["flag_pace", "flag_trap"]
    tdf["flags"] = tdf[flag_cols].fillna(False).sum(axis=1).astype(int)

    # ── Pace progression (best quali-sim lap gap to that session's field) ──
    prog_rows = []
    for sess in ["Practice 1", "Practice 2", "Practice 3", "Qualifying"]:
        sd = clean[clean["session_name"].str.startswith(sess)]
        if sd.empty:
            continue
        src = sd[sd["Is_Quali_Sim"]] if sess != "Qualifying" else sd
        if src.empty:
            src = sd
        best  = src.groupby("Team")["LapTime_s"].min()
        field = best.min()
        for t, v in best.items():
            prog_rows.append({"session": sess, "Team": t,
                              "gap_pct": (v / field - 1) * 100})
    prog = pd.DataFrame(prog_rows)

    return {
        "team_df": tdf, "banked_df": bp, "prog_df": prog,
        "has_quali": has_quali, "n_prac_sessions": n_prac_sessions,
        "event_label": event_label, "flag_cols": flag_cols,
    }


def _sb_div_bar(df, valcol, xaxis_title, *, suffix="%", decimals=2, flags=True):
    """Team-coloured horizontal diverging bar with outside labels and headroom
    so the longest labels never clip. Returns None if no data."""
    d = df.dropna(subset=[valcol]).sort_values(valcol)
    if d.empty:
        return None
    fcol = d["flags"] if (flags and "flags" in d.columns) else [0] * len(d)
    ylabels = [f"{_abbr(t)}{'  🚩' if f >= 2 else ''}" for t, f in zip(d["Team"], fcol)]
    fig = go.Figure(go.Bar(
        x=d[valcol], y=ylabels, orientation="h",
        marker_color=[TEAM_COLORS.get(t, "#808080") for t in d["Team"]],
        text=[f"{v:+.{decimals}f}{suffix}" for v in d[valcol]],
        textposition="outside", textfont=dict(size=9, color=TEXT_MAIN),
        customdata=d["Team"],
        hovertemplate="%{customdata}: %{x:+." + str(decimals) + "f}" + suffix + "<extra></extra>"))
    theme(fig, max(240, len(d) * 40 + 110), "")
    fig.add_vline(x=0, line_color=TEXT_DIM, line_width=1)
    vmax = d[valcol].abs().max() or 1
    fig.update_layout(showlegend=False, xaxis_title=xaxis_title,
        margin=dict(l=110, r=95, t=20, b=44),
        xaxis_range=[d[valcol].min() - vmax * 0.55, d[valcol].max() + vmax * 0.55])
    return fig


def _sb_quadrant(df, xcol, ycol, xtitle, ytitle, below_note):
    """Team-coloured scatter against a y=x parity line."""
    qd = df.dropna(subset=[xcol, ycol])
    fig = go.Figure()
    if not qd.empty:
        m = float(max(qd[xcol].max(), qd[ycol].max(), 0.1)) * 1.12
        fig.add_trace(go.Scatter(x=[0, m], y=[0, m], mode="lines",
            line=dict(color=TEXT_DIM, dash="dash"), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=qd[xcol], y=qd[ycol], mode="markers+text",
            text=[_abbr(t) for t in qd["Team"]], textposition="top center",
            textfont=dict(size=10, color=TEXT_MAIN),
            marker=dict(size=14, color=[TEAM_COLORS.get(t, "#808080") for t in qd["Team"]],
                        line=dict(width=1, color="#000")),
            customdata=qd["Team"],
            hovertemplate="%{customdata}<br>+%{x:.2f}%  /  +%{y:.2f}%<extra></extra>"))
        fig.add_annotation(x=m * 0.72, y=m * 0.16, text=below_note,
            showarrow=False, font=dict(color=ACCENT, size=11))
    theme(fig, 430, "")
    fig.update_layout(showlegend=False, xaxis_title=xtitle, yaxis_title=ytitle,
        margin=dict(l=60, r=30, t=20, b=44))
    return fig


def tab_practice_construction(wl):
    """PRACTICE CONSTRUCTION — how the weekend is being built: the two headline
    pace cards (lap-time distribution + driver performance matrix, shared with
    the TELEMETRY overview) followed by the session-to-session pace progression."""
    if wl is None or wl.empty:
        return html.P("No lap data for the current selection.",
                      style={"color": TEXT_DIM})

    body = list(overview_pace_cards(wl))

    # ── Pace progression across the sessions present ────────────
    prog = _practice_analysis(wl)["prog_df"]
    if not prog.empty:
        order = [s for s in ["Practice 1", "Practice 2", "Practice 3", "Qualifying"]
                 if s in prog["session"].unique()]
        fig_p = go.Figure()
        for t in sorted(prog["Team"].unique()):
            sub = (prog[prog["Team"] == t].set_index("session")
                   .reindex(order).reset_index())
            fig_p.add_trace(go.Scatter(
                x=sub["session"], y=sub["gap_pct"], mode="lines+markers",
                name=_abbr(t), connectgaps=True,
                line=dict(color=TEAM_COLORS.get(t, "#808080"), width=2),
                marker=dict(size=7),
                hovertemplate=f"{_abbr(t)} · %{{x}}<br>+%{{y:.2f}}%<extra></extra>"))
        theme(fig_p, 460, "")
        fig_p.update_layout(
            xaxis_title="", yaxis_title="Gap to session-best  (%)  ·  lower = faster",
            legend=dict(orientation="h", x=0, y=1.12, bgcolor="rgba(0,0,0,0)"),
            margin=dict(l=60, r=30, t=40, b=30))
        fig_p.update_yaxes(autorange="reversed")
        body.append(dbc.Row([dbc.Col(card("PACE PROGRESSION",
            dcc.Graph(figure=fig_p, config=GFX),
            info="Each team's best quali-sim lap per session (best valid lap in qualifying), as a gap to that session's fastest. Y-axis inverted so rising lines = relative improvement. Shows the build trajectory across the weekend."), md=12)]))

    return html.Div(body)


def tab_sandbagging(wl):
    """SANDBAGGING DETECTOR — who is holding pace back. Pace-in-hand scoreboard,
    banked time, the quali confirmation layer and the full evidence table."""
    if wl is None or wl.empty:
        return html.P("No lap data for the current selection.",
                      style={"color": TEXT_DIM})

    a = _practice_analysis(wl)
    tdf, bp = a["team_df"], a["banked_df"]
    has_quali = a["has_quali"]
    phase = ("Full weekend (quali loaded)" if has_quali
             else f"Practice in progress · {a['n_prac_sessions']} session(s) so far")

    # ── KPI strip (adapts to phase) ─────────────────────────────
    kpis = []
    if tdf["pace_in_hand"].notna().any():
        toph = tdf.loc[tdf["pace_in_hand"].idxmax()]
        kpis.append(kpi("MOST PACE IN HAND", f"{_abbr(toph['Team'])}  +{toph['pace_in_hand']:.2f}%",
                        tooltip="Largest gap between a team's one-lap deficit and its race-run deficit — relatively stronger on long runs than on a single lap, i.e. likely sitting on qualifying pace."))
    if has_quali and tdf["pace_unlocked"].notna().any():
        topu = tdf.loc[tdf["pace_unlocked"].idxmax()]
        kpis.append(kpi("MOST PACE UNLOCKED", f"{_abbr(topu['Team'])}  +{topu['pace_unlocked']:.2f}%",
                        color="#FFD700",
                        tooltip="Largest relative one-lap improvement from practice quali-sims to qualifying — confirms hidden pace."))
    if not bp.empty:
        topb = bp.iloc[0]
        kpis.append(kpi("MOST BANKED TIME", f"{topb['Driver_Short']}  {topb['banked']:.2f}s",
                        color="#39B54A",
                        tooltip="Largest gap between a driver's best practice lap and the sum of their best sectors — pace available but never assembled."))
    n_flagged = int((tdf["flags"] >= 2).sum())
    kpis.append(kpi("FLAGGED TEAMS", str(n_flagged),
                    color=ACCENT if n_flagged else TEXT_MAIN,
                    tooltip="Teams crossing ≥2 sandbag signals (pace in hand, banked time, no soft-tyre run shown" + (", pace unlocked, trap gain" if has_quali else "") + ")."))
    kpi_row = dbc.Row(kpis, className="mb-2")

    phase_pill = html.Div(html.Span(phase, style={
        "background": (ACCENT if has_quali else "#0055BB"), "color": "#fff",
        "borderRadius": "4px", "padding": "3px 10px", "fontSize": "0.72rem",
        "fontWeight": "700", "letterSpacing": "0.5px"}),
        style={"marginBottom": "14px"})

    body = [kpi_row, phase_pill]

    # ── Headline: pace in hand + one-lap-vs-long-run quadrant ───
    fig_hand = _sb_div_bar(tdf, "pace_in_hand",
        "Pace in hand  (%)   ·   + = relatively faster on race runs than one lap")
    fig_olr = _sb_quadrant(tdf, "prac_gap_pct", "longrun_gap_pct",
        "Best one-lap gap to field  (%)", "Race-run gap to field  (%)",
        "below line = one-lap pace in hand")
    head_cols = []
    if fig_hand is not None:
        head_cols.append(dbc.Col(card([*gloss("sandbagging", "SANDBAG"),
            " SCOREBOARD · PACE IN HAND"],
            dcc.Graph(figure=fig_hand, config=GFX),
            info="One-lap gap to field minus race-run gap to field. Positive = the team is relatively further back on a single lap than on long runs, a classic sign of qualifying pace held in reserve. 🚩 = ≥2 sandbag signals."), md=6))
    head_cols.append(dbc.Col(card([*gloss("one-lap pace", "ONE-LAP"), " vs ",
        *gloss("race pace", "RACE-RUN")],
        dcc.Graph(figure=fig_olr, config=GFX),
        info="Each team's best practice one-lap gap (x) vs its fuel-corrected race-run gap (y), both relative to the field. Markers below the parity line are stronger on long runs than on one lap — one-lap pace likely in hand."),
        md=6 if fig_hand is not None else 12))
    body.append(dbc.Row(head_cols))

    # ── Banked time (per driver) ────────────────────────────────
    if not bp.empty:
        bb = bp.head(24)
        fig_b = go.Figure(go.Bar(
            x=bb["banked"], y=bb["Driver_Short"], orientation="h",
            marker_color=[TEAM_COLORS.get(t, "#808080") for t in bb["Team"]],
            text=[f"{v:.2f}s" for v in bb["banked"]],
            textposition="outside", textfont=dict(size=9, color=TEXT_MAIN),
            customdata=bb["Team"],
            hovertemplate="%{y} (%{customdata})<br>banked %{x:.2f}s<extra></extra>"))
        theme(fig_b, max(260, len(bb) * 26 + 110), "")
        fig_b.update_layout(showlegend=False,
            xaxis_title="Unassembled practice lap time  (s)  =  best lap − sum of best sectors",
            margin=dict(l=60, r=70, t=20, b=44),
            xaxis_range=[0, (bb["banked"].max() or 0.5) * 1.18])
        fig_b.update_yaxes(autorange="reversed")
        body.append(dbc.Row([dbc.Col(card("BANKED TIME · PRACTICE (per driver)",
            dcc.Graph(figure=fig_b, config=GFX),
            info="Best assembled practice lap minus the sum of the driver's best sectors. Large values mean the pace was there but never put together on one lap — sometimes deliberate."), md=12)]))

    # ── Quali confirmation layer (only once qualifying is loaded) ──
    if has_quali:
        fig_sc = _sb_div_bar(tdf, "pace_unlocked",
            "Pace unlocked Friday → Quali  (%)   ·   + = hid pace in practice")
        fig_q = _sb_quadrant(tdf, "prac_gap_pct", "qual_gap_pct",
            "Practice quali-sim gap to field  (%)", "Qualifying gap to pole  (%)",
            "below line = hid pace")
        conf_cols = []
        if fig_sc is not None:
            conf_cols.append(dbc.Col(card("CONFIRMATION · PACE UNLOCKED",
                dcc.Graph(figure=fig_sc, config=GFX),
                info="Practice quali-sim gap% minus qualifying gap%, both vs the field. Positive = the team was relatively further back in practice than in qualifying — hidden pace, now confirmed."), md=6))
        conf_cols.append(dbc.Col(card([*gloss("practice", "PRACTICE"), " vs ",
            *gloss("qualifying", "QUALIFYING")],
            dcc.Graph(figure=fig_q, config=GFX),
            info="Each team's best practice quali-sim gap (x) vs its qualifying gap to pole (y). Markers below the parity line qualified relatively better than they ran in practice."),
            md=6 if fig_sc is not None else 12))
        body.append(dbc.Row(conf_cols))

        td = tdf.dropna(subset=["trap_delta"]).sort_values("trap_delta")
        if not td.empty:
            fig_t = go.Figure(go.Bar(
                x=td["trap_delta"], y=[_abbr(t) for t in td["Team"]], orientation="h",
                marker_color=[TEAM_COLORS.get(t, "#808080") for t in td["Team"]],
                text=[f"{v:+.1f}" for v in td["trap_delta"]],
                textposition="outside", textfont=dict(size=9, color=TEXT_MAIN),
                customdata=td["Team"], hovertemplate="%{customdata}: %{x:+.1f} km/h<extra></extra>"))
            theme(fig_t, max(240, len(td) * 40 + 110), "")
            fig_t.add_vline(x=0, line_color=TEXT_DIM, line_width=1)
            _tmax = td["trap_delta"].abs().max() or 1
            fig_t.update_layout(showlegend=False,
                xaxis_title="Top-speed gain Quali vs Practice  (km/h)   ·   + = held PU back Friday",
                margin=dict(l=90, r=80, t=20, b=44),
                xaxis_range=[td["trap_delta"].min() - _tmax * 0.32,
                             td["trap_delta"].max() + _tmax * 0.3])
            body.append(dbc.Row([dbc.Col(card("ENGINE-MODE EVIDENCE · SPEED TRAP",
                dcc.Graph(figure=fig_t, config=GFX),
                info="Max speed-trap reading in qualifying minus the max on practice quali-sim laps. A large positive gap suggests the team ran reduced power modes in practice."), md=12)]))

    # ── Evidence table (columns adapt to phase) ─────────────────
    tt = tdf.sort_values("flags", ascending=False).copy()
    def _fmt(v, suf="", plus=False):
        if pd.isna(v):
            return "—"
        return (f"{v:+.2f}{suf}" if plus else f"{v:.2f}{suf}")
    recs = []
    for _, r in tt.iterrows():
        rec = {
            "Team": r["Team"],
            "One-lap gap%":  _fmt(r["prac_gap_pct"], "%"),
            "Race-run gap%": _fmt(r["longrun_gap_pct"], "%"),
            "Pace in hand":  _fmt(r["pace_in_hand"], "%", plus=True),
            "Banked (s)":    _fmt(r["team_banked"], "s"),
            "# quali-sims":  int(r["n_qs"]),
            "Softest":       r["softest"],
        }
        if has_quali:
            rec["Quali gap%"]    = _fmt(r["qual_gap_pct"], "%")
            rec["Pace unlocked"] = _fmt(r["pace_unlocked"], "%", plus=True)
            rec["Δ trap (km/h)"] = _fmt(r["trap_delta"], "", plus=True)
        rec["Flags"] = "🚩" * int(r["flags"]) if r["flags"] else "—"
        recs.append(rec)
    table = dash_table.DataTable(
        data=recs,
        columns=[{"name": c, "id": c} for c in recs[0].keys()] if recs else [],
        **TABLE_STYLE,
        style_data_conditional=[
            {"if": {"filter_query": "{Flags} contains '🚩🚩'"},
             "backgroundColor": ACCENT + "22", "fontWeight": "700"},
        ],
    )
    _thresh = ("pace in hand >0.30%, banked >0.40s, no soft-tyre run shown"
               + (", pace unlocked >0.30%, trap gain >3 km/h" if has_quali else ""))
    body.append(card("EVIDENCE TABLE", table,
        info=f"All signals per team. Flags fire at {_thresh}. Sortable — click a header."))

    return html.Div(body)
