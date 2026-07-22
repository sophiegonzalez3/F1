"""
Cornering Speed by Corner Class — OVERVIEW (TELEMETRY tab).

Replaces the old "Cornering Speed by Track Region" heatmap, which was broken:
it bucketed raw telemetry samples by their OWN speed and then reported the
average speed within each bucket — a tautology bounded by the bucket, polluted
by pit-lane / safety-car / out-lap samples (it showed apex "speeds" of ~25 km/h)
and blind to where the actual corners are.

This card instead works from the real corners of the circuit:

  • each numbered corner is classified slow / medium / fast by its apex speed,
    using GLOBAL thresholds derived once from a whole season
    (scripts/compute_corner_classes.py → data/corner_speed_classes.json) so the
    classes mean the same km/h at every event — a car quicker in slow corners
    than at the previous round is a real gain, not a shifted definition;
  • each driver's apex (minimum) speed through every corner comes from their
    best lap, and is averaged within each class for the ranking.

Visual: the track map with corners coloured + labelled by class, and a side
panel of team-coloured ranking bars for the selected class.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, callback, no_update, ctx, ALL, Input, Output, State

import f1lib.state as state
from f1lib.components import theme, card, GFX, hex_to_rgba as _hex_to_rgba
from f1lib.config import TEAM_COLORS, CARD_BG, TEXT_MAIN, TEXT_DIM

logger = logging.getLogger(__name__)

APEX_WINDOW_M = 40.0
_CLASSES_PATH = Path("data/corner_speed_classes.json")

# Baked fallback = the 2025-season tertiles, used if the data file is absent.
_FALLBACK = {"slow_max_kmh": 146.0, "fast_min_kmh": 238.0, "season": 2025}

# class → (label, colour). Colours read as a slow→fast temperature ramp and are
# distinct from any team colour.
CLASS_SLOW, CLASS_MED, CLASS_FAST = "slow", "medium", "fast"
_CLASS_META = {
    CLASS_SLOW: ("Slow", "#4C8CF5"),      # blue   = low-speed / traction
    CLASS_MED:  ("Medium", "#B98CE0"),    # violet
    CLASS_FAST: ("Fast", "#F2683C"),      # orange = high-speed / commitment
}
_CLASS_ORDER = [CLASS_SLOW, CLASS_MED, CLASS_FAST]

_MEMO: dict[str, dict] = {}


def _thresholds() -> dict:
    try:
        d = json.loads(_CLASSES_PATH.read_text())
        return {"slow_max": float(d["slow_max_kmh"]),
                "fast_min": float(d["fast_min_kmh"]),
                "season": d.get("season")}
    except Exception:
        return {"slow_max": _FALLBACK["slow_max_kmh"],
                "fast_min": _FALLBACK["fast_min_kmh"],
                "season": _FALLBACK["season"]}


def _classify(apex: float, thr: dict) -> str:
    if not np.isfinite(apex):
        return CLASS_MED
    if apex < thr["slow_max"]:
        return CLASS_SLOW
    if apex >= thr["fast_min"]:
        return CLASS_FAST
    return CLASS_MED


# ── apex extraction ───────────────────────────────────────────
# Corners are located ONCE on the cached fastest-lap line (which is dense) and
# reduced to a fractional lap position. Each driver's apex is then read from
# their own dense Speed/Distance channel at that fraction — never by matching
# the driver's sparse X/Y to the corner, which silently misses the apex where a
# position-telemetry gap coincides with a corner (it put LEC at 223 km/h in a
# 165 km/h corner because his nearest sample sat 28 m past the apex).
def _corner_fracs(line: pd.DataFrame, corners: pd.DataFrame) -> np.ndarray:
    """Each corner's fractional position (0=start line → 1=lap end) along the
    reference line, by nearest dense line point."""
    lx = line["X"].to_numpy(float)
    ly = line["Y"].to_numpy(float)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(lx), np.diff(ly)))])
    total = cum[-1] if cum[-1] > 0 else 1.0
    out = []
    for _, c in corners.iterrows():
        i = int(np.argmin((lx - c["X"]) ** 2 + (ly - c["Y"]) ** 2))
        out.append(cum[i] / total)
    return np.array(out)


def _corner_segments(fracs: np.ndarray) -> list[tuple[float, float]]:
    """For each corner, the [lo, hi] fractional band to search for its apex —
    the midpoints to the neighbouring corners. Bounding each corner by its
    neighbours' midpoints means the search always contains the apex (robust to
    the ~tens-of-metres drift between the reference line's arc-length and a
    driver's speed-integrated distance) yet can never grab an adjacent corner.
    Returns bands in the ORIGINAL corner order."""
    n = len(fracs)
    order = np.argsort(fracs)
    fs = fracs[order]
    bounds = [(0.0, 0.0)] * n
    for j in range(n):
        f = fs[j]
        lo = (fs[j - 1] + f) / 2 if j > 0 else max(0.0, f - (fs[1] - f) / 2 if n > 1 else 0.0)
        hi = (f + fs[j + 1]) / 2 if j < n - 1 else min(1.0, f + (f - fs[j - 1]) / 2 if n > 1 else 1.0)
        bounds[order[j]] = (lo, hi)
    return bounds


def _apex_in_band(dist: np.ndarray, sp: np.ndarray, lo: float, hi: float) -> float:
    """Minimum speed while the lap fraction is in [lo, hi]."""
    if dist.size < 2 or dist[-1] <= 0:
        return np.nan
    fr = dist / dist[-1]
    m = (fr >= lo) & (fr <= hi)
    if not m.any():
        return np.nan
    v = np.nanmin(sp[m])
    return float(v) if np.isfinite(v) else np.nan


def _corner_apex_speeds(line: pd.DataFrame, corners: pd.DataFrame,
                        fracs: np.ndarray) -> np.ndarray:
    """The circuit's characteristic apex speed at each corner, from the cached
    fastest-lap line — the same ±window-on-the-line quantity the season
    thresholds were built on (the line is dense, so no alignment issue)."""
    lx = line["X"].to_numpy(float)
    ly = line["Y"].to_numpy(float)
    sp = pd.to_numeric(line["Speed"], errors="coerce").to_numpy(float)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(lx), np.diff(ly)))])
    total = cum[-1] if cum[-1] > 0 else 1.0
    out = []
    for f in fracs:
        m = np.abs(cum - f * total) <= APEX_WINDOW_M
        out.append(float(np.nanmin(sp[m])) if m.any() else np.nan)
    return np.array(out)


def _driver_apex_table(blt: pd.DataFrame, fracs: np.ndarray) -> pd.DataFrame:
    """Per driver × corner apex speed = the minimum of the driver's dense
    best-lap speed within each corner's midpoint-bounded band. Index =
    Driver_Short, columns = corner index 0..n-1, plus a 'Team' column."""
    bands = _corner_segments(fracs)
    n = len(fracs)
    rows, teams = {}, {}
    for drv, g in blt.groupby("Driver_Short"):
        g = g.dropna(subset=["Speed", "Distance"]).sort_values("Distance")
        d = pd.to_numeric(g["Distance"], errors="coerce").to_numpy(float)
        sp = pd.to_numeric(g["Speed"], errors="coerce").to_numpy(float)
        ok = np.isfinite(d) & np.isfinite(sp)
        d, sp = d[ok], sp[ok]
        if d.size < n + 1 or d[-1] <= 0:
            continue
        rows[drv] = [_apex_in_band(d, sp, lo, hi) for lo, hi in bands]
        teams[drv] = g["Team"].iloc[0] if "Team" in g.columns else None
    if not rows:
        return pd.DataFrame()
    tbl = pd.DataFrame.from_dict(rows, orient="index")
    tbl["Team"] = pd.Series(teams)
    return tbl


# ── assembly ──────────────────────────────────────────────────
def _corner_label(c) -> str:
    num, letter = c.get("Number"), c.get("Letter")
    letter = "" if letter is None or (isinstance(letter, float) and pd.isna(letter)) else str(letter).strip()
    try:
        return f"T{int(num)}{letter}"
    except (TypeError, ValueError):
        return f"T{num}{letter}"


def _sessions_frame(sessions) -> pd.DataFrame:
    """Full-field laps restricted to the given sessions. The card builds its
    apex table from the whole field (driver/team filtering happens later, at
    ranking) but the SESSION filter genuinely changes which lap is a driver's
    best, so it is applied here."""
    lp = state.laps
    if lp is None or lp.empty:
        return pd.DataFrame()
    if sessions:
        lp = lp[lp["session_name"].isin(sessions)]
    return lp


def _build(sessions) -> dict | None:
    """Everything the card needs for the loaded event: corner geometry +
    per-corner class + per-driver apex table. Memoised on data generation +
    the session selection, so the class-selector callback never rebuilds it."""
    from tabs.telemetry import (
        _best_lap_telemetry_frame, _get_track_map, _session_meeting_season, _rotate,
    )

    fl = _sessions_frame(sessions)
    if fl.empty:
        return None
    key = f"{state.DATA_GENERATION}|{','.join(sorted(sessions)) if sessions else 'all'}"
    if key in _MEMO:
        return _MEMO[key]

    season, event = _session_meeting_season(fl["session_name"].iloc[0])
    try:
        tm = _get_track_map()(season, event, "Q")
    except Exception:
        tm = None
    if (not tm or tm.get("line") is None or tm["line"].empty
            or tm.get("corners") is None or tm["corners"].empty):
        return None

    line, corners = tm["line"], tm["corners"]
    thr = _thresholds()
    fracs = _corner_fracs(line, corners)
    track_apex = _corner_apex_speeds(line, corners, fracs)
    classes = [_classify(a, thr) for a in track_apex]

    blt = _best_lap_telemetry_frame(fl)
    apex_tbl = _driver_apex_table(blt, fracs) if not blt.empty else pd.DataFrame()
    if apex_tbl.empty:
        return None

    ang = float(tm.get("rotation", 0.0)) / 180.0 * np.pi
    lx, ly = _rotate(line["X"].to_numpy(float), line["Y"].to_numpy(float), ang)
    cx, cy = _rotate(corners["X"].to_numpy(float), corners["Y"].to_numpy(float), ang)

    corner_info = []
    for i, (_, c) in enumerate(corners.iterrows()):
        corner_info.append({
            "idx": i, "label": _corner_label(c),
            "x": float(cx[i]), "y": float(cy[i]),
            "apex": None if not np.isfinite(track_apex[i]) else round(float(track_apex[i])),
            "cls": classes[i],
        })

    out = {
        "key": key, "season": season, "event": event,
        "thr": thr,
        "line_x": lx.tolist(), "line_y": ly.tolist(),
        "corners": corner_info,
        "apex_tbl": apex_tbl,
        "counts": {cl: int(sum(1 for c in corner_info if c["cls"] == cl))
                   for cl in _CLASS_ORDER},
    }
    _MEMO.clear()
    _MEMO[key] = out
    return out


# ── global-filter selection (harmony with the sidebar) ────────
def _allowed_from(fl: pd.DataFrame) -> tuple:
    if fl is None or fl.empty:
        return (None, None)
    return (frozenset(fl["Driver_Short"].dropna().unique()),
            frozenset(fl["Team"].dropna().unique()))


def _ranking(data: dict, cls: str, allowed=(None, None)) -> list[dict]:
    """Drivers ranked by mean apex speed across the corners of one class, under
    the sidebar's driver/team filter."""
    tbl = data["apex_tbl"]
    a_drv, a_team = allowed
    if a_drv is not None:
        tbl = tbl[tbl.index.isin(a_drv)]
    if a_team is not None:
        tbl = tbl[tbl["Team"].isin(a_team)]
    cols = [c["idx"] for c in data["corners"] if c["cls"] == cls]
    if not cols or tbl.empty:
        return []
    out = []
    for drv, row in tbl.iterrows():
        vals = pd.to_numeric(row[cols], errors="coerce")
        mean = float(vals.mean())
        if not np.isfinite(mean):
            continue
        out.append({"drv": drv, "team": row["Team"],
                    "speed": mean, "n": int(vals.notna().sum()),
                    "color": TEAM_COLORS.get(row["Team"], "#808080")})
    out.sort(key=lambda e: e["speed"], reverse=True)
    for i, e in enumerate(out):
        e["pos"] = i + 1
        e["gap"] = out[0]["speed"] - e["speed"]
    return out


# ── figure ────────────────────────────────────────────────────
_MUTED = "#5A5A66"          # neutral grey for the non-selected corner classes


def _track_fig(data: dict, cls: str) -> go.Figure:
    """Track outline with the SELECTED class of corners in its class colour and
    labelled; every other corner is a small neutral-grey dot. A colour change
    (class hue → grey), not just an opacity tweak, so switching class is
    unmistakable on the map."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=data["line_x"], y=data["line_y"], mode="lines",
        line=dict(color="rgba(160,160,170,0.45)", width=3),
        showlegend=False, hoverinfo="skip"))

    # non-selected corners first (underneath), as muted grey dots without labels
    other = [c for c in data["corners"] if c["cls"] != cls]
    if other:
        fig.add_trace(go.Scatter(
            x=[c["x"] for c in other], y=[c["y"] for c in other],
            mode="markers", marker=dict(size=8, color=_MUTED, opacity=0.55,
                                        line=dict(color="#0E0E14", width=0.5)),
            customdata=[[c["label"], c["apex"], _CLASS_META[c["cls"]][0]] for c in other],
            hovertemplate=("%{customdata[0]} · %{customdata[2]} corner"
                           "<br>apex %{customdata[1]} km/h<extra></extra>"),
            showlegend=False))

    # selected class on top, in colour, larger, labelled
    sel = [c for c in data["corners"] if c["cls"] == cls]
    if sel:
        _, colr = _CLASS_META[cls]
        fig.add_trace(go.Scatter(
            x=[c["x"] for c in sel], y=[c["y"] for c in sel],
            mode="markers+text",
            marker=dict(size=17, color=colr, opacity=1.0,
                        line=dict(color="#0E0E14", width=1.6)),
            text=[c["label"] for c in sel], textposition="top center",
            textfont=dict(size=11, color=TEXT_MAIN),
            customdata=[[c["label"], c["apex"], _CLASS_META[cls][0]] for c in sel],
            hovertemplate=("%{customdata[0]} · %{customdata[2]} corner"
                           "<br>apex %{customdata[1]} km/h<extra></extra>"),
            showlegend=False))

    theme(fig, 560)
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
        xaxis=dict(visible=False, showgrid=False, zeroline=False,
                   scaleanchor="y", scaleratio=1),
        yaxis=dict(visible=False, showgrid=False, zeroline=False),
        hovermode="closest")
    return fig


# ── ranking bars ──────────────────────────────────────────────
def _bars(data: dict, cls: str, ranking: list[dict]) -> html.Div:
    label, colr = _CLASS_META[cls]
    n_corners = data["counts"][cls]

    head = html.Div([
        html.Span(f"{label} corners", style={
            "color": TEXT_MAIN, "fontSize": "1.2rem", "fontWeight": "700"}),
        html.Span(f"{n_corners} on this track", style={
            "color": TEXT_DIM, "fontSize": "0.78rem", "marginLeft": "10px"}),
    ], style={"marginBottom": "10px"})

    if not ranking:
        thr = data["thr"]
        band = {CLASS_SLOW: f"apex < {thr['slow_max']:.0f} km/h",
                CLASS_MED: f"{thr['slow_max']:.0f}–{thr['fast_min']:.0f} km/h",
                CLASS_FAST: f"apex ≥ {thr['fast_min']:.0f} km/h"}[cls]
        return html.Div([head, html.P(
            f"This circuit has no {label.lower()} corners ({band}).",
            style={"color": TEXT_DIM})])

    top = ranking[0]["speed"]
    lo = min(e["speed"] for e in ranking)
    span = max(top - lo, 1.0)
    rows = []
    for e in ranking:
        # bar length emphasises the spread: scale within [lo-pad, top]
        frac = 0.25 + 0.75 * (e["speed"] - lo) / span
        rows.append(html.Div([
            html.Div(f"{e['pos']}", style={
                "width": "22px", "textAlign": "right", "color": TEXT_DIM,
                "fontSize": "0.78rem", "flexShrink": "0", "marginRight": "8px"}),
            html.Div(e["drv"], style={
                "width": "42px", "color": TEXT_MAIN, "fontWeight": "700",
                "fontSize": "0.85rem", "flexShrink": "0"}),
            html.Div(html.Div(style={
                "width": f"{frac*100:.1f}%", "height": "16px",
                "background": e["color"], "borderRadius": "3px",
                "minWidth": "4px"}),
                style={"flex": "1", "marginRight": "10px"}),
            html.Div([
                html.Span(f"{e['speed']:.0f}", style={
                    "color": TEXT_MAIN, "fontWeight": "700", "fontSize": "0.85rem"}),
                html.Span(" km/h" if e["pos"] == 1 else f"  −{e['gap']:.0f}",
                          style={"color": TEXT_DIM, "fontSize": "0.72rem"}),
            ], style={"width": "84px", "textAlign": "right", "flexShrink": "0"}),
        ], style={"display": "flex", "alignItems": "center", "padding": "3px 0"}))

    return html.Div([head, html.Div(rows)])


def _class_chips(counts: dict, active: str) -> html.Div:
    chips = []
    for cl in _CLASS_ORDER:
        label, colr = _CLASS_META[cl]
        on = (cl == active)
        chips.append(html.Button(
            [html.Span("●", style={"color": colr, "marginRight": "6px"}),
             f"{label} ({counts[cl]})"],
            id={"type": "cspeed-chip", "cls": cl}, n_clicks=0,
            style={
                "background": _hex_to_rgba(colr, 0.22) if on else "transparent",
                "border": f"1.5px solid {colr if on else 'rgba(255,255,255,0.15)'}",
                "borderRadius": "6px", "color": TEXT_MAIN,
                "padding": "5px 12px", "marginRight": "8px", "cursor": "pointer",
                "fontSize": "0.8rem", "fontWeight": "700" if on else "500"}))
    return html.Div(chips, style={"display": "flex", "flexWrap": "wrap",
                                  "gap": "4px", "marginBottom": "12px"})


# ── section ───────────────────────────────────────────────────
def corner_speed_section(fl: pd.DataFrame) -> html.Div:
    # fl is the sidebar-filtered frame; the session set narrows which lap is a
    # driver's best, the driver/team set narrows the ranking.
    sessions = set(fl["session_name"].unique()) if fl is not None and not fl.empty else set()
    data = _build(sessions)
    if data is None:
        return card("Cornering Speed by Corner Class",
                    html.P("No circuit geometry or best-lap telemetry available "
                           "for the loaded event.", style={"color": TEXT_DIM}))

    thr = data["thr"]
    default = CLASS_SLOW if data["counts"][CLASS_SLOW] else (
        CLASS_MED if data["counts"][CLASS_MED] else CLASS_FAST)
    allowed = _allowed_from(fl)
    ranking = _ranking(data, default, allowed)

    blurb = html.Div([
        html.P([
            "Each corner is the driver's ", html.B("apex (minimum) speed"),
            " on their best lap. Corners are classed ",
            html.Span("slow", style={"color": _CLASS_META[CLASS_SLOW][1], "fontWeight": "700"}),
            f" (< {thr['slow_max']:.0f} km/h), ",
            html.Span("medium", style={"color": _CLASS_META[CLASS_MED][1], "fontWeight": "700"}),
            f" ({thr['slow_max']:.0f}–{thr['fast_min']:.0f}), ",
            html.Span("fast", style={"color": _CLASS_META[CLASS_FAST][1], "fontWeight": "700"}),
            f" (≥ {thr['fast_min']:.0f}) by thresholds fixed across the "
            f"{thr['season']} season — so the classes mean the same km/h at "
            "every event.",
        ], style={"color": TEXT_MAIN, "fontSize": "0.86rem", "marginBottom": "2px"}),
        html.P("Pick a class to rank the field by average apex speed through "
               "its corners.",
               style={"color": TEXT_DIM, "fontSize": "0.8rem", "marginBottom": "0"}),
    ], style={"marginBottom": "12px"})

    return html.Div([
        dcc.Store(id="cspeed-active", data=default),
        card(
            "Cornering Speed by Corner Class",
            html.Div([
                blurb,
                html.Div([
                    html.Div(dcc.Graph(id="cspeed-map",
                                       figure=_track_fig(data, default), config=GFX),
                             style={"flex": "1 1 56%", "minWidth": "320px"}),
                    html.Div([
                        _class_chips(data["counts"], default),
                        html.Div(_bars(data, default, ranking), id="cspeed-bars"),
                    ], style={"flex": "1 1 40%", "minWidth": "300px",
                              "background": CARD_BG, "borderRadius": "8px",
                              "padding": "14px 14px"}),
                ], style={"display": "flex", "gap": "16px", "flexWrap": "wrap",
                          "alignItems": "flex-start"}),
            ]),
            info=("Data: every numbered corner of the circuit, classified slow / "
                  "medium / fast by its apex speed on the fastest cached lap, "
                  "using global thresholds derived once from a whole season "
                  "(scripts/compute_corner_classes.py) so the classes are the "
                  "same km/h everywhere. Each driver's apex (minimum) speed "
                  "through every corner comes from their best lap in the loaded "
                  "sessions, averaged within the selected class. Why: shows where "
                  "a car actually carries speed — low-speed traction vs "
                  "high-speed commitment — on a basis that is comparable from one "
                  "event to the next, so a gain is a real gain (upgrade, balance, "
                  "driver) and not a change in how corners were defined."),
        ),
    ])


# ── callback ──────────────────────────────────────────────────
@callback(Output("cspeed-active", "data"),
          Output("cspeed-map", "figure"),
          Output("cspeed-bars", "children"),
          Input({"type": "cspeed-chip", "cls": ALL}, "n_clicks"),
          State("session-filter", "value"),
          State("driver-filter", "value"),
          State("team-filter", "value"),
          prevent_initial_call=True)
def _select_class(_clicks, ss, sd, st):
    trig = ctx.triggered_id
    if not trig or not any(_clicks or []):
        return no_update, no_update, no_update
    cls = trig["cls"]
    data = _build(set(ss) if ss else set())
    if data is None:
        return no_update, no_update, no_update
    ranking = _ranking(data, cls, (frozenset(sd) if sd else None,
                                   frozenset(st) if st else None))
    return cls, _track_fig(data, cls), _bars(data, cls, ranking)
