"""
Reliability / DNF-cause view for the SEASON FORM section.

Derived — not hand-collected — from the historical race-results archive
(data/historical_results/race_results_all.parquet, the same file the standings
widgets use). Each car-race carries a FastF1/Ergast-style ``Status`` string; we
bucket those into finished vs. the reasons a car failed to finish, per team, for
the selected season.

Caveat baked into the UI: recent-season data (e.g. 2026) often only carries a
generic "Retired" status, so those DNFs land in "DNF — unclassified" rather than
a mechanical/incident split. Older seasons (2024/2025) carry the full cause
vocabulary and split cleanly.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc

from f1lib.components import card, theme, GFX
from f1lib.glossary import gloss
from f1lib.config import HISTORICAL_DIR, TEAM_COLORS, TEXT_MAIN, TEXT_DIM

_RACE_PATH = Path(HISTORICAL_DIR) / "race_results_all.parquet"


def _load_race() -> pd.DataFrame:
    if _RACE_PATH.exists():
        try:
            return pd.read_parquet(_RACE_PATH, engine="pyarrow")
        except Exception as _exc:
            print(f"Reliability archive     : failed to read ({_exc})")
    return pd.DataFrame()


_RACE = _load_race()

# ── Status → bucket mapping ───────────────────────────────────
_FINISHED = {"Finished", "Lapped", "+1 Lap", "+2 Laps", "+3 Laps",
             "+4 Laps", "+5 Laps", "+6 Laps"}
_MECHANICAL = {"Engine", "Gearbox", "Hydraulics", "Power Unit", "Turbo",
               "Brakes", "Suspension", "Electrical", "Fuel leak",
               "Fuel pressure", "Fuel pump", "Water leak", "Water pressure",
               "Water pump", "Oil leak", "Cooling system", "Driveshaft",
               "Differential", "Power loss", "Vibrations", "Mechanical",
               "Wheel nut", "Undertray", "Front wing", "Rear wing"}
_INCIDENT = {"Accident", "Collision", "Collision damage", "Spun off",
             "Damage", "Puncture"}
_DNS = {"Did not start", "Withdrew", "Illness"}
# Everything else that isn't a finish (notably the generic "Retired" used by
# recent-season data, plus "Disqualified") lands in the unclassified bucket.

_FINISH_KEY = "Finished"
_MECH_KEY = "DNF — mechanical"
_INC_KEY = "DNF — incident"
_UNC_KEY = "DNF — unclassified"
_DNS_KEY = "Did not start"
_BUCKET_ORDER = [_FINISH_KEY, _MECH_KEY, _INC_KEY, _UNC_KEY, _DNS_KEY]

# Status-style palette (good → bad), not team colours: the bars are keyed to
# teams on the y-axis, the segments to failure type.
_BUCKET_COLORS = {
    _FINISH_KEY: "#0ca30c",   # good
    _MECH_KEY:   "#fab219",   # warning — the team's own reliability
    _INC_KEY:    "#d03b3b",   # critical — racing incidents
    _UNC_KEY:    "#ec835a",   # serious — cause not recorded
    _DNS_KEY:    "#7A7A7A",   # muted — never started
}


def _bucket(status: str) -> str:
    if status in _FINISHED:
        return _FINISH_KEY
    if status in _MECHANICAL:
        return _MECH_KEY
    if status in _INCIDENT:
        return _INC_KEY
    if status in _DNS:
        return _DNS_KEY
    return _UNC_KEY


def reliability_table(season: int) -> pd.DataFrame:
    """Per-team bucket counts + finish rate for one season (race sessions)."""
    if _RACE.empty:
        return pd.DataFrame()
    r = _RACE[_RACE["season"] == season].copy()
    if r.empty:
        return pd.DataFrame()
    r["bucket"] = r["Status"].astype(str).map(_bucket)
    piv = (r.pivot_table(index="TeamName", columns="bucket", values="Status",
                         aggfunc="size", fill_value=0))
    for b in _BUCKET_ORDER:
        if b not in piv.columns:
            piv[b] = 0
    piv = piv[_BUCKET_ORDER]
    piv["starts"] = piv.sum(axis=1)
    piv["dnf"] = piv["starts"] - piv[_FINISH_KEY]
    piv["finish_rate"] = piv[_FINISH_KEY] / piv["starts"]
    return piv


def _reliability_fig(season: int) -> go.Figure:
    piv = reliability_table(season)
    fig = go.Figure()
    if piv.empty:
        theme(fig, 300, "No race-results archive for this season")
        return fig
    # Best reliability at the top: horizontal bars plot bottom-up, so sort
    # ascending by finish rate → worst at bottom, best at top.
    piv = piv.sort_values("finish_rate", ascending=True)
    teams = piv.index.tolist()

    for b in _BUCKET_ORDER:
        vals = piv[b].tolist()
        if sum(vals) == 0:
            continue
        # Label the finished segment with each team's finish-rate %.
        text = ([f"{r*100:.0f}%" for r in piv["finish_rate"]]
                if b == _FINISH_KEY else None)
        fig.add_trace(go.Bar(
            y=teams, x=vals, orientation="h", name=b,
            marker=dict(color=_BUCKET_COLORS[b], line=dict(color="#0d0d1a", width=1)),
            text=text, textposition="inside", insidetextanchor="start",
            textfont=dict(size=10, color="#000"),
            hovertemplate=f"<b>%{{y}}</b><br>{b}: %{{x}} car-race(s)<extra></extra>",
        ))
    n = len(teams)
    theme(fig, max(320, 30 * n + 130))
    fig.update_layout(barmode="stack",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0, font=dict(size=10)),
                      margin=dict(l=120, r=20, t=44, b=44))
    fig.update_xaxes(title_text="Car-races (2 cars × rounds)")
    fig.update_yaxes(title_text=None)
    return fig


def reliability_card(season: int):
    """Reliability card for the SEASON FORM section, or None if no archive."""
    piv = reliability_table(season)
    if piv.empty:
        return None
    # Detect the coarse-status case (all DNFs unclassified) to tune the note.
    coarse = (piv[_MECH_KEY].sum() == 0 and piv[_INC_KEY].sum() == 0
              and piv[_UNC_KEY].sum() > 0)
    note = (" This season's archive only records a generic retirement status, "
            "so DNFs show as 'unclassified' rather than split by cause."
            if coarse else "")
    _total_dnf, _starts = int(piv["dnf"].sum()), int(piv["starts"].sum())
    _best = piv["finish_rate"].idxmax()
    _plain = (
        "Not every car reaches the finish — a crash or a mechanical failure "
        "ends its race early (a 'DNF', short for Did Not Finish). This season "
        f"{_total_dnf} of {_starts} car-races ended that way. {_best} have been "
        "the most reliable, finishing the biggest share of their races — pace "
        "means nothing if the car doesn't make it home.")
    return card(
        ["Reliability & ", *gloss("dnf", "DNFs")],
        dcc.Graph(figure=_reliability_fig(season), config=GFX),
        plain=_plain,
        info=("Data: every car-race in the historical results archive for this "
              "season, bucketed by its finishing Status into a classified "
              "finish vs. the reason it failed to finish (mechanical, racing "
              "incident, unclassified, or did-not-start). The % on each green "
              "bar is the team's finish rate. Why: reliability is points left "
              "on the table — a fast car that keeps breaking or crashing "
              "bleeds a championship." + note),
    )
