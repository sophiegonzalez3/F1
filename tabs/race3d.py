"""
Race lap-1 3D replay — the whole field on a shared race clock, streaming
through the opening lap on a georeferenced 3D track (real width from OSM,
elevation and camber from national lidar where available — see
f1lib/track_scene.py).

This is the race-flavoured twin of the QUALI 3D replay (tabs/quali_replay.py).
The scene and the WebGL viewer (assets/quali3d.js, the `race3d` factory
instance driving `r3d-*` component ids) are shared verbatim. The one real
difference is the payload: qualifying is ghost-synced — every car starts at
t=0 at the line — whereas here every driver's arrays are sampled on ONE common
time grid, so the cars sit on the grid, launch together and spread out through
Turn 1 at their real, simultaneous positions.

Window: lights-out (min lap-1 start) to the moment the LAST car completes
lap 1, so the whole field gets its first lap; the leaders drift a little into
lap 2.

Embedded in the RACE tab via `race3d_card(season, meeting)`.
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
from f1lib.telemetry_clean import clean_pos_samples, monotonic_didx
from f1lib.track_scene import build_track_scene

logger = logging.getLogger(__name__)

REPLAYS_DIR = Path("data/replays")
_PAYLOAD_VERSION = 5           # v5: staggered grid formation (real 2-column start)
_DT = 0.1                      # replay grid step (s) → 10 Hz
_PRE_ROLL = 3.0               # seconds of stationary grid before lights out
_TAIL = 1.0                   # seconds after the last car crosses the line

_PAYLOAD_MEM: dict[tuple, dict] = {}


# ─────────────────────────────────────────────────────────────
# Payload builder
# ─────────────────────────────────────────────────────────────

def _payload_cache_path(season: int, meeting: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(meeting)).strip("_").lower()
    return REPLAYS_DIR / f"{season}_{slug}_race3d_v{_PAYLOAD_VERSION}.json.gz"


def cached_race3d_payload(season: int, meeting: str) -> dict | None:
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


def _seconds(s: pd.Series) -> pd.Series:
    """Freshly fetched FastF1 laps carry Timedelta columns; the parquet cache
    stores float seconds. pd.to_numeric silently NaNs timedeltas."""
    if pd.api.types.is_timedelta64_dtype(s):
        return s.dt.total_seconds()
    return pd.to_numeric(s, errors="coerce")


def _grid_slot(scene, grid_pos: int):
    """Approximate (x, y) of a grid slot in the scene display frame: boxes
    every 8 m behind the start line (scene section 0) along the centerline,
    alternating sides. Used only when a car's position feed has no fix before
    lights-out (e.g. Monaco 2026, where the feed only wakes as each car
    crosses the timing line) — without an anchor every such car would sit at
    the (0,0) placeholder 'floating in space' until its data starts."""
    n_sc = len(scene["cx"])
    step = float(scene["step"])
    back_m = 7.0 + 8.0 * (grid_pos - 1)
    idx = (-int(round(back_m / step))) % n_sc
    lat = 2.0 if grid_pos % 2 else -2.0
    return (scene["cx"][idx] + scene["nx"][idx] * lat,
            scene["cy"][idx] + scene["ny"][idx] * lat)


_GRID_STAGGER_M = 2.5      # lateral offset of each grid column from centerline
_GRID_LOCK_M = 2.0         # car within this of its grid box → full staggered slot
_GRID_RELEASE_M = 35.0     # car this far from its box → fully on its real line
_GRID_GATE_S = 15.0        # never re-apply the formation past this (avoids the
                           #   lap-1 leader re-triggering as it nears the line)


def _apply_grid_formation(xi, yi, didx, grid, lights_out, grid_pos, scene):
    """Seat a car in its real staggered grid slot for the pre-start, then blend
    onto its true racing line as it launches.

    The F1 position feed can't resolve the ~2 m grid-box stagger — every
    stationary grid car reads as a single-file line that merely follows the
    track's curve (measured: a smooth ±2 m ramp front-to-back, not two
    columns). But the grid is a KNOWN formation, so we reconstruct it from
    GridPosition: odd rows one side, even rows the other, ±`_GRID_STAGGER_M`
    across the track. Along-track position is left untouched (the feed gets
    that right, ~8 m spacing), so nothing lurches — only the lateral offset is
    driven to the column, and released as the car drives away from its box."""
    if grid_pos is None:
        return xi, yi
    nx = np.asarray(scene["nx"]); ny = np.asarray(scene["ny"])
    cx = np.asarray(scene["cx"]); cy = np.asarray(scene["cy"])
    ref = int(np.argmin(np.abs(grid - lights_out)))     # last stationary frame
    dist = np.hypot(xi - xi[ref], yi - yi[ref])          # how far it has launched
    w = np.clip((_GRID_RELEASE_M - dist)
                / (_GRID_RELEASE_M - _GRID_LOCK_M), 0.0, 1.0)
    w[grid > lights_out + _GRID_GATE_S] = 0.0            # launch phase only
    if not (w > 0).any():
        return xi, yi
    target = _GRID_STAGGER_M if (grid_pos % 2) else -_GRID_STAGGER_M
    nxi, nyi = nx[didx], ny[didx]
    lat = (xi - cx[didx]) * nxi + (yi - cy[didx]) * nyi  # current lateral
    shift = w * (target - lat)                            # → column when w=1
    return xi + shift * nxi, yi + shift * nyi


def build_race3d_payload(season: int, meeting: str) -> dict | None:
    """Scene + every driver's lap-1 position/telemetry on ONE shared 10 Hz
    grid (real race clock). Driver arrays (ints, per frame): x/y in cm (scene
    display frame), didx (nearest scene section), spd km/h, gear, thr 0-100,
    brk 0/1. All arrays share the same length and time base, so frame f is the
    same wall-clock instant for every car — the whole field at once."""
    payload = cached_race3d_payload(season, meeting)
    if payload is not None:
        return payload

    scene = build_track_scene(int(season), meeting)
    if scene is None:
        return None

    data = load_session(str(season), meeting, "Race")
    laps, tel = data.get("laps"), data.get("telemetry")
    if laps is None or laps.empty or tel is None or tel.empty:
        return None
    if not {"X", "Y", "timestamp", "DriverNo"}.issubset(tel.columns):
        return None
    if "LapNo" not in laps.columns:
        return None

    lp = laps.copy()
    lp["start_f"] = _seconds(lp["LapStartTime"])
    lp["end_f"] = _seconds(lp["Time"])
    lap1 = lp[lp["LapNo"] == 1].dropna(subset=["start_f"])
    if lap1.empty:
        return None

    # ── shared lap-1 window: lights out → last car completes lap 1 ──
    t0 = float(lap1["start_f"].min()) - _PRE_ROLL
    ends = lap1["end_f"].dropna()
    if ends.empty:
        return None
    t_end = float(ends.max()) + _TAIL
    if not np.isfinite(t_end) or t_end <= t0:
        return None
    n = int((t_end - t0) / _DT) + 1
    grid = t0 + np.arange(n) * _DT
    t_max = float((n - 1) * _DT)

    ang = float(scene["rotation"]) / 180.0 * np.pi
    from scipy.spatial import cKDTree
    tree = cKDTree(np.column_stack([scene["cx"], scene["cy"]]))

    lights_out = float(lap1["start_f"].min())
    grid_map: dict[str, int] = {}
    res = data.get("results")
    if res is not None and not res.empty \
            and {"DriverNumber", "GridPosition"}.issubset(res.columns):
        for _, rr in res.iterrows():
            gp = pd.to_numeric(rr["GridPosition"], errors="coerce")
            if pd.notna(gp) and gp >= 1:
                grid_map[str(rr["DriverNumber"]).strip()] = int(gp)

    drivers = []
    for drv, g1 in lap1.groupby(lap1["DriverNo"].astype(str).str.strip()):
        row = g1.iloc[0]
        l1end = float(g1["end_f"].dropna().min()) if g1["end_f"].notna().any() \
            else np.inf

        seg = tel[(tel["DriverNo"].astype(str).str.strip() == drv)
                  & (tel["timestamp"] >= t0 - 1.0)
                  & (tel["timestamp"] <= t_end + 1.0)]
        seg = seg.dropna(subset=["X", "Y", "timestamp"]).sort_values("timestamp")
        seg = seg.drop_duplicates("timestamp")
        if len(seg) < 30:
            continue

        pos = clean_pos_samples(seg)
        if len(pos) < 30:
            continue
        ts_pos = pos["timestamp"].to_numpy(float)
        xr, yr = _rotate(pos["X"].to_numpy(float) * 0.1,
                         pos["Y"].to_numpy(float) * 0.1, ang)
        # feed woke only after lights-out (no fix on the grid) → park the car
        # on its synthesized grid slot until the start, then bridge to the
        # first real fix instead of holding a mid-straight position.
        if ts_pos[0] > lights_out + 0.5 and drv in grid_map:
            gx, gy = _grid_slot(scene, grid_map[drv])
            ts_pos = np.concatenate([[t0 - 1.0, lights_out], ts_pos])
            xr = np.concatenate([[gx, gx], xr])
            yr = np.concatenate([[gy, gy], yr])

        ts = seg["timestamp"].to_numpy(float)    # channel time base (car data)
        # Constant-velocity glide across any gap left by dropped garbage: a
        # feed dropout is exactly where the data is least trustworthy, so the
        # humble steady interpolation beats a cleverer pacing that can amplify
        # an inflated (overshot) gap into an alarming peak speed.
        xi = np.interp(grid, ts_pos, xr)     # holds first/last pos outside range
        yi = np.interp(grid, ts_pos, yr)
        didx = monotonic_didx(xi, yi, scene, tree)
        # seat the car in its real staggered grid slot for the pre-start /
        # launch (the feed collapses the grid to a single file otherwise)
        xi, yi = _apply_grid_formation(xi, yi, didx, grid, lights_out,
                                       grid_map.get(drv), scene)

        def chan(col, default=0.0):
            if col not in seg.columns:
                return np.full(len(grid), default)
            v = pd.to_numeric(seg[col], errors="coerce").ffill().fillna(default)
            return np.interp(grid, ts, v.to_numpy(float))

        code = str(row.get("Driver", "?")).split("-")[0][:3].upper()
        team = str(row.get("Team", ""))
        drivers.append({
            "code": code, "team": team,
            "color": TEAM_COLORS.get(team, "#808080"),
            "endT": l1end,                    # lap-1 finish time (for ordering)
            "dur": round(t_max, 3),
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

    # lap-1 finishing order → running-position labels ("P1" … "DNF")
    drivers.sort(key=lambda d: d["endT"])
    for i, d in enumerate(drivers):
        d["lt"] = "DNF" if not np.isfinite(d.pop("endT")) else f"P{i + 1}"

    payload = {
        "v": _PAYLOAD_VERSION, "season": int(season), "event": meeting,
        "dt": _DT, "tMax": t_max, "scene": scene, "drivers": drivers,
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
    geo = (f" · georef ±{sc['geo']['median_m']:.1f} m" if sc.get("geo") else "")
    return (f"  {payload['event']} {payload['season']} · lap 1 · "
            f"{len(payload['drivers'])} cars · {payload['tMax']:.0f}s · "
            f"track: {src['track']} · terrain: {dtm} · "
            f"{' · '.join(extras)}{geo}")


def race3d_card(season: int, meeting: str) -> html.Div:
    """The Race Lap-1 3D card (second card in the RACE tab). Auto-loads when the
    payload is already cached; otherwise 'Build 3D replay' fetches OSM + DTM and
    slices the field's opening lap (one-off, then cached)."""
    payload = cached_race3d_payload(season, meeting)
    loaded = payload is not None
    n_frames = int(payload["tMax"] / payload["dt"]) + 1 if loaded else 1
    opts = _driver_options(payload) if loaded else []
    default_shown = [o["value"] for o in opts]              # ALL cars at once
    default_focus = opts[0]["value"] if opts else None      # lap-1 leader

    controls = html.Div([
        dbc.Button("▶ Play", id="r3d-play", size="sm", color="danger",
                   disabled=not loaded, n_clicks=0, style=_BTN_STYLE),
        html.Span("SPEED", style=_LBL_STYLE),
        dcc.RadioItems(
            id="r3d-speed",
            options=[{"label": f" {v}× ", "value": v} for v in (0.25, 0.5, 1)],
            value=1, inline=True,
            inputStyle={"marginLeft": "10px", "marginRight": "3px",
                        "accentColor": ACCENT},
            style={"display": "inline-block", "color": TEXT_MAIN,
                   "fontSize": "0.78rem"},
        ),
        html.Span("CAMERA", style=_LBL_STYLE),
        dcc.RadioItems(
            id="r3d-camera",
            options=[{"label": " Chase ", "value": "chase"},
                     {"label": " Onboard ", "value": "onboard"},
                     {"label": " TV ", "value": "tv"},
                     {"label": " Orbit ", "value": "orbit"}],
            value="orbit", inline=True,
            inputStyle={"marginLeft": "10px", "marginRight": "3px",
                        "accentColor": ACCENT},
            style={"display": "inline-block", "color": TEXT_MAIN,
                   "fontSize": "0.78rem"},
        ),
        html.Span(id="r3d-clock", children="", style={
            "color": ACCENT, "fontWeight": "800", "fontSize": "0.95rem",
            "fontVariantNumeric": "tabular-nums", "marginLeft": "auto",
        }),
    ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap",
              "gap": "4px", "marginTop": "10px"})

    selectors = html.Div([
        html.Div([
            html.Span("CARS", style={**_LBL_STYLE, "marginLeft": "0"}),
            dcc.Dropdown(id="r3d-shown", multi=True,
                         options=opts, value=default_shown,
                         placeholder="drivers…",
                         style={"minWidth": "320px", "fontSize": "0.78rem"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "8px",
                  "flex": "1"}),
        html.Div([
            html.Span("FOLLOW", style=_LBL_STYLE),
            dcc.Dropdown(id="r3d-focus", multi=False, clearable=False,
                         options=opts, value=default_focus,
                         style={"minWidth": "170px", "fontSize": "0.78rem"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "8px"}),
    ], style={"display": "flex", "alignItems": "center", "gap": "10px",
              "marginTop": "8px", "flexWrap": "wrap"})

    body = html.Div([
        dcc.Store(id="r3d-meta", data={"season": int(season), "meeting": meeting}),
        dcc.Store(id="r3d-data", data=payload),
        html.Div(id="r3d-dummy", style={"display": "none"}),
        html.Div([
            dbc.Button("Build 3D replay", id="r3d-load-btn", color="danger",
                       size="sm", n_clicks=0,
                       style=None if not loaded else {"display": "none"}),
            html.Span(id="r3d-status",
                      children=(_status_line(payload) if loaded else
                                "  georeferences the circuit (OpenStreetMap + "
                                "lidar terrain where available) and slices the "
                                "whole field's opening lap — one-off, then "
                                "cached"),
                      style={"color": TEXT_DIM, "fontSize": "0.75rem",
                             "marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        html.Div(id="r3d-mount", style={
            "height": "560px", "width": "100%", "position": "relative",
            "background": CARD_BG, "borderRadius": "6px", "overflow": "hidden",
        }),
        selectors,
        controls,
        dcc.Slider(id="r3d-slider", min=0, max=n_frames - 1, step=1, value=0,
                   marks=None, updatemode="drag",
                   tooltip={"placement": "bottom", "always_visible": False}),
        dcc.Interval(id="r3d-interval", interval=100, disabled=True),
    ])

    return card(
        "Race Lap 1 — 3D, whole field",
        body,
        info=("Data: every car's position + telemetry (10 Hz) through the "
              "opening lap, replayed together on the same georeferenced 3D "
              "circuit as the qualifying replay. Unlike qualifying (each lap "
              "ghost-synced to the start), here the field shares one race "
              "clock: cars sit on the grid, launch at lights-out and stream "
              "through Turn 1 at their real, simultaneous positions. The "
              "window runs to the moment the last car completes lap 1, so the "
              "whole field gets its first lap (the leaders drift a little into "
              "lap 2). The track ribbon uses the real asphalt centerline and "
              "width from OpenStreetMap with terrain and camber from national "
              "lidar where available. Show all cars or a subset, follow any "
              "one in chase / onboard / TV / orbit camera, and scrub or slow "
              "time to study launches, the first-corner scramble and who gains "
              "in the opening 500 metres. Why: lap 1 is the race's most "
              "chaotic, position-defining phase — this is the only view that "
              "shows the whole pack moving through it in the circuit's real "
              "shape."),
    )


# ─────────────────────────────────────────────────────────────
# Server callback — build payload on demand
# ─────────────────────────────────────────────────────────────

@callback(
    Output("r3d-data", "data"),
    Output("r3d-status", "children"),
    Output("r3d-load-btn", "style"),
    Output("r3d-slider", "max"),
    Output("r3d-shown", "options"),
    Output("r3d-shown", "value"),
    Output("r3d-focus", "options"),
    Output("r3d-focus", "value"),
    Output("r3d-play", "disabled"),
    Input("r3d-load-btn", "n_clicks"),
    State("r3d-meta", "data"),
    prevent_initial_call=True,
)
def _build_r3d(n_clicks, meta):
    if not n_clicks or not meta:
        return (no_update,) * 9
    try:
        payload = build_race3d_payload(meta["season"], meta["meeting"])
    except Exception as exc:
        logger.exception("race3d build failed")
        return (no_update, f"  build failed: {exc}", no_update, no_update,
                no_update, no_update, no_update, no_update, no_update)
    if payload is None:
        return (no_update, "  no race telemetry available.", no_update,
                no_update, no_update, no_update, no_update, no_update, no_update)
    opts = _driver_options(payload)
    shown = [o["value"] for o in opts]
    return (payload, _status_line(payload), {"display": "none"},
            int(payload["tMax"] / payload["dt"]),
            opts, shown, opts, opts[0]["value"], False)


# ─────────────────────────────────────────────────────────────
# Clientside callbacks (implementations in assets/quali3d.js, race3d instance)
# ─────────────────────────────────────────────────────────────

clientside_callback(
    "window.dash_clientside.race3d.onData",
    Output("r3d-slider", "value"),
    Input("r3d-data", "data"),
    State("r3d-shown", "value"),
    State("r3d-focus", "value"),
    State("r3d-camera", "value"),
)

clientside_callback(
    "window.dash_clientside.race3d.tick",
    Output("r3d-slider", "value", allow_duplicate=True),
    Input("r3d-interval", "n_intervals"),
    prevent_initial_call=True,
)

clientside_callback(
    "window.dash_clientside.race3d.seek",
    Output("r3d-clock", "children"),
    Input("r3d-slider", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    "window.dash_clientside.race3d.playPause",
    Output("r3d-interval", "disabled"),
    Output("r3d-play", "children"),
    Input("r3d-play", "n_clicks"),
    prevent_initial_call=True,
)

clientside_callback(
    "window.dash_clientside.race3d.setSpeed",
    Output("r3d-dummy", "children", allow_duplicate=True),
    Input("r3d-speed", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    "window.dash_clientside.race3d.setCamera",
    Output("r3d-dummy", "children", allow_duplicate=True),
    Input("r3d-camera", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    "window.dash_clientside.race3d.setShown",
    Output("r3d-dummy", "children", allow_duplicate=True),
    Input("r3d-shown", "value"),
    prevent_initial_call=True,
)

clientside_callback(
    "window.dash_clientside.race3d.setFocus",
    Output("r3d-dummy", "children", allow_duplicate=True),
    Input("r3d-focus", "value"),
    prevent_initial_call=True,
)
