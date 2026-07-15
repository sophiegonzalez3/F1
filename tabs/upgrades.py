"""
UPGRADES tab — what technical evolution each team brought to the loaded
meeting(s), in the style of the FIA Car Presentation documents.

Data source: data/upgrades.csv (curated, human-maintained; see the column
notes below). This module is the template for extracting further tabs out of
app.py — see tabs/__init__.py for the recipe.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, callback, Input, Output
import dash_bootstrap_components as dbc

import f1lib.state as state
from f1lib.components import kpi, badge, card, theme, GFX, abbr
from f1lib.config import TEAM_COLORS, CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR
from tabs.pace_data import team_pace_df, event_short

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


# ── Upgrade impact analysis ──────────────────────────────────
# Crosses upgrades.csv with the per-event team pace table
# (data/team_pace_by_event.csv, built by compute_team_pace.py) to ask the
# question the FIA documents never answer: did the upgrade actually work?

_WINDOW = 2   # rounds before / after an upgrade averaged for the effect


def _impact_season() -> int | None:
    """Season to analyse: the latest one present in BOTH tables."""
    up, pace = upgrades_df(), team_pace_df()
    if up.empty or pace.empty:
        return None
    common = (set(up["season"].dropna().astype(int))
              & set(pace["season"].astype(int)))
    return max(common) if common else None


def _upgrade_rounds(season: int) -> pd.DataFrame:
    """One row per (team, round) that brought upgrades: item count,
    component list, and whether any item was a Performance upgrade."""
    up = upgrades_df()
    up = up[up["season"] == season].copy()
    pace = team_pace_df()
    ev2rnd = (pace[pace["season"] == season]
              .drop_duplicates("event").set_index("event")["round"])
    up["round"] = up["event"].map(ev2rnd)
    up = up.dropna(subset=["round"])
    if up.empty:
        return up
    up["round"] = up["round"].astype(int)
    up["is_perf"] = (up["category"].str.strip().str.casefold()
                     .isin(["performance", "circuit specific"]))
    return (up.groupby(["team", "round", "event"])
            .agg(n_items=("component", "count"),
                 components=("component", lambda s: ", ".join(s)),
                 any_perf=("is_perf", "any"))
            .reset_index())


def _gap_series(season: int) -> pd.DataFrame:
    """(round, team) → quali_gap_pct for the season, indexed for lookups."""
    pace = team_pace_df()
    s = pace[pace["season"] == season]
    return s.set_index(["team", "round"])["quali_gap_pct"]


def _effect_rows(season: int) -> pd.DataFrame:
    """Control-adjusted pace effect of every performance-upgrade round.

    raw effect   = mean gap over rounds [r, r+W-1] minus mean gap over
                   [r-W, r-1] (negative = the car closed on the front).
    control      = the median of that same delta across teams that brought
                   NOTHING that round — track/tyre/weather swings hit
                   everyone, so they cancel out here.
    adj effect   = raw − control  →  what the upgrade itself was worth.
    """
    ups = _upgrade_rounds(season)
    gaps = _gap_series(season)
    if ups.empty or gaps.empty:
        return pd.DataFrame()
    all_teams = gaps.index.get_level_values(0).unique()
    max_round = int(gaps.index.get_level_values(1).max())

    def delta(team, r) -> float:
        before = [gaps.get((team, x), np.nan)
                  for x in range(max(1, r - _WINDOW), r)]
        after = [gaps.get((team, x), np.nan)
                 for x in range(r, min(max_round, r + _WINDOW - 1) + 1)]
        before = [v for v in before if np.isfinite(v)]
        after = [v for v in after if np.isfinite(v)]
        if not before or not after:
            return np.nan
        return float(np.mean(after) - np.mean(before))

    rows = []
    for _, u in ups[ups["any_perf"]].iterrows():
        r = int(u["round"])
        if r <= 1:
            continue                       # no baseline before round 1
        raw = delta(u["team"], r)
        if not np.isfinite(raw):
            continue
        upgraded_here = set(ups.loc[ups["round"] == r, "team"])
        ctrl_vals = [delta(t, r) for t in all_teams if t not in upgraded_here]
        ctrl_vals = [v for v in ctrl_vals if np.isfinite(v)]
        control = float(np.median(ctrl_vals)) if ctrl_vals else 0.0
        rows.append({
            "team": u["team"], "round": r, "event": u["event"],
            "n_items": int(u["n_items"]), "components": u["components"],
            "raw": round(raw, 3), "control": round(control, 3),
            "effect": round(raw - control, 3),
        })
    return pd.DataFrame(rows).sort_values("effect")


def _effect_board_fig(eff: pd.DataFrame, season: int) -> go.Figure:
    labels = [f"{abbr(r.team)} · {event_short(r.event)}"
              for r in eff.itertuples()]
    fig = go.Figure(go.Bar(
        y=labels, x=eff["effect"], orientation="h",
        marker_color=[TEAM_COLORS.get(t, "#808080") for t in eff["team"]],
        customdata=np.stack([eff["components"], eff["raw"], eff["control"],
                             eff["n_items"]], axis=-1),
        hovertemplate=("<b>%{y}</b> (%{customdata[3]} items)<br>"
                       "%{customdata[0]}<br><br>"
                       "Effect vs field: %{x:+.2f} pp of quali gap<br>"
                       "(raw %{customdata[1]:+.2f}, field control "
                       "%{customdata[2]:+.2f})<extra></extra>"),
        text=[f"{v:+.2f}" for v in eff["effect"]], textposition="outside",
        textfont=dict(size=10),
    ))
    fig.add_vline(x=0, line=dict(color="white", width=1, dash="dash"))
    theme(fig, max(340, 26 * len(eff) + 110),
          f"Upgrade effect board – {season} · negative = car got faster")
    span = float(eff["effect"].abs().max()) if len(eff) else 1.0
    fig.update_xaxes(title_text="Change in quali gap to pole (pp), "
                                "field-adjusted", range=[-span*1.35, span*1.35])
    fig.update_layout(showlegend=False, bargap=0.35)
    return fig


def _team_trend_fig(season: int, team: str) -> go.Figure:
    pace = team_pace_df()
    s = pace[pace["season"] == season]
    g = s[s["team"] == team].sort_values("round")
    ups = _upgrade_rounds(season)
    ups = ups[ups["team"] == team]
    clr = TEAM_COLORS.get(team, "#808080")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=g["round"], y=g["quali_gap_pct"], mode="lines+markers",
        name="Quali gap", line=dict(color=clr, width=2.5),
        marker=dict(size=7),
        hovertemplate="Quali gap: %{y:.2f}%<extra></extra>"))
    rp = g[g["race_pace_gap_pct"].notna()]
    if not rp.empty:
        fig.add_trace(go.Scatter(
            x=rp["round"], y=rp["race_pace_gap_pct"], mode="lines+markers",
            name="Race pace gap", line=dict(color=clr, width=1.5, dash="dot"),
            marker=dict(size=6, symbol="diamond"),
            hovertemplate="Race gap: %{y:.2f}%<extra></extra>"))
    ymax = float(np.nanmax([g["quali_gap_pct"].max(),
                            g["race_pace_gap_pct"].max()]))
    for u in ups.itertuples():
        fig.add_vline(x=u.round, line=dict(color="#FFB000", width=1,
                                           dash="dash"))
        fig.add_trace(go.Scatter(
            x=[u.round], y=[ymax * 1.06], mode="markers",
            marker=dict(symbol="triangle-down", size=11, color="#FFB000"),
            showlegend=False,
            hovertemplate=(f"<b>{event_short(u.event)}</b> · "
                           f"{u.n_items} upgrade item(s)<br>{u.components}"
                           "<extra>upgrades</extra>"),
        ))
    rounds, labels = (s.drop_duplicates("round").sort_values("round")["round"].tolist(),
                      [event_short(e) for e in
                       s.drop_duplicates("round").sort_values("round")["event"]])
    theme(fig, 420, f"{team} – pace gap through {season} (▼ = upgrades)")
    fig.update_xaxes(tickmode="array", tickvals=rounds, ticktext=labels,
                     tickangle=-40)
    fig.update_yaxes(title_text="Gap to front (%) · lower = faster")
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0))
    return fig


def _impact_section() -> html.Div:
    season = _impact_season()
    if season is None:
        return html.Div()
    eff = _effect_rows(season)
    ups = _upgrade_rounds(season)
    teams = sorted(ups["team"].unique()) if not ups.empty else []
    if not teams:
        return html.Div()
    # Pre-select the constructor-championship runner-up (rank 2) when it's among
    # the teams that brought upgrades; otherwise fall back to the busiest
    # developer, then to the first team alphabetically.
    from f1lib.standings import _team_champ_rank
    rank = _team_champ_rank()
    runner_up = next((t for t, r in sorted(rank.items(), key=lambda kv: kv[1])
                      if r == 2 and t in teams), None)
    default_team = (runner_up
                    or (ups.groupby("team")["n_items"].sum().idxmax()
                        if not ups.empty else teams[0]))

    trend_card = card(
        "Upgrade Impact — team pace trend",
        html.Div([
            dcc.Dropdown(id="upg-impact-team",
                         options=[{"label": t, "value": t} for t in teams],
                         value=default_team, clearable=False,
                         style={"width": "260px", "backgroundColor": "#111",
                                "fontSize": "0.85rem", "marginBottom": "10px"}),
            dcc.Graph(id="upg-impact-trend",
                      figure=_team_trend_fig(season, default_team),
                      config=GFX),
        ]),
        info=("Data: the team's qualifying gap to pole (solid) and corrected "
              "race-pace gap (dotted) at every round, with ▼ marking the "
              "events where the team brought upgrades (hover for the FIA "
              "component list). Why: reads the season as a development "
              "story — a gap that steps down right after a ▼ is an upgrade "
              "that worked; one that doesn't is money spent for nothing."),
    )
    board_card = card(
        "Upgrade Effect Board — did it work?",
        dcc.Graph(figure=_effect_board_fig(eff, season), config=GFX)
        if not eff.empty else
        html.P("Not enough rounds around each upgrade to measure effects yet.",
               style={"color": TEXT_DIM}),
        info=(f"Data: for every performance/circuit upgrade package, the "
              f"team's average quali gap over the {_WINDOW} rounds from its "
              f"debut minus the {_WINDOW} rounds before, MINUS the median of "
              "the same delta for teams that brought nothing that round "
              "(the field control — track and conditions swings hit "
              "everyone, so they cancel). Negative = the car genuinely "
              "closed on the front. Why: the question the FIA Car "
              "Presentation documents never answer. Caveats: two rounds is "
              "a small sample and setup/driver form add noise — treat "
              "±0.1 pp as noise, not signal."),
    )
    return html.Div([trend_card, board_card])


@callback(Output("upg-impact-trend", "figure"),
          Input("upg-impact-team", "value"),
          prevent_initial_call=True)
def _update_impact_trend(team):
    season = _impact_season()
    if season is None or not team:
        return go.Figure()
    return _team_trend_fig(season, team)


def upgrade_impact_section() -> html.Div:
    """Upgrade-effectiveness analysis: the team pace-trend card and the
    'did it work?' effect board. Rendered in the SEASON tab (CAR UPGRADES).

    This is the season-long "did the development pay off?" view; the
    per-event "what did each team bring here?" breakdown lives separately in
    upgrade_event_detail() (WEEK END PRED tab).
    """
    if upgrades_df().empty or _impact_season() is None:
        return html.P(
            "No upgrade-impact data yet — needs both data/upgrades.csv and a "
            "season pace table (compute_team_pace.py) for the same year.",
            style={"color": TEXT_DIM, "fontSize": "0.8rem"})
    section = _impact_section()
    # _impact_section() returns an empty Div when there are upgrades but not
    # enough surrounding rounds to measure anything — keep a note in that case.
    if not getattr(section, "children", None):
        return html.P("Not enough rounds around each upgrade to measure "
                      "effects yet.", style={"color": TEXT_DIM})
    return section


def upgrade_event_detail(team_rank: dict | None = None) -> html.Div:
    """Per-event FIA-style "Car Presentation" breakdown: what technical
    evolution each team brought to the loaded meeting(s). Rendered at the top
    of the WEEK END PRED tab (the event the weekend is about).

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
