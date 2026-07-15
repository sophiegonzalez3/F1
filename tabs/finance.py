"""
Team finance cards for the REGULATIONS & FINANCE section: Forbes team
valuations and estimated prize-money payouts (data/team_finance.csv, curated),
plus the budget-cap compliance ledger (data/budget_cap_compliance.csv, curated
from the FIA's annual review announcements).

Pairs with the headcount data in the HR section — valuation and prize money are
the money side of the same story the budget cap regulates. Prize-money splits in
particular are third-party estimates (the exact Concorde formula and heritage
bonuses aren't public), so treat them as indicative.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, dash_table

from f1lib.components import card, theme, GFX
from f1lib.config import (TEAM_COLORS, CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM,
                          GRID_CLR)

_FIN_PATH = Path("data/team_finance.csv")
_FIN_CACHE: dict = {"mtime": None, "df": pd.DataFrame()}
_CAP_PATH = Path("data/budget_cap_compliance.csv")
_CAP_CACHE: dict = {"mtime": None, "df": pd.DataFrame()}


def _load_finance() -> pd.DataFrame:
    if _FIN_PATH.exists():
        try:
            df = pd.read_csv(_FIN_PATH)
            for c in ("valuation_usd_bn", "prize_money_usd_m"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
            for c in ("team", "source", "notes"):
                if c in df.columns:
                    df[c] = df[c].fillna("").astype(str).str.strip()
            return df
        except Exception as _exc:
            print(f"Team finance            : failed to read ({_exc})")
    return pd.DataFrame()


def finance_df() -> pd.DataFrame:
    try:
        mtime = _FIN_PATH.stat().st_mtime if _FIN_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _FIN_CACHE["mtime"]:
        _FIN_CACHE["df"] = _load_finance()
        _FIN_CACHE["mtime"] = mtime
    return _FIN_CACHE["df"]


def _bar(df: pd.DataFrame, col: str, title: str, fmt, xtitle: str) -> go.Figure:
    d = df[df[col].notna()].sort_values(col, ascending=True)
    vals = d[col].tolist()
    fig = go.Figure(go.Bar(
        y=d["team"], x=vals, orientation="h",
        marker=dict(color=[TEAM_COLORS.get(t, "#808080") for t in d["team"]],
                    line=dict(color="#000", width=0.5)),
        text=[fmt(v) for v in vals], textposition="outside",
        textfont=dict(size=10),
        hovertemplate="<b>%{y}</b><br>" + xtitle + ": %{text}<extra></extra>",
    ))
    theme(fig, max(340, 28 * len(d) + 120), title)
    top = max(vals) if vals else 1
    fig.update_xaxes(title_text=xtitle, range=[0, top * 1.2])
    fig.update_yaxes(title_text=None, tickfont=dict(size=10))
    fig.update_layout(margin=dict(l=118, r=40, t=50, b=44), showlegend=False,
                      bargap=0.32)
    return fig


def compliance_df() -> pd.DataFrame:
    try:
        mtime = _CAP_PATH.stat().st_mtime if _CAP_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _CAP_CACHE["mtime"]:
        try:
            _CAP_CACHE["df"] = (pd.read_csv(_CAP_PATH).fillna("")
                                if mtime else pd.DataFrame())
        except Exception:
            _CAP_CACHE["df"] = pd.DataFrame()
        _CAP_CACHE["mtime"] = mtime
    return _CAP_CACHE["df"]


_OUTCOME_COLORS = {"Compliant": "#0ca30c", "Procedural breach": "#fab219",
                   "Minor overspend breach": "#E10600",
                   "Under review": "#AAAAAA"}


def compliance_card() -> html.Div | None:
    """Budget-cap compliance ledger — every FIA annual review outcome."""
    df = compliance_df()
    if df.empty:
        return None
    d = df.sort_values("review_season", ascending=False).copy()
    d["src_md"] = d["source"].apply(lambda u: f"[↗]({u})" if u else "")
    cols = [
        {"name": "Season", "id": "review_season"},
        {"name": "Entity", "id": "entity"},
        {"name": "Outcome", "id": "outcome"},
        {"name": "Penalty", "id": "penalty"},
        {"name": "Detail", "id": "detail"},
        {"name": "Src", "id": "src_md", "presentation": "markdown"},
    ]
    outcome_styles = [
        {"if": {"filter_query": f'{{outcome}} = "{o}"', "column_id": "outcome"},
         "color": c, "fontWeight": "700"} for o, c in _OUTCOME_COLORS.items()]
    table = dash_table.DataTable(
        data=d.to_dict("records"), columns=cols,
        sort_action="native", page_size=12,
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": CARD_BG, "color": TEXT_MAIN,
                    "border": f"1px solid {GRID_CLR}", "fontSize": "12px",
                    "padding": "6px 9px", "textAlign": "left",
                    "whiteSpace": "normal", "height": "auto",
                    "maxWidth": "340px"},
        style_header={"backgroundColor": "#09091A", "fontWeight": "bold",
                      "color": ACCENT, "border": f"1px solid {GRID_CLR}"},
        style_cell_conditional=[
            {"if": {"column_id": "detail"}, "color": TEXT_DIM,
             "fontSize": "11px", "maxWidth": "380px"},
            {"if": {"column_id": "src_md"}, "textAlign": "center",
             "maxWidth": "44px"},
            {"if": {"column_id": "review_season"}, "maxWidth": "60px",
             "fontWeight": "700"}],
        style_data_conditional=([{"if": {"row_index": "odd"},
                                  "backgroundColor": "#0d0d1a"}]
                                + outcome_styles),
        markdown_options={"link_target": "_blank"},
    )
    intro = html.P(
        ["The enforcement record of the budget cap. Only one team has ever "
         "overspent it — ", html.Strong("Red Bull in 2021"),
         " ($7M fine + 10% less wind-tunnel time) — but procedural breaches "
         "(late or inaccurate paperwork) keep appearing, and the FIA's "
         "review lands each autumn for the previous season."],
        style={"color": TEXT_DIM, "fontSize": "0.75rem", "marginBottom": "10px"})
    return card(
        "Budget-Cap Compliance Ledger",
        html.Div([intro, table]),
        info=("Data: curated data/budget_cap_compliance.csv — the outcome of "
              "every FIA cost-cap review since the cap began (2021), with "
              "penalties and source links to the FIA/press announcements. "
              "Why: the cap is only as real as its enforcement — this is "
              "the actual case law: what a 1.6% overspend cost Red Bull, "
              "and how procedural slips are settled."),
    )


def finance_block() -> html.Div:
    """Valuation + prize-money card for the REGULATIONS & FINANCE section."""
    df = finance_df()
    if df.empty:
        return html.Div()
    val_fig = _bar(df, "valuation_usd_bn", "Team valuation · Forbes 2025",
                   lambda v: f"${v:g}B", "US$ billions")
    prize_fig = _bar(df, "prize_money_usd_m",
                     "Prize money · 2025 (est., incl. bonuses)",
                     lambda v: f"${v:.0f}M", "US$ millions")
    intro = html.P(
        ["The money side of the grid. ", html.Strong("Ferrari"),
         " banked the biggest 2025 payout (~$277.7M) ", html.Em("despite "
         "winning no race"), " — heritage and historic bonuses — while champion ",
         html.Strong("McLaren"), " took only the 4th-biggest cheque. Valuations "
         "are Forbes 2025; prize-money splits are third-party estimates (the "
         "exact Concorde formula isn't public). Pair with team headcount in the "
         "HR section for a rough spend-efficiency read."],
        style={"color": TEXT_DIM, "fontSize": "0.78rem", "marginBottom": "10px"})
    return card(
        "Team Value & Prize Money",
        html.Div([
            intro,
            html.Div([
                html.Div(dcc.Graph(figure=val_fig, config=GFX),
                         style={"flex": "1 1 340px", "minWidth": "300px"}),
                html.Div(dcc.Graph(figure=prize_fig, config=GFX),
                         style={"flex": "1 1 340px", "minWidth": "300px"}),
            ], style={"display": "flex", "flexWrap": "wrap", "gap": "8px"}),
        ]),
        info=("Data: curated data/team_finance.csv — Forbes 2025 team "
              "valuations ($bn) and estimated 2025 prize-money payouts ($m, "
              "including heritage/historic bonuses). Why: the budget cap "
              "levels spending but not income — Ferrari's heritage money and "
              "the top teams' legacy bonuses mean the richest teams aren't "
              "always the fastest. Prize splits are estimates; methodologies "
              "vary between sources."),
    )
