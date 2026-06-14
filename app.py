"""
F1 Dashboard – app.py 
Run:   python app.py
Open:  http://127.0.0.1:8050
"""
from __future__ import annotations
import logging, warnings
warnings.filterwarnings("ignore")

from pathlib import Path
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import dash
from dash import dcc, html, Input, Output, State, dash_table
import dash_bootstrap_components as dbc

from config import (
    TEAM_COLORS, COMPOUND_COLORS,
    DARK_BG, CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
    SPEED_PERCENTILE, get_min_laps_for_compound,
    MIN_LAPS_SOFT, MIN_LAPS_MEDIUM, MIN_LAPS_HARD,
    HISTORICAL_DIR,
)
from data_loader import load_sessions, cache_summary
from processing import (
    clean_and_enrich_laps, analyze_stints,
    identify_quali_sim_laps, best_laps_table,
    format_lap_time, enrich_telemetry, flag_perturbed_laps,
    enrich_weather, enrich_track_limits,
    enrich_blue_flags, enrich_session_results,
    flag_position_changes,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

# ── Sessions to load ─────────────────────────────────────────
SESSION_INFO_LIST = [
    {"SEASON": "2026", "MEETING": "Australian Grand Prix", "SESSION": "Practice 1"},
    {"SEASON": "2026", "MEETING": "Australian Grand Prix", "SESSION": "Practice 2"},
    {"SEASON": "2026", "MEETING": "Australian Grand Prix", "SESSION": "Practice 3"},
    {"SEASON": "2026", "MEETING": "Australian Grand Prix", "SESSION": "Qualifying"},
    {"SEASON": "2026", "MEETING": "Australian Grand Prix", "SESSION": "Race"},
]

# ── Load data ────────────────────────────────────────────────
print("Loading sessions (cache-first)…")
_data            = load_sessions(SESSION_INFO_LIST)
laps_raw         = _data["laps"]
telemetry_raw    = _data["telemetry"]
weather_raw      = _data["weather"]
race_control_raw = _data["race_control"]
results_raw      = _data["results"]
 
laps = clean_and_enrich_laps(laps_raw)
laps["stint_key"] = laps["Stint"].astype("string") + "_" + laps["session_name"]
laps = enrich_weather(laps, weather_raw)
laps = enrich_track_limits(laps, race_control_raw)
laps = enrich_blue_flags(laps, race_control_raw)
laps = identify_quali_sim_laps(laps)
laps = flag_perturbed_laps(laps, rcm=race_control_raw)
laps = enrich_session_results(laps, results_raw)
laps = flag_position_changes(laps)
stints    = analyze_stints(laps)
telemetry = enrich_telemetry(telemetry_raw, laps)

SESSIONS  = sorted(laps["session_name"].unique())
DRIVERS   = sorted(laps["Driver_Short"].dropna().unique())
COMPOUNDS = [c for c in ["SOFT","MEDIUM","HARD","INTER","WET"]
             if c in laps["Compound"].unique()]
TEAMS     = sorted(laps["Team"].dropna().unique())
print(f"Ready  sessions={len(SESSIONS)}  drivers={len(DRIVERS)}  teams={len(TEAMS)}")

# ── Circuit characteristics reference table ───────────────────
_CIRCUIT_CHARS_PATH = Path("data/circuit_characteristics.csv")
try:
    CIRCUIT_CHARS = pd.read_csv(_CIRCUIT_CHARS_PATH, encoding="utf-8-sig")
    print(f"Circuit characteristics: {len(CIRCUIT_CHARS)} circuits loaded")
except FileNotFoundError:
    CIRCUIT_CHARS = pd.DataFrame()
    print("WARNING: data/circuit_characteristics.csv not found — Track Info tab will be limited")

# ── Historical results (race + quali) ────────────────────────
_HIST_BASE = Path(HISTORICAL_DIR)
def _load_hist(filename):
    p = _HIST_BASE / filename
    if p.exists():
        try:
            return pd.read_parquet(p, engine="pyarrow")
        except Exception:
            try:
                return pd.read_csv(p)
            except Exception:
                pass
    return pd.DataFrame()

HIST_RACE  = _load_hist("race_results_all.parquet")
HIST_QUALI = _load_hist("quali_results_all.parquet")
print(f"Historical race results : {len(HIST_RACE):,} rows")
print(f"Historical quali results: {len(HIST_QUALI):,} rows")

# ── Theme ────────────────────────────────────────────────────
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

def card(title, children):
    return dbc.Card([
        dbc.CardHeader(html.Span(title, style={"fontWeight":"700","letterSpacing":"1px","fontSize":"0.85rem"})),
        dbc.CardBody(children),
    ], className="mb-3",
       style={"background":CARD_BG,"border":f"1px solid {GRID_CLR}","borderRadius":"8px"})

def kpi(label, value, color=ACCENT, tooltip=None):
    label_content = [label, html.Span(
        " ⓘ", title=tooltip,
        style={"cursor":"help","fontSize":"0.65rem","opacity":"0.6","userSelect":"none"}
    )] if tooltip else [label]
    return dbc.Col(dbc.Card(dbc.CardBody([
        html.P(label_content, style={"color":TEXT_DIM,"fontSize":"0.72rem","marginBottom":"4px","letterSpacing":"1px"}),
        html.H4(value, style={"color":color,"fontWeight":"800","marginBottom":0}),
    ]), style={"background":CARD_BG,"border":f"1px solid {GRID_CLR}","borderRadius":"8px"}),
    xs=6, md=3, className="mb-3")

GFX = {"displayModeBar": False}

TABLE_STYLE = dict(
    style_table={"overflowX":"auto"},
    style_cell={"backgroundColor":CARD_BG,"color":TEXT_MAIN,
                "border":f"1px solid {GRID_CLR}","fontSize":"12px","padding":"8px"},
    style_header={"backgroundColor":"#09091A","fontWeight":"bold",
                  "color":ACCENT,"border":f"1px solid {GRID_CLR}"},
    sort_action="native", filter_action="native", page_size=20,
)

# ── Helpers ──────────────────────────────────────────────────
def team_metrics(df):
    v = df[df["ValidLap"]].copy()
    ts = v.groupby("Team").agg(
        Avg_Lap_s=("LapTime_s","mean"), Median_Lap_s=("LapTime_s","median"),
        Lap_Std_s=("LapTime_s","std"),  Best_Lap_s=("LapTime_s","min"),
        Laps=("LapTime_s","count"),     FuelCorr_Median=("LapTime_FuelCorrected","median"),
        Avg_Speed=("PseudoSpeed","mean"),Stints=("Stint","max"),
        Drivers=("Driver_Short","nunique"),
    ).round(3)
    ts["Consistency"] = (ts["Lap_Std_s"]/ts["Median_Lap_s"]*100).round(2)
    f = ts["Best_Lap_s"].min()
    ts["Gap_to_Best_s"]   = (ts["Best_Lap_s"]-f).round(3)
    ts["Gap_to_Best_pct"] = ((ts["Best_Lap_s"]/f-1)*100).round(2)
    return ts.sort_values("Best_Lap_s").reset_index()

def tmgaps(df):
    v = df[df["ValidLap"]].copy()
    b = v.groupby(["Driver_Short","Team"])["LapTime_s"].min().reset_index()
    b.columns = ["Driver_Short","Team","Best_Lap"]
    r = v.groupby(["Driver_Short","Team"])["LapTime_s"].median().reset_index()
    r.columns = ["Driver_Short","Team","Race_Median"]
    s = v.groupby(["Driver_Short","Team"])["LapTime_s"].std().reset_index()
    s.columns = ["Driver_Short","Team","Race_Lap_Std_s"]
    lc= v.groupby(["Driver_Short","Team"])["LapTime_s"].count().reset_index()
    lc.columns=["Driver_Short","Team","Laps_count"]
    m = b.merge(r,on=["Driver_Short","Team"]).merge(s,on=["Driver_Short","Team"]).merge(lc,on=["Driver_Short","Team"])
    m = m.sort_values(["Team","Best_Lap"])
    out=[]
    for _,g in m.groupby("Team"):
        rows=g.to_dict("records"); n=len(rows)
        for i,d in enumerate(rows):
            qg=rg=None
            if n>=2:
                j=1-i if n==2 else None
                if j is not None:
                    o=rows[j]
                    qg=round(d["Best_Lap"]-o["Best_Lap"],3)
                    rg=round(d["Race_Median"]-o["Race_Median"],3)
            out.append({**d,"Quali_Gap_to_Teammate_s":qg,"Race_Gap_to_Teammate_s":rg})
    return pd.DataFrame(out)

def styled_table(data, cols):
    return dash_table.DataTable(data=data, columns=cols, **TABLE_STYLE,
        style_data_conditional=[{"if":{"row_index":0},"backgroundColor":ACCENT+"22","fontWeight":"700"}])

# ── App layout ───────────────────────────────────────────────
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG],
                title="F1 Dashboard", suppress_callback_exceptions=True)

SIDEBAR = dbc.Col([html.Div([
    html.Img(src="https://upload.wikimedia.org/wikipedia/commons/thumb/3/33/F1.svg/1200px-F1.svg.png",
             style={"height":"34px","marginBottom":"18px"}),
    html.Hr(style={"borderColor":GRID_CLR}),
    html.P("SESSIONS", style={"color":TEXT_DIM,"fontSize":"0.68rem","letterSpacing":"2px"}),
    dcc.Checklist(id="session-filter",
        options=[{"label":s,"value":s} for s in SESSIONS], value=SESSIONS,
        inputStyle={"marginRight":"8px","accentColor":ACCENT},
        labelStyle={"display":"block","marginBottom":"8px","fontSize":"0.78rem"}),
    html.Hr(style={"borderColor":GRID_CLR}),
    html.P("COMPOUNDS", style={"color":TEXT_DIM,"fontSize":"0.68rem","letterSpacing":"2px"}),
    dcc.Checklist(id="compound-filter",
        options=[{"label":html.Span(c,style={"color":COMPOUND_COLORS.get(c,"#fff")}),"value":c} for c in COMPOUNDS],
        value=COMPOUNDS,
        inputStyle={"marginRight":"8px","accentColor":ACCENT},
        labelStyle={"display":"block","marginBottom":"8px","fontSize":"0.78rem"}),
    html.Hr(style={"borderColor":GRID_CLR}),
    html.P("TEAMS", style={"color":TEXT_DIM,"fontSize":"0.68rem","letterSpacing":"2px"}),
    dcc.Dropdown(id="team-filter",
        options=[{"label":t,"value":t} for t in TEAMS], value=TEAMS, multi=True,
        style={"backgroundColor":"#111","fontSize":"0.78rem"}),
    html.Hr(style={"borderColor":GRID_CLR}),
    html.P("DRIVERS", style={"color":TEXT_DIM,"fontSize":"0.68rem","letterSpacing":"2px"}),
    dcc.Dropdown(id="driver-filter",
        options=[{"label":d,"value":d} for d in DRIVERS], value=DRIVERS, multi=True,
        style={"backgroundColor":"#111","fontSize":"0.78rem"}),
    html.Hr(style={"borderColor":GRID_CLR}),
    html.Small(cache_summary(), style={"color":TEXT_DIM,"fontSize":"0.65rem","whiteSpace":"pre-line"}),
], style={"padding":"16px","height":"100vh","overflowY":"auto",
          "background":"#09091A","borderRight":f"1px solid {GRID_CLR}"})],
width=2, style={"padding":"0"})

TABS = dbc.Tabs([
    dbc.Tab(label="DATA QUALITY",   tab_id="tab-quality"),
    dbc.Tab(label="OVERVIEW",       tab_id="tab-overview"),
    dbc.Tab(label="TEAM ANALYSIS",  tab_id="tab-teams"),
    dbc.Tab(label="LAP TIMES",      tab_id="tab-laps"),
    dbc.Tab(label="STINTS",         tab_id="tab-stints"),
    dbc.Tab(label="TEAMMATES",      tab_id="tab-teammates"),
    dbc.Tab(label="TELEMETRY",      tab_id="tab-telemetry"),
    dbc.Tab(label="HEATMAPS",       tab_id="tab-heatmaps"),
    dbc.Tab(label="TRACK INFO",     tab_id="tab-track"),
], id="tabs", active_tab="tab-quality",
   style={"borderBottom":f"2px solid {ACCENT}","marginBottom":"16px"})

MAIN = dbc.Col([
    html.H2("F1 SESSION ANALYSIS",
            style={"color":ACCENT,"fontWeight":"900","letterSpacing":"3px","marginBottom":"4px","fontSize":"1.3rem"}),
    html.P(" | ".join(SESSIONS), style={"color":TEXT_DIM,"marginBottom":"18px","fontSize":"0.78rem"}),
    TABS,
    html.Div(id="tab-content"),
], width=10, style={"padding":"24px","background":DARK_BG,"minHeight":"100vh"})

app.layout = dbc.Container(dbc.Row([SIDEBAR,MAIN],className="g-0"),
    fluid=True, style={"background":DARK_BG,"fontFamily":"Inter, sans-serif"})

# ── Routing callback ─────────────────────────────────────────
@app.callback(Output("tab-content","children"),
              Input("tabs","active_tab"),
              Input("session-filter","value"),
              Input("compound-filter","value"),
              Input("driver-filter","value"),
              Input("team-filter","value"))
def render(tab, ss, sc, sd, st):
    ss=ss or SESSIONS; sc=sc or COMPOUNDS; sd=sd or DRIVERS; st=st or TEAMS
    fl   = laps[laps["session_name"].isin(ss) & laps["Compound"].isin(sc)].copy()
    fl_d = fl[fl["Driver_Short"].isin(sd) & fl["Team"].isin(st)].copy()
    fs   = stints[stints["session_name"].isin(ss) & stints["Compound"].isin(sc)].copy()
    fs_d = fs[fs["Driver_Short"].isin(sd) & fs["Team"].isin(st)].copy()
    dnos = laps[laps["Driver_Short"].isin(sd)]["DriverNo"].unique()
    ft   = telemetry[telemetry["DriverNo"].isin(dnos) & telemetry["session_name"].isin(ss)].copy() if not telemetry.empty else telemetry
    if tab=="tab-quality":    return tab_data_quality(fl_d, fs_d)
    if tab=="tab-overview":   return tab_overview(fl_d,fs_d)
    if tab=="tab-teams":      return tab_teams(fl_d, fs_d)
    if tab=="tab-laps":       return tab_laps(fl_d)
    if tab=="tab-stints":     return tab_stints(fl_d,fs_d)
    if tab=="tab-teammates":  return tab_teammates(fl_d,fs_d)
    if tab=="tab-telemetry":  return tab_telemetry(fl_d,ft)
    if tab=="tab-heatmaps":   return tab_heatmaps(fl_d,ft)
    if tab=="tab-track":      return tab_track_info()
    return html.P("Select a tab.")

# ── Raw Laps Inspector callback ───────────────────────────────
@app.callback(
    Output("inspector-table", "children"),
    Input("inspector-driver",  "value"),
    Input("inspector-session", "value"),
)
def update_inspector(driver, session):
    if not driver or not session:
        return html.P("Select a driver and session.", style={"color": TEXT_DIM})
    sub = laps[(laps["Driver_Short"] == driver) & (laps["session_name"] == session)].sort_values("LapNo")
    if sub.empty:
        return html.P(f"No laps found for {driver} in {session}.", style={"color": TEXT_DIM})
    wanted = ["LapNo", "LapTime_s", "Compound", 'Compound_RAW', "TyreAge", "TyreLife", "LapInStint", "Stint"]
    avail  = [c for c in wanted if c in sub.columns]
    sub    = sub[avail].copy()
    if "LapTime_s" in sub.columns:
        sub.insert(sub.columns.get_loc("LapTime_s") + 1, "LapTime", sub["LapTime_s"].apply(format_lap_time))
    return dash_table.DataTable(
        data=sub.to_dict("records"),
        columns=[{"name": c, "id": c} for c in sub.columns],
        **TABLE_STYLE,
        style_data_conditional=[
            {"if": {"filter_query": "{LapInStint} = 1"}, "borderLeft": f"3px solid {ACCENT}"},
        ],
    )

# ── Stints – Lap Evolution graph callback ────────────────────
@app.callback(
    Output("stints-evo-graph", "figure"),
    Input("stints-evo-session",  "value"),
    State("compound-filter",     "value"),
    State("driver-filter",       "value"),
    State("team-filter",         "value"),
)
def update_stints_evo(session, sc, sd, st):
    sc = sc or COMPOUNDS
    sd = sd or DRIVERS
    st = st or TEAMS

    if not session:
        return go.Figure()

    sv = laps[
        (laps["session_name"] == session)
        & laps["Compound"].isin(sc)
        & laps["Driver_Short"].isin(sd)
        & laps["Team"].isin(st)
    ].copy()

    fig = go.Figure()

    for drv in sorted(sv["Driver_Short"].dropna().unique()):
        dv = sv[sv["Driver_Short"] == drv].sort_values("LapNo")
        if dv.empty:
            continue
        clr = TEAM_COLORS.get(dv["Team"].iloc[0], "#808080")
        # Build x/y/compound lists; insert None to break line at lap-number gaps
        x_vals, y_vals, c_vals, f_vals = [], [], [], []
        prev_lap = None
        for _, row in dv.iterrows():
            if prev_lap is not None and row["LapNo"] - prev_lap > 1:
                x_vals.append(None); y_vals.append(None)
                c_vals.append(None); f_vals.append(None)
            x_vals.append(row["LapNo"])
            y_vals.append(row["LapTime_s"] if pd.notna(row["LapTime_s"]) else None)
            c_vals.append(row.get("Compound") or "?")
            f_vals.append(row.get("TrackStatus_Flag") or "Clear")
            prev_lap = row["LapNo"]

        fig.add_trace(go.Scatter(
            x=x_vals, y=y_vals,
            mode="lines+markers",
            name=drv,
            line=dict(color=clr, width=1.5),
            marker=dict(
                size=6,
                color=[COMPOUND_COLORS.get(c, clr) if c else clr for c in c_vals],
                line=dict(color=clr, width=1),
            ),
            customdata=list(zip(c_vals, f_vals)),
            hovertemplate=(
                f"<b>{drv}</b><br>"
                "Lap %{x}  |  %{y:.3f} s<br>"
                "Compound: %{customdata[0]}<br>"
                "Flag: %{customdata[1]}<extra></extra>"
            ),
        ))

    # Overlay track-flag bands
    _add_flag_bands(fig, sv)

    sess_label = session.split("_")[0]
    theme(fig, 540, f"Lap Time Evolution \u2013 All Laps \u2013 {sess_label}")
    fig.update_layout(
        xaxis_title="Lap Number",
        yaxis_title="Lap Time (s)",
        legend=dict(
            bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1,
            orientation="v",
        ),
    )
    return fig


# ── Stint Lap Inspector callbacks ────────────────────────────
# Compound emoji map for dropdown labels
_COMPOUND_ICON = {"SOFT": "🔴", "MEDIUM": "🟡", "HARD": "⚪", "INTER": "🟢", "WET": "🔵"}


@app.callback(
    Output("stint-insp-key", "options"),
    Output("stint-insp-key", "value"),
    Input("stint-insp-driver", "value"),
    State("session-filter",   "value"),
    State("compound-filter",  "value"),
    State("team-filter",      "value"),
)
def update_stint_key_options(driver, ss, sc, st):
    """Build human-readable ranked-stint options for the inspector dropdown."""
    if not driver:
        return [], None
    ss = ss or SESSIONS
    sc = sc or COMPOUNDS
    st = st or TEAMS

    drv_stints = stints[
        (stints["Driver_Short"] == driver)
        & stints["session_name"].isin(ss)
        & stints["Compound"].isin(sc)
        & stints["Team"].isin(st)
        & stints["Valid_Stint"]
    ].copy()

    if drv_stints.empty:
        return [], None

    # Reconstruct Stint_key (analyze_stints doesn't carry it)
    drv_stints["Stint_key"] = (
        drv_stints["Stint"].astype("string")
        + "_" + drv_stints["Driver_Short"]
        + "_" + drv_stints["session_name"]
    )

    opts: list[dict] = []
    seen_keys: set[str] = set()

    def _add(label: str, row: pd.Series) -> None:
        key = row["Stint_key"]
        if pd.isna(key) or key in seen_keys:
            return
        seen_keys.add(key)
        compound = row.get("Compound", "?")
        icon     = _COMPOUND_ICON.get(compound, "⬜")
        pace_fmt = format_lap_time(row.get("Stint_Rep_Lap", float("nan")))
        laps_n   = int(row.get("Stint_Laps_Count", 0))
        sess     = str(row.get("session_name", "")).split("_")[0]
        opts.append({
            "label": f"{label}  {icon}{compound}  {pace_fmt}  ({laps_n} laps, {sess})",
            "value": key,
        })

    # ── 1. Best overall (lowest Stint_Rep_Lap across all valid stints) ──
    if "Stint_Rank_Overall" in drv_stints.columns:
        best_overall = drv_stints.sort_values("Stint_Rep_Lap").iloc[0]
        _add("Best overall", best_overall)

    # ── 2. Best per session (Stint_Rank_No_Compound = 1 in that session) ──
    for sess in sorted(drv_stints["session_name"].unique()):
        sess_label = sess.split("_")[0]
        sub = drv_stints[drv_stints["session_name"] == sess].sort_values("Stint_Rep_Lap")
        if not sub.empty:
            _add(f"Best in {sess_label}", sub.iloc[0])

    # ── 3. Best per compound (Stint_Rank_Across_Sessions = 1) ──
    for compound in COMPOUNDS:
        sub = drv_stints[drv_stints["Compound"] == compound].sort_values("Stint_Rep_Lap")
        if sub.empty:
            continue
        icon = _COMPOUND_ICON.get(compound, "⬜")
        _add(f"{icon} Best on {compound}", sub.iloc[0])

    # ── 4. Any remaining valid stints not yet listed ──
    for _, row in drv_stints.sort_values("Stint_Rep_Lap").iterrows():
        if row["Stint_key"] not in seen_keys:
            _add(f"   Stint {int(row['Stint'])}", row)

    first_val = opts[0]["value"] if opts else None
    return opts, first_val


@app.callback(
    Output("stint-insp-table", "children"),
    Input("stint-insp-driver", "value"),
    Input("stint-insp-key",    "value"),
)
def render_stint_table(driver, stint_key):
    if not driver or not stint_key:
        return html.P("Select a driver and stint key.", style={"color": TEXT_DIM})
    sub = laps[
        (laps["Driver_Short"] == driver) & (laps["Stint_key"] == stint_key)
    ].sort_values("LapNo")
    if sub.empty:
        return html.P("No laps found for this selection.", style={"color": TEXT_DIM})
    cols_want  = ["Stint_key", "LapNo", "LapTime_s", "Compound", "PseudoTyreAge", "TyreLife"]
    cols_avail = [c for c in cols_want if c in sub.columns]
    sub = sub[cols_avail].copy()
    if "LapTime_s" in sub.columns:
        pos = sub.columns.get_loc("LapTime_s") + 1
        sub.insert(pos, "LapTime", sub["LapTime_s"].apply(format_lap_time))
    return dash_table.DataTable(
        data=sub.to_dict("records"),
        columns=[{"name": c, "id": c} for c in sub.columns],
        **TABLE_STYLE,
        style_data_conditional=[
            {"if": {"filter_query": "{PseudoTyreAge} = 1"},
             "borderLeft": f"3px solid {ACCENT}"},
        ],
    )


# ══════════════════════════════════════════════════════════════
# TAB 0 – DATA QUALITY
# ══════════════════════════════════════════════════════════════
def _badge(text, color):
    """Small coloured pill."""
    return html.Span(text, style={
        "background": color, "color": "#fff", "borderRadius": "4px",
        "padding": "2px 8px", "fontSize": "0.7rem", "fontWeight": "700",
        "letterSpacing": "0.5px", "marginLeft": "6px",
    })

def _status_icon(ok: bool):
    return "✅" if ok else "❌"

def tab_data_quality(fl, fs):
    # ── 0. Global counts ────────────────────────────────────
    raw_rows      = len(laps_raw)
    enr_rows      = len(laps)
    row_match     = raw_rows == enr_rows

    total         = len(laps)
    has_laptime   = int(laps["LapTime_s"].notna().sum())
    pct_laptime   = has_laptime / total * 100 if total else 0
    valid_count   = int(laps["ValidLap"].sum())
    pct_valid     = valid_count / total * 100 if total else 0
    pit_count     = int(laps["PitLap"].sum())
    outlier_count = int((
        laps["LapTime_s"].notna()
        & (laps["LapTime_s"] > laps["LapTime_s"].median() * 1.25)
        & ~laps["PitLap"]
    ).sum())
    if "Perturbed_Lap" in laps.columns:
        perturbed_count = int(laps["Perturbed_Lap"].sum())
        pct_perturbed   = perturbed_count / total * 100 if total else 0
    else:
        perturbed_count = None
        pct_perturbed   = None

    # ── 1. Per-session overview ──────────────────────────────
    per_sess = (
        laps.groupby("session_name")
        .agg(
            Total_Laps   =("LapNo",       "count"),
            Valid_Laps   =("ValidLap",     "sum"),
            Pit_Laps     =("PitLap",       "sum"),
            With_LapTime =("LapTime_s",    lambda x: x.notna().sum()),
            Drivers      =("Driver_Short", "nunique"),
            Teams        =("Team",         "nunique"),
            Best_Lap_s   =("LapTime_s",    "min"),
            Median_Lap_s =("LapTime_s",    "median"),
            Stints       =("Stint",        "max"),
        )
        .reset_index()
    )
    per_sess["Valid_%"]   = (per_sess["Valid_Laps"]   / per_sess["Total_Laps"] * 100).round(1)
    per_sess["LapTime_%"] = (per_sess["With_LapTime"] / per_sess["Total_Laps"] * 100).round(1)
    per_sess["Best Lap"]  = per_sess["Best_Lap_s"].apply(format_lap_time)
    per_sess = per_sess.rename(columns={"session_name": "Session"})

    sess_tbl = styled_table(
        per_sess[[
            "Session", "Total_Laps", "Valid_Laps", "Valid_%", "Pit_Laps",
            "LapTime_%", "Drivers", "Teams", "Stints", "Best Lap",
        ]].to_dict("records"),
        [{"name": c, "id": c} for c in [
            "Session", "Total_Laps", "Valid_Laps", "Valid_%", "Pit_Laps",
            "LapTime_%", "Drivers", "Teams", "Stints", "Best Lap",
        ]],
    )

    # ── 2. Per-session timing leaderboard (sanity check) ────
    sanity_rows = []
    for sess in SESSIONS:
        sub = laps[(laps["session_name"] == sess) & laps["ValidLap"]].copy()
        if sub.empty:
            continue
        best = (
            sub.groupby("Driver_Short")
            .agg(Best_s=("LapTime_s", "min"), Team=("Team", "first"))
            .reset_index()
            .sort_values("Best_s")
            .reset_index(drop=True)
        )
        best["Rank"]    = best.index + 1
        best["Gap"]     = (best["Best_s"] - best["Best_s"].iloc[0]).apply(
            lambda x: "—" if x == 0 else f"+{x:.3f} s"
        )
        best["Lap Time"] = best["Best_s"].apply(format_lap_time)
        best["Session"]  = sess
        # add compound used on best lap
        best_lap_rows = (
            sub.loc[sub.groupby("Driver_Short")["LapTime_s"].idxmin()][
                ["Driver_Short", "Compound", "PseudoTyreAge", "LapNo"]
            ]
        )
        best = best.merge(best_lap_rows, on="Driver_Short", how="left")
        sanity_rows.append(best[["Rank","Session","Driver_Short","Team",
                                  "Lap Time","Gap","Compound","PseudoTyreAge","LapNo"]].head(3))

    sanity_df   = pd.concat(sanity_rows, ignore_index=True) if sanity_rows else pd.DataFrame()
    sanity_cols = ["Rank","Session","Driver_Short","Team","Lap Time","Gap","Compound","PseudoTyreAge","LapNo"]
    sanity_tbl  = styled_table(
        sanity_df.to_dict("records") if not sanity_df.empty else [],
        [{"name": c, "id": c} for c in sanity_cols] if not sanity_df.empty else [],
    )

    # ── 3. LapTime coverage bar (per session) ───────────────
    fig_cov = go.Figure()
    for _, row in per_sess.iterrows():
        sess = row["Session"]
        fig_cov.add_trace(go.Bar(
            x=[sess], y=[row["Valid_%"]],  name="Valid",
            marker_color="#00D2BE", showlegend=(_ == 0),
        ))
        fig_cov.add_trace(go.Bar(
            x=[sess], y=[row["LapTime_%"]], name="Has LapTime",
            marker_color="#FF8700", showlegend=(_ == 0),
        ))
    theme(fig_cov, 300, "Coverage per Session (%)")
    fig_cov.update_layout(barmode="group", yaxis=dict(range=[0,105], gridcolor=GRID_CLR, zeroline=False),
                           xaxis_title="Session", yaxis_title="%")

    # ── 5. ValidLap breakdown donut per session ──────────────
    breakdown_cards = []
    for sess in SESSIONS:
        sub = laps[laps["session_name"] == sess]
        n_valid    = int(sub["ValidLap"].sum())
        n_pit      = int(sub["PitLap"].sum())
        n_no_time  = int(sub["LapTime_s"].isna().sum())
        n_outlier  = int((
            sub["LapTime_s"].notna()
            & (sub["LapTime_s"] > sub["LapTime_s"].median() * 1.25)
            & ~sub["PitLap"]
        ).sum())
        n_other    = len(sub) - n_valid - n_pit - n_no_time - n_outlier
        n_other    = max(n_other, 0)
        fig_d = px.pie(
            names=["Valid","Pit/OutLap","No LapTime","Outlier (>125%)","Other excluded"],
            values=[n_valid, n_pit, n_no_time, n_outlier, n_other],
            color_discrete_sequence=["#00D2BE","#FF8700","#FFC0CB","#E10600","#808080"],
            hole=0.55,
        )
        theme(fig_d, 260, sess)
        fig_d.update_traces(textinfo="percent+label", textfont_size=9)
        fig_d.update_layout(showlegend=False, margin=dict(l=10,r=10,t=40,b=10))
        breakdown_cards.append(dbc.Col(dcc.Graph(figure=fig_d, config=GFX), md=6))

    # ── 6. Multi-compound stints (integrity check on RAW labels) ─
    # Uses Compound_RAW so we measure the original data quality
    # independently of the cleaning step.
    _compound_col = "Compound_RAW" if "Compound_RAW" in laps.columns else "Compound"
    stint_comp = (
        laps.dropna(subset=[_compound_col])
        .groupby("Stint_key")[_compound_col]
        .nunique()
        .reset_index()
        .rename(columns={_compound_col: "N_Compounds"})
    )
    dirty = stint_comp[stint_comp["N_Compounds"] > 1].copy()
    n_dirty        = len(dirty)
    n_total_stints = len(stint_comp)
    dirty_pct      = n_dirty / n_total_stints * 100 if n_total_stints else 0
    if n_dirty > 0:
        dirty_detail = laps[laps["Stint_key"].isin(dirty["Stint_key"])].groupby(
            ["Stint_key","session_name","Driver_Short","Stint"]
        ).agg(
            Raw_Compounds   =(  _compound_col, lambda x: ", ".join(x.dropna().unique())),
            Clean_Compounds =("Compound",      lambda x: ", ".join(x.dropna().unique())),
        ).reset_index()
        dirty_rows = dirty_detail.to_dict("records")
        dirty_cols = [{"name": c, "id": c} for c in dirty_detail.columns]
    else:
        dirty_rows, dirty_cols = [], []

    dirty_status = _status_icon(n_dirty == 0)
    dirty_tbl    = styled_table(dirty_rows, dirty_cols) if n_dirty > 0 else html.P(
        "✅ All stints use a single compound.", style={"color":"#00D2BE","fontWeight":"700"}
    )

    # ── 6b. Valid stints after cleaning ──────────────────────
    # How many stints pass the minimum-laps threshold on the CLEAN compound?
    # Mirrors analyze_stints logic: count valid laps per driver×stint×compound,
    # compare against the per-compound minimum.
    _stint_laps = (
        laps[laps["ValidLap"]]
        .groupby(["session_name", "Driver_Short", "Stint", "Compound"])
        .size()
        .reset_index(name="_laps")
    )
    _stint_laps["_min_req"] = _stint_laps["Compound"].apply(get_min_laps_for_compound)
    _stint_laps["_passes"]  = _stint_laps["_laps"] >= _stint_laps["_min_req"]
    n_stints_total = len(_stint_laps)
    n_stints_valid = int(_stint_laps["_passes"].sum())
    pct_stints_valid = n_stints_valid / n_stints_total * 100 if n_stints_total else 0

    # ── 7. PseudoTyreAge vs TyreAge comparison ───────────────
    has_tyre_col = "TyreAge" in laps.columns
    if has_tyre_col:
        _pool  = laps[laps["TyreAge"].notna() & laps["PseudoTyreAge"].notna()]
        sample = _pool.sample(min(2000, len(_pool)), random_state=42)
        fig_tyre = go.Figure(go.Scatter(
            x=sample["TyreAge"], y=sample["PseudoTyreAge"],
            mode="markers", marker=dict(size=4, color=ACCENT, opacity=0.5),
            hovertemplate="TyreAge: %{x}<br>PseudoTyreAge: %{y}<extra></extra>",
        ))
        mn = min(sample["TyreAge"].min(), sample["PseudoTyreAge"].min())
        mx = max(sample["TyreAge"].max(), sample["PseudoTyreAge"].max())
        fig_tyre.add_trace(go.Scatter(x=[mn,mx], y=[mn,mx], mode="lines",
            line=dict(color="#00D2BE", dash="dash", width=1), name="Perfect match"))
        theme(fig_tyre, 380, "PseudoTyreAge vs TyreAge (should be on the diagonal)")
        fig_tyre.update_layout(xaxis_title="TyreAge (raw)", yaxis_title="PseudoTyreAge (computed)")
        delta = (sample["PseudoTyreAge"] - sample["TyreAge"]).abs().mean()
        tyre_note = f"Mean absolute deviation: {delta:.2f} laps"
    else:
        fig_tyre = None
        tyre_note = "TyreAge column not present in dataset — PseudoTyreAge cannot be cross-validated."

    # ── 8. Unknown teams ────────────────────────────────────
    unknown_drvs = sorted(laps[laps["Team"] == "Unknown"]["Driver_Short"].unique())

    # ── 9. Column schema table ───────────────────────────────
    schema = pd.DataFrame({
        "Column":     laps.columns.tolist(),
        "DType":      [str(laps[c].dtype) for c in laps.columns],
        "Non-Null":   [int(laps[c].notna().sum()) for c in laps.columns],
        "NaN Count":  [int(laps[c].isna().sum())  for c in laps.columns],
        "NaN %":      [(laps[c].isna().sum() / total * 100).round(1) for c in laps.columns],
        "Unique Vals":[int(laps[c].nunique(dropna=False)) for c in laps.columns],
        "Sample":     [str(laps[c].dropna().iloc[0]) if laps[c].notna().any() else "—"
                       for c in laps.columns],
    })
    # highlight high-nan columns in red
    schema_tbl = dash_table.DataTable(
        data=schema.to_dict("records"),
        columns=[{"name": c, "id": c} for c in schema.columns],
        **TABLE_STYLE,
        style_data_conditional=[
            {"if": {"filter_query": "{NaN %} > 50"}, "backgroundColor": "#3D0A0A", "color": "#FF9999"},
            {"if": {"filter_query": "{NaN %} > 20 && {NaN %} <= 50"}, "backgroundColor": "#2D200A"},
            {"if": {"filter_query": "{NaN %} = 0"}, "color": "#00D2BE"},
        ],
    )

    # ── 10. Compound distribution heat (driver × compound × session) ─
    comp_counts = (
        fl[fl["ValidLap"]]
        .groupby(["session_name","Driver_Short","Compound"])
        .size()
        .reset_index(name="Laps")
    )
    if not comp_counts.empty:
        pivot_cc = comp_counts.pivot_table(
            index="Driver_Short", columns=["session_name","Compound"],
            values="Laps", fill_value=0
        )
        pivot_cc.columns = [f"{s}|{c}" for s, c in pivot_cc.columns]
        fig_comp_heat = go.Figure(go.Heatmap(
            z=pivot_cc.values,
            x=list(pivot_cc.columns),
            y=list(pivot_cc.index),
            colorscale="Blues",
            text=pivot_cc.values,
            texttemplate="%{text}",
            textfont={"size": 9},
            hovertemplate="Driver: %{y}<br>Session|Compound: %{x}<br>Valid Laps: %{z}<extra></extra>",
            colorbar=dict(title=dict(text="Laps", font=dict(color=TEXT_MAIN)), tickfont=dict(color=TEXT_MAIN)),
        ))
        theme(fig_comp_heat, max(300, 26 * len(pivot_cc) + 120),
              "Valid Laps per Driver × Session × Compound")
        fig_comp_heat.update_layout(
            margin=dict(l=80,r=60,t=60,b=120),
            xaxis=dict(tickangle=45, gridcolor=GRID_CLR, zeroline=False),
        )
    else:
        fig_comp_heat = None

    # ── Build layout ─────────────────────────────────────────
    return html.Div([
        # ── KPI row 1 ────────────────────────────────────────
        dbc.Row([
            kpi("TOTAL LAPS (raw)",      f"{raw_rows:,}", "#808080",
                tooltip="Raw row count from livef1 before any enrichment or cleaning."),
            kpi("TOTAL LAPS (enriched)", f"{enr_rows:,}",
                "#00D2BE" if row_match else ACCENT,
                tooltip="Row count after clean_and_enrich_laps(). Should match raw — a mismatch indicates a pipeline bug."),
            kpi("HAS LAP TIME",          f"{pct_laptime:.1f}%", "#FF8700",
                tooltip="% of laps with a non-null LapTime_s. Laps without a time are excluded from all pace analysis."),
            kpi("VALID LAPS",            f"{pct_valid:.1f}%", "#00D2BE",
                tooltip="% of laps passing ALL validity checks: non-pit, non-deleted, has LapTime, and within 125% of compound/team/session median."),
        ]),
        dbc.Row([
            kpi("ROW COUNT MATCH",  f"{_status_icon(row_match)} {'OK' if row_match else 'MISMATCH'}",
                "#00D2BE" if row_match else ACCENT,
                tooltip="Confirms clean_and_enrich_laps() preserved the exact row count. Any change indicates unintended row creation or deletion."),
            kpi("PIT / OUT LAPS",   f"{pit_count:,}", "#FFC0CB",
                tooltip="Laps where the driver entered or exited the pit lane. Excluded from pace and degradation analysis."),
            kpi("OUTLIERS REMOVED", f"{outlier_count:,}", ACCENT,
                tooltip="Laps slower than 125% of the per-session/compound/team median (excluding pit laps). Does NOT use flag_perturbed_laps — see PERTURBED LAPS below."),
            kpi("DIRTY STINTS (raw)",
                f"{dirty_status} {dirty_pct:.1f}% ({n_dirty}/{n_total_stints})",
                "#00D2BE" if n_dirty == 0 else ACCENT,
                tooltip="Based on Compound_RAW: % of stints where more than one raw compound label was recorded. Includes UNKNOWN/NaN that were later cleaned. Non-zero is expected — see the Stint Compound Integrity table below."),
            kpi("VALID STINTS (clean)",
                f"{pct_stints_valid:.1f}% ({n_stints_valid}/{n_stints_total})",
                "#00D2BE" if pct_stints_valid >= 50 else ACCENT,
                tooltip=f"After compound cleaning: % of driver×stint×compound groups meeting the minimum lap threshold (SOFT≥{MIN_LAPS_SOFT}, MEDIUM≥{MIN_LAPS_MEDIUM}, HARD≥{MIN_LAPS_HARD}). These are the stints usable for race pace and degradation analysis."),
        ]),
        *([dbc.Row([
            kpi("PERTURBED LAPS", f"{pct_perturbed:.1f}% ({perturbed_count:,})", "#FFC0CB",
                tooltip="Laps flagged by flag_perturbed_laps(): either TrackStatus indicates Yellow/SC/VSC/RedFlag, OR a sector time anomaly (>2.5× IQR above 75th pct for that driver/session/compound) was detected. These laps are NOT automatically excluded by ValidLap — filter on Perturbed_Lap=False for clean pace analysis."),
        ])] if perturbed_count is not None else []),

        # ── Pipeline check alerts ─────────────────────────────
        *([dbc.Alert(
            f"⚠️  Row count mismatch: raw={raw_rows:,} → enriched={enr_rows:,} "
            f"({enr_rows-raw_rows:+,} rows). Check clean_and_enrich_laps().",
            color="danger", style={"fontSize":"0.8rem","borderRadius":"6px"},
        )] if not row_match else []),
        *([dbc.Alert(
            f"⚠️  Unknown team detected for: {', '.join(unknown_drvs)}. "
            "The Driver column format may not contain '-TeamName'.",
            color="warning", style={"fontSize":"0.8rem","borderRadius":"6px"},
        )] if unknown_drvs else []),

        # ── Coverage & breakdown ─────────────────────────────
        card("Session Coverage (%)", dcc.Graph(figure=fig_cov, config=GFX)),
        card("Lap Breakdown by Session", dbc.Row(breakdown_cards)),

        # ── Per-session table ────────────────────────────────
        card("Per-Session Statistics", sess_tbl),

        # ── Timing leaderboard (sanity) ──────────────────────
        card(
            html.Span([
                "Timing Leaderboard — Sanity Check  (Top 3 per session)",
                _badge("compare against live memory", "#444"),
            ]),
            sanity_tbl,
        ),

        # ── Compound × Driver heatmap (sidebar-filtered) ─────
        *([card("Valid Laps: Driver × Session × Compound",
                dcc.Graph(figure=fig_comp_heat, config=GFX))] if fig_comp_heat else []),

        # ── Raw Laps Inspector ───────────────────────────────
        card(
            "Raw Laps Inspector",
            html.Div([
                html.P("Inspect every lap for one driver in one session — useful for verifying stint/tyre age detection.",
                       style={"color":TEXT_DIM,"fontSize":"0.8rem","marginBottom":"10px"}),
                dbc.Row([
                    dbc.Col([
                        html.Label("Driver", style={"color":TEXT_DIM,"fontSize":"0.75rem","letterSpacing":"1px"}),
                        dcc.Dropdown(
                            id="inspector-driver",
                            options=[{"label":d,"value":d} for d in sorted(laps["Driver_Short"].dropna().unique())],
                            value=sorted(laps["Driver_Short"].dropna().unique())[0] if len(laps["Driver_Short"].dropna().unique()) else None,
                            style={"backgroundColor":"#111","fontSize":"0.82rem"},
                            clearable=False,
                        ),
                    ], md=4),
                    dbc.Col([
                        html.Label("Session", style={"color":TEXT_DIM,"fontSize":"0.75rem","letterSpacing":"1px"}),
                        dcc.Dropdown(
                            id="inspector-session",
                            options=[{"label":s,"value":s} for s in SESSIONS],
                            value=SESSIONS[0] if SESSIONS else None,
                            style={"backgroundColor":"#111","fontSize":"0.82rem"},
                            clearable=False,
                        ),
                    ], md=4),
                ], className="mb-3"),
                html.Div(id="inspector-table"),
            ]),
        ),

        # ── Multi-compound stints ────────────────────────────
        card(
            html.Span([
                f"{dirty_status} Stint Compound Integrity (Compound_RAW)",
                _badge(f"{n_dirty} dirty stints ({dirty_pct:.1f}%)", "#00D2BE" if n_dirty==0 else ACCENT),
                _badge("Raw labels before cleaning — non-zero is expected", "#444"),
            ]),
            dirty_tbl,
        ),

        # ── TyreAge cross-validation ─────────────────────────
        card(
            "PseudoTyreAge vs TyreAge Cross-Validation",
            html.Div([
                html.P(tyre_note, style={"color": TEXT_DIM, "fontSize": "0.8rem", "marginBottom": "8px"}),
                dcc.Graph(figure=fig_tyre, config=GFX) if fig_tyre else html.Div(),
            ]),
        ),

        # ── Column schema ────────────────────────────────────
        card(
            html.Span([
                "Column Schema",
                _badge("green = 0% NaN  |  yellow = <50%  |  red = >50%", "#444"),
            ]),
            schema_tbl,
        ),
    ])


def tab_overview(fl, fs):
    v = fl[fl["ValidLap"]]
    best = format_lap_time(v["LapTime_s"].min()) if len(v) else "—"

    fig_vio = go.Figure()
    for drv in sorted(v["Driver_Short"].dropna().unique()):
        sub  = v[v["Driver_Short"]==drv]["LapTime_s"]
        team = fl[fl["Driver_Short"]==drv]["Team"].iloc[0]
        clr  = TEAM_COLORS.get(team,"#808080")
        fig_vio.add_trace(go.Violin(x=sub, name=drv,
            line_color=clr, fillcolor="rgba({},{},{},0.27)".format(
    int(clr[1:3],16), int(clr[3:5],16), int(clr[5:7],16)
), meanline_visible=True,
            orientation="h", points="all", jitter=0.05, pointpos=0,
            marker=dict(size=3,color=clr)))
    theme(fig_vio,420,"Lap Time Distribution by Driver")
    fig_vio.update_layout(violinmode="overlay",showlegend=False,xaxis_title="Lap Time (s)")

    cc = fl["Compound"].value_counts().reset_index()
    cc.columns=["Compound","Count"]
    fig_pie = px.pie(cc,names="Compound",values="Count",
                     color="Compound",color_discrete_map=COMPOUND_COLORS,hole=0.55)
    theme(fig_pie,300,"Compound Distribution")

    tm = team_metrics(fl)
    tm["Best Lap"] = tm["Best_Lap_s"].apply(format_lap_time)
    tm["Gap"]      = tm["Gap_to_Best_s"].apply(lambda x:f"+{x:.3f}" if x>0 else "—")
    tbl = styled_table(
        tm[["Team","Best Lap","Gap","Median_Lap_s","Lap_Std_s","Consistency","Avg_Speed","Laps"]].rename(columns={
            "Median_Lap_s":"Median (s)","Lap_Std_s":"Std Dev","Consistency":"Consistency %","Avg_Speed":"Avg Speed"
        }).to_dict("records"),
        [{"name":c,"id":c} for c in ["Team","Best Lap","Gap","Median (s)","Std Dev","Consistency %","Avg Speed","Laps"]]
    )
    # ── Driver Performance Matrix ─────────────────────────────
    tg = tmgaps(fl)
    fig_bub = go.Figure()
    max_laps = max(tg["Laps_count"].max(), 1)
    for team in sorted(tg["Team"].unique()):
        g   = tg[tg["Team"] == team]
        clr = TEAM_COLORS.get(team, "#808080")
        fig_bub.add_trace(go.Scatter(
            x=g["Best_Lap"], y=g["Race_Median"],
            mode="markers+text", name=team,
            marker=dict(color=clr, size=g["Laps_count"],
                        sizemode="area", sizeref=2.*max_laps/(40.**2),
                        symbol="circle"),
            text=g["Driver_Short"], textposition="top center",
            textfont=dict(size=10, color=TEXT_MAIN),
            customdata=g[["Driver_Short","Race_Lap_Std_s",
                           "Quali_Gap_to_Teammate_s","Race_Gap_to_Teammate_s"]].values,
            hovertemplate=(
                "Team=%{fullData.name}<br>Best Lap (s)=%{x:.3f}<br>"
                "Median Lap (s)=%{y:.3f}<br>Laps=%{marker.size}<br>"
                "Driver=%{customdata[0]}<br>Std=%{customdata[1]:.3f}<extra></extra>"
            ),
        ))
    theme(fig_bub, 520, "Driver Performance Matrix – Best Lap vs Race Pace (bubble = lap count)")
    fig_bub.update_layout(xaxis_title="Best Lap Time (s)", yaxis_title="Median Lap Time (s)")

    return html.Div([
        dbc.Row([kpi("BEST LAP",best,ACCENT), kpi("VALID LAPS",f"{len(v):,}","#00D2BE"),
                 kpi("DRIVERS",str(fl["Driver_Short"].nunique()),"#FF8700"),
                 kpi("SESSIONS",str(fl["session_name"].nunique()),"#FFC0CB")]),
        dbc.Row([dbc.Col(card("Lap Time Distribution",dcc.Graph(figure=fig_vio,config=GFX)),md=8),
                 dbc.Col(card("Compound Mix",dcc.Graph(figure=fig_pie,config=GFX)),md=4)]),
        card("Team Performance Overview",tbl),
        card("Driver Performance Matrix",dcc.Graph(figure=fig_bub,config=GFX)),
    ])

# ══════════════════════════════════════════════════════════════
# TAB 2 – TEAM ANALYSIS  (reworked)
# ══════════════════════════════════════════════════════════════
def tab_teams(fl, fs):
    try:
        return _tab_teams_inner2(fl, fs)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        return html.Div([
            dbc.Alert([html.B("Team Analysis – error: "), str(exc)],
                      color="danger", style={"fontSize": "0.82rem"}),
            html.Pre(tb, style={
                "color": TEXT_DIM, "fontSize": "0.7rem",
                "background": "#09091A", "padding": "12px",
                "borderRadius": "6px", "overflowX": "auto",
            }),
        ])


def _tab_teams_inner2(fl, fs):
    # ── Session detection ─────────────────────────────────────
    sess_names = fl["session_name"].unique().tolist()
    race_sess  = [s for s in sess_names
                  if (s.startswith("Race") or s.startswith("Sprint"))
                  and "Qualifying" not in s and "Shootout" not in s]
    quali_sess = [s for s in sess_names
                  if "Qualifying" in s or "Shootout" in s]
    has_race   = bool(race_sess)
    has_quali  = bool(quali_sess)

    v = fl[fl["ValidLap"]].copy()
    if v.empty:
        return html.P("No valid laps in current filter.", style={"color": TEXT_DIM})

    _pert   = fl["Perturbed_Lap"] if "Perturbed_Lap" in fl.columns else pd.Series(False, index=fl.index)
    v_clean = fl[fl["ValidLap"] & ~_pert].copy()

    # ── Build team → [driver1, driver2] mapping ───────────────
    pairs: dict = {}
    for team, grp in v.groupby("Team"):
        if str(team) in ("Unknown", "", "nan"):
            continue
        drvs = sorted(grp["Driver_Short"].dropna().unique().tolist())
        if drvs:
            pairs[team] = drvs[:2]

    if not pairs:
        return html.P("No teams found in current filter.", style={"color": TEXT_DIM})

    teams_all = sorted(pairs.keys())

    # ── Generic helpers ───────────────────────────────────────
    def _drv_val(pool, driver, agg_fn):
        sub = pool[pool["Driver_Short"] == driver]
        if sub.empty:
            return np.nan
        try:
            r = agg_fn(sub)
            return float(r) if (r is not None and pd.notna(r)) else np.nan
        except Exception:
            return np.nan

    def _best_of(va, vb, lower_is_better=True):
        vals = [x for x in [va, vb] if pd.notna(x) and np.isfinite(x)]
        if not vals:
            return np.nan
        return min(vals) if lower_is_better else max(vals)

    def _avg_of(va, vb):
        vals = [x for x in [va, vb] if pd.notna(x) and np.isfinite(x)]
        return float(np.mean(vals)) if vals else np.nan

    def _team_dicts(pool, agg_fn, lower_is_better=True):
        """Return (best_d, avg_d): team → aggregated float."""
        best_d, avg_d = {}, {}
        for team in teams_all:
            drvs = pairs[team]
            va = _drv_val(pool, drvs[0], agg_fn)
            vb = _drv_val(pool, drvs[1], agg_fn) if len(drvs) > 1 else np.nan
            best_d[team] = _best_of(va, vb, lower_is_better)
            avg_d[team]  = _avg_of(va, vb)
        return best_d, avg_d

    # ── % gap to leader helper ────────────────────────────────
    def _pct_gap(value, leader, lower_is_better):
        """Return % gap from leader. Leader = 0%. Others = positive %."""
        if not np.isfinite(leader) or leader == 0:
            return float("nan")
        if lower_is_better:
            return (value - leader) / abs(leader) * 100.0
        else:
            return (leader - value) / abs(leader) * 100.0

    # ── Horizontal bar chart – % gap to leader ────────────────
    def _hbar(data_d, title, fmt_fn=None, lower_is_better=True, xlabel="", pct_gap=True):
        items = [(t, vv) for t, vv in data_d.items() if pd.notna(vv) and np.isfinite(vv)]
        if not items:
            return go.Figure()
        items.sort(key=lambda x: x[1], reverse=not lower_is_better)
        fmt    = fmt_fn or (lambda v: f"{v:.3f}")
        leader = items[0][1]

        if pct_gap and abs(leader) > 1e-9:
            gaps   = [_pct_gap(v, leader, lower_is_better) for _, v in items]
            x_vals = gaps
            # bar text: original value for leader, "value (+gap%)" for others
            bar_text = [
                fmt(v) if i == 0 else f"{fmt(v)}  +{g:.2f}%"
                for i, ((_, v), g) in enumerate(zip(items, gaps))
            ]
            x_title = "% gap to leader  (0 = best)"
        else:
            x_vals  = [v for _, v in items]
            bar_text = [fmt(v) for _, v in items]
            x_title = xlabel or title

        ts     = [i[0] for i in items]
        colors = [TEAM_COLORS.get(t, "#808080") for t in ts]
        fig = go.Figure(go.Bar(
            x=x_vals, y=ts, orientation="h",
            marker_color=colors,
            text=bar_text,
            textposition="outside",
            textfont=dict(size=9, color=TEXT_MAIN),
            hovertemplate="%{y}: %{text}<extra></extra>",
        ))
        h = max(200, len(items) * 44 + 90)
        theme(fig, h, title)
        fig.update_layout(
            xaxis_title=x_title,
            showlegend=False,
            margin=dict(l=140, r=140, t=50, b=40),
        )
        fig.update_xaxes(rangemode="tozero")
        fig.update_yaxes(autorange="reversed")
        return fig

    # ── Grouped compound bar – % gap per compound ─────────────
    def _compound_bars(compound_dicts, title, fmt_fn=None, lower_is_better=True):
        """compound_dicts: {compound: {team: value}}
        Each compound normalised independently to its own leader (0%)."""
        # Sort order by best overall value across compounds
        best_overall: dict = {}
        for cmp, d in compound_dicts.items():
            for t, vv in d.items():
                if pd.notna(vv) and np.isfinite(vv):
                    if t not in best_overall:
                        best_overall[t] = vv
                    else:
                        best_overall[t] = (
                            min(vv, best_overall[t]) if lower_is_better
                            else max(vv, best_overall[t])
                        )
        if not best_overall:
            return go.Figure()
        team_order = sorted(best_overall.keys(),
                            key=lambda t: best_overall[t],
                            reverse=not lower_is_better)
        fmt = fmt_fn or (lambda v: f"{v:.3f}")
        fig = go.Figure()
        for cmp, d in compound_dicts.items():
            raw_items = [(t, d[t]) for t in team_order
                         if pd.notna(d.get(t, np.nan)) and np.isfinite(d.get(t, np.nan))]
            if not raw_items:
                continue
            cmp_leader = min(v for _, v in raw_items) if lower_is_better else max(v for _, v in raw_items)
            y_teams = [t for t, _ in raw_items]
            gaps    = [_pct_gap(v, cmp_leader, lower_is_better) for _, v in raw_items]
            bar_text = [
                fmt(v) if i == 0 else f"{fmt(v)}  +{g:.2f}%"
                for i, ((_, v), g) in enumerate(zip(raw_items, gaps))
            ]
            fig.add_trace(go.Bar(
                x=gaps, y=y_teams, name=cmp,
                orientation="h",
                marker_color=COMPOUND_COLORS.get(cmp, "#808080"),
                text=bar_text,
                textposition="outside",
                textfont=dict(size=8, color=TEXT_MAIN),
                hovertemplate=f"<b>{{{{y}}}}</b> – {cmp}: %{{text}}<extra></extra>",
            ))
        h = max(220, len(team_order) * 58 + 130)
        theme(fig, h, title)
        fig.update_layout(
            barmode="group", showlegend=True,
            xaxis_title="% gap to compound leader  (0 = best per compound)",
            margin=dict(l=140, r=140, t=50, b=40),
            legend=dict(orientation="h", x=0, y=1.14, bgcolor="rgba(0,0,0,0)"),
        )
        fig.update_xaxes(rangemode="tozero")
        fig.update_yaxes(autorange="reversed", categoryorder="array",
                         categoryarray=list(reversed(team_order)))
        return fig

    # ── Laps per session grouped bar – % gap per session ──────
    def _session_laps_bar(laps_per_sess, title, fmt_fn=None):
        fig = go.Figure()
        for sess, d in laps_per_sess.items():
            items = [(t, vv) for t, vv in d.items() if pd.notna(vv) and vv > 0]
            if not items:
                continue
            # Higher laps = better; leader is the team with most laps this session
            leader_laps = max(v for _, v in items)
            ts = [i[0] for i in items]
            vs = [i[1] for i in items]
            gaps = [_pct_gap(v, leader_laps, lower_is_better=False) for v in vs]
            bar_text = [
                (fmt_fn(v) if fmt_fn else str(int(v))) if g == 0.0
                else ((fmt_fn(v) if fmt_fn else str(int(v))) + f"  +{g:.1f}%")
                for v, g in zip(vs, gaps)
            ]
            fig.add_trace(go.Bar(
                y=ts, x=gaps, name=sess.split("_")[0], orientation="h",
                text=bar_text,
                textposition="outside",
                textfont=dict(size=8, color=TEXT_MAIN),
                hovertemplate=f"<b>{{{{y}}}}</b> – {sess.split('_')[0]}: %{{text}}<extra></extra>",
            ))
        h = max(220, len(teams_all) * 50 + 130)
        theme(fig, h, title)
        fig.update_layout(
            barmode="group", showlegend=True,
            xaxis_title="% gap to session leader  (0 = most laps per session)",
            margin=dict(l=140, r=140, t=50, b=40),
            legend=dict(orientation="h", x=0, y=1.14, bgcolor="rgba(0,0,0,0)"),
        )
        fig.update_xaxes(rangemode="tozero")
        fig.update_yaxes(autorange="reversed")
        return fig

    # ═════════════════════════════════════════════════════════
    # COMPUTE ALL METRICS
    # ═════════════════════════════════════════════════════════

    # ── M1: Race pace per compound (best stint, all sessions) ─
    def _best_stint_for_driver(driver, compound):
        if fs is not None and not fs.empty and "Stint_Rank_Across_Sessions" in fs.columns:
            best_s = fs[
                (fs["Driver_Short"] == driver) &
                (fs["Compound"] == compound) &
                fs["Valid_Stint"] &
                (fs["Stint_Rank_Across_Sessions"] == 1)
            ]
            if not best_s.empty and "Stint_FuelCorr" in best_s.columns:
                v_ = pd.to_numeric(best_s["Stint_FuelCorr"], errors="coerce").dropna()
                if not v_.empty:
                    return float(v_.iloc[0])
        # Fallback: trimmed median of fuel-corrected (or raw) laps
        col = "LapTime_FuelCorrected" if "LapTime_FuelCorrected" in v_clean.columns else "LapTime_s"
        sub = v_clean[(v_clean["Driver_Short"] == driver) & (v_clean["Compound"] == compound)]
        if sub.empty:
            return np.nan
        t = sub[col].dropna()
        if t.empty:
            return np.nan
        lo, hi = t.quantile(0.10), t.quantile(0.90)
        trimmed = t[t.between(lo, hi)]
        return float(trimmed.median() if not trimmed.empty else t.median())

    race_pace_best_by_cmp: dict = {}
    race_pace_avg_by_cmp:  dict = {}
    for cmp in COMPOUNDS:
        bd, ad = {}, {}
        for team in teams_all:
            drvs = pairs[team]
            va = _best_stint_for_driver(drvs[0], cmp)
            vb = _best_stint_for_driver(drvs[1], cmp) if len(drvs) > 1 else np.nan
            b  = _best_of(va, vb, lower_is_better=True)
            a  = _avg_of(va, vb)
            if pd.notna(b):
                bd[team] = b
            if pd.notna(a):
                ad[team] = a
        if bd:
            race_pace_best_by_cmp[cmp] = bd
        if ad:
            race_pace_avg_by_cmp[cmp]  = ad

    # ── M2: Best lap overall (all sessions, all compounds) ────
    best_lap_best, best_lap_avg = _team_dicts(v, lambda s: s["LapTime_s"].min())

    # ── M3: NB laps – total ───────────────────────────────────
    laps_tot_best, laps_tot_avg = _team_dicts(
        v, lambda s: float(len(s)), lower_is_better=False)

    # ── M3b: NB laps – per session ────────────────────────────
    laps_per_sess_best: dict = {}
    laps_per_sess_avg:  dict = {}
    for sess in sorted(sess_names):
        pool = v[v["session_name"] == sess]
        if pool.empty:
            continue
        b, a = _team_dicts(pool, lambda s: float(len(s)), lower_is_better=False)
        laps_per_sess_best[sess] = b
        laps_per_sess_avg[sess]  = a

    # ── M4: Pit stop time (race/sprint only) ──────────────────
    pit_best: dict = {}
    pit_avg:  dict = {}
    if has_race and "PitIn" in fl.columns and "PitOut" in fl.columns:
        _race_laps = fl[fl["session_name"].isin(race_sess)].sort_values(
            ["session_name", "DriverNo", "LapNo"])
        _pit_rows: list = []
        for (sess, drv_no), grp in _race_laps.groupby(["session_name", "DriverNo"]):
            grp_s    = grp.sort_values("LapNo")
            in_laps  = grp_s[grp_s["InLap"]  & grp_s["PitIn"].notna()]
            out_laps = grp_s[grp_s["OutLap"] & grp_s["PitOut"].notna()]
            out_dict: dict = {}
            for _, orow in out_laps.iterrows():
                ln = int(orow["LapNo"])
                if ln not in out_dict:
                    out_dict[ln] = float(orow["PitOut"])
            for _, inrow in in_laps.iterrows():
                nxt = int(inrow["LapNo"]) + 1
                try:
                    pit_in_s = float(inrow["PitIn"])
                    if nxt in out_dict and np.isfinite(pit_in_s) and np.isfinite(out_dict[nxt]):
                        dur = out_dict[nxt] - pit_in_s
                        if 1.5 < dur < 65.0:
                            _pit_rows.append({
                                "Driver_Short": inrow["Driver_Short"],
                                "Team":         inrow["Team"],
                                "dur":          dur,
                            })
                except Exception:
                    pass
        if _pit_rows:
            _pit_df = pd.DataFrame(_pit_rows)
            pit_best, pit_avg = _team_dicts(
                _pit_df, lambda s: s["dur"].mean(), lower_is_better=True)

    # ── M5: Qualifying performance ────────────────────────────
    quali_best: dict = {}
    quali_avg:  dict = {}
    if has_quali:
        _ql = fl[fl["session_name"].isin(quali_sess)]
        q_cols = [c for c in ("Q3_s", "Q2_s", "Q1_s") if c in fl.columns]

        def _best_q_for(driver):
            sub = _ql[_ql["Driver_Short"] == driver]
            if sub.empty:
                return np.nan
            for qc in q_cols:
                v_ = pd.to_numeric(sub[qc], errors="coerce").dropna()
                if not v_.empty:
                    return float(v_.iloc[0])
            bl = sub[sub["ValidLap"]]["LapTime_s"].dropna()
            return float(bl.min()) if not bl.empty else np.nan

        for team in teams_all:
            drvs = pairs[team]
            va = _best_q_for(drvs[0])
            vb = _best_q_for(drvs[1]) if len(drvs) > 1 else np.nan
            b  = _best_of(va, vb, lower_is_better=True)
            a  = _avg_of(va, vb)
            if pd.notna(b):
                quali_best[team] = b
            if pd.notna(a):
                quali_avg[team]  = a

    # ── M6: Race pace perf (race/sprint sessions only) ────────
    race_pace_perf_best: dict = {}
    race_pace_perf_avg:  dict = {}
    if has_race:
        v_race = v_clean[v_clean["session_name"].isin(race_sess)]

        def _race_perf_for(driver):
            if fs is not None and not fs.empty:
                fs_race = fs[
                    fs["session_name"].isin(race_sess) &
                    (fs["Driver_Short"] == driver) &
                    fs["Valid_Stint"]
                ]
                if not fs_race.empty and "Stint_Rep_Lap" in fs_race.columns:
                    best = fs_race["Stint_Rep_Lap"].dropna().min()
                    if pd.notna(best):
                        return float(best)
            sub = v_race[v_race["Driver_Short"] == driver]
            if sub.empty:
                return np.nan
            col = "LapTime_FuelCorrected" if "LapTime_FuelCorrected" in sub.columns else "LapTime_s"
            t   = sub[col].dropna()
            if t.empty:
                return np.nan
            lo, hi = t.quantile(0.10), t.quantile(0.90)
            trimmed = t[t.between(lo, hi)]
            return float(trimmed.median() if not trimmed.empty else t.median())

        for team in teams_all:
            drvs = pairs[team]
            va = _race_perf_for(drvs[0])
            vb = _race_perf_for(drvs[1]) if len(drvs) > 1 else np.nan
            b  = _best_of(va, vb, lower_is_better=True)
            a  = _avg_of(va, vb)
            if pd.notna(b):
                race_pace_perf_best[team] = b
            if pd.notna(a):
                race_pace_perf_avg[team]  = a

    # ── M7: Positions gained / lost (race/sprint only) ────────
    pgain_best: dict = {}
    pgain_avg:  dict = {}
    if has_race and "Classified_Position" in fl.columns:
        _rr = fl[fl["session_name"].isin(race_sess)].copy()
        _rr["_fin"]  = pd.to_numeric(_rr["Classified_Position"], errors="coerce")
        _rr["_grid"] = (
            pd.to_numeric(_rr["Grid_Position"], errors="coerce")
            if "Grid_Position" in _rr.columns else np.nan
        )
        _rr["_gain"] = _rr["_grid"] - _rr["_fin"]
        _rr_drv = (
            _rr.groupby(["session_name", "Driver_Short"])
            .agg(_gain=("_gain", "first"))
            .reset_index()
            .groupby("Driver_Short")["_gain"]
            .sum()
            .reset_index()
        )
        _drv_team_map = (
            fl[["Driver_Short", "Team"]].drop_duplicates("Driver_Short")
            .set_index("Driver_Short")["Team"].to_dict()
        )
        _rr_drv["Team"] = _rr_drv["Driver_Short"].map(_drv_team_map)

        for team in teams_all:
            drvs = pairs[team]
            sub_a = _rr_drv[_rr_drv["Driver_Short"] == drvs[0]]
            sub_b = (_rr_drv[_rr_drv["Driver_Short"] == drvs[1]]
                     if len(drvs) > 1 else pd.DataFrame())
            va = float(sub_a["_gain"].iloc[0]) if not sub_a.empty else np.nan
            vb = float(sub_b["_gain"].iloc[0]) if not sub_b.empty else np.nan
            b  = _best_of(va, vb, lower_is_better=False)   # higher gain = better
            a  = _avg_of(va, vb)
            if pd.notna(b):
                pgain_best[team] = b
            if pd.notna(a):
                pgain_avg[team]  = a

    # ═════════════════════════════════════════════════════════
    # CONSTRUCTOR CHAMPIONSHIP STANDINGS WIDGET
    # Current 2026 constructor standings (after Australian GP,
    # which is race 1 of the season and the loaded meeting).
    # Position delta = change caused by the race sessions in fl.
    # ═════════════════════════════════════════════════════════

    # Hardcoded current standings after Australian GP 2026
    # Keys must match Team names in laps data (from TEAM_COLORS)
    _CHAMP_CURRENT: dict = {
        "Mercedes":         43,
        "Ferrari":          27,
        "McLaren":          10,
        "Red Bull Racing":   8,
        "Haas F1 Team":      6,
        "Racing Bulls":      4,
        "Audi":              2,
        "Alpine":            1,
        "Williams":          0,
        "Aston Martin":      0,
        "Cadillac":          0,
    }

    # Compute session pts scored by each team from the race/sprint sessions in fl
    _session_team_pts: dict = {}
    if has_race and "Race_Points" in fl.columns:
        _pts_raw = (
            fl[fl["session_name"].isin(race_sess)]
            .groupby(["session_name", "Driver_Short", "Team"])["Race_Points"]
            .first().reset_index()
        )
        _pts_raw["Race_Points"] = pd.to_numeric(_pts_raw["Race_Points"], errors="coerce").fillna(0)
        _by_team = _pts_raw.groupby("Team")["Race_Points"].sum()
        _session_team_pts = _by_team.to_dict()

    # Build before/after tables only for teams present in either dict
    _all_champ_teams = sorted(
        set(_CHAMP_CURRENT.keys()) | set(_session_team_pts.keys())
    )

    def _rank_by_pts(pts_dict):
        """Dense rank (1 = most pts). Ties get the same rank."""
        ordered = sorted(pts_dict.items(), key=lambda x: -x[1])
        rank, prev_pts, prev_rank = {}, None, 0
        for i, (t, p) in enumerate(ordered):
            if p != prev_pts:
                prev_rank = i + 1
            rank[t] = prev_rank
            prev_pts = p
        return rank

    _after_pts   = {t: _CHAMP_CURRENT.get(t, 0) for t in _all_champ_teams}
    _before_pts  = {t: max(0, _after_pts[t] - _session_team_pts.get(t, 0))
                    for t in _all_champ_teams}

    _rank_after  = _rank_by_pts(_after_pts)
    _rank_before = _rank_by_pts(_before_pts)

    _all_before_zero = all(v == 0 for v in _before_pts.values())

    def _arrow_el(delta):
        """Green ▲ / red ▼ / dash, with delta number."""
        if _all_before_zero:
            return html.Span("—", style={"color": TEXT_DIM, "fontSize": "0.75rem"})
        if delta > 0:
            return html.Span(
                f"▲{delta}", style={"color": "#00C04B", "fontWeight": "700",
                                    "fontSize": "0.78rem"}
            )
        elif delta < 0:
            return html.Span(
                f"▼{abs(delta)}", style={"color": "#FF4444", "fontWeight": "700",
                                         "fontSize": "0.78rem"}
            )
        return html.Span("=", style={"color": TEXT_DIM, "fontSize": "0.78rem"})

    # Rows sorted by current rank
    _champ_rows_sorted = sorted(
        _all_champ_teams,
        key=lambda t: (_rank_after.get(t, 99), -_after_pts.get(t, 0)),
    )

    champ_header = html.Div(
        [
            html.Span("POS", style={"width": "38px",  "display": "inline-block",
                                    "color": TEXT_DIM, "fontSize": "0.65rem",
                                    "fontWeight": "700", "letterSpacing": "1px"}),
            html.Span("Δ",   style={"width": "42px",  "display": "inline-block",
                                    "color": TEXT_DIM, "fontSize": "0.65rem",
                                    "fontWeight": "700", "letterSpacing": "1px",
                                    "textAlign": "center"}),
            html.Span("CONSTRUCTOR", style={"flex": "1",  "color": TEXT_DIM,
                                             "fontSize": "0.65rem", "fontWeight": "700",
                                             "letterSpacing": "1px"}),
            html.Span("THIS EVENT", style={"width": "80px", "textAlign": "right",
                                            "color": TEXT_DIM, "fontSize": "0.65rem",
                                            "fontWeight": "700", "letterSpacing": "1px"}),
            html.Span("TOTAL PTS",  style={"width": "80px", "textAlign": "right",
                                            "color": TEXT_DIM, "fontSize": "0.65rem",
                                            "fontWeight": "700", "letterSpacing": "1px"}),
        ],
        style={"display": "flex", "alignItems": "center",
               "padding": "4px 10px 6px 10px",
               "borderBottom": f"1px solid {GRID_CLR}",
               "marginBottom": "4px"},
    )

    champ_team_rows = []
    for t in _champ_rows_sorted:
        clr     = TEAM_COLORS.get(t, "#808080")
        rank_a  = _rank_after.get(t, 99)
        rank_b  = _rank_before.get(t, 99)
        delta   = rank_b - rank_a          # positive = moved UP in standings
        pts_now = int(_after_pts.get(t, 0))
        pts_evt = int(_session_team_pts.get(t, 0))
        evt_str = f"+{pts_evt}" if pts_evt > 0 else ("—" if pts_evt == 0 else str(pts_evt))

        # Bar fill representing share of leader's pts
        leader_pts = max(_after_pts.values()) or 1
        bar_pct = pts_now / leader_pts * 100

        row = html.Div(
            [
                html.Span(
                    f"P{rank_a}",
                    style={"width": "38px", "display": "inline-block",
                           "color": clr, "fontWeight": "800", "fontSize": "0.88rem"},
                ),
                html.Span(
                    _arrow_el(delta),
                    style={"width": "42px", "display": "inline-block",
                           "textAlign": "center"},
                ),
                html.Div(
                    [
                        html.Span("● ", style={"color": clr, "fontSize": "0.75rem"}),
                        html.Span(t, style={"color": TEXT_MAIN, "fontWeight": "600",
                                             "fontSize": "0.82rem"}),
                        # inline pts bar
                        html.Div(
                            html.Div(style={
                                "width": f"{bar_pct:.1f}%",
                                "height": "4px",
                                "background": clr,
                                "borderRadius": "2px",
                                "opacity": "0.6",
                            }),
                            style={"width": "100%", "height": "4px",
                                   "background": GRID_CLR, "borderRadius": "2px",
                                   "marginTop": "4px"},
                        ),
                    ],
                    style={"flex": "1", "paddingRight": "8px"},
                ),
                html.Span(
                    evt_str,
                    style={"width": "80px", "textAlign": "right",
                           "color": "#00C04B" if pts_evt > 0 else TEXT_DIM,
                           "fontWeight": "700" if pts_evt > 0 else "400",
                           "fontSize": "0.82rem"},
                ),
                html.Span(
                    f"{pts_now} pts",
                    style={"width": "80px", "textAlign": "right",
                           "color": TEXT_MAIN, "fontWeight": "700",
                           "fontSize": "0.88rem"},
                ),
            ],
            style={
                "display": "flex", "alignItems": "center",
                "padding": "6px 10px",
                "borderRadius": "6px",
                "marginBottom": "3px",
                "background": f"linear-gradient(90deg, {clr}14 0%, transparent 60%)",
                "border": f"1px solid {clr}28",
            },
        )
        champ_team_rows.append(row)

    _delta_note = (
        "↕ change during race/sprint sessions in current filter  ·  —  = first race / no race data"
        if _all_before_zero else
        "↕ constructor rank change  vs  standings before the race sessions in current filter"
    )

    champ_widget = card(
        html.Span([
            "Constructor Championship  ",
            html.Span("2026 season", style={"color": ACCENT, "fontWeight": "800"}),
            html.Span("  ·  current standings after this event",
                      style={"color": TEXT_DIM, "fontWeight": "400",
                             "fontSize": "0.72rem", "marginLeft": "6px"}),
        ]),
        html.Div([
            champ_header,
            html.Div(champ_team_rows),
            html.P(_delta_note,
                   style={"color": TEXT_DIM, "fontSize": "0.65rem",
                           "marginTop": "10px", "fontStyle": "italic"}),
        ]),
    )

    # ─────────────────────────────────────────────────────────

    # ═════════════════════════════════════════════════════════
    # COLUMN HEADER HELPER
    # ═════════════════════════════════════════════════════════
    def _col_header(emoji, title, subtitle):
        return html.Div([
            html.H5(
                f"{emoji}  {title}",
                style={"color": ACCENT, "fontWeight": "800", "letterSpacing": "2px",
                       "marginBottom": "2px", "fontSize": "0.92rem", "textAlign": "center"},
            ),
            html.P(subtitle, style={"color": TEXT_DIM, "fontSize": "0.70rem",
                                     "textAlign": "center", "marginBottom": "14px"}),
            html.Hr(style={"borderColor": GRID_CLR, "marginBottom": "12px"}),
        ])

    def _maybe_card(title, fig):
        """Only add the card if the figure has at least one trace."""
        if fig and fig.data:
            return [card(title, dcc.Graph(figure=fig, config=GFX))]
        return []

    # ═════════════════════════════════════════════════════════
    # LEFT COLUMN  – best of 2 drivers
    # ═════════════════════════════════════════════════════════
    left_cards = [_col_header(
        "BEST OF 2 DRIVERS",
        "each metric uses the strongest driver per team",
    )]

    # Race pace per compound (all sessions)
    if race_pace_best_by_cmp:
        left_cards += _maybe_card(
            "Race Pace – Best Stint per Compound (all sessions)",
            _compound_bars(race_pace_best_by_cmp, "Race Pace – Best Stint",
                           fmt_fn=format_lap_time, lower_is_better=True),
        )

    # Best lap overall
    left_cards += _maybe_card(
        "Best Lap Overall (all sessions)",
        _hbar(best_lap_best, "Best Lap Time", fmt_fn=format_lap_time,
              lower_is_better=True, xlabel="Lap Time (s)"),
    )

    # NB laps – total
    left_cards += _maybe_card(
        "Total Valid Laps",
        _hbar(laps_tot_best, "Total Valid Laps",
              fmt_fn=lambda v: str(int(v)), lower_is_better=False, xlabel="Laps"),
    )

    # NB laps – per session
    if laps_per_sess_best:
        _f = _session_laps_bar(laps_per_sess_best, "Valid Laps per Session")
        if _f and _f.data:
            left_cards.append(card("Laps per Session",
                                   dcc.Graph(figure=_f, config=GFX)))

    if has_race:
        left_cards += _maybe_card(
            "Pit Stop Duration",
            _hbar(pit_best, "Avg Pit Stop", fmt_fn=lambda v: f"{v:.2f}s",
                  lower_is_better=True, xlabel="Avg Pit Stop (s)"),
        )

    if has_quali:
        left_cards += _maybe_card(
            "Qualifying Performance",
            _hbar(quali_best, "Best Quali Lap", fmt_fn=format_lap_time,
                  lower_is_better=True, xlabel="Best Quali Lap (s)"),
        )

    if has_race:
        left_cards += _maybe_card(
            "Race Pace (race/sprint sessions only)",
            _hbar(race_pace_perf_best, "Race Pace", fmt_fn=format_lap_time,
                  lower_is_better=True, xlabel="Race Pace (s)"),
        )
        left_cards += _maybe_card(
            "Positions Gained / Lost (race/sprint)",
            _hbar(pgain_best, "Positions Gained",
                  fmt_fn=lambda v: f"+{int(v)}" if v > 0 else str(int(v)),
                  lower_is_better=False, xlabel="Pos Gained (+) / Lost (−)",
                  pct_gap=False),
        )

    # ═════════════════════════════════════════════════════════
    # RIGHT COLUMN  – average of 2 drivers
    # ═════════════════════════════════════════════════════════
    right_cards = [_col_header(
        "AVERAGE OF 2 DRIVERS",
        "NaN falls back to available driver — never forced to 0",
    )]

    if race_pace_avg_by_cmp:
        right_cards += _maybe_card(
            "Race Pace – Avg Best Stint per Compound",
            _compound_bars(race_pace_avg_by_cmp, "Race Pace – Avg Stint",
                           fmt_fn=format_lap_time, lower_is_better=True),
        )

    right_cards += _maybe_card(
        "Average Best Lap (all sessions)",
        _hbar(best_lap_avg, "Avg Best Lap", fmt_fn=format_lap_time,
              lower_is_better=True, xlabel="Avg Best Lap (s)"),
    )

    right_cards += _maybe_card(
        "Avg Valid Laps per Driver",
        _hbar(laps_tot_avg, "Avg Valid Laps",
              fmt_fn=lambda v: f"{v:.1f}", lower_is_better=False,
              xlabel="Avg Laps per Driver"),
    )

    if laps_per_sess_avg:
        _f = _session_laps_bar(laps_per_sess_avg, "Avg Laps per Session",
                               fmt_fn=lambda v: f"{v:.1f}")
        if _f and _f.data:
            right_cards.append(card("Avg Laps per Session",
                                    dcc.Graph(figure=_f, config=GFX)))

    if has_race:
        right_cards += _maybe_card(
            "Avg Pit Stop Duration",
            _hbar(pit_avg, "Avg Pit Stop", fmt_fn=lambda v: f"{v:.2f}s",
                  lower_is_better=True, xlabel="Avg Pit Stop (s)"),
        )

    if has_quali:
        right_cards += _maybe_card(
            "Avg Qualifying Performance",
            _hbar(quali_avg, "Avg Quali Lap", fmt_fn=format_lap_time,
                  lower_is_better=True, xlabel="Avg Quali Lap (s)"),
        )

    if has_race:
        right_cards += _maybe_card(
            "Avg Race Pace (race/sprint sessions only)",
            _hbar(race_pace_perf_avg, "Avg Race Pace", fmt_fn=format_lap_time,
                  lower_is_better=True, xlabel="Avg Race Pace (s)"),
        )
        right_cards += _maybe_card(
            "Avg Positions Gained / Lost (race/sprint)",
            _hbar(pgain_avg, "Avg Pos Gained",
                  fmt_fn=lambda v: f"+{v:.1f}" if v > 0 else f"{v:.1f}",
                  lower_is_better=False, xlabel="Avg Pos Gained (+) / Lost (−)",
                  pct_gap=False),
        )

    # ═════════════════════════════════════════════════════════
    # ASSEMBLE LAYOUT
    # ═════════════════════════════════════════════════════════
    return html.Div([
        champ_widget,
        html.Hr(style={"borderColor": GRID_CLR, "margin": "8px 0 16px 0"}),
        dbc.Row([
            dbc.Col(
                html.Div(left_cards),
                md=6,
                style={
                    "borderRight": f"2px solid {GRID_CLR}",
                    "paddingRight": "14px",
                },
            ),
            dbc.Col(
                html.Div(right_cards),
                md=6,
                style={"paddingLeft": "14px"},
            ),
        ], className="g-0"),
    ])

# ══════════════════════════════════════════════════════════════
# TAB 3 – LAP TIMES
# ══════════════════════════════════════════════════════════════
def tab_laps(fl):
    v = fl[fl["ValidLap"]].copy()

    fig_evo=go.Figure()
    for sess in sorted(v["session_name"].unique()):
        sv=v[v["session_name"]==sess]
        for drv in sv["Driver_Short"].dropna().unique():
            dv=sv[sv["Driver_Short"]==drv].sort_values("LapNo")
            clr=TEAM_COLORS.get(dv["Team"].iloc[0],"#808080")
            fig_evo.add_trace(go.Scatter(
                x=dv["LapNo"],y=dv["LapTime_s"],mode="lines+markers",
                name=f"{drv} ({sess.split('_')[0]})",
                line=dict(color=clr,width=1.5),
                marker=dict(size=5,color=[COMPOUND_COLORS.get(c,clr) for c in dv["Compound"].fillna("")],
                            line=dict(color=clr,width=1)),
                customdata=dv["Compound"].fillna("?"),
                hovertemplate=f"<b>{drv}</b> – {sess.split('_')[0]}<br>Lap %{{x}}<br>%{{y:.3f}} s<br>Compound: %{{customdata}}<extra></extra>"))
    theme(fig_evo,500,"Lap Time Evolution (marker colour = compound)")
    fig_evo.update_layout(xaxis_title="Lap Number",yaxis_title="Lap Time (s)")

    bt=best_laps_table(fl)
    bt["Best Lap"]=bt["LapTime_s"].apply(format_lap_time)
    disp=bt[["session_name","Driver_Short","Team","Compound","Best Lap","LapTime_s","PseudoTyreAge","LapNo"]].rename(columns={
        "session_name":"Session","Driver_Short":"Driver","LapTime_s":"Lap Time (s)","PseudoTyreAge":"Tyre Age","LapNo":"Lap #"
    }).sort_values("Lap Time (s)")
    tbl=styled_table(disp.to_dict("records"),[{"name":c,"id":c} for c in disp.columns])

    qs=pd.DataFrame()
    if "Is_Quali_Sim" in fl.columns:
        qs=fl[(fl["Is_Quali_Sim"]==True)&fl["ValidLap"]][
            ["session_name","Driver_Short","Team","LapNo","LapTime_s","Stint","PseudoTyreAge","Compound"]].copy()
        qs["Lap Time"]=qs["LapTime_s"].apply(format_lap_time)
        qs=qs.sort_values("LapTime_s").rename(columns={
            "session_name":"Session","Driver_Short":"Driver","LapNo":"Lap #",
            "LapTime_s":"Lap Time (s)","PseudoTyreAge":"Tyre Age"})
    qs_tbl=styled_table(qs.to_dict("records") if not qs.empty else [],
                        [{"name":c,"id":c} for c in qs.columns] if not qs.empty else [])

    return html.Div([
        card("Lap Time Evolution",dcc.Graph(figure=fig_evo,config=GFX)),
        card("Best Lap Leaderboard",tbl),
        card("Quali Simulation Laps (≤0.5% of personal best, tyre age ≤4)",qs_tbl),
    ])

# ══════════════════════════════════════════════════════════════
# TAB 4 – STINTS
# ══════════════════════════════════════════════════════════════

# Track flag visual config: (fill_rgba, line_hex)
_FLAG_STYLE = {
    "Yellow":       ("rgba(255,215,  0,0.10)", "#B8860B"),
    "DoubleYellow": ("rgba(255,140,  0,0.15)", "#CC6600"),
    "SafetyCar":    ("rgba(  0,220, 80,0.12)", "#007700"),
    "VSC":          ("rgba(  0,150,255,0.10)", "#0055BB"),
    "VSCEnding":    ("rgba(  0,150,255,0.07)", "#0055BB"),
    "RedFlag":      ("rgba(225,  6,  0,0.18)", "#AA0000"),
}


def _add_flag_bands(fig, df_sess):
    if "TrackStatus_Flag" not in df_sess.columns:
        return
    flag_laps = (
        df_sess[df_sess["TrackStatus_Flag"].isin(_FLAG_STYLE)]
        .sort_values("LapNo")[["LapNo", "TrackStatus_Flag"]]
        .drop_duplicates()
    )
    if flag_laps.empty:
        return
    groups = []
    for _, row in flag_laps.iterrows():
        lap, flag = int(row["LapNo"]), row["TrackStatus_Flag"]
        if groups and groups[-1]["flag"] == flag and lap == groups[-1]["end"] + 1:
            groups[-1]["end"] = lap
        else:
            groups.append({"flag": flag, "start": lap, "end": lap})
    seen = set()
    for grp in groups:
        flag = grp["flag"]
        fill, line_clr = _FLAG_STYLE[flag]
        show = flag not in seen
        seen.add(flag)
        fig.add_vrect(
            x0=grp["start"] - 0.5, x1=grp["end"] + 0.5,
            fillcolor=fill,
            line=dict(color=line_clr, width=1, dash="dot"),
            layer="below",
            annotation_text=flag if show else "",
            annotation_position="top left",
            annotation_font=dict(size=9, color=line_clr),
        )


def _best_stint_laps(fl, stints_df):
    """Return laps that belong to the best valid stint per driver x compound
    (session-agnostic: Stint_Rank_Across_Sessions == 1).
    Falls back to all valid laps if stints_df is empty or ranking unavailable.

    Note: analyze_stints() does not carry Stint_key, so we match on the
    three component columns (session_name, Driver_Short, Stint) instead.
    """
    if stints_df is None or stints_df.empty or "Stint_Rank_Across_Sessions" not in stints_df.columns:
        return fl[fl["ValidLap"]].copy()

    best = stints_df[
        stints_df["Valid_Stint"] & (stints_df["Stint_Rank_Across_Sessions"] == 1)
    ][["session_name", "Driver_Short", "Stint"]].drop_duplicates()

    # Build a merge key on the laps side then filter
    fl_valid = fl[fl["ValidLap"]].copy()
    merged = fl_valid.merge(
        best.assign(_keep=True),
        on=["session_name", "Driver_Short", "Stint"],
        how="left",
    )
    return merged[merged["_keep"] == True].drop(columns=["_keep"]).copy()


def tab_stints(fl, fs):
    # 1. Lap Time Evolution layout (dynamic via callback)
    avail_sessions = sorted(fl["session_name"].unique())
    default_sess   = avail_sessions[0] if avail_sessions else None

    flag_pills = [
        html.Span("Track flags: ",
                  style={"color": TEXT_DIM, "fontSize": "0.72rem"}),
    ]
    for label, bg in [
        ("Yellow", "#B8860B"), ("Dbl Yellow", "#CC6600"),
        ("Safety Car", "#007700"), ("VSC", "#0055BB"), ("Red Flag", "#AA0000"),
    ]:
        flag_pills.append(html.Span(label, style={
            "background": bg, "color": "#fff", "borderRadius": "3px",
            "padding": "2px 7px", "fontSize": "0.68rem", "fontWeight": "700",
            "marginRight": "5px",
        }))

    evo_layout = html.Div([
        html.Div(
            dcc.RadioItems(
                id="stints-evo-session",
                options=[{"label": s, "value": s} for s in avail_sessions],
                value=default_sess,
                inline=True,
                inputStyle={"marginRight": "6px", "accentColor": ACCENT},
                labelStyle={
                    "marginRight": "18px", "fontSize": "0.78rem",
                    "color": TEXT_MAIN, "cursor": "pointer",
                },
            ),
            style={"marginBottom": "10px"},
        ),
        html.Div(flag_pills, style={"marginBottom": "8px"}),
        dcc.Graph(id="stints-evo-graph", config=GFX),
    ])

    # 2. Violin per compound – laps from best stint only (session-agnostic)
    best_laps = _best_stint_laps(fl, fs)
    v_note = html.P(
        "ℹ️  Each violin uses only laps from the single best valid stint "
        "per driver × compound across all selected sessions "
        "(Stint_Rank_Across_Sessions = 1).",
        style={"color": TEXT_DIM, "fontSize": "0.75rem", "marginBottom": "6px",
               "fontStyle": "italic"},
    )
    team_order = (
        best_laps.groupby("Team")["LapTime_s"].min().sort_values().index.tolist()
        if not best_laps.empty else []
    )

    violin_cards = []
    for compound in COMPOUNDS:
        df_comp = best_laps[best_laps["Compound"] == compound]
        if df_comp.empty:
            continue
        fig_v = go.Figure()
        anns  = []
        for team in team_order:
            df_team = df_comp[df_comp["Team"] == team]
            if df_team.empty:
                continue
            drivers = sorted(df_team["Driver_Short"].dropna().unique())
            clr  = TEAM_COLORS.get(team, "#808080")
            rgba = "rgba({},{},{},0.27)".format(
                int(clr[1:3], 16), int(clr[3:5], 16), int(clr[5:7], 16)
            )
            for i, driver in enumerate(drivers[:2]):
                df_drv = df_team[df_team["Driver_Short"] == driver]
                if df_drv.empty:
                    continue
                lap_count = len(df_drv)
                ymax      = df_drv["LapTime_s"].max()
                ymin      = df_drv["LapTime_s"].min()
                margin    = (ymax - ymin) * 0.2 if ymax != ymin else 0.5
                side      = "negative" if i == 0 else "positive"
                pointpos  = -0.8      if i == 0 else 0.8
                fig_v.add_trace(go.Violin(
                    x=[team] * lap_count,
                    y=df_drv["LapTime_s"],
                    legendgroup=driver,
                    scalegroup=team,
                    name=driver,
                    side=side,
                    pointpos=pointpos,
                    line_color=clr,
                    fillcolor=rgba,
                    meanline_visible=True,
                    points="all",
                    jitter=0.05,
                    scalemode="count",
                    showlegend=True,
                ))
                anns.append(dict(
                    x=team, y=ymax + margin / 2,
                    text=f"{driver} ({lap_count})",
                    showarrow=False,
                    xshift=-25 if side == "negative" else 25,
                    yshift=10,
                    font=dict(size=11, color=clr),
                ))
        theme(fig_v, 650,
              f"Lap Time Distribution – {compound} (best stint per driver, all sessions)")
        fig_v.update_layout(
            violingap=0, violingroupgap=0, violinmode="overlay",
            xaxis=dict(categoryorder="array", categoryarray=team_order,
                       gridcolor=GRID_CLR, zeroline=False),
            yaxis_title="Lap Time (s)",
            annotations=anns,
        )
        violin_cards.append(card(
            f"Distribution – {compound}",
            html.Div([v_note, dcc.Graph(figure=fig_v, config=GFX)]),
        ))

    # 3. Tyre Degradation – per compound:
    #    (a) Ranked horizontal bar: Stint_Deg_Rate from the stint with best R²
    #        (most statistically reliable regression, not necessarily fastest stint)
    #        Source: analyze_stints() which uses LapTime_FuelCorrected and ValidLap.
    #        Additional filter: exclude Perturbed_Lap laps fed into the viz.
    #    (b) Normalised evolution: LapTime_FuelCorrected delta from lap-1 baseline,
    #        using the LONGEST valid non-perturbed stint per driver x compound
    #        (more laps = better shape; fuel-corrected so car weight doesn’t mask deg).
    deg_cards = []
    valid_stints = fs[fs["Valid_Stint"]].copy() if not fs.empty else pd.DataFrame()

    # Build a clean laps pool: ValidLap AND not Perturbed_Lap (if column exists)
    _perturb_mask = fl["Perturbed_Lap"] if "Perturbed_Lap" in fl.columns else pd.Series(False, index=fl.index)
    clean_laps = fl[fl["ValidLap"] & ~_perturb_mask].copy()

    for compound in COMPOUNDS:
        comp_stints = (
            valid_stints[valid_stints["Compound"] == compound].copy()
            if not valid_stints.empty else pd.DataFrame()
        )

        # --- (a) Deg rate bar: best-R² stint per driver ---
        fig_bar = None
        df_deg  = pd.DataFrame()
        if not comp_stints.empty and "Stint_Deg_Rate" in comp_stints.columns:
            has_r2 = comp_stints["Stint_Deg_R2"].notna()
            # Pick the stint with the highest R² for each driver; fall back to
            # highest lap count when R² is unavailable for all stints of that driver.
            best_r2 = (
                comp_stints[has_r2]
                .sort_values("Stint_Deg_R2", ascending=False)
                .groupby("Driver_Short", sort=False)
                .first()
                .reset_index()
            )
            # Drivers whose stints all have NaN R² → fall back to longest stint
            drivers_with_r2 = set(best_r2["Driver_Short"])
            fallback = (
                comp_stints[~comp_stints["Driver_Short"].isin(drivers_with_r2)]
                .sort_values("Stint_Laps_Count", ascending=False)
                .groupby("Driver_Short", sort=False)
                .first()
                .reset_index()
            )
            df_deg = pd.concat([best_r2, fallback], ignore_index=True)
            df_deg = df_deg[df_deg["Stint_Deg_Rate"].notna()].copy()

        if not df_deg.empty:
            df_deg = df_deg.sort_values("Stint_Deg_Rate", ascending=False)
            df_deg["Color"]   = df_deg["Team"].map(TEAM_COLORS).fillna("#808080")
            df_deg["DegFmt"]  = df_deg["Stint_Deg_Rate"].apply(
                lambda x: f"+{x:.4f}" if x >= 0 else f"{x:.4f}"
            )
            df_deg["R2Fmt"]   = df_deg["Stint_Deg_R2"].apply(
                lambda x: f"R²={x:.2f}" if pd.notna(x) else "R²=n/a"
            )
            df_deg["R2Color"] = df_deg["Stint_Deg_R2"].apply(
                lambda x: ("#00D2BE" if x >= 0.50 else ("#FF8700" if x >= 0.20 else "#E10600"))
                if pd.notna(x) else "#808080"
            )
            max_abs = df_deg["Stint_Deg_Rate"].abs().max() * 1.4 or 0.05

            fig_bar = go.Figure(go.Bar(
                y=df_deg["Driver_Short"],
                x=df_deg["Stint_Deg_Rate"],
                orientation="h",
                marker=dict(
                    color=df_deg["Color"],
                    line=dict(color=GRID_CLR, width=0.5),
                ),
                customdata=df_deg[["Team", "DegFmt", "R2Fmt", "R2Color",
                                   "Stint_Laps_Count", "session_name"]].values,
                hovertemplate=(
                    "<b>%{y}</b>  Team: %{customdata[0]}<br>"
                    "Deg rate: %{customdata[1]} s/lap<br>"
                    "<span style='color:%{customdata[3]}'>%{customdata[2]}</span><br>"
                    "Laps in stint: %{customdata[4]}<br>"
                    "Session: %{customdata[5]}<extra></extra>"
                ),
                text=df_deg["DegFmt"],
                textposition="outside",
                textfont=dict(size=10, color=TEXT_MAIN),
            ))
            fig_bar.add_vline(x=0, line=dict(color="white", width=1, dash="dash"))
            fig_bar.add_vrect(x0=-max_abs, x1=0,
                fillcolor="rgba(0,200,100,0.05)", line_width=0, layer="below")
            fig_bar.add_vrect(x0=0, x1=max_abs,
                fillcolor="rgba(225,6,0,0.05)", line_width=0, layer="below")
            ht = max(300, 28 * len(df_deg) + 80)
            theme(fig_bar, ht,
                  f"{compound} – Degradation Rate (best-R² stint, fuel-corrected)")
            fig_bar.update_layout(
                xaxis=dict(
                    title="s/lap  ← better tyre management",
                    range=[-max_abs, max_abs],
                    gridcolor=GRID_CLR, zeroline=False,
                ),
                yaxis=dict(gridcolor=GRID_CLR, zeroline=False, autorange="reversed"),
                bargap=0.25, showlegend=False,
                annotations=[dict(
                    text="🟢 R²≥0.50 good  🟠 0.20–0.50  🔴 <0.20 / n/a",
                    xref="paper", yref="paper", x=1, y=1.02,
                    xanchor="right", showarrow=False,
                    font=dict(size=9, color=TEXT_DIM),
                )],
            )

        # --- (b) Normalised evolution: longest clean stint per driver ---
        # Group clean laps by (driver, stint) and pick the stint with most laps
        comp_clean = clean_laps[clean_laps["Compound"] == compound].copy()

        fig_norm = go.Figure()
        if not comp_clean.empty:
            stint_lens = (
                comp_clean.groupby(["Driver_Short", "session_name", "Stint"])
                .size()
                .reset_index(name="_n_laps")
                .sort_values("_n_laps", ascending=False)
            )
            # Best stint = longest; one per driver
            best_per_drv = (
                stint_lens.groupby("Driver_Short", sort=False)
                .first()
                .reset_index()
            )
            for _, brow in best_per_drv.iterrows():
                drv  = brow["Driver_Short"]
                sess = brow["session_name"]
                snt  = brow["Stint"]
                n    = int(brow["_n_laps"])
                if n < 2:
                    continue
                df_drv = (
                    comp_clean[
                        (comp_clean["Driver_Short"] == drv)
                        & (comp_clean["session_name"] == sess)
                        & (comp_clean["Stint"] == snt)
                    ]
                    .sort_values("LapInStint")
                )
                baseline = df_drv.iloc[0]["LapTime_FuelCorrected"]
                if pd.isna(baseline) or baseline <= 0:
                    continue
                clr   = TEAM_COLORS.get(df_drv["Team"].iloc[0], "#808080")
                delta = df_drv["LapTime_FuelCorrected"] - baseline
                sess_label = sess.split("_")[0]
                fig_norm.add_trace(go.Scatter(
                    x=df_drv["LapInStint"],
                    y=delta,
                    mode="lines+markers",
                    name=f"{drv} ({n} laps, {sess_label})",
                    line=dict(color=clr, width=2),
                    marker=dict(size=6, color=clr),
                    hovertemplate=(
                        f"<b>{drv}</b><br>"
                        "Lap in stint: %{x}<br>"
                        "Δ fuel-corrected from lap 1: %{y:+.3f} s"
                        "<extra></extra>"
                    ),
                ))
            if fig_norm.data:
                fig_norm.add_hline(y=0, line=dict(color="white", width=1, dash="dash"))
                fig_norm.add_hrect(y0=0, y1=999,
                    fillcolor="rgba(225,6,0,0.03)", line_width=0, layer="below")
                fig_norm.add_hrect(y0=-999, y1=0,
                    fillcolor="rgba(0,200,100,0.03)", line_width=0, layer="below")

        theme(fig_norm, 460,
              f"{compound} – Normalised Deg (Δ fuel-corrected vs lap 1, longest clean stint)")
        fig_norm.update_layout(
            xaxis_title="Lap in Stint",
            yaxis_title="Δ Fuel-corrected lap time (s)  ↓ better",
            legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1),
            annotations=[dict(
                text="Perturbed laps (yellow / SC / VSC / red) excluded",
                xref="paper", yref="paper", x=1, y=1.02,
                xanchor="right", showarrow=False,
                font=dict(size=9, color=TEXT_DIM),
            )],
        )

        if fig_bar is not None:
            deg_cards.append(card(
                f"Tyre Degradation – {compound}",
                dbc.Row([
                    dbc.Col(dcc.Graph(figure=fig_bar,  config=GFX), md=5),
                    dbc.Col(dcc.Graph(figure=fig_norm, config=GFX), md=7),
                ]),
            ))
        else:
            deg_cards.append(card(
                f"Tyre Degradation – {compound}",
                dcc.Graph(figure=fig_norm, config=GFX),
            ))

    # 4. Stint Lap Inspector
    avail_drivers = sorted(fl["Driver_Short"].dropna().unique())
    first_driver  = avail_drivers[0] if avail_drivers else None

    stint_inspector = html.Div([
        html.P(
            "Select a driver then a pre-ranked stint to inspect its laps.",
            style={"color": TEXT_DIM, "fontSize": "0.8rem", "marginBottom": "10px"},
        ),
        dbc.Row([
            dbc.Col([
                html.Label("Driver",
                           style={"color": TEXT_DIM, "fontSize": "0.75rem",
                                  "letterSpacing": "1px"}),
                dcc.Dropdown(
                    id="stint-insp-driver",
                    options=[{"label": d, "value": d} for d in avail_drivers],
                    value=first_driver,
                    clearable=False,
                    style={"backgroundColor": "#111", "fontSize": "0.82rem"},
                ),
            ], md=3),
            dbc.Col([
                html.Label("Stint (ranked)",
                           style={"color": TEXT_DIM, "fontSize": "0.75rem",
                                  "letterSpacing": "1px"}),
                dcc.Dropdown(
                    id="stint-insp-key",
                    options=[],
                    value=None,
                    clearable=False,
                    style={"backgroundColor": "#111", "fontSize": "0.82rem"},
                ),
            ], md=9),
        ], className="mb-3"),
        html.Div(id="stint-insp-table"),
    ])

    return html.Div([
        card("Lap Time Evolution – All Laps", evo_layout),
        *violin_cards,
        *deg_cards,
        card("Stint Lap Inspector", stint_inspector),
    ])

# TAB 5 – TELEMETRY
# ══════════════════════════════════════════════════════════════
def tab_telemetry(fl, ft):
    if ft.empty:
        return card("Telemetry",html.P("No telemetry data.",style={"color":TEXT_DIM}))

    # Max speed bar
    fig_spd=go.Figure()
    if "Speed" in ft.columns:
        sp=(ft.groupby(["Driver_Short","Team"])["Speed"]
              .quantile(SPEED_PERCENTILE/100.0).reset_index())
        sp.columns=["Driver_Short","Team","MaxSpeed"]
        sp=sp.sort_values("MaxSpeed",ascending=False)
        for _,row in sp.iterrows():
            fig_spd.add_trace(go.Bar(x=[row["Driver_Short"]],y=[row["MaxSpeed"]],
                name=row["Driver_Short"],showlegend=False,
                marker_color=TEAM_COLORS.get(row["Team"],"#808080"),
                hovertemplate=f"<b>{row['Driver_Short']}</b><br>{SPEED_PERCENTILE}th pct: %{{y:.1f}} km/h<extra></extra>"))
        lo=sp["MaxSpeed"].min(); hi=sp["MaxSpeed"].max(); m=(hi-lo)*0.3
        theme(fig_spd,380,f"Maximum Speed by Driver ({SPEED_PERCENTILE}th percentile)")
        fig_spd.update_layout(xaxis_title="Driver",yaxis_title="Max Speed (km/h)",xaxis=dict(tickangle=0,gridcolor=GRID_CLR,zeroline=False))
        fig_spd.update_yaxes(range=[lo-m,hi+m/4])

    # Gear usage stacked bar
    fig_gear=go.Figure()
    if "GearNo" in ft.columns:
        gp=(ft.groupby(["Driver_Short","Team","GearNo"]).size().reset_index(name="cnt"))
        gp["total"]=gp.groupby("Driver_Short")["cnt"].transform("sum")
        gp["pct"]=gp["cnt"]/gp["total"]*100
        drv_ord=(ft.groupby("Driver_Short")["Driver_Short"].first().index.tolist())
        for gear in sorted(gp["GearNo"].dropna().unique()):
            sub=gp[gp["GearNo"]==gear].set_index("Driver_Short")
            fig_gear.add_trace(go.Bar(
                x=drv_ord,
                y=[sub.loc[d,"pct"] if d in sub.index else 0 for d in drv_ord],
                name=f"Gear {int(gear)}",
                marker_color=[TEAM_COLORS.get(
                    ft[ft["Driver_Short"]==d]["Team"].iloc[0] if len(ft[ft["Driver_Short"]==d]) else "x",
                    "#808080") for d in drv_ord],
                hovertemplate="Driver: %{x}<br>Gear "+str(int(gear))+": %{y:.1f}%<extra></extra>"))
        theme(fig_gear,420,"Gear Usage Distribution by Driver")
        fig_gear.update_layout(barmode="stack",xaxis_title="Driver",yaxis_title="Time in Gear (%)")

    # Channel overlay
    channels=[c for c in ["Speed","Throttle","Brake","GearNo"] if c in ft.columns]
    fig_ch=make_subplots(rows=len(channels),cols=1,shared_xaxes=True,
                          vertical_spacing=0.04,subplot_titles=channels)
    for r,ch in enumerate(channels,start=1):
        for drv in ft["Driver_Short"].dropna().unique():
            sub=ft[ft["Driver_Short"]==drv].sort_values("timestamp")
            if sub.empty: continue
            clr=TEAM_COLORS.get(sub["Team"].iloc[0] if "Team" in sub.columns else "x","#808080")
            fig_ch.add_trace(go.Scatter(x=sub["timestamp"],y=sub[ch],mode="lines",name=drv,
                line=dict(color=clr,width=0.8),showlegend=(r==1),
                hovertemplate=f"<b>{drv}</b><br>{ch}: %{{y}}<extra></extra>"),row=r,col=1)
        fig_ch.update_yaxes(title_text=ch,gridcolor=GRID_CLR,zeroline=False,row=r,col=1)
    fig_ch.update_layout(height=max(140*len(channels)+60,300),
        paper_bgcolor=CARD_BG,plot_bgcolor=CARD_BG,
        font=dict(color=TEXT_MAIN,family="Inter, sans-serif",size=11),
        legend=dict(bgcolor="rgba(0,0,0,0)"),margin=dict(l=60,r=20,t=60,b=40))
    fig_ch.update_xaxes(gridcolor=GRID_CLR,zeroline=False)

    return html.Div([
        dbc.Row([dbc.Col(card("Maximum Speed",dcc.Graph(figure=fig_spd,config=GFX)),md=6),
                 dbc.Col(card("Gear Usage",   dcc.Graph(figure=fig_gear,config=GFX)),md=6)]),
        card("Telemetry Channels (Speed / Throttle / Brake / Gear)",dcc.Graph(figure=fig_ch,config=GFX)),
    ])

# ══════════════════════════════════════════════════════════════
# TAB 6 – HEATMAPS
# ══════════════════════════════════════════════════════════════
def tab_heatmaps(fl, ft):
    out=[]
    v=fl[fl["ValidLap"]].copy()

    # Driver x Session pace heatmap
    pivot=(v.groupby(["Driver_Short","session_name"])["LapTime_s"].median().unstack(fill_value=np.nan))
    if not pivot.empty:
        norm=pivot.copy()
        for col in norm.columns:
            lo,hi=norm[col].min(),norm[col].max()
            norm[col]=(norm[col]-lo)/(hi-lo) if hi>lo else 0.5
        ss=[s.split("_")[0] for s in pivot.columns]
        avg=pivot.mean(axis=0); dvs=list(pivot.index)
        fp=make_subplots(rows=2,cols=1,row_heights=[0.08,0.92],vertical_spacing=0.02,shared_xaxes=True)
        fp.add_trace(go.Heatmap(z=[avg.values],x=ss,y=["Avg"],colorscale="RdYlGn_r",showscale=False,
            text=[avg.round(3).values],texttemplate="%{text}",textfont={"size":10},
            hovertemplate="Session: %{x}<br>Avg: %{z:.3f} s<extra></extra>"),row=1,col=1)
        fp.add_trace(go.Heatmap(z=norm.values,x=ss,y=dvs,colorscale="RdYlGn_r",showscale=True,
            text=pivot.round(3).values,texttemplate="%{text}",textfont={"size":9},
            customdata=pivot.values,
            hovertemplate="Driver: %{y}<br>Session: %{x}<br>Median: %{customdata:.3f} s<extra></extra>",
            colorbar=dict(title=dict(text="Norm", font=dict(color=TEXT_MAIN)),tickfont=dict(color=TEXT_MAIN))),row=2,col=1)
        fp.update_layout(title="Pace Heatmap: Driver × Session (column-normalized, red=slower)",
            height=max(300,80+26*len(dvs)),paper_bgcolor=CARD_BG,plot_bgcolor=CARD_BG,
            font=dict(color=TEXT_MAIN,family="Inter, sans-serif",size=11),
            margin=dict(l=80,r=100,t=60,b=40))
        out.append(card("Driver × Session Pace Heatmap",dcc.Graph(figure=fp,config=GFX)))

    # Cornering speed heatmap (Driver x TrackRegion)
    if (not ft.empty and "TrackRegion" in ft.columns and
            "Speed" in ft.columns and "Driver_Short" in ft.columns):
        tv=ft[ft["TrackRegion"].notna()&ft["Speed"].notna()].copy()
        if not tv.empty:
            cp=(tv.groupby(["Driver_Short","TrackRegion"])["Speed"]
                  .mean().unstack(fill_value=np.nan))
            cp=cp.sort_index().reindex(sorted(cp.columns),axis=1)
            cn=cp.copy()
            for col in cn.columns:
                lo,hi=cn[col].min(),cn[col].max()
                cn[col]=(cn[col]-lo)/(hi-lo) if hi>lo else 0.5
            ravg=cp.mean(axis=0); dc=list(cp.index); rg=list(cp.columns)
            fc=make_subplots(rows=2,cols=1,row_heights=[0.1,0.9],vertical_spacing=0.03,shared_xaxes=True)
            fc.add_trace(go.Heatmap(z=[ravg.values],x=rg,y=["Avg"],colorscale="RdYlGn",showscale=False,
                text=[np.round(ravg.values,1)],texttemplate="%{text}",textfont={"size":10},
                hovertemplate="Region: %{x}<br>Avg Speed: %{z:.1f} km/h<extra></extra>"),row=1,col=1)
            fc.add_trace(go.Heatmap(z=cn.values,x=rg,y=dc,colorscale="RdYlGn",showscale=False,
                text=np.round(cp.values,1),texttemplate="%{text}",textfont={"size":9},
                customdata=cp.values,
                hovertemplate="Driver: %{y}<br>Region: %{x}<br>Avg Speed: %{customdata:.1f} km/h<extra></extra>"),row=2,col=1)
            fc.update_layout(
                title="Cornering Speed by Track Region<br><sup>Columns normalized for comparison</sup>",
                height=max(900,30*len(dc)+200),paper_bgcolor=CARD_BG,plot_bgcolor=CARD_BG,
                font=dict(color=TEXT_MAIN,family="Inter, sans-serif",size=11),
                margin=dict(l=80,r=40,t=70,b=50))
            fc.update_yaxes(title_text="Driver",row=2,col=1,gridcolor=GRID_CLR,zeroline=False)
            fc.update_xaxes(title_text="Track Region",row=2,col=1,gridcolor=GRID_CLR,zeroline=False)
            out.append(card("Cornering Speed by Track Region",dcc.Graph(figure=fc,config=GFX)))

    return html.Div(out) if out else html.P("Not enough data.",style={"color":TEXT_DIM})


# ══════════════════════════════════════════════════════════════
# TAB 7 – TEAMMATE COMPARISON
# ══════════════════════════════════════════════════════════════

def tab_teammates(fl, fs):
    """
    Head-to-head teammate comparison across multiple performance dimensions.
    Wrapped in a top-level try/except so any crash shows in the UI rather
    than killing the Dash server callback.
    """
    try:
        return _tab_teammates_inner(fl, fs)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        return html.Div([
            dbc.Alert(
                [html.B("Teammate tab error: "), str(exc)],
                color="danger", style={"fontSize": "0.82rem"},
            ),
            html.Pre(tb, style={
                "color": TEXT_DIM, "fontSize": "0.7rem",
                "background": "#09091A", "padding": "12px",
                "borderRadius": "6px", "overflowX": "auto",
            }),
        ])


def _hex_to_rgba(hex_color: str, alpha: float = 1.0) -> str:
    """Convert a '#RRGGBB' hex string to 'rgba(r,g,b,a)' for Plotly."""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    else:
        r, g, b = 128, 128, 128
    return f"rgba({r},{g},{b},{alpha})"


def _tab_teammates_inner(fl, fs):

    # ── 0. Pools & session-type detection ────────────────────
    sess_names = fl["session_name"].unique().tolist()
    race_sess  = [s for s in sess_names
                  if (s.startswith("Race") or s.startswith("Sprint"))
                  and "Qualifying" not in s]
    quali_sess = [s for s in sess_names if "Qualifying" in s]
    has_race   = bool(race_sess)
    has_quali  = bool(quali_sess)

    v         = fl[fl["ValidLap"]].copy()
    _pert     = (fl["Perturbed_Lap"] if "Perturbed_Lap" in fl.columns
                 else pd.Series(False, index=fl.index))
    v_clean   = fl[fl["ValidLap"] & ~_pert].copy()
    v_race    = v_clean[v_clean["session_name"].isin(race_sess)] if has_race  else pd.DataFrame()
    v_quali   = v[v["session_name"].isin(quali_sess)]            if has_quali else pd.DataFrame()

    # ── 1. Build teammate pairs (alphabetical within team) ───
    pairs: dict[str, list[str]] = {}
    for team, grp in v.groupby("Team"):
        if team in ("Unknown", ""):
            continue
        drvs = sorted(grp["Driver_Short"].dropna().unique().tolist())
        if len(drvs) >= 2:
            pairs[team] = drvs[:2]

    if not pairs:
        return html.P(
            "No complete teammate pairs in current filter — widen driver / team selection.",
            style={"color": TEXT_DIM},
        )
    teams_sorted = sorted(pairs.keys())

    # ── 2. Generic metric helpers ─────────────────────────────

    def _val(pool: pd.DataFrame, driver: str, agg_fn) -> float:
        sub = pool[pool["Driver_Short"] == driver]
        if sub.empty:
            return float("nan")
        try:
            return float(agg_fn(sub))
        except Exception:
            return float("nan")

    def _metric_rows(pool: pd.DataFrame, agg_fn) -> list[dict]:
        rows = []
        for team in teams_sorted:
            if team not in pairs:
                continue
            drv_a, drv_b = pairs[team]
            va, vb = _val(pool, drv_a, agg_fn), _val(pool, drv_b, agg_fn)
            if not (np.isnan(va) and np.isnan(vb)):
                rows.append(dict(team=team, drv_a=drv_a, drv_b=drv_b,
                                 val_a=va, val_b=vb))
        return rows

    # ── 3. Chart builders ─────────────────────────────────────

    def _gap_chart(rows: list[dict], title: str, xlabel: str,
                   fmt_fn=None, lower_is_better: bool = True,
                   note: str = "", unit: str = "") -> go.Figure:
        """
        One horizontal bar per team, coloured by TEAM_COLORS.
        Bar extends LEFT when Driver A wins, RIGHT when Driver B wins.
        Text inside the bar: ★ DrvA  val_a | val_b  DrvB ★
        """
        rows = [r for r in rows
                if not (np.isnan(r["val_a"]) and np.isnan(r["val_b"]))]
        if not rows:
            return go.Figure()

        fmt_fn = fmt_fn or (lambda v: f"{v:.3f}")

        raw_gaps = [
            (r["val_a"] - r["val_b"])
            if not (np.isnan(r["val_a"]) or np.isnan(r["val_b"])) else 0.0
            for r in rows
        ]
        disp_gaps = [g if lower_is_better else -g for g in raw_gaps]
        # Team color for bar fill; winner side indicated by direction
        bar_colors = [TEAM_COLORS.get(r["team"], "#808080") for r in rows]

        bar_texts, hover_data = [], []
        for r, dg in zip(rows, disp_gaps):
            va_s = fmt_fn(r["val_a"]) if not np.isnan(r["val_a"]) else "—"
            vb_s = fmt_fn(r["val_b"]) if not np.isnan(r["val_b"]) else "—"
            gap_s = (
                f"{abs(r['val_a'] - r['val_b']):.3f} {unit}"
                if not (np.isnan(r["val_a"]) or np.isnan(r["val_b"])) else "—"
            )
            w_a = "★ " if dg <= 0 else ""
            w_b = " ★" if dg >  0 else ""
            bar_texts.append(f"{w_a}{r['drv_a']}  {va_s}  |  {vb_s}  {r['drv_b']}{w_b}")
            hover_data.append([r["drv_a"], va_s, r["drv_b"], vb_s, gap_s])

        fig = go.Figure(go.Bar(
            y=[r["team"] for r in rows],
            x=disp_gaps,
            orientation="h",
            marker=dict(color=bar_colors, line=dict(color=GRID_CLR, width=0.8)),
            text=bar_texts,
            textposition="auto",
            textfont=dict(size=10, color="#fff"),
            customdata=hover_data,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "%{customdata[0]}: <b>%{customdata[1]}</b><br>"
                "%{customdata[2]}: <b>%{customdata[3]}</b><br>"
                "Gap: %{customdata[4]}"
                "<extra></extra>"
            ),
        ))
        fig.add_vline(x=0, line=dict(color=TEXT_MAIN, width=1.5))
        theme(fig, max(220, len(rows) * 58 + 130), title)
        fig.update_layout(
            xaxis_title=xlabel,
            bargap=0.35,
            showlegend=False,
            margin=dict(l=160, r=20, t=70, b=55),
        )
        fig.add_annotation(
            text=(
                "◀ left driver faster / better  ·  right driver faster / better ▶"
            ),
            xref="paper", yref="paper", x=0.5, y=1.07,
            xanchor="center", showarrow=False,
            font=dict(size=9, color=TEXT_DIM),
        )
        if note:
            fig.add_annotation(
                text=note, xref="paper", yref="paper",
                x=1.0, y=-0.16, xanchor="right", showarrow=False,
                font=dict(size=9, color=TEXT_DIM),
            )
        return fig

    # Butterfly removed — all charts now use the same diverging gap style.
    # For "higher is better" metrics (laps, overtakes) lower_is_better=False
    # so the bar extends LEFT when Driver A has the higher value.

    # ── 4. Win counter ────────────────────────────────────────

    def _wins(va, vb, lower_is_better=True):
        if np.isnan(va) or np.isnan(vb):
            return 0, 0
        return (1, 0) if (va < vb if lower_is_better else va > vb) else (0, 1)

    # ══════════════════════════════════════════════════════════
    # COMPUTE ALL METRICS
    # ══════════════════════════════════════════════════════════

    # ── Race pace per compound ────────────────────────────────
    # Use the best valid stint per driver × compound across ALL sessions
    # (same logic as Stints tab: Stint_Rank_Across_Sessions = 1).
    # Falls back to all clean valid laps for that driver × compound if
    # stints_df is unavailable.
    pace_rows: dict[str, list[dict]] = {}
    for cmp in COMPOUNDS:
        cmp_rows: list[dict] = []
        for team in teams_sorted:
            if team not in pairs:
                continue
            drv_a, drv_b = pairs[team]

            def _best_stint_median(driver: str, compound: str) -> float:
                # Try to find the best valid stint from analyze_stints
                if fs is not None and not fs.empty and "Stint_Rank_Across_Sessions" in fs.columns:
                    best = fs[
                        (fs["Driver_Short"] == driver)
                        & (fs["Compound"] == compound)
                        & fs["Valid_Stint"]
                        & (fs["Stint_Rank_Across_Sessions"] == 1)
                    ]
                    if not best.empty and "Stint_FuelCorr" in best.columns:
                        v_ = pd.to_numeric(best["Stint_FuelCorr"], errors="coerce").dropna()
                        if not v_.empty:
                            return float(v_.iloc[0])
                # Fallback: trimmed median of fuel-corrected laps
                sub = v_clean[
                    (v_clean["Driver_Short"] == driver)
                    & (v_clean["Compound"] == compound)
                    & v_clean["LapTime_FuelCorrected"].notna()
                ]
                if sub.empty:
                    return float("nan")
                t = sub["LapTime_FuelCorrected"]
                lo, hi = t.quantile(0.10), t.quantile(0.90)
                trimmed = t[t.between(lo, hi)]
                return float(trimmed.median() if not trimmed.empty else t.median())

            va = _best_stint_median(drv_a, cmp)
            vb = _best_stint_median(drv_b, cmp)
            if not (np.isnan(va) and np.isnan(vb)):
                cmp_rows.append(dict(team=team, drv_a=drv_a, drv_b=drv_b,
                                     val_a=va, val_b=vb))
        if cmp_rows:
            pace_rows[cmp] = cmp_rows

    # ── Quali sim / single-lap pace ───────────────────────────
    # Best quali-sim lap across ALL sessions (not just quali sessions).
    # Falls back to best valid lap if Is_Quali_Sim is absent.
    if "Is_Quali_Sim" in fl.columns and fl["Is_Quali_Sim"].any():
        qs_pool  = fl[fl["ValidLap"] & (fl["Is_Quali_Sim"] == True)]
        qs_label = "Quali Sim Best Lap (all sessions)"
    else:
        qs_pool  = v
        qs_label = "Best Valid Lap (no Is_Quali_Sim)"
    qs_rows = _metric_rows(qs_pool, lambda s: s["LapTime_s"].min()) if not qs_pool.empty else []

    # Total valid laps
    laps_rows = _metric_rows(v, lambda s: float(len(s)))

    # Consistency — IQR/Median × 100 (lower = better)
    def _consistency(s: pd.DataFrame) -> float:
        t = s["LapTime_s"].dropna()
        if len(t) < 4:
            return float("nan")
        q25, q75, med = t.quantile(0.25), t.quantile(0.75), t.median()
        return (q75 - q25) / med * 100.0 if med > 0 else float("nan")
    cons_rows = _metric_rows(v_clean, _consistency)

    # Average pit stop duration (race/sprint only)
    pit_rows: list[dict] = []
    if has_race:
        _race_all = fl[fl["session_name"].isin(race_sess)].sort_values(
            ["session_name", "DriverNo", "LapNo"]
        )
        _pit_data: list[dict] = []
        for (sess, drv_no), grp in _race_all.groupby(["session_name", "DriverNo"]):
            grp_s   = grp.sort_values("LapNo")
            in_laps = grp_s[grp_s["InLap"]  & grp_s["PitIn"].notna()]
            out_laps = grp_s[grp_s["OutLap"] & grp_s["PitOut"].notna()]
            # Build a dict LapNo → first PitOut value (avoid duplicate-index issue)
            out_dict = {}
            for _, orow in out_laps.iterrows():
                ln = int(orow["LapNo"])
                if ln not in out_dict:
                    out_dict[ln] = float(orow["PitOut"])
            for _, inrow in in_laps.iterrows():
                nxt = int(inrow["LapNo"]) + 1
                try:
                    pit_in_s = float(inrow["PitIn"])
                    if nxt in out_dict and np.isfinite(pit_in_s) and np.isfinite(out_dict[nxt]):
                        dur = out_dict[nxt] - pit_in_s
                        if 1.5 < dur < 65.0:
                            _pit_data.append({
                                "Driver_Short": inrow["Driver_Short"],
                                "Team":         inrow["Team"],
                                "dur":          dur,
                            })
                except Exception:
                    pass
        if _pit_data:
            _pit_df  = pd.DataFrame(_pit_data)
            pit_rows = _metric_rows(_pit_df, lambda s: s["dur"].mean())

    # Race finish position & positions gained
    finish_rows: list[dict] = []
    pgain_rows:  list[dict] = []
    if has_race and "Classified_Position" in fl.columns:
        _rr_base = fl[fl["session_name"].isin(race_sess)].copy()
        # Convert to numeric safely (handles "DNF", "DSQ", etc.)
        _rr_base["_fin_num"]  = pd.to_numeric(_rr_base["Classified_Position"], errors="coerce")
        _rr_base["_grid_num"] = pd.to_numeric(
            _rr_base.get("Grid_Position", pd.Series(dtype=float)), errors="coerce"
        ) if "Grid_Position" in _rr_base.columns else np.nan
        _rr = (
            _rr_base.groupby("Driver_Short")
            .agg(
                Team      =("Team",       "first"),
                Finish_num=("_fin_num",   "first"),
                Grid_num  =("_grid_num",  "first"),
            )
            .reset_index()
        )
        _rr["Gained"] = _rr["Grid_num"] - _rr["Finish_num"]

        def _rr_rows(val_col):
            out = []
            for team in teams_sorted:
                if team not in pairs:
                    continue
                drv_a, drv_b = pairs[team]
                sa = _rr[_rr["Driver_Short"] == drv_a]
                sb = _rr[_rr["Driver_Short"] == drv_b]
                if sa.empty and sb.empty:
                    continue
                va = float(sa[val_col].iloc[0]) if (not sa.empty and sa[val_col].notna().any()) else float("nan")
                vb = float(sb[val_col].iloc[0]) if (not sb.empty and sb[val_col].notna().any()) else float("nan")
                out.append(dict(team=team, drv_a=drv_a, drv_b=drv_b, val_a=va, val_b=vb))
            return out

        finish_rows = _rr_rows("Finish_num")
        pgain_rows  = _rr_rows("Gained")

    # Overtakes (race/sprint only; requires flag_position_changes)
    overtake_rows: list[dict] = []
    if has_race and "Overtook" in fl.columns:
        _ov_pool  = fl[fl["session_name"].isin(race_sess)]
        overtake_rows = _metric_rows(_ov_pool, lambda s: float(s["Overtook"].sum()))

    # Championship points (sum across all race/sprint sessions in filter)
    # Race_Points is repeated on every lap row — deduplicate to one value
    # per driver × session before summing, then aggregate across sessions.
    champ_rows: list[dict] = []
    if has_race and "Race_Points" in fl.columns:
        _pts_dedup = (
            fl[fl["session_name"].isin(race_sess)]
            .groupby(["session_name", "Driver_Short", "Team"])["Race_Points"]
            .first()                                          # one value per session
            .reset_index()
        )
        _pts_dedup["Race_Points"] = pd.to_numeric(_pts_dedup["Race_Points"], errors="coerce")
        _pts_pool = (
            _pts_dedup
            .groupby(["Driver_Short", "Team"])["Race_Points"]
            .sum()
            .reset_index(name="pts")
        )
        for team in teams_sorted:
            if team not in pairs:
                continue
            drv_a, drv_b = pairs[team]
            ra = _pts_pool[_pts_pool["Driver_Short"] == drv_a]
            rb = _pts_pool[_pts_pool["Driver_Short"] == drv_b]
            va = float(ra["pts"].iloc[0]) if not ra.empty else float("nan")
            vb = float(rb["pts"].iloc[0]) if not rb.empty else float("nan")
            if not (np.isnan(va) and np.isnan(vb)):
                champ_rows.append(dict(team=team, drv_a=drv_a, drv_b=drv_b,
                                       val_a=va, val_b=vb))

    # Qualifying best time (Q3 → Q2 → Q1 cascade from results, else best lap in quali)
    quali_time_rows: list[dict] = []
    if has_quali:
        q_cols_avail = [c for c in ("Q3_s", "Q2_s", "Q1_s") if c in fl.columns]
        if q_cols_avail:
            _q_pool = fl[fl["session_name"].isin(quali_sess)]
            for team in teams_sorted:
                if team not in pairs:
                    continue
                drv_a, drv_b = pairs[team]
                def _best_q_time(driver):
                    sub = _q_pool[_q_pool["Driver_Short"] == driver]
                    if sub.empty:
                        return float("nan")
                    for qc in q_cols_avail:
                        v_ = pd.to_numeric(sub[qc], errors="coerce").dropna()
                        if not v_.empty:
                            return float(v_.iloc[0])
                    return float("nan")
                va, vb = _best_q_time(drv_a), _best_q_time(drv_b)
                if not (np.isnan(va) and np.isnan(vb)):
                    quali_time_rows.append(
                        dict(team=team, drv_a=drv_a, drv_b=drv_b, val_a=va, val_b=vb)
                    )
        if not quali_time_rows and not v_quali.empty:
            quali_time_rows = _metric_rows(v_quali, lambda s: s["LapTime_s"].min())

    # ══════════════════════════════════════════════════════════
    # SCOREBOARD  — tally wins per team
    # ══════════════════════════════════════════════════════════

    def _get_vals(rows_list, team):
        for r in rows_list:
            if r["team"] == team:
                return r["val_a"], r["val_b"]
        return float("nan"), float("nan")

    sb_items = []
    for team in teams_sorted:
        if team not in pairs:
            continue
        drv_a, drv_b = pairs[team]
        score_a, score_b = 0, 0
        metric_pills_data = []

        all_metrics_def = [
            *[(f"Pace {c}",   pace_rows.get(c, []),   True,  format_lap_time)
              for c in COMPOUNDS if c in pace_rows],
            (qs_label,        qs_rows,                 True,  format_lap_time),
            ("Consistency",   cons_rows,               True,  lambda v: f"{v:.2f}%"),
            ("Total Laps",    laps_rows,               False, lambda v: str(int(v)) if not np.isnan(v) else "—"),
            *([("Avg Pit Stop",  pit_rows,      True,  lambda v: f"{v:.2f}s")] if pit_rows  else []),
            *([("Race Finish",   finish_rows,   True,  lambda v: f"P{int(v)}"  if not np.isnan(v) else "—")] if finish_rows  else []),
            *([("Pos. Gained",   pgain_rows,    False, lambda v: (f"+{int(v)}" if v > 0 else str(int(v))) if not np.isnan(v) else "—")] if pgain_rows   else []),
            *([("Overtakes",     overtake_rows, False, lambda v: str(int(v))   if not np.isnan(v) else "—")] if overtake_rows else []),
            *([("Champ. Pts",    champ_rows,    False, lambda v: f"{int(v)} pts" if not np.isnan(v) else "—")] if champ_rows    else []),
            *([("Quali Time",    quali_time_rows, True, format_lap_time)] if quali_time_rows else []),
        ]

        for label, rows_list, lib, fmt in all_metrics_def:
            va, vb = _get_vals(rows_list, team)
            wa, wb = _wins(va, vb, lower_is_better=lib)
            score_a += wa; score_b += wb
            try:
                a_str = fmt(va) if not np.isnan(va) else "—"
                b_str = fmt(vb) if not np.isnan(vb) else "—"
            except Exception:
                a_str = "—"; b_str = "—"
            winner = drv_a if wa else (drv_b if wb else None)
            metric_pills_data.append((label, a_str, b_str, winner))

        clr   = TEAM_COLORS.get(team, "#808080")
        total = max(score_a + score_b, 1)
        pct_a = score_a / total * 100

        # Progress bar
        bar_el = html.Div(
            html.Div([
                html.Div(style={
                    "width": f"{pct_a:.1f}%", "height": "100%",
                    "background": "#00D2BE", "display": "inline-block",
                    "borderRadius": "3px 0 0 3px" if pct_a > 0 and pct_a < 100 else "3px",
                }),
                html.Div(style={
                    "width": f"{100 - pct_a:.1f}%", "height": "100%",
                    "background": "#FF8700", "display": "inline-block",
                    "borderRadius": "0 3px 3px 0" if pct_a > 0 and pct_a < 100 else "3px",
                }),
            ], style={"display": "flex", "height": "100%"}),
            style={"height": "7px", "borderRadius": "4px", "margin": "6px 0",
                   "background": GRID_CLR},
        )

        # Metric detail pills
        pills = []
        for label, a_str, b_str, winner in metric_pills_data:
            bg = "#00D2BE" if winner == drv_a else ("#FF8700" if winner == drv_b else "#333")
            pills.append(html.Span(
                f"{label}: {a_str} | {b_str}",
                style={
                    "background": bg + "28",
                    "border": f"1px solid {bg}",
                    "borderRadius": "3px", "padding": "2px 7px",
                    "fontSize": "0.68rem", "marginRight": "5px",
                    "marginBottom": "4px", "display": "inline-block",
                    "color": TEXT_MAIN,
                },
                title=f"Winner: {winner or '—'}",
            ))

        sb_items.append(dbc.Col(
            dbc.Card(dbc.CardBody([
                html.Div([
                    html.Span("● ", style={"color": clr, "fontSize": "1.1rem"}),
                    html.Span(team, style={
                        "fontWeight": "700", "fontSize": "0.88rem",
                        "color": TEXT_MAIN, "letterSpacing": "0.5px",
                    }),
                ]),
                html.Div([
                    html.Span(drv_a, style={
                        "color": "#00D2BE", "fontWeight": "800", "fontSize": "1.25rem",
                    }),
                    html.Span(f"  {score_a} – {score_b}  ", style={
                        "color": TEXT_DIM, "fontSize": "0.95rem", "fontWeight": "600",
                    }),
                    html.Span(drv_b, style={
                        "color": "#FF8700", "fontWeight": "800", "fontSize": "1.25rem",
                    }),
                ], style={"margin": "5px 0"}),
                bar_el,
                html.Div(pills, style={"marginTop": "8px", "lineHeight": "2.0"}),
            ]), style={
                "background": CARD_BG,
                "border": f"1px solid {_hex_to_rgba(clr, 0.27)}",
                "borderRadius": "8px",
            }),
            md=6, lg=4, className="mb-3",
        ))

    scoreboard = card(
        html.Span([
            "Head-to-Head Scoreboard",
            html.Span(
                " — drivers sorted alphabetically within each team (teal = A, orange = B)",
                style={"color": TEXT_DIM, "fontWeight": "400",
                       "fontSize": "0.75rem", "marginLeft": "8px"},
            ),
        ]),
        dbc.Row(sb_items),
    )

    # ══════════════════════════════════════════════════════════
    # SECTION: RACE PACE PER COMPOUND
    # ══════════════════════════════════════════════════════════
    pace_col_items = []
    if pace_rows:
        n_cmp = len(pace_rows)
        col_w = 12 if n_cmp == 1 else 6 if n_cmp == 2 else 4
        for cmp, rows_ in pace_rows.items():
            fig = _gap_chart(
                rows_,
                title=f"Race Pace – {cmp}",
                xlabel="Gap (s)  ·  negative = left driver faster",
                fmt_fn=format_lap_time,
                lower_is_better=True,
                note="Stint_FuelCorr (fuel-corrected trimmed median) of best valid stint across all sessions. Falls back to trimmed median of fuel-corrected laps.",
                unit="s",
            )
            pace_col_items.append(dbc.Col(card(
                html.Span([
                    "Race Pace – ",
                    html.Span(cmp, style={
                        "color": COMPOUND_COLORS.get(cmp, "#fff"),
                        "fontWeight": "800",
                    }),
                ]),
                dcc.Graph(figure=fig, config=GFX),
            ), md=col_w))
    else:
        pace_col_items = [dbc.Col(html.P(
            "No race / sprint race sessions in current selection.",
            style={"color": TEXT_DIM, "fontStyle": "italic"},
        ), md=12)]

    race_pace_section = card(
        html.Span([
            "Race Pace by Compound",
            html.Span(" — best valid stint per driver × compound across all sessions",
                      style={"color": TEXT_DIM, "fontWeight": "400",
                             "fontSize": "0.75rem", "marginLeft": "8px"}),
        ]),
        dbc.Row(pace_col_items),
    )

    # ══════════════════════════════════════════════════════════
    # SECTION: CONSISTENCY + TOTAL LAPS
    # ══════════════════════════════════════════════════════════
    cons_fig = _gap_chart(
        cons_rows,
        title="Consistency — IQR / Median × 100%",
        xlabel="Gap (%)  ·  negative = left driver more consistent",
        fmt_fn=lambda v: f"{v:.2f}%",
        lower_is_better=True,
        note="Valid non-perturbed laps. IQR = P75 − P25 of lap-time distribution. Lower % = tighter.",
        unit="%",
    )
    laps_fig = _gap_chart(
        laps_rows,
        title="Total Valid Laps  (all sessions)",
        xlabel="Gap (laps)  ·  negative = left driver ran more laps",
        fmt_fn=lambda v: str(int(v)) if not np.isnan(v) else "—",
        lower_is_better=False,
        note="ValidLap=True count across all sessions in current filter.",
        unit="laps",
    )
    consistency_section = card(
        "Consistency & Volume",
        dbc.Row([
            dbc.Col(dcc.Graph(figure=cons_fig, config=GFX), md=7),
            dbc.Col(dcc.Graph(figure=laps_fig, config=GFX), md=5),
        ]),
    )

    # ══════════════════════════════════════════════════════════
    # SECTION: QUALIFYING (conditional)
    # ══════════════════════════════════════════════════════════
    quali_col_items = []
    if has_quali:
        if qs_rows:
            qs_fig = _gap_chart(
                qs_rows,
                title=qs_label,
                xlabel="Gap (s)  ·  negative = left driver faster",
                fmt_fn=format_lap_time,
                lower_is_better=True,
                note=(
                    "Lap within 0.5% of personal best on tyre age ≤ 4."
                    if "Is_Quali_Sim" in fl.columns and fl["Is_Quali_Sim"].any()
                    else "Is_Quali_Sim absent — best valid lap used."
                ),
                unit="s",
            )
            quali_col_items.append(
                dbc.Col(card(qs_label, dcc.Graph(figure=qs_fig, config=GFX)), md=6)
            )
        if quali_time_rows:
            qt_fig = _gap_chart(
                quali_time_rows,
                title="Qualifying Classification Time",
                xlabel="Gap (s)  ·  negative = left driver faster",
                fmt_fn=format_lap_time,
                lower_is_better=True,
                note="Best of Q3 / Q2 / Q1 from session results (enrich_session_results).",
                unit="s",
            )
            quali_col_items.append(
                dbc.Col(card("Qualifying Classification Time", dcc.Graph(figure=qt_fig, config=GFX)), md=6)
            )

    # ══════════════════════════════════════════════════════════
    # SECTION: RACE / SPRINT (conditional)
    # ══════════════════════════════════════════════════════════
    race_col_items = []
    if has_race:
        if pit_rows:
            pit_fig = _gap_chart(
                pit_rows,
                title="Average Pit Stop Duration",
                xlabel="Gap (s)  ·  negative = left driver faster pit",
                fmt_fn=lambda v: f"{v:.2f}s",
                lower_is_better=True,
                note="PitOut − PitIn for matched in/out lap pairs. Range filter: 1.5 – 65 s.",
                unit="s",
            )
            race_col_items.append(
                dbc.Col(card("Pit Stop Duration", dcc.Graph(figure=pit_fig, config=GFX)), md=6)
            )

        if finish_rows:
            fin_fig = _gap_chart(
                finish_rows,
                title="Race Finish Position  (lower position = better)",
                xlabel="Gap  ·  negative = left driver finished higher",
                fmt_fn=lambda v: f"P{int(v)}" if not np.isnan(v) else "—",
                lower_is_better=True,
                note="Classified_Position from session results. DNF / DSQ → shown as —.",
                unit="pos",
            )
            race_col_items.append(
                dbc.Col(card("Race Finish Position", dcc.Graph(figure=fin_fig, config=GFX)), md=6)
            )

        if pgain_rows:
            pg_fig = _gap_chart(
                pgain_rows,
                title="Positions Gained / Lost  (Grid → Classified Finish)",
                xlabel="Gap  ·  negative = left driver gained more",
                fmt_fn=lambda v: (f"+{int(v)}" if v > 0 else str(int(v))) if not np.isnan(v) else "—",
                lower_is_better=False,   # higher gain is better
                note="Positions gained = Grid_Position − Classified_Position. Positive = moved up.",
                unit="pos",
            )
            race_col_items.append(
                dbc.Col(card("Positions Gained / Lost", dcc.Graph(figure=pg_fig, config=GFX)), md=6)
            )

        if overtake_rows:
            ov_fig = _gap_chart(
                overtake_rows,
                title="Overtakes Made  (race/sprint sessions)",
                xlabel="Gap (overtakes)  ·  negative = left driver made more",
                fmt_fn=lambda v: str(int(v)) if not np.isnan(v) else "—",
                lower_is_better=False,
                note="Overtook = position gained ≥ 1 on a non-pit lap (flag_position_changes).",
                unit="overtakes",
            )
            race_col_items.append(
                dbc.Col(card("Overtakes", dcc.Graph(figure=ov_fig, config=GFX)), md=6)
            )

        if champ_rows:
            champ_fig = _gap_chart(
                champ_rows,
                title="Championship Points Scored",
                xlabel="Gap (pts)  ·  negative = left driver scored more",
                fmt_fn=lambda v: f"{int(v)} pts" if not np.isnan(v) else "—",
                lower_is_better=False,
                note="Sum of Race_Points across all race/sprint sessions in current filter.",
                unit="pts",
            )
            # KPI pills: one per team showing A pts vs B pts
            champ_kpis = []
            for r in champ_rows:
                clr = TEAM_COLORS.get(r["team"], "#808080")
                va_s = f"{int(r['val_a'])} pts" if not np.isnan(r["val_a"]) else "—"
                vb_s = f"{int(r['val_b'])} pts" if not np.isnan(r["val_b"]) else "—"
                winner = (
                    r["drv_a"] if (not np.isnan(r["val_a"]) and not np.isnan(r["val_b"]) and r["val_a"] >= r["val_b"])
                    else (r["drv_b"] if not np.isnan(r["val_b"]) else None)
                )
                champ_kpis.append(dbc.Col(
                    dbc.Card(dbc.CardBody([
                        html.P(
                            html.Span([
                                "● ", html.Span(r["team"],
                                    style={"fontWeight":"700","fontSize":"0.78rem"})
                            ], style={"color": clr}),
                            style={"marginBottom": "4px", "fontSize": "0.72rem"},
                        ),
                        html.Div([
                            html.Span(r["drv_a"],
                                style={"color": "#00D2BE" if winner == r["drv_a"] else TEXT_DIM,
                                       "fontWeight": "800", "fontSize": "1.05rem"}),
                            html.Span(f"  {va_s}  ·  {vb_s}  ",
                                style={"color": TEXT_DIM, "fontSize": "0.85rem"}),
                            html.Span(r["drv_b"],
                                style={"color": "#FF8700" if winner == r["drv_b"] else TEXT_DIM,
                                       "fontWeight": "800", "fontSize": "1.05rem"}),
                        ]),
                    ]), style={"background": CARD_BG,
                               "border": f"1px solid {_hex_to_rgba(clr, 0.35)}",
                               "borderRadius": "8px"}),
                    xs=6, md=4, lg=3, className="mb-2",
                ))
            race_col_items.append(dbc.Col(card(
                html.Span([
                    "Championship Points",
                    html.Span(" — race/sprint sessions in current filter",
                              style={"color": TEXT_DIM, "fontWeight": "400",
                                     "fontSize": "0.75rem", "marginLeft": "8px"}),
                ]),
                html.Div([
                    dbc.Row(champ_kpis, className="mb-3"),
                    dcc.Graph(figure=champ_fig, config=GFX),
                ]),
            ), md=12))

    # ══════════════════════════════════════════════════════════
    # ASSEMBLE FULL LAYOUT
    # ══════════════════════════════════════════════════════════
    sections = [scoreboard, race_pace_section, consistency_section]

    if quali_col_items:
        sections.append(card("Qualifying", dbc.Row(quali_col_items)))

    if race_col_items:
        sections.append(card(
            html.Span([
                "Race / Sprint Performance",
                html.Span(
                    f" — {', '.join(s.split('_')[0] for s in race_sess)}",
                    style={"color": TEXT_DIM, "fontWeight": "400",
                           "fontSize": "0.75rem", "marginLeft": "8px"},
                ),
            ]),
            dbc.Row(race_col_items),
        ))

    return html.Div(sections)


# ══════════════════════════════════════════════════════════════
# TAB 8 – TRACK INFO
# ══════════════════════════════════════════════════════════════

# ── Score → colour mapping ────────────────────────────────────
def _score_color(score: int) -> str:
    return {1: "#2ECC71", 2: "#F1C40F", 3: "#E67E22", 4: "#E74C3C"}.get(score, "#808080")

def _score_badge(label: str, score: int) -> html.Span:
    bg = _score_color(score)
    return html.Span(label, style={
        "background": bg, "color": "#000" if score <= 2 else "#fff",
        "borderRadius": "4px", "padding": "2px 9px",
        "fontSize": "0.72rem", "fontWeight": "700", "letterSpacing": "0.3px",
    })

# ── Stat pill ─────────────────────────────────────────────────
def _stat_pill(label, value, color=None):
    return html.Div([
        html.P(label, style={"color": TEXT_DIM, "fontSize": "0.65rem",
                              "letterSpacing": "1px", "marginBottom": "2px",
                              "fontWeight": "600"}),
        html.P(value, style={"color": color or TEXT_MAIN, "fontSize": "0.95rem",
                              "fontWeight": "800", "marginBottom": 0}),
    ], style={
        "background": CARD_BG, "border": f"1px solid {GRID_CLR}",
        "borderRadius": "6px", "padding": "8px 14px", "textAlign": "center",
        "flex": "1",
    })

# ── FastF1 circuit meta (lap record, circuit length, corners) ──
_FF1_CIRCUIT_META: dict = {
    # circuit_key → {lap_record, lap_record_driver, lap_record_year,
    #                length_km, corners, drs_zones}
    "italie":          {"length_km": 5.793, "corners": 11, "drs_zones": 2, "lap_record": "1:21.046", "lap_record_driver": "Rubens Barrichello", "lap_record_year": 2004},
    "monaco":          {"length_km": 3.337, "corners": 19, "drs_zones": 1, "lap_record": "1:12.909", "lap_record_driver": "Lewis Hamilton",      "lap_record_year": 2021},
    "grande_bretagne": {"length_km": 5.891, "corners": 18, "drs_zones": 2, "lap_record": "1:27.097", "lap_record_driver": "Max Verstappen",      "lap_record_year": 2020},
    "belgique":        {"length_km": 7.004, "corners": 19, "drs_zones": 2, "lap_record": "1:46.286", "lap_record_driver": "Valtteri Bottas",     "lap_record_year": 2018},
    "japon":           {"length_km": 5.807, "corners": 18, "drs_zones": 1, "lap_record": "1:30.983", "lap_record_driver": "Lewis Hamilton",      "lap_record_year": 2019},
    "singapour":       {"length_km": 5.063, "corners": 23, "drs_zones": 3, "lap_record": "1:35.867", "lap_record_driver": "Kevin Magnussen",     "lap_record_year": 2018},
    "azerbaidjan":     {"length_km": 6.003, "corners": 20, "drs_zones": 2, "lap_record": "1:43.009", "lap_record_driver": "Charles Leclerc",     "lap_record_year": 2019},
    "arabie_saoudite": {"length_km": 6.174, "corners": 27, "drs_zones": 3, "lap_record": "1:30.734", "lap_record_driver": "Lewis Hamilton",      "lap_record_year": 2021},
    "hongrie":         {"length_km": 4.381, "corners": 14, "drs_zones": 1, "lap_record": "1:16.627", "lap_record_driver": "Lewis Hamilton",      "lap_record_year": 2020},
    "espagne":         {"length_km": 4.675, "corners": 16, "drs_zones": 2, "lap_record": "1:18.149", "lap_record_driver": "Max Verstappen",      "lap_record_year": 2021},
    "autriche":        {"length_km": 4.318, "corners": 10, "drs_zones": 3, "lap_record": "1:05.619", "lap_record_driver": "Carlos Sainz",        "lap_record_year": 2020},
    "pays_bas":        {"length_km": 4.259, "corners": 14, "drs_zones": 2, "lap_record": "1:11.097", "lap_record_driver": "Lewis Hamilton",      "lap_record_year": 2021},
    "qatar":           {"length_km": 5.419, "corners": 16, "drs_zones": 1, "lap_record": "1:24.319", "lap_record_driver": "Max Verstappen",      "lap_record_year": 2023},
    "canada":          {"length_km": 4.361, "corners": 14, "drs_zones": 2, "lap_record": "1:13.078", "lap_record_driver": "Valtteri Bottas",     "lap_record_year": 2019},
    "etats_unis":      {"length_km": 5.513, "corners": 20, "drs_zones": 2, "lap_record": "1:36.169", "lap_record_driver": "Charles Leclerc",     "lap_record_year": 2019},
    "mexique":         {"length_km": 4.304, "corners": 17, "drs_zones": 3, "lap_record": "1:17.774", "lap_record_driver": "Valtteri Bottas",     "lap_record_year": 2021},
    "bresil":          {"length_km": 4.309, "corners": 15, "drs_zones": 2, "lap_record": "1:10.540", "lap_record_driver": "Valtteri Bottas",     "lap_record_year": 2018},
    "abu_dhabi":       {"length_km": 5.281, "corners": 16, "drs_zones": 2, "lap_record": "1:26.103", "lap_record_driver": "Max Verstappen",      "lap_record_year": 2021},
}

# ── Notable corners by circuit ────────────────────────────────
_NOTABLE_CORNERS: dict = {
    "italie":          ["T1 Prima Variante (chicane)", "T4 Seconda Variante (chicane)", "T11 Parabolica (Curva Alboreto)"],
    "monaco":          ["T1 Sainte-Dévote", "T6 Massenet", "T10 Casino", "T17 Mirabeau", "T19 Fairmont Hairpin", "T23 Rascasse", "T25 Antony Noghes"],
    "grande_bretagne": ["T3 Vale", "T6 Maggotts", "T7 Becketts", "T8 Chapel", "T13 Stowe", "T15 Club"],
    "belgique":        ["T1 La Source", "T7 Eau Rouge", "T8 Raidillon", "T14 Pouhon", "T18 Bus Stop chicane"],
    "japon":           ["T1 First Curve", "T2 S Curves", "T11 Degner 1", "T15 Hairpin", "T16 Spoon", "T18 130R", "T20 Casio"],
    "singapour":       ["T1 Turn 1", "T10 Singapore Sling", "T18 Raffles Boulevard", "T23 Anderson Bridge"],
    "azerbaidjan":     ["T8 Castle corner", "T15 Station Hairpin", "T20 Turn 20"],
    "arabie_saoudite": ["T4 Turn 4", "T13 Turn 13", "T22 Turn 22", "T27 Final"],
    "hongrie":         ["T1 Turn 1", "T4 Turns 4-5", "T11 Hairpin"],
    "espagne":         ["T1 Turn 1", "T3 Renault (S-bend)", "T5 Seat", "T10 La Caixa", "T14 Campsa", "T16 Final chicane"],
    "autriche":        ["T2 Remus (hairpin)", "T4 Schlossgold", "T6 Rindt"],
    "pays_bas":        ["T3 Tarzanbocht", "T10 Scheivlak", "T12 Hugenholtz", "T14 Mastersbocht (banked)"],
    "qatar":           ["T1 Turn 1", "T12 Turn 12", "T14 Turn 14"],
    "canada":          ["T1 Senna S", "T10 Wall of Champions hairpin", "T13 Casino"],
    "etats_unis":      ["T1 Big Red Braking Zone", "T11 Back straight chicane", "T15 Thunder hairpin"],
    "mexique":         ["T1 Peraltada modified", "T4 Esses", "T12 Stadium S"],
    "bresil":          ["T1 Curva do Sol", "T2 Senna S", "T6 Ferradura", "T11 Junção", "T13 Subida dos Boxes"],
    "abu_dhabi":       ["T7 Hairpin", "T9 Marina", "T11 Bab Al Shams", "T13 Turn 13"],
}

# ── Radar chart for circuit demand profile ────────────────────
def _radar_chart(row: pd.Series) -> go.Figure:
    dims   = ["Avg Speed", "Full Throttle", "Lateral Load", "Tyre Deg", "Tyre Difficulty"]
    scores = [
        row["avg_speed_score"], row["full_throttle_score"],
        row["lateral_load_score"], row["tyre_deg_score"],
        row["tyre_difficulty_score"],
    ]
    # Close the polygon
    dims_c   = dims + [dims[0]]
    scores_c = scores + [scores[0]]
    fig = go.Figure(go.Scatterpolar(
        r=scores_c, theta=dims_c,
        fill="toself",
        fillcolor="rgba(225,6,0,0.18)",
        line=dict(color=ACCENT, width=2),
        marker=dict(size=6, color=ACCENT),
        hovertemplate="%{theta}: %{r}/4<extra></extra>",
    ))
    fig.update_layout(
        polar=dict(
            bgcolor=CARD_BG,
            radialaxis=dict(
                visible=True, range=[0, 4], tickvals=[1, 2, 3, 4],
                tickfont=dict(size=8, color=TEXT_DIM),
                gridcolor=GRID_CLR, linecolor=GRID_CLR,
            ),
            angularaxis=dict(
                tickfont=dict(size=9, color=TEXT_MAIN),
                gridcolor=GRID_CLR, linecolor=GRID_CLR,
            ),
        ),
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
        height=280, margin=dict(l=40, r=40, t=30, b=30),
        showlegend=False,
    )
    return fig

# ── Historical leaderboard chart ──────────────────────────────
def _hist_leaderboard(df_res: pd.DataFrame, session_type: str, year: int) -> go.Figure:
    sub = df_res[
        (df_res["session_type"] == session_type) &
        (df_res["season"] == year)
    ].copy()
    if sub.empty:
        return go.Figure()

    # Normalise position column
    pos_col = next((c for c in ("ClassifiedPosition","Position","Q") if c in sub.columns), None)
    if pos_col:
        sub["_pos"] = pd.to_numeric(sub[pos_col], errors="coerce")
    else:
        sub["_pos"] = range(1, len(sub)+1)

    sub = sub.sort_values("_pos").head(20).reset_index(drop=True)

    # Driver label
    abbr_col = next((c for c in ("Abbreviation","Driver","DriverId") if c in sub.columns), None)
    team_col = next((c for c in ("TeamName","ConstructorName","Team") if c in sub.columns), None)
    sub["_drv"]  = sub[abbr_col].astype(str).str.strip() if abbr_col else sub.index.astype(str)
    sub["_team"] = sub[team_col].astype(str).str.strip() if team_col else "Unknown"
    sub["_color"]= sub["_team"].map(TEAM_COLORS).fillna("#808080")

    # Time/gap column
    time_col = next((c for c in ("Time","Q1","FastestLap","FastestLapTime") if c in sub.columns), None)
    if time_col:
        sub["_time_s"] = pd.to_numeric(sub[time_col], errors="coerce")
        leader = sub["_time_s"].dropna().iloc[0] if sub["_time_s"].notna().any() else None
        if leader:
            sub["_gap"] = (sub["_time_s"] - leader).apply(
                lambda x: "—" if x == 0 or pd.isna(x) else f"+{x:.3f}s"
            )
            sub["_label"] = sub["_time_s"].apply(format_lap_time)
        else:
            sub["_gap"]   = "—"
            sub["_label"] = "—"
    else:
        sub["_gap"]   = "—"
        sub["_label"] = "—"

    fig = go.Figure(go.Bar(
        x=sub["_pos"],
        y=[1]*len(sub),
        orientation="v",
        marker_color=sub["_color"],
        text=sub["_drv"],
        textposition="inside",
        textfont=dict(size=9, color="#fff"),
        customdata=sub[["_drv","_team","_label","_gap","_pos"]].values,
        hovertemplate=(
            "P%{customdata[4]}  <b>%{customdata[0]}</b>  (%{customdata[1]})<br>"
            "Time: %{customdata[2]}  Gap: %{customdata[3]}<extra></extra>"
        ),
    ))
    theme(fig, 200, f"{session_type} – {year}")
    fig.update_layout(
        showlegend=False,
        xaxis=dict(title="Position", tickvals=sub["_pos"].tolist(),
                   gridcolor=GRID_CLR, zeroline=False),
        yaxis=dict(visible=False),
        margin=dict(l=10, r=10, t=50, b=40),
        bargap=0.05,
    )
    return fig


def _hist_table(df_res: pd.DataFrame, session_type: str, year: int) -> dash_table.DataTable:
    sub = df_res[
        (df_res["session_type"] == session_type) &
        (df_res["season"] == year)
    ].copy()
    if sub.empty:
        return html.P("No data available.", style={"color": TEXT_DIM})

    pos_col  = next((c for c in ("ClassifiedPosition","Position","Q") if c in sub.columns), None)
    abbr_col = next((c for c in ("Abbreviation","DriverId","Driver") if c in sub.columns), None)
    team_col = next((c for c in ("TeamName","ConstructorName","Team") if c in sub.columns), None)
    time_col = next((c for c in ("Time","Q1","FastestLap","FastestLapTime") if c in sub.columns), None)
    pts_col  = "Points" if "Points" in sub.columns else None

    keep: dict = {}
    if pos_col:  keep["Pos"]    = sub[pos_col].apply(lambda v: pd.to_numeric(v, errors="coerce"))
    if abbr_col: keep["Driver"] = sub[abbr_col].astype(str).str.strip()
    if team_col: keep["Team"]   = sub[team_col].astype(str).str.strip()
    if time_col:
        t_s = pd.to_numeric(sub[time_col], errors="coerce")
        keep["Time"]  = t_s.apply(format_lap_time)
        leader = t_s.dropna().iloc[0] if t_s.notna().any() else None
        keep["Gap"]   = (t_s - leader).apply(
            lambda x: "—" if (pd.isna(x) or x == 0) else f"+{x:.3f}s"
        ) if leader else "—"
    if pts_col:  keep["Pts"]   = pd.to_numeric(sub[pts_col], errors="coerce")

    out = pd.DataFrame(keep)
    if "Pos" in out.columns:
        out = out.sort_values("Pos").reset_index(drop=True)

    return dash_table.DataTable(
        data=out.to_dict("records"),
        columns=[{"name": c, "id": c} for c in out.columns],
        **TABLE_STYLE,
        style_data_conditional=[
            {"if": {"row_index": 0}, "backgroundColor": ACCENT+"22", "fontWeight": "700"},
            {"if": {"row_index": 1}, "backgroundColor": "#88888822"},
            {"if": {"row_index": 2}, "backgroundColor": "#88441122"},
        ],
    )


# ── Sector heatmap from laps data (current loaded meeting) ────
def _sector_heatmap(laps_df: pd.DataFrame) -> go.Figure:
    sect_cols = [c for c in ("Sector1Time","Sector2Time","Sector3Time") if c in laps_df.columns]
    if not sect_cols or laps_df.empty:
        return go.Figure()

    v = laps_df[laps_df["ValidLap"]].copy()
    if v.empty:
        return go.Figure()

    for col in sect_cols:
        v[f"_{col}_s"] = pd.to_numeric(v[col], errors="coerce")

    s_cols = [f"_{c}_s" for c in sect_cols]
    drv_order = (
        v.groupby("Driver_Short")["LapTime_s"].median()
        .sort_values().index.tolist()
    )

    # Best sector per driver
    best = (
        v.groupby("Driver_Short")[s_cols]
        .min().reindex(drv_order)
    )
    best.columns = [f"S{i+1}" for i in range(len(s_cols))]

    # Gap to best in sector (%)
    gap_pct = best.copy()
    for col in gap_pct.columns:
        leader = gap_pct[col].min()
        gap_pct[col] = ((gap_pct[col] - leader) / leader * 100).round(3)

    # Annotate with time strings
    text_annot = best.copy()
    for col in text_annot.columns:
        text_annot[col] = text_annot[col].apply(
            lambda v: f"{v:.3f}s" if pd.notna(v) else "—"
        )

    fig = go.Figure(go.Heatmap(
        z=gap_pct.values,
        x=list(gap_pct.columns),
        y=list(gap_pct.index),
        colorscale=[[0,"#2ECC71"],[0.5,"#F1C40F"],[1,"#E74C3C"]],
        zmin=0,
        text=text_annot.values,
        texttemplate="%{text}",
        textfont={"size": 9},
        hovertemplate="Driver: %{y}<br>Sector: %{x}<br>Best: %{text}<br>Gap: +%{z:.3f}%<extra></extra>",
        colorbar=dict(
            title=dict(text="% gap", font=dict(color=TEXT_MAIN)),
            tickfont=dict(color=TEXT_MAIN),
        ),
    ))
    h = max(300, len(drv_order) * 26 + 100)
    theme(fig, h, "Best Sector Time by Driver — % gap to sector leader")
    fig.update_layout(
        xaxis_title="Sector",
        margin=dict(l=80, r=80, t=60, b=40),
        yaxis=dict(autorange="reversed"),
    )
    return fig


# ── Tyre usage history chart ───────────────────────────────────
def _tyre_history_chart(laps_df: pd.DataFrame) -> go.Figure:
    v = laps_df[laps_df["ValidLap"] & laps_df["Compound"].notna()].copy()
    if v.empty:
        return go.Figure()

    usage = (
        v.groupby(["session_name", "Compound"])
        .agg(Laps=("LapTime_s","count"), AvgLapTime=("LapTime_s","median"))
        .reset_index()
    )

    fig = go.Figure()
    for cmp in COMPOUNDS:
        sub = usage[usage["Compound"] == cmp]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            x=sub["session_name"].apply(lambda s: s.split("_")[0]),
            y=sub["Laps"],
            name=cmp,
            marker_color=COMPOUND_COLORS.get(cmp, "#808080"),
            hovertemplate=f"{cmp}<br>Session: %{{x}}<br>Valid laps: %{{y}}<extra></extra>",
        ))

    theme(fig, 280, "Tyre Compound Usage — Valid Laps by Session")
    fig.update_layout(
        barmode="stack",
        xaxis_title="Session",
        yaxis_title="Laps",
        legend=dict(orientation="h", x=0, y=1.14, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=50, r=20, t=60, b=40),
    )
    return fig


# ── Main track tab layout builder ────────────────────────────
def tab_track_info() -> html.Div:
    if CIRCUIT_CHARS.empty:
        return html.Div([
            dbc.Alert(
                "Circuit characteristics data not found. "
                "Run write_circuit_characteristics.py and place the CSV in data/.",
                color="warning",
            )
        ])

    # Build dropdown options
    options = [
        {"label": row["grand_prix_fr"], "value": row["circuit_key"]}
        for _, row in CIRCUIT_CHARS.iterrows()
    ]
    default_key = CIRCUIT_CHARS["circuit_key"].iloc[0]

    # Historical year options
    avail_years = sorted(set(
        list(HIST_RACE["season"].unique() if "season" in HIST_RACE.columns else []) +
        list(HIST_QUALI["season"].unique() if "season" in HIST_QUALI.columns else [])
    ), reverse=True)
    year_opts = [{"label": str(y), "value": int(y)} for y in avail_years]

    return html.Div([
        # ── Selectors row ─────────────────────────────────────
        dbc.Row([
            dbc.Col([
                html.Label("Circuit", style={"color": TEXT_DIM, "fontSize": "0.72rem",
                                              "letterSpacing": "1px", "fontWeight": "600"}),
                dcc.Dropdown(
                    id="track-circuit-select",
                    options=options,
                    value=default_key,
                    clearable=False,
                    style={"backgroundColor": "#111", "fontSize": "0.85rem"},
                ),
            ], md=5),
            dbc.Col([
                html.Label("Historical Season", style={"color": TEXT_DIM, "fontSize": "0.72rem",
                                                        "letterSpacing": "1px", "fontWeight": "600"}),
                dcc.Dropdown(
                    id="track-year-select",
                    options=year_opts,
                    value=year_opts[0]["value"] if year_opts else None,
                    clearable=False,
                    style={"backgroundColor": "#111", "fontSize": "0.85rem"},
                ),
            ], md=3),
        ], className="mb-3"),

        # ── Dynamic content area ─────────────────────────────
        html.Div(id="track-content"),
    ])


# ── Track content callback ────────────────────────────────────
@app.callback(
    Output("track-content", "children"),
    Input("track-circuit-select", "value"),
    Input("track-year-select",    "value"),
)
def update_track_content(circuit_key: str, hist_year: int):
    if not circuit_key or CIRCUIT_CHARS.empty:
        return html.P("Select a circuit.", style={"color": TEXT_DIM})

    row = CIRCUIT_CHARS[CIRCUIT_CHARS["circuit_key"] == circuit_key]
    if row.empty:
        return html.P("Circuit not found.", style={"color": TEXT_DIM})
    row = row.iloc[0]

    meta = _FF1_CIRCUIT_META.get(circuit_key, {})
    corners_list = _NOTABLE_CORNERS.get(circuit_key, [])

    # ── Section 1: Header ─────────────────────────────────────
    header = html.Div([
        html.H3(row["grand_prix_fr"],
                style={"color": TEXT_MAIN, "fontWeight": "900", "letterSpacing": "2px",
                       "marginBottom": "2px", "fontSize": "1.15rem"}),
        html.Span(row["circuit_type_en"],
                  style={"color": ACCENT, "fontWeight": "700", "fontSize": "0.82rem",
                         "letterSpacing": "1px"}),
        html.Span(f"  ·  Overall demand: {row['overall_demand_score']}/4",
                  style={"color": TEXT_DIM, "fontSize": "0.78rem", "marginLeft": "8px"}),
    ], style={"marginBottom": "16px"})

    # ── Section 2: Stats pills row ────────────────────────────
    stats_pills = html.Div([
        _stat_pill("LENGTH",    f"{meta.get('length_km','—')} km"),
        _stat_pill("CORNERS",   str(meta.get("corners", "—"))),
        _stat_pill("DRS ZONES", str(meta.get("drs_zones", "—")), "#00D2BE"),
        _stat_pill("LAP RECORD",
                   f"{meta.get('lap_record','—')}  ({meta.get('lap_record_driver','—')}, {meta.get('lap_record_year','—')})",
                   "#FFD700"),
    ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"})

    # ── Section 3: Characteristics grid + radar ───────────────
    dims = [
        ("Average Speed",     row["avg_speed_label"],       row["avg_speed_score"]),
        ("Full Throttle",     row["full_throttle_label"],   row["full_throttle_score"]),
        ("Lateral Load",      row["lateral_load_label"],    row["lateral_load_score"]),
        ("Tyre Degradation",  row["tyre_deg_label"],        row["tyre_deg_score"]),
        ("Tyre Difficulty",   row["tyre_difficulty_label"], row["tyre_difficulty_score"]),
    ]
    chars_rows = [
        html.Div([
            html.Span(label, style={"color": TEXT_DIM, "fontSize": "0.75rem",
                                     "width": "160px", "display": "inline-block",
                                     "fontWeight": "600"}),
            _score_badge(val, score),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "8px"})
        for label, val, score in dims
    ]
    if row.get("notes"):
        chars_rows.append(html.P(
            f"Note: {row['notes']}",
            style={"color": TEXT_DIM, "fontSize": "0.7rem", "marginTop": "6px",
                   "fontStyle": "italic"},
        ))

    radar_fig = _radar_chart(row)

    chars_block = dbc.Row([
        dbc.Col([
            html.P("CIRCUIT CHARACTERISTICS",
                   style={"color": TEXT_DIM, "fontSize": "0.65rem", "letterSpacing": "2px",
                           "fontWeight": "700", "marginBottom": "12px"}),
            html.Div(chars_rows),
        ], md=6),
        dbc.Col([
            html.P("DEMAND PROFILE",
                   style={"color": TEXT_DIM, "fontSize": "0.65rem", "letterSpacing": "2px",
                           "fontWeight": "700", "marginBottom": "4px"}),
            dcc.Graph(figure=radar_fig, config=GFX),
        ], md=6),
    ])

    # ── Section 4: Notable corners ────────────────────────────
    if corners_list:
        corner_pills = html.Div(
            [html.Span(c, style={
                "background": CARD_BG, "border": f"1px solid {GRID_CLR}",
                "borderRadius": "4px", "padding": "3px 10px",
                "fontSize": "0.72rem", "marginRight": "6px",
                "marginBottom": "6px", "display": "inline-block",
                "color": TEXT_MAIN,
            }) for c in corners_list],
            style={"marginTop": "6px"},
        )
        corners_section = card(
            "Notable Corners",
            corner_pills,
        )
    else:
        corners_section = html.Div()

    # ── Section 5: Sector heatmap (current meeting data) ──────
    sector_fig = _sector_heatmap(laps)
    sector_section = card(
        "Sector Performance — Current Meeting (Best Sector Time, % gap to leader)",
        dcc.Graph(figure=sector_fig, config=GFX) if sector_fig.data else
        html.P("No sector time data available for the current session.",
               style={"color": TEXT_DIM}),
    )

    # ── Section 6: Tyre usage (current meeting) ───────────────
    tyre_fig = _tyre_history_chart(laps)
    tyre_section = card(
        "Tyre Compound Usage — Current Meeting",
        dcc.Graph(figure=tyre_fig, config=GFX) if tyre_fig.data else
        html.P("No compound data available.", style={"color": TEXT_DIM}),
    )

    # ── Section 7: Historical leaderboards ───────────────────
    hist_blocks = []
    if hist_year and not HIST_RACE.empty and not HIST_QUALI.empty:
        # Filter by circuit key
        def _filter_circuit(df):
            if df.empty or "circuit_key" not in df.columns:
                return pd.DataFrame()
            return df[df["circuit_key"] == circuit_key].copy()

        race_df  = _filter_circuit(HIST_RACE)
        quali_df = _filter_circuit(HIST_QUALI)

        avail_years_race  = sorted(race_df["season"].unique(), reverse=True)  if not race_df.empty  else []
        avail_years_quali = sorted(quali_df["season"].unique(), reverse=True) if not quali_df.empty else []

        for sess_type, df_h, avail_y in [
            ("Race",        race_df,  avail_years_race),
            ("Qualifying",  quali_df, avail_years_quali),
        ]:
            year_to_show = hist_year if hist_year in avail_y else (avail_y[0] if avail_y else None)
            if year_to_show is None:
                hist_blocks.append(card(
                    f"Historical {sess_type} Results",
                    html.P(f"No historical {sess_type.lower()} data for this circuit yet. "
                           "Run fetch_historical_results.py to populate.",
                           style={"color": TEXT_DIM, "fontStyle": "italic"}),
                ))
                continue

            tbl = _hist_table(df_h, sess_type, year_to_show)
            bar = _hist_leaderboard(df_h, sess_type, year_to_show)

            year_selector = dbc.Row([
                dbc.Col(
                    html.Div([
                        html.Span("Season: ", style={"color": TEXT_DIM, "fontSize": "0.72rem"}),
                        *[html.Span(
                            str(y),
                            style={
                                "color": ACCENT if y == year_to_show else TEXT_DIM,
                                "fontWeight": "700" if y == year_to_show else "400",
                                "fontSize": "0.78rem", "marginLeft": "8px",
                                "cursor": "default",
                                "borderBottom": f"2px solid {ACCENT}" if y == year_to_show else "none",
                            }
                        ) for y in avail_y],
                    ]),
                    md=12,
                ),
            ], className="mb-2")

            hist_blocks.append(card(
                f"Historical {sess_type} Results  —  {circuit_key.replace('_',' ').title()}  ({year_to_show})",
                html.Div([
                    year_selector,
                    dcc.Graph(figure=bar, config=GFX) if bar.data else html.Div(),
                    html.Div(style={"height": "8px"}),
                    tbl,
                ]),
            ))
    elif HIST_RACE.empty and HIST_QUALI.empty:
        hist_blocks.append(dbc.Alert(
            "Historical results not loaded. Run fetch_historical_results.py first.",
            color="secondary",
            style={"fontSize": "0.8rem"},
        ))

    # ── Assemble ──────────────────────────────────────────────
    return html.Div([
        header,
        stats_pills,
        card("Circuit Profile", chars_block),
        corners_section,
        sector_section,
        tyre_section,
        *hist_blocks,
    ])

if __name__=="__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)