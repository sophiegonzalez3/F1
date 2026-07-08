"""
F1 Dashboard – shared UI components & Plotly theme
==================================================
Pure presentation helpers with no data dependencies: import these from any
tab module instead of reaching into app.py. Everything here depends only on
config.py, dash, and plotly — never on loaded session data.
"""
from __future__ import annotations

from dash import html, dash_table
import dash_bootstrap_components as dbc

from config import (
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

def card(title, children, info=None):
    """A titled card. Pass `info` to show a small ⓘ tooltip in the header
    explaining what data the graph uses and why it is relevant (hover to read)."""
    header = [html.Span(title, style={"fontWeight": "700", "letterSpacing": "1px", "fontSize": "0.85rem"})]
    if info:
        header.append(html.Span(
            " ⓘ", title=info,
            style={"cursor": "help", "fontSize": "0.72rem", "opacity": "0.6",
                   "userSelect": "none", "marginLeft": "6px"},
        ))
    return dbc.Card([
        dbc.CardHeader(header),
        dbc.CardBody(children),
    ], className="mb-3",
       style={"background": CARD_BG, "border": f"1px solid {GRID_CLR}", "borderRadius": "8px"})


def kpi(label, value, color=ACCENT, tooltip=None):
    label_content = [label, html.Span(
        " ⓘ", title=tooltip,
        style={"cursor": "help", "fontSize": "0.65rem", "opacity": "0.6", "userSelect": "none"}
    )] if tooltip else [label]
    return dbc.Col(dbc.Card(dbc.CardBody([
        html.P(label_content, style={"color": TEXT_DIM, "fontSize": "0.72rem", "marginBottom": "4px", "letterSpacing": "1px"}),
        html.H4(value, style={"color": color, "fontWeight": "800", "marginBottom": 0}),
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
