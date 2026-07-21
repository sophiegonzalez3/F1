"""
Quali 3D replay — each driver's best qualifying lap replayed on a
georeferenced 3D track (real width from OSM, elevation AND camber from
national lidar where available — see track_scene.py).

Unlike the race replay (20 dots on a Plotly map), this is a proper WebGL
scene: assets/quali3d.js builds a Three.js track ribbon from the baked
scene and animates low-poly cars along each driver's best lap, all laps
synchronised at t=0 (ghost-style) so line/apex differences are visible.
Chase / onboard / TV / orbit cameras; animation is fully client-side.

Embedded in the QUALI tab via `quali3d_card(season, meeting)`.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
from dash import (
    html, dcc, callback, clientside_callback, no_update,
    Input, Output, State,
)
import dash_bootstrap_components as dbc

from f1lib.components import card
from f1lib.config import TEAM_COLORS, CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM
from f1lib.data_loader import load_session
from f1lib.processing import format_lap_time
from f1lib.telemetry_clean import clean_pos_samples, monotonic_didx
from f1lib.track_scene import build_track_scene, cached_scene

logger = logging.getLogger(__name__)

REPLAYS_DIR = Path("data/replays")
_PAYLOAD_VERSION = 7           # v7: speed-integral pos cleaning + gap pacing
_DT = 0.1                      # lap replay grid step (s) → 10 Hz

_PAYLOAD_MEM: dict[tuple, dict] = {}


# ─────────────────────────────────────────────────────────────
# Payload builder
# ─────────────────────────────────────────────────────────────

def _payload_cache_path(season: int, meeting: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(meeting)).strip("_").lower()
    return REPLAYS_DIR / f"{season}_{slug}_quali3d_v{_PAYLOAD_VERSION}.json.gz"


def cached_quali3d_payload(season: int, meeting: str) -> dict | None:
    """Cached payload (memory or disk) without touching telemetry."""
    key = (int(season), meeting)
    if key in _PAYLOAD_MEM:
        return _PAYLOAD_MEM[key]
    path = _payload_cache_path(season, meeting)
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        _PAYLOAD_MEM[key] = payload
        return payload
    return None


def _rotate(x, y, angle_rad):
    ca, sa = np.cos(angle_rad), np.sin(angle_rad)
    return x * ca - y * sa, x * sa + y * ca


def build_quali3d_payload(season: int, meeting: str) -> dict | None:
    """Scene + every driver's best qualifying lap on a 10 Hz grid.

    Driver arrays (ints, per frame): x/y in cm (scene display frame),
    didx (nearest scene section), spd km/h, gear, thr 0-100, brk 0/1.
    Cars are synchronised at lap start — a ghost-lap comparison."""
    payload = cached_quali3d_payload(season, meeting)
    if payload is not None:
        return payload

    scene = build_track_scene(int(season), meeting)
    if scene is None:
        return None

    data = load_session(str(season), meeting, "Qualifying")
    laps, tel = data.get("laps"), data.get("telemetry")
    if laps is None or laps.empty or tel is None or tel.empty:
        return None
    if not {"X", "Y", "timestamp", "DriverNo"}.issubset(tel.columns):
        return None

    ang = float(scene["rotation"]) / 180.0 * np.pi
    from scipy.spatial import cKDTree
    tree = cKDTree(np.column_stack([scene["cx"], scene["cy"]]))

    def _seconds(s: pd.Series) -> pd.Series:
        """Freshly fetched FastF1 laps carry Timedelta columns; the parquet
        cache stores float seconds. pd.to_numeric silently NaNs timedeltas,
        which dropped every lap on first-time builds."""
        if pd.api.types.is_timedelta64_dtype(s):
            return s.dt.total_seconds()
        return pd.to_numeric(s, errors="coerce")

    lp = laps.copy()
    lp["LapTime_f"] = _seconds(lp["LapTime"])
    lp["start_f"] = _seconds(lp["LapStartTime"])
    lp["end_f"] = _seconds(lp["Time"])
    if "IsDeleted" in lp.columns:
        lp = lp[~lp["IsDeleted"].fillna(False).astype(bool)]
    lp = lp.dropna(subset=["LapTime_f", "start_f", "end_f"])
    # in/out laps are never a driver's best; no extra filtering needed

    drivers = []
    for drv, g in lp.groupby(lp["DriverNo"].astype(str).str.strip()):
        best = g.loc[g["LapTime_f"].idxmin()]
        t0, t1 = float(best["start_f"]), float(best["end_f"])
        dur = float(best["LapTime_f"])

        seg = tel[(tel["DriverNo"].astype(str).str.strip() == drv)
                  & (tel["timestamp"] >= t0 - 1.0)
                  & (tel["timestamp"] <= t1 + 1.0)]
        seg = seg.dropna(subset=["X", "Y", "timestamp"]).sort_values("timestamp")
        seg = seg.drop_duplicates("timestamp")
        if len(seg) < 30:
            continue

        pos = clean_pos_samples(seg)
        if len(pos) < 30:
            continue
        ts_pos = pos["timestamp"].to_numpy(float)
        ts = seg["timestamp"].to_numpy(float)    # channel time base (car data)
        grid = t0 + np.arange(int(dur / _DT) + 1) * _DT
        xr, yr = _rotate(pos["X"].to_numpy(float) * 0.1,
                         pos["Y"].to_numpy(float) * 0.1, ang)
        xi = np.interp(grid, ts_pos, xr)
        yi = np.interp(grid, ts_pos, yr)
        didx = monotonic_didx(xi, yi, scene, tree)

        def chan(col, default=0.0):
            if col not in seg.columns:
                return np.full(len(grid), default)
            v = pd.to_numeric(seg[col], errors="coerce").ffill().fillna(default)
            return np.interp(grid, ts, v.to_numpy(float))

        code = str(best.get("Driver", "?")).split("-")[0][:3].upper()
        team = str(best.get("Team", ""))
        drivers.append({
            "code": code, "team": team,
            "color": TEAM_COLORS.get(team, "#808080"),
            "lt": format_lap_time(dur), "dur": round(dur, 3),
            "x": np.rint(xi * 100).astype(np.int64).tolist(),   # cm
            "y": np.rint(yi * 100).astype(np.int64).tolist(),
            "didx": didx.astype(int).tolist(),
            "spd": np.rint(chan("Speed")).astype(int).tolist(),
            "gear": np.rint(chan("GearNo")).astype(int).tolist(),
            "thr": np.clip(np.rint(chan("Throttle")), 0, 100).astype(int).tolist(),
            "brk": (chan("Brake") > 0.5).astype(int).tolist(),
        })

    if not drivers:
        return None
    drivers.sort(key=lambda d: d["dur"])

    payload = {
        "v": _PAYLOAD_VERSION, "season": int(season), "event": meeting,
        "dt": _DT, "tMax": max(d["dur"] for d in drivers),
        "scene": scene, "drivers": drivers,
    }
    REPLAYS_DIR.mkdir(parents=True, exist_ok=True)
    with gzip.open(_payload_cache_path(season, meeting), "wt",
                   encoding="utf-8") as fh:
        json.dump(payload, fh)
    _PAYLOAD_MEM[(int(season), meeting)] = payload
    return payload


# ─────────────────────────────────────────────────────────────
# Card layout
# ─────────────────────────────────────────────────────────────

_BTN_STYLE = {"fontSize": "0.75rem", "padding": "3px 12px"}
_LBL_STYLE = {"color": TEXT_DIM, "fontSize": "0.65rem",
              "letterSpacing": "1px", "marginLeft": "16px"}


def _driver_options(payload: dict) -> list[dict]:
    return [{"label": f"{d['code']}  {d['lt']}", "value": d["code"]}
            for d in payload["drivers"]]


def _status_line(payload: dict) -> str:
    sc = payload["scene"]
    src = sc["sources"]
    dtm = src["dtm"]
    extras = [f"elev 0–{sc['elev_range'][1]:.0f} m"]
    if sc["bank_max"] >= 2:
        extras.append(f"max banking {sc['bank_max']:.0f}°")
    sur = sc.get("surround")
    if sur:
        bits = []
        if sur.get("buildings"):
            bits.append(f"{len(sur['buildings'])} buildings")
        if sur.get("walls"):
            bits.append(f"{len(sur['walls'])} walls")
        if sur.get("trees"):
            bits.append(f"{len(sur['trees'])} trees")
        if sur.get("terrain"):
            bits.append("lidar terrain")
        if bits:
            extras.append(", ".join(bits))
    geo = (f" · georef ±{sc['geo']['median_m']:.1f} m" if sc.get("geo") else "")
    return (f"  {payload['event']} {payload['season']} · "
            f"{len(payload['drivers'])} laps · track: {src['track']} · "
            f"terrain: {dtm} · {' · '.join(extras)}{geo}")


def quali3d_card(season: int, meeting: str) -> html.Div:
    """The Quali 3D Replay card (top of the QUALI tab). Auto-loads when the
    payload is already cached; otherwise 'Build 3D replay' fetches OSM + DTM
    and slices the best laps (one-off, then cached)."""
    payload = cached_quali3d_payload(season, meeting)
    loaded = payload is not None
    n_frames = int(payload["tMax"] / payload["dt"]) + 1 if loaded else 1
    opts = _driver_options(payload) if loaded else []
    default_shown = [o["value"] for o in opts[:3]]
    default_focus = opts[0]["value"] if opts else None
    # When a pair was picked in the DUEL tab, the replay opens as that ghost
    # duel: just the two cars shown, camera following the attacker.
    try:
        from tabs.duel import LAST_PAIR
        if LAST_PAIR:
            have = {o["value"] for o in opts}
            pair = [d for d in LAST_PAIR if d in have]
            if len(pair) == 2:
                default_shown = pair
                default_focus = pair[0]
    except Exception:
        pass

    controls = html.Div([
        dbc.Button("▶ Play", id="q3d-play", size="sm", color="danger",
                   disabled=not loaded, n_clicks=0, style=_BTN_STYLE),
        html.Span("SPEED", style=_LBL_STYLE),
        dcc.RadioItems(
            id="q3d-speed",
            options=[{"label": f" {v}× ", "value": v} for v in (0.25, 0.5, 1)],
            value=1, inline=True,
            inputStyle={"marginLeft": "10px", "marginRight": "3px",
                        "accentColor": ACCENT},
            style={"display": "inline-block", "color": TEXT_MAIN,
                   "fontSize": "0.78rem"},
        ),
        html.Span("CAMERA", style=_LBL_STYLE),
        dcc.RadioItems(
            id="q3d-camera",
            options=[{"label": " Chase ", "value": "chase"},
                     {"label": " Onboard ", "value": "onboard"},
                     {"label": " TV ", "value": "tv"},
                     {"label": " Orbit ", "value": "orbit"}],
            value="chase", inline=True,
            inputStyle={"marginLeft": "10px", "marginRight": "3px",
                        "accentColor": ACCENT},
            style={"display": "inline-block", "color": TEXT_MAIN,
                   "fontSize": "0.78rem"},
        ),
        html.Span(id="q3d-clock", children="", style={
            "color": ACCENT, "fontWeight": "800", "fontSize": "0.95rem",
            "fontVariantNumeric": "tabular-nums", "marginLeft": "auto",
        }),
    ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap",
              "gap": "4px", "marginTop": "10px"})

    selectors = html.Div([
        html.Div([
            html.Span("CARS", style={**_LBL_STYLE, "marginLeft": "0"}),
            dcc.Dropdown(id="q3d-shown", multi=True,
                         options=opts, value=default_shown,
                         placeholder="drivers…",
                         style={"minWidth": "320px", "fontSize": "0.78rem"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "8px",
                  "flex": "1"}),
        html.Div([
            html.Span("FOLLOW", style=_LBL_STYLE),
            dcc.Dropdown(id="q3d-focus", multi=False, clearable=False,
                         options=opts, value=default_focus,
                         style={"minWidth": "170px", "fontSize": "0.78rem"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "8px"}),
    ], style={"display": "flex", "alignItems": "center", "gap": "10px",
              "marginTop": "8px", "flexWrap": "wrap"})

    body = html.Div([
        dcc.Store(id="q3d-meta", data={"season": int(season), "meeting": meeting}),
        dcc.Store(id="q3d-data", data=payload),
        html.Div(id="q3d-dummy", style={"display": "none"}),
        html.Div([
            dbc.Button("Build 3D replay", id="q3d-load-btn", color="danger",
                       size="sm", n_clicks=0,
                       style=None if not loaded else {"display": "none"}),
            html.Span(id="q3d-status",
                      children=(_status_line(payload) if loaded else
                                "  georeferences the circuit (OpenStreetMap + "
                                "lidar terrain where available) and slices "
                                "every driver's best lap — one-off, then cached"),
                      style={"color": TEXT_DIM, "fontSize": "0.75rem",
                             "marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        html.Div(id="q3d-mount", style={
            "height": "560px", "width": "100%", "position": "relative",
            "background": CARD_BG, "borderRadius": "6px", "overflow": "hidden",
        }),
        selectors,
        controls,
        dcc.Slider(id="q3d-slider", min=0, max=n_frames - 1, step=1, value=0,
                   marks=None, updatemode="drag",
                   tooltip={"placement": "bottom", "always_visible": False}),
        dcc.Interval(id="q3d-interval", interval=100, disabled=True),
    ])

    return card(
        "Quali 3D Replay — best laps",
        body,
        info=("Data: each driver's best qualifying lap (position + car "
              "telemetry at 10 Hz), replayed on a georeferenced 3D circuit. "
              "The track ribbon uses the real asphalt centerline and width "
              "from OpenStreetMap (the FastF1 racing line is fitted to it "
              "with a trimmed-ICP similarity transform, typically ±2 m), and "
              "terrain from national lidar (e.g. AHN 0.5 m for Zandvoort) "
              "sampled ACROSS the track — so slope, elevation and true "
              "camber/banking are all real geometry, not exaggeration. Where "
              "no open lidar exists the elevation falls back to the car's "
              "own z-telemetry with a flat cross-section. All laps start "
              "together (ghost style): pick cars, follow one in chase / "
              "onboard / TV / orbit camera, scrub or slow time to compare "
              "lines, apexes and kerb use. In Orbit view drag rotates, "
              "right- or shift-drag pans, scroll zooms; in TV view the "
              "surroundings turn translucent so buildings never hide the "
              "cars. Why: qualifying is one lap at the limit — this shows "
              "*where* it happens, in the circuit's real shape."),
    )


# ─────────────────────────────────────────────────────────────
# Server callback — build payload on demand
# ─────────────────────────────────────────────────────────────

@callback(
    Output("q3d-data", "data"),
    Output("q3d-status", "children"),
    Output("q3d-load-btn", "style"),
    Output("q3d-slider", "max"),
    Output("q3d-shown", "options"),
    Output("q3d-shown", "value"),
    Output("q3d-focus", "options"),
    Output("q3d-focus", "value"),
    Output("q3d-play", "disabled"),
    Input("q3d-load-btn", "n_clicks"),
    State("q3d-meta", "data"),
    prevent_initial_call=True,
)
def _build_q3d(n_clicks, meta):
    if not n_clicks or not meta:
        return (no_update,) * 9
    try:
        payload = build_quali3d_payload(meta["season"], meta["meeting"])
    except Exception as exc:
        logger.exception("quali3d build failed")
        return (no_update, f"  build failed: {exc}", no_update, no_update,
                no_update, no_update, no_update, no_update, no_update)
    if payload is None:
        return (no_update, "  no qualifying telemetry available.", no_update,
                no_update, no_update, no_update, no_update, no_update, no_update)
    opts = _driver_options(payload)
    shown = [o["value"] for o in opts[:3]]
    return (payload, _status_line(payload), {"display": "none"},
            int(payload["tMax"] / payload["dt"]),
            opts, shown, opts, opts[0]["value"], False)


# ─────────────────────────────────────────────────────────────
# Clientside callbacks (implementations in assets/quali3d.js)
# ─────────────────────────────────────────────────────────────

clientside_callback(
    "window.dash_clientside.quali3d.onData",
    Output("q3d-slider", "value"),
    Input("q3d-data", "data"),
    State("q3d-shown", "value"),
    State("q3d-focus", "value"),
    State("q3d-camera", "value"),
)

clientside_callback(
    "window.dash_clientside.quali3d.tick",
    Output("q3d-slider", "value", allow_duplicate=True),
    Input("q3d-interval", "n_intervals"),
    prevent_initial_call=True,
)

clientside_callback(
    "window.dash_clientside.quali3d.seek",
    Output("q3d-clock", "children"),
    Input("q3d-slider", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    "window.dash_clientside.quali3d.playPause",
    Output("q3d-interval", "disabled"),
    Output("q3d-play", "children"),
    Input("q3d-play", "n_clicks"),
    prevent_initial_call=True,
)

clientside_callback(
    "window.dash_clientside.quali3d.setSpeed",
    Output("q3d-dummy", "children", allow_duplicate=True),
    Input("q3d-speed", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    "window.dash_clientside.quali3d.setCamera",
    Output("q3d-dummy", "children", allow_duplicate=True),
    Input("q3d-camera", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    "window.dash_clientside.quali3d.setShown",
    Output("q3d-dummy", "children", allow_duplicate=True),
    Input("q3d-shown", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    "window.dash_clientside.quali3d.setFocus",
    Output("q3d-dummy", "children", allow_duplicate=True),
    Input("q3d-focus", "value"),
    prevent_initial_call=True,
)
