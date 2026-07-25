"""
Power-unit component-pool / grid-penalty-risk tracker for the SEASON FORM
section (2026+, new-PU era).

Unlike the reliability card, this is NOT derivable from the results archive —
the FIA component pool and penalties aren't in it. It reads a curated,
human-maintained table (data/pu_penalties.csv, seeded from Formula1.com's
per-driver usage audit) and shows how deep into each element's season allowance
every driver has gone. The closer a cell is to the limit, the closer that driver
is to a grid penalty (10 places for the first component over the allowance, +5
for each after; >15 places = back of grid).

2026 season allowance (incl. the one-off 'bonus' unit): ICE 4, Turbo 4, MGU-K 3,
Energy Store 3, Control Electronics 3, Exhaust 4, PU Ancillaries 6. Update the
CSV as rounds pass.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc

from f1lib.components import card, tip, GFX
from f1lib.glossary import gloss
from f1lib.config import CARD_BG, TEXT_MAIN, TEXT_DIM, GRID_CLR, ACCENT

_PU_PATH = Path("data/pu_penalties.csv")
_PU_COLS = ["season", "driver", "team", "pu_supplier",
            "ice", "tc", "mguk", "es", "ce", "ex", "anc",
            "penalties_places", "penalty_event", "as_of", "source"]
_ELEMENTS = [("ice", "ICE"), ("tc", "Turbo"), ("mguk", "MGU-K"),
             ("es", "ES"), ("ce", "CE"), ("ex", "EX"), ("anc", "ANC")]
# 2026 per-season allowance per element (one bonus unit vs. the 2027 baseline).
_LIMITS_2026 = {"ice": 4, "tc": 4, "mguk": 3, "es": 3, "ce": 3, "ex": 4,
                "anc": 6}

# Plain-English "what is it / roughly what does it cost" per element, for the
# hoverable legend under the heatmap. Costs are rough order-of-magnitude
# figures — the FIA caps a customer's full-season PU supply near €15m, and
# individual element prices aren't published, so treat these as ballparks.
_ELEMENT_INFO = {
    "ice": ("Internal Combustion Engine",
            "The 1.6-litre V6 turbo petrol engine itself — the heart of the "
            "power unit, now running on 100% sustainable fuel. It's the single "
            "most expensive and most heavily developed element. "
            "Rough cost: ~€8–10m to develop a spec; the priciest unit in the pool."),
    "tc": ("Turbocharger",
           "Forces compressed air into the engine for more power. In the 2026 "
           "rules it's a single turbo with no heat-recovery motor (the old "
           "MGU-H is gone). Rough cost: ~€1–2m."),
    "mguk": ("Motor Generator Unit – Kinetic",
             "The hybrid electric motor: recovers braking energy and redeploys "
             "it as a boost. Under 2026 rules it's much bigger — up to ~350 kW "
             "(~470 hp), roughly half the car's total power. "
             "Rough cost: ~€1–3m."),
    "es": ("Energy Store",
           "The battery pack that stores the energy the MGU-K recovers, ready "
           "to fire back out on the straights. Rough cost: ~€1m."),
    "ce": ("Control Electronics",
           "The brains — ECU and power electronics that manage the engine and "
           "the hybrid system. Rough cost: ~€0.5–1m."),
    "ex": ("Exhaust",
           "The exhaust system routing spent gases out and feeding the turbo. "
           "Cheapest element, but still on a strict allowance. "
           "Rough cost: ~€0.1–0.3m."),
    "anc": ("Power Unit ANCillary component",
            "New for 2026: the supporting hardware wrapped around the engine — "
            "the oil, water, fuel and hydraulic pumps, the power-unit wiring "
            "loom and sensors, and the coolers that keep everything in range. "
            "Individually humble parts, but any one of them failing stops the "
            "car. Swapped more often than anything else, and carries the most "
            "generous allowance of the seven elements (6). "
            "Rough cost: ~€0.3–0.8m a set."),
}


def _pu_legend() -> html.Div:
    """A row of hoverable chips explaining each PU element and its rough cost.
    Plotly can't attach tooltips to axis labels, so the explanations live here
    instead — using tip() so they work in every browser, including touch."""
    chips = []
    for e, lbl in _ELEMENTS:
        name, text = _ELEMENT_INFO[e]
        chips.extend(tip(
            lbl,
            [html.Strong(name), html.Br(), text],
            style={
                "display": "inline-block", "cursor": "help",
                "background": "#12233d", "color": TEXT_MAIN,
                "border": f"1px solid {GRID_CLR}", "borderRadius": "4px",
                "padding": "2px 9px", "margin": "0 6px 6px 0",
                "fontSize": "0.72rem", "fontWeight": "700",
                "letterSpacing": "0.5px",
            }))
    return html.Div([
        html.Span("What each part is  ", style={
            "color": ACCENT, "fontWeight": "700", "fontSize": "0.66rem",
            "letterSpacing": "1px", "textTransform": "uppercase",
            "marginRight": "8px"}),
        *chips,
    ], style={"marginTop": "8px", "lineHeight": "1.9"})

_PU_CACHE: dict = {"mtime": None, "df": pd.DataFrame(columns=_PU_COLS)}


def _load_pu() -> pd.DataFrame:
    if _PU_PATH.exists():
        try:
            df = pd.read_csv(_PU_PATH)
            for c in _PU_COLS:
                if c not in df.columns:
                    df[c] = "" if c not in ("season", *[e for e, _ in _ELEMENTS],
                                            "penalties_places") else pd.NA
            df["season"] = pd.to_numeric(df["season"], errors="coerce").astype("Int64")
            for e, _ in _ELEMENTS:
                df[e] = pd.to_numeric(df[e], errors="coerce")
            df["penalties_places"] = pd.to_numeric(
                df["penalties_places"], errors="coerce").fillna(0).astype(int)
            for c in ("driver", "team", "pu_supplier",
                      "penalty_event", "as_of", "source"):
                df[c] = df[c].fillna("").astype(str).str.strip()
            return df[_PU_COLS].dropna(subset=[e for e, _ in _ELEMENTS])
        except Exception as _exc:
            print(f"PU component pool       : failed to read ({_exc})")
    return pd.DataFrame(columns=_PU_COLS)


def pu_df(season: int) -> pd.DataFrame:
    try:
        mtime = _PU_PATH.stat().st_mtime if _PU_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _PU_CACHE["mtime"]:
        _PU_CACHE["df"] = _load_pu()
        _PU_CACHE["mtime"] = mtime
    df = _PU_CACHE["df"]
    return df[df["season"] == season].copy() if not df.empty else df


def _pu_heatmap_fig(season: int) -> go.Figure:
    d = pu_df(season)
    fig = go.Figure()
    if d.empty:
        fig.update_layout(paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                          height=300, font=dict(color=TEXT_MAIN))
        return fig

    ecols = [e for e, _ in _ELEMENTS]
    # Risk sort: fullest element first (max used/limit), then total burned.
    d["max_ratio"] = d.apply(
        lambda r: max(r[e] / _LIMITS_2026[e] for e in ecols), axis=1)
    d["total"] = d[ecols].sum(axis=1)
    d = d.sort_values(["max_ratio", "total"], ascending=[True, True])

    drivers = d["driver"].tolist()
    used = d[ecols].to_numpy(dtype=float)
    limits = np.array([_LIMITS_2026[e] for e in ecols], dtype=float)
    ratio = used / limits                       # colour = closeness to the limit
    headroom = limits - used

    xlabels = [f"{lbl}<br>(max {_LIMITS_2026[e]})" for e, lbl in _ELEMENTS]
    text = [[f"{int(v)}" for v in row] for row in used]
    custom = np.dstack([np.broadcast_to(limits, used.shape), headroom])

    fig.add_trace(go.Heatmap(
        z=ratio, x=xlabels, y=drivers, text=text, texttemplate="%{text}",
        textfont=dict(size=11, color="#ffffff"),
        customdata=custom,
        # ratio 1.0 (at the allowance) sits at 0.75 of the scale = amber; only
        # >1.0 (over the allowance = penalty territory) tips into red.
        colorscale=[[0.0, "#12233d"], [0.45, "#1c5cab"],
                    [0.66, "#3987e5"], [0.75, "#fab219"], [1.0, "#e66767"]],
        zmin=0.0, zmax=4/3, zmid=None,
        xgap=2, ygap=2,
        colorbar=dict(title=dict(text="used / limit", side="right"),
                      tickvals=[0, 1.0, 4/3],
                      ticktext=["empty", "at limit", "over"],
                      thickness=12, len=0.7),
        hovertemplate=("<b>%{y}</b> · %{x}<br>Used %{text} of "
                       "%{customdata[0]:.0f} · %{customdata[1]:.0f} spare"
                       "<extra></extra>"),
    ))
    fig.update_layout(
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
        height=max(360, 22 * len(drivers) + 150),
        margin=dict(l=54, r=20, t=54, b=54),
        title=dict(text=f"Power-unit pool used – {season} · redder = closer "
                        "to a grid penalty", font=dict(size=13)),
    )
    fig.update_xaxes(side="top", tickfont=dict(size=10), showgrid=False)
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=10), showgrid=False)
    return fig


def pu_pool_card(season: int):
    """PU component-pool tracker for SEASON FORM, or None if no data for the
    season (only maintained for the 2026+ new-PU era)."""
    d = pu_df(season)
    if d.empty:
        return None
    as_of = d["as_of"].iloc[0] if d["as_of"].any() else ""
    took = d[d["penalties_places"] > 0]
    pen_line = (f" {len(took)} driver(s) have taken grid penalties so far."
                if not took.empty
                else " No grid penalties taken at the data's cutoff.")
    _ecols = [e for e, _ in _ELEMENTS]
    _mr = d.apply(lambda r: max(r[e] / _LIMITS_2026[e] for e in _ecols), axis=1)
    _closest = d.loc[_mr.idxmax(), "driver"]
    _plain = (
        "Modern F1 engines — 'power units' — must last many races on a strict "
        "parts budget. Go over the season allowance and the driver drops grid "
        "places as a penalty at the next race. "
        + (f"{len(took)} driver(s) have already taken one, and {_closest} is "
           "now closest to the next limit." if not took.empty else
           f"None have been penalised yet; {_closest} is closest to the limit."))
    return card(
        [*gloss("power unit", "Power-Unit"), " Pool & Penalty Risk"],
        html.Div([
            dcc.Graph(figure=_pu_heatmap_fig(season), config=GFX),
            _pu_legend(),
            html.P(
                ["Curated from ", html.Code("data/pu_penalties.csv"),
                 f" (Formula1.com component audit, current to {as_of}). "
                 "Component counts are as-reported; update the CSV as the "
                 "season runs. Cells at 'at limit' mean the next unit of that "
                 "element brings a grid penalty."],
                style={"color": TEXT_DIM, "fontSize": "0.72rem",
                       "marginTop": "4px", "marginBottom": 0}),
        ]),
        info=("Data: curated data/pu_penalties.csv — per-driver power-unit "
              "element usage vs. the 2026 season allowance (ICE 4, Turbo 4, "
              "MGU-K 3, ES 3, CE 3, EX 4, ANC 6). Colour = used/limit, so redder rows "
              "are closer to a grid penalty (10 places for the first component "
              "over, +5 each after). This is NOT in the results archive, so it "
              "is hand-maintained." + pen_line),
        plain=_plain,
    )
