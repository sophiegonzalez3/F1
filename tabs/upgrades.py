"""
UPGRADES tab — what technical evolution each team brought to the loaded
meeting(s), in the style of the FIA Car Presentation documents.

Data source: data/upgrades.csv (curated, human-maintained; see the column
notes below). This module is the template for extracting further tabs out of
app.py — see tabs/__init__.py for the recipe.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from dash import html
import dash_bootstrap_components as dbc

import state
from components import kpi, badge
from config import TEAM_COLORS, CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR

# Curated, human-maintained table of the technical upgrades each team brings
# to a given Grand Prix — mirrors the FIA "Car Presentation" documents
# published each event. One row per (season, event, team, component).
#
#   season       e.g. 2025
#   event        must match the MEETING name, e.g. "Austrian Grand Prix"
#   team         must match a TEAM_COLORS key, e.g. "McLaren"
#   component    affected area, e.g. "Floor Body", "Front Wing"
#   category     FIA-style reason: Performance / Circuit specific /
#                Reliability / Driver comfort / Repairs
#   description  short free-text summary of the change
#   source       provenance tag (e.g. "FIA-2025-AUT", "starter-example")
#
# Edit data/upgrades.csv to add/replace rows — no code changes needed.
_UPGRADES_PATH = Path("data/upgrades.csv")
_UPGRADES_COLS = ["season", "event", "team", "component",
                  "category", "description", "source"]


def _load_upgrades() -> pd.DataFrame:
    if _UPGRADES_PATH.exists():
        try:
            df = pd.read_csv(_UPGRADES_PATH)
            for c in _UPGRADES_COLS:
                if c not in df.columns:
                    df[c] = "" if c != "season" else pd.NA
            df["season"] = pd.to_numeric(df["season"], errors="coerce").astype("Int64")
            for c in ("event", "team", "component", "category", "description", "source"):
                df[c] = df[c].fillna("").astype(str).str.strip()
            return df[_UPGRADES_COLS]
        except Exception as _exc:
            print(f"Team upgrades           : failed to read ({_exc})")
    return pd.DataFrame(columns=_UPGRADES_COLS)


# Cache the parsed CSV but reload automatically when the file changes on disk,
# so editing data/upgrades.csv takes effect without restarting the app.
_UPGRADES_CACHE: dict = {"mtime": None, "df": pd.DataFrame(columns=_UPGRADES_COLS)}


def upgrades_df() -> pd.DataFrame:
    """Current upgrades table, re-read from disk whenever the CSV's mtime changes."""
    try:
        mtime = _UPGRADES_PATH.stat().st_mtime if _UPGRADES_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _UPGRADES_CACHE["mtime"]:
        _UPGRADES_CACHE["df"] = _load_upgrades()
        _UPGRADES_CACHE["mtime"] = mtime
    return _UPGRADES_CACHE["df"]


def upgrades_for(season, meeting) -> pd.DataFrame:
    """Upgrade rows for one (season, event) pair, robust to type/whitespace."""
    up = upgrades_df()
    if up.empty or season is None or not meeting:
        return up.iloc[0:0]
    try:
        season = int(season)
    except (TypeError, ValueError):
        return up.iloc[0:0]
    m = str(meeting).strip().casefold()
    sub = up[(up["season"] == season)
             & (up["event"].str.strip().str.casefold() == m)]
    return sub.copy()


def _loaded_meetings() -> list[tuple[int | None, str]]:
    """Unique (season, event) meetings currently loaded, in load order."""
    seen: list[tuple[int | None, str]] = []
    for info in state.LOADED_SESSION_INFO:
        try:
            season = int(info.get("SEASON"))
        except (TypeError, ValueError):
            season = None
        meeting = str(info.get("MEETING", "")).strip()
        key = (season, meeting)
        if meeting and key not in seen:
            seen.append(key)
    return seen


# ── Layout ───────────────────────────────────────────────────
_UPGRADE_CAT_COLORS = {
    "performance":     ACCENT,
    "circuit specific":"#FFB000",
    "reliability":     "#0067FF",
    "driver comfort":  "#9B59B6",
    "repairs":         "#7A7A7A",
}


def _upgrade_cat_color(cat: str) -> str:
    return _UPGRADE_CAT_COLORS.get(str(cat).strip().casefold(), "#7A7A7A")


def _upgrade_meeting_block(season, meeting, team_rank: dict) -> html.Div:
    sub = upgrades_for(season, meeting)
    title = f"{meeting}" + (f"  ·  {season}" if season else "")

    if sub.empty:
        return html.Div([
            html.H4(title, style={"color": TEXT_MAIN, "fontWeight": "800",
                                  "letterSpacing": "1px", "fontSize": "1.05rem",
                                  "marginBottom": "8px"}),
            dbc.Alert(
                f"No upgrades recorded for this event yet. Add rows to "
                f"data/upgrades.csv with event = \"{meeting}\" and season = "
                f"{season or '<year>'}.",
                color="secondary",
                style={"background": CARD_BG, "border": f"1px solid {GRID_CLR}",
                       "color": TEXT_DIM},
            ),
        ], className="mb-4")

    # ── Summary KPIs ─────────────────────────────────────────
    n_total = len(sub)
    n_teams = sub["team"].nunique()
    cat_counts = sub["category"].str.strip().str.title().value_counts()
    top_cat = cat_counts.index[0] if not cat_counts.empty else "—"
    kpis = dbc.Row([
        kpi("UPGRADES", str(n_total), tooltip="Total upgrade items logged for this event."),
        kpi("TEAMS DEVELOPING", str(n_teams),
            tooltip="Teams that brought at least one upgrade here."),
        kpi("MOST COMMON", top_cat, color="#FFB000",
            tooltip="Most frequent upgrade category for this event."),
        kpi("PERFORMANCE ITEMS",
            str(int(cat_counts.get("Performance", 0))), color=ACCENT,
            tooltip="Upgrades flagged as pure performance (not circuit-specific)."),
    ], className="g-2 mb-2")

    # ── One card per team, ordered by championship rank if known ─
    teams = sorted(sub["team"].unique(),
                   key=lambda t: (team_rank.get(t, 999), t))
    team_cards = []
    for tname in teams:
        rows = sub[sub["team"] == tname]
        colr = TEAM_COLORS.get(tname, "#808080")
        items = []
        for _, r in rows.iterrows():
            ccolor = _upgrade_cat_color(r["category"])
            items.append(html.Div([
                html.Div([
                    html.Span(r["component"] or "—",
                              style={"fontWeight": "700", "color": TEXT_MAIN,
                                     "fontSize": "0.85rem"}),
                    badge((r["category"] or "—").title(), ccolor),
                ], style={"marginBottom": "2px"}),
                html.Div(r["description"] or "",
                         style={"color": TEXT_DIM, "fontSize": "0.78rem",
                                "lineHeight": "1.35"}),
            ], style={"padding": "8px 0",
                      "borderBottom": f"1px solid {GRID_CLR}"}))
        header = html.Div([
            html.Span(style={"display": "inline-block", "width": "10px",
                             "height": "10px", "borderRadius": "2px",
                             "background": colr, "marginRight": "8px"}),
            html.Span(tname, style={"fontWeight": "800", "letterSpacing": "0.5px"}),
            badge(f"{len(rows)}", colr),
        ])
        team_cards.append(dbc.Col(
            dbc.Card([dbc.CardHeader(header),
                      dbc.CardBody(items, style={"paddingTop": "4px"})],
                     className="mb-3",
                     style={"background": CARD_BG,
                            "border": f"1px solid {GRID_CLR}",
                            "borderLeft": f"3px solid {colr}",
                            "borderRadius": "8px"}),
            md=6))

    return html.Div([
        html.H4(title, style={"color": TEXT_MAIN, "fontWeight": "800",
                              "letterSpacing": "1px", "fontSize": "1.05rem",
                              "marginBottom": "10px"}),
        kpis,
        dbc.Row(team_cards, className="g-3"),
    ], className="mb-4")


def tab_upgrades(team_rank: dict | None = None) -> html.Div:
    """What technical evolution each team brought to the loaded meeting(s).

    `team_rank` (team → championship position) orders the team cards; the
    router in app.py passes it in so this module needs no standings imports.
    """
    team_rank = team_rank or {}
    if upgrades_df().empty:
        return html.Div([dbc.Alert(
            [html.Strong("No upgrade data found. "),
             "Create ", html.Code("data/upgrades.csv"),
             " with columns: ",
             html.Code("season, event, team, component, category, "
                       "description, source"),
             ". The ", html.Code("event"), " value must match the meeting name "
             "(e.g. \"Austrian Grand Prix\") and ", html.Code("team"),
             " a known team name."],
            color="warning")])

    meetings = _loaded_meetings()
    if not meetings:
        return html.Div([dbc.Alert(
            "No session loaded. Load a meeting in the DATA & QUALITY tab to see "
            "the upgrades each team brought to it.", color="secondary",
            style={"background": CARD_BG, "border": f"1px solid {GRID_CLR}",
                   "color": TEXT_DIM})])

    legend = html.Div(
        [html.Span("Category:", style={"color": TEXT_DIM, "fontSize": "0.72rem",
                                       "marginRight": "8px"})]
        + [badge(c.title(), col) for c, col in _UPGRADE_CAT_COLORS.items()],
        style={"marginBottom": "16px"})

    blocks = [_upgrade_meeting_block(season, meeting, team_rank)
              for season, meeting in meetings]

    return html.Div([
        html.P("Technical upgrades each team brought to the loaded event(s), "
               "in the style of the FIA Car Presentation documents. "
               "Maintained in data/upgrades.csv.",
               style={"color": TEXT_DIM, "fontSize": "0.8rem",
                      "marginBottom": "10px"}),
        legend,
        *blocks,
    ])
