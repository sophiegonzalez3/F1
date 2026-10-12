"""Car-profile cards — what kind of car each team has built, and where it
stopped behaving like itself.

The rest of the dashboard answers "which car is quicker". This answers *why*:
it decomposes the season into the physical traits that make lap time, so a
low-drag rocket, a downforce monster and a car that merely looks after its
tyres stop looking alike.

Reads data/car_profile.csv (scripts/compute_car_profile.py), one row per team
per round, every axis centred on the field that weekend. Split by the
dashboard's rule — season context on SEASON, event deviations on STINTS:

* SEASON  `car_traits_card`  top-end fade / tyre wear / energy saving averaged
          over the season (straight-line + cornering are NOT repeated: Car
          Character covers them pace-adjusted, the Engine Championship carries
          the straight-line engine/chassis split);
          `deg_rounds_card`  tyre wear round by round;
          `payoff_note`      "what's buying lap time", a line on Car Character.
* STINTS  `weekend_vs_season_card`  the loaded event against each team's OWN
          season norm, highlighting only deviations beyond round-to-round noise.

Honesty rules
-------------
* Every axis was tested for split-half reliability across the season (average
  the odd rounds and the even rounds separately; do they agree?) and shows its
  score. Tyre wear is the shakiest, hence the round-by-round card.
* Nothing here claims to measure battery state. There is no such telemetry
  channel; what is measurable is top-end fade, and that is what it is called.

The sidebar TEAMS filter chooses which teams are DRAWN; every statistic behind
them (z-scores, the noise σ, the field reference in the deg chart) stays
computed on the whole grid. Recomputing a "versus the field" number on three
teams would silently redefine the field.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc

from f1lib.components import card, theme, GFX, abbr
from f1lib.glossary import gloss
from f1lib.pace_features import canon
from f1lib.config import (
    team_color, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR, CARD_BG,
)

PROFILE_PATH = Path("data/car_profile.csv")

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
     "deliberate lift-and-coast — fuel and energy management. Deliberately NOT "
     "colour-scored, and that decision is now measured rather than asserted: "
     "coasting more is not associated with being slower, in the field "
     "(r=+0.01), within an event (r=+0.01) or within a team over the season "
     "(r=−0.00, n=752) — so calling it an 'energy deficit' and marking it red "
     "would be reading a cost the data does not show. Two other readings were "
     "tested and can be set aside: it is NOT a traffic artifact (r=+0.05 "
     "against median finishing position, p=0.20) and it is uncorrelated with "
     "every other axis here. About 23% of it tracks the PU SUPPLIER rather "
     "than the team — Ford-powered cars coast markedly more than the rest in "
     "2026 — so read it partly as the manufacturer's energy-management map, "
     "which is also why it is the steadiest axis (0.98): a supplier map "
     "barely changes between events."),
]


# ── loaders ──────────────────────────────────────────────────

def profile_df() -> pd.DataFrame:
    if not PROFILE_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(PROFILE_PATH)
    except Exception:
        return pd.DataFrame()


# ── the concept matrix ───────────────────────────────────────

def _matrix_fig(S: pd.DataFrame, order: list[str], height: int,
                cols: tuple[str, ...] | None = None) -> go.Figure:
    """Teams × axes, coloured by z-score within each axis so different units
    sit on one scale, with the real value printed in the cell."""
    cols = [c for c, *_ in AXES if c in S.columns and (cols is None or c in cols)]
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


def _payoff_rows(season: int) -> pd.DataFrame:
    """How strongly each trait tracks pace this season — i.e. which part of the
    car is buying lap time in these regulations. One row per axis × target."""
    from tabs.pace_data import team_pace_df
    P = profile_df()
    tp = team_pace_df()
    if P.empty or tp.empty:
        return pd.DataFrame()
    P = P[P["season"] == season]
    tp = tp[tp["season"] == season][["round", "team", "onelap_speed_pct",
                                     "race_pace_pct"]]
    J = P.merge(tp, on=["round", "team"], how="inner")
    if len(J) < 30:
        return pd.DataFrame()
    rows = []
    for c, label, _u, better, _rel, _d in AXES:
        if c not in J.columns or better is None:
            continue          # a style axis has no strong end to test
        for tgt, tname in (("onelap_speed_pct", "One-lap"),
                           ("race_pace_pct", "Race")):
            s = J[[c, tgt]].dropna()
            if len(s) < 25:
                continue
            r = float(np.corrcoef(s[c], s[tgt])[0, 1])
            # Oriented by the axis's OWN good direction (pace is
            # negative-is-faster): positive = the strong end really does
            # travel with a quicker car, negative = it does not.
            rows.append({"axis": label, "target": tname,
                         "gain": -r if better else r, "n": len(s)})
    return pd.DataFrame(rows)


def payoff_note(season: int) -> html.P | None:
    """'What's buying lap time' as one line — the evidence behind Car
    Character's decision to pace-adjust, so it rides on that card rather than
    being a card of its own."""
    D = _payoff_rows(season)
    if D.empty:
        return None
    W = D.pivot(index="axis", columns="target", values="gain")
    if "One-lap" not in W:
        return None
    W = W.sort_values("One-lap", ascending=False)
    n = int(D["n"].max())
    bits = []
    for axis, row in W.iterrows():
        race = (f" / {row['Race']:+.2f} race"
                if "Race" in W and pd.notna(row.get("Race")) else "")
        bits.append(f"{axis.lower()} {row['One-lap']:+.2f} one-lap{race}")
    return html.P(
        [html.B(f"What's buying lap time in {season}. "),
         "Correlation of each raw trait with pace, pooled over every team and "
         f"round (n≈{n}; positive = the strong end goes with a faster car): ",
         "; ".join(bits), ". Cornering is the pace — which is why the cells "
         "above are pace-adjusted. A negative top-end-fade figure is the "
         "confound, not a finding: the quickest cars run the most downforce "
         "and hit their drag limit soonest."],
        style={"color": TEXT_DIM, "fontSize": "0.74rem", "marginTop": "6px",
               "marginBottom": 0})


def _deg_fig(P: pd.DataFrame, order: list[str], height: int,
             season=None) -> go.Figure:
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
            line=dict(color=team_color(team, season), width=1.8),
            marker=dict(size=5), connectgaps=False,
            customdata=[ev.get(r, "") for r in rounds],
            hovertemplate=(f"<b>{abbr(team)}</b> · %{{customdata}}<br>"
                           "vs field at equal tyre age: %{y:>+.2f} s/lap"
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

# Straight-line and cornering are NOT in the SEASON traits matrix: Car
# Character covers them pace-adjusted (top speed, low-speed cornering), and the
# Engine Championship carries the straight-line engine/chassis split. These are
# the three axes nothing else on SEASON measures.
TRAIT_COLS = ("fade_pct", "deg_spl", "save_pct")


def _axis_legend(cols: tuple[str, ...] | None = None) -> html.Div:
    """A compact key: what each axis is, and how much to trust it."""
    rows = []
    for c, label, unit, better, rel, definition in AXES:
        if cols is not None and c not in cols:
            continue
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


def _scope(season: int | None, teams: list[str] | None):
    """(season, P, S, order, shown) for one season of car_profile.csv, or None.

    `teams` is the sidebar TEAMS filter: it picks which rows are DRAWN (`shown`);
    P / S / order stay full-grid so every "versus the field" number keeps its
    meaning. A filter matching nothing falls back to the whole field.
    """
    P = profile_df()
    if P.empty:
        return None
    if season is None:
        season = int(P["season"].max())
    P = P[P["season"] == season].copy()
    if P.empty:
        return None
    S = P.groupby("team")[[c for c, *_ in AXES if c in P.columns]].mean()
    try:
        from f1lib.standings import _order_teams_by_champ
        order = [t for t in _order_teams_by_champ(list(S.index)) if t in S.index]
    except Exception:
        order = list(S.index)
    sel = {canon(t) for t in teams} if teams else None
    shown = [t for t in order if canon(t) in sel] if sel is not None else order
    return season, P, S, order, (shown or order)


def _filter_note(shown: list, order: list):
    if len(shown) >= len(order):
        return ""
    return html.Span(f"  ·  showing {len(shown)} of {len(order)} teams "
                     "(sidebar filter) — all comparisons remain against "
                     "the full grid", style={"color": ACCENT})


def car_traits_card(season: int, teams: list[str] | None = None):
    """SEASON card: the car-concept axes Car Character does not already cover."""
    sc = _scope(season, teams)
    if sc is None:
        return None
    season, P, S, order, shown = sc
    cols = tuple(c for c in TRAIT_COLS if c in S.columns)
    if not cols:
        return None
    return card(
        "Car Traits — Top-End Fade · Tyre Wear · Energy Saving",
        html.Div([
            html.P([f"Season {season} · {P['round'].nunique()} events · every "
                    "value is versus the field that weekend, then averaged. "
                    "Straight-line speed and cornering are on Car Character "
                    "(pace-adjusted) and the Engine Championship.",
                    _filter_note(shown, order)],
                   style={"color": TEXT_DIM, "fontSize": "0.76rem",
                          "marginBottom": "6px"}),
            dcc.Graph(figure=_matrix_fig(S, shown, max(300, 34 * len(shown) + 130),
                                         cols=cols),
                      config=GFX),
            _axis_legend(cols),
        ]),
        # top-end fade comes off the best qualifying lap; tyre wear and energy
        # saving off race running — both chips, so the header never implies
        # the whole row was measured the same way
        measure=("one-lap", "stint"),
        info=("Data: data/car_profile.csv (scripts/compute_car_profile.py), "
              "built from the cached qualifying and race telemetry of every "
              "event this season. Each axis is centred on the field that "
              "weekend — otherwise the circuit swamps the car — then averaged "
              "over the season. Cell colour is the z-score within that column "
              "(green = the strong end; energy saving is a style and stays "
              "neutral), the number is the real value. 'Reliability' next to "
              "each axis is its split-half score: odd and even rounds averaged "
              "separately and correlated. The sidebar TEAMS filter chooses "
              "which rows are drawn; the z-scores are always computed on the "
              "full grid. Why: these are the parts of a car's character that "
              "neither lap pace nor the phase-based Car Character card can see "
              "— how it holds speed at the top end, how it treats its tyres, "
              "and how hard it is being managed in the race."),
        plain=["Each row is a team, each column a trait. Green means strong, "
               "red means weak; energy saving is grey because coasting more is "
               "a choice, not a weakness."],
    )


def deg_rounds_card(season: int, teams: list[str] | None = None):
    """SEASON card: tyre wear round by round (deliberately not averaged)."""
    sc = _scope(season, teams)
    if sc is None:
        return None
    season, P, _S, _order, shown = sc
    if "deg_spl" not in P.columns or not P["deg_spl"].notna().any():
        return None
    return _deg_card(P, shown, season)


def _deg_card(P: pd.DataFrame, order: list[str], season=None) -> html.Div:
    return card(
        [*gloss("degradation", "Tyre Wear"), " — round by round"],
        html.Div([
            html.Div([
                html.Span("Read this one more carefully than the others  ",
                          style={"color": ACCENT, "fontWeight": "700",
                                 "fontSize": "0.72rem",
                                 "letterSpacing": "0.5px"}),
                html.Span(
                    "Tyre wear is the least stable of the car-profile axes "
                    "(0.69 against cornering's 0.92), because it moves with "
                    "track temperature and compound choice as well as with the "
                    "car. The season average in Car Traits is real, but a small "
                    "gap between two teams there is worth less than the same "
                    "gap in another column — so here is the same measure round "
                    "by round, which shows how much it actually swings. A team "
                    "whose line sits consistently on one side of zero has a "
                    "genuine tyre characteristic; one that criss-crosses is "
                    "being told what to do by the circuit.",
                    style={"color": TEXT_DIM, "fontSize": "0.76rem",
                           "lineHeight": "1.5"}),
            ], style={"borderLeft": f"3px solid {ACCENT}", "background": "#0E0E1F",
                      "padding": "10px 12px", "marginBottom": "12px",
                      "borderRadius": "4px"}),
            dcc.Graph(figure=_deg_fig(P, order, 460, season), config=GFX),
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


# ── STINTS: this weekend against the season ──────────────────

# A deviation counts as notable at this many noise SDs. The noise is the pooled
# round-to-round scatter of each team around its own season mean, so 2 means
# "a weekend this far off a team's norm happens ~1 in 20 by chance".
NOTABLE_Z = 2.0
_MIN_OTHER_ROUNDS = 4


def _weekend_deviation(P: pd.DataFrame, rnd: int) -> pd.DataFrame:
    """One row per team × axis: this round's value, the team's norm over the
    OTHER rounds, the deviation and its z against the pooled within-team noise."""
    cur = P[P["round"] == rnd].set_index("team")
    oth = P[P["round"] != rnd]
    rows = []
    for c, label, unit, better, _rel, _d in AXES:
        if c not in P.columns:
            continue
        o = oth[["team", c]].dropna()
        if o.empty:
            continue
        g = o.groupby("team")[c]
        dof = len(o) - g.ngroups
        if dof < 5:
            continue
        resid = o[c] - g.transform("mean")
        sd = float(np.sqrt((resid ** 2).sum() / dof))
        norm, n = g.mean(), g.size()
        for team, v in cur[c].dropna().items():
            if team not in norm.index or n[team] < _MIN_OTHER_ROUNDS or not sd:
                continue
            dev = float(v - norm[team])
            # a new observation against a mean of n: variance sd²(1 + 1/n)
            z = dev / (sd * np.sqrt(1 + 1 / n[team]))
            rows.append({"team": team, "col": c, "axis": label, "unit": unit,
                         "better": better, "value": float(v),
                         "norm": float(norm[team]), "dev": dev, "z": float(z),
                         "n": int(n[team])})
    return pd.DataFrame(rows)


def _weekend_fig(D: pd.DataFrame, shown: list[str]) -> go.Figure:
    cols = [c for c, *_ in AXES if c in set(D["col"])]
    labels = {c: l for c, l, *_ in AXES}
    W = {(r.team, r.col): r for r in D.itertuples()}
    z, text, hover = [], [], []
    for team in shown:
        zr, tr, hr = [], [], []
        for c in cols:
            r = W.get((team, c))
            if r is None:
                zr.append(0.0); tr.append("—")
                hr.append(f"<b>{team}</b><br>{labels[c]}: no data")
                continue
            # colour = better / worse than its OWN norm; energy saving is a
            # style, so it stays neutral and only the number speaks
            zs = 0.0 if r.better is None else (r.z if r.better else -r.z)
            notable = abs(r.z) >= NOTABLE_Z
            if not notable:
                zs *= 0.25                                 # inside the noise
            zr.append(float(np.clip(zs, -3.5, 3.5)))
            tr.append(f"{r.dev:+.2f}" + (" ●" if notable else ""))
            hr.append(f"<b>{team}</b> · {labels[c]}<br>"
                      f"this weekend {r.value:+.2f} {r.unit} vs field<br>"
                      f"season norm {r.norm:+.2f} ({r.n} other rounds)<br>"
                      f"deviation {r.dev:+.2f} {r.unit} = {r.z:+.1f}σ")
        z.append(zr); text.append(tr); hover.append(hr)
    fig = go.Figure(go.Heatmap(
        z=z, x=[labels[c] for c in cols], y=[abbr(t) for t in shown],
        text=text, texttemplate="%{text}",
        textfont=dict(size=11, family="Inter, sans-serif"),
        customdata=hover, hovertemplate="%{customdata}<extra></extra>",
        colorscale=[[0.0, "#8B2F33"], [0.25, "#5A2A30"], [0.5, CARD_BG],
                    [0.75, "#1F5A46"], [1.0, "#2E9E6B"]],
        zmid=0, zmin=-3.5, zmax=3.5, showscale=False, xgap=3, ygap=3,
    ))
    theme(fig, max(300, 34 * len(shown) + 130))
    fig.update_xaxes(side="top", tickfont=dict(size=11, color=TEXT_MAIN),
                     showgrid=False)
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=11),
                     showgrid=False)
    fig.update_layout(margin=dict(l=60, r=20, t=60, b=20))
    return fig


def _weekend_plain(D: pd.DataFrame, shown: list[str], event: str) -> str:
    hit = D[(D["z"].abs() >= NOTABLE_Z) & D["team"].isin(shown)]
    if hit.empty:
        return (f"No team moved outside its normal round-to-round range at "
                f"{event} — every car drove to its season character.")
    hit = hit.reindex(hit["z"].abs().sort_values(ascending=False).index)
    bits = []
    for r in hit.head(6).itertuples():
        if r.better is None:
            word = "more" if r.dev > 0 else "less"
            bits.append(f"{abbr(r.team)} coasted {word} than usual "
                        f"({r.dev:+.2f} {r.unit}, {r.z:+.1f}σ)")
        else:
            good = (r.dev > 0) == bool(r.better)
            bits.append(f"{abbr(r.team)} {r.axis.lower()} "
                        f"{'better' if good else 'worse'} than its norm "
                        f"({r.dev:+.2f} {r.unit}, {abs(r.z):.1f}σ)")
    more = f" — and {len(hit) - 6} more" if len(hit) > 6 else ""
    return f"Broke character at {event}: " + "; ".join(bits) + more + "."


def weekend_vs_season_card(season: int | None, event: str | None,
                           teams: list[str] | None = None):
    """STINTS card: where each car departed from its OWN season norm this
    weekend. Only deviations beyond the round-to-round noise are highlighted —
    the season averages themselves live on the SEASON tab."""
    if season is None or not event:
        return None
    sc = _scope(season, teams)
    if sc is None:
        return None
    season, P, _S, order, shown = sc
    title = "This Weekend vs the Season — who broke character?"
    rounds = P.loc[P["event"] == event, "round"]
    if rounds.empty:
        return card(title, html.P(
            ["No car-profile row for ", html.B(event), " yet — rebuild it with ",
             html.Code("python scripts/compute_car_profile.py"),
             " once the race telemetry is cached."],
            style={"color": TEXT_DIM, "fontSize": "0.8rem"}))
    D = _weekend_deviation(P, int(rounds.max()))
    if D.empty:
        return card(title, html.P(
            "Too few other rounds this season to know what a normal weekend "
            "looks like yet.", style={"color": TEXT_DIM, "fontSize": "0.8rem"}))
    short = event.replace(" Grand Prix", "")
    return card(
        title,
        html.Div([
            html.P(_weekend_plain(D, shown, short),
                   style={"color": TEXT_MAIN, "fontSize": "0.82rem",
                          "marginBottom": "6px"}),
            dcc.Graph(figure=_weekend_fig(D, shown), config=GFX),
            html.P(["Each number is this weekend minus the team's own average "
                    "over the season's other rounds (both already versus the "
                    f"field). ● and full colour = beyond {NOTABLE_Z:.0f}σ of "
                    "normal round-to-round scatter; faded cells are inside the "
                    "noise. Season averages: SEASON tab → Car Character, Car "
                    "Traits, Engine Championship.",
                    _filter_note(shown, order)],
                   style={"color": TEXT_DIM, "fontSize": "0.74rem",
                          "marginTop": "4px", "marginBottom": 0}),
        ]),
        measure=("one-lap", "stint"),
        info=("Data: data/car_profile.csv — the same per-round, field-centred "
              "axes the SEASON tab averages. For the loaded event each team's "
              "value is compared with its mean over the OTHER rounds of the "
              "season; σ is the pooled scatter of every team around its own "
              "mean (inflated for the uncertainty of that mean), so 2σ is a "
              "weekend that far off-norm by chance about 1 time in 20. Green / "
              "red = better / worse than the team's own norm on that axis; "
              "energy saving is a style and stays neutral. Why: a season "
              "average says what kind of car it is; this says where the car "
              "did not behave like itself at this circuit — a setup gamble, a "
              "track that suits or punishes it, or an upgrade or damage story "
              "worth reading the stints below for. Caveat: with five axes × "
              "eleven teams, two or three 2σ cells per weekend are expected "
              "from noise alone — look for the big ones, and for several axes "
              "of one car moving together."),
    )


