"""
Infrastructure & Governance section (rendered after HR on the SEASON tab):

  • Facilities & Tooling (#7) — where each team designs its car: factory HQ and
    wind-tunnel capability (own / shared / rented), from data/facilities.csv.
  • ATR sliding scale — each team's aero-testing allowance per half-year,
    derived from the standings by scripts/compute_atr.py.
  • Technical Directives (#8) — the FIA clarifications that reshape the rules
    mid-season, from data/technical_directives.csv.

The facilities and TD tables are curated, human-maintained (not in the results
archive) and re-read when their CSV changes on disk; the ATR table is derived.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, dash_table

from f1lib.components import card, theme, GFX, abbr
from f1lib.config import TEAM_COLORS, CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR

_FAC_PATH = Path("data/facilities.csv")
_TD_PATH = Path("data/technical_directives.csv")
_ATR_PATH = Path("data/atr_allowance.csv")

_TUNNEL_COLORS = {"own": "#0ca30c", "shared": "#fab219", "rented": "#ec835a"}


def _read_csv(path: Path) -> pd.DataFrame:
    if path.exists():
        try:
            return pd.read_csv(path).fillna("")
        except Exception as _exc:
            print(f"Infrastructure          : failed to read {path.name} ({_exc})")
    return pd.DataFrame()


# Simple mtime caches so CSV edits show up without a restart.
_FAC_CACHE: dict = {"mtime": None, "df": pd.DataFrame()}
_TD_CACHE: dict = {"mtime": None, "df": pd.DataFrame()}
_ATR_CACHE: dict = {"mtime": None, "df": pd.DataFrame()}


def _cached(path: Path, cache: dict) -> pd.DataFrame:
    try:
        mtime = path.stat().st_mtime if path.exists() else None
    except OSError:
        mtime = None
    if mtime != cache["mtime"]:
        cache["df"] = _read_csv(path)
        cache["mtime"] = mtime
    return cache["df"]


def facilities_df() -> pd.DataFrame:
    return _cached(_FAC_PATH, _FAC_CACHE)


def tech_directives_df() -> pd.DataFrame:
    return _cached(_TD_PATH, _TD_CACHE)


def atr_df() -> pd.DataFrame:
    return _cached(_ATR_PATH, _ATR_CACHE)


# ── ATR sliding-scale card ───────────────────────────────────
def _atr_card():
    df = atr_df()
    if df.empty or "atr_pct" not in df.columns:
        return None
    df = df.copy()
    df["season"] = pd.to_numeric(df["season"], errors="coerce")
    df["atr_pct"] = pd.to_numeric(df["atr_pct"], errors="coerce")
    season = int(df["season"].max())
    s = df[df["season"] == season]
    periods = [p for p in ("H1", "H2") if (s["period"] == p).any()]
    if not periods:
        return None

    # order teams by their latest-period allowance (least aero testing first)
    latest = s[s["period"] == periods[-1]].set_index("team")["atr_pct"]
    order = list(latest.sort_values().index)

    fig = go.Figure()
    shade = {"H1": 0.45, "H2": 1.0}
    for p in periods:
        g = s[s["period"] == p].set_index("team").reindex(order)
        label = g["period_label"].dropna().iloc[0] if g["period_label"].notna().any() else p
        fig.add_trace(go.Bar(
            y=[abbr(t) for t in order], x=g["atr_pct"], orientation="h",
            name=str(label), opacity=shade[p],
            marker=dict(color=[TEAM_COLORS.get(t, "#808080") for t in order],
                        line=dict(color="#000", width=0.5)),
            text=[f"{v:.0f}%" if pd.notna(v) else "" for v in g["atr_pct"]],
            textposition="outside", textfont=dict(size=9),
            customdata=g["basis"].fillna(""),
            hovertemplate=("<b>%{y}</b> · " + str(label) +
                           "<br>%{x:.0f}% of baseline aero testing"
                           "<br>%{customdata}<extra></extra>"),
        ))
    theme(fig, max(360, 30 * len(order) + 140))
    fig.add_vline(x=100, line=dict(color=TEXT_DIM, width=1, dash="dot"))
    fig.update_xaxes(title_text="Wind-tunnel runs / CFD allowed (% of baseline)",
                     range=[0, 132])
    fig.update_yaxes(title_text=None, tickfont=dict(size=10))
    fig.update_layout(barmode="group", bargap=0.25,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0),
                      margin=dict(l=60, r=40, t=70, b=44))

    intro = html.P(
        ["F1's built-in handicap: wind-tunnel and CFD time scales with "
         "championship position — the leader gets 70% of the baseline, "
         "last place 115%, new entrants the maximum. It resets every "
         "1 January (previous season's final standings) and every 1 July "
         "(standings on 30 June), so a bad half-season quietly buys next "
         "year's development speed."],
        style={"color": TEXT_DIM, "fontSize": "0.75rem", "marginBottom": "8px"})
    return card(
        "ATR Sliding Scale — Who Gets the Tunnel Time",
        html.Div([intro, dcc.Graph(figure=fig, config=GFX)]),
        info=("Data: derived (scripts/compute_atr.py) — the ATR percentage "
              "each team is entitled to in each half-year window, computed "
              "from the standings archive using the sporting-regulation "
              "sliding scale (P1 = 70%, +5% per place, P10 = 115%, new "
              "entrant = 115%). Hover shows the standings basis. Why: "
              "tunnel time is the raw material of car development — pair "
              "this with the wind-tunnel table below and the upgrade board "
              "to judge who should out-develop whom."),
    )


# ── Facilities card ──────────────────────────────────────────
def _facilities_card():
    df = facilities_df()
    if df.empty:
        return None
    df = df.copy()
    df["pu_disp"] = (df["pu_maker"].astype(str).str.strip() + " · "
                     + df["pu_location"].astype(str).str.strip()).str.strip(" ·")
    n_own = int((df["tunnel_owner"].str.strip().str.casefold() == "own").sum())
    n_ext = len(df) - n_own
    records = df.to_dict("records")
    cols = [
        {"name": "Team", "id": "team"},
        {"name": "Base (HQ)", "id": "base_location"},
        {"name": "Wind tunnel", "id": "wind_tunnel_location"},
        {"name": "Tunnel owner", "id": "tunnel_owner"},
        {"name": "Power unit", "id": "pu_disp"},
        {"name": "Notes", "id": "notes"},
    ]
    team_styles = [
        {"if": {"filter_query": f'{{team}} = "{tm}"', "column_id": "team"},
         "color": c, "fontWeight": "700"} for tm, c in TEAM_COLORS.items()]
    # Colour the tunnel-owner cell: own = green, shared = amber, rented = orange.
    owner_styles = [
        {"if": {"filter_query": '{tunnel_owner} = "Own"',
                "column_id": "tunnel_owner"},
         "color": _TUNNEL_COLORS["own"], "fontWeight": "700"},
        {"if": {"filter_query": '{tunnel_owner} contains "shared"',
                "column_id": "tunnel_owner"}, "color": _TUNNEL_COLORS["shared"]},
        {"if": {"filter_query": '{tunnel_owner} contains "rented"',
                "column_id": "tunnel_owner"}, "color": _TUNNEL_COLORS["rented"]},
    ]
    table = dash_table.DataTable(
        data=records, columns=cols,
        sort_action="native", filter_action="native", page_size=11,
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": CARD_BG, "color": TEXT_MAIN,
                    "border": f"1px solid {GRID_CLR}", "fontSize": "12px",
                    "padding": "6px 9px", "textAlign": "left",
                    "whiteSpace": "normal", "height": "auto", "maxWidth": "300px"},
        style_header={"backgroundColor": "#09091A", "fontWeight": "bold",
                      "color": ACCENT, "border": f"1px solid {GRID_CLR}"},
        style_cell_conditional=[
            {"if": {"column_id": "notes"}, "color": TEXT_DIM, "fontSize": "11px",
             "maxWidth": "300px"}],
        style_data_conditional=([{"if": {"row_index": "odd"},
                                  "backgroundColor": "#0d0d1a"}]
                                + team_styles + owner_styles),
    )
    intro = html.P(
        [f"{n_own} teams run their own wind tunnel; {n_ext} rent or share one. "
         "The location columns map how geographically spread an operation is — "
         "and the logistics that follow. ", html.Strong("Aston Martin"),
         " designs in Silverstone but its Honda engine is built in Japan; ",
         html.Strong("Cadillac"), " spans the US, a UK base, a German tunnel "
         "and an Italian engine — the widest footprint on the grid."],
        style={"color": TEXT_DIM, "fontSize": "0.75rem", "marginBottom": "10px"})
    return card(
        "Facilities & Tooling",
        html.Div([intro, table]),
        info=("Data: curated data/facilities.csv — each team's base, wind "
              "tunnel (location + owner: own / shared / rented), and power-unit "
              "maker and where it's built, all as town, country. Why: aero dev "
              "is tunnel-bound and a car's chassis, tunnel and engine can sit "
              "on three different continents — a real logistical spread the "
              "cost cap doesn't level. Sortable/searchable."),
    )


# ── Technical Directives card ────────────────────────────────
def _td_card():
    df = tech_directives_df()
    if df.empty:
        return None
    d = df.copy()
    d["src_md"] = d["source"].apply(lambda u: f"[↗]({u})" if u else "")
    if "date" in d.columns:
        d = d.sort_values("date", ascending=False)
    records = d.to_dict("records")
    cols = [
        {"name": "Season", "id": "season"},
        {"name": "Date", "id": "date"},
        {"name": "Area", "id": "area"},
        {"name": "Directive", "id": "subject"},
        {"name": "Effect", "id": "effect"},
        {"name": "Src", "id": "src_md", "presentation": "markdown"},
    ]
    table = dash_table.DataTable(
        data=records, columns=cols,
        sort_action="native", filter_action="native", page_size=12,
        style_table={"overflowX": "auto"},
        style_cell={"backgroundColor": CARD_BG, "color": TEXT_MAIN,
                    "border": f"1px solid {GRID_CLR}", "fontSize": "12px",
                    "padding": "6px 9px", "textAlign": "left",
                    "whiteSpace": "normal", "height": "auto", "maxWidth": "360px"},
        style_header={"backgroundColor": "#09091A", "fontWeight": "bold",
                      "color": ACCENT, "border": f"1px solid {GRID_CLR}"},
        style_cell_conditional=[
            {"if": {"column_id": "effect"}, "color": TEXT_DIM, "fontSize": "11px",
             "maxWidth": "380px"},
            {"if": {"column_id": "src_md"}, "textAlign": "center",
             "maxWidth": "44px"},
            {"if": {"column_id": "season"}, "maxWidth": "60px", "fontWeight": "700"}],
        style_data_conditional=[{"if": {"row_index": "odd"},
                                 "backgroundColor": "#0d0d1a"}],
        markdown_options={"link_target": "_blank"},
    )
    intro = html.P(
        ["Technical Directives (TDs) are the FIA's in-season clarifications of "
         "the rules — how a test is done, what's legal. They can quietly reset "
         "the pecking order: the 2024-25 ", html.Strong("flexi-wing"),
         " saga (McLaren's 'mini-DRS', then tighter front-wing deflection from "
         "the 2025 Spanish GP) is the headline case. Newest first."],
        style={"color": TEXT_DIM, "fontSize": "0.75rem", "marginBottom": "10px"})
    return card(
        "Technical Directives",
        html.Div([intro, table]),
        info=("Data: curated data/technical_directives.csv — notable FIA "
              "technical directives (2023–2026) with the area, what changed and "
              "its effect, each with a source link. Why: TDs shift the rules "
              "mid-season without a regulation change, so a form step that "
              "lines up with a TD date is often the directive, not development. "
              "Sortable/searchable."),
    )


def infrastructure_section() -> html.Div:
    """Both cards for the INFRASTRUCTURE & GOVERNANCE section (after HR)."""
    parts = [c for c in (_facilities_card(), _atr_card(), _td_card())
             if c is not None]
    if not parts:
        return html.Div(html.P(
            "No facilities or technical-directive data found.",
            style={"color": TEXT_DIM, "fontSize": "0.8rem"}))
    return html.Div(parts)
