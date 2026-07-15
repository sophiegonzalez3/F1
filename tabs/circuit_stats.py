"""Measured circuit stats for the TRACK tab.

Three cards, all built from data the archive already measures (no curated
ratings):

  measured_weekend_card  – what actually happened in the archived races at
                           this circuit: SC/VSC rates, on-track passes, pit
                           loss, lap-1 swing, wet races, track-limits
                           deletions (with the corner hotspots), plus a
                           per-year detail table with the winner's strategy.
  pole_evolution_card    – pole time per archived season (HIST_QUALI).
  tyre_allocation_card   – the Pirelli C-compound nomination per year
                           (data/tyre_allocations.csv).
  pirelli_card           – Pirelli's own view of the circuit (asphalt
                           abrasion / grip / evolution / tyre stress and a
                           quote), curated from the official race-preview
                           press releases into data/pirelli_ratings.csv.

The measured card is the empirical companion of track.py's curated
"Race Weekend Guide" — same questions, real numbers.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, dash_table

from f1lib.components import card, theme, GFX
from f1lib.config import (
    HIST_CIRCUIT_KEY_MAP, COMPOUND_COLORS, TEAM_COLORS,
    CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
)
from f1lib.processing import format_lap_time
from tabs.race_stats_data import race_stats_df, track_limits_df


def _slugify(name) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


_EVENT_TO_CIRCUIT = {
    _slugify(hist): fr
    for fr, hists in HIST_CIRCUIT_KEY_MAP.items() for hist in hists
}


def _pill(label, value, color=None, sub=None):
    body = [
        html.P(label, style={"color": TEXT_DIM, "fontSize": "0.65rem",
                             "letterSpacing": "1px", "marginBottom": "2px",
                             "fontWeight": "600"}),
        html.P(value, style={"color": color or TEXT_MAIN, "fontSize": "0.95rem",
                             "fontWeight": "800", "marginBottom": 0}),
    ]
    if sub:
        body.append(html.P(sub, style={"color": TEXT_DIM, "fontSize": "0.62rem",
                                       "marginBottom": 0}))
    return html.Div(body, style={
        "background": CARD_BG, "border": f"1px solid {GRID_CLR}",
        "borderRadius": "6px", "padding": "8px 14px", "textAlign": "center",
        "flex": "1", "minWidth": "120px",
    })


def _rate_color(per_race: float) -> str:
    return ("#E10600" if per_race >= 1.5 else
            "#FFD700" if per_race >= 0.7 else "#2ECC71")


# ─────────────────────────────────────────────────────────────
# Measured weekend card
# ─────────────────────────────────────────────────────────────

def measured_weekend_card(circuit_key: str) -> html.Div | None:
    df = race_stats_df()
    if df.empty or "circuit_key" not in df.columns:
        return None
    s = df[df["circuit_key"] == circuit_key].sort_values("season")
    if s.empty:
        return None
    n = len(s)

    sc_rate = float(s["sc_count"].mean())
    vsc_rate = float(s["vsc_count"].mean())
    ot = s["overtakes"].dropna()
    pit = s["pit_loss_s"].dropna()
    stat = s["pit_stationary_med_s"].dropna()
    l1 = s["lap1_avg_swing"].dropna()
    # robust to the CSV round-trip: the column is bool today but becomes
    # object (bool/str/NaN mix) as soon as one race lacks weather data
    wet = s["rain"].astype(str).eq("True")
    dele = s["deleted_laps"].dropna()

    pills = [
        _pill("SC / VSC PER RACE", f"{sc_rate:.1f} · {vsc_rate:.1f}",
              _rate_color(sc_rate + 0.5 * vsc_rate),
              f"{int(s['red_flags'].sum())} red flag(s) in {n} races"),
    ]
    if len(ot):
        pills.append(_pill("ON-TRACK PASSES", f"~{ot.median():.0f} /race"))
    if len(pit):
        sub = f"{stat.median():.1f} s stationary" if len(stat) else None
        pills.append(_pill("PIT LOSS", f"≈{pit.median():.0f} s", "#00D2BE", sub))
    if len(l1):
        pills.append(_pill("LAP-1 SWING", f"±{l1.mean():.1f} places"))
    pills.append(_pill("WET RACES", f"{int(wet.sum())} of {n}",
                       "#00B4D8" if wet.any() else None))
    if len(dele):
        pills.append(_pill("LAPS DELETED", f"~{dele.mean():.0f} /race",
                           "#FFD700" if dele.mean() >= 15 else None))

    children = [html.Div(pills, style={
        "display": "flex", "gap": "10px", "flexWrap": "wrap",
        "marginBottom": "10px"})]

    # Track-limits hotspots (summed over the archived races)
    tl = track_limits_df()
    if not tl.empty and (tl["circuit_key"] == circuit_key).any():
        top = (tl[tl["circuit_key"] == circuit_key]
               .groupby("turn")["deleted"].sum()
               .sort_values(ascending=False).head(3))
        children.append(html.P([
            html.Span("Track-limits hotspots — ",
                      style={"color": TEXT_MAIN, "fontWeight": "700"}),
            " · ".join(f"T{int(t)} ×{int(v)}" for t, v in top.items()),
            f"  (laps deleted, all {n} archived races)",
        ], style={"color": TEXT_DIM, "fontSize": "0.78rem",
                  "marginBottom": "10px"}))

    # Per-year detail table
    rows = []
    for r in s.itertuples():
        rows.append({
            "year": int(r.season),
            "sc": f"{int(r.sc_count)} ({int(r.sc_laps)} laps)"
                  if r.sc_count else "—",
            "vsc": int(r.vsc_count) or "—",
            "red": int(r.red_flags) or "—",
            "passes": int(r.overtakes) if pd.notna(r.overtakes) else "—",
            "wet": "🌧" if str(r.rain) == "True" else "",
            "temps": (f"{r.airtemp_c:.0f} / {r.tracktemp_c:.0f} °C"
                      if pd.notna(r.airtemp_c) else "—"),
            "winner": f"{r.winner}  {r.winner_strategy}",
            "stops": (f"{int(r.stops_mode)}-stop"
                      + (f" ({r.one_stop_pct:.0f}% 1-stop)"
                         if pd.notna(r.one_stop_pct) else "")
                      if pd.notna(r.stops_mode) else "—"),
        })
    table = dash_table.DataTable(
        data=rows,
        columns=[{"name": c.upper(), "id": c} for c in
                 ("year", "sc", "vsc", "red", "passes", "wet", "temps",
                  "winner", "stops")],
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": CARD_BG, "color": TEXT_MAIN,
                    "border": f"1px solid {GRID_CLR}", "fontSize": "12px",
                    "padding": "5px 9px", "textAlign": "left",
                    "whiteSpace": "nowrap"},
        style_header={"backgroundColor": "#111", "color": TEXT_DIM,
                      "fontWeight": "700", "fontSize": "10px",
                      "letterSpacing": "1px",
                      "border": f"1px solid {GRID_CLR}"},
    )
    children.append(table)

    return card(
        f"What Actually Happened Here — {n} archived race(s)",
        html.Div(children),
        info=("Data: measured from the archived races at this circuit "
              "(scripts/compute_race_stats.py). Safety cars and VSCs are "
              "track-status deployments; passes are green-flag on-track "
              "overtakes (lap-chart method: lap 1, pit cycles and non-green "
              "laps excluded); pit loss is the median green-flag time cost "
              "of a stop vs the driver's clean pace; lap-1 swing is the "
              "mean absolute position change on the opening lap; the "
              "winner's strategy reads compound + stint length. Why: the "
              "curated weekend guide above says what is *typical* — this "
              "card shows what the data actually recorded, year by year."),
    )


# ─────────────────────────────────────────────────────────────
# Pole-time evolution
# ─────────────────────────────────────────────────────────────

def pole_evolution_card(circuit_key: str, hist_quali: pd.DataFrame) -> html.Div | None:
    if hist_quali is None or hist_quali.empty \
            or "circuit_key" not in hist_quali.columns:
        return None
    keys = HIST_CIRCUIT_KEY_MAP.get(circuit_key, [circuit_key])
    sub = hist_quali[hist_quali["circuit_key"].isin(keys)].copy()
    if sub.empty:
        return None

    qcols = [c for c in ("Q1", "Q2", "Q3") if c in sub.columns]
    if not qcols:
        return None
    sub["best"] = sub[qcols].min(axis=1)
    abbr_col = next((c for c in ("Abbreviation", "DriverId", "Driver")
                     if c in sub.columns), None)
    team_col = next((c for c in ("TeamName", "ConstructorName", "Team")
                     if c in sub.columns), None)

    rows = []
    for season, g in sub.groupby("season"):
        g = g.dropna(subset=["best"])
        if g.empty:
            continue
        r = g.loc[g["best"].idxmin()]
        rows.append({"season": int(season), "t": float(r["best"]),
                     "driver": str(r[abbr_col]) if abbr_col else "?",
                     "team": str(r[team_col]) if team_col else ""})
    if len(rows) < 2:
        return None
    d = pd.DataFrame(rows).sort_values("season")

    fig = go.Figure(go.Scatter(
        x=d["season"], y=d["t"], mode="lines+markers+text",
        line=dict(color=ACCENT, width=2),
        marker=dict(size=10,
                    color=[TEAM_COLORS.get(t, "#808080") for t in d["team"]],
                    line=dict(color="#000", width=1)),
        text=[f"{r.driver}<br>{format_lap_time(r.t)}" for r in d.itertuples()],
        textposition="top center", textfont=dict(size=9, color=TEXT_DIM),
        customdata=np.stack([d["driver"], d["team"],
                             [format_lap_time(t) for t in d["t"]]], axis=-1),
        hovertemplate=("<b>%{x}</b> · %{customdata[0]} (%{customdata[1]})"
                       "<br>Pole: %{customdata[2]}<extra></extra>"),
        showlegend=False,
    ))
    theme(fig, 320, "Pole time by season")
    pad = max((d["t"].max() - d["t"].min()) * 0.25, 0.4)
    fig.update_yaxes(title_text="Pole lap (s)",
                     range=[d["t"].min() - pad, d["t"].max() + pad])
    fig.update_xaxes(tickmode="array", tickvals=d["season"].tolist(),
                     ticktext=[str(y) for y in d["season"]])

    return card(
        "Pole-Time Evolution",
        dcc.Graph(figure=fig, config=GFX),
        info=("Data: the fastest single qualifying lap (best of Q1/Q2/Q3, any "
              "driver) for every archived season at this circuit, marker "
              "coloured by the pole-sitter's team. Why: pole pace across the "
              "years shows car development, regulation resets (2022, 2026) "
              "and resurfacing effects at this venue in one line."),
    )


# ─────────────────────────────────────────────────────────────
# Tyre allocation history
# ─────────────────────────────────────────────────────────────

def tyre_allocation_card(circuit_key: str) -> html.Div | None:
    from f1lib.tyre_allocations import _tyre_allocations
    df = _tyre_allocations()
    if df.empty:
        return None
    d = df[df["event"].map(lambda e: _EVENT_TO_CIRCUIT.get(_slugify(e)))
           == circuit_key].sort_values("season", ascending=False)
    if d.empty:
        return None

    def _chip(compound, cnum):
        clr = COMPOUND_COLORS.get(compound.upper(), "#808080")
        return html.Span(f"{compound[0].upper()} {cnum}", style={
            "border": f"2px solid {clr}", "color": clr, "borderRadius": "10px",
            "padding": "1px 9px", "fontSize": "0.72rem", "fontWeight": "700",
            "marginRight": "6px"})

    rows = [html.Div([
        html.Span(str(int(r.season)), style={
            "color": TEXT_MAIN, "fontWeight": "800", "fontSize": "0.8rem",
            "width": "46px", "display": "inline-block"}),
        _chip("HARD", r.hard), _chip("MEDIUM", r.medium), _chip("SOFT", r.soft),
    ], style={"marginBottom": "6px"}) for r in d.itertuples()]

    return card(
        "Pirelli Compound Nomination by Year",
        html.Div(rows),
        info=("Data: the Pirelli C-compound allocation (hard/medium/soft) "
              "nominated for this event each season, from "
              "data/tyre_allocations.csv. Why: a softer or harder nomination "
              "than last year changes the whole strategy picture — compare "
              "with the winner's strategy in the measured card above."),
    )


# ─────────────────────────────────────────────────────────────
# Pirelli's view of the circuit
# ─────────────────────────────────────────────────────────────

_PIR_PATH = Path("data/pirelli_ratings.csv")
_PIR_CACHE: dict = {"mtime": None, "df": pd.DataFrame()}

_LEVEL_COLORS = {
    "low": "#2ECC71", "medium-low": "#A3E635", "medium": "#FFD700",
    "medium-high": "#FB923C", "high": "#E10600", "very high": "#E10600",
}


def pirelli_df() -> pd.DataFrame:
    try:
        mtime = _PIR_PATH.stat().st_mtime if _PIR_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _PIR_CACHE["mtime"]:
        try:
            _PIR_CACHE["df"] = (pd.read_csv(_PIR_PATH).fillna("")
                                if mtime else pd.DataFrame())
        except Exception:
            _PIR_CACHE["df"] = pd.DataFrame()
        _PIR_CACHE["mtime"] = mtime
    return _PIR_CACHE["df"]


def _level_chip(label: str, value: str) -> html.Div:
    clr = _LEVEL_COLORS.get(str(value).strip().lower(), TEXT_MAIN)
    return html.Div([
        html.P(label, style={"color": TEXT_DIM, "fontSize": "0.65rem",
                             "letterSpacing": "1px", "marginBottom": "2px",
                             "fontWeight": "600"}),
        html.P(value or "—", style={"color": clr, "fontSize": "0.9rem",
                                    "fontWeight": "800", "marginBottom": 0}),
    ], style={
        "background": CARD_BG, "border": f"1px solid {GRID_CLR}",
        "borderRadius": "6px", "padding": "8px 14px", "textAlign": "center",
        "flex": "1", "minWidth": "120px",
    })


def pirelli_card(circuit_key: str) -> html.Div | None:
    df = pirelli_df()
    if df.empty or "circuit_key" not in df.columns:
        return None
    d = df[df["circuit_key"] == circuit_key]
    if d.empty:
        return None
    r = d.sort_values("season").iloc[-1]

    chips = html.Div([
        _level_chip("ASPHALT ABRASION", r.get("abrasion", "")),
        _level_chip("ASPHALT GRIP", r.get("grip", "")),
        _level_chip("TRACK EVOLUTION", r.get("evolution", "")),
        _level_chip("TYRE STRESS", r.get("tyre_stress", "")),
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap",
              "marginBottom": "10px"})

    children = [chips]
    if r.get("key_challenge"):
        children.append(html.P([
            html.Span("Key demand — ", style={"color": TEXT_MAIN,
                                              "fontWeight": "700"}),
            str(r["key_challenge"]),
        ], style={"color": TEXT_DIM, "fontSize": "0.8rem",
                  "marginBottom": "8px", "lineHeight": "1.45"}))
    if r.get("pirelli_notes"):
        children.append(html.P([
            str(r["pirelli_notes"]),
            html.Span(f"  (summarised from Pirelli's {r.get('season', '')} "
                      "race-preview material)",
                      style={"fontSize": "0.68rem", "fontStyle": "italic"}),
        ], style={"color": TEXT_DIM, "fontSize": "0.78rem",
                  "marginBottom": 0, "lineHeight": "1.45",
                  "borderLeft": f"3px solid {GRID_CLR}",
                  "paddingLeft": "10px"}))

    return card(
        "Pirelli's View of the Circuit",
        html.Div(children),
        info=("Data: curated from Pirelli's official race-preview press "
              "releases (press.pirelli.com, source link in "
              "data/pirelli_ratings.csv) — the tyre maker's own read of the "
              "asphalt (abrasion, grip, weekend evolution) and how hard the "
              "circuit works its tyres, plus the demand Pirelli singles "
              "out. Why: this is the supplier's ground truth behind the "
              "compound nomination above — it explains WHY the C-levels "
              "and pressures are what they are, independent of our own "
              "telemetry-derived profile."),
    )
