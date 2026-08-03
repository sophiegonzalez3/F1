"""UPGRADES tab card: the econometric read on car development.

Renders data/upgrade_study.csv (built by scripts/compute_upgrade_study.py,
estimation in f1lib/upgrade_study.py). Two panels:

  left    the event-study plot — pace relative to the round before a major
          package arrived, by rounds since. The LEADS on the left of the
          zero line are the point: they are the test that teams were not
          already moving before the parts showed up.
  right   the dose-response headline (pp of pace per declared component)
          with its placebo null, so the reader sees the estimate against the
          distribution it has to beat rather than a bare number.

Colour separates the two outcomes (one-lap speed, race pace) and nothing
else; both series are direct-labelled as well as legended.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dash import dcc, html
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from f1lib.components import card, theme, GFX
from f1lib.config import CARD_BG, TEXT_MAIN, TEXT_DIM, GRID_CLR
from f1lib.upgrade_study import MAJOR_ITEMS, REFERENCE_K, study_df

# One colour per outcome — validated against CARD_BG for contrast and
# colour-vision deficiency; identity is also carried by the legend and by
# the direct label on the dose panel.
_KINDS = [("longrun", "Race pace", "#3987e5"),
          ("onelap", "One-lap speed", "#d95926")]


def _k_of(term: str) -> float:
    """'k_-2' -> -2, 'k_3plus' -> 3."""
    t = term[2:].replace("plus", "")
    try:
        return float(t)
    except ValueError:
        return np.nan


def _fig(d: pd.DataFrame) -> go.Figure:
    ev = d[d["spec"] == "event"].copy()
    dose = d[d["spec"] == "dose"]
    plac = d[d["spec"] == "placebo"]

    fig = make_subplots(
        rows=1, cols=2, column_widths=[0.62, 0.38], horizontal_spacing=0.11,
        subplot_titles=("Pace around a major package (≥ %d parts)" % MAJOR_ITEMS,
                        "Per declared part"))

    for kind, label, clr in _KINDS:
        e = ev[ev["kind"] == kind].copy()
        if e.empty:
            continue
        e["k"] = e["term"].map(_k_of)
        # the omitted reference round is a true zero by construction — draw it
        # so the reader sees what everything is measured against
        e = pd.concat([e, pd.DataFrame([{
            "k": REFERENCE_K, "coef": 0.0, "se_cluster": 0.0,
            "p_wild": np.nan}])], ignore_index=True).sort_values("k")
        fig.add_trace(go.Scatter(
            x=e["k"], y=e["coef"], name=label, mode="lines+markers",
            line=dict(color=clr, width=2), marker=dict(size=9, color=clr),
            error_y=dict(type="data", array=1.96 * e["se_cluster"],
                         color=clr, thickness=1.5, width=5),
            customdata=np.stack([e["se_cluster"], e["p_wild"]], axis=-1),
            hovertemplate=(f"<b>{label}</b><br>%{{x:>+.0f}} rounds from the "
                           "package<br>%{y:>+.3f} pp "
                           "(se %{customdata[0]:.3f}, p %{customdata[1]:.3f})"
                           "<extra></extra>"),
        ), row=1, col=1)

    fig.add_vline(x=REFERENCE_K + 0.5, line_dash="dot", line_color=TEXT_DIM,
                  line_width=1, row=1, col=1)
    fig.add_hline(y=0, line_color=GRID_CLR, line_width=1, row=1, col=1)
    fig.add_annotation(x=REFERENCE_K + 0.5, y=1.0, yref="y domain",
                       text="package arrives", showarrow=False,
                       font=dict(size=10, color=TEXT_DIM),
                       xanchor="left", xshift=4, row=1, col=1)

    # right panel: dose estimate vs its placebo null
    for i, (kind, label, clr) in enumerate(_KINDS):
        dk = dose[dose["kind"] == kind]
        pk = plac[plac["kind"] == kind]
        if dk.empty:
            continue
        c = float(dk["coef"].iloc[0])
        se = float(dk["se_cluster"].iloc[0])
        p = float(dk["p_wild"].iloc[0])
        if not pk.empty:
            # the null band: what shuffled upgrade timing produces
            nm, ns = float(pk["coef"].iloc[0]), float(pk["se_cluster"].iloc[0])
            fig.add_trace(go.Scatter(
                x=[nm - 1.96 * ns, nm + 1.96 * ns], y=[label, label],
                mode="lines", line=dict(color=GRID_CLR, width=12),
                showlegend=(i == 0), name="placebo null (shuffled timing)",
                hovertemplate=("placebo null: %{x:>+.3f} pp"
                               "<extra></extra>"),
            ), row=1, col=2)
        fig.add_trace(go.Scatter(
            x=[c], y=[label], mode="markers+text", showlegend=False,
            marker=dict(size=13, color=clr, symbol="diamond",
                        line=dict(color=CARD_BG, width=1)),
            error_x=dict(type="data", array=[1.96 * se], color=clr,
                         thickness=1.5, width=6),
            text=[f"  {c:+.3f} pp/part (p={p:.3f})"], textposition="middle right",
            textfont=dict(size=11, color=TEXT_MAIN),
            hovertemplate=(f"<b>{label}</b><br>%{{x:>+.4f}} pp per declared "
                           f"part<br>95% CI ±{1.96 * se:.3f}, "
                           f"wild-bootstrap p={p:.3f}<extra></extra>"),
        ), row=1, col=2)
    fig.add_vline(x=0, line_color=TEXT_DIM, line_width=1, row=1, col=2)

    fig.update_xaxes(title_text="rounds since the package", dtick=1,
                     row=1, col=1)
    fig.update_yaxes(title_text="pp vs the round before (− = faster)",
                     row=1, col=1)
    fig.update_xaxes(title_text="pp per part (− = faster)", row=1, col=2)
    fig.update_yaxes(showticklabels=False, row=1, col=2)
    fig.update_layout(
        height=430, hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.10, x=0),
        margin=dict(r=150),
    )
    theme(fig)
    return fig


def _verdict(d: pd.DataFrame) -> html.Div:
    """One plain sentence per outcome, so the statistics are not the only
    way to read the card."""
    bits = []
    for kind, label, clr in _KINDS:
        dk = d[(d["spec"] == "dose") & (d["kind"] == kind)]
        loo = d[(d["spec"] == "loo_summary") & (d["kind"] == kind)]
        ev = d[(d["spec"] == "event") & (d["kind"] == kind)]
        if dk.empty:
            continue
        c, p = float(dk["coef"].iloc[0]), float(dk["p_wild"].iloc[0])
        clean = bool(ev["pretrend_clean"].iloc[0]) if not ev.empty else None
        robust = bool(loo["same_sign"].iloc[0]) if not loo.empty else None
        sig = p < 0.05
        txt = (f"{label}: each declared part is worth {abs(c):.3f} pp "
               f"{'faster' if c < 0 else 'slower'}"
               f" ({'significant' if sig else 'not significant'}, p={p:.3f})."
               f" A ten-part package therefore buys about {abs(c) * 10:.1f} pp.")
        if clean is False:
            txt += " Pre-trend test FAILED — read with suspicion."
        elif clean:
            txt += " Teams were not already moving beforehand."
        if robust is False:
            txt += " Sign flips when one team is dropped — fragile."
        bits.append(html.Li(txt, style={"marginBottom": "3px"}))
    return html.Ul(bits, style={"color": TEXT_DIM, "fontSize": "0.8rem",
                                "lineHeight": "1.5", "marginBottom": "0"})


def upgrade_econ_card(season) -> object:
    d = study_df()
    d = d[d["season"] == int(season)] if not d.empty else d
    if d.empty or d[d["spec"] == "dose"].empty:
        body = html.P(
            ["No upgrade study for this season yet — build it with ",
             html.Code(f"python scripts/compute_upgrade_study.py "
                       f"--season {season}"),
             " (it needs the pace table and data/upgrades.csv)."],
            style={"color": TEXT_DIM, "fontSize": "0.85rem"})
    else:
        body = html.Div([dcc.Graph(figure=_fig(d), config=GFX), _verdict(d)])
    return card(
        "Did development actually work? — panel event study", body,
        info=("Data: a fixed-effects panel of every team-round in the season. "
              "Outcome = pace vs the field median; treatment = performance "
              "components declared in the FIA Car Presentation. TEAM fixed "
              "effects absorb how good the car started, ROUND fixed effects "
              "absorb anything that hit the whole field at once. LEFT: pace "
              f"in the rounds around a major package (≥ {MAJOR_ITEMS} parts), "
              "measured against the round before it arrived. The bars left of "
              "the dotted line are the credibility test — if teams were "
              "already gaining before the parts appeared, this is measuring a "
              "trend, not an upgrade. RIGHT: the pooled effect per declared "
              "part, shown against the placebo null produced by reshuffling "
              "each team's upgrade timing within its own season (the null is "
              "not centred on zero because parts accumulate through a season "
              "regardless of when they land — the estimate has to beat that, "
              "not merely beat zero). Bars are 95% CI from team-clustered "
              "standard errors; p-values are wild cluster bootstrap, which is "
              "the honest choice with only eleven clusters. Why: the Effect "
              "Board above says what happened around one package; this says "
              "whether development pays off on average, and whether the board "
              "is reading causation or the calendar. Caveats: it cannot "
              "separate development from CIRCUIT CHARACTER — a high-downforce "
              "car gains at Hungary and loses at Spa with no new parts, and "
              "round fixed effects only remove what moved the whole field. A "
              "part count is also a poor proxy for how much performance was "
              "actually brought: one clever floor can beat nine small items."),
        measure=["one-lap", "race"])
