"""
Driver-style fingerprints — how a driver drives, not how fast.

Six style traits are measured on each driver's single best lap of the loaded
weekend (the same best-lap telemetry the Max-Speed/Gear charts use):

  Braking force    p95 deceleration while on the brakes (g)
  Brake duration   % of the lap spent braking (long trail-braking vs
                   short-sharp stops)
  Coasting         % of the lap off both pedals
  Full throttle    % of the lap at ≥95% throttle
  Modulation       % of the lap at partial throttle (5–95%) — mid-corner
                   balancing on the pedal
  Power aggression how quickly full power is applied after brake release
                   (median seconds to 90% throttle, inverted)

The radar shows each trait as a percentile rank within the loaded field, so
it reads as a *style* silhouette relative to the other drivers, not absolute
physics. The throttle-application card is the average throttle trace in the
four seconds after every brake release — the corner-exit signature.

Rendered at the bottom of the TELEMETRY tab; all figures are driven by two
driver dropdowns via a pre-computed dcc.Store (no recomputation on change).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, callback, Input, Output, State
import dash_bootstrap_components as dbc

from components import theme, card, GFX
from config import TEAM_COLORS, CARD_BG, TEXT_DIM, TEXT_MAIN, GRID_CLR, ACCENT

_RAMP_HORIZON = 4.0      # seconds after brake release
_RAMP_GRID = np.arange(0.0, _RAMP_HORIZON + 0.001, 0.1)

# trait → (raw-metric key, higher-raw-means-more-of-trait, unit, description)
_TRAITS = {
    "Braking force":    ("peak_brake_g", True,  "g",
                         "p95 deceleration under braking"),
    "Brake duration":   ("brake_share",  True,  "%",
                         "share of lap on the brakes"),
    "Coasting":         ("coast_share",  True,  "%",
                         "share of lap off both pedals"),
    "Full throttle":    ("full_share",   True,  "%",
                         "share of lap flat out"),
    "Modulation":       ("partial_share", True, "%",
                         "share of lap at partial throttle"),
    "Power aggression": ("ramp_s",       False, "s",
                         "time from brake release to 90% throttle"),
}


# ─────────────────────────────────────────────────────────────
# Metric computation (once per render, stored client-side)
# ─────────────────────────────────────────────────────────────

def _driver_metrics(g: pd.DataFrame) -> dict | None:
    g = g.sort_values("t_rel")
    t = pd.to_numeric(g["t_rel"], errors="coerce").to_numpy(float)
    thr = pd.to_numeric(g["Throttle"], errors="coerce").to_numpy(float)
    spd = pd.to_numeric(g["Speed"], errors="coerce").to_numpy(float) / 3.6
    brk = g["Brake"]
    brk = (pd.to_numeric(brk, errors="coerce").fillna(0) > 0).to_numpy() \
        if brk.dtype != bool else brk.to_numpy()
    ok = np.isfinite(t) & np.isfinite(thr) & np.isfinite(spd)
    if ok.sum() < 100:
        return None
    t, thr, spd, brk = t[ok], thr[ok], spd[ok], brk[ok]

    # deceleration (smoothed) while braking
    v_s = pd.Series(spd).rolling(3, center=True, min_periods=1).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        acc = np.gradient(v_s, t)
    dec = -acc[brk & np.isfinite(acc)]
    dec = dec[dec > 0]
    peak_g = float(np.percentile(dec, 95) / 9.81) if len(dec) >= 10 else np.nan

    # brake-release events → power-application ramp
    rel_idx = np.flatnonzero(brk[:-1] & ~brk[1:]) + 1
    ramps, curves = [], []
    for i in rel_idx:
        t0 = t[i]
        win = (t >= t0) & (t <= t0 + _RAMP_HORIZON)
        if win.sum() < 5:
            continue
        tw, yw = t[win] - t0, thr[win]
        curves.append(np.interp(_RAMP_GRID, tw, yw))
        hit = np.flatnonzero(yw >= 90)
        if len(hit):
            ramps.append(float(tw[hit[0]]))
    ramp_s = float(np.median(ramps)) if len(ramps) >= 3 else np.nan
    curve = (np.mean(curves, axis=0).round(1).tolist()
             if len(curves) >= 3 else None)

    return {
        "peak_brake_g":  round(peak_g, 2) if np.isfinite(peak_g) else None,
        "brake_share":   round(float(brk.mean()) * 100, 1),
        "coast_share":   round(float(((thr < 5) & ~brk).mean()) * 100, 1),
        "full_share":    round(float((thr >= 95).mean()) * 100, 1),
        "partial_share": round(float(((thr >= 5) & (thr < 95)).mean()) * 100, 1),
        "ramp_s":        round(ramp_s, 2) if np.isfinite(ramp_s) else None,
        "lap_s":         round(float(t.max() - t.min()), 3),
        "n_brake_events": int(len(rel_idx)),
        "curve":         curve,
    }


def _build_store(blt: pd.DataFrame) -> dict:
    metrics: dict[str, dict] = {}
    for drv, g in blt.groupby("Driver_Short"):
        m = _driver_metrics(g)
        if m is None:
            continue
        m["team"] = g["Team"].iloc[0]
        metrics[drv] = m
    if len(metrics) < 2:
        return {}
    # percentile rank per trait across the field
    raw = pd.DataFrame(metrics).T
    pct: dict[str, dict] = {d: {} for d in metrics}
    for trait, (key, higher, _u, _d) in _TRAITS.items():
        s = pd.to_numeric(raw[key], errors="coerce")
        r = s.rank(pct=True, ascending=higher) * 100
        for d in metrics:
            v = r.get(d)
            pct[d][trait] = round(float(v), 0) if pd.notna(v) else None
    order = sorted(metrics, key=lambda d: metrics[d]["lap_s"])
    return {"metrics": metrics, "pct": pct, "order": order}


# ─────────────────────────────────────────────────────────────
# Figures
# ─────────────────────────────────────────────────────────────

def _radar_fig(store: dict, drv_a: str, drv_b: str | None) -> go.Figure:
    fig = go.Figure()
    traits = list(_TRAITS)
    closed = traits + [traits[0]]
    # field-median reference silhouette
    fig.add_trace(go.Scatterpolar(
        r=[50] * len(closed), theta=closed, mode="lines",
        line=dict(color=TEXT_DIM, width=1, dash="dot"),
        name="field median", hoverinfo="skip"))
    for drv, width, op in ((drv_a, 2.5, 0.25), (drv_b, 2, 0.12)):
        if not drv or drv not in store.get("pct", {}):
            continue
        p, m = store["pct"][drv], store["metrics"][drv]
        clr = TEAM_COLORS.get(m["team"], "#808080")
        vals = [p.get(tr) if p.get(tr) is not None else 50 for tr in traits]
        raws = []
        for tr in traits:
            key, _h, unit, _d = _TRAITS[tr]
            v = m.get(key)
            raws.append(f"{v}{unit}" if v is not None else "n/a")
        fig.add_trace(go.Scatterpolar(
            r=vals + [vals[0]], theta=closed, mode="lines+markers",
            name=drv, fill="toself",
            fillcolor=f"rgba({int(clr[1:3],16)},{int(clr[3:5],16)},{int(clr[5:7],16)},{op})",
            line=dict(color=clr, width=width), marker=dict(size=5),
            customdata=np.array(raws + [raws[0]], dtype=object),
            hovertemplate=(f"<b>{drv}</b> · %{{theta}}<br>"
                           "%{r:.0f}th percentile · raw %{customdata}"
                           "<extra></extra>"),
        ))
    fig.update_layout(
        polar=dict(
            bgcolor=CARD_BG,
            radialaxis=dict(visible=True, range=[0, 100],
                            tickvals=[25, 50, 75],
                            tickfont=dict(size=8, color=TEXT_DIM),
                            gridcolor=GRID_CLR, linecolor=GRID_CLR),
            angularaxis=dict(tickfont=dict(size=10, color=TEXT_MAIN),
                             gridcolor=GRID_CLR, linecolor=GRID_CLR),
        ),
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
        height=420, margin=dict(l=60, r=60, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=-0.12,
                    xanchor="center", x=0.5, bgcolor="rgba(0,0,0,0)"),
    )
    return fig


def _ramp_fig(store: dict, drv_a: str, drv_b: str | None) -> go.Figure:
    fig = go.Figure()
    curves = {d: m["curve"] for d, m in store.get("metrics", {}).items()
              if m.get("curve")}
    if curves:
        field = np.mean([c for c in curves.values()], axis=0)
        fig.add_trace(go.Scatter(
            x=_RAMP_GRID, y=field, mode="lines", name="field average",
            line=dict(color=TEXT_DIM, width=1.5, dash="dot"),
            hovertemplate="field: %{y:.0f}%<extra></extra>"))
    for drv, width in ((drv_a, 3), (drv_b, 2)):
        if not drv or drv not in curves:
            continue
        clr = TEAM_COLORS.get(store["metrics"][drv]["team"], "#808080")
        n = store["metrics"][drv]["n_brake_events"]
        fig.add_trace(go.Scatter(
            x=_RAMP_GRID, y=curves[drv], mode="lines", name=drv,
            line=dict(color=clr, width=width),
            hovertemplate=(f"<b>{drv}</b> +%{{x:.1f}}s: %{{y:.0f}}% throttle"
                           f"<extra>{n} braking zones</extra>")))
    fig.add_hline(y=90, line=dict(color=GRID_CLR, width=1, dash="dash"),
                  annotation_text="90%", annotation_font_size=9)
    theme(fig, 380, "Throttle application after brake release — best lap")
    fig.update_xaxes(title_text="Seconds after brake release")
    fig.update_yaxes(title_text="Mean throttle (%)", range=[0, 105])
    return fig


# ─────────────────────────────────────────────────────────────
# Section layout + callbacks
# ─────────────────────────────────────────────────────────────

def fingerprint_section(blt: pd.DataFrame) -> html.Div:
    """Style-fingerprint cards for the TELEMETRY tab. `blt` is the
    best-lap telemetry frame (one best lap per driver, Driver_Short/Team
    tagged) that tab_laps already builds."""
    if blt is None or blt.empty or "Throttle" not in blt.columns:
        return html.Div()
    store = _build_store(blt)
    if not store:
        return html.Div()
    order = store["order"]
    drv_a = order[0]
    drv_b = order[1] if len(order) > 1 else None
    dd_style = {"width": "160px", "backgroundColor": "#111",
                "fontSize": "0.85rem", "marginRight": "10px"}
    controls = html.Div([
        html.Span("DRIVER", style={"color": TEXT_DIM, "fontSize": "0.7rem",
                                   "letterSpacing": "1px", "marginRight": "8px"}),
        dcc.Dropdown(id="fp-driver-a",
                     options=[{"label": d, "value": d} for d in order],
                     value=drv_a, clearable=False, style=dd_style),
        html.Span("VS", style={"color": TEXT_DIM, "fontSize": "0.7rem",
                               "letterSpacing": "1px", "margin": "0 8px"}),
        dcc.Dropdown(id="fp-driver-b",
                     options=[{"label": d, "value": d} for d in order],
                     value=drv_b, clearable=True, placeholder="(nobody)",
                     style=dd_style),
    ], style={"display": "flex", "alignItems": "center",
              "marginBottom": "10px"})

    return html.Div([
        dcc.Store(id="fp-store", data=store),
        card(
            "Driver Style Fingerprint",
            html.Div([
                controls,
                dcc.Graph(id="fp-radar",
                          figure=_radar_fig(store, drv_a, drv_b), config=GFX),
            ]),
            info=("Data: six style traits measured on each driver's single "
                  "best lap of the loaded weekend — p95 braking force, time "
                  "on the brakes, coasting, full-throttle share, partial-"
                  "throttle modulation, and how fast full power is applied "
                  "after brake release. Each axis is the driver's percentile "
                  "within the loaded field (hover shows the raw value), so "
                  "the shape is a relative style silhouette, not lap time. "
                  "Why: separates HOW a driver is fast — late-brake-and-"
                  "point vs momentum-and-modulation — and makes teammate "
                  "style differences visible beyond the stopwatch."),
        ),
        card(
            "Throttle Application After Braking",
            dcc.Graph(id="fp-ramp",
                      figure=_ramp_fig(store, drv_a, drv_b), config=GFX),
            info=("Data: the average throttle trace in the 4 s after every "
                  "brake release on the best lap (≥3 braking zones needed), "
                  "aligned at the release moment; dotted grey = field "
                  "average. Why: the corner-exit signature — a steep curve "
                  "is confident, early power (or better traction); a long "
                  "plateau at partial throttle is a car/driver managing "
                  "rotation or rear grip. Compare teammates here to see who "
                  "the car obeys."),
        ),
    ])


@callback(Output("fp-radar", "figure"),
          Output("fp-ramp", "figure"),
          Input("fp-driver-a", "value"),
          Input("fp-driver-b", "value"),
          State("fp-store", "data"),
          prevent_initial_call=True)
def _update_fingerprint(drv_a, drv_b, store):
    store = store or {}
    return (_radar_fig(store, drv_a, drv_b),
            _ramp_fig(store, drv_a, drv_b))
