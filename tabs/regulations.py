"""
REGULATIONS & FINANCE block — the money and rule-book context behind upgrades.

This is a static, explanatory section (no session loads). It sits at the bottom
of the SEASON tab, next to the CAR UPGRADES board, so the "did the upgrade work?"
charts have their economic backdrop: what a team is *allowed* to spend, what a
crash costs against that budget, how much wind-tunnel time each team gets to
develop with, and what happens if you overspend.

Every figure here is sourced from the FIA Financial & Sporting Regulations and
reputable F1 media (see the ⓘ tooltips and the SOURCES card). Crash-repair
numbers are media estimates, not official FIA figures, and are labelled as such.
Update the constants below when a new season's cost cap / ATR table is published.
"""
from __future__ import annotations

import plotly.graph_objects as go
from dash import html, dcc

from f1lib.components import theme, card, GFX
from f1lib.config import (
    TEAM_COLORS, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR, CARD_BG,
)

# ── Season-specific figures (update when the FIA publishes new numbers) ──────
COST_CAP_2026 = 215      # $m — team cost cap, 2026 regulations
COST_CAP_2025 = 135      # $m — 2023–25 base (before annual inflation indexing)
PU_CAP_2026 = 130        # $m — power-unit manufacturer cost cap, 2026 (was $95m)

# Aerodynamic Testing Restrictions: baseline 100% = 320 wind-tunnel runs +
# 2,000 CFD "items" per 8-week reporting period. Sliding scale by prior
# constructors' finish: P1 gets the least, P10 the most (+5% per place).
ATR_BASELINE_RUNS = 320
ATR_BASELINE_CFD = 2000
ATR_SCALE = [(p, 70 + (p - 1) * 5) for p in range(1, 11)]  # (position, %)


# ── Small presentation helpers ──────────────────────────────────────────────
def _stat_tiles(items: list[tuple[str, str, str, str]]) -> html.Div:
    """Row of headline number tiles: (value, label, sublabel, colour)."""
    tiles = []
    for value, label, sub, clr in items:
        tiles.append(html.Div([
            html.Div(value, style={"color": clr, "fontWeight": "900",
                                   "fontSize": "1.7rem", "lineHeight": "1.1"}),
            html.Div(label, style={"color": TEXT_MAIN, "fontWeight": "700",
                                   "fontSize": "0.8rem", "marginTop": "4px"}),
            html.Div(sub, style={"color": TEXT_DIM, "fontSize": "0.7rem",
                                 "marginTop": "2px"}),
        ], style={
            "flex": "1 1 150px", "minWidth": "150px", "padding": "14px 16px",
            "background": "#12121f", "border": f"1px solid {GRID_CLR}",
            "borderRadius": "8px",
        }))
    return html.Div(tiles, style={"display": "flex", "flexWrap": "wrap",
                                  "gap": "12px", "marginBottom": "6px"})


def _p(text, **extra) -> html.P:
    style = {"color": TEXT_DIM, "fontSize": "0.85rem", "lineHeight": "1.6",
             "marginBottom": "10px"}
    style.update(extra)
    return html.P(text, style=style)


def _lead(text: str) -> html.Span:
    return html.Span(text, style={"color": TEXT_MAIN, "fontWeight": "700"})


def _bullet_col(title: str, colour: str, items: list) -> html.Div:
    lis = [html.Li(it, style={"marginBottom": "6px", "lineHeight": "1.45"})
           for it in items]
    return html.Div([
        html.Div(title, style={"color": colour, "fontWeight": "800",
                               "fontSize": "0.82rem", "letterSpacing": "0.5px",
                               "marginBottom": "8px"}),
        html.Ul(lis, style={"color": TEXT_DIM, "fontSize": "0.82rem",
                            "paddingLeft": "18px", "margin": 0}),
    ], style={"flex": "1 1 260px", "minWidth": "260px"})


def _mini_table(headers: list[str], rows: list[list], align_right_from=1) -> html.Table:
    """Compact dark table for reference figures."""
    th = [html.Th(h, style={
        "textAlign": "left" if i < align_right_from else "right",
        "padding": "6px 10px", "color": ACCENT, "fontSize": "0.72rem",
        "letterSpacing": "0.5px", "borderBottom": f"1px solid {GRID_CLR}"})
        for i, h in enumerate(headers)]
    trs = [html.Tr(th)]
    for row in rows:
        tds = [html.Td(c, style={
            "textAlign": "left" if i < align_right_from else "right",
            "padding": "6px 10px", "fontSize": "0.8rem",
            "color": TEXT_MAIN if i < align_right_from else TEXT_DIM,
            "borderBottom": f"1px solid {GRID_CLR}22"})
            for i, c in enumerate(row)]
        trs.append(html.Tr(tds))
    return html.Table(trs, style={"width": "100%", "borderCollapse": "collapse"})


# ── The ATR sliding-scale figure ────────────────────────────────────────────
def _atr_fig(height: int = 360) -> go.Figure:
    positions = [p for p, _ in ATR_SCALE]
    pct = [v for _, v in ATR_SCALE]
    # Colour the extremes with the 2025 finish (champion McLaren = tightest
    # limit; last-placed Alpine = the most development freedom); neutral middle.
    colours = []
    for p in positions:
        if p == 1:
            colours.append(TEAM_COLORS["McLaren"])
        elif p == 10:
            colours.append(TEAM_COLORS["Alpine"])
        else:
            colours.append("#3a3a55")
    runs = [round(ATR_BASELINE_RUNS * v / 100) for v in pct]
    fig = go.Figure(go.Bar(
        x=positions, y=pct, marker=dict(color=colours,
                                        line=dict(color="#000", width=1)),
        customdata=list(zip(runs, [round(ATR_BASELINE_CFD * v / 100) for v in pct])),
        hovertemplate=("Finished P%{x}<br>%{y}% of baseline<br>"
                       "≈ %{customdata[0]} tunnel runs · %{customdata[1]} CFD items"
                       "<extra></extra>"),
        text=[f"{v}%" for v in pct], textposition="outside",
        textfont=dict(size=10, color=TEXT_DIM),
    ))
    fig.add_hline(y=100, line=dict(color=TEXT_DIM, width=1, dash="dot"),
                  annotation_text="baseline (100% = 320 runs)",
                  annotation_font=dict(size=9, color=TEXT_DIM),
                  annotation_position="top left")
    theme(fig, height, "Wind-tunnel & CFD allowance by prior finish")
    fig.update_xaxes(title_text="Previous constructors' championship position",
                     tickmode="array", tickvals=positions)
    fig.update_yaxes(title_text="% of baseline aero-test allowance", range=[0, 130])
    fig.add_annotation(x=1, y=pct[0], text="2025 champion", showarrow=True,
                       arrowhead=0, ax=0, ay=-38, font=dict(size=9, color=TEAM_COLORS["McLaren"]))
    return fig


# ── The public entry point ──────────────────────────────────────────────────
def regulations_block() -> html.Div:
    """The full REGULATIONS & FINANCE content block for the SEASON tab."""
    return html.Div([

        # 1 ── Budget cap headline + explainer ------------------------------
        card(
            "The Budget Cap — 2026",
            html.Div([
                _stat_tiles([
                    (f"${COST_CAP_2026}M", "Team cost cap", "2026 regulations",
                     ACCENT),
                    (f"+${COST_CAP_2026 - COST_CAP_2025}M", "vs 2025 base",
                     f"up from ${COST_CAP_2025}M", "#00D2BE"),
                    (f"≈${PU_CAP_2026}M", "Power-unit cap",
                     "separate manufacturer cap", "#FFC0CB"),
                    ("10%", "Aero-test cut", "max cost-cap breach penalty",
                     "#FF8700"),
                ]),
                _p([
                    _lead("What it is. "),
                    "Introduced in 2021, the cost cap is a hard ceiling on what a "
                    "team may spend on the parts of the operation that make the "
                    "car go faster in a given season. It exists to stop the "
                    "richest teams simply out-spending the grid into the ground "
                    "— before the cap, the biggest budgets were roughly "
                    "$400–500M a year against perhaps $100M at the back — and to "
                    "make the sport financially sustainable so teams stop going "
                    "bust.",
                ]),
                _p([
                    _lead("2026 jump. "),
                    "The cap rises from a $135M base (2023–25, indexed for "
                    "inflation each year) to $215M for 2026. That headline "
                    "+$80M is far less generous than it looks: the separate "
                    "capital-expenditure allowance (buildings, machinery — "
                    "previously ~$36M over a rolling four years) is folded into "
                    "the main cap as annual depreciation, several previously "
                    "excluded costs are now counted, and 2026 is a ground-up new "
                    "car and power unit. The FIA's own framing is that the change "
                    "is broadly cost-neutral in real terms.",
                ]),
            ]),
            info=("Source: FIA Financial Regulations and Formula1.com. The team "
                  "cost cap governs car-performance spend; the power-unit cost "
                  "cap is a separate limit on the engine manufacturers."),
        ),

        # 2 ── What's in / out of the cap -----------------------------------
        card(
            "What Counts Against the Cap — and What Doesn't",
            html.Div([
                _p("The line the FIA draws is 'performance-related' spend. That "
                   "is why the cap is as much an accounting contest as an "
                   "engineering one — and why the biggest teams, who can afford "
                   "the most lavish excluded categories, retain an edge the cap "
                   "does not erase."),
                html.Div([
                    _bullet_col("INSIDE THE CAP (limited)", "#FF6B6B", [
                        "Car design, R&D, aerodynamics, CFD & wind-tunnel work",
                        "All car parts, spares and manufacturing",
                        "Crash & accident damage repair (a big deal — see below)",
                        "Most operational and race-team staff salaries",
                        "Garage & trackside equipment, transport of parts",
                    ]),
                    _bullet_col("OUTSIDE THE CAP (free spend)", "#4ECDC4", [
                        "Driver salaries — the sport's single biggest cheques",
                        "The three highest-paid staff (usually Team Principal + "
                        "two technical/senior leaders)",
                        "Marketing, HR, legal, finance, sustainability programmes",
                        "Race-travel, entry fees, and property/rent",
                        "Heritage-car programmes and driver-development ladders",
                    ]),
                ], style={"display": "flex", "flexWrap": "wrap", "gap": "22px"}),
            ]),
            info=("The excluded categories are the main structural criticism of "
                  "the cap: they let well-resourced teams keep spending in ways "
                  "smaller teams cannot match. Source: FIA Financial Regs."),
        ),

        # 3 ── The concern / why it matters for upgrades --------------------
        card(
            "Why It's the Real Constraint on Upgrade Strategy",
            html.Div([
                _p([
                    "Under the cap, development is a ",
                    _lead("zero-sum budget game"),
                    ". Every dollar spent on an upgrade package is a dollar not "
                    "available for spares, for the next package, or for repairing "
                    "crash damage. A team that damages several chassis early can "
                    "find itself effectively freezing development in the "
                    "run-in, because the money is simply gone.",
                ]),
                _p([
                    _lead("The trade-offs teams actually make: "),
                    "how many upgrade steps to fund across the year; whether to "
                    "keep developing the current car or switch spend to next "
                    "year's; how many spare floors/wings to build (fragile, "
                    "expensive, easily damaged); and — increasingly — how hard "
                    "to push a driver who keeps crashing. The 'did the upgrade "
                    "work?' board above is only half the story; the other half "
                    "is whether the team could afford to bring it at all.",
                ]),
                _p([
                    _lead("2026 sharpens this. "),
                    "A brand-new car and power-unit formula means development "
                    "curves are steep and unknown, so in-season upgrades matter "
                    "more than in a stable rule era — yet the cap and the "
                    "wind-tunnel limits (below) throttle how fast anyone can "
                    "actually chase the design.",
                ], marginBottom="0px"),
            ]),
            info=("This card ties the finance context to the upgrade board: the "
                  "cost cap is why upgrade cadence, spares policy and crash "
                  "damage are strategic decisions, not just engineering ones."),
        ),

        # 4 ── Crash cost ----------------------------------------------------
        card(
            "The Price of Binning It — What a Wrecked Car Costs",
            html.Div([
                _p([
                    "There is no separate 'crash budget': accident repairs come "
                    "straight out of the same capped pot as development. A single "
                    "heavy shunt can wipe out a chunk of a team's in-season "
                    "upgrade money. A fully destroyed car isn't one number — "
                    "it's the sum of its (very expensive) parts:",
                ]),
                html.Div([
                    html.Div(_mini_table(
                        ["Component", "Est. cost"],
                        [["Monocoque / chassis", "$0.7–1.5M"],
                         ["Gearbox / transmission", "≈ $0.5M"],
                         ["Front wing assembly", "$100–200k"],
                         ["Floor & bargeboards", "$150–300k"],
                         ["Halo", "≈ $17k"],
                         ["Set of wheels", "≈ $5k"],
                         ["Full write-off (rough)", "$1.5–2.5M+"]],
                    ), style={"flex": "1 1 300px", "minWidth": "300px"}),
                    html.Div([
                        html.Div("Real season damage bills (media estimates)",
                                 style={"color": ACCENT, "fontWeight": "800",
                                        "fontSize": "0.75rem", "marginBottom": "8px"}),
                        _mini_table(
                            ["Case", "Est. cost"],
                            [["Williams — full 2024 season", "≈ €13.8M"],
                             ["Colapinto — 2024 (Williams)", "≈ €5.0M"],
                             ["Albon — 2024 (Williams)", "≈ €5.0M"],
                             ["Bortoleto — full 2025 (Sauber)", "≈ $4.0M"],
                             ["  └ São Paulo GP alone", "≈ $2.4M"]],
                        ),
                    ], style={"flex": "1 1 300px", "minWidth": "300px"}),
                ], style={"display": "flex", "flexWrap": "wrap", "gap": "22px",
                          "marginBottom": "10px"}),
                _p([
                    "Williams' ~€13.8M of 2024 crash damage was roughly a tenth "
                    "of the entire cost cap — money that could not go into "
                    "developing the car. This is why teams quietly rank drivers "
                    "on a 'damage cost' table, and why a crash-prone rookie is a "
                    "genuine championship-development liability, not just a "
                    "Sunday-afternoon setback.",
                ], marginBottom="0px"),
            ]),
            info=("Component and season-damage figures are ESTIMATES compiled by "
                  "F1 media (PlanetF1, Newsweek, f1oversteer), not official FIA "
                  "numbers — teams do not publish part prices. Directionally "
                  "reliable, not exact."),
        ),

        # 5 ── Aero Testing Restrictions ------------------------------------
        card(
            "Aerodynamic Testing Restrictions (ATR) — the 'development handicap'",
            html.Div([
                _p([
                    "Separate from the money cap, the FIA limits ",
                    _lead("how much wind-tunnel and CFD (simulation) time"),
                    " each team gets — and it is deliberately unequal. On a "
                    "sliding scale set by the previous constructors' finish, the "
                    "champion gets the least development time and the last-placed "
                    "team the most, to help the field converge. Baseline (100%) "
                    "is 320 wind-tunnel runs and 2,000 CFD items per eight-week "
                    "period; the table is reset twice a year (1 Jan and 1 Jul).",
                ]),
                dcc.Graph(figure=_atr_fig(), config=GFX),
                _p([
                    "For 2026 the first-half allocation follows the 2025 order, "
                    "so champion McLaren develops with ~70% of baseline while "
                    "Alpine gets ~115%. It's a real handicap on upgrade pace: "
                    "the team that most wants to keep winning has the least tunnel "
                    "time to refine next season's radically new car. A new entrant "
                    "(Cadillac in 2026) gets a special allocation while it has no "
                    "prior finish to rank.",
                ], marginBottom="0px"),
            ]),
            info=("Source: FIA Sporting Regulations, Appendix (Aerodynamic "
                  "Testing Restrictions) and Formula1.com. Scale: P1 = 70% of "
                  "baseline, +5% per position, to P10 = 115%."),
        ),

        # 6 ── Breach penalties ---------------------------------------------
        card(
            "What Happens If You Overspend",
            html.Div([
                _p("The FIA classifies breaches into procedural (late/incorrect "
                   "filing), minor (overspend under 5%) and material (5% or "
                   "more). Penalties range from fines to points deductions, "
                   "reduced aero testing, or in the worst case suspension from "
                   "the championship — the sanction is negotiated or imposed "
                   "case by case."),
                html.Div([
                    _bullet_col("BREACH TIERS", ACCENT, [
                        "Procedural — paperwork wrong or late",
                        "Minor — overspend below 5% of the cap",
                        "Material — overspend of 5% or more",
                    ]),
                    _bullet_col("POSSIBLE SANCTIONS", "#FF8700", [
                        "Financial penalty (fine)",
                        "Constructors'/drivers' points deduction",
                        "Reduced wind-tunnel & CFD allowance",
                        "Reduction of the following year's cost cap",
                        "Suspension / exclusion (severe material breaches)",
                    ]),
                ], style={"display": "flex", "flexWrap": "wrap", "gap": "22px",
                          "marginBottom": "8px"}),
                _p([
                    _lead("Precedent — Red Bull, 2021. "),
                    "The only major cost-cap case so far: Red Bull was found to "
                    "have committed a minor overspend (~£1.8M, about 1.6% over "
                    "the cap) plus a procedural breach. The FIA found no bad "
                    "faith, but still imposed a $7M fine and a 10% cut to its "
                    "wind-tunnel/CFD time for 12 months — and rivals argued even "
                    "that was too lenient, given how valuable aero-test time is. "
                    "It set the tone: the sporting penalty (development time) "
                    "hurts more than the cash.",
                ], marginBottom="0px"),
            ]),
            info=("Source: FIA Financial Regulations and the FIA's 2022 "
                  "'Accepted Breach Agreement' with Red Bull over 2021."),
        ),

        # 7 ── 2026 reset context -------------------------------------------
        card(
            "2026 Rule Reset — Why Development Context Changes",
            html.Div([
                _p("2026 is the biggest rule change in a generation, which is "
                   "why the finance and upgrade picture matters more than usual. "
                   "The car and the power unit are both new, so early-season "
                   "development gains (and mistakes) are unusually large."),
                html.Div([
                    _bullet_col("POWER UNIT", "#00D2BE", [
                        "~50/50 split between combustion (~400kW) and electric "
                        "(~350kW, up from 120kW)",
                        "MGU-H removed — simpler, cheaper engines",
                        "100% advanced sustainable fuel (non-food feedstock)",
                        "PU manufacturer cost cap ≈ $130M, with allowances for "
                        "new/underperforming makers",
                    ]),
                    _bullet_col("CHASSIS & AERO", "#FF8700", [
                        "Smaller cars: wheelbase −200mm, ~100mm narrower",
                        "Lighter: minimum weight down to 768kg (from 800kg)",
                        "Active aero — driver-adjustable front & rear wings",
                        "'Manual Override' overtake boost replaces DRS",
                    ]),
                ], style={"display": "flex", "flexWrap": "wrap", "gap": "22px"}),
                _p([
                    _lead("Bottom line for upgrades: "),
                    "with a clean-sheet formula, the teams that read the new "
                    "rules best early — and can afford to iterate under the cap "
                    "and their ATR limit — set the pecking order. Watch the "
                    "qualifying- and race-pace trend charts above for who is "
                    "developing fastest through the year.",
                ], marginBottom="0px"),
            ]),
            info=("Source: Formula1.com 2026 regulations summary and FIA 2026 "
                  "Technical & Power Unit Regulations."),
        ),

        # 8 ── Sources ------------------------------------------------------
        html.Div([
            html.Span("Sources & caveat  ", style={
                "color": TEXT_MAIN, "fontWeight": "700", "fontSize": "0.75rem"}),
            html.Span(
                "FIA Financial, Sporting, Technical & Power Unit Regulations "
                "(api.fia.com) · Formula1.com official explainers · The Race, "
                "Motorsport.com, PlanetF1, Newsweek, f1oversteer for figures and "
                "damage estimates. Cost-cap and ATR figures are official; "
                "crash-repair costs are media estimates (teams don't publish part "
                "prices). Figures reflect the 2026 regulations as published; "
                "update the constants in tabs/regulations.py when the FIA revises "
                "them.",
                style={"color": TEXT_DIM, "fontSize": "0.72rem",
                       "lineHeight": "1.5"}),
        ], style={"padding": "12px 14px", "background": "#0e0e18",
                  "border": f"1px dashed {GRID_CLR}", "borderRadius": "8px",
                  "marginTop": "4px"}),
    ])
