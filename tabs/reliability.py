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


def _apply_incident_register(r: pd.DataFrame, season: int) -> tuple[pd.DataFrame, int]:
    """Re-label unclassified DNFs the incident register can explain.

    From 2023 the archive records a bare "Retired" for every non-finish, so
    everything lands in the unclassified bucket. Race control still logged the
    contact, so a retirement within a couple of laps of a contact incident
    involving that driver becomes a real 'collision' DNF.

    Only PROXIMATE contact counts — see f1lib.incidents.classify_retirement.
    Matching any earlier incident would "explain" six 2026 retirements
    including one where the contact was 26 laps before the car stopped.
    """
    from f1lib.incidents import has_incidents, classify_retirement

    if not has_incidents(season):
        return r, 0
    laps_col = "Laps" if "Laps" in r.columns else None
    n = 0
    for idx, row in r[r["bucket"] == _UNC_KEY].iterrows():
        got = classify_retirement(
            season, str(row.get("event_name", "")), row.get("Abbreviation"),
            row.get(laps_col) if laps_col else None)
        if got["cause"] == "collision":
            r.loc[idx, "bucket"] = _INC_KEY
            n += 1
    return r, n


def reliability_table(season: int) -> pd.DataFrame:
    """Per-team bucket counts + finish rate for one season (race sessions)."""
    if _RACE.empty:
        return pd.DataFrame()
    r = _RACE[_RACE["season"] == season].copy()
    if r.empty:
        return pd.DataFrame()
    r["bucket"] = r["Status"].astype(str).map(_bucket)
    r, _ = _apply_incident_register(r, season)
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


def _contact_table(season: int) -> pd.DataFrame:
    """Per-team contact incidents for a season, split by fault.

    'At fault' = the stewards issued a penalty against that car for it. A
    contact with no penalty is still recorded — a driver who keeps getting hit
    loses just as much lap time as one who keeps hitting people, and the whole
    point of this card is that it counts contact whether or not it ended a
    race.
    """
    from f1lib.incidents import contact_for

    c = contact_for(season)
    if c.empty or _RACE.empty:
        return pd.DataFrame()
    team_of = (_RACE[_RACE["season"] == season]
               .drop_duplicates("Abbreviation")
               .set_index("Abbreviation")["TeamName"])
    c = c.assign(team=c["driver"].map(team_of)).dropna(subset=["team"])
    if c.empty:
        return pd.DataFrame()
    c["at_fault"] = c["outcome"].astype(str).str.startswith("penalty")
    out = (c.groupby("team")
             .agg(contacts=("driver", "size"),
                  at_fault=("at_fault", "sum"),
                  drivers=("driver", lambda s: ", ".join(sorted(set(s)))))
             .reset_index())
    out["not_at_fault"] = out["contacts"] - out["at_fault"]
    return out.sort_values("contacts", ascending=False)


def _contact_fig(season: int) -> go.Figure:
    t = _contact_table(season)
    fig = go.Figure()
    if t.empty:
        theme(fig, 300, "No incident register for this season")
        return fig
    teams = t["team"].tolist()[::-1]
    for col, label, colour in (("at_fault", "Penalised for it", "#d03b3b"),
                               ("not_at_fault", "Involved, no penalty", "#ec835a")):
        fig.add_trace(go.Bar(
            y=teams, x=t.set_index("team").loc[teams, col], orientation="h",
            name=label,
            marker=dict(color=colour, line=dict(color="#0d0d1a", width=1)),
            customdata=t.set_index("team").loc[teams, ["drivers"]].values,
            hovertemplate=(f"<b>%{{y}}</b><br>{label}: %{{x}}<br>"
                           "%{customdata[0]}<extra></extra>"),
        ))
    theme(fig, max(320, 30 * len(teams) + 130))
    fig.update_layout(barmode="stack",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0, font=dict(size=10)),
                      margin=dict(l=120, r=20, t=44, b=44))
    fig.update_xaxes(title_text="Contact incidents logged by race control")
    fig.update_yaxes(title_text=None)
    return fig


def contact_card(season: int):
    """Season contact record, or None when the register hasn't been built."""
    from f1lib.incidents import has_incidents
    if not has_incidents(season):
        return None
    t = _contact_table(season)
    if t.empty:
        return None
    worst = t.iloc[0]
    return card(
        "Contact Record — who is in the wars",
        dcc.Graph(figure=_contact_fig(season), config=GFX),
        plain=(
            f"Not every knock ends a race — most don't. This counts every "
            f"contact race control logged, whether or not the car retired. "
            f"{worst['team']} lead with {int(worst['contacts'])}, "
            f"{int(worst['at_fault'])} of them penalised."),
        info=("Data: data/incidents.csv (scripts/compute_incidents.py), parsed "
              "from the cached race-control messages of every race this "
              "season. One row per car per incident, with the four announcement "
              "stages (noted → investigated → penalty → served) collapsed via "
              "the incident's own clock time. 'Penalised for it' means the "
              "stewards issued a penalty against that car; the rest were "
              "logged but not punished — including the driver who was hit. "
              "Why: the results archive has recorded a bare 'Retired' since "
              "2023, so contact was invisible unless it ended a race, and most "
              "contact doesn't. Caveat: this counts EVENTS, not damage. An "
              "attempt to measure the lap-time cost of each one was built and "
              "rejected — within a stint, normal tyre degradation produces a "
              "bigger before/after step than the contact does, so the "
              "measurement could not be separated from noise on a season's "
              "worth of cases."),
    )


def reliability_card(season: int):
    """Reliability card for the SEASON FORM section, or None if no archive."""
    piv = reliability_table(season)
    if piv.empty:
        return None
    # Detect the coarse-status case (all DNFs unclassified) to tune the note.
    coarse = (piv[_MECH_KEY].sum() == 0 and piv[_INC_KEY].sum() == 0
              and piv[_UNC_KEY].sum() > 0)
    from f1lib.incidents import has_incidents, CAUSAL_WINDOW
    if coarse:
        note = (" This season's archive only records a generic retirement "
                "status, so DNFs show as 'unclassified' rather than split by "
                "cause.")
    elif has_incidents(season) and piv[_MECH_KEY].sum() == 0:
        note = (
            f" This season's archive records only a generic 'Retired' status, "
            f"so the cause is recovered from race control (data/incidents.csv): "
            f"a retirement within {CAUSAL_WINDOW} laps of a logged contact "
            f"incident involving that driver is counted as a racing incident. "
            f"Everything else stays UNCLASSIFIED rather than being assumed "
            f"mechanical — matching a retirement to any earlier contact would "
            f"be mostly wrong (in 2026 it would 'explain' a retirement whose "
            f"contact was 26 laps earlier). So the incident bar is a floor, "
            f"not a count, and the unclassified bar still holds most DNFs.")
    else:
        note = ""
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
