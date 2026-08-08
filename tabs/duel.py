"""
DUEL tab — pick an attacker and a target: how does A beat B at this event?

The rest of the dashboard answers "who is fast?"; this tab answers the
question a race engineer on A's pit wall would ask on Thursday: given
everything we know, HOW does our driver finish ahead of that specific rival
on Sunday? It assembles, for one selected pair:

  · the verdict — P(A ahead) from the duel Monte Carlo (the BRIEF tab's
    forecaster re-run pairwise), decomposed channel by channel, plus the
    championship points swing this event is likely to produce
  · paths to victory — outqualify-and-convert, comeback, rival retirement
  · the head-to-head record from the results archive, overall and here
  · attack zones — corner-by-corner time delta between the two drivers'
    best laps, tagged with which corners feed a DRS zone
  · the mistake radar — per-corner error rates from the telemetry archive
    (compute_mistakes.py), where the target errs at this circuit, and who
    cracks under pressure
  · the strategy playbook — measured undercut power, SC likelihood, pit loss
  · chaos channels — lap-1 habits and team reliability

Default pair: the championship runner-up (attacker) vs the leader (target).
All analysis is for the event loaded in the DATA tab.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, dash_table, callback, Input, Output
import dash_bootstrap_components as dbc

import f1lib.state as state
from f1lib.components import (
    theme, card, kpi, GFX, TABLE_STYLE, abbr as _abbr,
    hex_to_rgba as _hex_to_rgba,
)
from f1lib.config import (
    TEAM_COLORS, ACCENT, CARD_BG, TEXT_MAIN, TEXT_DIM, GRID_CLR,
)
from f1lib.pace_model import PaceModel
from f1lib.race_forecast import RaceForecaster
import f1lib.duel as duel
from f1lib.circuits import circuit_id
from f1lib.mistakes import (
    load_corner_fractions, load_track_line,
    corner_features_for_session, aggregate_mistakes,
)
from f1lib.standings import (
    HIST_RACE, _loaded_meeting_season_round, _driver_standings_after_round,
)

logger = logging.getLogger(__name__)

state.register(globals())

_MODEL: PaceModel | None = None
_FORECASTER: RaceForecaster | None = None
_PRED_CACHE: dict = {}
_BODY_CACHE: dict = {}

# Last (attacker, target) rendered — the QUALI tab's 3D replay reads this to
# open as the pair's ghost duel, and app.py keys its QUALI memo on it.
LAST_PAIR: tuple[str, str] | None = None

_GOLD = "#FFD700"
_RED = "#E8002D"
_GREEN = "#00C04B"


def _model() -> PaceModel:
    global _MODEL
    if _MODEL is None:
        _MODEL = PaceModel()
    return _MODEL


def _forecaster() -> RaceForecaster | None:
    global _FORECASTER
    if _FORECASTER is None:
        try:
            _FORECASTER = RaceForecaster()
        except Exception:
            _FORECASTER = False
    return _FORECASTER or None


# ─────────────────────────────────────────────────────────────
# Context helpers
# ─────────────────────────────────────────────────────────────

def _event_context() -> dict | None:
    """(season, round, event, circuit ids) of the loaded meeting.

    `cid` is the physical-circuit id and is what every pooled-across-seasons
    lookup must use — `ck` (the slugified event name) cannot tell the Madring
    from Barcelona, or Sepang from Sakhir, because they share a race name.
    """
    season, rnd, event = _loaded_meeting_season_round()
    if season is None or not event:
        return None
    ck = None
    if not HIST_RACE.empty:
        sub = HIST_RACE[HIST_RACE["event_name"].astype(str).str.strip() == event]
        if not sub.empty:
            ck = str(sub["circuit_key"].iloc[0])
    return {"season": int(season), "round": rnd, "event": event,
            "ck": ck, "cid": circuit_id(event, season),
            "ck_fr": duel.circuit_key_fr(event, season)}


def _roster() -> pd.DataFrame:
    if state.laps is None or state.laps.empty:
        return pd.DataFrame(columns=["driver", "team"])
    return (state.laps.dropna(subset=["Driver_Short", "Team"])
            [["Driver_Short", "Team"]].drop_duplicates()
            .rename(columns={"Driver_Short": "driver", "Team": "team"}))


def _default_pair(ctx: dict, roster: pd.DataFrame) -> tuple[str | None, str | None]:
    """Championship runner-up (attacker) vs leader (target), restricted to the
    loaded roster; falls back to the two quickest loaded drivers."""
    st = _driver_standings_after_round(ctx["season"], ctx["round"])
    have = set(roster["driver"])
    ordered = [d for d, v in sorted(st.items(), key=lambda kv: -kv[1]["pts"])
               if d in have]
    if len(ordered) >= 2:
        return ordered[1], ordered[0]
    if len(have) >= 2:
        two = sorted(have)[:2]
        return two[0], two[1]
    return None, None


def _team_of(drv: str, roster: pd.DataFrame) -> str:
    m = roster[roster["driver"] == drv]
    return str(m["team"].iloc[0]) if not m.empty else ""


def _clr(team: str, alt: bool = False) -> str:
    base = TEAM_COLORS.get(team, "#808080")
    return _hex_to_rgba(base, 0.55) if alt else base


def _pair_colors(a, b, roster):
    ta, tb = _team_of(a, roster), _team_of(b, roster)
    ca, cb = _clr(ta), _clr(tb)
    if ta == tb:
        cb = _clr(tb, alt=True)
    return ta, tb, ca, cb


def _predictions(ctx: dict) -> dict | None:
    """Driver-level race/quali predictions + the actual grid when loaded.
    Cached per (event, data generation)."""
    key = (ctx["season"], ctx["event"], state.DATA_GENERATION)
    if key in _PRED_CACHE:
        return _PRED_CACHE[key]
    out = None
    try:
        # Same quali-informed update as the BRIEF tab: once qualifying is
        # loaded, its real gaps sharpen the long-run (race) prediction. The
        # one-lap latent is untouched by it, so qpred stays outcome-blind.
        q_gap = pd.Series(dtype=float)
        if (state.laps is not None and not state.laps.empty
                and "session" in state.laps.columns):
            q_gap = _model().actual_quali_gap(
                state.laps[state.laps["session"] == "Qualifying"])
        stages = _model().predict_weekend(
            ctx["season"], ctx["event"],
            quali_gap=q_gap if not q_gap.empty else None)
        final = stages[list(stages)[-1]]
        roster = _roster()
        as_of = (ctx["season"], ctx["round"]) if ctx["round"] else None
        dpred = _model().driver_predictions(final, roster, "longrun", as_of=as_of)
        qpred = _model().driver_predictions(final, roster, "onelap", as_of=as_of)
        grid = None
        if state.laps is not None and "Grid_Position" in state.laps.columns:
            gser = (state.laps.dropna(subset=["Grid_Position"])
                    .drop_duplicates("Driver_Short")
                    .set_index("Driver_Short")["Grid_Position"])
            gser = gser[gser > 0]
            if len(gser) >= 8:
                grid = gser.astype(int).to_dict()
        if not dpred.empty:
            out = {"dpred": dpred, "qpred": qpred, "grid": grid}
    except Exception as exc:
        logger.warning("duel predictions unavailable: %s", exc)
    _PRED_CACHE[key] = out
    return out


# ─────────────────────────────────────────────────────────────
# Telemetry: best-lap pair + live weekend mistakes
# ─────────────────────────────────────────────────────────────

def _window_lap(tel_pool: pd.DataFrame, start: float, dur: float
                ) -> pd.DataFrame | None:
    """Slice one lap out of a per-driver telemetry pool and add t_rel +
    integrated Distance (same integration as the TELEMETRY tab)."""
    t = tel_pool[(tel_pool["timestamp"] >= start)
                 & (tel_pool["timestamp"] <= start + dur)]
    if len(t) < 20:
        return None
    t = t.sort_values("timestamp").copy()
    t["t_rel"] = t["timestamp"] - start
    spd = pd.to_numeric(t["Speed"], errors="coerce").fillna(0).to_numpy() / 3.6
    trel = t["t_rel"].to_numpy(float)
    dt = np.diff(trel)
    t["Distance"] = np.concatenate([[0.0], np.cumsum((spd[1:] + spd[:-1]) / 2 * dt)])
    return t


def _best_lap_tel_loaded(drv: str) -> tuple[pd.DataFrame | None, str]:
    """The driver's best valid lap telemetry across the LOADED sessions."""
    lp, tel = state.laps, state.telemetry
    if lp is None or lp.empty or tel is None or tel.empty:
        return None, ""
    v = lp[(lp["Driver_Short"] == drv) & lp["ValidLap"]
           & (pd.to_numeric(lp["LapTime_s"], errors="coerce") > 0)]
    if v.empty:
        return None, ""
    row = v.loc[v["LapTime_s"].idxmin()]
    pool = tel[(tel["session_name"] == row["session_name"])
               & (tel["DriverNo"].astype(str).str.strip()
                  == str(row["DriverNo"]).strip())]
    t = _window_lap(pool, float(row["LapStartTime"]), float(row["LapTime_s"]))
    label = str(row["session_name"]).split("_")[0]
    return t, f"{label} lap {int(row['LapNo'])} ({row['LapTime_s']:.3f}s)"


def _best_lap_tel_archive(drv: str, ctx: dict) -> tuple[pd.DataFrame | None, str]:
    """Fallback: the driver's best valid lap from a cached PAST session at
    this circuit (prefers last year's Qualifying, then the Race)."""
    from f1lib.data_loader import is_cached, load_sessions
    from f1lib.processing import clean_and_enrich_laps
    for yr in (ctx["season"] - 1, ctx["season"] - 2):
        for sess in ("Qualifying", "Race"):
            if not is_cached(str(yr), ctx["event"], sess):
                continue
            try:
                data = load_sessions([{"SEASON": str(yr), "MEETING": ctx["event"],
                                       "SESSION": sess}])
                lp = clean_and_enrich_laps(data["laps"])
            except Exception:
                continue
            tel = data.get("telemetry")
            if tel is None or tel.empty:
                continue
            v = lp[(lp["Driver_Short"] == drv) & lp["ValidLap"]
                   & (pd.to_numeric(lp["LapTime_s"], errors="coerce") > 0)]
            if v.empty:
                continue
            row = v.loc[v["LapTime_s"].idxmin()]
            if tel["timestamp"].dtype == object:
                tel = tel.copy()
                tel["timestamp"] = pd.to_numeric(tel["timestamp"], errors="coerce")
            pool = tel[tel["DriverNo"].astype(str).str.strip()
                       == str(row["DriverNo"]).strip()]
            t = _window_lap(pool, float(row["LapStartTime"]),
                            float(row["LapTime_s"]))
            if t is not None:
                return t, f"{yr} {sess} lap {int(row['LapNo'])}"
    return None, ""


def _pair_best_laps(a: str, b: str, ctx: dict):
    ta, la = _best_lap_tel_loaded(a)
    tb, lb = _best_lap_tel_loaded(b)
    src = "loaded weekend"
    if ta is None or tb is None:
        ta, la = _best_lap_tel_archive(a, ctx)
        tb, lb = _best_lap_tel_archive(b, ctx)
        src = "archived session at this circuit"
    return ta, tb, la, lb, src


def _live_weekend_mistakes(a: str, b: str, ctx: dict) -> pd.DataFrame:
    """Per-corner mistake counts for the pair across the LOADED sessions."""
    lp, tel = state.laps, state.telemetry
    if lp is None or lp.empty or tel is None or tel.empty:
        return pd.DataFrame()
    fracs = load_corner_fractions(ctx["event"], ctx["season"])
    if fracs.empty:
        return pd.DataFrame()
    parts = []
    for sess, g in lp.groupby("session_name"):
        tl = tel[tel["session_name"] == sess]
        if tl.empty:
            continue
        feats = corner_features_for_session(g, tl, fracs, drivers=[a, b])
        agg, _ = aggregate_mistakes(feats, g)
        if not agg.empty:
            agg["session"] = str(sess).split("_")[0]
            parts.append(agg)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# ─────────────────────────────────────────────────────────────
# Figures
# ─────────────────────────────────────────────────────────────

def _ladder_fig(res: dict, a: str, b: str, ca: str) -> go.Figure:
    lad = res["ladder"]
    stages = ["pace draw only", "+ grid & track position", "+ race-day chaos",
              "+ reliability"]
    vals = [lad["pace"] * 100, lad["track"] * 100, lad["chaos"] * 100,
            lad["full"] * 100]
    fig = go.Figure(go.Bar(
        x=stages, y=vals, marker_color=[_hex_to_rgba(ca, 0.45),
                                        _hex_to_rgba(ca, 0.6),
                                        _hex_to_rgba(ca, 0.8), ca],
        text=[f"{v:.0f}%" for v in vals], textposition="outside",
        textfont=dict(color=TEXT_MAIN, size=12),
        hovertemplate="%{x}<br>P(" + a + " ahead) = %{y:.1f}%<extra></extra>"))
    fig.add_hline(y=50, line_color=TEXT_DIM, line_dash="dash", line_width=1)
    theme(fig, 320, "")
    fig.update_layout(yaxis_title=f"P({a} finishes ahead of {b})  (%)",
                      yaxis_range=[0, max(100, max(vals) + 12)],
                      margin=dict(l=54, r=10, t=10, b=40), showlegend=False)
    return fig


def _h2h_fig(h_all: dict, h_circ: dict, a: str, b: str,
             ca: str, cb: str) -> go.Figure:
    """Stacked share bars: who finished/qualified ahead, overall and here."""
    rows = [
        ("Race · all circuits", h_all["race_a"], h_all["race_n"]),
        ("Quali · all circuits", h_all["quali_a"], h_all["quali_n"]),
        ("Race · here", h_circ["race_a"], h_circ["race_n"]),
        ("Quali · here", h_circ["quali_a"], h_circ["quali_n"]),
    ]
    labels = [r[0] for r in rows]
    fa = [100 * r[1] / r[2] if r[2] else 0 for r in rows]
    fb = [100 * (r[2] - r[1]) / r[2] if r[2] else 0 for r in rows]
    txt_a = [f"{a} {r[1]}/{r[2]}" if r[2] else "no data" for r in rows]
    txt_b = [f"{b} {r[2]-r[1]}/{r[2]}" if r[2] else "" for r in rows]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=labels, x=fa, orientation="h", marker_color=ca,
                         text=txt_a, textposition="inside", name=a,
                         insidetextanchor="start",
                         hovertemplate="%{y} · " + a + " ahead %{x:.0f}%<extra></extra>"))
    fig.add_trace(go.Bar(y=labels, x=fb, orientation="h", marker_color=cb,
                         text=txt_b, textposition="inside", name=b,
                         insidetextanchor="end",
                         hovertemplate="%{y} · " + b + " ahead %{x:.0f}%<extra></extra>"))
    fig.add_vline(x=50, line_color=TEXT_DIM, line_dash="dash", line_width=1)
    theme(fig, 260, "")
    fig.update_layout(barmode="stack", showlegend=False,
                      xaxis_title="share of meetings ahead (%)",
                      margin=dict(l=10, r=10, t=8, b=40))
    fig.update_yaxes(autorange="reversed")
    return fig


def _rotate(x, y, angle):
    ca_, sa = np.cos(angle), np.sin(angle)
    return x * ca_ - y * sa, x * sa + y * ca_


def _corner_delta_fig(deltas: pd.DataFrame, a: str, b: str,
                      ca: str, cb: str) -> go.Figure:
    d = deltas.dropna(subset=["delta_s"]).copy()
    labels = [f"T{l}" + ("  → DRS" if f else "")
              for l, f in zip(d["label"], d.get("feeds_drs", [False] * len(d)))]
    colors = [ca if v < 0 else cb for v in d["delta_s"]]
    fig = go.Figure(go.Bar(
        x=-d["delta_s"], y=labels, orientation="h", marker_color=colors,
        customdata=np.stack([d["delta_s"].abs(),
                             np.where(d["delta_s"] < 0, a, b)], axis=-1),
        hovertemplate="%{y}: %{customdata[1]} faster by %{customdata[0]:.3f}s"
                      "<extra></extra>"))
    fig.add_vline(x=0, line_color=TEXT_DIM, line_width=1)
    theme(fig, max(420, 18 * len(d) + 110), "")
    fig.update_layout(
        xaxis_title=f"corner time delta (s)  ·  ← {b} faster   |   {a} faster →",
        margin=dict(l=80, r=16, t=8, b=44), showlegend=False)
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=9))
    return fig


def _attack_map_fig(line: pd.DataFrame, fracs: pd.DataFrame,
                    deltas: pd.DataFrame, a: str, b: str,
                    ca: str, cb: str) -> go.Figure:
    fig = go.Figure()
    rot = float(line.attrs.get("rotation", 0.0)) / 180 * np.pi
    lx, ly = _rotate(line["X"].to_numpy(float), line["Y"].to_numpy(float), rot)
    fig.add_trace(go.Scatter(x=lx, y=ly, mode="lines",
                             line=dict(color=GRID_CLR, width=3),
                             hoverinfo="skip", showlegend=False))
    # DRS zones drawn on top of the line
    if "drs" in line.columns:
        drs = line["drs"].to_numpy(int) == 1
        fig.add_trace(go.Scatter(
            x=np.where(drs, lx, np.nan), y=np.where(drs, ly, np.nan),
            mode="lines", line=dict(color=_hex_to_rgba(ACCENT, 0.85), width=5),
            name="DRS zone", hoverinfo="skip"))
    d = fracs.merge(deltas[["label", "delta_s"] +
                           (["feeds_drs"] if "feeds_drs" in deltas.columns else [])],
                    on="label", how="left")
    d = d.dropna(subset=["delta_s"])
    if not d.empty:
        cx, cy = _rotate(d["X"].to_numpy(float), d["Y"].to_numpy(float), rot)
        col = [ca if v < 0 else cb for v in d["delta_s"]]
        size = 8 + 40 * d["delta_s"].abs().clip(upper=0.5)
        fig.add_trace(go.Scatter(
            x=cx, y=cy, mode="markers+text",
            text=["T" + str(l) for l in d["label"]], textposition="top center",
            textfont=dict(size=9, color=TEXT_DIM),
            marker=dict(size=size, color=col, line=dict(width=1, color="#000")),
            customdata=np.stack([d["delta_s"].abs(),
                                 np.where(d["delta_s"] < 0, a, b)], axis=-1),
            name="corners",
            hovertemplate="T%{text}: %{customdata[1]} faster by "
                          "%{customdata[0]:.3f}s<extra></extra>"))
        # star the attack corners: A faster AND feeding a DRS zone
        if "feeds_drs" in d.columns:
            atk = d[(d["delta_s"] < -0.015) & d["feeds_drs"].fillna(False)]
            if not atk.empty:
                ax, ay = _rotate(atk["X"].to_numpy(float),
                                 atk["Y"].to_numpy(float), rot)
                fig.add_trace(go.Scatter(
                    x=ax, y=ay, mode="markers",
                    marker=dict(symbol="star", size=17, color=_GOLD,
                                line=dict(width=1, color="#000")),
                    name="attack zone",
                    hovertemplate="T%{customdata}: attack zone — faster exit "
                                  "onto DRS<extra></extra>",
                    customdata=atk["label"]))
    theme(fig, 520, "")
    fig.update_layout(showlegend=True,
                      legend=dict(orientation="h", x=0, y=1.05,
                                  bgcolor="rgba(0,0,0,0)"),
                      margin=dict(l=10, r=10, t=30, b=10))
    fig.update_xaxes(visible=False, scaleanchor="y", scaleratio=1)
    fig.update_yaxes(visible=False)
    return fig


def _mistake_map_fig(line: pd.DataFrame, fracs: pd.DataFrame,
                     mm: pd.DataFrame, drv: str) -> go.Figure:
    fig = go.Figure()
    rot = float(line.attrs.get("rotation", 0.0)) / 180 * np.pi
    lx, ly = _rotate(line["X"].to_numpy(float), line["Y"].to_numpy(float), rot)
    fig.add_trace(go.Scatter(x=lx, y=ly, mode="lines",
                             line=dict(color=GRID_CLR, width=3),
                             hoverinfo="skip", showlegend=False))
    d = fracs.merge(mm.rename(columns={"corner": "label"}), on="label",
                    how="inner")
    if not d.empty:
        cx, cy = _rotate(d["X"].to_numpy(float), d["Y"].to_numpy(float), rot)
        rate = d["rate_pct"].fillna(0)
        size = 8 + 3.2 * rate.clip(upper=15)
        fig.add_trace(go.Scatter(
            x=cx, y=cy, mode="markers+text",
            text=["T" + str(l) for l in d["label"]],
            textposition="top center", textfont=dict(size=9, color=TEXT_DIM),
            marker=dict(size=size, color=rate, colorscale="YlOrRd",
                        cmin=0, cmax=max(10, float(rate.max())),
                        line=dict(width=1, color="#000")),
            customdata=np.stack([rate, d["n_mistakes"], d["n_laps"],
                                 d["time_lost_s"], d["tl_deletions"]], axis=-1),
            hovertemplate=("T%{text} · mistake on %{customdata[0]:.1f}% of laps"
                           "<br>%{customdata[1]:.0f} events / %{customdata[2]:.0f} laps"
                           " · %{customdata[3]:.1f}s lost"
                           "<br>%{customdata[4]:.0f} track-limit deletions"
                           "<extra></extra>"),
            showlegend=False))
    theme(fig, 480, "")
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
    fig.update_xaxes(visible=False, scaleanchor="y", scaleratio=1)
    fig.update_yaxes(visible=False)
    return fig


def _corner_type_fig(ct: pd.DataFrame, a: str, b: str,
                     ca: str, cb: str) -> go.Figure:
    order = ["slow", "medium", "fast"]
    fig = go.Figure()
    for drv, col in ((a, ca), (b, cb)):
        g = ct[ct["Driver_Short"] == drv].set_index("ctype").reindex(order)
        fig.add_trace(go.Bar(
            x=[f"{o} corners" for o in order], y=g["rate"], name=drv,
            marker_color=col,
            text=[f"{v:.1f}" if np.isfinite(v) else "–" for v in g["rate"]],
            textposition="outside", textfont=dict(size=10),
            customdata=np.stack([g["mistakes"].fillna(0),
                                 g["passes"].fillna(0)], axis=-1),
            hovertemplate=(drv + " · %{x}<br>%{y:.1f} mistakes /100 passes"
                           "<br>%{customdata[0]:.0f} events / "
                           "%{customdata[1]:.0f} passes<extra></extra>")))
    theme(fig, 320, "")
    fig.update_layout(barmode="group",
                      yaxis_title="micro-mistakes /100 corner passes",
                      legend=dict(orientation="h", x=0, y=1.15,
                                  bgcolor="rgba(0,0,0,0)"),
                      margin=dict(l=50, r=10, t=10, b=30))
    return fig


def _lap1_fig(l1: dict, a: str, b: str, ca: str, cb: str) -> go.Figure:
    cats = ["career avg", "at this circuit"]
    va = [l1.get("a", {}).get("mean_gain", np.nan),
          l1.get("a", {}).get("circuit_mean", np.nan)]
    vb = [l1.get("b", {}).get("mean_gain", np.nan),
          l1.get("b", {}).get("circuit_mean", np.nan)]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=cats, y=va, name=a, marker_color=ca,
                         text=[f"{v:+.2f}" if np.isfinite(v) else "–" for v in va],
                         textposition="outside"))
    fig.add_trace(go.Bar(x=cats, y=vb, name=b, marker_color=cb,
                         text=[f"{v:+.2f}" if np.isfinite(v) else "–" for v in vb],
                         textposition="outside"))
    fig.add_hline(y=0, line_color=TEXT_DIM, line_width=1)
    theme(fig, 300, "")
    fig.update_layout(barmode="group",
                      yaxis_title="avg positions gained on lap 1",
                      legend=dict(orientation="h", x=0, y=1.15,
                                  bgcolor="rgba(0,0,0,0)"),
                      margin=dict(l=50, r=10, t=10, b=30))
    return fig


# ─────────────────────────────────────────────────────────────
# Section builders
# ─────────────────────────────────────────────────────────────

def _fmt_pct(v, digits=0):
    return f"{v*100:.{digits}f}%" if np.isfinite(v) else "–"


def _verdict_section(res: dict, a: str, b: str, ca: str, grid_known: bool,
                     ga: int | None = None, gb: int | None = None):
    p = res["p_ahead"]
    verdict_col = _GREEN if p >= 0.5 else (_GOLD if p >= 0.35 else _RED)
    if grid_known and ga and gb:
        if ga < gb:
            first = html.Li([html.B("Hold what Saturday gave — "),
                f"{a} starts P{ga} against {b}'s P{gb} and converts that "
                f"track position into the flag "
                f"{_fmt_pct(res['p_convert_from_ahead'])} of the time."])
        else:
            first = html.Li([html.B("Saturday is lost — "),
                f"{a} starts P{ga} against {b}'s P{gb}, so every winning "
                "path below runs through the race itself."])
    else:
        first = html.Li([html.B("Outqualify and hold — "),
            f"{a} starts ahead of {b} in {_fmt_pct(res['p_outqualify'])} "
            f"of simulations and converts track position into the flag "
            f"{_fmt_pct(res['p_convert_from_ahead'])} of the time."])
    paths = [
        first,
        html.Li([html.B("Comeback — "),
                 f"when {a} starts behind, they still finish ahead "
                 f"{_fmt_pct(res['p_comeback'])} of the time (passability of "
                 f"this circuit: {res['pull']:.2f} — "
                 f"{'pace gets through' if res['pull'] > 0.6 else 'track position matters' if res['pull'] > 0.4 else 'the grid tends to stick'})."]),
        html.Li([html.B("Attrition — "),
                 f"{_fmt_pct(res['share_win_b_dnf'])} of {a}'s winning "
                 f"outcomes involve a {b} retirement "
                 f"(P({b} DNF) ≈ {_fmt_pct(res['p_b_dnf'])}, "
                 f"P({a} DNF) ≈ {_fmt_pct(res['p_a_dnf'])})."]),
        html.Li([html.B("Points — "),
                 f"expected championship swing at this event: "
                 f"{res['e_swing']:+.1f} pts for {a} "
                 f"(10th–90th percentile {res['swing_q10']:+.0f} … "
                 f"{res['swing_q90']:+.0f}); {a} outscores {b} in "
                 f"{_fmt_pct(res['p_swing_pos'])} of simulations."]),
    ]
    paths = [x for x in paths if x is not None]
    kpis = dbc.Row([
        kpi(f"P({a} BEATS {b})", _fmt_pct(p), color=verdict_col,
            tooltip="Share of 20,000 race simulations in which the attacker is "
                    "classified ahead of the target. Same engine as the BRIEF "
                    "tab's race forecast (pace + grid + circuit passability + "
                    "per-team reliability), evaluated pairwise."),
        kpi("EXPECTED FINISH", f"{a} P{res['e_finish_a']:.1f} · "
                               f"{b} P{res['e_finish_b']:.1f}",
            tooltip="Mean simulated finishing position of each driver."),
        kpi("WIN PROBABILITY", f"{a} {_fmt_pct(res['p_win_a'])} · "
                               f"{b} {_fmt_pct(res['p_win_b'])}",
            color=_GOLD,
            tooltip="Outright race-win probability of each driver in the same "
                    "simulation set."),
        kpi("GRID", "actual qualifying" if grid_known else "predicted",
            tooltip="Whether the simulation uses the real starting grid (once "
                    "qualifying is loaded) or samples the grid from the "
                    "one-lap speed prediction."),
    ], className="mb-2")
    ladder = card(
        "WHERE THE PROBABILITY COMES FROM",
        dcc.Graph(figure=_ladder_fig(res, a, b, ca), config=GFX),
        info="The same duel probability rebuilt channel by channel. 'Pace draw "
             "only' = who is simply faster on the day (posterior pace + "
             "driver rating). '+ grid & track position' adds where they start "
             "and how sticky this circuit is. '+ race-day chaos' adds the "
             "strategy/traffic shuffle noise. '+ reliability' adds per-team "
             "retirement risk. The step changes show what helps or hurts the "
             "attacker.")
    paths_card = card(
        "PATHS TO VICTORY",
        html.Ul(paths, style={"color": TEXT_MAIN, "fontSize": "0.85rem",
                              "lineHeight": "1.9", "marginBottom": 0}),
        info="Conditional decomposition of the winning simulations: how the "
             "attacker actually gets it done — track position, overtaking, or "
             "the rival hitting trouble.")
    return html.Div([kpis, dbc.Row([dbc.Col(ladder, md=6),
                                    dbc.Col(paths_card, md=6)])])


def _h2h_section(ctx, a, b, ca, cb):
    h_all = duel.h2h_record(a, b)
    h_circ = duel.h2h_record(a, b, circuit=ctx["cid"]) if ctx["cid"] else \
        {"race_n": 0, "race_a": 0, "quali_n": 0, "quali_a": 0,
         "a_dnfs": 0, "b_dnfs": 0}
    cres = duel.circuit_results(a, b, ctx["cid"]) if ctx["cid"] else pd.DataFrame()
    rows = []
    for _, r in cres.iterrows():
        def _f(v):
            return "–" if pd.isna(v) else f"P{int(v)}"
        rows.append({
            "Season": int(r["season"]),
            f"{a} grid→finish": f"{_f(r['a_grid'])} → {_f(r['a_fin'])}"
                                + (f"  ({r['a_status']})" if r["a_status"] else ""),
            f"{b} grid→finish": f"{_f(r['b_grid'])} → {_f(r['b_fin'])}"
                                + (f"  ({r['b_status']})" if r["b_status"] else ""),
        })
    table = (dash_table.DataTable(data=rows,
             columns=[{"name": c, "id": c} for c in rows[0]], **TABLE_STYLE)
             if rows else html.P("No archived races at this circuit for this "
                                 "pair.", style={"color": TEXT_DIM,
                                                 "fontSize": "0.8rem"}))
    return dbc.Row([
        dbc.Col(card("HEAD-TO-HEAD RECORD (2021 →)",
                     dcc.Graph(figure=_h2h_fig(h_all, h_circ, a, b, ca, cb),
                               config=GFX),
                     info="Meetings in the results archive where both drivers "
                          "took part: share qualified ahead (best Q1–Q3 time) "
                          "and finished ahead (both classified — retirements "
                          "are excluded from the race count so this reads as "
                          "performance, not luck)."), md=6),
        dbc.Col(card("AT THIS CIRCUIT — GRID → FINISH BY SEASON", table,
                     info="Both drivers' starting and finishing positions in "
                          "every archived edition of this event. Non-finishes "
                          "show the reason from the official classification."),
                md=6),
    ])


def _style_read(deltas: pd.DataFrame, a: str, b: str) -> list:
    """Bullet sentences translating the corner deltas into a scouting read."""
    d = deltas.dropna(subset=["delta_s", "vmin_a", "vmin_b"]).copy()
    if d.empty or len(d) < 4:
        return []
    d["kind"] = pd.cut(d[["vmin_a", "vmin_b"]].mean(axis=1),
                       bins=[0, 120, 200, 999],
                       labels=["slow corners", "medium corners", "fast corners"])
    bullets = []
    for kind, g in d.groupby("kind", observed=True):
        if len(g) < 2:
            continue
        tot = g["delta_s"].sum()
        who = a if tot < 0 else b
        bullets.append(html.Li(
            f"{who} is net {abs(tot):.2f}s quicker across the "
            f"{len(g)} {kind} (avg {abs(tot)/len(g):.3f}s per corner)."))
    apex = (d["vmin_a"] - d["vmin_b"]).mean()
    if np.isfinite(apex) and abs(apex) > 1.5:
        who, other = (a, b) if apex > 0 else (b, a)
        bullets.append(html.Li(
            f"{who} carries ~{abs(apex):.0f} km/h more minimum speed through "
            f"corners on average — {other}'s V-style (brake deeper, rotate, "
            f"fire out) vs {who}'s U-style (carry speed) is the shape of "
            f"this duel."))
    best = d.loc[d["delta_s"].idxmin()]
    if best["delta_s"] < -0.03:
        bullets.append(html.Li(
            f"{a}'s single biggest weapon is T{best['label']} "
            f"({-best['delta_s']:.3f}s faster)"
            + (" — and it feeds a DRS zone." if best.get("feeds_drs") else ".")))
    return bullets


def _attack_section(ctx, a, b, ca, cb):
    ta, tb, la, lb, src = _pair_best_laps(a, b, ctx)
    if ta is None or tb is None:
        return card("ATTACK ZONES",
                    html.P("No telemetry available for both drivers — load a "
                           "session of this event (or fetch last year's) in "
                           "the DATA tab.", style={"color": TEXT_DIM}),
                    info="Corner-by-corner comparison needs one full lap of "
                         "telemetry for each driver.")
    fracs = load_corner_fractions(ctx["event"], ctx["season"])
    line = load_track_line(ctx["event"], ctx["season"])
    if fracs.empty:
        return card("ATTACK ZONES",
                    html.P("No corner geometry cached for this circuit yet — "
                           "open the TRACK tab once to fetch it.",
                           style={"color": TEXT_DIM}))
    deltas = duel.corner_time_deltas(ta, tb, fracs)
    zones = duel.drs_zone_fracs(line)
    deltas = duel.tag_attack_corners(deltas, zones)
    if deltas.empty:
        return card("ATTACK ZONES", html.P("Corner comparison failed.",
                                           style={"color": TEXT_DIM}))
    n_atk = int(((deltas["delta_s"] < -0.015)
                 & deltas.get("feeds_drs", False)).sum()) if not deltas.empty else 0
    style = _style_read(deltas, a, b)
    head = html.P([
        f"Comparing {a}'s best lap ({la}) against {b}'s ({lb}) — source: "
        f"{src}. ", html.B(f"{n_atk} attack zone(s)"),
        " — corners where the attacker is faster AND which feed a DRS zone, "
        "so the advantage converts into a passing chance rather than just "
        "lap time.",
    ], style={"color": TEXT_DIM, "fontSize": "0.8rem", "lineHeight": "1.5"})
    return html.Div([
        head,
        dbc.Row([
            dbc.Col(card("WHO OWNS WHICH CORNER",
                         dcc.Graph(figure=_attack_map_fig(line, fracs, deltas,
                                                          a, b, ca, cb),
                                   config=GFX),
                         info="Track map coloured by the faster driver at each "
                              "corner (marker size = time delta). Accent "
                              "segments are DRS zones; gold stars are the "
                              "attack corners — attacker faster into a DRS "
                              "straight."), md=6),
            dbc.Col(card("CORNER TIME DELTAS",
                         dcc.Graph(figure=_corner_delta_fig(deltas, a, b,
                                                            ca, cb),
                                   config=GFX),
                         info="Per-corner traversal-time difference between "
                              "the two best laps, corner zones split at the "
                              "midpoints between apexes. '→ DRS' marks corners "
                              "feeding a DRS zone. One lap each — treat "
                              "small deltas (<0.03s) as noise."), md=6),
        ]),
        card("SCOUTING READ", html.Ul(style, style={
            "color": TEXT_MAIN, "fontSize": "0.85rem", "lineHeight": "1.9",
            "marginBottom": 0}) if style else
            html.P("Not enough corners for a style read.",
                   style={"color": TEXT_DIM}),
            info="Automated interpretation of the corner deltas: where the "
                 "time systematically comes from (slow/medium/fast corners), "
                 "the apex-speed style contrast, and the single biggest "
                 "weapon."),
        html.P([html.B("👻 Watch it: "),
                f"open the QUALI tab — the 3D replay now opens as the "
                f"{a} vs {b} ghost duel (both best laps released together, "
                f"camera following {a}), so every one of these deltas is "
                "visible as a real gap on the real track."],
               style={"color": TEXT_DIM, "fontSize": "0.8rem",
                      "marginBottom": "4px"}),
    ])


def _mistake_section(ctx, a, b, ca, cb):
    mm_b = duel.mistake_map(ctx["cid"], b) if ctx["cid"] else pd.DataFrame()
    mm_a = duel.mistake_map(ctx["cid"], a) if ctx["cid"] else pd.DataFrame()
    press = duel.pressure_summary(a, b)
    live = pd.DataFrame()
    try:
        live = _live_weekend_mistakes(a, b, ctx)
    except Exception as exc:
        logger.warning("live mistake scan failed: %s", exc)

    parts = []
    # target's error map at this circuit
    line = load_track_line(ctx["event"], ctx["season"])
    fracs = load_corner_fractions(ctx["event"], ctx["season"])
    if not mm_b.empty and not line.empty and not fracs.empty:
        n_sess = duel.load_mistakes(ctx["cid"], [b])
        n_sess = n_sess[["season", "session"]].drop_duplicates().shape[0]
        laps_total = int(mm_b["n_laps"].max()) if len(mm_b) else 0
        top = mm_b.head(3)
        toplist = ", ".join(
            f"T{r['corner']} ({r['rate_pct']:.0f}%/lap, "
            f"{r['time_lost_s']:.1f}s lost)"
            for _, r in top.iterrows() if r["n_mistakes"] > 0)
        parts.append(dbc.Row([
            dbc.Col(card(f"WHERE {b} ERRS AT THIS TRACK",
                dcc.Graph(figure=_mistake_map_fig(line, fracs, mm_b, b),
                          config=GFX),
                info=f"Per-corner micro-mistake rate for {b}, pooled over "
                     f"{n_sess} archived session(s) at this circuit "
                     "(compute_mistakes.py). A mistake = a corner-exit "
                     "throttle lift, a brake re-application on entry, or a "
                     "corner time ≥3 MAD above the driver's own median (dirty-"
                     "air laps excluded), plus track-limit deletions. Marker "
                     "size & colour = mistake rate per lap."), md=7),
            dbc.Col([
                card("PRESSURE INDEX",
                     _pressure_block(press, a, b, ca, cb),
                     info="Archive-wide (every scanned race): the drivers' "
                          "mistake rate per 100 clean laps with a car within "
                          "1.5s behind versus running free. Ratio > 1 = errs "
                          "more under pressure — sitting in their mirrors is "
                          "itself a weapon. Traffic-affected laps are already "
                          "excluded from the underlying detection."),
                card("TARGET'S HOTSPOTS",
                     html.P(toplist or "No repeat-offender corners found here.",
                            style={"color": TEXT_MAIN, "fontSize": "0.85rem",
                                   "lineHeight": "1.7", "marginBottom": 0}),
                     info=f"{b}'s three highest per-lap mistake-rate corners "
                          "at this circuit. Pressure applied INTO these "
                          "corners has the best odds of forcing the error."),
            ], md=5),
        ]))
    else:
        parts.append(card("MISTAKE RADAR",
            html.P("No archived mistake data for this circuit yet — run "
                   "compute_mistakes.py after fetching sessions here, and make "
                   "sure the circuit's track map is cached (TRACK tab).",
                   style={"color": TEXT_DIM})))

    # attacker vs target comparison table (archive at this circuit)
    if not mm_a.empty and not mm_b.empty:
        ra = 100 * mm_a["n_mistakes"].sum() / max(mm_a["n_laps"].max(), 1)
        rb = 100 * mm_b["n_mistakes"].sum() / max(mm_b["n_laps"].max(), 1)
        parts.append(dbc.Row([
            kpi(f"{a} ERROR RATE HERE", f"{ra:.0f} /100 laps", color=ca,
                tooltip="Total micro-mistakes per 100 clean laps across all "
                        "archived sessions at this circuit."),
            kpi(f"{b} ERROR RATE HERE", f"{rb:.0f} /100 laps", color=cb,
                tooltip="Total micro-mistakes per 100 clean laps across all "
                        "archived sessions at this circuit."),
            kpi("READ", f"{'target' if rb > ra else 'attacker'} more error-prone",
                color=_GREEN if rb > ra else _RED,
                tooltip="Who historically makes more micro-mistakes at this "
                        "circuit. Small samples — treat as a lean, not a "
                        "verdict."),
        ], className="mb-2"))

    # archive-wide profile by corner type
    try:
        ct = duel.corner_type_profile(a, b)
    except Exception as exc:
        logger.warning("corner-type profile failed: %s", exc)
        ct = pd.DataFrame()
    if not ct.empty:
        read = ""
        try:
            piv = ct.pivot(index="ctype", columns="Driver_Short",
                           values="rate")
            if a in piv.columns and b in piv.columns:
                diff = (piv[b] - piv[a]).dropna()
                if not diff.empty:
                    worst = diff.idxmax()
                    if diff[worst] > 0.3:
                        read = (f"{b} is most error-prone relative to {a} in "
                                f"{worst} corners (+{diff[worst]:.1f} "
                                f"/100 passes) — the highest-percentage places "
                                "to apply pressure, at any circuit.")
                    elif diff.min() < -0.3:
                        best = diff.idxmin()
                        read = (f"{a} actually errs more than {b} in "
                                f"{best} corners ({-diff[best]:.1f} "
                                "/100 passes) — discipline there matters more "
                                "than attack.")
        except Exception:
            pass
        parts.append(card("ERROR PROFILE BY CORNER TYPE — ALL CIRCUITS",
            html.Div([
                dcc.Graph(figure=_corner_type_fig(ct, a, b, ca, cb),
                          config=GFX),
                html.P(read, style={"color": TEXT_MAIN, "fontSize": "0.85rem",
                                    "marginBottom": 0}) if read else html.Div(),
            ]),
            info="The same micro-mistake detection pooled over the ENTIRE "
                 "archive (every scanned circuit, 2023 →), with each corner "
                 "classified slow (<120 km/h), medium (120–200) or fast "
                 "(>200) from the cached track-line speed. Tens of thousands "
                 "of corner passes per driver, so this is the statistically "
                 "solid version of the single-circuit map — where each "
                 "driver's errors structurally live."))

    # live weekend
    if not live.empty:
        lw = (live.groupby(["Driver_Short", "corner"], as_index=False)
              .agg(laps=("n_laps", "sum"), slow=("n_slow", "sum"),
                   lifts=("n_lift", "sum"), brake=("n_brake_reapp", "sum"),
                   lost=("time_lost_s", "sum")))
        lw["events"] = lw["slow"] + lw["lifts"] + lw["brake"]
        lw = lw[lw["events"] > 0].sort_values("events", ascending=False).head(12)
        if not lw.empty:
            rows = [{"Driver": r["Driver_Short"], "Corner": f"T{r['corner']}",
                     "Events": int(r["events"]),
                     "Slow": int(r["slow"]), "Lifts": int(r["lifts"]),
                     "Brake re-apps": int(r["brake"]),
                     "Time lost (s)": f"{r['lost']:.2f}"}
                    for _, r in lw.iterrows()]
            parts.append(card("THIS WEEKEND SO FAR — LIVE MISTAKE SCAN",
                dash_table.DataTable(data=rows,
                    columns=[{"name": c, "id": c} for c in rows[0]],
                    **TABLE_STYLE),
                info="The same detector run live on the loaded weekend's "
                     "telemetry for the two selected drivers — the freshest "
                     "read on where each is struggling on THIS car/tyre/"
                     "surface combination."))
    return html.Div(parts)


def _pressure_block(press: pd.DataFrame, a, b, ca, cb):
    if press.empty:
        return html.P("Run compute_mistakes.py to build the pressure archive.",
                      style={"color": TEXT_DIM, "fontSize": "0.8rem"})
    items = []
    for drv, col in ((a, ca), (b, cb)):
        r = press[press["Driver_Short"] == drv]
        if r.empty:
            items.append(html.P(f"{drv}: no data", style={"color": TEXT_DIM}))
            continue
        r = r.iloc[0]
        ratio = r["pressure_ratio"]
        lbl = ("cracks under pressure" if ratio > 1.25 else
               "solid under pressure" if ratio < 0.85 else "unaffected")
        items.append(html.Div([
            html.Span(drv, style={"color": col, "fontWeight": "800",
                                  "fontSize": "0.95rem"}),
            html.Span(f"  {r['rate_free']:.1f} → {r['rate_pressured']:.1f} "
                      f"micro-events /100 laps  ",
                      style={"color": TEXT_MAIN, "fontSize": "0.85rem"}),
            html.Span(f"×{ratio:.2f} · {lbl}",
                      style={"color": (_RED if ratio > 1.25 else _GREEN
                                       if ratio < 0.85 else TEXT_DIM),
                             "fontWeight": "700", "fontSize": "0.8rem"}),
            html.Div(f"free: {int(r['laps_f']):,} laps · pressured: "
                     f"{int(r['laps_p']):,} laps",
                     style={"color": TEXT_DIM, "fontSize": "0.7rem",
                            "marginBottom": "10px"}),
        ]))
    return html.Div(items)


def _adversarial_board(ctx, pred, a, b, sc_prob: float):
    """Strategy plans scored against the TARGET's optimal plan.

    The target is assumed to run the race-time-optimal compound plan; every
    alternative plan the attacker could commit to is priced in two worlds —
    no Safety Car, and an SC falling at a random mid-race lap (both cars
    re-time their stops within their committed compounds when it comes out).
    A diverging plan can't beat the optimal one in clean-air expectation by
    construction; what it buys is SC upside — this board makes that trade
    explicit and compares it against the pace deficit the attacker must find."""
    from tabs.race import (_resolve_race_data, _estimate_pit_loss,
                           _strategy_model, _simulate_strategies)
    rd = _resolve_race_data(ctx["season"], ctx["event"])
    if not rd:
        return None
    rl = rd["laps"]
    total_laps = int(pd.to_numeric(rl["LapNo"], errors="coerce").max())
    if total_laps < 20:
        return None
    pit_loss = _estimate_pit_loss(rl)
    if pit_loss is None:
        scp = duel.sc_profile(ctx["ck_fr"])
        pit_loss = scp.get("pit_loss_s")
        if pit_loss is None or not np.isfinite(pit_loss):
            return None
    model = _strategy_model(rl, total_laps)
    if model is None:
        return None

    def _per_comp(res_df):
        """Best total per compound plan (label of its best variant kept)."""
        g = res_df.sort_values("Total").drop_duplicates("Compounds")
        return {r.Compounds: (float(r.Total), r.Label)
                for r in g.itertuples()}

    base, _ = _simulate_strategies(model, total_laps, pit_loss)
    if base.empty:
        return None
    nosc = _per_comp(base)
    b_comp = base.iloc[0]["Compounds"]
    b_label = base.iloc[0]["Label"]

    sc_grid = list(range(8, max(total_laps - 8, 9), 6))
    sc_tot: dict[str, list[float]] = {c: [] for c in nosc}
    for scl in sc_grid:
        r_sc, _ = _simulate_strategies(model, total_laps, pit_loss, sc_lap=scl)
        pc = _per_comp(r_sc)
        for c in sc_tot:
            if c in pc:
                sc_tot[c].append(pc[c][0])

    # pace deficit A vs B over the race distance, from the model prediction
    pace_deficit = np.nan
    if pred is not None:
        dp = pred["dpred"].set_index("driver")["mean"]
        if a in dp.index and b in dp.index:
            lt = pd.to_numeric(rl.loc[rl["ValidLap"], "LapTime_s"],
                               errors="coerce").median()
            if np.isfinite(lt):
                pace_deficit = (float(dp[a] - dp[b]) / 100.0) * lt * total_laps

    rows = []
    for comp, (tot, label) in nosc.items():
        edge_nosc = nosc[b_comp][0] - tot            # + = A's plan faster
        scs_b = sc_tot.get(b_comp, [])
        scs_a = sc_tot.get(comp, [])
        edge_sc = (float(np.mean(np.array(scs_b) - np.array(scs_a)))
                   if scs_a and len(scs_a) == len(scs_b) else np.nan)
        exp_edge = ((1 - sc_prob) * edge_nosc + sc_prob * edge_sc
                    if np.isfinite(edge_sc) else edge_nosc)
        rows.append({"comp": comp, "label": label, "is_b": comp == b_comp,
                     "edge_nosc": edge_nosc, "edge_sc": edge_sc,
                     "exp_edge": exp_edge})
    board = pd.DataFrame(rows).sort_values("exp_edge", ascending=False)
    return {"board": board, "b_label": b_label, "b_comp": b_comp,
            "pace_deficit": pace_deficit, "total_laps": total_laps,
            "pit_loss": float(pit_loss), "year": rd["season"],
            "n_sc_scenarios": len(sc_grid)}


def _adversarial_card(adv, a, b, sc_prob):
    board = adv["board"]
    need = adv["pace_deficit"]
    rows = []
    for _, r in board.iterrows():
        if r["is_b"]:
            continue
        rows.append({
            "Attacker plan": r["label"],
            "vs target · no SC (s)": f"{r['edge_nosc']:+.1f}",
            "vs target · SC race (s)": f"{r['edge_sc']:+.1f}"
            if np.isfinite(r["edge_sc"]) else "–",
            "Expected edge (s)": f"{r['exp_edge']:+.1f}",
        })
    if not rows:
        return None
    deficit_txt = (f"{need:+.1f}s" if np.isfinite(need) else "unknown")
    verdict = []
    if np.isfinite(need):
        best = board[~board["is_b"]].iloc[0] if (~board["is_b"]).any() else None
        if need <= 0:
            verdict = [f"{a} is quicker over the distance ({deficit_txt}) — "
                       f"mirroring the target's plan is enough; divergence "
                       "only adds risk."]
        elif best is not None and best["exp_edge"] > 0:
            verdict = [f"{a} needs to find {deficit_txt} on {b}. "
                       f"Best divergence: {best['label']} — expected "
                       f"{best['exp_edge']:+.1f}s vs the target's plan once "
                       f"the {sc_prob*100:.0f}% SC probability is priced in."]
        else:
            verdict = [f"{a} needs to find {deficit_txt} on {b}, and no "
                       "committed plan buys it on paper — the edge has to "
                       "come from the start, an error, or reactive calls "
                       "(SC timing, weather)."]
    header = html.P([
        html.B(f"Target's optimal plan: {adv['b_label']}"),
        f"  ·  {adv['total_laps']} laps · pit loss {adv['pit_loss']:.1f}s · "
        f"deg/offsets measured from the {adv['year']} race here. ",
        html.B(f"Pace deficit to overcome: {deficit_txt}."),
        html.Br(), *verdict,
    ], style={"color": TEXT_DIM, "fontSize": "0.8rem", "lineHeight": "1.6"})
    return card("ADVERSARIAL STRATEGY BOARD — BEAT THEIR PLAN",
        html.Div([header,
                  dash_table.DataTable(data=rows,
                      columns=[{"name": c, "id": c} for c in rows[0]],
                      **TABLE_STYLE)]),
        info="Every compound plan the attacker could commit to, priced "
             "against the target running the race-time-optimal plan. "
             "'No SC' is clean-air expectation (a diverging plan can never "
             "beat the optimum there — the column shows what the divergence "
             "costs). 'SC race' re-times both cars' stops with a Safety Car "
             f"at {adv['n_sc_scenarios']} different mid-race laps and "
             "averages — offset plans keep a cheap-stop window open and gain "
             "here. 'Expected edge' weights the two worlds by this circuit's "
             "measured SC probability. Committed pre-race plans only; "
             "in-race reactive strategy is not modelled.")


def _strategy_section(ctx, res, a, b, ga=None, gb=None, pred=None):
    sc = duel.sc_profile(ctx["ck_fr"])
    # measured undercut power from the most recent archived race here
    uc_med, uc_n, uc_year = np.nan, 0, None
    try:
        from tabs.race import _resolve_race_data, _undercut_pairs
        rd = _resolve_race_data(ctx["season"], ctx["event"])
        if rd:
            pairs = _undercut_pairs(rd["laps"])
            if not pairs.empty:
                clean = pairs[~pairs["Flag_Affected"]]["Net_Gain"]
                if len(clean) >= 3:
                    uc_med, uc_n = float(clean.median()), len(clean)
                uc_year = rd["season"]
    except Exception as exc:
        logger.warning("undercut lookup failed: %s", exc)

    kpis = []
    if sc:
        kpis += [
            kpi("P(SAFETY CAR)", _fmt_pct(sc["p_sc"]),
                color=_GOLD if sc["p_sc"] >= 0.5 else TEXT_MAIN,
                tooltip=f"Share of the last {sc['n_races']} races here with at "
                        "least one full Safety Car (measured, race_stats.csv). "
                        f"VSC: {_fmt_pct(sc.get('p_vsc', np.nan))}."),
            kpi("PIT LOSS", f"{sc['pit_loss_s']:.0f}s"
                if np.isfinite(sc["pit_loss_s"]) else "–",
                tooltip="Median measured pit-lane time loss at this circuit — "
                        "what a 'free stop' under SC is worth roughly half of."),
            kpi("OVERTAKES / RACE", f"{sc['overtakes_med']:.0f}"
                if np.isfinite(sc["overtakes_med"]) else "–",
                tooltip="Median genuine on-track passes in recent races here — "
                        "how much a pace edge can actually be used."),
        ]
    if np.isfinite(uc_med):
        kpis.append(kpi("UNDERCUT VALUE", f"{uc_med:+.1f}s",
            color=_GREEN if uc_med > 0 else TEXT_MAIN,
            tooltip=f"Median net gain of the first stopper across {uc_n} clean "
                    f"pit exchanges in the {uc_year} race here — the measured "
                    "power of pitting first at this circuit."))

    if ga and gb:
        behind = ga > gb
        behind_txt = f"{a} starts P{ga} vs {b}'s P{gb}"
    else:
        behind = res["p_outqualify"] < 0.5 if res else False
        behind_txt = (f"{a} out-qualifies {b} in only "
                      f"{_fmt_pct(res['p_outqualify']) if res else '–'} of sims")
    advice = []
    if res:
        if behind:
            advice.append(html.Li([html.B("Starting behind: "),
                f"{behind_txt} — the stop is the primary weapon. "
                + (f"The undercut here has been worth {uc_med:+.1f}s — pit "
                   f"first, within ~{max(1.0, uc_med):.0f}s on track it wins "
                   "the exchange. " if np.isfinite(uc_med) and uc_med > 0 else
                   "The undercut here has historically been weak — track "
                   "position via the overcut/offset matters more. ")]))
        else:
            advice.append(html.Li([html.B("Starting ahead: "),
                f"{behind_txt.replace('in only', 'in')} — cover the rival's "
                "stop (mirror strategy) and use clean air. Divergence only "
                "pays when behind — don't gamble from the front."]))
        if sc and sc.get("p_sc", 0) >= 0.5:
            advice.append(html.Li([html.B("SC lottery is live: "),
                f"{_fmt_pct(sc['p_sc'])} of recent races here had a Safety "
                "Car. Running long with a tyre offset keeps the cheap-stop "
                "window open — the classic path for the car behind."]))
        if sc and np.isfinite(sc.get("one_stop_pct", np.nan)):
            osp = sc["one_stop_pct"]
            advice.append(html.Li([html.B("Stop count: "),
                f"{osp:.0f}% of the field one-stopped here last time — "
                + ("a one-stop track: the undercut window is a single, "
                   "decisive call." if osp >= 60 else
                   "a multi-stop track: more exchanges, more chances to win "
                   "one.")]))
    advice.append(html.Li([html.B("Full simulator: "),
        "the RACE tab's Strategy What-If board simulates exact stop laps and "
        "compounds (SC- and traffic-aware) once race data is loaded."]))

    adv_card = None
    try:
        p_sc = float(sc.get("p_sc", 0.5)) if sc else 0.5
        adv = _adversarial_board(ctx, pred, a, b, p_sc)
        if adv is not None:
            adv_card = _adversarial_card(adv, a, b, p_sc)
    except Exception as exc:
        logger.warning("adversarial strategy board failed: %s", exc)

    return html.Div([
        dbc.Row(kpis, className="mb-2") if kpis else html.Div(),
        card("THE PLAYBOOK",
             html.Ul(advice, style={"color": TEXT_MAIN, "fontSize": "0.85rem",
                                    "lineHeight": "1.9", "marginBottom": 0}),
             info="Strategy guidance synthesized from the duel simulation "
                  "(who is likely ahead), the measured undercut power of this "
                  "circuit, its Safety-Car history and stop-count pattern. "
                  "Heuristics, not a plan — the RACE tab simulator does the "
                  "exact math."),
        adv_card or html.Div(),
    ])


def _chaos_section(ctx, a, b, ta, tb, ca, cb):
    l1 = duel.lap1_profile(a, b, ctx["ck_fr"])
    rates, detail = duel.team_dnf_rates(
        seasons=(ctx["season"] - 2, ctx["season"] - 1, ctx["season"]))
    rel_rows = []
    teams = [ta] if ta == tb else [ta, tb]
    for team in teams:
        m = detail[detail["team"] == team]
        if m.empty:
            continue
        m = m.iloc[0]
        rel_rows.append({"Team": _abbr(team), "Starts": int(m["starts"]),
                         "DNFs": int(m["dnfs"]),
                         "Mechanical": int(m["mech"]),
                         "Incidents": int(m["incidents"]),
                         "DNF rate (shrunk)": f"{m['rate']*100:.1f}%"})
    rel_children = [dash_table.DataTable(data=rel_rows,
                    columns=[{"name": c, "id": c} for c in rel_rows[0]],
                    **TABLE_STYLE)] if rel_rows else \
        [html.P("No reliability history for these teams.",
                style={"color": TEXT_DIM})]
    if ta == tb and rel_rows:
        rel_children.append(html.P(
            "Same car on both sides of this duel — reliability largely "
            "cancels out, except for driver-induced incidents.",
            style={"color": TEXT_DIM, "fontSize": "0.75rem",
                   "marginTop": "8px", "marginBottom": 0}))
    rel = html.Div(rel_children)
    return html.Div([
        dbc.Row([
            dbc.Col(card("LAP-1 HABITS",
                         dcc.Graph(figure=_lap1_fig(l1, a, b, ca, cb),
                                   config=GFX),
                         info="Average positions gained/lost on lap 1 "
                              "(measured lap-1 league, 2023 →), career-wide "
                              "and at this circuit. A driver who habitually "
                              "gains at lights-out can undo Saturday in 300 "
                              "metres — front-row starters can only lose, so "
                              "interpret alongside usual grid slots."), md=6),
            dbc.Col(card("RELIABILITY — LAST 3 SEASONS",
                         rel,
                         info="Retirements per start from the results "
                              "archive, split mechanical vs incident. The "
                              "shrunk rate (pulled toward the field mean) is "
                              "what the duel simulation uses as each car's "
                              "DNF probability."), md=6),
        ]),
        _wet_card(ctx, a, b, ca, cb),
    ])


def _wet_card(ctx, a, b, ca, cb):
    wp = duel.wet_profile(a, b)
    if not wp or not (wp.get("a", {}).get("wet_n") or wp.get("b", {}).get("wet_n")):
        return html.Div()
    items = []
    fc = duel.rain_forecast(ctx["season"], ctx["event"])
    if fc:
        pr = fc["p_rain"]
        items.append(html.Div([
            html.Span("RACE-DAY FORECAST  ", style={
                "color": TEXT_DIM, "fontSize": "0.68rem",
                "letterSpacing": "2px"}),
            html.Span(f"{pr*100:.0f}% precipitation probability",
                      style={"color": ("#4FC3F7" if pr >= 0.4 else TEXT_MAIN),
                             "fontWeight": "800", "fontSize": "0.95rem"}),
            html.Span(f"  ·  {fc['precip_mm']:.1f} mm expected  ·  "
                      f"{fc['date']} · Open-Meteo",
                      style={"color": TEXT_DIM, "fontSize": "0.72rem"}),
        ], style={"marginBottom": "12px", "paddingBottom": "10px",
                  "borderBottom": f"1px solid {GRID_CLR}"}))
    for drv, col, tag in ((a, ca, "a"), (b, cb, "b")):
        d = wp.get(tag, {})
        if not d or not np.isfinite(d.get("rain_delta", np.nan)):
            items.append(html.Div([
                html.Span(drv, style={"color": col, "fontWeight": "800"}),
                html.Span("  not enough wet races in the archive.",
                          style={"color": TEXT_DIM, "fontSize": "0.82rem"}),
            ], style={"marginBottom": "8px"}))
            continue
        lbl = ("thrives in the rain" if d["rain_delta"] > 1.0 else
               "suffers in the rain" if d["rain_delta"] < -1.0 else
               "rain-neutral")
        items.append(html.Div([
            html.Span(drv, style={"color": col, "fontWeight": "800",
                                  "fontSize": "0.95rem"}),
            html.Span(f"  dry {d['dry_gain']:+.1f} → wet {d['wet_gain']:+.1f} "
                      "positions gained per race  ",
                      style={"color": TEXT_MAIN, "fontSize": "0.85rem"}),
            html.Span(f"Δ{d['rain_delta']:+.1f} · {lbl}",
                      style={"color": (_GREEN if d["rain_delta"] > 1.0 else
                                       _RED if d["rain_delta"] < -1.0
                                       else TEXT_DIM),
                             "fontWeight": "700", "fontSize": "0.8rem"}),
            html.Div(f"{d['wet_n']} wet · {d['dry_n']} dry classified races "
                     "(2023 →)",
                     style={"color": TEXT_DIM, "fontSize": "0.7rem",
                            "marginBottom": "10px"}),
        ]))
    da = wp.get("a", {}).get("rain_delta", np.nan)
    db_ = wp.get("b", {}).get("rain_delta", np.nan)
    if np.isfinite(da) and np.isfinite(db_):
        diff = da - db_
        verdict = (f"Rain historically shifts this duel toward {a} by "
                   f"{diff:+.1f} positions per race — pray for rain."
                   if diff > 0.8 else
                   f"Rain historically shifts this duel toward {b} "
                   f"({diff:+.1f}) — hope it stays dry."
                   if diff < -0.8 else
                   "Rain is roughly neutral between these two.")
        items.append(html.P(html.B(verdict),
                            style={"color": TEXT_MAIN, "fontSize": "0.85rem",
                                   "marginBottom": 0}))
    return card("IF IT RAINS — THE EQUALIZER",
        html.Div(items),
        info="Positions gained grid → flag per classified race, split by "
             "whether INTERMEDIATES WERE ACTUALLY FITTED "
             "(data/session_weather.csv, 2019 →). It used to split on "
             "race_stats.csv's rain flag, which is Rainfall.any() over the "
             "weather stream — a single damp sample marked a whole race wet, "
             "and 7 of the 13 races it flagged since 2023 never ran an "
             "intermediate (Austria 2024 among them, at a 46 °C track), while "
             "Canada 2026 ran inters with the sensor never tripping. "
             "Classifying on the tyre fixes it in both directions and roughly "
             "triples the sample by reaching back to 2019. The wet-vs-dry "
             "delta reads each driver's racecraft when grip disappears; "
             "retirements are excluded so crashes don't pollute the skill "
             "read. Wet samples are still small — treat ±1 position as noise. "
             "When the loaded event's race is within the next 16 days, the "
             "header shows the live Open-Meteo precipitation forecast at the "
             "circuit; for past events this stays an if-it-rains scenario.")


# ─────────────────────────────────────────────────────────────
# Layout + callback
# ─────────────────────────────────────────────────────────────

def tab_duel(sel_drivers=None, sel_teams=None):
    ctx = _event_context()
    roster = _roster()
    if ctx is None or roster.empty:
        return html.P("No event loaded — pick one in the DATA tab.",
                      style={"color": TEXT_DIM})
    a0, b0 = _default_pair(ctx, roster)
    opts = [{"label": f"{d}  ·  {_abbr(t)}", "value": d}
            for d, t in roster.sort_values("driver").itertuples(index=False)]
    dd_style = {"backgroundColor": "#111", "fontSize": "0.85rem"}
    intro = html.P([
        html.B("The duel planner.  "),
        f"Pick an attacker and a target (default: the championship runner-up "
        f"chasing the leader) and this tab assembles the battle plan for "
        f"{ctx['event']}: the head-to-head probability and where it comes "
        "from, which corners to attack, where the rival makes mistakes and "
        "whether they crack under pressure, the strategy levers, and the "
        "chaos channels (starts, reliability, Safety Cars).",
    ], style={"color": TEXT_DIM, "fontSize": "0.8rem", "lineHeight": "1.5",
              "marginBottom": "14px"})
    controls = dbc.Row([
        dbc.Col([html.P("ATTACKER", style={"color": TEXT_DIM,
                 "fontSize": "0.68rem", "letterSpacing": "2px",
                 "marginBottom": "4px"}),
                 dcc.Dropdown(id="duel-a", options=opts, value=a0,
                              clearable=False, style=dd_style)], md=3),
        dbc.Col(html.Div("⚔", style={"color": ACCENT, "fontSize": "1.6rem",
                                     "textAlign": "center",
                                     "paddingTop": "22px"}), md=1),
        dbc.Col([html.P("TARGET", style={"color": TEXT_DIM,
                 "fontSize": "0.68rem", "letterSpacing": "2px",
                 "marginBottom": "4px"}),
                 dcc.Dropdown(id="duel-b", options=opts, value=b0,
                              clearable=False, style=dd_style)], md=3),
    ], className="mb-3")
    return html.Div([
        intro, controls,
        dcc.Loading(html.Div(id="duel-body"), type="default", color=ACCENT,
                    delay_show=250),
    ])


def _section_title(txt):
    return html.H4(txt, style={
        "color": TEXT_MAIN, "fontWeight": "800", "letterSpacing": "2px",
        "fontSize": "1.0rem", "marginTop": "18px", "marginBottom": "10px",
        "borderBottom": f"2px solid {ACCENT}", "paddingBottom": "6px"})


@callback(Output("duel-body", "children"),
          Input("duel-a", "value"), Input("duel-b", "value"))
def render_duel(a, b):
    if not a or not b:
        return dbc.Alert("Pick two drivers.", color="secondary")
    if a == b:
        return dbc.Alert("Pick two different drivers — a driver can't duel "
                         "themselves.", color="warning")
    ctx = _event_context()
    roster = _roster()
    if ctx is None or roster.empty:
        return dbc.Alert("No event loaded.", color="warning")

    global LAST_PAIR
    LAST_PAIR = (a, b)

    key = (a, b, state.DATA_GENERATION)
    if key in _BODY_CACHE:
        return _BODY_CACHE[key]

    ta, tb, ca, cb = _pair_colors(a, b, roster)

    # championship context
    st = _driver_standings_after_round(ctx["season"], ctx["round"])
    pts_a = st.get(a, {}).get("pts", np.nan)
    pts_b = st.get(b, {}).get("pts", np.nan)
    order = [d for d, v in sorted(st.items(), key=lambda kv: -kv[1]["pts"])]
    pos_a = order.index(a) + 1 if a in order else None
    pos_b = order.index(b) + 1 if b in order else None

    # duel simulation
    res, grid_known, ga, gb = None, False, None, None
    pred = _predictions(ctx)
    rf = _forecaster()
    if pred is not None and rf is not None:
        rates, _ = duel.team_dnf_rates(
            seasons=(ctx["season"] - 2, ctx["season"] - 1, ctx["season"]))
        teamof = dict(zip(pred["dpred"]["driver"], pred["dpred"]["team"]))
        drates = {d: rates.get(teamof.get(d, ""), 0.11)
                  for d in pred["dpred"]["driver"]}
        grid_known = pred["grid"] is not None
        if grid_known:
            ga, gb = pred["grid"].get(a), pred["grid"].get(b)
        try:
            res = duel.duel_simulation(
                rf, pred["dpred"], event=ctx["event"], a=a, b=b,
                grid=pred["grid"],
                quali_pred=None if grid_known else pred["qpred"],
                dnf_rates=drates)
        except Exception as exc:
            logger.warning("duel simulation failed: %s", exc)

    head_kpis = dbc.Row([
        kpi(f"{a} · CHAMPIONSHIP", f"P{pos_a} · {pts_a:.0f} pts"
            if pos_a else "–", color=ca,
            tooltip="Attacker's current championship position and points."),
        kpi(f"{b} · CHAMPIONSHIP", f"P{pos_b} · {pts_b:.0f} pts"
            if pos_b else "–", color=cb,
            tooltip="Target's current championship position and points."),
        kpi("POINTS GAP", f"{(pts_b - pts_a):+.0f} to close"
            if np.isfinite(pts_a) and np.isfinite(pts_b) else "–",
            tooltip="Target's points minus attacker's — what the attacker "
                    "has to make up over the remaining rounds."),
        kpi("E[SWING] THIS EVENT", f"{res['e_swing']:+.1f} pts"
            if res else "–",
            color=_GREEN if res and res["e_swing"] > 0 else TEXT_MAIN,
            tooltip="Expected championship-points swing between the two at "
                    "this event, from the duel simulation (positive = "
                    "attacker gains)."),
    ], className="mb-2")

    sections = [head_kpis]
    if res:
        sections += [_section_title("THE VERDICT"),
                     _verdict_section(res, a, b, ca, grid_known, ga, gb)]
    else:
        sections.append(dbc.Alert(
            "Pace-model prediction unavailable for this event — the verdict "
            "simulation is skipped (run compute_team_pace.py for this "
            "season).", color="secondary"))

    def _safe_section(title, builder, *args):
        try:
            out = builder(*args)
        except Exception as exc:
            logger.exception("duel section %s failed", title)
            out = dbc.Alert(f"{title} failed: {exc}", color="secondary")
        sections.append(_section_title(title))
        sections.append(out)

    _safe_section("TRACK RECORD — THE HISTORY", _h2h_section, ctx, a, b, ca, cb)
    _safe_section("ATTACK ZONES — WHERE TO STRIKE", _attack_section,
                  ctx, a, b, ca, cb)
    _safe_section("MISTAKE RADAR — WHERE THE ERROR COMES", _mistake_section,
                  ctx, a, b, ca, cb)
    _safe_section("STRATEGY PLAYBOOK", _strategy_section, ctx, res, a, b,
                  ga, gb, pred)
    _safe_section("CHAOS CHANNELS — STARTS & RELIABILITY", _chaos_section,
                  ctx, a, b, ta, tb, ca, cb)

    out = html.Div(sections)
    _BODY_CACHE[key] = out
    while len(_BODY_CACHE) > 8:
        _BODY_CACHE.pop(next(iter(_BODY_CACHE)))
    return out
