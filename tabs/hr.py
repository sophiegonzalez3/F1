"""
HR / personnel-movement section — the technical & management "transfer
market" that, under the budget cap, has become one of the biggest levers on a
team's long-term form.

Data source: data/staff_moves.csv (curated, human-maintained). One row per
move of a senior staff member (team principals, technical directors,
aero/PU/design heads, sporting & management leadership — not drivers).

    name        person, e.g. "Adrian Newey"
    role        job title at the destination, e.g. "Managing Technical Partner"
    category    Technical / Aerodynamics / Power Unit / Design / Management /
                Sporting / Team Principal
    from_team   previous employer (free text; F1 team or outside org)
    to_team     new employer — an F1 team name (matches TEAM_COLORS) or
                "Departed" when the person left the grid
    timeline    "announced → started" in one field, so the contractual
                gardening-leave gap the budget-cap era is full of reads at a
                glance (e.g. "2024-09 → 2025-03"); "→ TBC" for pending moves
    season      the first F1 season the move influences ON TRACK (a 2024
                signing that shapes the 2025 car is season 2025) — the field
                to search on
    status      Confirmed / Rumored / Gardening leave
    source      provenance URL
    notes       short free-text context; also where a source org's engine
                division or historical lineage is spelled out

from_team / to_team are harmonised to the destination's CURRENT F1-team node
(Sauber→Audi, Renault/Enstone→Alpine, Mercedes AMG HPP→Mercedes) so the data
feeds cleanly into a team-to-team flow/Sankey view; "Departed" is the sink for
people who left the grid, and the FIA / Formula 1 (FOM) are kept as their own
non-team nodes. Origin is the person's last F1 team even across an unemployment
gap (e.g. Horner is Red Bull, not "free agent").

Edit data/staff_moves.csv to add/replace rows — no code changes needed.
Rendered at the bottom of the SEASON tab.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, dash_table, callback, Input, Output
import dash_bootstrap_components as dbc

from f1lib.components import kpi, card, theme, GFX
from f1lib.config import TEAM_COLORS, CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR

_MOVES_PATH = Path("data/staff_moves.csv")
_MOVES_COLS = ["name", "nationality", "role", "category", "from_team",
               "to_team", "timeline", "season", "status", "source", "notes"]

# Teams whose destination cell we colour with their livery (current-grid
# canonical names; aliases and non-F1 orgs fall through to the default text).
_COLOURED_TEAMS = ["Ferrari", "Red Bull Racing", "Mercedes", "McLaren",
                   "Aston Martin", "Alpine", "Williams", "Racing Bulls",
                   "Haas F1 Team", "Audi", "Cadillac", "Sauber"]

_STATUS_COLORS = {
    "confirmed":       ACCENT,
    "rumored":         "#FFB000",
    "gardening leave": "#9B59B6",
}


def _load_moves() -> pd.DataFrame:
    if _MOVES_PATH.exists():
        try:
            df = pd.read_csv(_MOVES_PATH)
            for c in _MOVES_COLS:
                if c not in df.columns:
                    df[c] = "" if c != "season" else pd.NA
            df["season"] = pd.to_numeric(df["season"], errors="coerce").astype("Int64")
            for c in ("name", "nationality", "role", "category", "from_team",
                      "to_team", "timeline", "status", "source", "notes"):
                df[c] = df[c].fillna("").astype(str).str.strip()
            return df[_MOVES_COLS]
        except Exception as _exc:
            print(f"Staff moves             : failed to read ({_exc})")
    return pd.DataFrame(columns=_MOVES_COLS)


# Cache the parsed CSV but reload when the file changes on disk, so editing
# data/staff_moves.csv takes effect without restarting the app (mirrors the
# upgrades.csv loader).
_MOVES_CACHE: dict = {"mtime": None, "df": pd.DataFrame(columns=_MOVES_COLS)}


def moves_df() -> pd.DataFrame:
    """Current staff-moves table, re-read from disk when the CSV's mtime changes."""
    try:
        mtime = _MOVES_PATH.stat().st_mtime if _MOVES_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _MOVES_CACHE["mtime"]:
        _MOVES_CACHE["df"] = _load_moves()
        _MOVES_CACHE["mtime"] = mtime
    return _MOVES_CACHE["df"]


# ── Team headcount (scale context) ───────────────────────────
# Publicly reported per-team total staff. Approximate and mostly EXCLUDING
# engine divisions (see notes column). Department-level splits are not published
# by the teams, so this holds totals only.
_STAFF_PATH = Path("data/team_staff.csv")
_STAFF_COLS = ["team", "as_of", "total_staff", "source", "notes"]
_STAFF_CACHE: dict = {"mtime": None, "df": pd.DataFrame(columns=_STAFF_COLS)}


def _load_team_staff() -> pd.DataFrame:
    if _STAFF_PATH.exists():
        try:
            df = pd.read_csv(_STAFF_PATH)
            for c in _STAFF_COLS:
                if c not in df.columns:
                    df[c] = "" if c != "total_staff" else pd.NA
            df["total_staff"] = pd.to_numeric(df["total_staff"], errors="coerce")
            for c in ("team", "as_of", "source", "notes"):
                df[c] = df[c].fillna("").astype(str).str.strip()
            return df[_STAFF_COLS].dropna(subset=["total_staff"])
        except Exception as _exc:
            print(f"Team staff              : failed to read ({_exc})")
    return pd.DataFrame(columns=_STAFF_COLS)


def team_staff_df() -> pd.DataFrame:
    """Per-team headcount table, re-read when the CSV's mtime changes."""
    try:
        mtime = _STAFF_PATH.stat().st_mtime if _STAFF_PATH.exists() else None
    except OSError:
        mtime = None
    if mtime != _STAFF_CACHE["mtime"]:
        _STAFF_CACHE["df"] = _load_team_staff()
        _STAFF_CACHE["mtime"] = mtime
    return _STAFF_CACHE["df"]


# ── Representative department split (illustrative) ───────────
# Teams do NOT publish department headcount breakdowns, so this is a single
# representative F1-team structure, editable in data/dept_split_representative.csv
# — clearly labelled as illustrative, NOT any specific team's real figures.
_DEPT_PATH = Path("data/dept_split_representative.csv")
# Dark categorical palette (validated for the #1A1A2E surface via the dataviz
# skill's validator; fixed order, never cycled). CVD sits in the floor band, so
# the donut carries direct labels + 2px surface gaps as the secondary encoding.
_DEPT_PALETTE = ["#3987e5", "#199e70", "#c98500", "#008300",
                 "#9085e9", "#e66767", "#d55181", "#d95926"]


def _load_dept_split() -> pd.DataFrame:
    if _DEPT_PATH.exists():
        try:
            df = pd.read_csv(_DEPT_PATH)
            df["department"] = df["department"].fillna("").astype(str).str.strip()
            df["pct"] = pd.to_numeric(df["pct"], errors="coerce")
            return df.dropna(subset=["pct"])[["department", "pct"]]
        except Exception as _exc:
            print(f"Dept split              : failed to read ({_exc})")
    return pd.DataFrame(columns=["department", "pct"])


# ── Layout ───────────────────────────────────────────────────
_TABLE_COLS = [
    {"name": "Season",   "id": "season"},
    {"name": "Name",     "id": "name"},
    {"name": "Nat.",     "id": "nationality"},
    {"name": "Role",     "id": "role"},
    {"name": "Category", "id": "category"},
    {"name": "From",     "id": "from_team"},
    {"name": "To",       "id": "to_team"},
    {"name": "Announced → Started", "id": "timeline"},
    {"name": "Status",   "id": "status"},
    {"name": "Notes",    "id": "notes"},
    {"name": "Src",      "id": "source_md", "presentation": "markdown"},
]


def _style_conditional() -> list[dict]:
    styles = [
        {"if": {"row_index": "odd"}, "backgroundColor": "#0d0d1a"},
    ]
    # Colour each destination cell with the team livery.
    for team in _COLOURED_TEAMS:
        styles.append({
            "if": {"filter_query": f'{{to_team}} = "{team}"', "column_id": "to_team"},
            "color": TEAM_COLORS.get(team, TEXT_MAIN), "fontWeight": "700",
        })
    # Grey-out departures.
    styles.append({
        "if": {"filter_query": '{to_team} = "Departed"', "column_id": "to_team"},
        "color": TEXT_DIM, "fontStyle": "italic",
    })
    # Colour the status pill.
    for key, colr in _STATUS_COLORS.items():
        styles.append({
            "if": {"filter_query": f'{{status_lc}} = "{key}"', "column_id": "status"},
            "color": colr, "fontWeight": "700",
        })
    return styles


def _moves_table(df: pd.DataFrame) -> dash_table.DataTable:
    d = df.sort_values(["season", "timeline", "name"],
                       ascending=[False, False, True]).copy()
    d["source_md"] = d["source"].apply(
        lambda u: f"[↗]({u})" if u else "")
    d["status_lc"] = d["status"].str.casefold()          # hidden, drives styling
    d["season"] = d["season"].astype("Int64").astype(str).replace("<NA>", "")
    records = d.to_dict("records")
    return dash_table.DataTable(
        data=records, columns=_TABLE_COLS,
        sort_action="native", filter_action="native", page_size=15,
        style_table={"overflowX": "auto"},
        style_cell={
            "backgroundColor": CARD_BG, "color": TEXT_MAIN,
            "border": f"1px solid {GRID_CLR}", "fontSize": "12px",
            "padding": "7px 9px", "textAlign": "left",
            "whiteSpace": "normal", "height": "auto",
            "maxWidth": "260px", "minWidth": "60px",
        },
        style_header={
            "backgroundColor": "#09091A", "fontWeight": "bold",
            "color": ACCENT, "border": f"1px solid {GRID_CLR}",
            "textAlign": "left",
        },
        style_cell_conditional=[
            {"if": {"column_id": "role"}, "maxWidth": "210px"},
            {"if": {"column_id": "notes"}, "maxWidth": "290px",
             "color": TEXT_DIM, "fontSize": "11px"},
            {"if": {"column_id": "source_md"}, "textAlign": "center",
             "minWidth": "34px", "maxWidth": "40px"},
            {"if": {"column_id": "season"}, "minWidth": "56px",
             "maxWidth": "60px", "fontWeight": "700"},
            {"if": {"column_id": "nationality"}, "minWidth": "58px",
             "maxWidth": "78px", "color": TEXT_DIM},
            {"if": {"column_id": "timeline"}, "minWidth": "112px",
             "maxWidth": "130px", "whiteSpace": "nowrap"},
        ],
        style_data_conditional=_style_conditional(),
        markdown_options={"link_target": "_blank"},
    )


# ── Sankey flow ──────────────────────────────────────────────
# Team-momentum view: a bipartite Sankey with every team on the LEFT as an
# origin (talent leaving) and on the RIGHT as a destination (talent arriving).
# Bipartite = no cycles, so Plotly renders cleanly, and a team's left-bar vs
# right-bar thickness reads directly as "losing vs gaining people". Anything
# that isn't a current F1 team — Departed, FIA, FOM, and any future outside-
# industry / manufacturer / retirement entry — collapses into one "Other" node.
_OTHER_LABEL = "Other"
_OTHER_COLOR = "#6C6C6C"


def _node_team(name: str) -> str:
    return name if name in _COLOURED_TEAMS else _OTHER_LABEL


def _node_color(team: str) -> str:
    if team == _OTHER_LABEL:
        return _OTHER_COLOR
    return TEAM_COLORS.get(team, "#808080")


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _current_season(lo: int, hi: int) -> int:
    """Default upper bound of the season slider: the season now, clamped into
    the data's range. staff_moves carries announced future starts (2027-28),
    and opening on those would show a near-empty board."""
    from datetime import date
    return max(lo, min(hi, date.today().year))


def _season_window(df: pd.DataFrame, season_range, mode: str) -> pd.DataFrame:
    """Rows whose on-track influence season falls in the selected window.

    mode 'upto'  — everything from the start of the data to the upper handle
                   (the cumulative squad a team has assembled).
    mode 'only'  — only the selected span (who moved in THIS window).
    Rows with no season are kept in cumulative mode and dropped in
    year-only mode, where "which year" is the whole question.
    """
    if not season_range:
        return df
    lo, hi = int(min(season_range)), int(max(season_range))
    s = pd.to_numeric(df["season"], errors="coerce")
    if mode == "only":
        return df[s.between(lo, hi)]
    return df[s.le(hi) | s.isna()]


def _sankey_fig(df: pd.DataFrame, include_rumored: bool) -> go.Figure:
    d = df.copy()
    if not include_rumored:
        d = d[d["status"].str.casefold() != "rumored"]
    d = d[(d["from_team"] != "") & (d["to_team"] != "")]
    # Internal promotions (same org on both ends) are not team-to-team flow —
    # they live in their own bar chart below.
    d = d[d["from_team"] != d["to_team"]]

    fig = go.Figure()
    if d.empty:
        fig.update_layout(paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                          height=300, font=dict(color=TEXT_MAIN),
                          annotations=[dict(text="No moves for this filter.",
                                            showarrow=False,
                                            font=dict(color=TEXT_DIM))])
        return fig

    d["src"] = d["from_team"].map(_node_team)
    d["dst"] = d["to_team"].map(_node_team)

    outflow = d.groupby("src").size()
    inflow = d.groupby("dst").size()
    left = sorted(outflow.index, key=lambda t: (-outflow[t], t))
    right = sorted(inflow.index, key=lambda t: (-inflow[t], t))
    left_idx = {t: i for i, t in enumerate(left)}
    right_idx = {t: i + len(left) for i, t in enumerate(right)}

    labels = left + right
    node_colors = [_node_color(t) for t in left] + [_node_color(t) for t in right]

    node_x = [0.02] * len(left) + [0.98] * len(right)
    node_y = ([(i + 0.5) / max(len(left), 1) for i in range(len(left))]
              + [(i + 0.5) / max(len(right), 1) for i in range(len(right))])

    g = (d.groupby(["src", "dst"])
         .agg(n=("name", "size"),
              names=("name", lambda s: ", ".join(sorted(s))))
         .reset_index())
    sources = [left_idx[r.src] for r in g.itertuples()]
    targets = [right_idx[r.dst] for r in g.itertuples()]
    values = [int(r.n) for r in g.itertuples()]
    link_colors = [_rgba(_node_color(r.src), 0.40) for r in g.itertuples()]
    customdata = [r.names for r in g.itertuples()]

    fig.add_trace(go.Sankey(
        arrangement="snap",
        node=dict(
            label=labels, color=node_colors, x=node_x, y=node_y,
            pad=16, thickness=16, line=dict(color="#000", width=0.5),
            hovertemplate="<b>%{label}</b><br>%{value} move(s)<extra></extra>",
        ),
        link=dict(
            source=sources, target=targets, value=values, color=link_colors,
            customdata=customdata,
            hovertemplate=("<b>%{source.label} → %{target.label}</b><br>"
                           "%{value} move(s)<br>%{customdata}<extra></extra>"),
        ),
    ))
    n_nodes = max(len(left), len(right))
    seasons = d["season"].dropna()
    span = (f"{int(seasons.min())}–{int(seasons.max())}"
            if not seasons.empty else "")
    fig.update_layout(
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
        height=max(430, 34 * n_nodes + 120),
        margin=dict(l=10, r=10, t=54, b=20),
        title=dict(text="Where the people went — team-to-team staff flow "
                        f"({span})", font=dict(size=13)),
        annotations=[
            dict(x=0.02, y=1.06, xref="paper", yref="paper", showarrow=False,
                 text="◀ LOST FROM", font=dict(size=10, color=TEXT_DIM),
                 xanchor="left"),
            dict(x=0.98, y=1.06, xref="paper", yref="paper", showarrow=False,
                 text="GAINED BY ▶", font=dict(size=10, color=TEXT_DIM),
                 xanchor="right"),
        ],
    )
    return fig


def _net_fig(df: pd.DataFrame, include_rumored: bool) -> go.Figure:
    """Diverging bar of each team's NET senior-staff balance = arrivals minus
    departures (moves to/from the "Other" pool are ignored, since only real
    team-vs-team transfers change a team's standing)."""
    d = df.copy()
    if not include_rumored:
        d = d[d["status"].str.casefold() != "rumored"]
    d = d[(d["from_team"] != "") & (d["to_team"] != "")]
    d = d[d["from_team"] != d["to_team"]]        # promotions aren't churn
    d["src"] = d["from_team"].map(_node_team)
    d["dst"] = d["to_team"].map(_node_team)

    inflow = d[d["dst"] != _OTHER_LABEL].groupby("dst").size()
    outflow = d[d["src"] != _OTHER_LABEL].groupby("src").size()
    teams = sorted(set(inflow.index) | set(outflow.index))

    rows = []
    for t in teams:
        gi, go_ = int(inflow.get(t, 0)), int(outflow.get(t, 0))
        rows.append((t, gi, go_, gi - go_))
    rows.sort(key=lambda r: r[3])                     # most negative at bottom

    fig = go.Figure()
    if not rows:
        fig.update_layout(paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                          height=200, font=dict(color=TEXT_MAIN))
        return fig

    labels = [r[0] for r in rows]
    nets = [r[3] for r in rows]
    fig.add_trace(go.Bar(
        y=labels, x=nets, orientation="h",
        marker=dict(color=[TEAM_COLORS.get(t, "#808080") for t in labels],
                    line=dict(color="#000", width=0.5)),
        customdata=[[r[1], r[2]] for r in rows],
        text=[f"{n:+d}" for n in nets], textposition="outside",
        textfont=dict(size=11),
        hovertemplate=("<b>%{y}</b><br>Gained %{customdata[0]} · "
                       "Lost %{customdata[1]}<br>Net %{x:>+d}<extra></extra>"),
    ))
    fig.add_vline(x=0, line=dict(color=TEXT_DIM, width=1))
    span = max(abs(min(nets)), abs(max(nets)), 1)
    theme(fig, max(300, 30 * len(rows) + 120),
          "Net senior-staff balance by team · arrivals − departures")
    fig.update_xaxes(title_text="Net people gained (right) / lost (left)",
                     range=[-span - 1.2, span + 1.2], dtick=1, zeroline=False)
    fig.update_yaxes(title_text=None)
    fig.update_layout(margin=dict(l=118, r=24, t=50, b=44), showlegend=False,
                      bargap=0.35)
    return fig


def _promotions_fig(df: pd.DataFrame, include_rumored: bool) -> go.Figure:
    """Horizontal bar of INTERNAL promotions/appointments per team — rows where
    from_team == to_team. These are excluded from the Sankey and net-balance
    (they aren't churn) and counted here instead: a team backfilling from
    within reads very differently from one hiring off the market. Non-team
    orgs (FIA etc.) pool into 'Other' like everywhere else."""
    d = df.copy()
    if not include_rumored:
        d = d[d["status"].str.casefold() != "rumored"]
    d = d[(d["from_team"] != "") & (d["from_team"] == d["to_team"])]

    fig = go.Figure()
    if d.empty:
        fig.update_layout(paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                          height=200, font=dict(color=TEXT_MAIN),
                          annotations=[dict(text="No internal promotions for "
                                            "this filter.", showarrow=False,
                                            font=dict(color=TEXT_DIM))])
        return fig

    d["team"] = d["to_team"].map(_node_team)
    g = (d.groupby("team")
         .agg(n=("name", "size"),
              names=("name", lambda s: ", ".join(sorted(s))))
         .reset_index()
         .sort_values("n", ascending=True))

    labels = g["team"].tolist()
    vals = g["n"].tolist()
    fig.add_trace(go.Bar(
        y=labels, x=vals, orientation="h",
        marker=dict(color=[_node_color(t) for t in labels],
                    line=dict(color="#000", width=0.5)),
        customdata=g["names"].tolist(),
        text=[str(v) for v in vals], textposition="outside",
        textfont=dict(size=11),
        hovertemplate=("<b>%{y}</b><br>%{x} internal promotion(s)<br>"
                       "%{customdata}<extra></extra>"),
    ))
    theme(fig, max(260, 30 * len(labels) + 120),
          "Internal promotions by team · backfilling from within")
    fig.update_xaxes(title_text="People promoted / re-appointed internally",
                     dtick=1, rangemode="tozero")
    fig.update_yaxes(title_text=None)
    fig.update_layout(margin=dict(l=118, r=40, t=50, b=44), showlegend=False,
                      bargap=0.35)
    return fig


def _team_size_fig(df: pd.DataFrame) -> go.Figure:
    """Horizontal bar of each team's total headcount — the scale backdrop the
    move flows sit against."""
    d = df.sort_values("total_staff", ascending=True)
    labels = d["team"].tolist()
    vals = d["total_staff"].astype(int).tolist()
    fig = go.Figure(go.Bar(
        y=labels, x=vals, orientation="h",
        marker=dict(color=[TEAM_COLORS.get(t, "#808080") for t in labels],
                    line=dict(color="#000", width=0.5)),
        customdata=[[a, n] for a, n in zip(d["as_of"], d["notes"])],
        text=[f"{v:,}" for v in vals], textposition="outside",
        textfont=dict(size=11),
        hovertemplate=("<b>%{y}</b><br>~%{x:,} staff (%{customdata[0]})<br>"
                       "%{customdata[1]}<extra></extra>"),
    ))
    theme(fig, max(300, 30 * len(labels) + 120),
          "Team size · total staff (approx., mostly excl. engine divisions)")
    top = max(vals) if vals else 1000
    fig.update_xaxes(title_text="Employees (approx.)", range=[0, top * 1.18])
    fig.update_yaxes(title_text=None)
    fig.update_layout(margin=dict(l=118, r=40, t=50, b=44), showlegend=False,
                      bargap=0.35)
    return fig


def _dept_split_fig() -> go.Figure:
    """Illustrative donut of a representative F1-team department split. NOT any
    single team's real numbers — teams don't publish these."""
    d = _load_dept_split()
    fig = go.Figure()
    if d.empty:
        fig.update_layout(paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
                          height=300, font=dict(color=TEXT_MAIN))
        return fig
    colors = [_DEPT_PALETTE[i % len(_DEPT_PALETTE)] for i in range(len(d))]
    fig.add_trace(go.Pie(
        labels=d["department"].tolist(), values=d["pct"].tolist(),
        hole=0.52, sort=False, direction="clockwise",
        marker=dict(colors=colors, line=dict(color=CARD_BG, width=2)),
        textinfo="percent", textposition="inside",
        insidetextorientation="horizontal",
        textfont=dict(size=11, color="#ffffff"),
        hovertemplate="<b>%{label}</b><br>%{percent}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
        height=430, margin=dict(l=10, r=10, t=50, b=10),
        title=dict(text="Representative department split · illustrative",
                   font=dict(size=13)),
        legend=dict(orientation="v", x=1.0, xanchor="right", y=0.5,
                    yanchor="middle", font=dict(size=10)),
        annotations=[dict(text="typical<br>F1 team", x=0.5, y=0.5,
                          showarrow=False,
                          font=dict(size=11, color=TEXT_DIM))],
    )
    return fig


def hr_section() -> html.Div:
    """Personnel-movement board for the SEASON tab: KPI summary plus a fully
    searchable/sortable table of senior technical & management moves. The
    native filter row lets you search across every season at once — type a
    name, a team, a year or a role to trace who went where."""
    df = moves_df()
    if df.empty:
        return html.Div(html.P(
            ["No staff-move data found. Create ", html.Code("data/staff_moves.csv"),
             " with columns: ", html.Code(", ".join(_MOVES_COLS)),
             ". One row per senior technical/management move."],
            style={"color": TEXT_DIM, "fontSize": "0.8rem"}))

    n_total = len(df)
    n_confirmed = int((df["status"].str.casefold() == "confirmed").sum())
    n_tp = int(df["category"].str.casefold().isin(
        ["management", "team principal"]).sum())
    # Destinations that are actual F1 teams gaining people (exclude departures).
    gained = df[df["to_team"].isin(_COLOURED_TEAMS)]
    top_dest = (gained["to_team"].value_counts().index[0]
                if not gained.empty else "—")

    kpis = html.Div([
        kpi("MOVES LOGGED", str(n_total),
            tooltip="Total senior technical/management moves in the table."),
        kpi("CONFIRMED", str(n_confirmed), color=ACCENT,
            tooltip="Officially announced/reported moves (vs. rumored)."),
        kpi("LEADERSHIP CHANGES", str(n_tp), color="#FFB000",
            tooltip="Team-principal and senior-management moves."),
        kpi("MOST ACTIVE HIRER", top_dest,
            color=TEAM_COLORS.get(top_dest, ACCENT),
            tooltip="F1 team that picked up the most senior staff in the table."),
    ], className="row g-2 mb-2", style={"display": "flex", "flexWrap": "wrap"})

    intro = html.P(
        ["Under the budget cap, teams can no longer simply out-spend rivals on "
         "parts — so the fight has moved to people. This board tracks the "
         "senior technical & management ", html.Strong("transfer market"),
         ": who moved, from where to where, and the often-long gardening-leave "
         "gap between ", html.Em("announced"), " and ", html.Em("started"),
         ". Use the filter row under the headers to search across every season "
         "at once — a name, a team, a year or a role. Season = the first year "
         "the move influences the car on track."],
        style={"color": TEXT_DIM, "fontSize": "0.8rem", "marginBottom": "12px"})

    staff = team_staff_df()
    size_card = (card(
        "Team Size & Structure",
        html.Div([
            dbc.Row([
                dbc.Col(dcc.Graph(figure=_team_size_fig(staff), config=GFX),
                        md=7),
                dbc.Col(dcc.Graph(figure=_dept_split_fig(), config=GFX),
                        md=5),
            ], className="g-2"),
            html.P("Left: real, publicly reported totals per team. Right: a "
                   "representative department split — illustrative only, since "
                   "teams do not disclose their real department headcounts.",
                   style={"color": TEXT_DIM, "fontSize": "0.72rem",
                          "marginTop": "4px", "marginBottom": 0}),
        ]),
        info=("Left (real): data/team_staff.csv — publicly reported total staff "
              "per team, approximate and mostly EXCLUDING the separately-counted "
              "engine divisions (see each bar's hover). Right (illustrative): "
              "data/dept_split_representative.csv — a single representative "
              "F1-team department breakdown, NOT any specific team's figures, "
              "because teams do not publish department-level headcounts. Why: "
              "the move flows below land very differently on a 350-person Haas "
              "than a 1,200-person Mercedes."),
    ) if not staff.empty else html.Div())

    # Season range. Collapsing five years of transfer market into one picture
    # makes ribbon thickness meaningless as "momentum" — a team that rebuilt
    # in 2024 and has been quiet since looks identical to one signing now.
    seasons = pd.to_numeric(df["season"], errors="coerce").dropna()
    s_lo = int(seasons.min()) if not seasons.empty else 2024
    s_hi = int(seasons.max()) if not seasons.empty else 2026
    cur = _current_season(s_lo, s_hi)

    sankey_controls = html.Div([
        html.Div([
            dbc.Switch(id="hr-rumored-toggle", value=False,
                       label="Include rumored moves",
                       style={"display": "inline-block"}),
            html.Span("rumored flows are drawn only when this is on",
                      style={"color": TEXT_DIM, "fontSize": "0.72rem",
                             "marginLeft": "10px"}),
        ], style={"display": "flex", "alignItems": "center"}),
        html.Div([
            dbc.RadioItems(
                id="hr-season-mode", inline=True, value="upto",
                options=[{"label": "Cumulative to year", "value": "upto"},
                         {"label": "That year only", "value": "only"}],
                style={"fontSize": "0.75rem"},
                inputStyle={"marginRight": "4px"},
                labelStyle={"marginRight": "12px", "color": TEXT_DIM}),
        ], style={"marginTop": "6px"}),
        html.Div([
            html.Span("Seasons influenced on track",
                      style={"color": TEXT_DIM, "fontSize": "0.72rem"}),
            dcc.RangeSlider(
                id="hr-season-range", min=s_lo, max=s_hi, step=1,
                value=[s_lo, cur], allowCross=False,
                marks={y: {"label": str(y),
                           "style": {"color": TEXT_DIM, "fontSize": "0.7rem"}}
                       for y in range(s_lo, s_hi + 1)},
                tooltip={"placement": "bottom", "always_visible": False}),
        ], style={"marginTop": "4px", "maxWidth": "520px"}),
    ], style={"marginBottom": "8px"})

    df_win = _season_window(df, [s_lo, cur], "upto")

    sankey_card = card(
        "Team Momentum — staff flow (Sankey)",
        html.Div([
            sankey_controls,
            dcc.Graph(id="hr-sankey", figure=_sankey_fig(df_win, False),
                      config=GFX),
            html.Div(dcc.Graph(id="hr-net", figure=_net_fig(df_win, False),
                               config=GFX),
                     style={"borderTop": f"1px solid {GRID_CLR}",
                            "marginTop": "8px", "paddingTop": "6px"}),
        ]),
        info=("Data: the same staff_moves.csv, drawn as a team-to-team flow. "
              "Each person is one unit of flow from their origin team (left) to "
              "their destination team (right); bar thickness on the left = "
              "talent a team LOST, on the right = talent it GAINED, so you can "
              "read momentum at a glance. Anything that is not a current F1 "
              "team (departures, the FIA, FOM, sister divisions like AMPT or "
              "RBAT, and outside-industry orgs) is pooled into one 'Other' "
              "node. Internal promotions (same team on both ends) are NOT "
              "drawn here — they have their own card below. Toggle 'Include "
              "rumored' to fold in unconfirmed moves (e.g. Horner → Alpine). "
              "The season slider sets which moves are drawn, by the year each "
              "one first influences the car on track: 'cumulative to year' is "
              "the squad a team has assembled by then, 'that year only' is who "
              "moved in that window. It matters — undated, the chart pools "
              "five years of transfer market into one picture, so a team that "
              "rebuilt in 2024 and has been quiet since looks exactly like one "
              "signing hard right now. It opens on the current season."),
    )

    promo_card = card(
        "Internal Promotions — backfilling from within",
        dcc.Graph(id="hr-promotions", figure=_promotions_fig(df_win, False),
                  config=GFX),
        info=("Data: staff_moves.csv rows where origin and destination are the "
              "same team — promotions and internal re-appointments (e.g. "
              "Permane to Racing Bulls TP, Waterhouse's Red Bull remit, the "
              "Alpine three-TD restructure). Why: under the budget cap a team "
              "that promotes from within is making a different bet than one "
              "buying on the transfer market — this chart shows who leans on "
              "which approach. These rows are excluded from the Sankey and "
              "net-balance above so they don't inflate a team's churn; "
              "non-team orgs pool into 'Other'. Hover a bar for the names; "
              "the rumored toggle above applies here too."),
    )

    body = html.Div([intro, kpis, size_card, sankey_card, promo_card,
                     _moves_table(df)])
    return card(
        "Staff Movements — the budget-cap transfer market",
        body,
        info=("Data: data/staff_moves.csv, a curated list of senior technical "
              "and management moves (not drivers) from 2024 onwards — "
              "including announced future starts — each with a source link. Why: with spending frozen by the cap, recruiting "
              "the right technical leadership is one of the few remaining ways "
              "to buy pace — and gardening-leave clauses mean a signing today "
              "may not pay off for a year or two. The table is fully "
              "searchable/sortable; season is the first year the move shows up "
              "on track."),
    )


@callback([Output("hr-sankey", "figure"), Output("hr-net", "figure"),
           Output("hr-promotions", "figure")],
          [Input("hr-rumored-toggle", "value"),
           Input("hr-season-range", "value"),
           Input("hr-season-mode", "value")],
          prevent_initial_call=True)
def _update_hr_figs(include_rumored, season_range, mode):
    df = _season_window(moves_df(), season_range, mode)
    b = bool(include_rumored)
    return _sankey_fig(df, b), _net_fig(df, b), _promotions_fig(df, b)
