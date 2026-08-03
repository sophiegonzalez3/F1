"""
TELEMETRY tab — track zone dominance map + best-lap leaderboard + telemetry
channel overlay + corner analysis + mini-sector delta decomposition +
racing-line overlay. Adds the driver-style fingerprint section at the bottom.
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
from f1lib.standings import _season_team_tiers
from tabs.fingerprints import fingerprint_section
from tabs.zones import zone_dominance_section

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
    and Team. Used by the Max-Speed / Gear-usage charts and the style
    fingerprints. (The zone dominance card does NOT use this — it measures
    quartile pace over many laps, not a single best lap.)

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


# Preference order for the session whose fastest lap defines the circuit
# geometry. Corner positions are identical across every session of an event —
# we only want the cleanest available lap for the line. The key point is that
# this list reaches PRACTICE sessions: mid-weekend, before Qualifying has run,
# they are the only sessions loaded, and the cards that need the track map
# (cornering-speed, racing line, zone map) must still work. (label, FastF1 id.)
_GEOMETRY_SESSION_PREF: list[tuple[str, str]] = [
    ("Qualifying",        "Q"),
    ("Sprint Qualifying", "SQ"),
    ("Sprint Shootout",   "SQ"),
    ("Race",              "R"),
    ("Sprint",            "Sprint"),
    ("Practice 3",        "FP3"),
    ("Practice 2",        "FP2"),
    ("Practice 1",        "FP1"),
]


def _geometry_session_ids(season, event) -> list[str]:
    """FastF1 session ids to try for this event's circuit geometry, cleanest
    lap first, restricted to sessions actually loaded — so mid-weekend we never
    fire a doomed fetch for a Qualifying that hasn't happened. Falls back to the
    historical ('Q', 'R') when nothing matches the loaded set (e.g. a completed
    event loaded before this info list was populated)."""
    loaded: set[str] = set()
    for info in LOADED_SESSION_INFO:
        try:
            same = (int(info.get("SEASON")) == int(season)
                    and str(info.get("MEETING")) == str(event))
        except (TypeError, ValueError):
            same = False
        if same:
            loaded.add(str(info.get("SESSION")))
    ids: list[str] = []
    for label, sid in _GEOMETRY_SESSION_PREF:
        if label in loaded and sid not in ids:
            ids.append(sid)
    return ids or ["Q", "R"]


def _geometry_track_map(season, event) -> dict | None:
    """Track map (corner geometry + a clean fastest lap) for the event, from the
    best AVAILABLE loaded session. Replaces hardcoded get_track_map(..., "Q")
    calls so the geometry cards light up on practice-only weekends. Returns None
    if no loaded session yields geometry."""
    getter = _get_track_map()
    if getter is None or not season or not event:
        return None
    for sid in _geometry_session_ids(season, event):
        try:
            tm = getter(season, event, sid)
        except Exception:
            tm = None
        if (tm and tm.get("line") is not None and not tm["line"].empty
                and tm.get("corners") is not None and not tm["corners"].empty):
            return tm
    return None


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
    tm = _geometry_track_map(season, event)   # cleanest loaded session, incl. practice
    if tm and tm.get("corners") is not None and not tm["corners"].empty:
        out = _corner_fractions_from_geometry(tm.get("line"), tm["corners"])
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
    ``(fig_speed, fig_brake)``. When a single lap is selected the speed chart
    shows its full entry/apex/exit profile; with several laps it overlays each
    lap's apex speed for a direct comparison.
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
        return _empty_channel_fig(msg), _empty_channel_fig(msg)

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

    return fig_speed, fig_brake


# ── Delta decomposition by track sector ───────────────────────────
# Cumulative time-delta vs distance between selected laps, relative to the
# fastest one, plus a per-timing-sector breakdown of where the time goes.
# Uses _lap_telemetry's integrated Distance + the lap's SectorNTime values;
# no extra data source.
_SECTOR_FILL = ("rgba(255,255,255,0.00)", "rgba(255,255,255,0.035)")


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
    tm = _geometry_track_map(season, event)
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


# ── Best Lap Leaderboard: one lap per driver, paged by championship tier ──
_TIER_PAGES = [("top", "Top teams"), ("mid", "Midfield"), ("back", "Back of the grid")]


def _leaderboard_tier_pages(disp: pd.DataFrame) -> list[tuple[str, list]]:
    """Split the one-lap-per-driver leaderboard into three pages by the loaded
    season's championship tier — the SAME top/mid/back split the sidebar's tier
    buttons use — fastest lap first within each page. Falls back to pace-thirds
    when no standings are available (e.g. pre-season)."""
    tiers = _season_team_tiers()
    if tiers and any(tiers.get(k) for k, _ in _TIER_PAGES):
        pages = []
        for key, label in _TIER_PAGES:
            teams = set(tiers.get(key, []))
            recs = disp[disp["Team"].isin(teams)].to_dict("records")
            pages.append((label, recs))
        return pages
    # no standings → split the pace-sorted field into three near-equal pages
    recs = disp.to_dict("records")
    c = max(1, -(-len(recs) // 3))
    return [("Fastest third", recs[:c]),
            ("Middle third", recs[c:2 * c]),
            ("Slowest third", recs[2 * c:])]


def _tier_caption(idx: int, total: int, label: str, n: int) -> html.Span:
    return html.Span([
        html.Span(f"Page {idx + 1} / {total}", style={
            "color": ACCENT, "fontWeight": "700"}),
        html.Span(f"  ·  {label}  ·  {n} driver{'s' if n != 1 else ''}",
                  style={"color": TEXT_DIM}),
    ], style={"fontSize": "0.78rem"})


def tab_laps(fl, ft):
    # one heavy best-lap telemetry extraction, shared by the zone dominance map,
    # max-speed/gear charts and the style fingerprints
    blt = _best_lap_telemetry_frame(fl)

    bt=best_laps_table(fl)
    # One row per driver: the absolute best valid lap across every loaded session
    # (best_laps_table gives best-per-compound-per-session; collapse to the single
    # fastest per driver).
    bt=bt.loc[bt.groupby("Driver_Short")["LapTime_s"].idxmin()]
    bt["Best Lap"]=bt["LapTime_s"].apply(format_lap_time)
    disp=bt[["session_name","Driver_Short","Team","Compound","Best Lap","LapTime_s","TyreAge","LapNo"]].rename(columns={
        "session_name":"Session","Driver_Short":"Driver","LapTime_s":"Lap Time (s)","TyreAge":"Tyre Age","LapNo":"Lap #"
    }).sort_values("Lap Time (s)").reset_index(drop=True)

    # Split into three pages by championship tier (same top/mid/back definition
    # the sidebar's tier buttons use), fastest first within each page.
    pages=_leaderboard_tier_pages(disp)
    page0=pages[0][1] if pages else []
    # custom pagination is incompatible with native sort/filter (they need the
    # full dataset client-side); drop them for this table — each tier page is
    # already ordered fastest-first.
    _tbl_style={k:v for k,v in TABLE_STYLE.items()
                if k not in ("sort_action","filter_action")}
    best_tbl=dash_table.DataTable(
        id="laptel-best-table",
        data=page0,
        columns=[{"name":c,"id":c} for c in disp.columns],
        row_selectable="multi",
        selected_rows=[0] if page0 else [],
        page_action="custom", page_current=0, page_count=len(pages),
        **_tbl_style,       # provides page_size (20 > any tier, so a tier shows whole)
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
        theme(fig_spd,380)
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
        drv_hex=[TEAM_COLORS.get(drv_team.get(d,"x"),"#808080") for d in drv_ord]
        gears=sorted(gp["GearNo"].dropna().unique())
        # Two channels: hue = team (so drivers stay scannable across the row),
        # opacity = gear. Against the dark card a low alpha blends toward the
        # background, so low gears read dark and the top gears read brightest.
        # Without this every segment of a driver's stack was the same team
        # colour and the breakdown was invisible.
        def _alpha(i):
            return 0.30+0.70*(i/(len(gears)-1)) if len(gears)>1 else 1.0
        for i,gear in enumerate(gears):
            sub=gp[gp["GearNo"]==gear].set_index("Driver_Short")
            a=_alpha(i)
            fig_gear.add_trace(go.Bar(
                x=drv_ord,
                y=[sub.loc[d,"pct"] if d in sub.index else 0 for d in drv_ord],
                name=f"Gear {int(gear)}", showlegend=False,
                marker=dict(color=[_hex_to_rgba(c,a) for c in drv_hex],
                            line=dict(color=CARD_BG,width=0.8)),
                hovertemplate="Driver: %{x}<br>Gear "+str(int(gear))+": %{y:.1f}%<extra></extra>"))
        # The bars are multi-coloured, so their own legend swatch would show one
        # arbitrary team. These empty traces carry a neutral swatch at each
        # gear's opacity instead — the legend then reads as the gear ramp.
        for i,gear in enumerate(gears):
            fig_gear.add_trace(go.Bar(
                x=[None],y=[None],name=f"Gear {int(gear)}",showlegend=True,
                hoverinfo="skip",
                marker=dict(color=_hex_to_rgba("#C8CCD4",_alpha(i)),
                            line=dict(color=CARD_BG,width=0.8))))
        theme(fig_gear,420)
        fig_gear.update_layout(barmode="stack",xaxis_title="Driver",yaxis_title="Time in Gear (%)",
                               bargap=0.25,
                               legend=dict(orientation="h",yanchor="bottom",y=1.0,
                                           xanchor="left",x=0,bgcolor="rgba(0,0,0,0)",
                                           font=dict(size=10)))
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
        zone_dominance_section(fl),
        card("Best Lap Leaderboard",
             measure="one-lap",
             info=("Data: each driver's single fastest valid lap across all loaded "
                   "sessions (one lap per driver). The list is paged by "
                   "championship tier — page 1 the top teams, page 2 the "
                   "midfield, page 3 the back of the grid (the same split as the "
                   "sidebar's tier buttons). Why: the entry point for telemetry "
                   "work — tick laps here to overlay their full telemetry traces "
                   "in the charts below and see where the time difference is made."),
             children=html.Div([
                 dcc.Store(id="laptel-pages",
                           data=[{"label": lbl, "records": recs} for lbl, recs in pages]),
                 html.Div(_tier_caption(0, len(pages), pages[0][0], len(pages[0][1]))
                          if pages else "",
                          id="laptel-tier-label", style={"marginBottom":"6px"}),
                 html.P("One lap per driver. Use the page controls below the table "
                        "to move between tiers; tick laps to drive the Telemetry "
                        "Channels overlay below.",
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
             dbc.Row([
                 dbc.Col(dcc.Graph(id="corner-speed-graph", config=GFX), md=6),
                 dbc.Col(dcc.Graph(id="corner-brake-graph", config=GFX), md=6),
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


# ── Leaderboard pagination — swap the table's rows per championship tier ──
@callback(
    Output("laptel-best-table", "data"),
    Output("laptel-best-table", "selected_rows"),
    Output("laptel-tier-label", "children"),
    Input("laptel-best-table", "page_current"),
    State("laptel-pages", "data"),
    prevent_initial_call=True,
)
def _laptel_paginate(page_current, pages):
    if not pages:
        return [], [], no_update
    i = max(0, min(int(page_current or 0), len(pages) - 1))
    recs = pages[i].get("records", [])
    # Clear the selection on a page change: the previously-selected row indices
    # are meaningless against the new tier's rows, and leaving them set would
    # re-fire the (heavy) telemetry overlays. Paging stays instant; the user
    # ticks a lap on the new page to drive the charts.
    return (recs, [],
            _tier_caption(i, len(pages), pages[i].get("label", ""), len(recs)))


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
    Input("laptel-best-table", "selected_rows"),
    State("laptel-best-table", "data"),
)
def update_corner_analysis(selected_rows, data):
    if not data or not selected_rows:
        empty = _empty_channel_fig(
            "Select one or more laps in the Best Lap Leaderboard to view corner analysis.")
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
    if not specs:
        empty = _empty_channel_fig("Could not resolve the selected lap(s).")
        return empty, empty
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


