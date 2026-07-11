"""
Race replay — animated track-map replay of the whole race: 20 team-coloured
dots moving on the circuit, with play/pause, scrub slider, speed control, a
synced elevation-profile strip and an optional 3D view with camera presets.

The payoff of merge_channels' 100% X/Y coverage: every driver's position is
interpolated onto a shared 2 Hz time grid (the *replay payload*), built once
per race and cached to data/replays/. Animation is fully client-side: a
dcc.Interval ticks a clientside callback (assets/replay.js) that Plotly.restyle's
the car-dot traces — no server round-trip per frame.

Embedded in the RACE tab via `replay_card(season, meeting)`.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import (
    html, dcc, callback, clientside_callback, no_update,
    Input, Output, State,
)
import dash_bootstrap_components as dbc

from components import card, GFX
from config import (
    TEAM_COLORS,
    CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
)
from data_loader import load_session

logger = logging.getLogger(__name__)

REPLAYS_DIR = Path("data/replays")
_PAYLOAD_VERSION = 1          # bump when the payload schema changes
_DT = 0.5                     # replay grid step (s) → 2 Hz
_Z_EXAGGERATION = 5.0         # vertical exaggeration of the 3D view

_PAYLOAD_MEM: dict[tuple, dict] = {}   # (season, meeting) → payload


# ─────────────────────────────────────────────────────────────
# Payload builder
# ─────────────────────────────────────────────────────────────

def _replay_cache_path(season: int, meeting: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(meeting)).strip("_").lower()
    return REPLAYS_DIR / f"{season}_{slug}_race_v{_PAYLOAD_VERSION}.json.gz"


def cached_payload(season: int, meeting: str) -> dict | None:
    """Return the replay payload if it is already built (memory or disk cache)
    WITHOUT touching session telemetry — used to auto-load the card."""
    key = (int(season), meeting)
    if key in _PAYLOAD_MEM:
        return _PAYLOAD_MEM[key]
    path = _replay_cache_path(season, meeting)
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        _PAYLOAD_MEM[key] = payload
        return payload
    return None


def _filtered_payload(payload: dict, codes: list[str] | None) -> dict:
    """Payload restricted to the sidebar Driver/Team filter (list of
    Driver_Short codes). Falls back to the full grid when the filter matches
    nobody (e.g. a fallback season with a different line-up)."""
    if not codes:
        return payload
    keep = {str(c).upper() for c in codes}
    drivers = [d for d in payload["drivers"] if d["code"] in keep]
    if not drivers:
        return payload
    out = dict(payload)
    out["drivers"] = drivers
    return out


def _rotate(x, y, angle_rad):
    ca, sa = np.cos(angle_rad), np.sin(angle_rad)
    return x * ca - y * sa, x * sa + y * ca


def _masked_int_list(values: np.ndarray, hidden: np.ndarray) -> list:
    """Round to int and replace hidden frames with None (JSON null) so the
    browser simply doesn't draw the dot (retired / not-yet-started cars)."""
    out = np.rint(values).astype(np.int64).tolist()
    for j in np.flatnonzero(hidden):
        out[j] = None
    return out


def _outline_from_track_map(season: int, meeting: str) -> tuple[pd.DataFrame, float] | None:
    """Reference line (X, Y, z) + rotation from the cached track map. Lazy
    import — tabs.track owns the track-map fetch/cache."""
    try:
        from tabs.track import get_track_map
        tm = get_track_map(season, meeting, "Q")
        if tm is None or tm["line"].empty:
            return None
        return tm["line"], float(tm["rotation"])
    except Exception as exc:
        logger.warning("replay: track map unavailable for %s %s: %s",
                       season, meeting, exc)
        return None


def _outline_from_telemetry(tel: pd.DataFrame, laps: pd.DataFrame) -> pd.DataFrame | None:
    """Fallback outline when no track map exists: one full racing lap (lap 2 of
    the driver with the densest position data), unrotated."""
    lap2 = laps[laps["LapNo"] == 2]
    for _, lp in lap2.iterrows():
        t0, t1 = lp["LapStartTime"], lp["Time"]
        if pd.isna(t0) or pd.isna(t1):
            continue
        seg = tel[(tel["DriverNo"] == lp["DriverNo"])
                  & (tel["timestamp"] >= t0) & (tel["timestamp"] <= t1)]
        if len(seg) > 100:
            out = seg[["X", "Y"]].dropna().reset_index(drop=True)
            out["z"] = np.nan
            return out
    return None


def build_replay_payload(season: int, meeting: str) -> dict | None:
    """Build (or load from cache) the replay payload for a race.

    Payload schema (all coordinates in FastF1 world units of 0.1 m, already
    rotated by the track-map rotation):
      t0, dt, n           — time grid (session seconds)
      nLaps, lap[n]       — leader's current lap per frame
      outline             — {x, y, z, dist}: reference track line; z is relative
                            elevation in 0.1 m (None per-point when unknown),
                            dist is metres along the lap from the start line
      drivers[]           — {code, team, color, x[n], y[n], didx[n]}: didx is
                            the index of the nearest outline point (elevation +
                            track-distance lookup), None while the car is hidden
      has_z               — whether elevation data is usable (strip + 3D)
    """
    payload = cached_payload(season, meeting)
    if payload is not None:
        return payload
    key = (int(season), meeting)
    path = _replay_cache_path(season, meeting)

    data = load_session(str(season), meeting, "Race")
    tel, laps = data.get("telemetry"), data.get("laps")
    if tel is None or tel.empty or laps is None or laps.empty:
        return None
    if not {"X", "Y", "timestamp", "DriverNo"}.issubset(tel.columns):
        return None

    # ── Race time window: lights-out to the last lap completed ──
    lap1 = laps.loc[laps["LapNo"] == 1, "LapStartTime"].dropna()
    t_start = float(lap1.min()) - 5.0 if not lap1.empty else float(tel["timestamp"].min())
    t_end = float(pd.to_numeric(laps["Time"], errors="coerce").max()) + 5.0
    if not np.isfinite(t_end) or t_end <= t_start:
        t_end = float(tel["timestamp"].max())
    n = int((t_end - t_start) / _DT) + 1
    grid = t_start + np.arange(n) * _DT

    # ── Reference outline + rotation (shared by dots, strip and 3D) ──
    rotation = 0.0
    res = _outline_from_track_map(season, meeting)
    if res is not None:
        line, rotation = res
    else:
        line = _outline_from_telemetry(tel, laps)
        if line is None:
            return None
    ang = rotation / 180.0 * np.pi
    ox, oy = _rotate(line["X"].to_numpy(float), line["Y"].to_numpy(float), ang)
    oz = line["z"].to_numpy(float) if "z" in line.columns else np.full(len(ox), np.nan)
    has_z = bool(np.isfinite(oz).sum() > len(oz) * 0.5)
    oz_rel = (oz - np.nanmin(oz)) if has_z else oz          # 0.1 m above low point
    dist = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(ox), np.diff(oy)))]) / 10.0

    outline = {
        "x": np.rint(ox).astype(int).tolist(),
        "y": np.rint(oy).astype(int).tolist(),
        "z": ([None if not np.isfinite(v) else int(round(v)) for v in oz_rel]
              if has_z else None),
        "dist": np.rint(dist).astype(int).tolist(),
    }

    # ── Driver identity: DriverNo → code / team / colour ──
    lm = laps.dropna(subset=["DriverNo"]).drop_duplicates("DriverNo")
    ident = {
        str(r["DriverNo"]).strip(): {
            "code": str(r.get("Driver", "?")).split("-")[0][:3].upper(),
            "team": str(r.get("Team", "")),
        }
        for _, r in lm.iterrows()
    }
    # each driver's last on-track moment (retirees vanish shortly after stopping)
    last_lap_end = pd.to_numeric(laps["Time"], errors="coerce").groupby(
        laps["DriverNo"].astype(str).str.strip()).max()

    from scipy.spatial import cKDTree
    tree = cKDTree(np.column_stack([ox, oy]))

    drivers = []
    for drv, g in tel.groupby("DriverNo"):
        drv = str(drv).strip()
        if drv not in ident:
            continue
        g = g.dropna(subset=["X", "Y", "timestamp"]).sort_values("timestamp")
        g = g.drop_duplicates("timestamp")
        if len(g) < 50:
            continue
        ts = g["timestamp"].to_numpy(float)
        xr, yr = _rotate(g["X"].to_numpy(float), g["Y"].to_numpy(float), ang)
        xi = np.interp(grid, ts, xr)
        yi = np.interp(grid, ts, yr)

        t_off = float(last_lap_end.get(drv, np.nan))
        if not np.isfinite(t_off):
            t_off = float(ts[-1])
        hidden = (grid < ts[0]) | (grid > min(t_off + 5.0, ts[-1] + 5.0))

        didx = np.full(n, -1, dtype=np.int64)
        vis = ~hidden
        if vis.any():
            _, nearest = tree.query(np.column_stack([xi[vis], yi[vis]]))
            didx[vis] = nearest
        didx_list = didx.tolist()
        for j in np.flatnonzero(hidden):
            didx_list[j] = None

        drivers.append({
            "code":  ident[drv]["code"],
            "team":  ident[drv]["team"],
            "color": TEAM_COLORS.get(ident[drv]["team"], "#808080"),
            "x":     _masked_int_list(xi, hidden),
            "y":     _masked_int_list(yi, hidden),
            "didx":  didx_list,
        })
    if not drivers:
        return None

    # ── Leader's current lap per frame (for the clock + slider marks) ──
    starts = laps.groupby("LapNo")["LapStartTime"].min().dropna().sort_index()
    n_laps = int(starts.index.max()) if len(starts) else 0
    lap_per_frame = np.clip(
        np.searchsorted(starts.to_numpy(float), grid, side="right"), 1, max(n_laps, 1)
    ).astype(int).tolist()

    payload = {
        "v": _PAYLOAD_VERSION, "t0": t_start, "dt": _DT, "n": n,
        "nLaps": n_laps, "lap": lap_per_frame,
        "event": meeting, "season": int(season), "has_z": has_z,
        "outline": outline, "drivers": drivers,
    }

    REPLAYS_DIR.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)
    _PAYLOAD_MEM[key] = payload
    return payload


# ─────────────────────────────────────────────────────────────
# Figures
# ─────────────────────────────────────────────────────────────

def _frame0(payload: dict):
    """Dot coordinates at frame 0 for the server-rendered initial figure."""
    xs = [d["x"][0] for d in payload["drivers"]]
    ys = [d["y"][0] for d in payload["drivers"]]
    return xs, ys


def _cars_kwargs(payload: dict) -> dict:
    colors = [d["color"] for d in payload["drivers"]]
    codes  = [d["code"] for d in payload["drivers"]]
    return dict(
        mode="markers+text", name="cars",
        text=codes, textposition="top center",
        textfont=dict(size=9, color=colors, family="Inter, sans-serif"),
        marker=dict(size=10, color=colors, line=dict(color="#FFFFFF", width=1)),
        hovertext=[f"{d['code']} · {d['team']}" for d in payload["drivers"]],
        hoverinfo="text",
    )


def _empty_fig(message: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        height=560, paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        margin=dict(l=20, r=20, t=20, b=20),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
    )
    fig.add_annotation(text=message, xref="paper", yref="paper",
                       x=0.5, y=0.5, showarrow=False,
                       font=dict(size=13, color=TEXT_DIM))
    return fig


def _fig_replay_2d(payload: dict) -> go.Figure:
    o = payload["outline"]
    fig = go.Figure()
    # Road: a wide dark band with a faint centre line.
    fig.add_trace(go.Scatter(
        x=o["x"], y=o["y"], mode="lines",
        line=dict(color="#2E2E3E", width=9),
        hoverinfo="skip", showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=o["x"], y=o["y"], mode="lines",
        line=dict(color="#55556A", width=1, dash="dot"),
        hoverinfo="skip", showlegend=False,
    ))
    # Start/finish tick perpendicular to the first outline segment.
    if len(o["x"]) > 1:
        dx, dy = o["x"][1] - o["x"][0], o["y"][1] - o["y"][0]
        nrm = (dx * dx + dy * dy) ** 0.5 or 1.0
        px, py, h = -dy / nrm, dx / nrm, 450.0
        fig.add_trace(go.Scatter(
            x=[o["x"][0] - px * h, o["x"][0] + px * h],
            y=[o["y"][0] - py * h, o["y"][0] + py * h],
            mode="lines", line=dict(color="#FFFFFF", width=4),
            hovertext="Start / Finish", hoverinfo="text", showlegend=False,
        ))
    xs, ys = _frame0(payload)
    fig.add_trace(go.Scatter(x=xs, y=ys, **_cars_kwargs(payload)))

    fig.update_layout(
        height=560, paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        margin=dict(l=10, r=10, t=10, b=10), showlegend=False,
        uirevision="replay",
    )
    axkw = dict(showgrid=False, zeroline=False, visible=False)
    fig.update_xaxes(**axkw)
    fig.update_yaxes(scaleanchor="x", scaleratio=1, **axkw)
    return fig


def _fig_replay_3d(payload: dict) -> go.Figure:
    o = payload["outline"]
    ox = np.asarray(o["x"], float)
    oy = np.asarray(o["y"], float)
    oz = np.asarray([v if v is not None else np.nan for v in o["z"]], float)
    # Fill occasional gaps so the ribbon and skirt stay continuous.
    if np.isnan(oz).any():
        idx = np.arange(len(oz))
        ok = np.isfinite(oz)
        oz = np.interp(idx, idx[ok], oz[ok])

    fig = go.Figure()

    # Vertical "curtain" from the track down to the base plane → depth cue.
    m = len(ox)
    base = np.full(m, np.nanmin(oz) - 40.0)          # 4 m below the low point
    vi = np.arange(m - 1)
    fig.add_trace(go.Mesh3d(
        x=np.concatenate([ox, ox]), y=np.concatenate([oy, oy]),
        z=np.concatenate([oz, base]),
        i=np.concatenate([vi, vi + 1]),
        j=np.concatenate([vi + 1, m + vi + 1]),
        k=np.concatenate([m + vi, m + vi]),
        color="#232330", opacity=0.55, flatshading=True,
        hoverinfo="skip", showlegend=False,
    ))
    # Track ribbon coloured by elevation (same Turbo scale as the 2D relief map).
    fig.add_trace(go.Scatter3d(
        x=ox, y=oy, z=oz, mode="lines",
        line=dict(color=oz / 10.0, colorscale="Turbo", width=7),
        hoverinfo="skip", showlegend=False,
    ))
    xs, ys = _frame0(payload)
    zs = [payload["outline"]["z"][d["didx"][0]] if d["didx"][0] is not None else None
          for d in payload["drivers"]]
    kw = _cars_kwargs(payload)
    kw["marker"]["size"] = 5
    fig.add_trace(go.Scatter3d(x=xs, y=ys, z=zs, **kw))

    xr = float(np.ptp(ox)) or 1.0
    yr = float(np.ptp(oy)) or 1.0
    zr = float(np.ptp(oz)) or 1.0
    # Aspect scaled so the longest track axis spans 1.5 scene units — the
    # track fills the viewport instead of floating small in the middle.
    # 5× vertical exaggeration, floored so nearly-flat circuits (Melbourne:
    # ~2.5 m over 5.3 km) still show a readable relief.
    scale = 1.5 / max(xr, yr)
    z_aspect = max(zr * scale * _Z_EXAGGERATION, 0.07)
    axkw = dict(visible=False, showgrid=False, zeroline=False,
                showbackground=False)
    fig.update_layout(
        height=560, paper_bgcolor=CARD_BG, showlegend=False,
        margin=dict(l=0, r=0, t=0, b=0),
        # no uirevision: every switch to 3D re-opens on the side view so the
        # elevation idea reads immediately (presets/orbit from there).
        scene=dict(
            xaxis=axkw, yaxis=axkw, zaxis=axkw,
            aspectmode="manual",
            aspectratio=dict(x=xr * scale, y=yr * scale, z=z_aspect),
            camera=dict(eye=dict(x=0, y=-1.6, z=0.12),
                        up=dict(x=0, y=0, z=1)),
            bgcolor=CARD_BG,
        ),
    )
    return fig


def _fig_strip(payload: dict) -> go.Figure:
    """Elevation profile strip: distance along the lap vs relative altitude,
    with the same car dots sliding along it (synced by the clientside tick)."""
    o = payload["outline"]
    dist = o["dist"]
    z_m = [v / 10.0 if v is not None else None for v in o["z"]]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dist, y=z_m, mode="lines", fill="tozeroy",
        line=dict(color="#55556A", width=1.5),
        fillcolor="rgba(70,70,95,0.25)",
        hovertemplate="%{x:.0f} m · +%{y:.1f} m<extra></extra>",
        showlegend=False,
    ))
    xs0 = [dist[d["didx"][0]] if d["didx"][0] is not None else None
           for d in payload["drivers"]]
    ys0 = [z_m[d["didx"][0]] if d["didx"][0] is not None else None
           for d in payload["drivers"]]
    kw = _cars_kwargs(payload)
    kw["mode"] = "markers"                      # codes would clutter the strip
    kw.pop("text"), kw.pop("textposition"), kw.pop("textfont")
    kw["marker"]["size"] = 8
    fig.add_trace(go.Scatter(x=xs0, y=ys0, **kw))
    fig.update_layout(
        height=160, paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=10),
        margin=dict(l=45, r=10, t=6, b=28), showlegend=False,
        xaxis=dict(title=dict(text="track distance (m)", font=dict(size=9)),
                   gridcolor=GRID_CLR, zeroline=False),
        yaxis=dict(title=dict(text="elev (m)", font=dict(size=9)),
                   gridcolor=GRID_CLR, zeroline=False),
        uirevision="replaystrip",
    )
    return fig


# ─────────────────────────────────────────────────────────────
# Card layout
# ─────────────────────────────────────────────────────────────

_BTN_STYLE = {"fontSize": "0.75rem", "padding": "3px 12px"}


def _slider_marks(payload: dict) -> dict:
    """Slider marks at lap 1 and every 10th lap."""
    lap_arr = np.asarray(payload["lap"])
    marks = {}
    for lp in [1] + list(range(10, payload["nLaps"] + 1, 10)):
        hits = np.flatnonzero(lap_arr == lp)
        if hits.size:
            marks[int(hits[0])] = {"label": f"L{lp}",
                                   "style": {"color": TEXT_DIM,
                                             "fontSize": "0.65rem"}}
    return marks


def _status_line(payload: dict) -> str:
    return (f"  {payload['event']} {payload['season']} · "
            f"{payload['nLaps']} laps · {len(payload['drivers'])} cars · "
            f"{payload['n']:,} frames @ {1 / payload['dt']:.0f} Hz")


def _view_options(has_z: bool) -> list[dict]:
    return [{"label": " 2D ", "value": "2d"},
            {"label": " 3D ", "value": "3d", "disabled": not has_z}]


def replay_card(season: int, meeting: str, codes: list[str] | None = None) -> html.Div:
    """The Race Replay card (embedded near the top of the RACE tab).

    `codes` is the sidebar Driver/Team filter (Driver_Short codes of the cars
    to show). When the replay payload is already cached the card renders fully
    loaded — so a filter change (which re-renders the tab) re-applies the
    filter with no extra click; otherwise 'Load replay' builds it once."""
    # Auto-load from cache: the tab re-renders on every sidebar filter change,
    # so a cached replay comes back instantly with the new filter applied.
    payload = cached_payload(season, meeting)
    fp = _filtered_payload(payload, codes) if payload else None
    loaded = fp is not None
    has_z = bool(fp["has_z"]) if loaded else False

    controls = html.Div([
        dbc.Button("▶ Play", id="replay-play", size="sm", color="danger",
                   disabled=True, n_clicks=0, style=_BTN_STYLE),
        html.Span("SPEED", style={"color": TEXT_DIM, "fontSize": "0.65rem",
                                  "letterSpacing": "1px", "marginLeft": "18px"}),
        dcc.RadioItems(
            id="replay-speed",
            options=[{"label": f" {v}× ", "value": v} for v in (5, 15, 30, 60, 120)],
            value=30, inline=True,
            inputStyle={"marginLeft": "10px", "marginRight": "3px",
                        "accentColor": ACCENT},
            style={"display": "inline-block", "color": TEXT_MAIN,
                   "fontSize": "0.78rem"},
        ),
        html.Span("VIEW", style={"color": TEXT_DIM, "fontSize": "0.65rem",
                                 "letterSpacing": "1px", "marginLeft": "18px"}),
        dcc.RadioItems(
            id="replay-view",
            options=_view_options(has_z),
            value="2d", inline=True,
            inputStyle={"marginLeft": "10px", "marginRight": "3px",
                        "accentColor": ACCENT},
            style={"display": "inline-block", "color": TEXT_MAIN,
                   "fontSize": "0.78rem"},
        ),
        html.Span(id="replay-camera-wrap", children=[
            dbc.ButtonGroup([
                dbc.Button("Top",  id="replay-cam-top",  size="sm",
                           color="secondary", outline=True, n_clicks=0,
                           style=_BTN_STYLE),
                dbc.Button("Side", id="replay-cam-side", size="sm",
                           color="secondary", outline=True, n_clicks=0,
                           style=_BTN_STYLE),
                dbc.Button("Iso",  id="replay-cam-iso",  size="sm",
                           color="secondary", outline=True, n_clicks=0,
                           style=_BTN_STYLE),
            ]),
            html.Span(
                "drag / scroll to orbit & zoom — the cars hold still while "
                "you move the camera and catch up on release",
                style={"color": TEXT_DIM, "fontSize": "0.68rem",
                       "marginLeft": "10px", "fontStyle": "italic"},
            ),
        ], style={"display": "none", "marginLeft": "14px"}),
        html.Span(id="replay-clock", children="", style={
            "color": ACCENT, "fontWeight": "800", "fontSize": "0.95rem",
            "fontVariantNumeric": "tabular-nums", "marginLeft": "auto",
        }),
    ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap",
              "gap": "4px", "marginTop": "10px"})

    body = html.Div([
        dcc.Store(id="replay-meta",
                  data={"season": int(season), "meeting": meeting,
                        "codes": list(codes) if codes else None}),
        dcc.Store(id="replay-data", data=fp),
        html.Div(id="replay-camera-dummy", style={"display": "none"}),
        html.Div([
            dbc.Button("Load replay", id="replay-load-btn", color="danger",
                       size="sm", n_clicks=0,
                       style=None if not loaded else {"display": "none"}),
            html.Span(id="replay-status",
                      children=(_status_line(fp) if loaded else
                                "  builds the position grid from race telemetry "
                                "(a few seconds the first time, then cached)"),
                      style={"color": TEXT_DIM, "fontSize": "0.75rem",
                             "marginLeft": "10px"}),
        ], style={"marginBottom": "8px"}),
        dcc.Loading(
            dcc.Graph(id="replay-graph",
                      figure=(_fig_replay_2d(fp) if loaded else
                              _empty_fig("Press “Load replay” to start")),
                      config=GFX),
            type="default",
        ),
        html.Div(
            dcc.Graph(id="replay-strip",
                      figure=(_fig_strip(fp) if loaded and has_z else
                              _empty_fig("")),
                      config=GFX),
            id="replay-strip-wrap",
            style={"display": "block" if (loaded and has_z) else "none"},
        ),
        controls,
        dcc.Slider(id="replay-slider", min=0,
                   max=(fp["n"] - 1) if loaded else 1, step=1, value=0,
                   marks=_slider_marks(fp) if loaded else None,
                   updatemode="drag",
                   tooltip={"placement": "bottom", "always_visible": False}),
        dcc.Interval(id="replay-interval", interval=100, disabled=True),
    ])

    return card(
        "Race Replay",
        body,
        info=("Data: every car's X/Y/Z position stream (100% coverage via "
              "FastF1's merge_channels), interpolated onto a shared 2 Hz time "
              "grid from lights-out to the last lap, snapped to the reference "
              "track line for elevation — built once per race and cached to "
              "data/replays/. Animation runs entirely in the browser (no "
              "server round-trips): play/pause, scrub the slider, change "
              "playback speed, or switch to the 3D view (elevation exaggerated "
              "5× — use the Top/Side/Iso camera presets or drag to orbit; "
              "while you orbit/zoom during playback the cars hold still and "
              "catch up on release — redrawing them mid-drag would cancel the "
              "camera gesture, a WebGL rendering limitation). "
              "The strip below the map is the lap's elevation profile with the "
              "same cars sliding along it. Why: the race as it actually "
              "unfolded in space — undercuts, safety-car bunching, backmarker "
              "traffic and gap evolution, visible as motion instead of charts."),
    )


# ─────────────────────────────────────────────────────────────
# Server callbacks
# ─────────────────────────────────────────────────────────────

@callback(
    Output("replay-data", "data"),
    Output("replay-graph", "figure"),
    Output("replay-strip", "figure"),
    Output("replay-strip-wrap", "style"),
    Output("replay-slider", "max"),
    Output("replay-slider", "marks"),
    Output("replay-status", "children"),
    Output("replay-view", "options"),
    Input("replay-load-btn", "n_clicks"),
    State("replay-meta", "data"),
    State("replay-view", "value"),
    prevent_initial_call=True,
)
def _build_replay(n_clicks, meta, view):
    if not n_clicks or not meta:
        return (no_update,) * 8
    try:
        payload = build_replay_payload(meta["season"], meta["meeting"])
    except Exception as exc:
        logger.exception("replay build failed")
        return (no_update, no_update, no_update, no_update, no_update, no_update,
                f"  replay build failed: {exc}", no_update)
    if payload is None:
        return (no_update, no_update, no_update, no_update, no_update, no_update,
                "  no position telemetry available for this race.", no_update)

    fp = _filtered_payload(payload, meta.get("codes"))
    has_z = fp["has_z"]
    fig = (_fig_replay_3d(fp) if (view == "3d" and has_z)
           else _fig_replay_2d(fp))
    strip_fig = _fig_strip(fp) if has_z else no_update
    strip_style = {"display": "block"} if has_z else {"display": "none"}
    return (fp, fig, strip_fig, strip_style,
            fp["n"] - 1, _slider_marks(fp), _status_line(fp),
            _view_options(has_z))


@callback(
    Output("replay-graph", "figure", allow_duplicate=True),
    Output("replay-camera-wrap", "style"),
    Input("replay-view", "value"),
    State("replay-data", "data"),
    prevent_initial_call=True,
)
def _switch_view(view, payload):
    cam_style = ({"display": "inline-block", "marginLeft": "14px"}
                 if view == "3d" else {"display": "none"})
    if not payload:
        return no_update, cam_style
    fig = (_fig_replay_3d(payload) if (view == "3d" and payload["has_z"])
           else _fig_replay_2d(payload))
    return fig, cam_style


# ─────────────────────────────────────────────────────────────
# Clientside callbacks (implementations in assets/replay.js)
# ─────────────────────────────────────────────────────────────

# Payload arrived → reset the JS playhead, enable Play, rewind the slider.
clientside_callback(
    "window.dash_clientside.replay.onData",
    Output("replay-play", "disabled"),
    Output("replay-slider", "value"),
    Input("replay-data", "data"),
)

# Interval tick → advance the playhead, restyle the dots, move the slider.
clientside_callback(
    "window.dash_clientside.replay.tick",
    Output("replay-slider", "value", allow_duplicate=True),
    Input("replay-interval", "n_intervals"),
    State("replay-speed", "value"),
    State("replay-data", "data"),
    prevent_initial_call=True,
)

# Slider moved (user scrub or tick) → seek + update the clock.
clientside_callback(
    "window.dash_clientside.replay.seek",
    Output("replay-clock", "children"),
    Input("replay-slider", "value"),
    State("replay-data", "data"),
    prevent_initial_call=True,
)

# Play / pause toggle.
clientside_callback(
    "window.dash_clientside.replay.playPause",
    Output("replay-interval", "disabled"),
    Output("replay-play", "children"),
    Input("replay-play", "n_clicks"),
    State("replay-data", "data"),
    prevent_initial_call=True,
)

# Camera presets (3D view) — pure Plotly.relayout, dummy output.
clientside_callback(
    "window.dash_clientside.replay.camera",
    Output("replay-camera-dummy", "children"),
    Input("replay-cam-top", "n_clicks"),
    Input("replay-cam-side", "n_clicks"),
    Input("replay-cam-iso", "n_clicks"),
    prevent_initial_call=True,
)
