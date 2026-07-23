"""
RACE tab — the meeting's Race session, with race trace / position chart /
tyre strategy / undercut duels / strategy simulator (SC + traffic aware) /
wet-race crossover / weather / lap-1 & restarts / pit-stop performance /
race-control timeline / transcribed team radio (with lap-mapped ★ markers).
Extracted from app.py.
"""
from __future__ import annotations

import logging
import re
from itertools import product

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import (
    html, dcc, callback, no_update,
    Input, Output, State,
)
import dash_bootstrap_components as dbc

import f1lib.state as state
from f1lib.components import (
    theme, card, kpi, GFX, TABLE_STYLE, styled_table, tip,
    badge as _badge, abbr as _abbr, hex_to_rgba as _hex_to_rgba,
)
from f1lib.glossary import gloss
from f1lib.config import (
    TEAM_COLORS, COMPOUND_COLORS,
    CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
)
from f1lib.processing import (
    clean_and_enrich_laps, enrich_weather, enrich_track_limits,
    enrich_blue_flags, identify_quali_sim_laps, flag_perturbed_laps,
    flag_dirty_air, enrich_track_evolution, enrich_session_results,
    flag_position_changes,
    analyze_stints, enrich_telemetry,
    field_deg_curves, compound_offsets, format_lap_time,
    detect_wet_crossover, dirty_air_penalty, traffic_exposure_curve,
    clipped_range,
)
from f1lib.figures import _add_flag_bands, _rain_lap_groups, _add_rain_bands, _lap_evolution_fig
from f1lib.tyre_allocations import _allocation_chips, _laps_event
from f1lib.data_loader import load_session, load_sessions, is_cached
from f1lib.radio_loader import load_race_radio, race_radio_available, radio_cached
from tabs.replay import replay_card
from tabs.race3d import race3d_card
from f1lib.pitstops_loader import load_pitstops
from f1lib.standings import _order_by_champ, _order_teams_by_champ

# mirror data state (LOADED_SESSION_INFO etc.)
state.register(globals())

# The Race tab is meeting-centric and self-contained: it loads the *race*
# session for the currently-selected meeting, falling back to the previous
# season's race when the current season's race hasn't happened / isn't
# available yet. It does NOT use the sidebar session/driver filters because
# the race shown may be a different season (different driver line-up) than
# what is otherwise loaded.

_RACE_DATA_CACHE: dict[tuple, dict | None] = {}   # (season, meeting) → enriched data | None


def _enrich_race_laps(data: dict) -> pd.DataFrame:
    """Run the same lap-enrichment pipeline as rebuild_state() on a single
    race session's raw frames. Returns the enriched laps frame."""
    _laps = clean_and_enrich_laps(data["laps"])
    _laps["stint_key"] = (
        _laps["Stint"].astype("string") + "_" + _laps["session_name"]
    )
    _laps = enrich_weather(_laps, data["weather"])
    _laps = enrich_track_limits(_laps, data["race_control"])
    _laps = enrich_blue_flags(_laps, data["race_control"])
    _laps = identify_quali_sim_laps(_laps)
    _laps = flag_perturbed_laps(_laps, rcm=data["race_control"])
    _laps = flag_dirty_air(_laps)
    _laps = enrich_track_evolution(_laps)
    _laps = enrich_session_results(_laps, data["results"])
    _laps = flag_position_changes(_laps)
    return _laps


def _load_one_race(season: int, meeting: str) -> dict | None:
    """Load + enrich the Race session for (season, meeting). Returns
    {laps, stints, season, meeting} or None when no lap data is available."""
    info = [{"SEASON": str(season), "MEETING": meeting, "SESSION": "Race"}]
    try:
        data = load_sessions(info)
    except Exception as exc:           # network / FastF1 failure
        print(f"  [race] load failed {season} {meeting}: {exc}", flush=True)
        return None
    lr = data.get("laps")
    if lr is None or lr.empty:
        return None
    try:
        rl = _enrich_race_laps(data)
        rs = analyze_stints(rl)
    except Exception as exc:
        print(f"  [race] enrich failed {season} {meeting}: {exc}", flush=True)
        return None
    return {"laps": rl, "stints": rs, "season": season, "meeting": meeting,
            "race_control": data.get("race_control", pd.DataFrame())}


def _resolve_race_data(season: int, meeting: str) -> dict | None:
    """Get race data for the meeting, preferring the current season and falling
    back to the previous one. Cached data is preferred over a live fetch so the
    tab stays fast and works offline. Memoized per (season, meeting)."""
    key = (int(season), meeting)
    if key in _RACE_DATA_CACHE:
        return _RACE_DATA_CACHE[key]

    candidates = [int(season), int(season) - 1]
    result: dict | None = None
    # Pass 1 – cached years only (fast, offline-safe), current season first
    for yr in candidates:
        if is_cached(str(yr), meeting, "Race"):
            result = _load_one_race(yr, meeting)
            if result:
                break
    # Pass 2 – nothing cached: attempt a live fetch, current season first
    if result is None:
        for yr in candidates:
            result = _load_one_race(yr, meeting)
            if result:
                break

    _RACE_DATA_CACHE[key] = result
    return result


def _position_changes_fig(rl: pd.DataFrame, title: str, height: int = 640) -> go.Figure:
    """Broadcast-style race position chart: each driver's on-track position by
    lap, team-coloured (teammates solid vs dashed), driver code labelled at the
    end of the line, grid position shown at lap 0, points-paying top-10 zone
    shaded, and track-flag periods banded behind. Y-axis inverted (P1 on top)."""
    fig = go.Figure()
    if rl.empty or "Position" not in rl.columns or rl["Position"].notna().sum() == 0:
        theme(fig, height, title)
        fig.add_annotation(
            text="No per-lap position data available for this race.",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(color=TEXT_DIM, size=13),
        )
        return fig

    n_laps    = int(rl["LapNo"].max())
    n_drivers = int(rl["Driver_Short"].nunique())
    y_bottom  = max(20, n_drivers) + 0.5

    # Points-paying zone (top 10)
    fig.add_hrect(y0=0.5, y1=10.5, fillcolor="rgba(0,210,190,0.05)",
                  line_width=0, layer="below")

    end_labels: list[tuple] = []   # (x, y, code, color)
    for team in sorted(rl["Team"].dropna().unique()):
        drv_team = (
            rl[rl["Team"] == team]
            .sort_values("DriverNo")["Driver_Short"].dropna().unique().tolist()
        )
        clr = TEAM_COLORS.get(team, "#808080")
        for i, drv in enumerate(drv_team):
            dv = rl[(rl["Driver_Short"] == drv) & rl["Position"].notna()] \
                .sort_values("LapNo")
            if dv.empty:
                continue
            dash = "solid" if i == 0 else "dash"
            x = dv["LapNo"].tolist()
            y = dv["Position"].tolist()
            # Prepend starting grid slot at lap 0 so the start is visible
            grid = dv["Grid_Position"].iloc[0] if "Grid_Position" in dv.columns else np.nan
            if pd.notna(grid) and grid > 0:
                x = [0] + x
                y = [float(grid)] + y
            fig.add_trace(go.Scatter(
                x=x, y=y, mode="lines", name=drv,
                line=dict(color=clr, width=2.2, dash=dash),
                hovertemplate=(
                    f"<b>{drv}</b> · {team}<br>"
                    "Lap %{x}  →  P%{y}<extra></extra>"
                ),
                showlegend=False,
            ))
            end_labels.append((x[-1], y[-1], drv, clr))

    # Track-flag bands (SC / VSC / yellow / red) behind the lines
    _add_flag_bands(fig, rl)
    _add_rain_bands(fig, rl)

    theme(fig, height, title)

    # Driver-code labels at the end of each line (replaces a crowded legend)
    for xe, ye, drv, clr in end_labels:
        fig.add_annotation(
            x=xe, y=ye, text=f"  {drv}", showarrow=False, xanchor="left",
            font=dict(size=10, color=clr, family="Inter, sans-serif"),
        )
    fig.add_annotation(
        x=0.0, y=10.5, xref="x", yref="y", text="points ▲", showarrow=False,
        xanchor="left", yanchor="bottom",
        font=dict(size=9, color="#00D2BE"),
    )

    fig.update_layout(
        showlegend=False,
        xaxis=dict(title="Lap", range=[-1.5, n_laps + 3.5],
                   gridcolor=GRID_CLR, zeroline=False),
        yaxis=dict(title="Position", range=[y_bottom, 0.5],
                   tickvals=[1, 5, 10, 15, 20],
                   gridcolor=GRID_CLR, zeroline=False),
    )
    return fig


def _race_trace_fig(rl: pd.DataFrame, title: str, height: int = 640) -> go.Figure:
    """Strategist-style race trace: cumulative race time vs a constant
    reference pace (the winner's average lap), one line per driver.

    y(lap) = ref_pace × lap − elapsed_race_time(driver, lap)
    Higher = ahead of the reference schedule. Undercuts, deg cliffs, pit-stop
    losses and Safety-Car compression all read directly off the slopes: a
    driver's line rising = lapping faster than the reference, falling =
    slower; a vertical drop ≈ a pit stop.

    Uses per-lap LapStartTime + LapTime_s for the elapsed-time stamp (immune
    to isolated missing laps, unlike a cumulative sum of lap times).
    """
    fig = go.Figure()
    need = {"LapNo", "LapStartTime", "LapTime_s"}
    if rl.empty or not need.issubset(rl.columns):
        theme(fig, height, title)
        fig.add_annotation(
            text="No lap-timing data available for a race trace.",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(color=TEXT_DIM, size=13),
        )
        return fig

    df = rl.copy()
    df["_t_end"] = (
        pd.to_numeric(df["LapStartTime"], errors="coerce")
        + pd.to_numeric(df["LapTime_s"], errors="coerce")
    )
    df = df[df["_t_end"].notna() & df["LapNo"].notna()]
    if df.empty:
        theme(fig, height, title)
        fig.add_annotation(
            text="No usable lap timestamps for a race trace.",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(color=TEXT_DIM, size=13),
        )
        return fig

    # Race clock zero = earliest lap-1 start (≈ lights out)
    _lap1 = pd.to_numeric(
        df.loc[df["LapNo"] == df["LapNo"].min(), "LapStartTime"], errors="coerce"
    )
    t0 = _lap1.min()
    if not np.isfinite(t0):
        t0 = float(df["_t_end"].min())
    df["_race_t"] = df["_t_end"] - t0

    # Reference pace: winner's average lap (Classified_Position 1 when known,
    # else whoever completes the most laps in the least time)
    win_drv = None
    if "Classified_Position" in df.columns:
        _w = df[pd.to_numeric(df["Classified_Position"], errors="coerce") == 1]
        if not _w.empty:
            win_drv = _w["Driver_Short"].iloc[0]
    if win_drv is None:
        _last = df[df["LapNo"] == df["LapNo"].max()]
        if _last.empty:
            _last = df
        win_drv = _last.sort_values("_race_t")["Driver_Short"].iloc[0]
    win = df[df["Driver_Short"] == win_drv]
    ref_pace = float(win["_race_t"].max()) / float(win["LapNo"].max())

    # Leader elapsed time per lap → gap-to-leader in the hover
    lead_t = df.groupby("LapNo")["_race_t"].min()

    end_labels: list[tuple] = []
    for team in sorted(df["Team"].dropna().unique()):
        drv_team = (
            df[df["Team"] == team]
            .sort_values("DriverNo")["Driver_Short"].dropna().unique().tolist()
        )
        clr = TEAM_COLORS.get(team, "#808080")
        for i, drv in enumerate(drv_team):
            dv = df[df["Driver_Short"] == drv].sort_values("LapNo")
            if dv.empty:
                continue
            y = ref_pace * dv["LapNo"] - dv["_race_t"]
            gap_lead = dv["_race_t"] - dv["LapNo"].map(lead_t)
            fig.add_trace(go.Scatter(
                x=dv["LapNo"], y=y, mode="lines", name=drv,
                line=dict(color=clr, width=2.0,
                          dash="solid" if i == 0 else "dash"),
                customdata=np.column_stack([gap_lead]),
                hovertemplate=(
                    f"<b>{drv}</b> · {team}<br>"
                    "Lap %{x}<br>"
                    "vs reference: %{y:+.1f} s<br>"
                    "Gap to leader: +%{customdata[0]:.1f} s<extra></extra>"
                ),
                showlegend=False,
            ))
            end_labels.append((dv["LapNo"].iloc[-1], float(y.iloc[-1]), drv, clr))

    _add_flag_bands(fig, rl)
    _add_rain_bands(fig, rl)
    theme(fig, height, title)

    for xe, ye, drv, clr in end_labels:
        fig.add_annotation(
            x=xe, y=ye, text=f"  {drv}", showarrow=False, xanchor="left",
            font=dict(size=10, color=clr, family="Inter, sans-serif"),
        )

    n_laps = int(df["LapNo"].max())
    fig.update_layout(
        showlegend=False,
        xaxis=dict(title="Lap", range=[-1, n_laps + 3.5],
                   gridcolor=GRID_CLR, zeroline=False),
        yaxis=dict(
            title=f"Time vs reference (s) · ref = {win_drv} avg pace "
                  f"({format_lap_time(ref_pace)})",
            gridcolor=GRID_CLR, zeroline=False,
        ),
    )
    return fig


def _undercut_pairs(rl: pd.DataFrame, max_stop_gap: int = 5,
                    max_track_gap_s: float = 15.0) -> pd.DataFrame:
    """Find every undercut/overcut duel in a race and measure its net outcome.

    A duel = driver A pits on lap L_A, and a rival B running within
    max_track_gap_s of A on track (at the end of lap L_A−1) pits within the
    next max_stop_gap laps. The gap between them is measured before A's stop
    and again at the end of B's out-lap (lap L_B+1), when both cars have
    completed the pit cycle.

    Net_Gain > 0  →  the first stopper (A, the undercutter) gained time.

    Columns: Attacker (first stopper), Defender, Team (attacker's),
    Stop_A, Stop_B, Gap_Before, Gap_After, Net_Gain, Jumped (A passed B
    through the cycle), Lost_Position, Flag_Affected (any yellow/SC/VSC/red
    on either car between L_A−1 and L_B+1 — pit-cycle maths is unreliable
    under those).
    """
    need = {"LapNo", "LapStartTime", "LapTime_s", "PitIn"}
    if rl.empty or not need.issubset(rl.columns):
        return pd.DataFrame()

    df = rl.copy()
    df["LapNo"] = pd.to_numeric(df["LapNo"], errors="coerce")
    df["_t_end"] = (
        pd.to_numeric(df["LapStartTime"], errors="coerce")
        + pd.to_numeric(df["LapTime_s"], errors="coerce")
    )
    df = df[df["_t_end"].notna() & df["LapNo"].notna()]
    if df.empty:
        return pd.DataFrame()
    df["LapNo"] = df["LapNo"].astype(int)

    # Elapsed race time at the end of each completed lap, per driver
    t = df.pivot_table(index="LapNo", columns="Driver_Short",
                       values="_t_end", aggfunc="first")
    teams = df.groupby("Driver_Short")["Team"].first()

    # (driver, lap) pairs run under a disturbing flag
    flagged: set = set()
    if "TrackStatus_Flag" in df.columns:
        _f = df[df["TrackStatus_Flag"].fillna("Clear") != "Clear"]
        flagged = set(zip(_f["Driver_Short"], _f["LapNo"]))

    stops = {
        drv: sorted(g.loc[g["PitIn"].notna(), "LapNo"].tolist())
        for drv, g in df.groupby("Driver_Short")
    }

    rows = []
    for a, a_stops in stops.items():
        for la in a_stops:
            for b, b_stops in stops.items():
                if b == a:
                    continue
                lb = next((s for s in b_stops if la < s <= la + max_stop_gap),
                          None)
                if lb is None:
                    continue
                m = lb + 1
                try:
                    ta0, tb0 = t.at[la - 1, a], t.at[la - 1, b]
                    ta1, tb1 = t.at[m, a],      t.at[m, b]
                except KeyError:
                    continue
                if any(pd.isna(v) for v in (ta0, tb0, ta1, tb1)):
                    continue
                gap_before = float(ta0 - tb0)     # > 0 : A behind B on track
                if abs(gap_before) > max_track_gap_s:
                    continue
                gap_after = float(ta1 - tb1)
                dist = any(
                    (d, l) in flagged
                    for d in (a, b) for l in range(la - 1, m + 1)
                )
                rows.append(dict(
                    Attacker=a, Defender=b, Team=teams.get(a, ""),
                    Stop_A=la, Stop_B=lb,
                    Gap_Before=gap_before, Gap_After=gap_after,
                    Net_Gain=gap_before - gap_after,
                    Jumped=(gap_before > 0) and (gap_after < 0),
                    Lost_Position=(gap_before < 0) and (gap_after > 0),
                    Flag_Affected=dist,
                ))
    return pd.DataFrame(rows)


def _undercut_fig(pairs: pd.DataFrame, title: str) -> go.Figure:
    """Diverging bar chart of pit-cycle duels: one row per undercut attempt,
    positive = the first stopper gained time. Flag-affected cycles are dimmed."""
    fig = go.Figure()
    if pairs.empty:
        theme(fig, 320, title)
        fig.add_annotation(
            text="No comparable pit-cycle duels found (cars must be within "
                 "15 s and stop within 5 laps of each other).",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(color=TEXT_DIM, size=13),
        )
        return fig

    p = pairs.sort_values("Net_Gain").reset_index(drop=True)
    p["Label"] = [
        f"{r.Attacker} L{r.Stop_A} → {r.Defender} L{r.Stop_B}"
        for r in p.itertuples()
    ]
    base_clr = p["Team"].map(TEAM_COLORS).fillna("#808080")
    p["Color"] = [
        "rgba({},{},{},0.33)".format(
            int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
        ) if fa else c
        for c, fa in zip(base_clr, p["Flag_Affected"])
    ]
    p["Outcome"] = np.select(
        [p["Jumped"], p["Lost_Position"]],
        ["✓ jumped ahead", "✗ lost the place"],
        default="held station",
    )
    p["FlagNote"] = np.where(
        p["Flag_Affected"], "⚠ flag/SC during cycle — unreliable", "clean cycle"
    )
    p["GainFmt"] = p["Net_Gain"].apply(lambda x: f"{x:+.1f}")
    p["Text"] = [
        f"{g}{' ✓' if j else ''}" for g, j in zip(p["GainFmt"], p["Jumped"])
    ]

    _max = max(p["Net_Gain"].abs().max() * 1.35, 3.0)
    fig.add_trace(go.Bar(
        y=p["Label"], x=p["Net_Gain"], orientation="h",
        marker=dict(color=p["Color"], line=dict(color=GRID_CLR, width=0.5)),
        customdata=p[["Gap_Before", "Gap_After", "Outcome", "FlagNote"]].values,
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Gap before first stop: %{customdata[0]:+.1f} s "
            "(+ = attacker behind)<br>"
            "Gap after both stops: %{customdata[1]:+.1f} s<br>"
            "Net gain for first stopper: %{x:+.1f} s<br>"
            "%{customdata[2]}  ·  %{customdata[3]}<extra></extra>"
        ),
        text=p["Text"], textposition="outside",
        textfont=dict(size=10, color=TEXT_MAIN),
    ))
    fig.add_vline(x=0, line=dict(color="white", width=1, dash="dash"))
    fig.add_vrect(x0=0, x1=_max, fillcolor="rgba(0,200,100,0.05)",
                  line_width=0, layer="below")
    fig.add_vrect(x0=-_max, x1=0, fillcolor="rgba(225,6,0,0.05)",
                  line_width=0, layer="below")

    clean = p[~p["Flag_Affected"]]["Net_Gain"]
    subtitle = (
        f"median clean-cycle undercut value: {clean.median():+.1f} s"
        if len(clean) >= 3 else "too few clean cycles for a median"
    )
    ht = max(340, 26 * len(p) + 110)
    theme(fig, ht, title)
    fig.update_layout(
        xaxis=dict(
            title="s gained by the first stopper  ·  positive = undercut worked",
            range=[-_max, _max], gridcolor=GRID_CLR, zeroline=False,
        ),
        yaxis=dict(gridcolor=GRID_CLR, zeroline=False),
        bargap=0.3, showlegend=False,
        annotations=[dict(
            text=subtitle, xref="paper", yref="paper", x=1, y=1.02,
            xanchor="right", showarrow=False,
            font=dict(size=10, color=TEXT_DIM),
        )],
    )
    return fig


# ══════════════════════════════════════════════════════════════
#  STRATEGY WHAT-IF SIMULATOR
#  Built entirely from quantities the pipeline already estimates:
#  field deg curves + compound offsets + pit loss measured in-race.
# ══════════════════════════════════════════════════════════════

_SIM_MIN_STINT = 5      # laps — shortest stint the optimizer may schedule


from f1lib.tyre_allocations import _allocation_chips, _allocation_for, _laps_event


def _estimate_pit_loss(rl: pd.DataFrame) -> float | None:
    """Median time lost across a pit cycle (in-lap + out-lap vs two normal
    laps), from clean (non-flag) stops only. This is the real 'cost of a
    stop' the strategy optimizer needs — pit-lane transit plus the slow
    in/out phases."""
    need = {"LapNo", "LapTime_s", "PitIn"}
    if rl.empty or not need.issubset(rl.columns):
        return None
    losses = []
    for drv, g in rl.groupby("Driver_Short"):
        g = g.sort_values("LapNo")
        clean = g[g["ValidLap"]] if "ValidLap" in g.columns else g
        med = clean["LapTime_s"].median()
        if pd.isna(med):
            continue
        lt = g.set_index("LapNo")["LapTime_s"]
        fl = (g.set_index("LapNo")["TrackStatus_Flag"]
              if "TrackStatus_Flag" in g.columns else None)
        for l_in in g.loc[g["PitIn"].notna(), "LapNo"]:
            t_in, t_out = lt.get(l_in), lt.get(l_in + 1)
            if pd.isna(t_in) or pd.isna(t_out):
                continue
            if fl is not None:
                f1 = str(fl.get(l_in, "Clear")); f2 = str(fl.get(l_in + 1, "Clear"))
                if f1 not in ("Clear", "nan") or f2 not in ("Clear", "nan"):
                    continue        # SC/VSC stops are artificially cheap
            loss = (t_in + t_out) - 2 * med
            if 5 < loss < 60:
                losses.append(loss)
    return round(float(np.median(losses)), 1) if len(losses) >= 3 else None


def _strategy_model(rl: pd.DataFrame, total_laps: int) -> dict | None:
    """Per-compound per-lap cost arrays for the simulator.

    cost[a] (a = tyre age 1..total_laps) = compound offset + field deg curve
    value at that age. The offset chain is anchored on the softest compound
    present; the deg curve is linearly extrapolated beyond the longest
    observed stint (slope of its last 4 observed points, floored at
    +0.02 s/lap so an extrapolated tyre never becomes immortal).

    Returns {comp: {"cost": np.ndarray (index 0 unused), "max_obs": int}}
    or None when fewer than two dry compounds have usable curves.
    """
    order = ["SOFT", "MEDIUM", "HARD"]
    comps = [c for c in order if c in rl["Compound"].unique()]
    if len(comps) < 2:
        return None

    # ── Offsets chained to the softest compound present ──────
    off_df = compound_offsets(rl)
    offsets = {comps[0]: 0.0}
    if not off_df.empty:
        pair_map = {r.Pair: r.Offset_s for r in off_df.itertuples()}
        for c in comps[1:]:
            direct = pair_map.get(f"{comps[0]} → {c}")
            if direct is not None:
                offsets[c] = float(direct)
                continue
            # chain through an intermediate compound if needed
            for mid in comps:
                if mid in offsets and f"{mid} → {c}" in pair_map:
                    offsets[c] = offsets[mid] + float(pair_map[f"{mid} → {c}"])
                    break
    for c in comps:                     # unreachable pairs → assume 0 offset
        offsets.setdefault(c, 0.0)

    # ── Deg curves → per-lap cost arrays ─────────────────────
    model = {}
    for c in comps:
        fd = field_deg_curves(rl, c)
        if fd is None:
            continue
        curve = fd["curve"]
        ages  = curve["_age"].values.astype(float)
        delta = curve["median"].values.astype(float)
        max_obs = int(ages.max())

        # slope of the last 4 observed points for extrapolation
        tail = curve.tail(4)
        if len(tail) >= 2 and np.ptp(tail["_age"].values) > 0:
            slope = float(np.polyfit(tail["_age"], tail["median"], 1)[0])
        else:
            slope = 0.05
        slope = max(slope, 0.02)

        a_all = np.arange(1, total_laps + 1, dtype=float)
        d_all = np.interp(a_all, ages, delta)          # clamps at both ends
        beyond = a_all > max_obs
        d_all[beyond] = delta[-1] + slope * (a_all[beyond] - max_obs)
        # Enforce monotonic deg: pooled medians can DIP at high ages because
        # only the healthiest stints survive that long (survivor bias), and
        # the optimizer would exploit those dips. A tyre never un-degrades.
        d_all = np.maximum.accumulate(d_all)

        cost = np.empty(total_laps + 1)
        cost[0] = 0.0
        cost[1:] = offsets[c] + d_all
        model[c] = {"cost": cost, "max_obs": max_obs}

    return model if len(model) >= 2 else None


# Safety-car what-if: a stop taken while the SC is out only costs a fraction
# of the normal pit loss (the field circulates slowly, so the pit-lane detour
# hurts far less). Window = SC deployment length in laps.
_SC_FACTOR = 0.45
_SC_WINDOW = 2      # SC covers laps [sc_lap, sc_lap + _SC_WINDOW]

# Traffic model: a stop drops the car behind every rival that was within
# pit_loss behind it (traffic_exposure_curve measures how many, weighted by
# rejoin proximity). Each of those costs roughly LAPS_TO_CLEAR laps in dirty
# air at the penalty measured from this race (dirty_air_penalty).
_TRAFFIC_LAPS_TO_CLEAR = 2.0
_TRAFFIC_MIN_PENALTY = 0.10   # s/lap — below this the term is noise, leave it off


def _simulate_strategies(model: dict, total_laps: int, pit_loss: float,
                         allowed_stops=(1, 2), sc_lap: int | None = None,
                         traffic_cost: np.ndarray | None = None):
    """Grid-search optimal stop laps for every legal compound plan.

    Returns (results DataFrame sorted by Total, sensitivity dict
    {label: (s1_array, delta_vs_best_array)} for the pit-window chart).
    Times are relative — only differences between strategies matter.
    With `sc_lap`, stops falling inside the SC window are discounted to
    _SC_FACTOR × pit_loss (the what-if: "who'd have won with an SC there?").
    With `traffic_cost` (array indexed by stop lap, 0..total_laps), each
    stop additionally pays the rejoin-traffic cost of its lap — so windows
    that release the car into a train price worse than clear ones. The SC
    discount applies to the pit-lane loss only; rejoining an SC queue still
    carries its (large) traffic term, which is exactly what happens in
    reality.
    """
    L, minS = total_laps, _SIM_MIN_STINT
    comps = list(model)
    cum = {c: np.concatenate([[0.0], np.cumsum(model[c]["cost"][1:])])
           for c in comps}     # cum[c][n] = cost of an n-lap stint on c

    def _loss(stop_laps):
        arr = np.asarray(stop_laps, dtype=float)
        if sc_lap is None:
            base = np.full(arr.shape, pit_loss)
        else:
            in_sc = (arr >= sc_lap) & (arr <= sc_lap + _SC_WINDOW)
            base = np.where(in_sc, pit_loss * _SC_FACTOR, pit_loss)
        if traffic_cost is not None:
            base = base + traffic_cost[np.clip(arr.astype(int), 0, L)]
        return base

    rows, sens = [], {}

    if 1 in allowed_stops and L >= 2 * minS:
        s_range = np.arange(minS, L - minS + 1)
        for c1 in comps:
            for c2 in comps:
                if c1 == c2:
                    continue                     # two-compound rule
                totals = (cum[c1][s_range] + cum[c2][L - s_range]
                          + _loss(s_range))
                k = int(np.argmin(totals))
                s1 = int(s_range[k])
                label = f"{c1[0]}({s1}) → {c2[0]}({L - s1})"
                rows.append(dict(
                    Label=label, Stops=1, Total=float(totals[k]),
                    StopLaps=f"L{s1}",
                    Extrapolated=(s1 > model[c1]["max_obs"]
                                  or (L - s1) > model[c2]["max_obs"]),
                    Compounds=f"{c1} → {c2}",
                ))
                sens[label] = (s_range, totals)

    if 2 in allowed_stops and L >= 3 * minS:
        from itertools import product
        s1_range = np.arange(minS, L - 2 * minS + 1)
        for c1, c2, c3 in product(comps, repeat=3):
            if len({c1, c2, c3}) < 2:
                continue
            best = None
            best_curve = np.full(len(s1_range), np.inf)
            for i, s1 in enumerate(s1_range):
                s2r = np.arange(s1 + minS, L - minS + 1)
                if len(s2r) == 0:
                    continue
                t = (cum[c1][s1] + cum[c2][s2r - s1] + cum[c3][L - s2r]
                     + float(_loss(s1)) + _loss(s2r))
                j = int(np.argmin(t))
                best_curve[i] = t[j]
                if best is None or t[j] < best[0]:
                    best = (float(t[j]), int(s1), int(s2r[j]))
            if best is None:
                continue
            tot, s1, s2 = best
            label = f"{c1[0]}({s1}) → {c2[0]}({s2 - s1}) → {c3[0]}({L - s2})"
            rows.append(dict(
                Label=label, Stops=2, Total=tot,
                StopLaps=f"L{s1} / L{s2}",
                Extrapolated=(s1 > model[c1]["max_obs"]
                              or (s2 - s1) > model[c2]["max_obs"]
                              or (L - s2) > model[c3]["max_obs"]),
                Compounds=f"{c1} → {c2} → {c3}",
            ))
            sens[label] = (s1_range, best_curve)

    if not rows:
        return pd.DataFrame(), {}
    res = pd.DataFrame(rows).sort_values("Total").reset_index(drop=True)
    best_total = res["Total"].iloc[0]
    res["Delta_s"] = (res["Total"] - best_total).round(2)
    sens = {k: (s, v - best_total) for k, (s, v) in sens.items()}
    return res, sens


def _strategy_sim_content(rl: pd.DataFrame, pit_loss=None, stops=(1, 2),
                          sc_lap=None, traffic_on=True):
    """Build the simulator output (ranked board + pit-window chart)."""
    if rl.empty or "LapNo" not in rl.columns:
        return html.P("No race laps available.", style={"color": TEXT_DIM})
    total_laps = int(pd.to_numeric(rl["LapNo"], errors="coerce").max())
    est_loss = _estimate_pit_loss(rl)
    if pit_loss is None:
        pit_loss = est_loss if est_loss is not None else 22.0
    pit_loss = float(pit_loss)
    try:
        sc_lap = int(sc_lap) if sc_lap else None
    except (TypeError, ValueError):
        sc_lap = None
    if sc_lap is not None and not (1 < sc_lap < total_laps):
        sc_lap = None

    model = _strategy_model(rl, total_laps)
    if model is None:
        return html.P(
            "Not enough dry-compound data to build deg curves for at least "
            "two compounds — the simulator needs a dry race with mixed "
            "strategies.", style={"color": TEXT_DIM})

    # ── traffic term: measured dirty-air penalty × rejoin exposure ──
    pen = dirty_air_penalty(rl) if traffic_on else None
    exposure = (traffic_exposure_curve(rl, pit_loss)
                if traffic_on and pen is not None else None)
    traffic_usable = (pen is not None and exposure is not None
                      and pen["penalty_s"] >= _TRAFFIC_MIN_PENALTY)
    traffic_cost = None
    if traffic_usable:
        traffic_cost = np.zeros(total_laps + 1)
        idx = exposure.index[(exposure.index >= 1)
                             & (exposure.index <= total_laps)]
        traffic_cost[idx] = (exposure.loc[idx].to_numpy()
                             * _TRAFFIC_LAPS_TO_CLEAR * pen["penalty_s"])

    stops = tuple(int(s) for s in (stops or (1, 2)))
    res, sens = _simulate_strategies(model, total_laps, pit_loss, stops,
                                     sc_lap=sc_lap,
                                     traffic_cost=traffic_cost)
    if res.empty:
        return html.P("No legal strategies for the chosen settings.",
                      style={"color": TEXT_DIM})

    top = res.head(10).iloc[::-1]          # best at the top of a h-bar chart
    labels = [f"{'⚠ ' if e else ''}{l}"
              for l, e in zip(top["Label"], top["Extrapolated"])]
    fig_rank = go.Figure(go.Bar(
        y=labels, x=top["Delta_s"], orientation="h",
        marker=dict(
            color=[COMPOUND_COLORS.get(c.split(" → ")[0], "#808080")
                   for c in top["Compounds"]],
            line=dict(color=GRID_CLR, width=0.5),
        ),
        customdata=top[["StopLaps", "Stops", "Compounds"]].values,
        hovertemplate=(
            "<b>%{customdata[2]}</b><br>"
            "Optimal stop(s): %{customdata[0]} (%{customdata[1]}-stop)<br>"
            "Time vs best strategy: +%{x:.1f} s<extra></extra>"
        ),
        text=[f"+{v:.1f}s" if v > 0 else "BEST" for v in top["Delta_s"]],
        textposition="outside",
        textfont=dict(size=10, color=TEXT_MAIN),
    ))
    theme(fig_rank, max(320, 30 * len(top) + 90),
          f"Strategy Board — {total_laps} laps · pit loss {pit_loss:.1f}s"
          + (" · traffic-aware" if traffic_usable else "")
          + (f" · what-if SC L{sc_lap}–L{sc_lap + _SC_WINDOW}"
             if sc_lap else ""))
    fig_rank.update_layout(
        xaxis=dict(title="time lost vs optimal strategy (s)",
                   gridcolor=GRID_CLR, zeroline=False,
                   range=[0, max(float(top['Delta_s'].max()) * 1.25, 3)]),
        yaxis=dict(gridcolor=GRID_CLR, zeroline=False),
        showlegend=False, bargap=0.3,
    )

    fig_sens = go.Figure()
    if traffic_usable:
        # faint backdrop first, so the strategy lines draw on top of it
        exp_idx = exposure.index[(exposure.index >= 1)
                                 & (exposure.index <= total_laps)]
        fig_sens.add_trace(go.Scatter(
            x=exp_idx, y=exposure.loc[exp_idx], mode="lines",
            name="cars in rejoin window", yaxis="y2",
            line=dict(width=0), fill="tozeroy",
            fillcolor="rgba(255,176,0,0.14)",
            hovertemplate=("stop on lap %{x}: rejoin behind "
                           "~%{y:.1f} cars<extra></extra>"),
        ))
    for label in res.head(5)["Label"]:
        if label not in sens:
            continue
        s_arr, d_arr = sens[label]
        first_comp = label.split("(")[0]
        clr = COMPOUND_COLORS.get(
            {"S": "SOFT", "M": "MEDIUM", "H": "HARD"}.get(first_comp, ""),
            "#808080")
        fig_sens.add_trace(go.Scatter(
            x=s_arr, y=d_arr, mode="lines", name=label,
            line=dict(width=2),
            hovertemplate=(f"<b>{label}</b><br>First stop lap %{{x}}<br>"
                           "+%{y:.1f} s vs optimal<extra></extra>"),
        ))
    fig_sens.add_hline(y=1.0, line=dict(color=TEXT_DIM, width=1, dash="dot"),
                       annotation_text="+1 s", annotation_font_size=9)
    theme(fig_sens, 380, "Pit Window Sensitivity — cost of mistiming the first stop")
    fig_sens.update_layout(
        xaxis_title="First stop lap",
        yaxis_title="Time lost vs optimal (s)",
        yaxis=dict(range=[0, 15], gridcolor=GRID_CLR),
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR,
                    borderwidth=1, font=dict(size=9)),
    )
    if traffic_usable:
        _exp_max = float(exposure.max()) or 1.0
        fig_sens.update_layout(yaxis2=dict(
            overlaying="y", side="right", showgrid=False, zeroline=False,
            range=[0, _exp_max * 2.6],           # keep the backdrop low
            title=dict(text="cars in rejoin window",
                       font=dict(size=10, color="#FFB000")),
            tickfont=dict(size=9, color="#FFB000"),
        ))

    note_bits = [f"Pit loss estimated from this race: "
                 f"{est_loss:.1f} s. " if est_loss is not None else
                 "Pit loss could not be estimated from this race — using the "
                 "value above. "]
    if traffic_usable:
        note_bits.append(
            f"Traffic: dirty air measured at +{pen['penalty_s']:.2f} s/lap "
            f"({pen['n_stints']} stints); each stop pays "
            f"~{_TRAFFIC_LAPS_TO_CLEAR:.0f} laps of that per car in its "
            "rejoin window (amber backdrop below). ")
    elif traffic_on:
        note_bits.append(
            "Traffic term off: dirty air wasn't measurably slow in this race"
            + (f" ({pen['penalty_s']:+.2f} s/lap — slipstream/DRS likely "
               "offset it)" if pen is not None else
               " (not enough mixed clean/dirty stints to measure)") + ". ")
    if sc_lap:
        note_bits.append(
            f"What-if: Safety Car on laps {sc_lap}–{sc_lap + _SC_WINDOW} — "
            f"stops in that window cost only "
            f"{pit_loss * _SC_FACTOR:.1f} s ({int(_SC_FACTOR * 100)}%) of "
            "pit loss (their rejoin-traffic term still applies). ")
    if res["Extrapolated"].any():
        note_bits.append("⚠ marks plans needing stints longer than anything "
                         "observed — their deg is extrapolated.")
    _sim_season, _sim_meeting = _laps_event(rl)
    return html.Div([
        _allocation_chips(_sim_season, _sim_meeting) or html.Div(),
        html.P("".join(note_bits),
               style={"color": TEXT_DIM, "fontSize": "0.75rem",
                      "marginBottom": "6px", "fontStyle": "italic"}),
        dcc.Graph(figure=fig_rank, config=GFX),
        dcc.Graph(figure=fig_sens, config=GFX),
    ])


# ── Wet-race crossover (inter ↔ slick break-even) ─────────────
def _wet_crossover_fig(res: dict, title: str, height: int = 460) -> go.Figure:
    """Top: field median lap time on inters vs slicks per lap. Bottom: their
    delta with the crossover lap(s) marked — where the fastest tyre changed."""
    per = res["per_lap"]
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        row_heights=[0.62, 0.38],
        subplot_titles=("Field median lap time by tyre group",
                        "Inter − slick delta  ·  0 = break-even"),
    )
    fig.add_trace(go.Scatter(
        x=per["LapNo"], y=per["inter_med"], mode="lines", name="Intermediate",
        line=dict(color=COMPOUND_COLORS["INTER"], width=2.5),
        connectgaps=False,
        hovertemplate="L%{x} inter: %{y:.1f}s<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=per["LapNo"], y=per["slick_med"], mode="lines", name="Slick",
        line=dict(color="#E8E8E8", width=2.5), connectgaps=False,
        hovertemplate="L%{x} slick: %{y:.1f}s<extra></extra>"), row=1, col=1)

    dpos = per["delta"].clip(lower=0)
    dneg = per["delta"].clip(upper=0)
    fig.add_trace(go.Scatter(
        x=per["LapNo"], y=dpos, mode="lines", name="slicks faster",
        line=dict(width=0), fill="tozeroy",
        fillcolor="rgba(232,232,232,0.35)", connectgaps=False,
        hoverinfo="skip", showlegend=False), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=per["LapNo"], y=dneg, mode="lines", name="inters faster",
        line=dict(width=0), fill="tozeroy",
        fillcolor="rgba(57,181,74,0.35)", connectgaps=False,
        hoverinfo="skip", showlegend=False), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=per["LapNo"], y=per["delta"], mode="lines", name="delta",
        line=dict(color=TEXT_MAIN, width=1.5), connectgaps=False,
        hovertemplate="L%{x} delta: %{y:+.1f}s<extra></extra>",
        showlegend=False), row=2, col=1)
    fig.add_hline(y=0, line=dict(color=TEXT_DIM, width=1, dash="dash"),
                  row=2, col=1)

    for c in res["crossings"]:
        lab = ("→ slicks" if c["direction"] == "to_slick" else "→ inters")
        style = "solid" if c.get("interp", True) else "dot"
        for r in (1, 2):
            fig.add_vline(x=c["lap"], line=dict(color=ACCENT, width=1.5,
                                                dash=style), row=r, col=1)
        fig.add_annotation(x=c["lap"], yref="paper", y=1.0,
                           text=f"L{c['lap']} {lab}", showarrow=False,
                           font=dict(size=9, color=ACCENT),
                           xanchor="left", xshift=3)

    theme(fig, height, title)
    fig.update_yaxes(title_text="Lap time (s)", row=1, col=1)
    fig.update_yaxes(title_text="Δ (s)", row=2, col=1)
    fig.update_xaxes(title_text="Lap", row=2, col=1)
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.04,
                                  xanchor="left", x=0))
    return fig


def _wet_switch_fig(res: dict, title: str, height: int = 420) -> go.Figure:
    """Per-driver: how many laps late (vs the field crossover) each driver
    switched tyres, and the field-median time that timing cost."""
    sw = res["switches"].dropna(subset=["delta_laps"]).copy()
    fig = go.Figure()
    if sw.empty:
        theme(fig, height, title)
        fig.add_annotation(text="No driver switches matched a crossover.",
                           xref="paper", yref="paper", x=0.5, y=0.5,
                           showarrow=False, font=dict(color=TEXT_DIM))
        return fig
    # one row per driver: prefer the switch with the largest time impact
    sw["_abs"] = sw["time_lost_s"].abs().fillna(0)
    sw = (sw.sort_values("_abs", ascending=False)
          .drop_duplicates("Driver_Short"))
    sw = sw.sort_values("delta_laps")
    fig.add_trace(go.Bar(
        x=sw["delta_laps"], y=sw["Driver_Short"], orientation="h",
        marker_color=[TEAM_COLORS.get(t, "#808080") for t in sw["Team"]],
        customdata=np.stack([sw["direction"].map(
            {"to_slick": "→ slicks", "to_inter": "→ inters"}),
            sw["lap"], sw["crossover_lap"], sw["time_lost_s"]], axis=-1),
        hovertemplate=("<b>%{y}</b> %{customdata[0]}<br>"
                       "switched lap %{customdata[1]:.0f} "
                       "(crossover lap %{customdata[2]:.0f})<br>"
                       "%{x:+.0f} laps vs field · ~%{customdata[3]:.0f}s"
                       "<extra></extra>"),
        text=[f"{v:+.0f}" for v in sw["delta_laps"]], textposition="outside",
        textfont=dict(size=10)))
    fig.add_vline(x=0, line=dict(color="#fff", width=1, dash="dash"))
    theme(fig, max(340, 22 * len(sw) + 110), title)
    span = float(sw["delta_laps"].abs().max()) or 1.0
    fig.update_xaxes(title_text="Laps late (+) / early (−) vs field crossover",
                     range=[-span * 1.3, span * 1.3])
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(showlegend=False, bargap=0.3)
    return fig


def _weather_race_fig(rl: pd.DataFrame, title: str, height: int = 480) -> go.Figure:
    """Lap-aligned weather strip for a race: track & air temperature (with rain
    periods shaded) stacked directly above the field's median lap pace, sharing
    the lap x-axis so conditions can be read straight down onto their effect on
    pace. Returns an empty Figure when no usable weather data is present."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.55, 0.45], vertical_spacing=0.07,
    )

    has_temp = any(
        c in rl.columns and rl[c].notna().any() for c in ("TrackTemp", "AirTemp")
    )
    if rl.empty or "LapNo" not in rl.columns or not has_temp:
        return go.Figure()

    # ── Per-lap weather (one value per lap, averaged across cars on track) ──
    agg: dict[str, tuple] = {}
    for col, how in (("TrackTemp", "mean"), ("AirTemp", "mean"),
                     ("Humidity", "mean"), ("WindSpeed", "mean"),
                     ("Rainfall", "max")):
        if col in rl.columns:
            agg[col] = (col, how)
    per_lap = rl.groupby("LapNo").agg(**agg).reset_index().sort_values("LapNo")

    # ── Field pace per lap (median of racing laps; spikes show SC/rain) ──
    racing = rl[~rl.get("PitLap", False) & rl["LapTime_s"].notna()
                & (rl["LapTime_s"] > 0)]
    pace = (racing.groupby("LapNo")["LapTime_s"].median().reset_index()
            .sort_values("LapNo")) if not racing.empty else pd.DataFrame()

    # ── Row 1: temperatures ──────────────────────────────────
    if "TrackTemp" in per_lap.columns:
        fig.add_trace(go.Scatter(
            x=per_lap["LapNo"], y=per_lap["TrackTemp"], mode="lines",
            name="Track temp", line=dict(color="#FF8700", width=2.2),
            hovertemplate="Lap %{x}<br>Track %{y:.1f} °C<extra></extra>",
        ), row=1, col=1)
    if "AirTemp" in per_lap.columns:
        fig.add_trace(go.Scatter(
            x=per_lap["LapNo"], y=per_lap["AirTemp"], mode="lines",
            name="Air temp", line=dict(color="#00D2BE", width=2.0, dash="dot"),
            hovertemplate="Lap %{x}<br>Air %{y:.1f} °C<extra></extra>",
        ), row=1, col=1)

    # ── Row 2: field pace ────────────────────────────────────
    if not pace.empty:
        fig.add_trace(go.Scatter(
            x=pace["LapNo"], y=pace["LapTime_s"], mode="lines",
            name="Field median lap", line=dict(color=TEXT_MAIN, width=1.8),
            hovertemplate="Lap %{x}<br>Median %{y:.3f} s<extra></extra>",
        ), row=2, col=1)

    # ── Rain bands across both rows ──────────────────────────
    rain_groups = _rain_lap_groups(per_lap)
    for i, (start, end) in enumerate(rain_groups):
        for r in (1, 2):
            fig.add_vrect(
                x0=start - 0.5, x1=end + 0.5,
                fillcolor="rgba(0,120,255,0.12)", line_width=0, layer="below",
                annotation_text=("\U0001f327 rain" if (i == 0 and r == 1) else ""),
                annotation_position="top left",
                annotation_font=dict(size=9, color="#4DA3FF"),
                row=r, col=1,
            )

    theme(fig, height, title)
    fig.update_yaxes(title_text="Temp (°C)", row=1, col=1)
    fig.update_yaxes(title_text="Lap Time (s)", row=2, col=1)
    fig.update_xaxes(title_text="Lap Number", row=2, col=1)
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="left", x=0, bgcolor="rgba(0,0,0,0)",
                    bordercolor=GRID_CLR, borderwidth=1),
    )
    return fig


# ── Pit-stop performance (real stationary / pit-lane times) ──
# Loaded from pitstops_loader (live-timing PitStopSeries → stationary times;
# Jolpica fallback → pit-lane durations only). Memoized per meeting so a
# no-data race doesn't re-hit the network on every tab render.
_PITSTOP_MEMO: dict[tuple, pd.DataFrame] = {}


def _pitstops_for(season, meeting) -> pd.DataFrame:
    key = (str(season), meeting)
    if key not in _PITSTOP_MEMO:
        try:
            _PITSTOP_MEMO[key] = load_pitstops(season, meeting)
        except Exception as exc:
            logging.warning("Pit-stop load failed for %s %s: %s",
                            season, meeting, exc)
            _PITSTOP_MEMO[key] = pd.DataFrame()
    return _PITSTOP_MEMO[key]


def _pitstops_enriched(ps: pd.DataFrame, rl: pd.DataFrame) -> pd.DataFrame:
    """Attach Driver_Short/Team from the race laps. Live-timing rows carry
    only the racing number (matches laps DriverNo); Jolpica rows carry the
    3-letter code (its 'permanent number' can differ from the racing number,
    so the code is the safe join key there)."""
    if ps.empty or rl.empty:
        return pd.DataFrame()
    ps = ps.copy()
    ref = rl.dropna(subset=["Driver_Short"]).drop_duplicates("DriverNo")
    no2code = ref.set_index(ref["DriverNo"].astype(str))["Driver_Short"].to_dict()
    code2team = (rl.dropna(subset=["Driver_Short", "Team"])
                 .drop_duplicates("Driver_Short")
                 .set_index("Driver_Short")["Team"].to_dict())
    need_code = ps["Driver_Short"].fillna("").eq("")
    ps.loc[need_code, "Driver_Short"] = (
        ps.loc[need_code, "DriverNo"].astype(str).map(no2code)
    )
    ps["Team"] = ps["Driver_Short"].map(code2team)
    ps = ps.dropna(subset=["Driver_Short", "Team"])
    # respect the sidebar Driver/Team filter (rl is already filtered)
    return ps[ps["Driver_Short"].isin(rl["Driver_Short"].unique())]


def _pitstops_fig(ps: pd.DataFrame, title: str, use_stationary: bool,
                  height: int = 420) -> go.Figure:
    """Left: every stop on the race-lap axis (label = driver). Right: teams
    ranked by their median time. Uses true stationary time when the
    live-timing feed had it, pit-lane transit time otherwise."""
    val_col = "StationaryTime_s" if use_stationary else "PitLaneTime_s"
    metric  = "Stationary time (s)" if use_stationary else "Pit-lane time (s)"
    d = ps.dropna(subset=[val_col])
    # Some live-timing feeds omit the lap number — fall back to clock time
    # on the x-axis so the stops still plot.
    use_lap_axis = d["LapNo"].notna().mean() >= 0.5
    x_col, x_title = ("LapNo", "Lap") if use_lap_axis else ("Utc", "Time (UTC)")
    if not use_lap_axis:
        d = d.assign(Utc=pd.to_datetime(d["Utc"], errors="coerce"))

    fig = make_subplots(
        rows=1, cols=2, column_widths=[0.60, 0.40], horizontal_spacing=0.09,
        subplot_titles=(f"Every stop, by {x_title.lower().split(' ')[0]}",
                        "Team ranking · median"),
    )
    for team in _order_teams_by_champ(d["Team"].unique()):
        g = d[d["Team"] == team].sort_values(x_col)
        clr = TEAM_COLORS.get(team, "#808080")
        fig.add_trace(go.Scatter(
            x=g[x_col], y=g[val_col], mode="markers+text",
            text=g["Driver_Short"], textposition="top center",
            textfont=dict(size=9, color=clr),
            marker=dict(size=10, color=clr, line=dict(width=1, color="#000")),
            name=_abbr(team), legendgroup=team,
            customdata=np.stack([g["Driver_Short"], g["StopNo"]], axis=-1),
            hovertemplate=("%{customdata[0]} · stop %{customdata[1]} · "
                           + ("lap %{x}" if use_lap_axis else "%{x}") + "<br>"
                           + metric + ": %{y:.1f}s"
                           "<extra>" + _abbr(team) + "</extra>"),
        ), row=1, col=1)

    med = (d.groupby("Team")[val_col].median().sort_values(ascending=False))
    fig.add_trace(go.Bar(
        x=med.values, y=[_abbr(t) for t in med.index], orientation="h",
        marker_color=[TEAM_COLORS.get(t, "#808080") for t in med.index],
        text=[f"{v:.2f}s" for v in med.values], textposition="outside",
        textfont=dict(size=10), showlegend=False,
        hovertemplate="%{y}: median %{x:.2f}s<extra></extra>",
    ), row=1, col=2)

    theme(fig, height, title)
    fig.update_xaxes(title_text=x_title, row=1, col=1)
    fig.update_yaxes(title_text=metric, row=1, col=1)
    fig.update_xaxes(title_text=f"median {metric.lower()}", row=1, col=2)
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.06,
                                  xanchor="left", x=0,
                                  bgcolor="rgba(0,0,0,0)"))
    # headroom so the outside bar labels and marker text don't clip
    if len(d):
        fig.update_yaxes(range=clipped_range(d[val_col], 0.35), row=1, col=1)
        fig.update_xaxes(range=[0, med.max() * 1.18], row=1, col=2)
    return fig


def _pitstops_card(rl: pd.DataFrame, meeting, shown_year) -> object:
    info = ("Data: real per-stop pit data — the F1 live-timing PitStopSeries "
            "feed (true stationary jack-up-to-jack-down time plus pit-lane "
            "transit) for recent races, falling back to the Jolpica/Ergast "
            "archive (pit-lane duration only) for older ones. Cached under "
            "data/pitstops/. Why: pit-crew execution is a real performance "
            "axis — a slow stop costs the same as a driving mistake, and "
            "until now the dashboard only *inferred* pit loss from lap "
            "times. The right panel ranks each crew's median stop.")
    ps = _pitstops_for(shown_year, meeting)
    ps = _pitstops_enriched(ps, rl)
    if ps.empty:
        return card(
            [*gloss("pit stop", "Pit Stop"), " Performance"],
            html.P("No pit-stop data available for this race (neither the "
                   "live-timing archive nor Jolpica has it).",
                   style={"color": TEXT_DIM}),
            info=info,
        )

    use_stationary = ps["StationaryTime_s"].notna().any()
    val_col = "StationaryTime_s" if use_stationary else "PitLaneTime_s"
    best = ps.loc[ps[val_col].idxmin()]
    _best_lap = (f" (L{int(best['LapNo'])})"
                 if pd.notna(best.get("LapNo")) else "")
    kpis = dbc.Row([
        kpi("FASTEST STOP",
            f"{best[val_col]:.1f}s · {best['Driver_Short']}{_best_lap}",
            "#00D2BE",
            tooltip="Quickest single stop of the race on the measured metric "
                    "(stationary time when available, pit-lane time otherwise)."),
        kpi("MEDIAN STATIONARY",
            f"{ps['StationaryTime_s'].median():.1f}s"
            if use_stationary else "n/a",
            tooltip="Field-wide median time stationary in the box — the "
                    "pit-crew component of a stop, excluding pit-lane transit."),
        kpi("MEDIAN PIT-LANE TIME",
            f"{ps['PitLaneTime_s'].median():.1f}s"
            if ps["PitLaneTime_s"].notna().any() else "n/a",
            "#FF8700",
            tooltip="Field-wide median pit-entry-to-pit-exit time. The "
                    "strategy simulator's pit loss is larger: it also counts "
                    "the slow in/out laps."),
        kpi("TOTAL STOPS", f"{len(ps)}", "#808080",
            tooltip="Number of recorded stops in this race (after the "
                    "sidebar Driver/Team filter)."),
    ])
    fig = _pitstops_fig(ps, "", use_stationary)
    src = ps["source"].iloc[0]
    note = html.P(
        ("Source: F1 live-timing PitStopSeries (true stationary times)."
         if src == "livetiming" else
         "Source: Jolpica archive — pit-lane duration only (stationary "
         "times aren't recorded there)."),
        style={"color": TEXT_DIM, "fontSize": "0.72rem", "marginBottom": "4px"},
    )
    _where = "stationary in the box" if use_stationary else "through the pit lane"
    _pit_plain = (
        "A pit stop is where the crew swaps all four tyres in seconds. The "
        f"quickest here was {best['Driver_Short']}'s at {best[val_col]:.1f}s "
        f"({_where}). Even a perfect stop costs a car around 20 seconds of race "
        "time in all, so when to stop is a big strategic call.")
    return card([*gloss("pit stop", "Pit Stop"), " Performance"],
                html.Div([kpis, dcc.Graph(figure=fig, config=GFX), note]),
                info=info, plain=_pit_plain)


# ── Lap-1 & restart analysis ──────────────────────────────────
_SC_FLAGS = {"SafetyCar", "VSC", "VSCEnding"}


def _start_restart_stats(rl: pd.DataFrame) -> tuple[pd.DataFrame, list[int]]:
    """Per driver: positions gained on lap 1 (grid → end of L1) and summed
    across SC/VSC restarts. Restart lap = first green lap after a lap where
    at least half the field ran under SC/VSC."""
    need = {"Driver_Short", "LapNo", "Position"}
    if rl.empty or not need.issubset(rl.columns):
        return pd.DataFrame(), []
    pos = (rl.dropna(subset=["Position"])
           .set_index(["Driver_Short", "LapNo"])["Position"]
           .groupby(level=[0, 1]).first())

    # field-level SC laps
    restarts: list[int] = []
    if "TrackStatus_Flag" in rl.columns:
        under = (rl.groupby("LapNo")["TrackStatus_Flag"]
                 .agg(lambda s: (s.isin(_SC_FLAGS)).mean() >= 0.5))
        sc_laps = set(under[under].index.astype(int))
        restarts = sorted(int(l) + 1 for l in sc_laps
                          if (l + 1) not in sc_laps
                          and (l + 1) <= int(rl["LapNo"].max()))

    rows = []
    for drv, g in rl.groupby("Driver_Short"):
        grid = pd.to_numeric(g.get("Grid_Position"), errors="coerce").dropna()
        grid = float(grid.iloc[0]) if len(grid) else np.nan
        p1 = pos.get((drv, 1), np.nan)
        start_gain = (grid - p1) if np.isfinite(grid) and pd.notna(p1) else np.nan
        r_gain, r_n = 0.0, 0
        for r in restarts:
            a, b = pos.get((drv, r - 1), np.nan), pos.get((drv, r), np.nan)
            if pd.notna(a) and pd.notna(b):
                r_gain += float(a - b)
                r_n += 1
        rows.append({"driver": drv, "team": g["Team"].iloc[0],
                     "grid": grid, "p1": p1,
                     "start_gain": start_gain,
                     "restart_gain": r_gain if r_n else np.nan,
                     "n_restarts": r_n})
    df = pd.DataFrame(rows).dropna(subset=["start_gain"])
    return df.sort_values("start_gain", ascending=False), restarts


def _lap1_plain(st: pd.DataFrame):
    """Beginner reading of the lap-1 chart: who gained most off the line."""
    if st is None or st.empty or "start_gain" not in st.columns:
        return None
    lead = ("The start is a race in itself — cars launch from a standstill and "
            "scrap for position into the first corner.")
    top = st.sort_values("start_gain", ascending=False).iloc[0]
    g = top["start_gain"]
    if pd.isna(g) or g <= 0:
        return lead + " Here the field mostly held station off the line."
    n = int(round(g))
    return (lead + f" {top['driver']} gained the most here — up {n} "
            f"place{'s' if n != 1 else ''} by the end of lap 1.")


def _strategy_plain(rl: pd.DataFrame):
    """Beginner reading of the tyre-strategy chart: why cars pit + the most
    common number of stops."""
    base = ("In a dry race a driver must use at least two of the three dry tyre "
            "types, so everyone pits at least once. Softer tyres are quicker but "
            "wear out sooner; harder ones last longer — so teams trade lap-time "
            "against pit-stop time.")
    if rl is None or rl.empty or not {"Driver_Short", "Stint"}.issubset(rl.columns):
        return base
    st = (rl.dropna(subset=["Driver_Short", "Stint"])
          .groupby("Driver_Short")["Stint"].nunique())
    if st.empty:
        return base
    stops = (st - 1).clip(lower=0)
    m = stops.mode()
    common = int(m.iloc[0]) if not m.empty else int(round(stops.median()))
    if common <= 0:
        return base
    words = {1: "a one", 2: "a two", 3: "a three", 4: "a four"}
    w = words.get(common, f"a {common}")
    plural = "" if common == 1 else "s"
    return base + f" Most drivers here ran {w}-stop race ({common} pit stop{plural})."


def _start_restart_fig(st: pd.DataFrame, restarts: list[int]) -> go.Figure:
    fig = go.Figure()
    has_restarts = bool(restarts) and st["restart_gain"].notna().any()
    fig.add_trace(go.Bar(
        x=st["driver"], y=st["start_gain"], name="Lap 1",
        marker_color=[TEAM_COLORS.get(t, "#808080") for t in st["team"]],
        customdata=np.stack([st["grid"], st["p1"]], axis=-1),
        hovertemplate=("<b>%{x}</b> · lap 1: %{y:+.0f}<br>"
                       "P%{customdata[0]:.0f} on the grid → "
                       "P%{customdata[1]:.0f} after lap 1<extra></extra>"),
    ))
    if has_restarts:
        fig.add_trace(go.Bar(
            x=st["driver"], y=st["restart_gain"],
            name=f"SC/VSC restarts (lap {', '.join(map(str, restarts))})",
            marker_color=[_hex_to_rgba(TEAM_COLORS.get(t, "#808080"), 0.45)
                          for t in st["team"]],
            hovertemplate=("<b>%{x}</b> · restarts combined: %{y:+.0f}"
                           "<extra></extra>"),
        ))
    fig.add_hline(y=0, line=dict(color="white", width=1, dash="dash"))
    theme(fig, 420)
    fig.update_yaxes(title_text="Positions gained (+) / lost (−)")
    fig.update_layout(barmode="group",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0))
    return fig


# ── Race-control "radio" message timeline ─────────────────────
# F1 publishes no transcribed team-radio text (only audio clips), so the
# closest exploitable per-driver message stream is the FIA race-control
# feed: penalties, investigations, track-limit deletions and blue flags,
# each driver-tagged via "CAR NN (XXX)" in the message text. These are
# laid out as a swimlane timeline (one lane per driver + a TRACK lane for
# field-wide messages) on the race's lap axis.

_RC_ABBR_RE = re.compile(r"\(([A-Z]{3})\)")
_RC_CAR_RE  = re.compile(r"CAR \d+")

# message type → (label, colour, marker symbol)
_RC_TYPES: dict[str, tuple] = {
    "penalty":       ("Penalty",        "#E10600", "x"),
    "investigation": ("Investigation",  "#F59E0B", "diamond"),
    "track_limits":  ("Track limits",   "#A855F7", "circle-open"),
    "blue_flag":     ("Blue flag",      "#3B82F6", "triangle-up"),
    "safety_car":    ("Safety car/VSC", "#FBBF24", "square"),
    "drs":           ("DRS",            "#22D3EE", "star"),
    "flag":          ("Other flag",     "#34D399", "triangle-down"),
    "other":         ("Other",          "#9CA3AF", "circle"),
}


def _classify_rc(category: str, message: str, flag) -> str:
    """Map a race-control row to one of the _RC_TYPES keys."""
    msg = (message or "").upper()
    cat = (category or "")
    if "PENALTY" in msg:
        return "penalty"
    if any(k in msg for k in ("NOTED", "UNDER INVESTIGATION", "REVIEWED", "STEWARDS")):
        return "investigation"
    if "TRACK LIMITS" in msg or ("DELETED" in msg and "TIME" in msg):
        return "track_limits"
    if cat == "SafetyCar" or "SAFETY CAR" in msg or "VIRTUAL SAFETY" in msg:
        return "safety_car"
    if cat == "Drs" or "DRS" in msg:
        return "drs"
    if (flag and str(flag).upper() == "BLUE") or "BLUE FLAG" in msg:
        return "blue_flag"
    if cat == "Flag":
        return "flag"
    return "other"


def _prep_rc_messages(rc: pd.DataFrame) -> pd.DataFrame:
    """Annotate a race-control frame with driver code (or 'TRACK'), message
    type and a readable clock time. Returns a copy ready for plotting."""
    if rc is None or rc.empty:
        return pd.DataFrame()
    df = rc.copy()
    df["Lap"] = pd.to_numeric(df.get("Lap"), errors="coerce")

    # Driver code: prefer the (XXX) abbreviation in the text, else the
    # RacingNumber mapped through the driver table, else TRACK (field-wide).
    abbr = df["Message"].astype(str).str.extract(_RC_ABBR_RE)[0]
    num_to_code = {}
    try:
        num_to_code = (laps.dropna(subset=["DriverNo", "Driver_Short"])
                       .astype({"DriverNo": str})
                       .drop_duplicates("DriverNo")
                       .set_index("DriverNo")["Driver_Short"].to_dict())
    except Exception:
        pass
    by_num = df.get("RacingNumber").astype("string").map(num_to_code) \
        if "RacingNumber" in df.columns else pd.Series(index=df.index, dtype="object")
    df["Code"] = abbr.fillna(by_num).fillna("TRACK")

    df["Type"] = [
        _classify_rc(c, m, f)
        for c, m, f in zip(df.get("Category"), df.get("Message"), df.get("Flag"))
    ]
    if "Time" in df.columns:
        t = pd.to_datetime(df["Time"], errors="coerce")
        df["Clock"] = t.dt.strftime("%H:%M:%S").fillna("")
    else:
        df["Clock"] = ""
    return df.dropna(subset=["Lap"])


def _rc_driver_options(rc: pd.DataFrame, season=None) -> list[str]:
    """Driver codes (excluding TRACK) that have at least one message. Ordered
    by championship points when `season` is given, else by message count."""
    df = _prep_rc_messages(rc)
    if df.empty:
        return []
    codes = df[df["Code"] != "TRACK"]["Code"].value_counts().index.tolist()
    return _order_by_champ(codes, season) if season is not None else codes


def _radio_timeline_fig(rc: pd.DataFrame, selected_codes: list[str],
                        title: str, height: int = 560) -> go.Figure:
    """Swimlane timeline of race-control messages: one lane per selected
    driver plus a TRACK lane for field-wide messages, markers placed on the
    lap axis and coloured by message type, full text on hover."""
    fig = go.Figure()
    df = _prep_rc_messages(rc)
    if df.empty:
        theme(fig, height, title)
        fig.add_annotation(text="No race-control messages available for this race.",
                           xref="paper", yref="paper", x=0.5, y=0.5,
                           showarrow=False, font=dict(color=TEXT_DIM, size=13))
        return fig

    selected_codes = selected_codes or []
    # Lanes (bottom→top): TRACK at the bottom, then drivers with the
    # championship leader on top. selected_codes arrives leader-first, so the
    # driver list is reversed to put index 0 (leader) at the highest lane.
    drivers = [c for c in selected_codes if c != "TRACK"]
    lanes = ["TRACK"] + list(reversed(drivers))
    keep = df[df["Code"].isin(lanes)].copy()
    lane_idx = {code: i for i, code in enumerate(lanes)}
    keep["y"] = keep["Code"].map(lane_idx)

    # Spread markers that share a lane+lap so they don't fully overlap.
    keep = keep.sort_values(["y", "Lap", "Clock"])
    keep["x"] = keep["Lap"].astype(float)
    for (_, _), grp in keep.groupby(["y", "Lap"]):
        n = len(grp)
        if n > 1:
            offs = np.linspace(-0.28, 0.28, n)
            keep.loc[grp.index, "x"] = grp["Lap"].astype(float).values + offs

    n_laps = int(df["Lap"].max())
    for tkey, (label, colour, symbol) in _RC_TYPES.items():
        sub = keep[keep["Type"] == tkey]
        if sub.empty:
            continue
        wrapped = sub["Message"].astype(str).str.replace(
            r"(.{60}\S*)\s", r"\1<br>", regex=True)
        fig.add_trace(go.Scatter(
            x=sub["x"], y=sub["y"], mode="markers", name=label,
            marker=dict(size=11, color=colour, symbol=symbol,
                        line=dict(width=1, color="#0B0B18")),
            customdata=np.stack([sub["Code"], sub["Clock"],
                                 sub["Lap"].astype(int), wrapped], axis=-1),
            hovertemplate=("<b>%{customdata[0]}</b> · Lap %{customdata[2]}"
                           " · %{customdata[1]}<br>%{customdata[3]}<extra>"
                           + label + "</extra>"),
        ))

    theme(fig, height, title)
    fig.update_layout(
        xaxis=dict(title="Lap", range=[-1, n_laps + 2],
                   gridcolor=GRID_CLR, zeroline=False),
        yaxis=dict(tickmode="array",
                   tickvals=list(lane_idx.values()),
                   ticktext=["TRACK (field-wide)" if c == "TRACK" else c
                             for c in lanes],
                   range=[-0.6, len(lanes) - 0.4],
                   gridcolor=GRID_CLR, zeroline=False),
        legend=dict(orientation="h", yanchor="top", y=-0.12,
                    xanchor="center", x=0.5),
        margin=dict(l=120, r=30, t=50, b=90),
    )
    # Faint band behind the TRACK lane to set it apart from driver lanes.
    fig.add_hrect(y0=-0.5, y1=0.5, fillcolor="rgba(255,255,255,0.04)",
                  line_width=0, layer="below")
    return fig


# ── Transcribed team-radio: figure + table ────────────────────
# Actual driver/pit-wall radio, downloaded from the F1 live-timing archive
# and transcribed locally (see radio_loader.py). Time-stamped (not lap-tagged),
# so this is a clock-time swimlane: one lane per driver, the transcript on
# hover, and a table below with inline audio players.

def _code_team(code: str) -> str:
    try:
        m = laps.loc[laps["Driver_Short"] == code, "Team"]
        return m.iloc[0] if len(m) else ""
    except Exception:
        return ""


def _radio_text_col(mode: str) -> str:
    """Which transcript column to display: reviewed (corrected) vs raw."""
    return "Transcript_raw" if str(mode) == "raw" else "Transcript"


def _attach_radio_laps(rdf: pd.DataFrame, rl: pd.DataFrame) -> pd.DataFrame:
    """Map each clip's UTC timestamp to the driver's race lap (RadioLap
    column). Laps carry LapStartDate (UTC wall clock); a clip belongs to the
    last lap that started before it. Clips before the race or more than 90 s
    after a driver's final lap ended stay unmapped (formation grid chatter /
    in-lap congratulations)."""
    if (rdf is None or rdf.empty or rl is None or rl.empty
            or "LapStartDate" not in rl.columns):
        return rdf
    rdf = rdf.copy()
    rdf["RadioLap"] = np.nan
    for drv, g in rl.dropna(subset=["LapStartDate"]).groupby("Driver_Short"):
        g = g.sort_values("LapStartDate")
        starts = pd.to_datetime(g["LapStartDate"]).to_numpy()
        lapnos = g["LapNo"].to_numpy()
        durs   = pd.to_numeric(g["LapTime_s"], errors="coerce").to_numpy()
        m = rdf["Driver_Short"] == drv
        if not m.any():
            continue
        utcs = pd.to_datetime(rdf.loc[m, "Utc"]).to_numpy()
        idx = np.searchsorted(starts, utcs, side="right") - 1
        laps_out = np.full(len(utcs), np.nan)
        for i, j in enumerate(idx):
            if j < 0:
                continue
            end = starts[j] + np.timedelta64(
                int((durs[j] if np.isfinite(durs[j]) else 120) + 90), "s")
            if utcs[i] <= end:
                laps_out[i] = lapnos[j]
        rdf.loc[m, "RadioLap"] = laps_out
    return rdf


def _add_radio_markers(fig: go.Figure, rl: pd.DataFrame,
                       rdf: pd.DataFrame) -> None:
    """Overlay transcribed-radio markers on the position chart: one star per
    clip at (lap, driver's position that lap), transcript + topics on hover.
    Toggleable via the legend."""
    if rdf is None or rdf.empty or "RadioLap" not in rdf.columns:
        return
    d = rdf.dropna(subset=["RadioLap"])
    if d.empty:
        return
    pos = (rl.dropna(subset=["Position"])
           .set_index(["Driver_Short", "LapNo"])["Position"])
    xs, ys, hover, colors = [], [], [], []
    for r in d.itertuples():
        lap = int(r.RadioLap)
        p = pos.get((r.Driver_Short, lap))
        if p is None or (isinstance(p, pd.Series) and p.empty):
            continue
        p = float(p.iloc[0]) if isinstance(p, pd.Series) else float(p)
        xs.append(lap); ys.append(p)
        topics = getattr(r, "Topics", "") or ""
        txt = re.sub(r"(.{60}\S*)\s", r"\1<br>", str(r.Transcript or ""))
        hover.append(f"<b>{r.Driver_Short}</b> · L{lap} · {r.Clock}"
                     + (f"<br><i>{topics}</i>" if topics else "")
                     + f"<br>{txt or '(no speech detected)'}")
        first_topic = topics.split(", ")[0] if topics else ""
        colors.append(_TOPIC_COLORS.get(first_topic, "#DDDDDD"))
    if not xs:
        return
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers", name="📻 radio",
        marker=dict(symbol="star", size=10, color=colors,
                    line=dict(width=1, color="#0B0B18")),
        customdata=hover,
        hovertemplate="%{customdata}<extra>radio</extra>",
    ))


# Topic tags come from radio_loader.tag_topics (keyword rules on the
# transcript). One colour per topic, used for the table badges.
_TOPIC_COLORS = {
    "PIT CALL":        "#E10600",
    "TYRES":           "#FFD700",
    "WEATHER":         "#4DA3FF",
    "TRAFFIC / FLAGS": "#FF8700",
    "ENERGY / MODE":   "#00D2BE",
    "STRATEGY":        "#B07CFF",
    "CAR / DAMAGE":    "#FF5C8A",
}


def _radio_row_topics(val) -> list[str]:
    return [t for t in str(val or "").split(", ") if t]


def _filter_radio_topics(df: pd.DataFrame, topics) -> pd.DataFrame:
    """Keep clips carrying at least one selected topic (empty selection =
    no topic filter)."""
    sel = [t for t in (topics or []) if t]
    if not sel or "Topics" not in df.columns:
        return df
    mask = df["Topics"].map(
        lambda v: any(t in _radio_row_topics(v) for t in sel))
    return df[mask]


def _topic_badges(val) -> html.Span:
    spans = []
    for t in _radio_row_topics(val):
        spans.append(html.Span(t, style={
            "background": _TOPIC_COLORS.get(t, "#555") + "33",
            "color": _TOPIC_COLORS.get(t, "#AAA"),
            "border": f"1px solid {_TOPIC_COLORS.get(t, '#555')}66",
            "borderRadius": "4px", "padding": "1px 6px",
            "fontSize": "0.62rem", "fontWeight": "700",
            "letterSpacing": "0.5px", "marginRight": "4px",
            "whiteSpace": "nowrap", "display": "inline-block",
            "marginBottom": "2px",
        }))
    return html.Span(spans)


def _team_radio_fig(rdf: pd.DataFrame, selected_codes: list[str],
                    title: str, height: int = 520, mode: str = "reviewed",
                    season=None, topics=None) -> go.Figure:
    fig = go.Figure()
    if rdf is None or rdf.empty:
        theme(fig, height, title)
        fig.add_annotation(text="No transcribed race radio.", xref="paper",
                           yref="paper", x=0.5, y=0.5, showarrow=False,
                           font=dict(color=TEXT_DIM, size=13))
        return fig
    sel = [c for c in (selected_codes or []) if c]
    df = rdf[rdf["Driver_Short"].isin(sel)].copy() if sel else rdf.copy()
    df = _filter_radio_topics(df, topics)
    if df.empty:
        theme(fig, height, title)
        fig.add_annotation(text="No radio matches the selected drivers / topics.",
                           xref="paper", yref="paper", x=0.5, y=0.5,
                           showarrow=False, font=dict(color=TEXT_DIM, size=13))
        return fig

    # Lanes ordered by championship points, leader at the top.
    ordered = _order_by_champ(list(df["Driver_Short"].unique()), season)
    lanes = list(reversed(ordered))            # bottom→top: leader on top
    lane_idx = {c: i for i, c in enumerate(lanes)}
    df["y"] = df["Driver_Short"].map(lane_idx)
    col = _radio_text_col(mode)
    wrapped = df[col].fillna("").astype(str).str.replace(
        r"(.{55}\S*)\s", r"\1<br>", regex=True).replace("", "(no speech detected)")

    for code in lanes:
        sub = df[df["Driver_Short"] == code]
        clr = TEAM_COLORS.get(_code_team(code), ACCENT)
        fig.add_trace(go.Scatter(
            x=sub["Utc"], y=sub["y"], mode="markers", name=code,
            marker=dict(size=12, color=clr, symbol="circle",
                        line=dict(width=1, color="#0B0B18")),
            customdata=np.stack([sub["Driver_Short"], sub["Clock"],
                                 wrapped.loc[sub.index]], axis=-1),
            hovertemplate=("<b>%{customdata[0]}</b> · %{customdata[1]}<br>"
                           "%{customdata[2]}<extra></extra>"),
            showlegend=False,
        ))

    theme(fig, height, title)
    fig.update_layout(
        xaxis=dict(title="Time (UTC)", gridcolor=GRID_CLR, zeroline=False),
        yaxis=dict(tickmode="array", tickvals=list(lane_idx.values()),
                   ticktext=lanes, range=[-0.6, len(lanes) - 0.4],
                   gridcolor=GRID_CLR, zeroline=False),
        margin=dict(l=70, r=30, t=50, b=50),
    )
    return fig


def _team_radio_table(rdf: pd.DataFrame, selected_codes: list[str],
                      mode: str = "reviewed", topics=None):
    """Chronological clip list: time, driver, inline audio player, topic
    badges, transcript."""
    sel = [c for c in (selected_codes or []) if c]
    df = rdf[rdf["Driver_Short"].isin(sel)] if sel else rdf
    df = _filter_radio_topics(df, topics)
    df = df.sort_values("Utc")
    col = _radio_text_col(mode)
    if df.empty:
        return html.P("No radio matches the selected drivers / topics.",
                      style={"color": TEXT_DIM, "fontSize": "0.82rem"})
    hdr = html.Tr([html.Th(h, style={"padding": "6px 10px", "color": ACCENT,
                                      "textAlign": "left", "position": "sticky",
                                      "top": 0, "background": "#09091A"})
                   for h in ("", "Time", "Lap", "Driver", "Audio", "Topics", "Transcript")])
    rows = []
    for _, r in df.iterrows():
        clr = TEAM_COLORS.get(_code_team(r["Driver_Short"]), ACCENT)
        txt = (r.get(col) or "").strip() or "(no speech detected)"
        is_reviewed = bool(r.get("reviewed", False))
        badge = tip("✓" if is_reviewed else "•",
                    ("Reviewed — transcript checked/corrected"
                     if is_reviewed else "Not yet reviewed (raw transcript)"),
                    style={"color": ("#34D399" if is_reviewed else TEXT_DIM),
                           "fontWeight": "800", "cursor": "help"})
        rows.append(html.Tr([
            html.Td(badge, style={"padding": "6px 4px 6px 10px", "textAlign": "center"}),
            html.Td(r["Clock"], style={"padding": "6px 10px", "color": TEXT_DIM,
                                       "whiteSpace": "nowrap", "fontVariantNumeric": "tabular-nums"}),
            html.Td(f"L{int(r['RadioLap'])}" if pd.notna(r.get("RadioLap")) else "—",
                    style={"padding": "6px 10px", "color": TEXT_DIM,
                           "whiteSpace": "nowrap",
                           "fontVariantNumeric": "tabular-nums"}),
            html.Td(r["Driver_Short"], style={"padding": "6px 10px",
                    "color": clr, "fontWeight": "700"}),
            html.Td(html.Audio(src=f"/radio/{r['Mp3']}", controls=True,
                               preload="none", style={"height": "30px", "width": "180px"}),
                    style={"padding": "4px 10px"}),
            html.Td(_topic_badges(r.get("Topics", "")),
                    style={"padding": "6px 10px", "maxWidth": "160px"}),
            html.Td(txt, style={"padding": "6px 10px", "color": TEXT_MAIN,
                                "fontSize": "0.82rem"}),
        ], style={"borderBottom": f"1px solid {GRID_CLR}"}))
    return html.Div(
        html.Table([html.Thead(hdr), html.Tbody(rows)],
                   style={"width": "100%", "borderCollapse": "collapse"}),
        style={"maxHeight": "420px", "overflowY": "auto"},
    )


def _team_radio_block(rdf: pd.DataFrame, meeting: str, year,
                      default_codes=None, season=None):
    """Driver selector + raw/reviewed toggle + timeline + table for an
    already-loaded radio frame. Driver lanes default to `default_codes`
    (the global-filtered grid) ordered by championship points."""
    season = season if season is not None else year
    all_codes = _order_by_champ(list(rdf["Driver_Short"].unique()), season)
    value = [c for c in all_codes if c in set(default_codes)] if default_codes else all_codes
    if not value:
        value = all_codes
    return html.Div([
        html.Div([
            html.P(f"{len(rdf)} race-radio clips transcribed · driver lanes default "
                   "to the sidebar filter (championship order). Adjust below:",
                   style={"color": TEXT_DIM, "fontSize": "0.78rem",
                          "marginBottom": "6px", "flex": "1 1 320px"}),
            dcc.RadioItems(
                id="radio-tr-mode",
                options=[{"label": " Reviewed", "value": "reviewed"},
                         {"label": " Raw", "value": "raw"}],
                value="reviewed", inline=True,
                inputStyle={"marginRight": "4px", "marginLeft": "12px"},
                style={"color": TEXT_DIM, "fontSize": "0.78rem",
                       "whiteSpace": "nowrap"},
            ),
        ], style={"display": "flex", "alignItems": "center",
                  "justifyContent": "space-between", "flexWrap": "wrap"}),
        dcc.Dropdown(id="radio-tr-select",
                     options=[{"label": c, "value": c} for c in all_codes],
                     value=value, multi=True, placeholder="Pick drivers…",
                     style={"backgroundColor": "#111", "fontSize": "0.8rem",
                            "marginBottom": "6px"}),
        dcc.Dropdown(id="radio-tr-topics",
                     options=[{"label": t, "value": t}
                              for t in _TOPIC_COLORS
                              if any(t in _radio_row_topics(v)
                                     for v in rdf.get("Topics", []))],
                     value=[], multi=True,
                     placeholder="Filter by topic (pit calls, tyres, weather…) — empty = all",
                     style={"backgroundColor": "#111", "fontSize": "0.8rem",
                            "marginBottom": "10px"}),
        dcc.Graph(id="radio-tr-graph",
                  figure=_team_radio_fig(rdf, value, "",
                                         mode="reviewed", season=season),
                  config=GFX),
        html.Div(_team_radio_table(rdf, value, mode="reviewed"),
                 id="radio-tr-table"),
    ])


def _section_header(title: str, subtitle: str) -> html.Div:
    """Big centred divider between the tab's major sections (mirrors the
    SEASON tab's section headers so the app reads consistently)."""
    return html.Div([
        html.H3(title, style={
            "color": TEXT_MAIN, "fontWeight": "900", "letterSpacing": "3px",
            "textAlign": "center", "fontSize": "1.4rem",
            "borderBottom": f"2px solid {ACCENT}",
            "paddingBottom": "8px", "marginBottom": "4px"}),
        html.P(subtitle, style={"color": TEXT_DIM, "fontSize": "0.78rem",
                                "textAlign": "center",
                                "marginBottom": "18px"}),
    ], style={"marginTop": "26px"})


def tab_race(sel_drivers=None, sel_teams=None):
    cur = LOADED_SESSION_INFO[0] if LOADED_SESSION_INFO else None
    if not cur:
        return html.P("No meeting loaded — pick a session in the Data tab.",
                      style={"color": TEXT_DIM})

    season  = int(cur["SEASON"])
    meeting = cur["MEETING"]
    data    = _resolve_race_data(season, meeting)

    if data is None:
        return html.Div([
            html.H3(f"{meeting}", style={"color": TEXT_MAIN, "fontWeight": "800"}),
            html.P(
                f"No race data is available for {meeting} in {season} or {season - 1} "
                "(neither cached locally nor fetchable). Load the race in the Data tab.",
                style={"color": TEXT_DIM, "fontSize": "0.9rem"},
            ),
        ])

    rl          = data["laps"]
    shown_year  = data["season"]
    is_fallback = shown_year != season

    # ── Sidebar filters: only Driver and Team apply to the Race tab ──
    # Apply a filter only when the user has actually narrowed it. A full
    # selection is treated as "no filter" so a fallback season (whose team
    # names / line-up may differ from the loaded one) still shows the whole
    # grid instead of silently dropping drivers on stale team names.
    if sel_teams and set(sel_teams) != set(TEAMS):
        rl = rl[rl["Team"].isin(sel_teams)]
    if sel_drivers and set(sel_drivers) != set(DRIVERS):
        rl = rl[rl["Driver_Short"].isin(sel_drivers)]

    # ── Year banner (makes the displayed season unmistakable) ──
    banner_bits = [
        html.Span("RACE", style={
            "background": ACCENT, "color": "#fff", "borderRadius": "4px",
            "padding": "3px 10px", "fontWeight": "800", "letterSpacing": "2px",
            "fontSize": "0.8rem", "marginRight": "12px",
        }),
        html.Span(f"{meeting}", style={
            "color": TEXT_MAIN, "fontWeight": "800", "fontSize": "1.15rem",
            "marginRight": "10px",
        }),
        html.Span(str(shown_year), style={
            "color": "#fff", "background": "#005AFF" if not is_fallback else "#B8860B",
            "borderRadius": "4px", "padding": "3px 12px", "fontWeight": "800",
            "fontSize": "1.0rem", "letterSpacing": "1px",
        }),
    ]
    if is_fallback:
        banner_bits.append(html.Span(
            f"  ⚠  {season} race not available yet — showing {shown_year} data",
            style={"color": "#E0B040", "fontSize": "0.8rem", "marginLeft": "12px",
                   "fontStyle": "italic"},
        ))
    banner = html.Div(
        banner_bits,
        style={"display": "flex", "alignItems": "center", "flexWrap": "wrap",
               "padding": "12px 16px", "marginBottom": "18px",
               "background": CARD_BG, "border": f"1px solid {GRID_CLR}",
               "borderLeft": f"4px solid {ACCENT}", "borderRadius": "8px"},
    )

    if rl.empty:
        return html.Div([
            banner,
            html.P("No race laps match the current Driver / Team filter "
                   "(note: a fallback season may have a different line-up).",
                   style={"color": TEXT_DIM, "fontSize": "0.9rem"}),
        ])

    evo_fig = _lap_evolution_fig(rl, "")
    pos_fig = _position_changes_fig(rl, "")
    start_stats, restart_laps = _start_restart_stats(rl)
    trace_fig = _race_trace_fig(rl, "")
    strat_fig = _tyre_strategy_chart(rl, title="", already_race=True)
    uc_pairs = _undercut_pairs(rl)
    uc_fig   = _undercut_fig(uc_pairs, "")
    _sim_pitloss_default = _estimate_pit_loss(rl) or 22.0
    sim_controls = dbc.Row([
        dbc.Col([
            html.Label("PIT LOSS (s)",
                       style={"color": TEXT_DIM, "fontSize": "0.72rem",
                              "letterSpacing": "1px"}),
            dcc.Input(id="strat-sim-pitloss", type="number",
                      value=_sim_pitloss_default, min=5, max=60, step=0.5,
                      debounce=True,
                      style={"width": "100%", "background": "#111",
                             "color": TEXT_MAIN, "border": f"1px solid {GRID_CLR}",
                             "borderRadius": "4px", "padding": "4px 8px"}),
        ], md=2),
        dbc.Col([
            html.Label("STRATEGIES",
                       style={"color": TEXT_DIM, "fontSize": "0.72rem",
                              "letterSpacing": "1px"}),
            dcc.Checklist(
                id="strat-sim-stops",
                options=[{"label": " 1-stop", "value": 1},
                         {"label": " 2-stop", "value": 2}],
                value=[1, 2], inline=True,
                inputStyle={"marginRight": "4px", "accentColor": ACCENT},
                labelStyle={"marginRight": "16px", "color": TEXT_MAIN,
                            "fontSize": "0.8rem"},
            ),
        ], md=3),
        dbc.Col([
            html.Label("WHAT-IF: SC ON LAP",
                       style={"color": TEXT_DIM, "fontSize": "0.72rem",
                              "letterSpacing": "1px"}),
            dcc.Input(id="strat-sim-sclap", type="number",
                      value=None, min=2, step=1, debounce=True,
                      placeholder="none",
                      style={"width": "100%", "background": "#111",
                             "color": TEXT_MAIN, "border": f"1px solid {GRID_CLR}",
                             "borderRadius": "4px", "padding": "4px 8px"}),
        ], md=2),
        dbc.Col([
            html.Label("TRAFFIC",
                       style={"color": TEXT_DIM, "fontSize": "0.72rem",
                              "letterSpacing": "1px"}),
            dcc.Checklist(
                id="strat-sim-traffic",
                options=[{"label": " price rejoin traffic", "value": "on"}],
                value=["on"], inline=True,
                inputStyle={"marginRight": "4px", "accentColor": ACCENT},
                labelStyle={"color": TEXT_MAIN, "fontSize": "0.8rem"},
            ),
        ], md=3),
    ], className="mb-2")
    sim_card = card(
        "Strategy What-If Simulator",
        html.Div([
            sim_controls,
            dcc.Loading(html.Div(id="strat-sim-output",
                                 children=_strategy_sim_content(rl)),
                        type="default"),
        ]),
        info=("Data: a race model assembled from this race's own measurements "
              "— per-compound field degradation curves (extrapolated beyond "
              "the longest observed stint, marked ⚠), compound pace offsets, "
              "and the pit loss measured from actual stops (editable above). "
              "The optimizer grid-searches every legal 1- and 2-stop compound "
              "plan and its stop laps. Top chart: every plan ranked by time "
              "lost vs the optimum. Bottom chart: how much mistiming the "
              "first stop costs — a flat valley means a wide, forgiving pit "
              "window; the amber backdrop is how many cars a stop on that lap "
              "would drop you behind (from the race's real gap structure). "
              "The traffic toggle prices that in: each stop pays ~2 laps of "
              "the dirty-air penalty measured from this race per car in its "
              "rejoin window — automatically left off when following cost "
              "nothing here (slipstream tracks). The SC what-if control "
              "re-prices stops taken during a hypothetical Safety Car window "
              "(lap N to N+2) at 45% of the normal pit loss — watch the "
              "optimal plan flip when a cheap stop appears mid-race. Why: "
              "answers 'was the winning strategy actually optimal, and who "
              "was one Safety Car away from a different result?' using only "
              "what the tyres, and the traffic, really did that day."),
    )
    wx_fig = _weather_race_fig(rl, "")

    # ── Wet-race crossover (only shown for wet/transition races) ──
    wet = detect_wet_crossover(rl)
    wet_card = None
    if wet is not None and not wet["per_lap"]["delta"].dropna().empty:
        wet_card = card(
            "Wet-Race Crossover — Inters vs Slicks",
            html.Div([
                dcc.Graph(figure=_wet_crossover_fig(wet, ""), config=GFX),
                dcc.Graph(figure=_wet_switch_fig(
                    wet, "Switch timing vs the field crossover"),
                    config=GFX),
            ]),
            info=("Data: on every lap where cars ran BOTH intermediates and "
                  "slicks, the field's median lap time on each is compared — "
                  "their delta (top→bottom) crosses zero at the break-even "
                  "lap, marked in red (dotted = estimated when the overlap "
                  "window was one-sided). The lower chart shows how many laps "
                  "late or early each driver switched relative to that "
                  "crossover, and the field-median time that timing cost. "
                  "Why: in a drying or rain-hit race the whole result turns "
                  "on when you change tyres — this pins the optimal moment "
                  "from the cars themselves and grades every driver's call. "
                  "Caveats: medians include Safety-Car laps; only crossovers "
                  "where the field delta clears ~1s are flagged confident."),
        )

    # ── Race-control message timeline ("radio") ──────────────
    # Default: every driver with messages, ordered by championship points, and
    # narrowed to the sidebar Driver/Team filter (the same drivers visible in
    # `rl` above), so this card responds to the global filter.
    rc          = data.get("race_control", pd.DataFrame())
    rc_codes    = _rc_driver_options(rc, season=shown_year)
    visible     = set(rl["Driver_Short"].dropna().unique())
    rc_default  = [c for c in rc_codes if c in visible] or rc_codes
    radio_fig   = _radio_timeline_fig(rc, rc_default, "")
    radio_card = card(
        "Race-Control Message Timeline",
        html.Div([
            html.P("Driver lanes default to the sidebar filter, ordered by "
                   "championship points (the TRACK lane for field-wide messages "
                   "is always shown). Adjust the selection below:",
                   style={"color": TEXT_DIM, "fontSize": "0.78rem",
                          "marginBottom": "6px"}),
            dcc.Dropdown(
                id="radio-driver-select",
                options=[{"label": c, "value": c} for c in rc_codes],
                value=rc_default, multi=True,
                placeholder="Pick drivers…",
                style={"backgroundColor": "#111", "fontSize": "0.8rem",
                       "marginBottom": "10px"},
            ),
            dcc.Graph(id="radio-timeline-graph", figure=radio_fig, config=GFX),
        ]) if rc_codes else
        html.P("No driver-attributable race-control messages for this race.",
               style={"color": TEXT_DIM}),
        info=("Data: FIA race-control messages — penalties, stewards' "
              "investigations, track-limit lap deletions, blue flags, safety-car "
              "and DRS calls — placed on the race lap axis, one swimlane per "
              "driver plus a field-wide TRACK lane, coloured by message type with "
              "the full text on hover. (Actual driver team radio, transcribed, is in "
              "the Team Radio card below.) Why: see at a glance who was investigated, "
              "penalised or losing lap times, and exactly when in the race."),
    )

    # ── Transcribed team-radio card ──────────────────────────
    tr_info = ("Data: actual driver/pit-wall team radio, downloaded from the F1 "
               "live-timing archive and transcribed locally with faster-whisper. "
               "One clock-time swimlane per driver with the transcript on hover, "
               "plus a table of every clip with an inline audio player. Each clip "
               "is auto-tagged by topic (pit calls, tyres, weather, traffic, "
               "energy, strategy, car issues) from transcript keywords — use the "
               "topic filter to isolate e.g. every pit call. Note: F1 only keeps "
               "race-radio audio for recent events, so older races show nothing; "
               "transcription is automatic and not always perfect.")
    if radio_cached(season, meeting) or (is_fallback and radio_cached(shown_year, meeting)):
        ry  = shown_year if (is_fallback and radio_cached(shown_year, meeting)) else season
        rdf = load_race_radio(ry, meeting)        # instant (cached)
        # map clips to race laps only when the radio belongs to the shown
        # race (a fallback season's laps don't match this year's clips)
        if ry == shown_year:
            rdf = _attach_radio_laps(rdf, rl)
            _add_radio_markers(pos_fig, rl, rdf)
        tr_body = (_team_radio_block(rdf, meeting, ry,
                                     default_codes=visible, season=ry)
                   if not rdf.empty else
                   html.P("No race radio found for this meeting.",
                          style={"color": TEXT_DIM}))
    elif race_radio_available(season, meeting):
        tr_body = html.Div([
            html.P("Race radio is available for this meeting but not yet "
                   "transcribed. This downloads the clips and transcribes them "
                   "locally (about a minute the first time, then cached).",
                   style={"color": TEXT_DIM, "fontSize": "0.8rem"}),
            dbc.Button("Fetch & transcribe race radio", id="load-radio-btn",
                       color="danger", size="sm", n_clicks=0),
            dcc.Loading(html.Div(id="radio-tr-output"), type="default"),
        ])
    else:
        tr_body = html.P(
            "No team-radio audio is archived for this race (F1 only retains it "
            "for recent events).", style={"color": TEXT_DIM})
    team_radio_card = card("Team Radio (transcribed)", tr_body, info=tr_info)

    return html.Div([
        banner,
        _section_header(
            "WATCH IT BACK",
            "play the Grand Prix back — a full 2D/3D replay, then the entire "
            "field funnelling through the opening lap on one shared clock"),
        replay_card(shown_year, meeting,
                    codes=sorted(rl["Driver_Short"].dropna().unique())),
        race3d_card(shown_year, meeting),
        _section_header(
            "HOW THE RACE UNFOLDED",
            "the shape of the race from lights to flag — pace on every lap, "
            "the position battles, the start and restarts, the strategist's "
            "race trace, and how weather and rain moved the field's pace"),
        card(
            "Lap Time Evolution – All Laps (Race)",
            dcc.Graph(figure=evo_fig, config=GFX),
            info=("Data: every race lap (valid or not), one line per driver, markers "
                  "tinted by compound, with track-flag periods shaded behind (yellow / "
                  "SC / VSC / red). Why: the full story of the race — stint lengths, pit "
                  "stops, degradation and how interruptions reshaped the pace."),
        ),
        card(
            "Position Changes During the Race",
            dcc.Graph(figure=pos_fig, config=GFX),
            info=("Data: each driver's on-track position at every lap (grid slot shown "
                  "at lap 0), team-coloured with teammates split solid/dashed, driver "
                  "code labelled at the line end. The shaded band marks the points-paying "
                  "top 10; flag periods are banded behind. ★ stars are transcribed "
                  "team-radio clips placed at the lap they surfaced on the F1 feed, "
                  "coloured by topic — hover to read the call, toggle them via the "
                  "legend. (The feed publishes clips up to a lap or two after they "
                  "were actually spoken, so treat placement as approximate.) Why: "
                  "shows overtakes, pit-stop shuffles and Safety-Car bunching at a "
                  "glance, now with the pit-wall conversation on top."),
        ),
        card(
            "Lap 1 & Restarts",
            dcc.Graph(figure=_start_restart_fig(
                start_stats, restart_laps), config=GFX)
            if not start_stats.empty else
            html.P("No grid/position data for this race.",
                   style={"color": TEXT_DIM}),
            info=("Data: grid slot vs position at the end of lap 1 (solid "
                  "bars), plus positions gained across every SC/VSC restart "
                  "combined (faded bars — a restart is the first green lap "
                  "after the field ran under Safety Car). Why: launches and "
                  "restarts are a distinct driver skill the lap-time charts "
                  "never show — some drivers make their season in the first "
                  "500 metres, and a good restart is free overtaking."),
            plain=_lap1_plain(start_stats),
        ),
        card(
            "Race Trace",
            dcc.Graph(figure=trace_fig, config=GFX),
            info=("Data: each driver's cumulative race time compared against a "
                  "constant reference — the winner's average lap — so the vertical "
                  "axis is 'how far ahead/behind the winner's average schedule'. "
                  "Teammates split solid/dashed; flag periods banded behind. Why: "
                  "the classic strategist's chart. Line slope = relative pace "
                  "(rising = faster than the reference), a sudden drop = a pit "
                  "stop, converging lines = a battle for track position, and the "
                  "field bunching to a point = Safety Car. Undercuts and tyre "
                  "cliffs are visible as slope changes around the pit windows."),
        ),
        card(
            "Weather & Race Pace",
            dcc.Graph(figure=wx_fig, config=GFX)
            if wx_fig.data else
            html.P("No weather data available for this race.", style={"color": TEXT_DIM}),
            info=("Data: track and air temperature per lap (averaged across cars), "
                  "stacked above the field's median lap time, on a shared lap axis; "
                  "rain periods are shaded blue. Why: reading conditions straight down "
                  "onto pace shows how the weather shaped the race — a cooling track, "
                  "a rain shower or the grip swing that triggered the pit cascade."),
        ),
        *([wet_card] if wet_card is not None else []),
        _section_header(
            "STRATEGY & PIT STOPS",
            "who ran which tyres and when, how fast the crews worked, who won "
            "the pit-lane duels — and a what-if optimiser that re-runs the "
            "strategy from the race's own numbers"),
        card(
            "Race Tyre Strategy",
            html.Div([
                _allocation_chips(shown_year, meeting) or html.Div(),
                dcc.Graph(figure=strat_fig, config=GFX),
            ])
            if strat_fig.data else
            html.P("No stint data available for this race.", style={"color": TEXT_DIM}),
            info=("Data: each driver's stints, one bar split into compound-coloured "
                  "segments sized by stint length (laps), ordered by finishing position; "
                  "diamonds mark pit stops and show pit-lane time (s). The chip strip "
                  "above shows this event's Pirelli C-compound nomination (from "
                  "data/tyre_allocations.csv) — SOFT here is not the same tyre as SOFT "
                  "elsewhere. Why: the strategic shape of the race — who ran which "
                  "tyres, stint lengths and stop timing."),
            plain=_strategy_plain(rl),
        ),
        _pitstops_card(rl, meeting, shown_year),
        card(
            [*gloss("undercut", "Undercut"), " / ", *gloss("overcut", "Overcut"),
             " Duels"],
            dcc.Graph(figure=uc_fig, config=GFX),
            info=("Data: every pit-cycle duel — two cars within 15 s on track "
                  "whose stops fall within 5 laps of each other. The gap between "
                  "them is measured just before the first stop and again at the "
                  "end of the second stopper's out-lap; the bar is the time the "
                  "FIRST stopper gained (+) or lost (−) through the cycle, "
                  "coloured by the first stopper's team. ✓ marks a completed "
                  "on-track jump; duels run under yellow/SC/VSC are dimmed "
                  "(cheap SC stops distort the maths). Why: quantifies each "
                  "strategy call — who won the pit exchanges, and how powerful "
                  "the undercut actually was at this circuit (see the median in "
                  "the corner)."),
        ),
        sim_card,
        _section_header(
            "RADIO & RACE CONTROL",
            "everything said to and about the drivers — FIA race-control "
            "messages on the lap axis, and the actual transcribed team radio"),
        radio_card,
        team_radio_card,
    ])


# ── Team radio: fetch + transcribe on demand, then filter ─────
def _current_race_meeting():
    """(season_to_use, meeting) for the loaded meeting, preferring a cached
    radio season (handles the race tab's previous-season fallback)."""
    cur = LOADED_SESSION_INFO[0] if LOADED_SESSION_INFO else None
    if not cur:
        return None, None
    season, meeting = int(cur["SEASON"]), cur["MEETING"]
    if not radio_cached(season, meeting) and radio_cached(season - 1, meeting):
        season = season - 1
    return season, meeting


@callback(
    Output("radio-tr-output", "children"),
    Input("load-radio-btn", "n_clicks"),
    prevent_initial_call=True,
)
def fetch_team_radio(n_clicks):
    if not n_clicks:
        return no_update
    cur = LOADED_SESSION_INFO[0] if LOADED_SESSION_INFO else None
    if not cur:
        return html.P("No meeting loaded.", style={"color": TEXT_DIM})
    season, meeting = int(cur["SEASON"]), cur["MEETING"]
    try:
        rdf = load_race_radio(season, meeting)
    except Exception as exc:
        return dbc.Alert(f"Radio fetch/transcription failed: {exc}", color="danger")
    if rdf.empty:
        return html.P("No race radio could be retrieved for this meeting.",
                      style={"color": TEXT_DIM})
    return _team_radio_block(rdf, meeting, season, season=season)


@callback(
    Output("radio-tr-graph", "figure"),
    Output("radio-tr-table", "children"),
    Input("radio-tr-select", "value"),
    Input("radio-tr-mode", "value"),
    Input("radio-tr-topics", "value"),
    prevent_initial_call=True,
)
def filter_team_radio(selected_codes, mode, topics):
    season, meeting = _current_race_meeting()
    if not meeting or not radio_cached(season, meeting):
        return no_update, no_update
    rdf = load_race_radio(season, meeting)        # cached → instant
    data = _resolve_race_data(season, meeting)
    if data is not None and data.get("season") == season:
        rdf = _attach_radio_laps(rdf, data["laps"])
    ordered = _order_by_champ(selected_codes or [], season)
    mode = mode or "reviewed"
    fig = _team_radio_fig(rdf, ordered, "",
                          mode=mode, season=season, topics=topics)
    return fig, _team_radio_table(rdf, ordered, mode=mode, topics=topics)


# ── Strategy simulator: recompute on control change ──────────
@callback(
    Output("strat-sim-output", "children"),
    Input("strat-sim-pitloss", "value"),
    Input("strat-sim-stops", "value"),
    Input("strat-sim-sclap", "value"),
    Input("strat-sim-traffic", "value"),
    prevent_initial_call=True,
)
def update_strategy_sim(pit_loss, stops, sc_lap, traffic):
    cur = LOADED_SESSION_INFO[0] if LOADED_SESSION_INFO else None
    if not cur:
        return html.P("No meeting loaded.", style={"color": TEXT_DIM})
    data = _resolve_race_data(int(cur["SEASON"]), cur["MEETING"])
    if not data:
        return html.P("No race data available.", style={"color": TEXT_DIM})
    return _strategy_sim_content(
        data["laps"],
        pit_loss=pit_loss,
        stops=tuple(stops) if stops else (1, 2),
        sc_lap=sc_lap,
        traffic_on="on" in (traffic or []),
    )


# ── Race-control timeline: redraw on driver selection ─────────
@callback(
    Output("radio-timeline-graph", "figure"),
    Input("radio-driver-select", "value"),
)
def update_radio_timeline(selected_codes):
    cur = LOADED_SESSION_INFO[0] if LOADED_SESSION_INFO else None
    if not cur:
        return go.Figure()
    season  = int(cur["SEASON"])
    meeting = cur["MEETING"]
    data    = _resolve_race_data(season, meeting)
    if not data:
        return go.Figure()
    rc         = data.get("race_control", pd.DataFrame())
    shown_year = data.get("season", season)
    ordered    = _order_by_champ(selected_codes or [], shown_year)
    return _radio_timeline_fig(rc, ordered, "")


# Text colour that stays readable on each compound's bar colour.
_COMPOUND_TEXT = {"SOFT": "#FFFFFF", "MEDIUM": "#111111", "HARD": "#111111",
                  "INTER": "#FFFFFF", "WET": "#FFFFFF"}


def _pit_durations(race: pd.DataFrame, lap_col: str) -> dict:
    """Pit-lane time loss per (driver, stint-just-ended), in seconds.

    Uses the session-time stamps already normalised to seconds in the laps
    frame: PitIn lands on the in-lap, PitOut on the following out-lap, so the
    difference is the full pit-lane transit time (~20–30 s). Anomalies
    (red-flag stops, garage time) are filtered with a sanity bound.
    """
    if "PitIn" not in race.columns or "PitOut" not in race.columns:
        return {}
    out: dict = {}
    for drv, g in race.groupby("Driver_Short"):
        g = g.sort_values(lap_col).reset_index(drop=True)
        pit_out = g[g["PitOut"].notna()]
        for _, row in g[g["PitIn"].notna()].iterrows():
            nxt = pit_out[pit_out[lap_col] > row[lap_col]]
            if nxt.empty:
                continue
            dur = float(nxt.iloc[0]["PitOut"]) - float(row["PitIn"])
            if 0 < dur < 120:
                out[(drv, int(row["Stint"]))] = dur
    return out


def _tyre_strategy_chart(laps_df: pd.DataFrame, results: pd.DataFrame | None = None,
                         title: str = "Race Tyre Strategy",
                         already_race: bool = False) -> go.Figure:
    """Per-driver tyre strategy for a race: one horizontal bar per driver, split
    into stint segments coloured by compound and sized by stint length (laps),
    ordered by finishing position (P1 on top). Compound + lap count are printed
    inside wide segments, and each pit stop is marked at the stint boundary with
    its pit-lane time. Recreates the FastF1 'Tyre strategies during a race'
    example, dressed up to match the rest of the dashboard.

    Accepts either the in-memory enriched laps (with Driver_Short /
    Classified_Position) or raw cache-loaded race laps (with Driver / DriverNo),
    optionally with a *results* frame for the finishing order.
    """
    race = laps_df.copy()
    if not already_race and "session_name" in race.columns:
        race = race[race["session_name"].astype(str).str.startswith("Race_")].copy()
    if race.empty:
        return go.Figure()

    lap_col = "LapNo" if "LapNo" in race.columns else "LapNumber"

    # Driver short code: prefer the enriched column, else derive from "Driver".
    if "Driver_Short" not in race.columns or race["Driver_Short"].isna().all():
        race["Driver_Short"] = (race["Driver"].astype(str)
                                .str.split("-").str[0].str.strip())
    race = race.dropna(subset=["Driver_Short", "Stint", "Compound"])
    race = race[race["Driver_Short"].astype(str).str.len() > 0]
    if race.empty:
        return go.Figure()

    pit = _pit_durations(race, lap_col)

    # Stint length = number of laps per driver × stint × compound.
    seg = (race.groupby(["Driver_Short", "Stint", "Compound"])[lap_col]
              .count().reset_index().rename(columns={lap_col: "StintLength"}))
    seg["_stint"] = pd.to_numeric(seg["Stint"], errors="coerce")

    # Finishing order (P1 first); unclassified drivers fall to the bottom.
    if "Classified_Position" in race.columns and race["Classified_Position"].notna().any():
        order = (race.groupby("Driver_Short")["Classified_Position"].first()
                    .sort_values(na_position="last").index.tolist())
    elif (results is not None and not results.empty
          and {"Abbreviation", "ClassifiedPosition"}.issubset(results.columns)):
        res = results.copy()
        res["_p"] = pd.to_numeric(res["ClassifiedPosition"], errors="coerce")
        res["_abbr"] = res["Abbreviation"].astype(str).str.strip()
        pos = (res.dropna(subset=["_p"]).drop_duplicates("_abbr")
                  .set_index("_abbr")["_p"].to_dict())
        drivers = list(seg["Driver_Short"].unique())
        order = sorted(drivers, key=lambda d: (pos.get(d, 1e9), d))
    else:
        order = (race.groupby("Driver_Short")[lap_col].max()
                    .sort_values(ascending=False).index.tolist())

    fig = go.Figure()
    seen_comp: set = set()
    pit_x, pit_y, pit_txt, pit_hover = [], [], [], []   # pit-stop markers
    for drv in order:
        d = seg[seg["Driver_Short"] == drv].sort_values("_stint")
        left = 0
        n_stints = len(d)
        for i, (_, r) in enumerate(d.iterrows()):
            cmp = str(r["Compound"]).upper()
            length = int(r["StintLength"])
            stint_no = int(r["_stint"]) if pd.notna(r["_stint"]) else None
            clr = COMPOUND_COLORS.get(cmp, "#808080")
            # Compound + laps printed inside the bar when there's room.
            seg_text = f"{cmp[0]} · {length}" if length >= 4 else (
                cmp[0] if length >= 2 else "")
            fig.add_trace(go.Bar(
                y=[drv], x=[length], base=left, orientation="h",
                name=cmp, legendgroup=cmp, showlegend=(cmp not in seen_comp),
                marker=dict(color=clr, line=dict(color="#000", width=1)),
                text=[seg_text], textposition="inside", insidetextanchor="middle",
                textfont=dict(color=_COMPOUND_TEXT.get(cmp, "#111111"), size=10),
                hovertemplate=(f"<b>{drv}</b> · {cmp}<br>"
                               f"Laps {left + 1}–{left + length} "
                               f"({length} laps)<extra></extra>"),
            ))
            seen_comp.add(cmp)
            left += length
            # Pit stop at the end of this stint (not after the final stint).
            if stint_no is not None and i < n_stints - 1 and (drv, stint_no) in pit:
                dur = pit[(drv, stint_no)]
                pit_x.append(left)
                pit_y.append(drv)
                pit_txt.append(f"{dur:.1f}")
                pit_hover.append(f"<b>{drv}</b><br>Pit stop · lap {left}<br>"
                                 f"Pit-lane time: {dur:.1f} s<extra></extra>")

    # Pit-stop markers + times overlaid at the stint boundaries.
    if pit_x:
        fig.add_trace(go.Scatter(
            x=pit_x, y=pit_y, mode="markers+text",
            marker=dict(symbol="diamond", size=9, color="#FFFFFF",
                        line=dict(color="#111", width=1)),
            text=pit_txt, textposition="top center",
            textfont=dict(size=8, color=TEXT_DIM),
            hovertemplate=pit_hover, name="Pit stop", showlegend=True,
            cliponaxis=False,
        ))

    theme(fig, max(360, 26 * len(order) + 150), title)
    fig.update_layout(
        barmode="stack",
        xaxis_title="Lap Number",
        yaxis_title="",
        bargap=0.28,
        legend=dict(orientation="h", x=0, y=1.06, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=60, r=20, t=70, b=40),
        annotations=[dict(
            text="◆ pit stop · number = pit-lane time (s)",
            xref="paper", yref="paper", x=1, y=1.04, xanchor="right",
            showarrow=False, font=dict(size=9, color=TEXT_DIM),
        )],
    )
    fig.update_yaxes(autorange="reversed")     # P1 at the top
    fig.update_xaxes(rangemode="tozero")
    return fig
