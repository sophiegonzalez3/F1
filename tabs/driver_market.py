"""
Driver market card for the SEASON FORM section: contract expiry, estimated
salary, and FIA superlicence penalty points for the grid.

Curated, human-maintained (data/driver_info.csv) — none of it is in the results
archive. Salary and contract figures are third-party estimates/reports (teams
don't publish them); penalty points are a rolling 12-month total that must be
refreshed as the season runs (the CSV carries a points_as_of date).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, dash_table

from f1lib.components import card, theme, GFX
from f1lib.config import (TEAM_COLORS, CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM,
                          GRID_CLR)

_DRV_PATH = Path("data/driver_info.csv")
_DRV_COLS = ["season", "driver", "name", "team", "contract_until",
             "salary_usd_m", "academy", "penalty_points", "points_as_of",
             "source", "notes"]
_BAN_POINTS = 12   # 12 points in 12 months → automatic one-race ban

_DRV_CACHE: dict = {"mtime": None, "df": pd.DataFrame(columns=_DRV_COLS)}


def _load_drivers() -> pd.DataFrame:
    if _DRV_PATH.exists():
        try:
            df = pd.read_csv(_DRV_PATH)
            for c in _DRV_COLS:
                if c not in df.columns:
                    df[c] = pd.NA
            df["season"] = pd.to_numeric(df["season"], errors="coerce").astype("Int64")
            df["contract_until"] = pd.to_numeric(df["contract_until"], errors="coerce").astype("Int64")
            df["salary_usd_m"] = pd.to_numeric(df["salary_usd_m"], errors="coerce")
            df["penalty_points"] = pd.to_numeric(df["penalty_points"], errors="coerce").fillna(0)
            for c in ("driver", "name", "team", "academy", "points_as_of",
                      "source", "notes"):
                df[c] = df[c].fillna("").astype(str).str.strip()
            return df[_DRV_COLS]
        except Exception as _exc:
            print(f"Driver info             : failed to read ({_exc})")
    return pd.DataFrame(columns=_DRV_COLS)


def drivers_df(season: int) -> pd.DataFrame:
    try:
        mtime = _DRV_PATH.stat().st_mtime if _DRV_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _DRV_CACHE["mtime"]:
        _DRV_CACHE["df"] = _load_drivers()
        _DRV_CACHE["mtime"] = mtime
    df = _DRV_CACHE["df"]
    return df[df["season"] == season].copy() if not df.empty else df


def _salary_fig(d: pd.DataFrame) -> go.Figure:
    s = d[d["salary_usd_m"].notna()].sort_values("salary_usd_m", ascending=True)
    fig = go.Figure(go.Bar(
        y=s["driver"], x=s["salary_usd_m"], orientation="h",
        marker=dict(color=[TEAM_COLORS.get(t, "#808080") for t in s["team"]],
                    line=dict(color="#000", width=0.5)),
        customdata=s["name"],
        text=[f"${v:g}M" for v in s["salary_usd_m"]], textposition="outside",
        textfont=dict(size=10),
        hovertemplate="<b>%{customdata}</b><br>~$%{x:g}M / year<extra></extra>",
    ))
    theme(fig, max(360, 20 * len(s) + 120),
          "Estimated salary · $M/year (excl. bonuses)")
    top = float(s["salary_usd_m"].max()) if len(s) else 70
    fig.update_xaxes(title_text="US$ millions / year", range=[0, top * 1.18])
    fig.update_yaxes(title_text=None, tickfont=dict(size=9))
    fig.update_layout(margin=dict(l=48, r=30, t=50, b=40), showlegend=False,
                      bargap=0.3)
    return fig


def _points_fig(d: pd.DataFrame) -> go.Figure:
    s = d.sort_values("penalty_points", ascending=True)
    fig = go.Figure(go.Bar(
        y=s["driver"], x=s["penalty_points"], orientation="h",
        marker=dict(color=[TEAM_COLORS.get(t, "#808080") for t in s["team"]],
                    line=dict(color="#000", width=0.5)),
        customdata=s["name"],
        text=[f"{int(v)}" if v else "" for v in s["penalty_points"]],
        textposition="outside", textfont=dict(size=10),
        hovertemplate="<b>%{customdata}</b><br>%{x:.0f} / 12 points<extra></extra>",
    ))
    fig.add_vline(x=_BAN_POINTS, line=dict(color="#e66767", width=2, dash="dash"))
    fig.add_annotation(x=_BAN_POINTS, y=1.0, yref="paper", yanchor="bottom",
                       text="12 = race ban", showarrow=False,
                       font=dict(size=10, color="#e66767"), xanchor="right")
    theme(fig, max(360, 20 * len(s) + 120),
          "Superlicence penalty points · 12 in 12 months = ban")
    fig.update_xaxes(title_text="Penalty points", range=[0, _BAN_POINTS + 0.6],
                     dtick=2)
    fig.update_yaxes(title_text=None, tickfont=dict(size=9))
    fig.update_layout(margin=dict(l=48, r=20, t=50, b=40), showlegend=False,
                      bargap=0.3)
    return fig


def _driver_table(d: pd.DataFrame) -> dash_table.DataTable:
    t = d.sort_values("contract_until").copy()
    t["salary_disp"] = t["salary_usd_m"].apply(
        lambda v: f"${v:g}M" if pd.notna(v) else "—")
    t["contract_disp"] = t["contract_until"].astype("Int64").astype(str).replace("<NA>", "—")
    t["pts_disp"] = t["penalty_points"].astype(int)
    records = t.rename(columns={"name": "Driver", "team": "Team"}).to_dict("records")
    cols = [
        {"name": "Driver", "id": "Driver"},
        {"name": "Team", "id": "Team"},
        {"name": "Contract until", "id": "contract_disp"},
        {"name": "Salary", "id": "salary_disp"},
        {"name": "Academy origin", "id": "academy"},
        {"name": "Pts", "id": "pts_disp"},
        {"name": "Notes", "id": "notes"},
    ]
    team_styles = [
        {"if": {"filter_query": f'{{Team}} = "{tm}"', "column_id": "Team"},
         "color": c, "fontWeight": "700"}
        for tm, c in TEAM_COLORS.items()
    ]
    return dash_table.DataTable(
        data=records, columns=cols,
        sort_action="native", filter_action="native", page_size=22,
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": CARD_BG, "color": TEXT_MAIN,
                    "border": f"1px solid {GRID_CLR}", "fontSize": "12px",
                    "padding": "6px 9px", "textAlign": "left",
                    "whiteSpace": "normal", "height": "auto", "maxWidth": "320px"},
        style_header={"backgroundColor": "#09091A", "fontWeight": "bold",
                      "color": ACCENT, "border": f"1px solid {GRID_CLR}"},
        style_cell_conditional=[
            {"if": {"column_id": "notes"}, "color": TEXT_DIM, "fontSize": "11px",
             "maxWidth": "300px"},
            {"if": {"column_id": "academy"}, "color": TEXT_DIM,
             "fontSize": "11px", "maxWidth": "170px"},
            {"if": {"column_id": "pts_disp"}, "textAlign": "center", "maxWidth": "48px"},
        ],
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "#0d0d1a"},
            {"if": {"filter_query": "{pts_disp} >= 8", "column_id": "pts_disp"},
             "color": "#e66767", "fontWeight": "700"},
        ] + team_styles,
    )


def driver_market_card(season: int):
    """Driver contracts / salary / penalty-points card, or None if no data."""
    d = drivers_df(season)
    if d.empty:
        return None
    expiring = int((d["contract_until"] == season).sum())
    as_of = d["points_as_of"].replace("", pd.NA).dropna()
    as_of = as_of.iloc[0] if len(as_of) else "n/a"
    intro = html.P(
        [f"{expiring} of {len(d)} drivers are out of contract at the end of "
         f"{season} — a big free-agent class. Salary figures are third-party "
         "estimates (teams don't disclose them); penalty points are a rolling "
         f"12-month total, current to {as_of} — refresh ",
         html.Code("data/driver_info.csv"), " as the season runs."],
        style={"color": TEXT_DIM, "fontSize": "0.75rem", "marginBottom": "10px"})
    return card(
        "Driver Market — contracts, pay & discipline",
        html.Div([
            intro,
            html.Div([
                html.Div(dcc.Graph(figure=_salary_fig(d), config=GFX),
                         style={"flex": "1 1 340px", "minWidth": "300px"}),
                html.Div(dcc.Graph(figure=_points_fig(d), config=GFX),
                         style={"flex": "1 1 340px", "minWidth": "300px"}),
            ], style={"display": "flex", "flexWrap": "wrap", "gap": "8px"}),
            _driver_table(d),
        ]),
        info=("Data: curated data/driver_info.csv — per-driver contract expiry "
              "year (#5), estimated annual salary in $M (teams don't publish "
              "these, so they're third-party estimates), the junior "
              "academy that raised each driver, and FIA superlicence "
              "penalty points (#9; 12 in a rolling 12 months = a one-race ban). "
              "Why: the driver market and cost side of the grid — who's a free "
              "agent, who's expensive, whose pipeline produced them, and who's "
              "a stray incident from a ban. Penalty points must be refreshed "
              "each round; the CSV notes the as-of date."),
    )
