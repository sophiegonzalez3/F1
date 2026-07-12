"""
TELEMETRY tab — best-lap leaderboard + telemetry channel overlay + corner
analysis + mini-sector delta decomposition + racing-line overlay + mini-
sector heatmap. Adds the driver-style fingerprint section at the bottom.
Extracted from app.py.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import (
    html, dcc, dash_table, callback, no_update,
    Input, Output, State,
)
import dash_bootstrap_components as dbc

import f1lib.state as state
from f1lib.components import (
    theme, card, kpi, GFX, TABLE_STYLE, styled_table,
    badge as _badge, abbr as _abbr, hex_to_rgba as _hex_to_rgba,
)
from f1lib.config import (
    TEAM_COLORS, COMPOUND_COLORS, get_driver_color,
    ACCENT, CARD_BG, TEXT_MAIN, TEXT_DIM, GRID_CLR,
    SPEED_PERCENTILE, MINI_SECTORS,
)
from f1lib.processing import (
    best_laps_table, format_lap_time,
)
from tabs.fingerprints import fingerprint_section

# mirror data state so bare `laps`, `telemetry`, SESSIONS, etc. still resolve
state.register(globals())


def _get_track_map():
    """Lazy handle to app.get_track_map (which still lives in app.py during
    the TRACK-tab extraction). Called by corner-marker code below."""
    import app
    return getattr(app, "get_track_map", None)


_LAPTEL_CHANNELS = ["Speed", "Throttle", "Brake", "GearNo"]
_LAPTEL_DASHES   = ["solid", "dash", "dot", "dashdot", "longdash"]


def _rotate(x, y, angle):
    """Rotate point(s) (x, y) by *angle* radians — matches FastF1's example.
    Local copy (same as tabs/track.py, tabs/replay.py) so the racing-line
    overlay can orient laps in the circuit frame without importing that tab."""
    ca, sa = np.cos(angle), np.sin(angle)
    return x * ca - y * sa, x * sa + y * ca


def _lap_telemetry(session, driver_short, lapno, tel_pool=None):
    """Telemetry samples belonging to one lap, with a lap-relative time column.

    Locates the lap in the global ``laps`` frame (by session / driver / lap
    number), reads its [LapStartTime, LapStartTime+LapTime_s] window, and slices
    the global ``telemetry`` frame to that driver+window. Returns
    ``(tel_sub_sorted_by_t_rel, lap_row)`` or ``(None, lap_row_or_None)``.

    ``tel_pool`` — optional pre-filtered telemetry subframe (same session +
    driver). Callers that window many laps pass per-driver pools so each call
    slices a few thousand rows instead of re-scanning the full multi-million-
    row frame; the masks below are identical either way.
    """
    src = tel_pool if tel_pool is not None else telemetry
    if src is None or src.empty:
        return None, None
    lp = laps[(laps["session_name"] == session)
              & (laps["Driver_Short"] == driver_short)
              & (laps["LapNo"] == lapno)]
    if lp.empty:
        return None, None
    row   = lp.iloc[0]
    dno   = str(row["DriverNo"]).strip()
    start = pd.to_numeric(row.get("LapStartTime"), errors="coerce")
    dur   = pd.to_numeric(row.get("LapTime_s"),    errors="coerce")
    if not (np.isfinite(start) and np.isfinite(dur)):
        return None, row
    tel = src[
        (src["session_name"] == session)
        & (src["DriverNo"].astype(str).str.strip() == dno)
        & (src["timestamp"] >= start)
        & (src["timestamp"] <= start + dur)
    ].copy()
    if tel.empty:
        return None, row
    tel = tel.sort_values("timestamp")
    tel["t_rel"] = tel["timestamp"] - start
    # Distance from the start line (m), integrating speed (km/h→m/s) over time —
    # the same quantity FastF1's Telemetry.add_distance() produces.
    if "Speed" in tel.columns:
        spd = pd.to_numeric(tel["Speed"], errors="coerce").fillna(0).to_numpy() * (1000.0 / 3600.0)
        t   = pd.to_numeric(tel["t_rel"], errors="coerce").fillna(method="ffill").fillna(0).to_numpy()
        if len(t) > 1:
            dt   = np.diff(t)
            avg  = (spd[1:] + spd[:-1]) / 2.0
            tel["Distance"] = np.concatenate([[0.0], np.cumsum(avg * dt)])
        else:
            tel["Distance"] = 0.0
    return tel, row


def _best_lap_telemetry_frame(fl):
    """Concatenated telemetry of each driver's single best valid lap across all
    loaded sessions in *fl* (one best lap per driver). Tagged with Driver_Short
    and Team. Used by the Max-Speed / Gear-usage charts, the mini-sector
    heatmap, and the style fingerprints.

    Splits the telemetry into per-(session, driver) pools with ONE pass first;
    windowing each lap then works on a few thousand rows. The old version
    re-scanned the full frame per driver, which cost ~18 s per call on a
    five-session weekend."""
    v = fl[fl["ValidLap"]].copy()
    v = v[pd.to_numeric(v["LapTime_s"], errors="coerce") > 0]
    if v.empty or telemetry is None or telemetry.empty:
        return pd.DataFrame()
    idx  = v.groupby("Driver_Short")["LapTime_s"].idxmin()
    best = v.loc[idx]

    pool_src = telemetry[telemetry["session_name"].isin(set(best["session_name"]))]
    pool_src = pool_src.assign(
        _dno=pool_src["DriverNo"].astype(str).str.strip())
    pools = {k: g for k, g in pool_src.groupby(["session_name", "_dno"])}

    parts = []
    for _, row in best.iterrows():
        pool = pools.get((row["session_name"], str(row["DriverNo"]).strip()))
        if pool is None:
            continue
        tel, _ = _lap_telemetry(row["session_name"], row["Driver_Short"],
                                row["LapNo"], tel_pool=pool)
        if tel is None or tel.empty:
            continue
        tel = tel.copy()
        tel["Driver_Short"] = row["Driver_Short"]
        tel["Team"]         = row["Team"]
        parts.append(tel)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


_CORNER_FRAC_CACHE: dict[tuple, pd.DataFrame] = {}


def _corner_fractions_from_geometry(line, corners) -> pd.DataFrame:
    """Each corner's fractional position along the lap (0=start line, 1=lap end),
    from the cached track-line + corner X/Y. Unit-independent, so it can be scaled
    by any lap's measured distance. Returns DataFrame[label, frac] sorted by frac."""
    if (line is None or corners is None or line.empty or corners.empty
            or not {"X", "Y"}.issubset(line.columns)
            or not {"X", "Y"}.issubset(corners.columns)):
        return pd.DataFrame()
    lx = line["X"].to_numpy(float); ly = line["Y"].to_numpy(float)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(lx), np.diff(ly)))])
    total = cum[-1]
    if not np.isfinite(total) or total <= 0:
        return pd.DataFrame()
    rows = []
    for _, c in corners.iterrows():
        i = int(np.argmin((lx - c["X"]) ** 2 + (ly - c["Y"]) ** 2))
        num = c.get("Number")
        letter = c.get("Letter")
        letter = "" if (letter is None or (isinstance(letter, float) and np.isnan(letter))) else str(letter).strip()
        try:
            label = f"{int(num)}{letter}"
        except (TypeError, ValueError):
            label = f"{num}{letter}"
        rows.append({"label": label, "frac": cum[i] / total})
    return pd.DataFrame(rows).sort_values("frac").reset_index(drop=True)


def _session_meeting_season(session_name) -> tuple[int | None, str | None]:
    """Recover (season, meeting) from a lap's session_name. session_name is built
    as f'{session}_{meeting}_{season}', so prefer an exact match against the loaded
    session info, then fall back to parsing."""
    for info in LOADED_SESSION_INFO:
        sn = f"{info.get('SESSION')}_{info.get('MEETING')}_{info.get('SEASON')}"
        if sn == session_name:
            try:
                return int(info.get("SEASON")), str(info.get("MEETING"))
            except (TypeError, ValueError):
                return None, str(info.get("MEETING"))
    toks = str(session_name).split("_")
    if len(toks) >= 3:
        try:
            return int(toks[-1]), "_".join(toks[1:-1])
        except ValueError:
            return None, "_".join(toks[1:-1])
    return None, None


def _corner_fractions_for(season, event) -> pd.DataFrame:
    """Corner fractional positions for a specific circuit. Uses the app's track-map
    cache and, if that circuit isn't cached yet, fetches it once via get_track_map
    (which then persists it). Result is memoised per (season, event); empty on
    failure so corner markers are simply omitted."""
    if not season or not event:
        return pd.DataFrame()
    key = (int(season), str(event))
    if key in _CORNER_FRAC_CACHE:
        return _CORNER_FRAC_CACHE[key]
    out = pd.DataFrame()
    for sid in ("Q", "R"):           # quali gives the cleanest lap; race as fallback
        try:
            tm = _get_track_map()(season, event, sid)
        except Exception as exc:
            logging.warning("corner markers: track map fetch failed for %s %s (%s): %s",
                            season, event, sid, exc)
            tm = None
        if tm and tm.get("corners") is not None and not tm["corners"].empty:
            out = _corner_fractions_from_geometry(tm.get("line"), tm["corners"])
            if not out.empty:
                break
    _CORNER_FRAC_CACHE[key] = out
    return out


def _prewarm_track_maps(session_info_list) -> None:
    """Fetch + cache the track map (corner geometry) for each loaded meeting in a
    daemon thread, so the Telemetry Channels corner markers are ready without a
    long blocking fetch the first time that circuit's laps are viewed. Safe to call
    repeatedly — get_track_map / the memo skip already-cached circuits."""
    if _get_track_map() is None:
        return
    seen: set[tuple] = set()
    targets = []
    for info in session_info_list:
        try:
            season = int(info.get("SEASON"))
        except (TypeError, ValueError):
            continue
        event = str(info.get("MEETING", "")).strip()
        if not event or (season, event) in seen:
            continue
        seen.add((season, event))
        targets.append((season, event))
    if not targets:
        return

    def _worker():
        for season, event in targets:
            try:
                _corner_fractions_for(season, event)
            except Exception:
                pass

    import threading
    threading.Thread(target=_worker, name="track-map-prewarm", daemon=True).start()


# From now on, session reloads (Data Selection tab) prewarm the track-map
# cache in the background. The initial import-time load intentionally runs
# before this hook exists — same behaviour as before the state extraction.
state.post_load_hook = _prewarm_track_maps


def _empty_channel_fig(msg):
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
                       showarrow=False, font=dict(size=13, color=TEXT_DIM))
    theme(fig, 360, "")
    fig.update_xaxes(visible=False); fig.update_yaxes(visible=False)
    return fig


def _laptel_channel_fig(lap_specs):
    """Overlay Speed/Throttle/Brake/Gear traces for each selected lap, aligned on
    lap-relative time so different laps (and drivers) line up. *lap_specs* is a
    list of (session, driver_short, lapno)."""
    if telemetry is None or telemetry.empty:
        return _empty_channel_fig("No telemetry data loaded.")
    channels = [c for c in _LAPTEL_CHANNELS if c in telemetry.columns]
    if not channels:
        return _empty_channel_fig("No telemetry channels available.")

    MAX_POINTS = 2000
    fig = make_subplots(rows=len(channels), cols=1, shared_xaxes=True,
                        vertical_spacing=0.04, subplot_titles=channels)
    any_trace = False
    lap_totals = []                       # measured lap distance (m) per plotted lap
    marker_session = None                 # session_name of the first plotted lap
    for i, (session, driver, lapno) in enumerate(lap_specs):
        tel, row = _lap_telemetry(session, driver, lapno)
        if tel is None or tel.empty:
            continue
        if marker_session is None:
            marker_session = session
        use_dist = "Distance" in tel.columns
        xcol = "Distance" if use_dist else "t_rel"
        if use_dist:
            lap_totals.append(float(tel["Distance"].iloc[-1]))
        clr   = TEAM_COLORS.get(row["Team"], "#808080") if row is not None else "#808080"
        dash  = _LAPTEL_DASHES[i % len(_LAPTEL_DASHES)]
        stride = max(1, len(tel) // MAX_POINTS)
        if stride > 1:
            tel = tel.iloc[::stride]
        label = f"{driver} · {str(session).split('_')[0]} (L{int(lapno)})"
        xunit = "m" if use_dist else "s"
        for r, ch in enumerate(channels, start=1):
            fig.add_trace(go.Scattergl(
                x=tel[xcol], y=tel[ch], mode="lines",
                name=label, legendgroup=label, showlegend=(r == 1),
                line=dict(color=clr, width=1.1, dash=dash),
                hovertemplate=f"<b>{label}</b><br>{ch}: %{{y}}<br>%{{x:.0f}} {xunit}<extra></extra>",
            ), row=r, col=1)
        any_trace = True

    if not any_trace:
        return _empty_channel_fig(
            "No telemetry found for the selected lap(s) — they may predate the "
            "loaded telemetry window.")

    # ── Corner markers (only meaningful on a distance x-axis) ──
    on_distance = bool(lap_totals)
    if on_distance and marker_session:
        season, event = _session_meeting_season(marker_session)
        corner_df = _corner_fractions_for(season, event)
        if not corner_df.empty:
            ref_total = float(np.median(lap_totals))
            line_kw = dict(color="rgba(150,150,150,0.45)", width=1, dash="dot")
            for _, cr in corner_df.iterrows():
                xx = float(cr["frac"]) * ref_total
                # label only on the top subplot; plain dotted lines below
                fig.add_vline(x=xx, row=1, col=1, layer="below", line=line_kw,
                              annotation_text=str(cr["label"]),
                              annotation_position="top",
                              annotation_font=dict(size=8, color=TEXT_DIM))
                for r in range(2, len(channels) + 1):
                    fig.add_vline(x=xx, row=r, col=1, layer="below", line=line_kw)

    for r, ch in enumerate(channels, start=1):
        fig.update_yaxes(title_text=ch, gridcolor=GRID_CLR, zeroline=False, row=r, col=1)
    fig.update_xaxes(
        title_text="Distance from start line (m)" if on_distance else "Time since lap start (s)",
        row=len(channels), col=1)
    fig.update_layout(
        height=max(150 * len(channels) + 60, 320),
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
        legend=dict(bgcolor="rgba(0,0,0,0)"), margin=dict(l=60, r=20, t=60, b=45))
    fig.update_xaxes(gridcolor=GRID_CLR, zeroline=False)
    return fig


# ── Corner Analysis ───────────────────────────────────────────────
# Segment a lap by corner (using the cached corner geometry) and extract,
# per corner, the braking point and the entry / apex / exit speeds. Built on
# the same integrated-Distance telemetry + corner fractions that drive the
# Telemetry Channels overlay, so it needs no extra data source.
_CORNER_ENTRY_CLR = "#4FC3F7"   # light blue  — speed at brake onset
_CORNER_APEX_CLR  = "#FF6E6E"   # red         — minimum (apex) speed
_CORNER_EXIT_CLR  = "#7CE38B"   # green       — speed back on full throttle


def _corner_metrics(tel) -> pd.DataFrame:
    """Per-corner braking & speed metrics for one lap's telemetry.

    *tel* is the frame returned by :func:`_lap_telemetry` (needs ``Distance``,
    ``Speed``; uses ``Brake``/``Throttle``/``GearNo`` when present). Corners are
    located from the cached circuit geometry via :func:`_corner_fractions_for`,
    scaled to this lap's measured length, and the lap is split into one zone per
    corner at the midpoints between consecutive corners.

    Returns DataFrame[label, frac, apex_dist, entry_speed, apex_speed,
    exit_speed, brake_dist, brake_point, min_gear] sorted by distance, or empty.
    """
    if tel is None or tel.empty or "Distance" not in tel.columns:
        return pd.DataFrame()
    season, event = _session_meeting_season(tel["session_name"].iloc[0]) \
        if "session_name" in tel.columns else (None, None)
    corner_df = _corner_fractions_for(season, event)
    if corner_df.empty:
        return pd.DataFrame()

    t = tel.sort_values("Distance").reset_index(drop=True)
    dist = pd.to_numeric(t["Distance"], errors="coerce").to_numpy()
    total = float(dist[-1]) if len(dist) else 0.0
    if not np.isfinite(total) or total <= 0:
        return pd.DataFrame()
    spd  = pd.to_numeric(t.get("Speed"), errors="coerce").to_numpy()
    brk  = (pd.to_numeric(t["Brake"], errors="coerce").fillna(0).to_numpy()
            if "Brake" in t.columns else None)
    thr  = (pd.to_numeric(t["Throttle"], errors="coerce").to_numpy()
            if "Throttle" in t.columns else None)
    gear = (pd.to_numeric(t["GearNo"], errors="coerce").to_numpy()
            if "GearNo" in t.columns else None)

    cd = corner_df.copy()
    cd["dist"] = cd["frac"].astype(float) * total
    cd = cd.sort_values("dist").reset_index(drop=True)
    centers = cd["dist"].to_numpy()
    n = len(centers)

    rows = []
    for i in range(n):
        lo = 0.0   if i == 0     else (centers[i - 1] + centers[i]) / 2.0
        hi = total if i == n - 1 else (centers[i] + centers[i + 1]) / 2.0
        idx = np.where((dist >= lo) & (dist <= hi))[0]
        if idx.size == 0 or np.all(np.isnan(spd[idx])):
            continue
        # Apex = slowest point in the zone.
        apex = idx[int(np.nanargmin(spd[idx]))]
        apex_speed, apex_dist = spd[apex], dist[apex]

        # Braking point: first sample on the approach (zone start → apex) where
        # the brake is applied. brake_dist = metres of braking before the apex.
        brake_dist = np.nan; brake_point = np.nan; entry_speed = np.nan
        if brk is not None:
            appr = idx[idx <= apex]
            on   = np.where(brk[appr] > 0.5)[0]
            if on.size:
                bp = appr[on[0]]
                brake_point = dist[bp]
                brake_dist  = apex_dist - brake_point
                entry_speed = spd[bp]
        if not np.isfinite(entry_speed):           # no brake trace → zone-start speed
            entry_speed = spd[idx[0]]

        # Exit = first point after the apex back on (near-)full throttle, else
        # the end of the zone.
        post = idx[idx >= apex]
        exit_speed = spd[post[-1]] if post.size else apex_speed
        if thr is not None and post.size:
            up = np.where(thr[post] >= 95)[0]
            if up.size:
                exit_speed = spd[post[up[0]]]

        min_gear = np.nan
        if gear is not None and np.isfinite(np.nanmin(gear[idx])):
            min_gear = int(np.nanmin(gear[idx]))

        rows.append({
            "label": cd["label"].iloc[i], "frac": float(cd["frac"].iloc[i]),
            "apex_dist": apex_dist, "entry_speed": entry_speed,
            "apex_speed": apex_speed, "exit_speed": exit_speed,
            "brake_dist": brake_dist, "brake_point": brake_point,
            "min_gear": min_gear,
        })
    return pd.DataFrame(rows)


def _corner_analysis(specs):
    """Build the Corner Analysis outputs for the selected lap(s).

    *specs* is a list of (session, driver_short, lapno). Returns
    ``(fig_speed, fig_brake, table_records, table_columns)``. When a single lap
    is selected the speed chart shows its full entry/apex/exit profile; with
    several laps it overlays each lap's apex speed for a direct comparison.
    """
    metrics = []   # (label_str, team, dataframe)
    for session, driver, lapno in specs:
        tel, row = _lap_telemetry(session, driver, lapno)
        if tel is None or tel.empty:
            continue
        cm = _corner_metrics(tel)
        if cm.empty:
            continue
        team  = row["Team"] if row is not None else None
        label = f"{driver} · {str(session).split('_')[0]} (L{int(lapno)})"
        metrics.append((label, team, cm))

    if not metrics:
        msg = ("No corner geometry available for the selected lap(s) — the "
               "circuit map may still be downloading, or the laps predate the "
               "loaded telemetry window.")
        return (_empty_channel_fig(msg), _empty_channel_fig(msg), [], [])

    # Master corner order (by track position) across every plotted lap.
    order = (pd.concat([m[2][["label", "frac"]] for m in metrics])
               .drop_duplicates("label").sort_values("frac")["label"].tolist())

    fig_speed = go.Figure()
    fig_brake = go.Figure()
    single = len(metrics) == 1

    for i, (label, team, cm) in enumerate(metrics):
        clr  = TEAM_COLORS.get(team, "#808080")
        dash = _LAPTEL_DASHES[i % len(_LAPTEL_DASHES)]
        cm   = cm.set_index("label").reindex(order)
        x    = order

        if single:
            for ycol, cclr, nm in (("entry_speed", _CORNER_ENTRY_CLR, "Entry"),
                                   ("apex_speed",  _CORNER_APEX_CLR,  "Apex"),
                                   ("exit_speed",  _CORNER_EXIT_CLR,  "Exit")):
                fig_speed.add_trace(go.Scatter(
                    x=x, y=cm[ycol], mode="lines+markers", name=nm,
                    line=dict(color=cclr, width=2),
                    marker=dict(size=6),
                    hovertemplate=f"<b>%{{x}}</b><br>{nm}: %{{y:.0f}} km/h<extra></extra>"))
        else:
            fig_speed.add_trace(go.Scatter(
                x=x, y=cm["apex_speed"], mode="lines+markers", name=label,
                line=dict(color=clr, width=2, dash=dash), marker=dict(size=6),
                hovertemplate=(f"<b>{label}</b><br>%{{x}}<br>"
                               "Apex: %{y:.0f} km/h<extra></extra>")))

        # Bars, not lines: flat-out corners have no braking point (NaN), and a
        # line would draw misleading segments across those gaps. A missing bar
        # reads cleanly as "no braking here".
        fig_brake.add_trace(go.Bar(
            x=x, y=cm["brake_dist"], name=label, marker_color=clr,
            marker_pattern_shape=["", "/", ".", "x", "-"][i % 5],
            hovertemplate=(f"<b>{label}</b><br>%{{x}}<br>"
                           "Braking starts %{y:.0f} m before apex<extra></extra>")))

    theme(fig_speed, 380,
          "Corner Entry / Apex / Exit Speed" if single else "Apex Speed by Corner")
    fig_speed.update_layout(xaxis_title="Corner", yaxis_title="Speed (km/h)",
                            xaxis=dict(type="category", categoryorder="array",
                                       categoryarray=order))
    theme(fig_brake, 380, "Braking Point by Corner")
    fig_brake.update_layout(barmode="group", xaxis_title="Corner",
                            yaxis_title="Braking distance before apex (m)",
                            xaxis=dict(type="category", categoryorder="array",
                                       categoryarray=order))

    # Detail table (one row per corner per lap).
    recs = []
    for label, _team, cm in metrics:
        for _, r in cm.iterrows():
            recs.append({
                "Lap": label, "Corner": r["label"],
                "Entry": round(r["entry_speed"]) if np.isfinite(r["entry_speed"]) else None,
                "Apex":  round(r["apex_speed"])  if np.isfinite(r["apex_speed"])  else None,
                "Exit":  round(r["exit_speed"])  if np.isfinite(r["exit_speed"])  else None,
                "Brake (m)": round(r["brake_dist"]) if np.isfinite(r["brake_dist"]) else None,
                "Min Gear": int(r["min_gear"]) if np.isfinite(r["min_gear"]) else None,
            })
    cols = [{"name": c, "id": c} for c in
            ["Lap", "Corner", "Entry", "Apex", "Exit", "Brake (m)", "Min Gear"]]
    return fig_speed, fig_brake, recs, cols


# ── Delta decomposition by track sector ───────────────────────────
# Cumulative time-delta vs distance between selected laps, relative to the
# fastest one, plus a per-timing-sector breakdown of where the time goes.
# Uses _lap_telemetry's integrated Distance + the lap's SectorNTime values;
# no extra data source.
_SECTOR_FILL = ("rgba(255,255,255,0.00)", "rgba(255,255,255,0.035)")


def _minisector_times(dist, trel, n=MINI_SECTORS):
    """Per-mini-sector traversal times for one lap.

    Splits the lap into *n* equal-distance segments (edges at fractions
    0, 1/n … 1 of the lap's measured length) and returns the time spent in each
    by interpolating lap-relative time at the segment edges. *dist* must be
    strictly increasing. Returns a float array of length *n* (NaN where the lap
    is too short), so different laps' mini-sectors line up fraction-for-fraction.
    """
    dist = np.asarray(dist, float); trel = np.asarray(trel, float)
    if dist.size < 2 or not np.isfinite(dist[-1]) or dist[-1] <= 0:
        return np.full(n, np.nan)
    edges = np.linspace(0.0, dist[-1], n + 1)
    t_at  = np.interp(edges, dist, trel)
    return np.diff(t_at)


def _lap_trace(session, driver, lapno):
    """One lap as monotonic (distance, lap-relative time) arrays for interpolation.

    Returns a dict {dist, trel, total, row, label, team, laptime} or None.
    Distance comes from _lap_telemetry (cumulative speed integral, so it is
    non-decreasing); duplicate-distance samples are dropped so the array is
    strictly increasing and safe to use as np.interp's xp.
    """
    tel, row = _lap_telemetry(session, driver, lapno)
    if tel is None or tel.empty or "Distance" not in tel.columns:
        return None
    t = tel.sort_values("Distance")
    dist = pd.to_numeric(t["Distance"], errors="coerce").to_numpy()
    trel = pd.to_numeric(t["t_rel"], errors="coerce").to_numpy()
    ok = np.isfinite(dist) & np.isfinite(trel)
    dist, trel = dist[ok], trel[ok]
    if dist.size < 3:
        return None
    keep = np.concatenate([[True], np.diff(dist) > 0])   # strictly increasing
    dist, trel = dist[keep], trel[keep]
    if dist.size < 3:
        return None
    return {
        "dist": dist, "trel": trel, "total": float(dist[-1]), "row": row,
        "label": f"{driver} · {str(session).split('_')[0]} (L{int(lapno)})",
        "team": row["Team"] if row is not None else None,
        "laptime": pd.to_numeric(row.get("LapTime_s"), errors="coerce") if row is not None else np.nan,
    }


def _delta_decomposition(specs):
    """Delta-vs-distance trace + per-mini-sector breakdown for the selected laps.

    The fastest selected lap is the reference (the zero line); every other lap
    is plotted as cumulative time gained/lost against it. Returns
    ``(fig_delta, fig_sector)``. Needs at least two resolvable laps.
    """
    traces = [tr for tr in (_lap_trace(*s) for s in specs) if tr is not None]
    if len(traces) < 2:
        msg = "Select at least two laps in the Best Lap Leaderboard to compare deltas."
        return _empty_channel_fig(msg), _empty_channel_fig(msg)

    ref = min(traces, key=lambda t: t["laptime"] if np.isfinite(t["laptime"]) else t["trel"][-1])
    grid_max = min(t["total"] for t in traces)
    grid = np.linspace(0.0, grid_max, 600)
    tref = np.interp(grid, ref["dist"], ref["trel"])

    n = MINI_SECTORS
    ms_edges   = np.linspace(0.0, grid_max, n + 1)
    ms_centers = (ms_edges[:-1] + ms_edges[1:]) / 2.0

    fig_delta = go.Figure()
    fig_delta.add_hline(y=0, line=dict(color=TEAM_COLORS.get(ref["team"], "#AAAAAA"),
                                       width=1.4, dash="solid"))

    ms_rows = []              # (lap_label, team, per-mini-sector Δ array)
    di = 0
    for tr in traces:
        if tr is ref:
            continue
        ti = np.interp(grid, tr["dist"], tr["trel"])
        delta = ti - tref
        clr  = TEAM_COLORS.get(tr["team"], "#808080")
        dash = _LAPTEL_DASHES[di % len(_LAPTEL_DASHES)]; di += 1
        fig_delta.add_trace(go.Scatter(
            x=grid, y=delta, mode="lines", name=tr["label"],
            line=dict(color=clr, width=1.8, dash=dash),
            hovertemplate=(f"<b>{tr['label']}</b><br>%{{x:.0f}} m<br>"
                           "Δ %{y:+.3f}s<extra></extra>")))
        # Per-mini-sector delta = change in cumulative delta across each segment.
        cum_at = np.interp(ms_edges, grid, delta)
        ms_rows.append((tr["label"], tr["team"], np.diff(cum_at)))

    # Faint alternating mini-sector bands tie the trace to the bars below.
    for k in range(n):
        if k % 2:
            fig_delta.add_vrect(x0=ms_edges[k], x1=ms_edges[k + 1], layer="below",
                                line_width=0, fillcolor=_SECTOR_FILL[1])

    # Corner markers (same source as the channel overlay).
    season, event = _session_meeting_season(ref["row"]["session_name"]) \
        if ref["row"] is not None and "session_name" in ref["row"] else (None, None)
    corner_df = _corner_fractions_for(season, event)
    if not corner_df.empty:
        for _, cr in corner_df.iterrows():
            fig_delta.add_vline(x=float(cr["frac"]) * grid_max, layer="below",
                                line=dict(color="rgba(150,150,150,0.35)", width=1, dash="dot"))

    theme(fig_delta, 450, f"Time Delta vs Distance  ·  reference: {ref['label']}")
    fig_delta.update_layout(
        margin=dict(l=70, r=20, t=95, b=50),
        title=dict(y=0.96, yanchor="top"),
        xaxis_title="Distance from start line (m)",
        yaxis_title="Δ to reference (s)  ·  ↑ slower",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                    font=dict(size=10)))

    # ── Per-mini-sector bar (shared distance axis with the trace) ──
    fig_sector = go.Figure()
    if ms_rows:
        bar_w = (grid_max / n) * (0.8 / max(1, len(ms_rows)))
        for j, (label, team, vals) in enumerate(ms_rows):
            fig_sector.add_trace(go.Bar(
                x=ms_centers, y=vals, name=label, width=bar_w,
                offset=(j - (len(ms_rows) - 1) / 2.0) * bar_w,
                marker_color=TEAM_COLORS.get(team, "#808080"),
                marker_pattern_shape=["", "/", ".", "x", "-"][j % 5],
                hovertemplate=(f"<b>{label}</b><br>%{{x:.0f}} m<br>"
                               "Δ %{y:+.3f}s in this mini-sector<extra></extra>")))
        theme(fig_sector, 340, f"Time Gained / Lost per Mini-Sector  ·  vs {ref['label']}")
        fig_sector.update_layout(
            barmode="overlay",
            margin=dict(l=70, r=20, t=95, b=45),
            title=dict(y=0.96, yanchor="top"),
            xaxis_title="Distance from start line (m)",
            yaxis_title="Δ to reference (s)  ·  ↑ slower",
            legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                        font=dict(size=10)))
        fig_sector.add_hline(y=0, line=dict(color=TEXT_DIM, width=1))
    else:
        fig_sector = _empty_channel_fig("Could not compute mini-sector deltas.")
    return fig_delta, fig_sector


# ── Racing line comparison ────────────────────────────────────────
# Now possible because the telemetry frame carries X/Y track position (merged
# from FastF1's position stream in data_loader._fetch_telemetry). Each selected
# lap's actual driven line is drawn in the circuit's reference frame.
def _racing_line_fig(specs):
    """Overlay the actual driven X/Y line of each selected lap, oriented with the
    circuit rotation and annotated with corner numbers. A single lap is coloured
    by speed; several laps are team-coloured so you can see where the lines
    diverge — different apex, wider or tighter entry, earlier turn-in."""
    if telemetry is None or telemetry.empty or not {"X", "Y"}.issubset(telemetry.columns):
        return _empty_channel_fig(
            "No position (X/Y) telemetry loaded — re-fetch sessions to enable racing lines.")

    lines, marker_session = [], None
    for session, driver, lapno in specs:
        tel, row = _lap_telemetry(session, driver, lapno)
        if tel is None or tel.empty or not {"X", "Y"}.issubset(tel.columns):
            continue
        t = tel.dropna(subset=["X", "Y"])
        if len(t) < 10:
            continue
        lines.append((session, driver, lapno, row, t))
        if marker_session is None:
            marker_session = session
    if not lines:
        return _empty_channel_fig("No position data found for the selected lap(s).")

    season, event = _session_meeting_season(marker_session)
    try:
        tm = _get_track_map()(season, event, "Q")
    except Exception:
        tm = None
    ang = (tm["rotation"] / 180.0 * np.pi) if tm else 0.0
    single = len(lines) == 1

    fig = go.Figure()
    for i, (session, driver, lapno, row, t) in enumerate(lines):
        X, Y = _rotate(t["X"].to_numpy(float), t["Y"].to_numpy(float), ang)
        label = f"{driver} · {str(session).split('_')[0]} (L{int(lapno)})"
        if single and "Speed" in t.columns:
            spd = pd.to_numeric(t["Speed"], errors="coerce").to_numpy()
            # Thin neutral underlay so the line reads continuously, speed dots on top.
            fig.add_trace(go.Scattergl(
                x=X, y=Y, mode="lines", showlegend=False, hoverinfo="skip",
                line=dict(color="rgba(160,160,160,0.35)", width=1)))
            fig.add_trace(go.Scattergl(
                x=X, y=Y, mode="markers", name=label,
                marker=dict(size=5, color=spd, colorscale="Turbo", showscale=True,
                            colorbar=dict(title=dict(text="km/h", font=dict(color=TEXT_MAIN)),
                                          tickfont=dict(color=TEXT_MAIN), thickness=12)),
                hovertemplate=f"<b>{label}</b><br>%{{marker.color:.0f}} km/h<extra></extra>"))
        else:
            clr  = TEAM_COLORS.get(row["Team"], "#808080") if row is not None else "#808080"
            dash = _LAPTEL_DASHES[i % len(_LAPTEL_DASHES)]
            fig.add_trace(go.Scattergl(
                x=X, y=Y, mode="lines", name=label,
                line=dict(color=clr, width=2.4, dash=dash),
                hovertemplate=f"<b>{label}</b><extra></extra>"))

    # Corner numbers from the cached circuit geometry (same coordinate frame).
    if tm and tm.get("corners") is not None and not tm["corners"].empty:
        c = tm["corners"]
        cx, cy = _rotate(c["X"].to_numpy(float), c["Y"].to_numpy(float), ang)
        clabels = []
        for _, cc in c.iterrows():
            num, letter = cc.get("Number"), cc.get("Letter")
            letter = "" if letter is None or (isinstance(letter, float) and np.isnan(letter)) else str(letter).strip()
            try:
                clabels.append(f"{int(num)}{letter}")
            except (TypeError, ValueError):
                clabels.append(f"{num}{letter}")
        fig.add_trace(go.Scatter(
            x=cx, y=cy, mode="text", text=clabels, showlegend=False, hoverinfo="skip",
            textfont=dict(size=9, color=TEXT_DIM)))

    ttl = ("Racing Line — coloured by speed" if single
           else "Racing Line Comparison — where the lines diverge")
    from tabs.track import _track_map_layout   # shared equal-aspect track layout
    _track_map_layout(fig, ttl, height=560)
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left",
                                  x=0, bgcolor="rgba(0,0,0,0)", font=dict(size=10)))
    return fig


def tab_laps(fl, ft):
    # one heavy best-lap telemetry extraction, shared by the heatmap,
    # max-speed/gear charts and the style fingerprints
    blt = _best_lap_telemetry_frame(fl)
    sector_fig = _sector_heatmap(fl, blt=blt)

    bt=best_laps_table(fl)
    bt["Best Lap"]=bt["LapTime_s"].apply(format_lap_time)
    disp=bt[["session_name","Driver_Short","Team","Compound","Best Lap","LapTime_s","TyreAge","LapNo"]].rename(columns={
        "session_name":"Session","Driver_Short":"Driver","LapTime_s":"Lap Time (s)","TyreAge":"Tyre Age","LapNo":"Lap #"
    }).sort_values("Lap Time (s)").reset_index(drop=True)
    best_tbl=dash_table.DataTable(
        id="laptel-best-table",
        data=disp.to_dict("records"),
        columns=[{"name":c,"id":c} for c in disp.columns],
        row_selectable="multi",
        selected_rows=[0] if len(disp) else [],
        **TABLE_STYLE,
        style_data_conditional=[
            {"if":{"state":"selected"},
             "backgroundColor":ACCENT+"33","border":f"1px solid {ACCENT}"},
        ],
    )

    # ── Telemetry section ────────────────────────────────────────
    # Max-speed and gear use each driver's single best lap across all loaded
    # sessions (blt, computed once above); the channel overlay is driven by
    # the leaderboard selection.

    fig_spd = go.Figure()
    fig_gear = go.Figure()
    if not blt.empty and "Speed" in blt.columns:
        sp=(blt.groupby(["Driver_Short","Team"])["Speed"]
              .quantile(SPEED_PERCENTILE/100.0).reset_index())
        sp.columns=["Driver_Short","Team","MaxSpeed"]
        sp=sp.sort_values("MaxSpeed",ascending=False)
        for _,row in sp.iterrows():
            fig_spd.add_trace(go.Bar(x=[row["Driver_Short"]],y=[row["MaxSpeed"]],
                name=row["Driver_Short"],showlegend=False,
                marker_color=TEAM_COLORS.get(row["Team"],"#808080"),
                hovertemplate=f"<b>{row['Driver_Short']}</b><br>{SPEED_PERCENTILE}th pct: %{{y:.1f}} km/h<extra></extra>"))
        lo=sp["MaxSpeed"].min(); hi=sp["MaxSpeed"].max(); m=(hi-lo)*0.3 if hi>lo else 1
        theme(fig_spd,380,f"Maximum Speed by Driver ({SPEED_PERCENTILE}th pct of best lap)")
        fig_spd.update_layout(xaxis_title="Driver",yaxis_title="Max Speed (km/h)",xaxis=dict(tickangle=0,gridcolor=GRID_CLR,zeroline=False))
        fig_spd.update_yaxes(range=[lo-m,hi+m/4])
    else:
        fig_spd=_empty_channel_fig("No best-lap telemetry available.")

    if not blt.empty and "GearNo" in blt.columns:
        drv_team=blt.dropna(subset=["Driver_Short"]).groupby("Driver_Short")["Team"].first().to_dict()
        gp=(blt.groupby(["Driver_Short","Team","GearNo"]).size().reset_index(name="cnt"))
        gp["total"]=gp.groupby("Driver_Short")["cnt"].transform("sum")
        gp["pct"]=gp["cnt"]/gp["total"]*100
        drv_ord=sorted(gp["Driver_Short"].dropna().unique().tolist())
        drv_colors=[TEAM_COLORS.get(drv_team.get(d,"x"),"#808080") for d in drv_ord]
        for gear in sorted(gp["GearNo"].dropna().unique()):
            sub=gp[gp["GearNo"]==gear].set_index("Driver_Short")
            fig_gear.add_trace(go.Bar(
                x=drv_ord,
                y=[sub.loc[d,"pct"] if d in sub.index else 0 for d in drv_ord],
                name=f"Gear {int(gear)}",
                marker_color=drv_colors,
                hovertemplate="Driver: %{x}<br>Gear "+str(int(gear))+": %{y:.1f}%<extra></extra>"))
        theme(fig_gear,420,"Gear Usage Distribution by Driver (best lap)")
        fig_gear.update_layout(barmode="stack",xaxis_title="Driver",yaxis_title="Time in Gear (%)")
    else:
        fig_gear=_empty_channel_fig("No best-lap telemetry available.")

    ch_title=html.Span([
        "Telemetry Channels (Speed / Throttle / Brake / Gear)",
        html.Span(
            "  ·  vs distance, with corner markers  ·  select laps in the Best Lap "
            "Leaderboard above to overlay them",
            style={"color":TEXT_DIM,"fontWeight":"400","fontSize":"0.72rem","marginLeft":"6px"},
        ),
    ])

    return html.Div([
        card(f"Mini-Sector Dominance — best lap split into {MINI_SECTORS} segments, "
             "% gap to fastest",
             dcc.Graph(figure=sector_fig, config=GFX) if sector_fig.data else
             html.P("No telemetry available for the selected sessions.",
                    style={"color": TEXT_DIM}),
             info=(f"Data: each driver's single best lap is split into {MINI_SECTORS} "
                   "equal-distance mini-sectors (from the telemetry), and each cell is "
                   "coloured by that driver's % gap to the fastest driver through that "
                   "mini-sector (green = quickest there, red = slowest). Drivers are "
                   "ordered fastest lap on top. Why: far finer than the three timing "
                   "sectors — it shows exactly which stretches of track each driver "
                   "owns and where the lap time is really won or lost.")),
        card("Best Lap Leaderboard",
             info=("Data: each driver's best valid lap per compound and session, "
                   "ranked, with sector times and speed-trap figures. Why: the "
                   "entry point for telemetry work — tick laps here to overlay "
                   "their full telemetry traces in the charts below and see "
                   "where the time difference is made."),
             children=html.Div([
                 html.P("Select one or more laps (checkbox at left) to drive the "
                        "Telemetry Channels overlay below.",
                        style={"color":TEXT_DIM,"fontSize":"0.74rem","marginBottom":"8px"}),
                 best_tbl,
             ])),
        dbc.Row([dbc.Col(card("Maximum Speed",dcc.Graph(figure=fig_spd,config=GFX),
                              info=(f"Data: the {SPEED_PERCENTILE}th-percentile speed "
                                    "from each driver's single best lap across all "
                                    "loaded sessions (a robust 'top speed' that ignores "
                                    "one-off GPS spikes), team-coloured. Why: a proxy "
                                    "for straight-line speed / power-unit and drag.")),md=6),
                 dbc.Col(card("Gear Usage",dcc.Graph(figure=fig_gear,config=GFX),
                              info=("Data: share of telemetry samples spent in each "
                                    "gear during each driver's best lap across all "
                                    "loaded sessions (stacked to 100%). Why: a "
                                    "fingerprint of how the lap is driven and of "
                                    "gearing/setup choices.")),md=6)]),
        card(ch_title, dcc.Graph(id="laptel-channels-graph",config=GFX),
             info=("Data: raw Speed, Throttle, Brake and Gear telemetry traces for the "
                   "lap(s) you select in the Best Lap Leaderboard, plotted against "
                   "distance from the start line (integrated from speed) so different "
                   "laps and drivers line up corner-for-corner. Dotted grey lines mark "
                   "the numbered corners (from the cached circuit map). Why: a direct "
                   "comparison of driving inputs — where each driver brakes, gets on "
                   "throttle and shifts through each corner.")),
        card(html.Span([
                "Corner Analysis (Braking Point · Entry / Apex / Exit Speed)",
                html.Span(
                    "  ·  per numbered corner  ·  select laps in the Best Lap "
                    "Leaderboard above to compare them",
                    style={"color":TEXT_DIM,"fontWeight":"400","fontSize":"0.72rem","marginLeft":"6px"},
                ),
             ]),
             html.Div([
                 dbc.Row([
                     dbc.Col(dcc.Graph(id="corner-speed-graph", config=GFX), md=6),
                     dbc.Col(dcc.Graph(id="corner-brake-graph", config=GFX), md=6),
                 ]),
                 dash_table.DataTable(
                     id="corner-analysis-table", data=[], columns=[], **TABLE_STYLE,
                 ),
             ]),
             info=("Data: for each lap you select in the Best Lap Leaderboard, the "
                   "lap is split into one zone per numbered corner (from the cached "
                   "circuit map). The apex is the slowest point in each zone; the "
                   "braking point is where the brake first comes on before it; the "
                   "exit speed is where the driver is back on full throttle. One lap "
                   "shows its full entry/apex/exit profile, several laps overlay apex "
                   "speed for comparison. Why: isolates exactly which corners — and "
                   "which phase, braking, apex or exit — a driver gains or loses in.")),
        card(html.Span([
                "Delta Decomposition by Mini-Sector",
                html.Span(
                    "  ·  cumulative time gap vs distance  ·  select 2+ laps in the "
                    "Best Lap Leaderboard above",
                    style={"color":TEXT_DIM,"fontWeight":"400","fontSize":"0.72rem","marginLeft":"6px"},
                ),
             ]),
             html.Div([
                 dcc.Graph(id="delta-trace-graph", config=GFX),
                 dcc.Graph(id="delta-sector-graph", config=GFX),
             ]),
             info=(f"Data: the fastest of the laps you select is the reference (the "
                   "zero line); every other lap is plotted as the running time gap "
                   "to it, against distance from the start line (time integrated from "
                   "the telemetry, lined up corner-for-corner). The lower chart splits "
                   f"that gap into {MINI_SECTORS} equal-distance mini-sectors, each bar "
                   "showing the time gained or lost through that stretch. Dotted grey "
                   "lines mark corners; faint bands mark the mini-sectors. Why: shows "
                   "not just who is faster but exactly where on the lap the time is won "
                   "or lost — a rising line (or a bar above zero) means that lap is "
                   "losing time through that stretch.")),
        card(html.Span([
                "Racing Line",
                html.Span(
                    "  ·  actual driven line (X/Y)  ·  one lap = speed-coloured, "
                    "several = overlaid to compare",
                    style={"color":TEXT_DIM,"fontWeight":"400","fontSize":"0.72rem","marginLeft":"6px"},
                ),
             ]),
             dcc.Graph(id="racing-line-graph", config=GFX),
             info=("Data: the actual X/Y track position of each lap you select in the "
                   "Best Lap Leaderboard, drawn in the circuit's orientation with corner "
                   "numbers. Position comes from the car-position telemetry stream merged "
                   "into the pipeline. Select one lap to see it coloured by speed; select "
                   "several to overlay their lines team-coloured. Why: shows the line each "
                   "driver actually takes — turn-in point, apex, how much track they use "
                   "on exit — which lap-time and speed traces alone can't reveal.")),
        fingerprint_section(blt),
    ])


# ── Telemetry Channels overlay — driven by leaderboard selection ──
@callback(
    Output("laptel-channels-graph", "figure"),
    Input("laptel-best-table", "selected_rows"),
    State("laptel-best-table", "data"),
)
def update_laptel_channels(selected_rows, data):
    if not data or not selected_rows:
        return _empty_channel_fig(
            "Select one or more laps in the Best Lap Leaderboard to view telemetry.")
    specs = []
    for i in selected_rows:
        if i is None or i >= len(data):
            continue
        row = data[i]
        try:
            specs.append((row.get("Session"), row.get("Driver"), int(row.get("Lap #"))))
        except (TypeError, ValueError):
            continue
    if not specs:
        return _empty_channel_fig("Could not resolve the selected lap(s).")
    return _laptel_channel_fig(specs)


# ── Corner Analysis — driven by the same leaderboard selection ──
@callback(
    Output("corner-speed-graph", "figure"),
    Output("corner-brake-graph", "figure"),
    Output("corner-analysis-table", "data"),
    Output("corner-analysis-table", "columns"),
    Input("laptel-best-table", "selected_rows"),
    State("laptel-best-table", "data"),
)
def update_corner_analysis(selected_rows, data):
    if not data or not selected_rows:
        empty = _empty_channel_fig(
            "Select one or more laps in the Best Lap Leaderboard to view corner analysis.")
        return empty, empty, [], []
    specs = []
    for i in selected_rows:
        if i is None or i >= len(data):
            continue
        row = data[i]
        try:
            specs.append((row.get("Session"), row.get("Driver"), int(row.get("Lap #"))))
        except (TypeError, ValueError):
            continue
    if not specs:
        empty = _empty_channel_fig("Could not resolve the selected lap(s).")
        return empty, empty, [], []
    return _corner_analysis(specs)


# ── Delta decomposition — driven by the same leaderboard selection ──
@callback(
    Output("delta-trace-graph", "figure"),
    Output("delta-sector-graph", "figure"),
    Input("laptel-best-table", "selected_rows"),
    State("laptel-best-table", "data"),
)
def update_delta_decomposition(selected_rows, data):
    if not data or not selected_rows:
        empty = _empty_channel_fig(
            "Select two or more laps in the Best Lap Leaderboard to compare deltas.")
        return empty, empty
    specs = []
    for i in selected_rows:
        if i is None or i >= len(data):
            continue
        row = data[i]
        try:
            specs.append((row.get("Session"), row.get("Driver"), int(row.get("Lap #"))))
        except (TypeError, ValueError):
            continue
    if len(specs) < 2:
        empty = _empty_channel_fig(
            "Select at least two laps to compare deltas.")
        return empty, empty
    return _delta_decomposition(specs)


# ── Racing line — driven by the same leaderboard selection ──
@callback(
    Output("racing-line-graph", "figure"),
    Input("laptel-best-table", "selected_rows"),
    State("laptel-best-table", "data"),
)
def update_racing_line(selected_rows, data):
    if not data or not selected_rows:
        return _empty_channel_fig(
            "Select one or more laps in the Best Lap Leaderboard to view the racing line.")
    specs = []
    for i in selected_rows:
        if i is None or i >= len(data):
            continue
        row = data[i]
        try:
            specs.append((row.get("Session"), row.get("Driver"), int(row.get("Lap #"))))
        except (TypeError, ValueError):
            continue
    if not specs:
        return _empty_channel_fig("Could not resolve the selected lap(s).")
    return _racing_line_fig(specs)


# ── Sector heatmap from laps data (current loaded meeting) ────
def _sector_heatmap(laps_df: pd.DataFrame, blt: pd.DataFrame | None = None) -> go.Figure:
    """Mini-sector dominance map: each driver's best lap split into MINI_SECTORS
    equal-distance segments, coloured by % gap to the fastest driver in that
    mini-sector (green = quickest there). Far finer than the three timing
    sectors — it shows exactly which stretches of track each driver owns.

    Pass `blt` (the best-lap telemetry frame) when the caller already built
    it — tab_laps does — so the heavy extraction runs once per render."""
    if telemetry is None or telemetry.empty or laps_df.empty:
        return go.Figure()
    if blt is None:
        blt = _best_lap_telemetry_frame(laps_df)
    if blt.empty or not {"Distance", "t_rel", "Driver_Short"}.issubset(blt.columns):
        return go.Figure()

    n = MINI_SECTORS
    times, teams = {}, {}
    for drv, g in blt.groupby("Driver_Short"):
        g = g.sort_values("Distance")
        dist = pd.to_numeric(g["Distance"], errors="coerce").to_numpy()
        trel = pd.to_numeric(g["t_rel"], errors="coerce").to_numpy()
        ok = np.isfinite(dist) & np.isfinite(trel)
        dist, trel = dist[ok], trel[ok]
        if dist.size < n + 1:
            continue
        keep = np.concatenate([[True], np.diff(dist) > 0])      # strictly increasing
        dist, trel = dist[keep], trel[keep]
        mt = _minisector_times(dist, trel, n)
        if np.all(np.isnan(mt)):
            continue
        times[drv] = mt
        teams[drv] = g["Team"].iloc[0] if "Team" in g.columns else None
    if not times:
        return go.Figure()

    cols = [str(i + 1) for i in range(n)]
    mat = pd.DataFrame(times, index=cols).T                     # drivers × mini-sectors
    mat = mat.reindex(mat.sum(axis=1).sort_values().index)      # fastest lap on top

    gap_pct = mat.copy()
    for col in gap_pct.columns:
        leader = gap_pct[col].min()
        gap_pct[col] = (gap_pct[col] - leader) / leader * 100 if leader and np.isfinite(leader) else np.nan

    # Colour by each mini-sector's OWN range (fastest=0 → slowest=1), so the
    # within-mini-sector ranking is legible everywhere. With a shared scale the
    # mini-sectors with the biggest spread dominate and tightly-matched ones all
    # wash out to the same green.
    znorm = gap_pct.copy()
    for col in znorm.columns:
        cmax = znorm[col].max()
        znorm[col] = znorm[col] / cmax if (cmax and np.isfinite(cmax) and cmax > 0) else 0.0

    text_annot = mat.applymap(lambda v: f"{v:.3f}s" if pd.notna(v) else "—")

    fig = go.Figure(go.Heatmap(
        z=znorm.values, x=cols, y=list(gap_pct.index),
        colorscale=[[0, "#2ECC71"], [0.5, "#F1C40F"], [1, "#E74C3C"]],
        zmin=0, zmax=1,
        text=text_annot.values, customdata=gap_pct.values,
        hovertemplate=("Driver: %{y}<br>Mini-sector: %{x}<br>"
                       "Time: %{text}<br>Gap: +%{customdata:.3f}%<extra></extra>"),
        colorbar=dict(title=dict(text="rank in<br>mini-sector", font=dict(color=TEXT_MAIN)),
                      tickvals=[0, 1], ticktext=["fastest", "slowest"],
                      tickfont=dict(color=TEXT_MAIN)),
    ))
    h = max(300, len(mat) * 26 + 100)
    theme(fig, h, "Mini-Sector Dominance — green = fastest through that stretch")
    fig.update_layout(
        xaxis_title="Mini-sector  (1 = start/finish → lap end)",
        margin=dict(l=80, r=80, t=60, b=40),
        yaxis=dict(autorange="reversed"),
    )
    return fig
