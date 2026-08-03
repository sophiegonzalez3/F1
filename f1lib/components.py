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
BASE = dict(
    paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
    font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=12),
    xaxis=dict(gridcolor=GRID_CLR, zeroline=False),
    yaxis=dict(gridcolor=GRID_CLR, zeroline=False),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1),
    margin=dict(l=60, r=20, t=50, b=50),
)


def theme(fig, h=450, t=""):
    fig.update_layout(**BASE, height=h, title=t)
    fig.update_xaxes(gridcolor=GRID_CLR, zeroline=False)
    fig.update_yaxes(gridcolor=GRID_CLR, zeroline=False)
    return fig


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


# ── Pace-measure badges ──────────────────────────────────────
# "Pace" means four different things in this dashboard and the difference
# decides whether a number is meaningful. A card that shows any of them wears
# the matching badge in its header, so you never have to infer which one from
# the title. Colours: warm = single lap, cool = sustained running, grey = a
# classification result rather than a speed measurement.
PACE_MEASURES: dict[str, tuple[str, str, str]] = {
    # key: (label, colour, definition)
    "one-lap": (
        "ONE-LAP", "#FF8A3D",
        "ONE-LAP PACE — a single flat-out lap: low fuel, fresh tyres, maximum "
        "attack. This is qualifying speed. It says nothing about how the car "
        "behaves over a stint, and a car can be strong here and weak on Sunday."),
    "race": (
        "RACE PACE", "#3DD6C4",
        "RACE PACE — the MEDIAN of clean green-flag laps on race fuel and "
        "wearing tyres, corrected for fuel burn and track evolution, with "
        "dirty-air laps excluded. Sustained speed over many laps, which is what "
        "actually decides races. Not a single fast lap."),
    "stint": (
        "STINT PACE", "#5BA7FF",
        "STINT PACE — race pace narrowed to one continuous run on one tyre "
        "compound. Same measure as race pace, but per-compound, so it separates "
        "'the car is quick' from 'the car is quick on this tyre'."),
    "result": (
        "RESULT", "#8A8FA3",
        "RESULT — where the car actually ended up (grid slot, classification, "
        "gap to pole), not a like-for-like speed measurement. It bakes in "
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
    PACE_MEASURES. Any card whose subject is a speed should carry one."""
    header = [html.Span(title, style={"fontWeight": "700", "letterSpacing": "1px", "fontSize": "0.85rem"})]
    if measure:
        header += pace_badge(measure)
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
