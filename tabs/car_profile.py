"""CAR CONCEPT section (STINTS tab) — what kind of car each team has built.

The rest of the dashboard answers "which car is quicker". This answers *why*:
it decomposes the season into the physical traits that make lap time, so a
low-drag rocket, a downforce monster and a car that merely looks after its
tyres stop looking alike.

Reads data/car_profile.csv (scripts/compute_car_profile.py) for the measured
axes, the results archive for reliability, and data/pu_penalties.csv for
power-unit attrition. All of it is season-scoped — a car concept is not a
single-weekend quantity — with the loaded event marked so it is still worth
reading mid-weekend.

Honesty rules this section follows
----------------------------------
* Every axis was tested for split-half reliability across the season (average
  the odd rounds and the even rounds separately; do they agree?). Only axes
  that clear 0.6 are presented as season traits, and each one shows its score.
* Tyre degradation FAILED that test (0.17). It is real within a race and is
  charted per round here, but it is deliberately kept out of the concept
  matrix — see `_deg_card`.
* Nothing here claims to measure battery state. There is no such telemetry
  channel; what is measurable is top-end fade, and that is what it is called.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc

from f1lib.components import card, theme, GFX, abbr
from f1lib.glossary import gloss
from f1lib.config import (
    TEAM_COLORS, HISTORICAL_DIR, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR, CARD_BG,
)

PROFILE_PATH = Path("data/car_profile.csv")
FACILITIES_PATH = Path("data/facilities.csv")
PU_PATH = Path("data/pu_penalties.csv")
RACE_PATH = Path(HISTORICAL_DIR) / "race_results_all.parquet"

# 2026 power-unit element allowances (FIA Sporting Regs) — the same table the
# PU pool card uses. Total elements a driver may use before a grid penalty.
PU_ALLOWANCE = {"ice": 4, "tc": 4, "mguk": 3, "es": 3, "ce": 3, "ex": 4, "anc": 6}

# (column, label, unit, higher_is_better, split-half reliability, definition)
# reliability figures come from scripts/compute_car_profile.py's validation —
# see that module's docstring for the method.
AXES = [
    ("straight_kmh", "Straight-line", "km/h", True, 0.75,
     "Speed-trap reading on each driver's three quickest laps, team = both "
     "cars averaged, versus the field that weekend. The public proxy for "
     "engine plus low drag — but it is a SETUP choice as much as a car "
     "property, since teams trade wing level for straight-line speed circuit "
     "by circuit. Split-half reliability 0.75."),
    ("corner_pct", "Cornering", "%", True, 0.92,
     "Apex speed at every medium and fast corner on the best lap, each corner "
     "measured against the field's mean at THAT corner, then averaged. Higher "
     "= carries more speed through corners = more downforce (or more front-end "
     "confidence). The most reliable axis here (0.92) and by far the biggest "
     "single driver of lap time this season."),
    ("fade_pct", "Top-end fade", "%", False, 0.77,
     "Share of pinned-throttle samples where the car is DECELERATING — the "
     "signature of a car that has stopped pulling near the top of its range. "
     "Lower is better. This is NOT a battery reading: public telemetry has no "
     "state-of-charge channel, so it cannot separate 'out of deployment' from "
     "'hit its drag limit'. Split-half reliability 0.77."),
    ("deg_spl", "Tyre wear", "s/lap", False, 0.69,
     "How far the car's lap time drifts from the field's at the SAME tyre age, "
     "averaged over compounds and races (f1lib.processing.field_deg_curves). "
     "Negative = the tyre falls away more slowly than the field's, i.e. kinder "
     "to its rubber. Age-matched and compound-matched, so it is not just "
     "'who ran longer stints'. The least reliable axis of the five (0.69) — "
     "tyre behaviour moves with track temperature and compound more than the "
     "others do — so read a small difference here with more caution."),
    ("save_pct", "Energy saving", "pp", None, 0.98,
     "How much more the car coasts (off both pedals) in the race than in "
     "qualifying. Qualifying is the max-attack baseline, so the difference is "
     "deliberate lift-and-coast — fuel and energy management. Neither good nor "
     "bad on its own, which is why it is not colour-scored: it is a style. The "
     "steadiest axis here (0.98), and essentially uncorrelated with pace, so "
     "it is genuinely its own trait."),
]


# ── loaders ──────────────────────────────────────────────────

def profile_df() -> pd.DataFrame:
    if not PROFILE_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(PROFILE_PATH)
    except Exception:
        return pd.DataFrame()


def _pu_makers() -> dict[str, str]:
    if not FACILITIES_PATH.exists():
        return {}
    try:
        f = pd.read_csv(FACILITIES_PATH)
        return dict(zip(f["team"], f["pu_maker"]))
    except Exception:
        return {}


def _finish_rate(season: int) -> pd.DataFrame:
    """Finish rate and DNF count per team from the results archive.

    The cause split (mechanical vs incident) is NOT available for recent
    seasons — 2024 onward the archive carries a bare "Retired" — so this
    reports the rate only rather than inventing a breakdown.
    """
    if not RACE_PATH.exists():
        return pd.DataFrame()
    try:
        r = pd.read_parquet(RACE_PATH)
    except Exception:
        return pd.DataFrame()
    r = r[r["season"] == season]
    if r.empty:
        return pd.DataFrame()
    finished = {"Finished", "Lapped"} | {f"+{i} Lap" + ("s" if i > 1 else "")
                                         for i in range(1, 10)}
    r = r.copy()
    r["ok"] = r["Status"].isin(finished)
    g = r.groupby("TeamName").agg(starts=("ok", "size"), fin=("ok", "sum"))
    g["finish_pct"] = g["fin"] / g["starts"] * 100
    g["dnf"] = g["starts"] - g["fin"]
    return g


def _pu_usage(season: int) -> pd.DataFrame:
    """Mean share of the season's power-unit allowance already consumed."""
    if not PU_PATH.exists():
        return pd.DataFrame()
    try:
        p = pd.read_csv(PU_PATH)
    except Exception:
        return pd.DataFrame()
    p = p[p["season"] == season]
    if p.empty:
        return pd.DataFrame()
    cols = [c for c in PU_ALLOWANCE if c in p.columns]
    if not cols:
        return pd.DataFrame()
    used = p[cols].astype(float)
    limits = pd.Series({c: PU_ALLOWANCE[c] for c in cols})
    p = p.assign(pool_pct=(used / limits).mean(axis=1) * 100)
    return p.groupby("team")["pool_pct"].mean().to_frame()


# ── the concept matrix ───────────────────────────────────────

def _matrix_fig(S: pd.DataFrame, order: list[str], height: int) -> go.Figure:
    """Teams × axes, coloured by z-score within each axis so different units
    sit on one scale, with the real value printed in the cell."""
    cols = [c for c, *_ in AXES if c in S.columns]
    labels = {c: l for c, l, *_ in AXES}
    better = {c: b for c, _, _, b, *_ in AXES}
    units = {c: u for c, _, u, *_ in AXES}

    z, text, hover = [], [], []
    for team in order:
        zr, tr, hr = [], [], []
        for c in cols:
            v = S.loc[team, c] if team in S.index else np.nan
            col = S[c].dropna()
            sd = col.std()
            zs = (v - col.mean()) / sd if sd and np.isfinite(v) else 0.0
            if better[c] is False:
                zs = -zs                      # lower is better: flip the colour
            elif better[c] is None:
                zs = 0.0                      # a style, not a score — stay neutral
            zr.append(float(np.clip(zs, -2.2, 2.2)) if np.isfinite(zs) else 0.0)
            tr.append(f"{v:+.2f}" if np.isfinite(v) else "—")
            hr.append(f"<b>{team}</b><br>{labels[c]}: "
                      f"{v:+.2f} {units[c]} vs field"
                      if np.isfinite(v) else f"<b>{team}</b><br>{labels[c]}: no data")
        z.append(zr); text.append(tr); hover.append(hr)

    fig = go.Figure(go.Heatmap(
        z=z, x=[labels[c] for c in cols], y=[abbr(t) for t in order],
        text=text, texttemplate="%{text}",
        textfont=dict(size=11, family="Inter, sans-serif"),
        customdata=hover, hovertemplate="%{customdata}<extra></extra>",
        colorscale=[[0.0, "#8B2F33"], [0.25, "#5A2A30"], [0.5, CARD_BG],
                    [0.75, "#1F5A46"], [1.0, "#2E9E6B"]],
        zmid=0, zmin=-2.2, zmax=2.2, showscale=False, xgap=3, ygap=3,
    ))
    theme(fig, height)
    fig.update_xaxes(side="top", tickfont=dict(size=11, color=TEXT_MAIN),
                     showgrid=False)
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=11),
                     showgrid=False)
    fig.update_layout(margin=dict(l=60, r=20, t=60, b=20))
    return fig


def _reliability_fig(fin: pd.DataFrame, pu: pd.DataFrame,
                     order: list[str], height: int) -> go.Figure:
    fig = go.Figure()
    teams = [t for t in order if t in fin.index]
    fig.add_trace(go.Bar(
        y=[abbr(t) for t in teams], x=[fin.loc[t, "finish_pct"] for t in teams],
        orientation="h", name="Finish rate",
        marker=dict(color=[TEAM_COLORS.get(t, "#808080") for t in teams]),
        text=[f"{fin.loc[t, 'finish_pct']:.0f}%  ({int(fin.loc[t, 'dnf'])} DNF)"
              for t in teams],
        textposition="outside", textfont=dict(size=10),
        customdata=[[int(fin.loc[t, "starts"]), int(fin.loc[t, "dnf"])] for t in teams],
        hovertemplate=("<b>%{y}</b><br>Finish rate: %{x:.1f}%<br>"
                       "%{customdata[0]} starts · %{customdata[1]} DNF"
                       "<extra></extra>"),
    ))
    theme(fig, height)
    fig.update_xaxes(title_text="Race finish rate (%)", range=[0, 118])
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=10))
    fig.update_layout(showlegend=False, margin=dict(l=60, r=90, t=30, b=45),
                      bargap=0.3)
    return fig


def _engine_fig(S: pd.DataFrame, makers: dict, height: int) -> go.Figure:
    """Straight-line speed split into the engine everyone on that PU shares and
    the team's own deviation from it (drag / wing choice)."""
    d = S[["straight_kmh"]].copy()
    d["pu"] = [makers.get(t, "?") for t in d.index]
    eng = d.groupby("pu")["straight_kmh"].agg(["mean", "count"])
    d["engine"] = d["pu"].map(eng["mean"])
    d["chassis"] = d["straight_kmh"] - d["engine"]
    d["n_pu"] = d["pu"].map(eng["count"])
    d = d.sort_values("straight_kmh", ascending=True)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=[abbr(t) for t in d.index], x=d["engine"], orientation="h",
        name="Engine (shared by everyone on this PU)",
        marker=dict(color="#5B8DEF"),
        customdata=np.stack([d["pu"], d["n_pu"]], axis=-1),
        hovertemplate=("<b>%{y}</b><br>%{customdata[0]}<br>"
                       "Engine share: %{x:+.2f} km/h "
                       "(%{customdata[1]} team(s) on this PU)<extra></extra>"),
    ))
    fig.add_trace(go.Bar(
        y=[abbr(t) for t in d.index], x=d["chassis"], orientation="h",
        name="Chassis / wing level (this team's own deviation)",
        marker=dict(color="#E8A33D"),
        customdata=np.stack([d["pu"], d["n_pu"]], axis=-1),
        hovertemplate=("<b>%{y}</b><br>Own deviation from %{customdata[0]}: "
                       "%{x:+.2f} km/h<extra></extra>"),
    ))
    theme(fig, height)
    fig.add_vline(x=0, line=dict(color=TEXT_DIM, width=1))
    fig.update_xaxes(title_text="Straight-line speed vs field (km/h) · "
                                "engine + chassis = the team's total")
    fig.update_yaxes(tickfont=dict(size=10))
    fig.update_layout(barmode="relative", bargap=0.28,
                      margin=dict(l=60, r=30, t=30, b=50),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0, font=dict(size=10)))
    return fig


def _payoff_fig(P: pd.DataFrame, season: int, height: int) -> go.Figure | None:
    """How strongly each trait actually tracks pace this season — i.e. which
    part of the car is buying lap time in these regulations."""
    from tabs.pace_data import team_pace_df
    tp = team_pace_df()
    if tp.empty:
        return None
    tp = tp[tp["season"] == season][["round", "team", "quali_pace_pct",
                                     "race_pace_pct"]]
    J = P.merge(tp, on=["round", "team"], how="inner")
    if len(J) < 30:
        return None
    rows = []
    for c, label, _u, better, _rel, _d in AXES:
        if c not in J.columns or better is None:
            continue          # a style axis has no strong end to test
        for tgt, tname in (("quali_pace_pct", "One-lap"),
                           ("race_pace_pct", "Race")):
            s = J[[c, tgt]].dropna()
            if len(s) < 25:
                continue
            r = float(np.corrcoef(s[c], s[tgt])[0, 1])
            # Orient the bar by the axis's OWN good direction, so this chart
            # and the matrix's colours can never disagree. Pace is
            # negative-is-faster, so for a higher-is-better axis the bar is -r
            # and for a lower-is-better axis it is +r. A bar that comes out
            # NEGATIVE is the interesting case: it says the end the matrix
            # paints green does not actually travel with a quicker car.
            rows.append({"axis": label, "target": tname,
                         "gain": -r if better else r, "n": len(s)})
    if not rows:
        return None
    D = pd.DataFrame(rows)
    fig = go.Figure()
    for tname, clr in (("One-lap", "#FF8A3D"), ("Race", "#3DD6C4")):
        sub = D[D["target"] == tname]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            x=sub["axis"], y=sub["gain"], name=tname,
            marker=dict(color=clr),
            customdata=sub["n"],
            hovertemplate=("<b>%{x}</b> · " + tname + " pace<br>"
                           "correlation %{y:+.2f} (n=%{customdata})"
                           "<extra></extra>"),
        ))
    theme(fig, height)
    fig.add_hline(y=0, line=dict(color=TEXT_DIM, width=1))
    fig.update_yaxes(title_text="does the strong end of this axis go with a "
                                "faster car? · below zero = no",
                     range=[-0.45, 0.9])
    fig.update_layout(barmode="group", bargap=0.35,
                      margin=dict(l=60, r=20, t=40, b=50),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0, font=dict(size=10)))
    return fig


def _deg_fig(P: pd.DataFrame, order: list[str], height: int) -> go.Figure:
    """Tyre degradation round by round — deliberately NOT averaged."""
    fig = go.Figure()
    rounds = sorted(P["round"].dropna().unique())
    ev = (P.drop_duplicates("round").set_index("round")["event"]
          .str.replace(" Grand Prix", "", regex=False))
    for team in order:
        g = P[P["team"] == team].sort_values("round")
        if g["deg_spl"].notna().sum() == 0:
            continue
        g = g.set_index("round").reindex(rounds).reset_index()
        fig.add_trace(go.Scatter(
            x=rounds, y=g["deg_spl"], mode="lines+markers", name=abbr(team),
            line=dict(color=TEAM_COLORS.get(team, "#808080"), width=1.8),
            marker=dict(size=5), connectgaps=False,
            customdata=[ev.get(r, "") for r in rounds],
            hovertemplate=(f"<b>{abbr(team)}</b> · %{{customdata}}<br>"
                           "vs field at equal tyre age: %{y:+.2f} s/lap"
                           "<extra></extra>"),
        ))
    theme(fig, height)
    fig.add_hline(y=0, line=dict(color=TEXT_DIM, width=1, dash="dot"))
    fig.update_xaxes(tickmode="array", tickvals=rounds,
                     ticktext=[ev.get(r, str(int(r))) for r in rounds],
                     tickangle=-40)
    fig.update_yaxes(title_text="s/lap vs field at equal tyre age · "
                                "lower = kinder to its tyres")
    fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0, font=dict(size=10)))
    return fig


# ── assembly ─────────────────────────────────────────────────

def _axis_legend() -> html.Div:
    """A compact key: what each axis is, and how much to trust it."""
    rows = []
    for _c, label, unit, better, rel, definition in AXES:
        arrow = ("higher = better" if better is True else
                 "lower = better" if better is False else "style, not a score")
        rows.append(html.Div([
            html.Span(label, style={"color": TEXT_MAIN, "fontWeight": "700",
                                    "fontSize": "0.76rem"}),
            html.Span(f"  ({unit}, {arrow})",
                      style={"color": TEXT_DIM, "fontSize": "0.7rem"}),
            html.Span(f"  reliability {rel:.2f}",
                      style={"color": ACCENT, "fontSize": "0.68rem",
                             "fontWeight": "700", "marginLeft": "6px"}),
            html.Div(definition, style={"color": TEXT_DIM, "fontSize": "0.72rem",
                                        "lineHeight": "1.45",
                                        "marginTop": "2px"}),
        ], style={"marginBottom": "9px"}))
    return html.Div(rows, style={"borderLeft": f"2px solid {GRID_CLR}",
                                 "paddingLeft": "12px", "marginTop": "10px"})


def car_concept_section(season: int | None = None,
                        loaded_event: str | None = None) -> html.Div:
    """The whole CAR CONCEPT block: concept matrix, engine/chassis split,
    what-pays analysis, reliability, and the honest tyre-deg treatment."""
    P = profile_df()
    if P.empty:
        return html.Div(card(
            "Car Concept",
            html.P(["No car-profile table yet — build it with ",
                    html.Code("python scripts/compute_car_profile.py"), "."],
                   style={"color": TEXT_DIM, "fontSize": "0.82rem"}),
            info="Needs data/car_profile.csv (scripts/compute_car_profile.py), "
                 "which reads the cached qualifying and race telemetry."))
    if season is None:
        season = int(P["season"].max())
    P = P[P["season"] == season].copy()
    if P.empty:
        return html.Div()

    axis_cols = [c for c, *_ in AXES if c in P.columns]
    S = P.groupby("team")[axis_cols].mean()
    n_ev = int(P["round"].nunique())

    try:
        from f1lib.standings import _order_teams_by_champ
        order = [t for t in _order_teams_by_champ(list(S.index)) if t in S.index]
    except Exception:
        order = list(S.sort_values("corner_pct", ascending=False).index) \
            if "corner_pct" in S.columns else list(S.index)

    fin = _finish_rate(season)
    pu = _pu_usage(season)
    makers = _pu_makers()

    parts: list = []

    # 1 — the matrix
    parts.append(card(
        ["Car Concept — what kind of car is this?"],
        html.Div([
            html.P(f"Season {season} · {n_ev} events · every value is versus the "
                   "field that weekend, then averaged.",
                   style={"color": TEXT_DIM, "fontSize": "0.76rem",
                          "marginBottom": "6px"}),
            dcc.Graph(figure=_matrix_fig(S, order, max(300, 34 * len(order) + 130)),
                      config=GFX),
            _axis_legend(),
        ]),
        info=("Data: data/car_profile.csv (scripts/compute_car_profile.py), "
              "built from the cached qualifying and race telemetry of every "
              "event this season. Each axis is centred on the field that "
              "weekend — otherwise the circuit swamps the car, since a Monza "
              "speed trap reads 340 km/h and a Monaco one 290 — then averaged "
              "over the season. Cell colour is the z-score within that column "
              "(green = the strong end), the number is the real value. "
              "'Reliability' next to each axis is its split-half score: the "
              "odd rounds and the even rounds were averaged separately and "
              "correlated, so 0.92 means the season number is a genuine car "
              "measurement rather than noise. Why: lap time is an outcome; "
              "this is the anatomy behind it, and it is what tells you whether "
              "a quick car is quick because of its engine, its downforce, or "
              "how it is being driven."),
        plain=["Each row is a team, each column one thing a car can be good at. "
               "Green means strong, red means weak. A car can be green in one "
               "column and red in the next — that is the whole point: being "
               "fast down the straight and being fast through corners are "
               "different talents, and most cars trade one for the other."],
    ))

    # 2 — engine vs chassis
    if makers and "straight_kmh" in S.columns:
        parts.append(card(
            "Engine or Chassis? — splitting the straight-line number",
            dcc.Graph(figure=_engine_fig(S, makers, max(300, 30 * len(S) + 140)),
                      config=GFX),
            measure="one-lap",
            info=("Data: the straight-line axis above, split into the average "
                  "of every team running that power unit (the engine's "
                  "contribution, blue) and each team's own deviation from its "
                  "engine-mates (its drag level and wing choice, orange). PU "
                  "supplier mapping from data/facilities.csv. Why: a slow "
                  "speed trap can mean a down-on-power engine or a team simply "
                  "choosing more wing, and those call for completely different "
                  "conclusions — this separates them. Caveat: the split only "
                  "works where a supplier has several customers. Honda and "
                  "Audi each power one team this season, so for those the "
                  "chassis bar is zero by construction, not by measurement."),
        ))

    # 3 — what actually pays
    pay = _payoff_fig(P, season, 340)
    if pay is not None:
        parts.append(card(
            "What's Buying Lap Time in " + str(season),
            dcc.Graph(figure=pay, config=GFX),
            info=("Data: the correlation between each trait and the team's "
                  "session-normalised pace, pooled over every team and event "
                  "of the season, oriented so a positive bar means 'the end "
                  "the matrix paints green really does go with a faster car'. "
                  "Energy saving is left out — it is a style with no good end "
                  "to test. Why: it says which part of the car these "
                  "regulations actually reward, and cornering dominating "
                  "everything else is the single most useful fact on this "
                  "page. Read a NEGATIVE bar as a warning about that axis "
                  "rather than about the cars: top-end fade goes slightly the "
                  "'wrong' way because the quickest cars run the most "
                  "downforce and therefore hit their drag limit soonest, "
                  "which is exactly the confound its own definition warns "
                  "about. Caveat: 11 teams over 11 events — this says the "
                  "trait travels with pace, not that bolting it onto a given "
                  "car would make it quicker."),
        ))

    # 4 — reliability
    if not fin.empty:
        fin = fin.reindex([t for t in order if t in fin.index])
        body = [dcc.Graph(figure=_reliability_fig(fin, pu, list(fin.index),
                                                  max(280, 28 * len(fin) + 120)),
                          config=GFX)]
        if not pu.empty:
            worst = pu["pool_pct"].sort_values(ascending=False).head(3)
            body.append(html.Div(
                ["Power-unit pool used so far — ",
                 ", ".join(f"{t} {v:.0f}%" for t, v in worst.items()),
                 ". A team burning through elements is carrying a reliability "
                 "problem even when the cars keep finishing."],
                style={"color": TEXT_DIM, "fontSize": "0.75rem",
                       "marginTop": "8px"}))
        parts.append(card(
            "Reliability — did it get to the flag?",
            html.Div(body),
            info=("Data: every car-race in the results archive this season, "
                  "counted as classified finish vs retirement, plus the "
                  "power-unit pool from data/pu_penalties.csv. Why: the "
                  "cheapest lap time in F1 is the lap you actually complete — "
                  "a fast car that retires scores the same as a slow one. "
                  "Caveat: from 2024 the archive records a bare 'Retired' with "
                  "no cause, so this is a rate only — the mechanical-vs-"
                  "incident split older seasons allow is genuinely not in the "
                  "data, and is not guessed at here."),
        ))

    # 5 — the axis that failed, shown honestly
    if "deg_spl" in P.columns and P["deg_spl"].notna().any():
        parts.append(_deg_card(P, order))

    return html.Div(parts)


def _deg_card(P: pd.DataFrame, order: list[str]) -> html.Div:
    return card(
        [*gloss("degradation", "Tyre Wear"), " — round by round"],
        html.Div([
            html.Div([
                html.Span("Read this one more carefully than the others  ",
                          style={"color": ACCENT, "fontWeight": "700",
                                 "fontSize": "0.72rem",
                                 "letterSpacing": "0.5px"}),
                html.Span(
                    "Tyre wear is the least stable of the five axes (0.69 "
                    "against cornering's 0.92), because it moves with track "
                    "temperature and compound choice as well as with the car. "
                    "The season average in the matrix above is real, but a "
                    "small gap between two teams there is worth less than the "
                    "same gap in another column — so here is the same measure "
                    "round by round, which shows how much it actually swings. "
                    "A team whose line sits consistently on one side of zero "
                    "has a genuine tyre characteristic; one that criss-crosses "
                    "is being told what to do by the circuit.",
                    style={"color": TEXT_DIM, "fontSize": "0.76rem",
                           "lineHeight": "1.5"}),
            ], style={"borderLeft": f"3px solid {ACCENT}", "background": "#0E0E1F",
                      "padding": "10px 12px", "marginBottom": "12px",
                      "borderRadius": "4px"}),
            dcc.Graph(figure=_deg_fig(P, order, 460), config=GFX),
        ]),
        measure="stint",
        info=("Data: each team's mean deviation from the pooled field "
              "degradation curve at equal tyre age, per race, averaged over "
              "compounds (f1lib.processing.field_deg_curves). Negative = the "
              "tyre falls away more slowly than the field's. Rounds without "
              "enough clean stints break the line rather than interpolate. "
              "Why: the season number tells you what kind of car it is; this "
              "tells you how reliably that holds, and which weekends went "
              "against type. Note the underlying laps have perturbed and "
              "dirty-air laps removed before the fit — including safety-car "
              "laps destroys this measurement entirely."),
    )
