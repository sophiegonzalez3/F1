"""
Gearbox component-pool / grid-penalty-risk tracker for the SEASON FORM section
— the non-power-unit companion to tabs/pu_pool.py.

The power unit is not the only part of the car on a strict FIA season budget:
the gearbox is too, and it is in fact the *only* non-PU component with a
sanctioned allocation. Under the 2026 Sporting Regulations (Article B8.3), the
transmission is split into two "restricted-number components" (RNCs):

  • Gearbox case & cassette
  • Gearbox driveline, gear-change & auxiliary components

Each driver may use a maximum number of each per season (4 on a calendar of up
to 23 races — 2026 has 22 — rising to 5 for 24-25 races). Fit one over the
allowance and the driver takes a 5-place grid penalty at that race for each RNC
over the limit. Uniquely, if a driver goes over on BOTH RNC groups
on the same gearbox assembly at once, the penalty is the *maximum* of the two
(so 5), not the sum — the FIA does not double-stack the gearbox penalty.

Like the PU pool, this is NOT derivable from the results archive: the RNC counts
live in FIA decision documents, not the timing data. It reads a curated,
human-maintained table (data/gearbox_penalties.csv) and shows how deep into each
RNC's allowance every driver has gone — the closer a cell is to the limit, the
closer that driver is to a gearbox grid penalty. Update the CSV as rounds pass.
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

_GB_PATH = Path("data/gearbox_penalties.csv")
_CAL_PATH = Path("data/season_calendar.csv")
_GB_COLS = ["season", "driver", "team",
            "gc_case", "gc_drive",
            "penalties_places", "as_of", "source"]
# The two gearbox RNC groups (short label used on the heatmap axis).
_ELEMENTS = [("gc_case", "Case &<br>Cassette"),
             ("gc_drive", "Driveline /<br>Gear-change")]
# Grid places lost for the first (and each subsequent) unit over the allowance.
_PENALTY_PLACES = 5

# Plain-English "what is it / roughly what does it cost" per RNC group, for the
# hoverable legend under the heatmap (Plotly can't tooltip axis labels).
_ELEMENT_INFO = {
    "gc_case": ("Gearbox case & cassette",
                "The gearbox housing plus the removable 'cassette' that carries "
                "the gear cluster — the structural core of the transmission, and "
                "a stressed chassis member the rear suspension hangs off. "
                "Regs: Technical Articles 9.1.5 & 9.1.7. "
                "Rough cost: the casing is a major carbon/titanium part, ~€0.5–1m."),
    "gc_drive": ("Driveline, gear-change & auxiliary",
                 "The moving guts: driveshafts, the hydraulic/electronic "
                 "gear-selection mechanism and the ancillary components that "
                 "operate the box. Wear-and-tear parts, so the ones most likely "
                 "to force an early change. Regs: Technical Articles 9.1.2–9.1.4. "
                 "Rough cost: ~€0.3–0.6m per fresh set."),
}


def _race_count(season: int) -> int:
    """Number of Grands Prix in the season, from the calendar (default 22)."""
    try:
        if _CAL_PATH.exists():
            c = pd.read_csv(_CAL_PATH)
            n = int((c["season"] == season).sum())
            if n:
                return n
    except Exception:
        pass
    return 22


def _gb_limit(season: int) -> int:
    """Per-RNC season allowance from the FIA table: 4 up to 23 races, then 5."""
    return 5 if _race_count(season) >= 24 else 4


def _limits(season: int) -> dict[str, int]:
    lim = _gb_limit(season)
    return {e: lim for e, _ in _ELEMENTS}


def _gb_legend() -> html.Div:
    """A row of hoverable chips explaining each gearbox RNC group."""
    chips = []
    for e, lbl in _ELEMENTS:
        name, text = _ELEMENT_INFO[e]
        chips.extend(tip(
            lbl.replace("<br>", " "),
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
        html.Span("The two gearbox parts on an allowance  ", style={
            "color": ACCENT, "fontWeight": "700", "fontSize": "0.66rem",
            "letterSpacing": "1px", "textTransform": "uppercase",
            "marginRight": "8px"}),
        *chips,
    ], style={"marginTop": "8px", "lineHeight": "1.9"})


_GB_CACHE: dict = {"mtime": None, "df": pd.DataFrame(columns=_GB_COLS)}


def _load_gb() -> pd.DataFrame:
    if _GB_PATH.exists():
        try:
            df = pd.read_csv(_GB_PATH)
            for c in _GB_COLS:
                if c not in df.columns:
                    df[c] = pd.NA
            df["season"] = pd.to_numeric(df["season"], errors="coerce").astype("Int64")
            for e, _ in _ELEMENTS:
                df[e] = pd.to_numeric(df[e], errors="coerce")
            df["penalties_places"] = pd.to_numeric(
                df["penalties_places"], errors="coerce").fillna(0).astype(int)
            for c in ("driver", "team", "as_of", "source"):
                df[c] = df[c].fillna("").astype(str).str.strip()
            return df[_GB_COLS].dropna(subset=[e for e, _ in _ELEMENTS])
        except Exception as _exc:
            print(f"Gearbox component pool  : failed to read ({_exc})")
    return pd.DataFrame(columns=_GB_COLS)


def gb_df(season: int) -> pd.DataFrame:
    try:
        mtime = _GB_PATH.stat().st_mtime if _GB_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _GB_CACHE["mtime"]:
        _GB_CACHE["df"] = _load_gb()
        _GB_CACHE["mtime"] = mtime
    df = _GB_CACHE["df"]
    return df[df["season"] == season].copy() if not df.empty else df


def _gb_heatmap_fig(season: int) -> go.Figure:
    d = gb_df(season)
    fig = go.Figure()
    if d.empty:
        fig.update_layout(paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                          height=300, font=dict(color=TEXT_MAIN))
        return fig

    limits_map = _limits(season)
    ecols = [e for e, _ in _ELEMENTS]
    # Risk sort: fullest RNC first (max used/limit), then total burned.
    d["max_ratio"] = d.apply(
        lambda r: max(r[e] / limits_map[e] for e in ecols), axis=1)
    d["total"] = d[ecols].sum(axis=1)
    d = d.sort_values(["max_ratio", "total"], ascending=[True, True])

    drivers = d["driver"].tolist()
    used = d[ecols].to_numpy(dtype=float)
    limits = np.array([limits_map[e] for e in ecols], dtype=float)
    ratio = used / limits                       # colour = closeness to the limit
    headroom = limits - used

    xlabels = [f"{lbl}<br>(max {limits_map[e]})" for e, lbl in _ELEMENTS]
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
        title=dict(text=f"Gearbox pool used – {season} · redder = closer "
                        "to a grid penalty", font=dict(size=13)),
    )
    fig.update_xaxes(side="top", tickfont=dict(size=10), showgrid=False)
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=10), showgrid=False)
    return fig


def gearbox_pool_card(season: int):
    """Gearbox RNC-pool tracker for SEASON FORM, or None if no data for the
    season (only maintained for the 2026+ era). Sibling of pu_pool_card."""
    d = gb_df(season)
    if d.empty:
        return None
    limits_map = _limits(season)
    lim = next(iter(limits_map.values()))
    as_of = d["as_of"].iloc[0] if d["as_of"].any() else ""
    # Unlike PU elements — which the FIA publishes per driver in a Technical
    # Delegate's Report every event — there is no public per-driver gearbox RNC
    # table (re-verified 2026-07-25). Until real figures exist the shipped file
    # is a placeholder, and the card has to say so rather than imply FIA data.
    is_seed = d["source"].str.contains("SEED", case=False, na=False).any()
    took = d[d["penalties_places"] > 0]
    pen_line = (f" {len(took)} driver(s) have taken a gearbox grid penalty so far."
                if not took.empty
                else " No gearbox grid penalties taken at the data's cutoff.")
    _ecols = [e for e, _ in _ELEMENTS]
    _mr = d.apply(lambda r: max(r[e] / limits_map[e] for e in _ecols), axis=1)
    _closest = d.loc[_mr.idxmax(), "driver"]
    _plain = (
        ("Heads up: the per-driver counts below are placeholders, not real FIA "
         "figures — treat the shape of the card, not the numbers, as the point. "
         if is_seed else "")
        + "The gearbox is the only part outside the engine that F1 rations: each "
        f"driver gets {lim} of each of two gearbox 'parts' for the whole season. "
        "Go over and they drop 5 grid places, exactly like an engine penalty. "
        + (f"{len(took)} driver(s) have already taken one, and {_closest} is now "
           "closest to the next gearbox limit." if not took.empty else
           f"None have been penalised yet; {_closest} is closest to the limit."))
    return card(
        [*gloss("gearbox", "Gearbox"), " Pool & Penalty Risk"],
        html.Div([
            dcc.Graph(figure=_gb_heatmap_fig(season), config=GFX),
            _gb_legend(),
            html.P(
                ["PLACEHOLDER DATA — the FIA publishes no per-driver gearbox "
                 "RNC table (checked 2026-07-25), so these counts are an "
                 "unverified seed baseline, not real usage. The allowances and "
                 "penalty rules shown are real."],
                style={"color": "#e8a33d", "fontSize": "0.72rem",
                       "fontWeight": "700", "marginTop": "4px",
                       "marginBottom": "2px"}) if is_seed else None,
            html.P(
                ["Curated from ", html.Code("data/gearbox_penalties.csv"),
                 f", current to {as_of}. "
                 "The gearbox is the only non-power-unit part on an FIA season "
                 "allowance. Cells 'at limit' mean the next unit of that part "
                 "brings a 5-place grid penalty."],
                style={"color": TEXT_DIM, "fontSize": "0.72rem",
                       "marginTop": "4px", "marginBottom": 0}),
        ]),
        info=(("PLACEHOLDER: the per-driver counts are a seed baseline, not "
               "sourced FIA figures — no public per-driver gearbox RNC table "
               "exists. " if is_seed else "")
              + "Data: curated data/gearbox_penalties.csv — per-driver gearbox "
              "restricted-number-component (RNC) usage vs. the 2026 season "
              f"allowance ({lim} each for case & cassette and for driveline / "
              "gear-change / auxiliary, per FIA Sporting Reg B8.3). Colour = "
              "used/limit, so redder rows are closer to a grid penalty (5 places "
              "for each RNC over the limit; going over both groups on one "
              "assembly at once still costs only 5, not 10). This is NOT in the "
              "results archive, so it is hand-maintained." + pen_line),
        plain=_plain,
    )
