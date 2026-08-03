"""
F1 Dashboard – shared UI components & Plotly theme
==================================================
Pure presentation helpers with no data dependencies: import these from any
tab module instead of reaching into app.py. Everything here depends only on
config.py, dash, and plotly — never on loaded session data.
"""
from __future__ import annotations

import uuid

from dash import html, dash_table
import dash_bootstrap_components as dbc

from f1lib.config import (
    CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
)

# ── Plotly theme ─────────────────────────────────────────────
# HOVER_FMT is the house rounding rule, applied at the axis so it reaches every
# trace that does not spell out its own format. Without it Plotly prints raw
# float64 into the hover box — "1.2999999999999998% vs median" — which is
# unreadable at a glance and makes a measurement look more precise than it is.
# "~" trims trailing zeros, so 1.5 stays "1.5" while 1.23456 becomes "1.235".
# Three decimals is the ceiling: lap times need them, nothing here needs more.
HOVER_FMT = ".3~f"

BASE = dict(
    paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
    font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=12),
    xaxis=dict(gridcolor=GRID_CLR, zeroline=False),
    yaxis=dict(gridcolor=GRID_CLR, zeroline=False),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1),
    margin=dict(l=60, r=20, t=50, b=50),
)

# BASE minus the two axis entries, for figures that manage their own axes
# (make_subplots, where layout.xaxis only reaches the first panel). Pair it
# with theme_axes() so those figures still get the house hover rounding.
BASE_NO_AXES = {k: v for k, v in BASE.items() if k not in ("xaxis", "yaxis")}


def _is_temporal(fig, letter: str) -> bool:
    """True when this figure's x (or y) axis carries dates.

    Matters because Plotly reads `hoverformat` on a date axis as a d3-TIME
    format, so a numeric one would render literally — the hover would read
    ".3~f" instead of a date. Checked against the trace data rather than
    layout.type, because callers routinely set type="date" AFTER theming.
    """
    import numpy as _np
    ax_type = getattr(getattr(fig.layout, f"{letter}axis", None), "type", None)
    if ax_type == "date":
        return True
    for tr in fig.data:
        vals = getattr(tr, letter, None)
        if vals is None or _np.ndim(vals) == 0:
            continue
        arr = _np.asarray(vals)
        if arr.dtype.kind == "M":                 # datetime64
            return True
        if arr.dtype == object and arr.size:
            head = arr.flat[0]
            if hasattr(head, "year") and hasattr(head, "month"):
                return True
    return False


def theme_axes(fig, **kw):
    """Apply the shared axis styling — including hover rounding — to EVERY
    axis of a figure, subplots included. update_*axes with no selector hits
    all of them, which is exactly what layout.xaxis cannot do.

    Date axes keep their own formatting; everything else gets HOVER_FMT.
    """
    fig.update_xaxes(gridcolor=GRID_CLR, zeroline=False, **kw)
    fig.update_yaxes(gridcolor=GRID_CLR, zeroline=False, **kw)
    if not _is_temporal(fig, "x"):
        fig.update_xaxes(hoverformat=HOVER_FMT)
    if not _is_temporal(fig, "y"):
        fig.update_yaxes(hoverformat=HOVER_FMT)
    return fig


def theme(fig, h=450, t=""):
    # BASE carries no axis hoverformat: theme_axes decides per figure, since a
    # numeric format on a date axis renders as literal text.
    fig.update_layout(**BASE, height=h, title=t)
    return theme_axes(fig)


GFX = {"displayModeBar": False}

TABLE_STYLE = dict(
    style_table={"overflowX": "auto"},
    style_cell={"backgroundColor": CARD_BG, "color": TEXT_MAIN,
                "border": f"1px solid {GRID_CLR}", "fontSize": "12px", "padding": "8px"},
    style_header={"backgroundColor": "#09091A", "fontWeight": "bold",
                  "color": ACCENT, "border": f"1px solid {GRID_CLR}"},
    sort_action="native", filter_action="native", page_size=20,
)


# ── Building blocks ──────────────────────────────────────────

def tip(children, text, placement="bottom", style=None):
    """Hover tooltip that works in every browser. Native `title=` tooltips
    are unreliable in Safari and never show on touch devices, so bind a
    Bootstrap tooltip to a uniquely-id'd span instead.
    Returns [span, dbc.Tooltip] — splice both into the parent's children."""
    tid = f"tip-{uuid.uuid4().hex[:12]}"
    return [
        html.Span(children, id=tid, style=style),
        dbc.Tooltip(text, target=tid, placement=placement,
                    delay={"show": 150, "hide": 50}, class_name="app-tooltip"),
    ]


def plain_line(text):
    """A newcomer-facing 'In plain terms: …' strip — a plain-English reading of
    what the card above is actually saying, for someone who can't yet read the
    chart. Distinct from `info` (the ⓘ hover, which explains the *data* to
    someone who already speaks F1). `text` may be a string or a children list
    (so it can splice in gloss() terms). Returns None-safe: pass None → nothing."""
    if text is None:
        return None
    body = text if isinstance(text, list) else [text]
    return html.Div(
        [html.Span("In plain terms  ", style={
            "color": ACCENT, "fontWeight": "700", "fontSize": "0.68rem",
            "letterSpacing": "1px", "textTransform": "uppercase"}), *body],
        style={"borderLeft": f"3px solid {ACCENT}", "background": "#0E0E1F",
               "padding": "8px 12px", "marginTop": "12px", "borderRadius": "4px",
               "color": TEXT_MAIN, "fontSize": "0.8rem", "lineHeight": "1.45",
               "fontStyle": "italic"})


# ── Speed / pace measure badges ──────────────────────────────
# A card that shows any of these wears the matching badge in its header, so you
# never have to infer which one from the title. Colours: warm = single lap,
# cool = sustained running, grey = a classification result rather than a speed
# measurement.
#
# HOUSE RULE — SPEED vs PACE
# SPEED is instantaneous: one flat-out lap. PACE is a rate held over distance:
# many laps, race fuel, wearing tyres. It is the same distinction runners and
# cyclists use, and it is load-bearing here.
#
# The sport itself does say "qualifying pace" and "one-lap pace", and that is
# perfectly good English. It is banned in this dashboard's copy anyway, because
# three of the five measures below would otherwise all be called "pace" — at
# which point the badge stops carrying information and you have to read the
# qualifier to know whether you are looking at 90 seconds or 90 minutes. The
# Upgrade Impact trend, which plots both on one chart in the same units, is
# what made that unworkable.
#
# tests/test_vocabulary.py enforces the rule on new UI strings.
PACE_MEASURES: dict[str, tuple[str, str, str]] = {
    # key: (label, colour, definition)
    "one-lap": (
        "ONE-LAP SPEED", "#FF8A3D",
        "ONE-LAP SPEED — a single flat-out lap: low fuel, fresh tyres, maximum "
        "attack. This is qualifying speed. Called SPEED, not pace, on purpose: "
        "in this dashboard 'pace' always means a rhythm sustained over many "
        "laps. It says nothing about how the car behaves over a stint, and a "
        "car can be strong here and weak on Sunday."),
    "race": (
        "RACE PACE", "#3DD6C4",
        "RACE PACE — the MEDIAN of clean green-flag laps on race fuel and "
        "wearing tyres, corrected for fuel burn and track evolution, with "
        "dirty-air laps excluded. A rhythm sustained over many laps, which is "
        "what actually decides races. Not a single fast lap."),
    "stint": (
        "STINT PACE", "#5BA7FF",
        "STINT PACE — race pace narrowed to one continuous run on one tyre "
        "compound. Same measure as race pace, but per-compound, so it separates "
        "'the car is quick' from 'the car is quick on this tyre'."),
    "result": (
        "RESULT", "#8A8FA3",
        "RESULT — where the car actually ended up (grid slot, classification, "
        "gap to pole), not a like-for-like measurement of how quick the car is. "
        "It bakes in "
        "session progression, traffic, penalties and mistakes. Use it for what "
        "happened, not for how fast the car is."),
    "predicted": (
        "PREDICTED", "#B47BEA",
        "PREDICTED — a model estimate, not a measurement. Produced before the "
        "session it describes, from season form plus whatever practice running "
        "has happened so far. Check the prediction ledger for its track record."),
}


def pace_badge(kind: str):
    """Small colour-coded chip naming WHICH pace measure a card shows, with the
    full definition on hover. Returns a children list (chip + tooltip) — splice
    it into a header, or pass `measure=` to card() which does it for you."""
    entry = PACE_MEASURES.get(str(kind).strip().lower())
    if entry is None:
        return []
    label, colour, definition = entry
    return tip(label, definition, placement="bottom", style={
        "cursor": "help", "fontSize": "0.6rem", "fontWeight": "800",
        "letterSpacing": "0.08em", "color": colour,
        "border": f"1px solid {colour}", "borderRadius": "3px",
        "padding": "1px 5px", "marginLeft": "8px", "whiteSpace": "nowrap",
        "verticalAlign": "middle", "userSelect": "none"})


def card(title, children, info=None, plain=None, measure=None):
    """A titled card. Pass `info` to show a small ⓘ tooltip in the header
    explaining what data the graph uses and why it is relevant (hover to read).
    Pass `plain` for a beginner-facing 'In plain terms: …' strip below the
    content — a plain-English reading of what the card shows.

    Pass `measure` ("one-lap" / "race" / "stint" / "result" / "predicted") to
    badge the header with WHICH pace measure the card is showing — see
    PACE_MEASURES. Any card whose subject is a speed should carry one.

    A card that plots MORE THAN ONE measure must name all of them: pass a
    tuple/list and every badge is rendered, left to right, in the order given.
    A single badge on a two-measure card is worse than none — it silently
    mislabels the series it does not cover, which is exactly how the Upgrade
    Impact trend (one-lap solid + race dotted) read as a one-lap-only card.
    """
    header = [html.Span(title, style={"fontWeight": "700", "letterSpacing": "1px", "fontSize": "0.85rem"})]
    if measure:
        for _m in ([measure] if isinstance(measure, str) else list(measure)):
            header += pace_badge(_m)
    if info:
        header += tip(" ⓘ", info, style={
            "cursor": "help", "fontSize": "0.72rem", "opacity": "0.6",
            "userSelect": "none", "marginLeft": "6px"})
    # Normalise children to a flat list. Wrapping a list-valued `children`
    # in another list (the old `[children]`) produced `[[...]]`, which Dash
    # rejects as "children is a list of lists" — and appending the `plain`
    # strip made it a genuine mixed list-of-lists that fails to render (the
    # QUALI grid card hit exactly this: a list body *and* a plain= reading).
    body = list(children) if isinstance(children, (list, tuple)) else [children]
    strip = plain_line(plain)
    if strip is not None:
        body.append(strip)
    return dbc.Card([
        dbc.CardHeader(header),
        dbc.CardBody(body),
    ], className="mb-3",
       style={"background": CARD_BG, "border": f"1px solid {GRID_CLR}", "borderRadius": "8px"})


def kpi(label, value, color=ACCENT, tooltip=None):
    label_content, tip_comp = [label], []
    if tooltip:
        icon, overlay = tip(" ⓘ", tooltip, style={
            "cursor": "help", "fontSize": "0.65rem", "opacity": "0.6", "userSelect": "none"})
        label_content.append(icon)
        tip_comp = [overlay]  # overlay renders a div — keep it out of the <p>
    return dbc.Col(dbc.Card(dbc.CardBody([
        html.P(label_content, style={"color": TEXT_DIM, "fontSize": "0.72rem", "marginBottom": "4px", "letterSpacing": "1px"}),
        html.H4(value, style={"color": color, "fontWeight": "800", "marginBottom": 0}),
        *tip_comp,
    ]), style={"background": CARD_BG, "border": f"1px solid {GRID_CLR}", "borderRadius": "8px"}),
    xs=6, md=3, className="mb-3")


def styled_table(data, cols):
    return dash_table.DataTable(data=data, columns=cols, **TABLE_STYLE,
        style_data_conditional=[{"if": {"row_index": 0}, "backgroundColor": ACCENT + "22", "fontWeight": "700"}])


def badge(text, color):
    """Small coloured pill."""
    return html.Span(text, style={
        "background": color, "color": "#fff", "borderRadius": "4px",
        "padding": "2px 8px", "fontSize": "0.7rem", "fontWeight": "700",
        "letterSpacing": "0.5px", "marginLeft": "6px",
    })


# ── Small formatting helpers ─────────────────────────────────

TEAM_ABBR = {
    "Ferrari": "FER", "Red Bull Racing": "RBR", "Mercedes": "MER",
    "McLaren": "MCL", "Aston Martin": "AST", "Alpine": "ALP",
    "Williams": "WIL", "Racing Bulls": "RB", "RB": "RB", "AlphaTauri": "RB",
    "Haas F1 Team": "HAAS", "Audi": "AUD", "Cadillac": "CAD",
    "Sauber": "SAU", "Kick Sauber": "SAU", "Alfa Romeo": "SAU",
    "Alfa Romeo Racing": "SAU",
}


def abbr(team) -> str:
    return TEAM_ABBR.get(team, str(team)[:3].upper())


def hex_to_rgba(hex_color: str, alpha: float = 1.0) -> str:
    """Convert a '#RRGGBB' hex string to 'rgba(r,g,b,a)' for Plotly."""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    else:
        r, g, b = 128, 128, 128
    return f"rgba({r},{g},{b},{alpha})"
