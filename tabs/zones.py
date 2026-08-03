"""
Track Zone Dominance — TELEMETRY tab.

Splits the circuit at its REAL marshalling-sector boundaries (the per-track
mini-sectors F1's own timing uses — 21 at Spa, and the count varies by
circuit) and colours each stretch of track by the team whose driver was
fastest through it. Hover or click a zone for the full field ranking.

Pace measure — deliberately NOT a single hot lap. For each driver the card
takes every valid lap from the selected session(s) and compound(s), keeps the
fastest quartile (Q1) of them, and averages the per-zone times across that
quartile. Qualifying and sprint qualifying are excluded outright: this card is
about representative running pace, and absolute one-lap dominance belongs in
the QUALI tab. Taking the fastest 25% does the traffic filtering implicitly —
a lap spent in dirty air does not make a driver's own top quartile.

Per-lap zone times for the whole weekend are computed once and cached (memory
+ data/zone_pace/), so the session/compound dropdowns only re-aggregate.

Replaces the old 20x20 mini-sector heatmap: same underlying idea, but the lap
is drawn as the lap instead of as a grid of unlabelled cells.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, callback, no_update, Input, Output, State, ctx

import f1lib.state as state
from f1lib.components import theme, card, GFX, hex_to_rgba as _hex_to_rgba
from f1lib.config import (
    TEAM_COLORS, ACCENT, CARD_BG, TEXT_MAIN, TEXT_DIM,
)

logger = logging.getLogger(__name__)

ZONE_PACE_DIR = Path("data/zone_pace")

# Fallback when a circuit has no marshal-sector geometry cached.
_FALLBACK_ZONES = 10
_NEUTRAL = "#808080"

# Sessions this card never uses. "Shootout" is the 2023 name for sprint
# qualifying; the sprint RACE is deliberately not matched — it is racing pace.
_QUALI_RE = re.compile(r"qualifying|shootout", re.I)

ALL = "__all__"
_QUARTILE = 0.25

# A lap whose integrated distance is far from the field median has a telemetry
# dropout (missing speed samples mid-lap). Its total time still looks normal —
# the clock is rescaled onto LapTime_s — but every zone boundary lands on the
# wrong piece of track, so the split is meaningless and must be discarded.
# Spa FP2 2026 lap 10 did this to five cars, one of which then "won" a zone.
_DIST_TOL = 0.02

# Zone colour is winner-take-all by nature, but the winning margins are often
# noise: in a race view the median margin is ~0.02 s and 18 of 21 zones are
# decided by under 0.05 s. Painting those in a confident team colour reads as
# dominance that is not there (it made two Ferrari drivers 0.037 s apart over a
# whole lap look decisively different). So the team colour is mixed toward a
# neutral grey as the margin shrinks: a zone won by _DECISIVE_MARGIN or more is
# full strength, a coin-flip is grey.
_DECISIVE_MARGIN = 0.10          # seconds
_NEUTRAL_MIX = "#6E7681"

# In-process memos. Everything heavy (the per-lap table, the split geometry,
# each filter's rankings) is kept server-side and looked up by the small
# dropdown values, so a hover does not make the browser re-upload ~80 KB of
# rankings on every mouse move. All three are keyed by the lap-population
# fingerprint and reset wholesale when it changes (a data reload), so they
# cannot accumulate across events.
_PACE_MEMO: dict[str, pd.DataFrame] = {}
_CTX_MEMO: dict[str, dict] = {}
_RANK_MEMO: dict[tuple, tuple] = {}


# ── zone boundaries ───────────────────────────────────────────
def _zone_boundaries(tm) -> tuple[np.ndarray, list[str], bool]:
    """Fractional positions (0=start line → 1=lap end) where each zone STARTS.

    Returns (fracs, labels, is_real). Zone i runs from fracs[i] to fracs[i+1];
    the last zone wraps across the start/finish line back to fracs[0], exactly
    as a marshalling sector does — so there are as many zones as boundaries.
    `is_real` says whether these are the circuit's marshalling sectors or an
    equal-distance fallback.
    """
    from tabs.telemetry import _corner_fractions_from_geometry

    ms = (tm or {}).get("marshal_sectors")
    line = (tm or {}).get("line")
    if ms is not None and not ms.empty and line is not None and not line.empty:
        fr = _corner_fractions_from_geometry(line, ms)
        if not fr.empty:
            fr = fr.drop_duplicates(subset="frac").sort_values("frac")
            f = fr["frac"].to_numpy(float)
            keep = (f >= 0.0) & (f < 1.0)
            f, lab = f[keep], fr["label"].tolist()
            lab = [l for l, k in zip(lab, keep) if k]
            if f.size >= 3:
                return f, lab, True

    f = np.linspace(0.0, 1.0, _FALLBACK_ZONES + 1)[:-1]
    return f, [str(i + 1) for i in range(len(f))], False


def _zone_times(dist: np.ndarray, trel: np.ndarray, fracs: np.ndarray) -> np.ndarray:
    """Time spent in each zone, for one lap. `dist`/`trel` must be finite and
    strictly increasing in distance; boundaries are taken as fractions of THIS
    lap's own measured length, so laps whose integrated distance differs by a
    few metres still line up zone-for-zone.

    The final zone wraps the start/finish line: it is the run from the last
    boundary to the end of the lap PLUS the run from the line to the first
    boundary. (With an equal-distance fallback fracs[0] is 0, so that second
    piece is empty and the wrap degenerates to a normal zone.)"""
    n = len(fracs)
    total = dist[-1]
    if not np.isfinite(total) or total <= 0:
        return np.full(n, np.nan)
    t_at = np.interp(fracs * total, dist, trel)
    t_end = np.interp(total, dist, trel)
    t_start = np.interp(0.0, dist, trel)

    out = np.empty(n)
    out[:n - 1] = np.diff(t_at)
    out[n - 1] = (t_end - t_at[n - 1]) + (t_at[0] - t_start)
    return out


# ── per-lap zone times for the whole weekend ──────────────────
def pace_laps(laps_df: pd.DataFrame) -> pd.DataFrame:
    """Valid, timed laps from every session EXCEPT qualifying / sprint
    qualifying — the population this card measures pace over."""
    if laps_df is None or laps_df.empty:
        return pd.DataFrame()
    df = laps_df[~laps_df["session_name"].str.contains(_QUALI_RE, na=False)]
    df = df[df["ValidLap"].fillna(False)]
    return df[pd.to_numeric(df["LapTime_s"], errors="coerce") > 0]


def _cache_key(season, event, nz: int, laps_df: pd.DataFrame) -> str:
    """Fingerprint of the exact lap population + zone split, so a re-fetch or a
    different circuit never reads a stale table."""
    t = pd.to_numeric(laps_df["LapTime_s"], errors="coerce")
    raw = "|".join([
        str(season), str(event), str(nz), str(len(laps_df)),
        f"{float(t.sum()):.3f}",
        ",".join(sorted(laps_df["session_name"].unique())),
    ])
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _compute_lap_zone_times(laps_df: pd.DataFrame, fracs: np.ndarray) -> pd.DataFrame:
    """One row per lap: identity columns plus z0..z{n-1} zone times.

    Windows the telemetry per lap (using per-(session, driver) pools so each
    lap slices a few thousand rows rather than the multi-million-row frame),
    integrates distance from speed, then rescales the lap's clock onto its
    official LapTime_s — the telemetry window is truncated at both ends by the
    sample rate, by a different amount per lap, which would otherwise bias
    every cross-driver gap.
    """
    tel = state.telemetry
    if tel is None or tel.empty or laps_df.empty:
        return pd.DataFrame()

    nz = len(fracs)
    src = tel[tel["session_name"].isin(set(laps_df["session_name"]))]
    if src.empty:
        return pd.DataFrame()
    src = src.assign(_dno=src["DriverNo"].astype(str).str.strip())
    pools = {k: g.sort_values("timestamp") for k, g in src.groupby(["session_name", "_dno"])}

    rows, zmat = [], []
    for r in laps_df.itertuples(index=False):
        pool = pools.get((r.session_name, str(r.DriverNo).strip()))
        if pool is None:
            continue
        start = pd.to_numeric(r.LapStartTime, errors="coerce")
        dur = pd.to_numeric(r.LapTime_s, errors="coerce")
        if not (np.isfinite(start) and np.isfinite(dur) and dur > 0):
            continue
        ts = pool["timestamp"].to_numpy()
        i0, i1 = np.searchsorted(ts, start), np.searchsorted(ts, start + dur, side="right")
        if i1 - i0 < nz + 1:
            continue
        w = pool.iloc[i0:i1]
        trel = (w["timestamp"].to_numpy(float) - float(start))
        spd = pd.to_numeric(w["Speed"], errors="coerce").fillna(0).to_numpy(float) * (1000.0 / 3600.0)
        if trel.size < 2:
            continue
        dist = np.concatenate([[0.0], np.cumsum((spd[1:] + spd[:-1]) / 2.0 * np.diff(trel))])

        ok = np.isfinite(dist) & np.isfinite(trel)
        dist, trel = dist[ok], trel[ok]
        if dist.size < nz + 1:
            continue
        keep = np.concatenate([[True], np.diff(dist) > 0])
        dist, trel = dist[keep], trel[keep]
        if dist.size < nz + 1:
            continue

        span = trel[-1] - trel[0]
        trel = (trel - trel[0]) * (float(dur) / span) if span > 0 else trel - trel[0]

        zt = _zone_times(dist, trel, fracs)
        if not np.all(np.isfinite(zt)):
            continue
        rows.append({
            "Driver_Short": r.Driver_Short, "Team": r.Team,
            "session_name": r.session_name, "Compound": getattr(r, "Compound", None),
            "LapNo": r.LapNo, "LapTime_s": float(dur),
            "LapDist_m": float(dist[-1]),
        })
        zmat.append(zt)

    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    zdf = pd.DataFrame(np.vstack(zmat), columns=[f"z{i}" for i in range(nz)])
    out = pd.concat([out.reset_index(drop=True), zdf], axis=1)

    # Drop laps with a telemetry dropout (see _DIST_TOL).
    med = out["LapDist_m"].median()
    if np.isfinite(med) and med > 0:
        good = (out["LapDist_m"] - med).abs() / med <= _DIST_TOL
        if (~good).any():
            logger.info("zone pace: dropped %d/%d laps with corrupt distance "
                        "integration (>%.0f%% off the %.0f m median)",
                        int((~good).sum()), len(out), _DIST_TOL * 100, med)
        out = out[good].reset_index(drop=True)
    return out


def _zone_pace_table(laps_df: pd.DataFrame, fracs: np.ndarray, season, event) -> pd.DataFrame:
    """Per-lap zone times, memoised in process and cached on disk. The heavy
    extraction runs once per weekend; the dropdowns only re-aggregate."""
    key = _cache_key(season, event, len(fracs), laps_df)
    if key in _PACE_MEMO:
        return _PACE_MEMO[key]

    path = ZONE_PACE_DIR / f"{key}.parquet"
    if path.exists():
        try:
            tbl = pd.read_parquet(path)
            _PACE_MEMO[key] = tbl
            return tbl
        except Exception as exc:
            logger.warning("zone-pace cache unreadable (%s); recomputing: %s", path, exc)

    tbl = _compute_lap_zone_times(laps_df, fracs)
    if not tbl.empty:
        try:
            ZONE_PACE_DIR.mkdir(parents=True, exist_ok=True)
            tbl.to_parquet(path, index=False)
        except Exception as exc:
            logger.warning("could not write zone-pace cache %s: %s", path, exc)
    _PACE_MEMO[key] = tbl
    return tbl


# ── server-side context ───────────────────────────────────────
def _track_map_for(season, event):
    from tabs.telemetry import _geometry_track_map
    # Best loaded session (incl. practice), so the zone map works mid-weekend.
    return _geometry_track_map(season, event)


def _allowed(sessions, drivers, teams) -> tuple:
    """The sidebar's global filter as a hashable selection. None/empty means
    'no constraint' — matching how app.render falls back to the full lists."""
    return (frozenset(sessions) if sessions else None,
            frozenset(drivers) if drivers else None,
            frozenset(teams) if teams else None)


def _allowed_from(laps_df: pd.DataFrame) -> tuple:
    """The same selection, recovered from an already-filtered laps frame (what
    tab_laps is handed at render time)."""
    if laps_df is None or laps_df.empty:
        return (None, None, None)
    return (frozenset(laps_df["session_name"].unique()),
            frozenset(laps_df["Driver_Short"].dropna().unique()),
            frozenset(laps_df["Team"].dropna().unique()))


def _current():
    """Everything the card needs for the currently loaded data: split geometry
    plus the per-lap zone-time table. Built from the FULL lap population (not
    the sidebar-filtered one) so the expensive table stays one-per-weekend on
    disk; the global filter is applied later, at aggregation."""
    from tabs.telemetry import _session_meeting_season

    pl = pace_laps(state.laps)
    if pl.empty:
        return None
    season, event = _session_meeting_season(pl["session_name"].iloc[0])
    tm = _track_map_for(season, event)
    if not tm or tm.get("line") is None or tm["line"].empty:
        return None

    fracs, zlabels, is_real = _zone_boundaries(tm)
    key = _cache_key(season, event, len(fracs), pl)
    if key in _CTX_MEMO:
        return _CTX_MEMO[key]

    geom = _zone_geometry(tm, fracs, zlabels)
    if geom is None:
        return None
    tbl = _zone_pace_table(pl, fracs, season, event)
    if tbl.empty:
        return None

    compounds = [c for c in tbl["Compound"].dropna().unique()]
    order = {"SOFT": 0, "MEDIUM": 1, "HARD": 2, "INTERMEDIATE": 3, "WET": 4}
    compounds.sort(key=lambda c: order.get(str(c).upper(), 9))

    ctx = {"key": key, "geom": geom, "tbl": tbl, "is_real": is_real,
           "sessions": sorted(tbl["session_name"].unique()),
           "compounds": compounds}
    _CTX_MEMO.clear()       # only ever the current data generation
    _RANK_MEMO.clear()
    _CTX_MEMO[key] = ctx
    return ctx


def _ranked(ctx, session, compound, allowed=(None, None, None)):
    """(rankings, winners, meta) for one filter, memoised. `allowed` is the
    sidebar's global session/driver/team selection."""
    mk = (ctx["key"], session, compound, allowed)
    if mk not in _RANK_MEMO:
        _RANK_MEMO[mk] = _rankings_for(ctx["tbl"], ctx["geom"]["n_zones"],
                                       session, compound, allowed)
    return _RANK_MEMO[mk]


# ── aggregation ───────────────────────────────────────────────
def _rankings_for(tbl: pd.DataFrame, nz: int, session, compound,
                  allowed=(None, None, None)) -> tuple[list, list, dict]:
    """Rank every driver in every zone, from the fastest quartile of their laps
    under the current filter. Returns (rankings, winners, meta).

    `allowed` applies the sidebar's global session/driver/team selection first,
    so this card narrows with the rest of the dashboard; the card's own
    session/compound dropdowns then narrow further within that."""
    a_sess, a_drv, a_team = allowed
    df = tbl
    if a_sess is not None:
        df = df[df["session_name"].isin(a_sess)]
    if a_drv is not None:
        df = df[df["Driver_Short"].isin(a_drv)]
    if a_team is not None:
        df = df[df["Team"].isin(a_team)]
    if session and session != ALL:
        df = df[df["session_name"] == session]
    if compound and compound != ALL:
        df = df[df["Compound"] == compound]

    zcols = [f"z{i}" for i in range(nz)]
    per_driver = {}
    for drv, g in df.groupby("Driver_Short"):
        n = len(g)
        if n == 0:
            continue
        # Q1 = the fastest quartile of this driver's laps (at least one lap).
        k = max(1, int(np.ceil(n * _QUARTILE)))
        top = g.nsmallest(k, "LapTime_s")
        per_driver[drv] = {
            "team": top["Team"].iloc[0],
            "means": top[zcols].mean().to_numpy(float),
            "n_used": k, "n_total": n,
            "best": float(top["LapTime_s"].min()),
            "avg": float(top["LapTime_s"].mean()),
        }

    rankings, winners = [], []
    for z in range(nz):
        entries = []
        for drv, r in per_driver.items():
            t = r["means"][z]
            if not np.isfinite(t):
                continue
            entries.append({
                "drv": drv, "team": r["team"], "t": float(t),
                "n_used": r["n_used"], "n_total": r["n_total"],
                "avg": r["avg"],
                "color": TEAM_COLORS.get(r["team"], _NEUTRAL),
            })
        entries.sort(key=lambda e: e["t"])
        for i, e in enumerate(entries):
            e["gap"] = e["t"] - entries[0]["t"]
            e["pos"] = i + 1
        rankings.append(entries)
        winners.append(entries[0] if entries else None)

    meta = {"n_drivers": len(per_driver), "n_laps": int(len(df)),
            "n_used": int(sum(r["n_used"] for r in per_driver.values()))}
    return rankings, winners, meta


# ── figure ────────────────────────────────────────────────────
def _mix(hex_a: str, hex_b: str, w: float) -> str:
    """Blend two '#RRGGBB' colours; w=1 keeps hex_a, w=0 gives hex_b."""
    def _rgb(h):
        h = h.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)) if len(h) == 6 else (128, 128, 128)
    a, b = _rgb(hex_a), _rgb(hex_b)
    return "#%02X%02X%02X" % tuple(int(round(a[i] * w + b[i] * (1 - w))) for i in range(3))


def _margin_color(hex_color: str, margin) -> str:
    """Team colour faded toward neutral as the winning margin shrinks (see
    _DECISIVE_MARGIN). sqrt so mid-sized margins still show real colour rather
    than collapsing everything below the threshold into grey."""
    if margin is None or not np.isfinite(margin):
        return _NEUTRAL_MIX
    f = min(max(float(margin) / _DECISIVE_MARGIN, 0.0), 1.0)
    return _mix(hex_color, _NEUTRAL_MIX, f ** 0.5)


def _winners_margins(rankings: list) -> tuple[list, list]:
    """Per zone: the fastest entry, and how much faster it was than second."""
    winners, margins = [], []
    for r in rankings:
        winners.append(r[0] if r else None)
        margins.append(r[1]["gap"] if len(r) > 1 else None)
    return winners, margins


def _zone_map_fig(geom: dict, rankings: list, selected: int | None = None) -> go.Figure:
    """The circuit, each zone drawn in the winning team's colour, its intensity
    scaled by how decisively that zone was won. The selected zone is drawn
    thicker and fully opaque; the rest dim back so the highlight reads."""
    fig = go.Figure()
    winners, margins = _winners_margins(rankings)

    for seg in geom["segments"]:
        z = seg["z"]
        w = winners[z] if z < len(winners) else None
        mg = margins[z] if z < len(margins) else None
        clr = _margin_color(w["color"], mg) if w else _NEUTRAL
        is_sel = (selected is not None and z == selected)
        dim = (selected is not None and not is_sel)
        who = (f"{w['drv']} · {w['team']}<br>margin: "
               + (f"{mg:.3f} s over {rankings[z][1]['drv']}" if mg is not None
                  else "only car with data")) if w else "no data"
        # plain SVG Scatter, not Scattergl: the track polyline is ~1k points, so
        # WebGL buys nothing and costs crispness (and breaks the None gap break
        # the wrapping zone needs)
        fig.add_trace(go.Scatter(
            x=seg["x"], y=seg["y"], mode="lines",
            name=f"Zone {seg['label']}", showlegend=False,
            customdata=[z] * len(seg["x"]),
            # simplify=False: Plotly's default point-decimation straightens
            # the polyline and visibly cuts the corners off a track map
            line=dict(color=_hex_to_rgba(clr, 0.28) if dim else clr,
                      width=11 if is_sel else 7,
                      shape="spline", smoothing=0.4, simplify=False),
            hovertemplate=(f"<b>Zone {seg['label']}</b><br>fastest: {who}"
                           f"<br>{seg['length_m']:,.0f} m long"
                           "<extra></extra>"),
            # note: `who` already carries the margin, which is what the colour
            # intensity encodes — hovering explains the shade
        ))

    if geom["corners"]:
        fig.add_trace(go.Scatter(
            x=[c["x"] for c in geom["corners"]],
            y=[c["y"] for c in geom["corners"]],
            mode="text", text=[c["label"] for c in geom["corners"]],
            showlegend=False, hoverinfo="skip",
            textfont=dict(size=9, color=TEXT_DIM)))

    theme(fig, 560)
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False,
        xaxis=dict(visible=False, showgrid=False, zeroline=False,
                   scaleanchor="y", scaleratio=1),
        yaxis=dict(visible=False, showgrid=False, zeroline=False),
        hovermode="closest",
    )
    return fig


# ── ranking panel ─────────────────────────────────────────────
def _rank_row(e: dict) -> html.Div:
    return html.Div([
        html.Div(style={"width": "4px", "alignSelf": "stretch",
                        "backgroundColor": e["color"], "borderRadius": "2px",
                        "marginRight": "12px", "flexShrink": "0"}),
        html.Div(str(e["pos"]), style={
            "color": TEXT_DIM, "fontSize": "0.8rem", "width": "22px",
            "flexShrink": "0", "textAlign": "right", "marginRight": "12px"}),
        html.Div([
            html.Div(e["drv"], style={"color": TEXT_MAIN, "fontWeight": "700",
                                      "fontSize": "0.95rem", "lineHeight": "1.25"}),
            html.Div(f"{e['team']} · Q1 of {e['n_used']}/{e['n_total']} laps",
                     style={"color": TEXT_DIM, "fontSize": "0.72rem"}),
        ], style={"flex": "1", "minWidth": "0"}),
        html.Div([
            html.Div(f"{e['t']:.3f} s", style={
                "color": TEXT_MAIN, "fontWeight": "700", "fontSize": "0.9rem"}),
            html.Div("—" if e["pos"] == 1 else f"+{e['gap']:.3f}", style={
                "color": TEXT_DIM if e["pos"] == 1 else "#E8635A",
                "fontSize": "0.72rem"}),
        ], style={"textAlign": "right", "flexShrink": "0", "marginLeft": "10px"}),
    ], style={"display": "flex", "alignItems": "center", "padding": "7px 10px",
              "borderBottom": "1px solid rgba(255,255,255,0.05)"})


def _margin_note(entries: list) -> html.Div:
    """States how decisively the zone was won — the quantity the map's colour
    intensity encodes, so the two readings agree."""
    if len(entries) < 2:
        return html.Div()
    m = entries[1]["gap"]
    decisive = m >= _DECISIVE_MARGIN
    if decisive:
        txt, clr = f"won by {m:.3f} s — a clear margin", "#5BC98C"
    elif m >= _DECISIVE_MARGIN / 4:
        txt, clr = f"won by only {m:.3f} s", TEXT_DIM
    else:
        txt, clr = f"won by {m:.3f} s — too close to call", "#E8A33D"
    return html.Div(txt, style={"color": clr, "fontSize": "0.76rem",
                                "marginTop": "4px"})


def _rank_panel(geom: dict, rankings: list, z: int, pinned: bool) -> html.Div:
    entries = rankings[z] if 0 <= z < len(rankings) else []
    seg = next((s for s in geom["segments"] if s["z"] == z), None)
    if seg is not None:
        span = (f"{seg['start_m']:,.0f} m – {seg['end_m']:,.0f} m"
                f" · {seg['length_m']:,.0f} m long")
        if seg.get("wraps"):
            span += "  · crosses the start/finish line"
        label = seg["label"]
    else:
        span, label = "", str(z + 1)

    head = html.Div([
        html.Div([
            html.Span(f"Zone {label}", style={
                "color": TEXT_MAIN, "fontSize": "1.35rem", "fontWeight": "700"}),
            html.Span("PINNED" if pinned else "HOVER", style={
                "color": ACCENT if pinned else TEXT_DIM,
                "border": f"1px solid {ACCENT if pinned else TEXT_DIM}",
                "borderRadius": "3px", "padding": "1px 6px", "marginLeft": "10px",
                "fontSize": "0.6rem", "letterSpacing": "1px",
                "verticalAlign": "middle"}),
        ]),
        html.Div(span, style={"color": TEXT_DIM, "fontSize": "0.8rem",
                              "marginTop": "2px"}),
        _margin_note(entries),
    ], style={"marginBottom": "10px"})

    if not entries:
        return html.Div([head, html.P("No laps match this session / compound.",
                                      style={"color": TEXT_DIM})])

    return html.Div([
        head,
        html.Div([_rank_row(e) for e in entries],
                 style={"maxHeight": "430px", "overflowY": "auto",
                        "border": "1px solid rgba(255,255,255,0.07)",
                        "borderRadius": "6px"}),
    ])


# ── geometry ──────────────────────────────────────────────────
def _zone_geometry(tm, fracs, zlabels) -> dict | None:
    """Track polyline split into the zones, plus corner labels — everything the
    figure needs that does not depend on the pace filter."""
    from tabs.telemetry import _rotate

    line = tm["line"]
    lx, ly = _rotate(line["X"].to_numpy(float), line["Y"].to_numpy(float),
                     float(tm.get("rotation", 0.0)) / 180.0 * np.pi)
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(lx), np.diff(ly)))])
    if cum[-1] <= 0:
        return None
    lap_len = float(cum[-1])
    cum = cum / cum[-1]
    nz = len(fracs)

    def _polyline(lo, hi):
        """Track points between two fractions, extended one point either side
        so consecutive zones visually join up rather than leaving gaps."""
        idx = np.flatnonzero((cum >= lo) & (cum <= hi))
        if idx.size < 2:
            return [], []
        i0 = max(idx[0] - 1, 0)
        i1 = min(idx[-1] + 1, len(lx) - 1)
        return lx[i0:i1 + 1].tolist(), ly[i0:i1 + 1].tolist()

    segments = []
    for z in range(nz):
        lo = fracs[z]
        if z < nz - 1:
            hi = fracs[z + 1]
            xs, ys = _polyline(lo, hi)
        else:
            # wraps the start/finish line — two disjoint pieces of track, drawn
            # as one trace with a None break between them
            xs, ys = _polyline(lo, 1.0)
            if fracs[0] > 1e-6:
                x2, y2 = _polyline(0.0, fracs[0])
                if x2:
                    xs, ys = xs + [None] + x2, ys + [None] + y2
            hi = 1.0 + fracs[0]
        if not xs:
            continue
        segments.append({
            "z": z, "x": xs, "y": ys,
            "label": zlabels[z] if z < len(zlabels) else str(z + 1),
            "start_m": lo * lap_len, "end_m": hi * lap_len,
            "length_m": (hi - lo) * lap_len,
            "wraps": z == nz - 1 and fracs[0] > 1e-6,
        })

    corners = []
    cdf = tm.get("corners")
    if cdf is not None and not cdf.empty and {"X", "Y"}.issubset(cdf.columns):
        cx, cy = _rotate(cdf["X"].to_numpy(float), cdf["Y"].to_numpy(float),
                         float(tm.get("rotation", 0.0)) / 180.0 * np.pi)
        for (_, cc), x, y in zip(cdf.iterrows(), cx, cy):
            num, letter = cc.get("Number"), cc.get("Letter")
            letter = "" if letter is None or (isinstance(letter, float) and pd.isna(letter)) else str(letter).strip()
            try:
                lbl = f"T{int(num)}{letter}"
            except (TypeError, ValueError):
                lbl = f"T{num}{letter}"
            corners.append({"x": float(x), "y": float(y), "label": lbl})

    return {"n_zones": nz, "segments": segments, "corners": corners,
            "lap_len": lap_len}


# ── section ───────────────────────────────────────────────────
def _session_label(s: str) -> str:
    """'Practice 2_Belgian Grand Prix_2026' → 'Practice 2'."""
    return str(s).split("_")[0]


def _context_line(session, compound, meta, geom) -> html.Div:
    # "selected" because the sidebar's global filter has already narrowed this
    sess = "all selected sessions" if session == ALL else _session_label(session)
    comp = "all compounds" if compound == ALL else str(compound).title()
    return html.Div(
        f"{sess} · {comp} · {meta['n_drivers']} drivers · "
        f"fastest {meta['n_used']} of {meta['n_laps']} valid laps",
        style={"color": TEXT_DIM, "fontSize": "0.78rem", "marginTop": "6px"})


def zone_dominance_section(laps_df: pd.DataFrame) -> html.Div:
    """Track Zone Dominance card for the TELEMETRY tab."""
    if pace_laps(laps_df).empty:
        return card("Track Zone Dominance",
                    html.P("No valid race or practice laps loaded — this card "
                           "excludes qualifying and sprint qualifying by design.",
                           style={"color": TEXT_DIM}),
                               measure="race",
                           )

    ctx = _current()
    if ctx is None:
        return card("Track Zone Dominance",
                    html.P("No circuit geometry or position telemetry available "
                           "for the loaded laps.", style={"color": TEXT_DIM}),
                               measure="race",
                           )

    geom, is_real = ctx["geom"], ctx["is_real"]
    # tab_laps hands us the sidebar-filtered frame; the dropdowns must offer
    # only what survives that filter, or they would promise empty views.
    allowed = _allowed_from(pace_laps(laps_df))
    a_sess, a_drv, a_team = allowed
    sub = ctx["tbl"]
    if a_sess is not None:
        sub = sub[sub["session_name"].isin(a_sess)]
    if a_drv is not None:
        sub = sub[sub["Driver_Short"].isin(a_drv)]
    if a_team is not None:
        sub = sub[sub["Team"].isin(a_team)]
    sessions = [s for s in ctx["sessions"] if s in set(sub["session_name"])]
    compounds = [c for c in ctx["compounds"] if c in set(sub["Compound"].dropna())]

    rankings, winners, meta = _ranked(ctx, ALL, ALL, allowed)

    dd = {"width": "190px", "backgroundColor": "#111", "fontSize": "0.82rem"}
    controls = html.Div([
        html.Span("SESSION", style={"color": TEXT_DIM, "fontSize": "0.7rem",
                                    "letterSpacing": "1px", "marginRight": "8px"}),
        dcc.Dropdown(id="zone-session", clearable=False, style=dd, value=ALL,
                     options=[{"label": "All sessions", "value": ALL}]
                             + [{"label": _session_label(s), "value": s} for s in sessions]),
        html.Span("COMPOUND", style={"color": TEXT_DIM, "fontSize": "0.7rem",
                                     "letterSpacing": "1px", "margin": "0 8px 0 16px"}),
        dcc.Dropdown(id="zone-compound", clearable=False, style=dd, value=ALL,
                     options=[{"label": "All compounds", "value": ALL}]
                             + [{"label": str(c).title(), "value": c} for c in compounds]),
    ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap",
              "gap": "6px", "marginBottom": "4px"})

    origin = ("the circuit's real marshalling sectors — the same per-track "
              "mini-sectors F1's own timing uses"
              if is_real else
              f"{geom['n_zones']} equal-distance sections (no marshalling-sector "
              "geometry cached for this circuit)")

    blurb = html.Div([
        html.P([
            "The track is split into ", html.B(f"{geom['n_zones']} zones"), " — ", origin,
            " — each coloured by the team whose driver was fastest through it. "
            "Each driver's zone times are the average of their ",
            html.B("fastest quartile of laps"),
            " (qualifying and sprint qualifying excluded).",
        ], style={"color": TEXT_MAIN, "fontSize": "0.86rem", "marginBottom": "2px"}),
        html.P([
            "Colour ", html.B("intensity shows the winning margin"),
            f" — full strength at {_DECISIVE_MARGIN:.2f} s or more, fading to "
            "grey where the zone was a coin-flip. Hover a zone for the full "
            "ranking; click to pin it, click again to unpin.",
        ], style={"color": TEXT_DIM, "fontSize": "0.8rem", "marginBottom": "0"}),
    ], style={"marginBottom": "10px"})

    return html.Div([
        dcc.Store(id="zone-pinned", data=None),
        card(
            "Track Zone Dominance",
            html.Div([
                blurb, controls,
                html.Div(_context_line(ALL, ALL, meta, geom), id="zone-context"),
                html.Div([
                    html.Div(dcc.Graph(id="zone-map",
                                       figure=_zone_map_fig(geom, rankings),
                                       config=GFX),
                             style={"flex": "1 1 58%", "minWidth": "320px"}),
                    html.Div(_rank_panel(geom, rankings, 0, False), id="zone-panel",
                             style={"flex": "1 1 38%", "minWidth": "300px",
                                    "backgroundColor": CARD_BG,
                                    "borderRadius": "8px", "padding": "14px 12px"}),
                ], style={"display": "flex", "gap": "16px", "flexWrap": "wrap",
                          "alignItems": "flex-start", "marginTop": "8px"}),
            ]),
            info=("Data: every valid lap from the selected session(s) and "
                  "compound(s) — qualifying and sprint qualifying are excluded, "
                  "because this card measures representative running pace, not "
                  "one-lap dominance. For each driver the fastest quartile (Q1) "
                  "of those laps is kept and their per-zone times averaged, so "
                  "the figure is a repeatable pace rather than a single hot lap; "
                  "taking only the top 25% also drops laps spent in traffic. "
                  "The lap is split at the circuit's marshalling-sector "
                  "boundaries (the real per-circuit mini-sectors, fetched with "
                  "the track map) and each zone is coloured by the winner's "
                  "team. Why: shows which stretches of track each car genuinely "
                  "owns over a run — a slow-corner sector won by one team and a "
                  "straight won by another is a car-balance story lap time "
                  "hides. Absolute one-lap dominance lives in the QUALI tab."),
            measure="race",
        ),
    ])


# ── callbacks ─────────────────────────────────────────────────
def _zone_of(payload):
    try:
        return int(payload["points"][0]["customdata"])
    except (TypeError, KeyError, IndexError, ValueError):
        return None


@callback(Output("zone-map", "figure", allow_duplicate=True),
          Output("zone-panel", "children", allow_duplicate=True),
          Output("zone-context", "children"),
          Output("zone-pinned", "data", allow_duplicate=True),
          Input("zone-session", "value"),
          Input("zone-compound", "value"),
          State("session-filter", "value"),
          State("driver-filter", "value"),
          State("team-filter", "value"),
          prevent_initial_call=True)
def _update_filter(session, compound, ss, sd, st):
    """Re-aggregate on a session/compound change. Everything heavy is memoised
    server-side, so this only re-ranks and redraws."""
    c = _current()
    if c is None:
        return (no_update,) * 4
    geom = c["geom"]
    rankings, winners, meta = _ranked(c, session, compound, _allowed(ss, sd, st))
    # a filter change invalidates any pinned zone's contents, so reset to hover
    return (_zone_map_fig(geom, rankings),
            _rank_panel(geom, rankings, 0, False),
            _context_line(session, compound, meta, geom), None)


@callback(Output("zone-panel", "children"),
          Output("zone-map", "figure"),
          Output("zone-pinned", "data"),
          Input("zone-map", "hoverData"),
          Input("zone-map", "clickData"),
          State("zone-pinned", "data"),
          State("zone-session", "value"),
          State("zone-compound", "value"),
          State("session-filter", "value"),
          State("driver-filter", "value"),
          State("team-filter", "value"),
          prevent_initial_call=True)
def _update_zone(hover, click, pinned, session, compound, ss, sd, st):
    c = _current()
    if c is None:
        return no_update, no_update, no_update
    geom = c["geom"]
    rankings, winners, _meta = _ranked(c, session, compound, _allowed(ss, sd, st))

    src = ctx.triggered_id and ctx.triggered[0]["prop_id"].split(".")[-1]

    if src == "clickData":
        z = _zone_of(click)
        if z is None:
            return no_update, no_update, no_update
        # clicking the pinned zone unpins; clicking another moves the pin
        new_pin = None if pinned == z else z
        sel = new_pin if new_pin is not None else z
        return (_rank_panel(geom, rankings, sel, new_pin is not None),
                _zone_map_fig(geom, rankings, sel), new_pin)

    # hover — ignored entirely while a zone is pinned
    if pinned is not None:
        return no_update, no_update, no_update
    z = _zone_of(hover)
    if z is None:
        return no_update, no_update, no_update
    return (_rank_panel(geom, rankings, z, False),
            _zone_map_fig(geom, rankings, z), None)
