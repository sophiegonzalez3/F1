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
_ERR_KEY = "DNF — solo accident"
_DSQ_KEY = "Disqualified"
_UNC_KEY = "DNF — unclassified"
_DNS_KEY = "Did not start"
_BUCKET_ORDER = [_FINISH_KEY, _MECH_KEY, _INC_KEY, _ERR_KEY, _DSQ_KEY,
                 _UNC_KEY, _DNS_KEY]

# cause_family (f1lib.dnf_causes) -> bucket.
_FAMILY_TO_BUCKET = {"mechanical": _MECH_KEY, "collision": _INC_KEY,
                     "solo accident": _ERR_KEY, "disqualified": _DSQ_KEY}

# Which buckets can only ever be filled by CURATION, never by race control.
# Race control classifies exactly one thing — contact — so every other family
# arrives from data/dnf_causes.csv. These render hatched, so a reader can see
# at a glance which part of the chart is measured and which is reported.
_PRESS_ONLY = {_MECH_KEY, _ERR_KEY, _DSQ_KEY}

# Status-style palette (good → bad), not team colours: the bars are keyed to
# teams on the y-axis, the segments to failure type.
_BUCKET_COLORS = {
    _FINISH_KEY: "#0ca30c",   # good
    _MECH_KEY:   "#fab219",   # warning — the team's own reliability
    _INC_KEY:    "#d03b3b",   # critical — racing incidents
    _ERR_KEY:    "#b5651d",   # off or into the wall, no other car involved
    _DSQ_KEY:    "#8a2be2",   # not a reliability event at all — kept separate
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
    """Re-label unclassified DNFs, race control first and curation to fill.

    From 2023 the archive records a bare "Retired" for every non-finish, so
    everything lands in the unclassified bucket. Two layers dig it back out,
    and their ORDER is the point (see f1lib.dnf_causes.resolve_cause):

    1. RACE CONTROL — contemporaneous FIA messages, via f1lib.incidents. It
       classifies exactly one thing, contact, and it outranks curation.
       Only PROXIMATE contact counts, with an asymmetric window: real damage
       ends a race fast, but the register's lap is the message's PUBLICATION
       lap and can legitimately sit after the car stopped.
    2. CURATION — data/dnf_causes.csv, for the ~169 retirements race control
       never saw because nothing was investigated. Press is the only source
       for a car that simply stopped.

    Returns the count of rows re-labelled from EITHER layer. Curated families
    render hatched in the figure so measured and reported stay distinguishable.
    """
    from f1lib.dnf_causes import resolve_cause

    laps_col = "Laps" if "Laps" in r.columns else None
    n = 0
    for idx, row in r[r["bucket"] == _UNC_KEY].iterrows():
        got = resolve_cause(
            season, str(row.get("event_name", "")), row.get("Abbreviation"),
            row.get(laps_col) if laps_col else None)
        bucket = _FAMILY_TO_BUCKET.get(got["cause_family"])
        if bucket:
            r.loc[idx, "bucket"] = bucket
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
        # Hatch the families only curation can fill. Race control classifies
        # contact and nothing else, so a solid segment is an FIA record and a
        # hatched one is a person reading the press — a distinction the chart
        # must not swallow.
        marker = dict(color=_BUCKET_COLORS[b],
                      line=dict(color="#0d0d1a", width=1))
        if b in _PRESS_ONLY:
            marker["pattern"] = dict(shape="/", size=5, solidity=0.35,
                                     fgcolor="#0d0d1a")
        fig.add_trace(go.Bar(
            y=teams, x=vals, orientation="h", name=b, marker=marker,
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

    # How many of those knocks actually ENDED a race. The card's own caveat is
    # that it counts events, not damage — this is the one damage-ish figure
    # that is not an estimate: the retirement either happened or it did not.
    # Uses the same two-layer resolution as the reliability card, so a contact
    # whose damage took a dozen laps to end the race (curated, e.g. Piastri at
    # the Hungaroring 2026) counts alongside the ones race control tied to the
    # retirement directly.
    from f1lib.dnf_causes import resolve_cause

    dnf = _RACE[(_RACE["season"] == season)
                & ~_RACE["Status"].isin(_FINISHED)]
    ended = set()
    for _, row in dnf.iterrows():
        got = resolve_cause(season, str(row.get("event_name", "")),
                            row.get("Abbreviation"),
                            row.get("Laps") if "Laps" in dnf.columns else None)
        if got["cause_family"] == "collision":
            ended.add((str(row.get("event_name", "")),
                       str(row.get("Abbreviation", ""))))
    # Count DRIVER-RACES, not contact rows: a driver with two logged knocks in
    # the race he retired from ended one race, not two.
    c["_key"] = list(zip(c["event"].astype(str), c["driver"].astype(str)))
    c["ended_race"] = [k in ended for k in c["_key"]]

    out = (c.groupby("team")
             .agg(contacts=("driver", "size"),
                  at_fault=("at_fault", "sum"),
                  ended_race=("_key", lambda s: len({
                      k for k in s if k in ended})),
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
            customdata=t.set_index("team").loc[
                teams, ["drivers", "ended_race", "contacts"]].values,
            hovertemplate=(f"<b>%{{y}}</b><br>{label}: %{{x}}<br>"
                           "%{customdata[1]} of %{customdata[2]} ended the "
                           "race<br>%{customdata[0]}<extra></extra>"),
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
            f"{int(worst['at_fault'])} of them penalised"
            + (f", and {int(t['ended_race'].sum())} of the "
               f"{int(t['contacts'].sum())} contacts across the field ended "
               f"someone's race." if int(t["ended_race"].sum()) else ".")),
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
              "worth of cases. The one damage figure here that is NOT an "
              "estimate is 'ended the race' in the hover: the retirement "
              "either happened or it did not. It uses the same two-layer "
              "resolution as the reliability card, so a contact whose damage "
              "took a dozen laps to finish the car (Piastri at the "
              "Hungaroring, hit on lap 38 and out on lap 55) is counted "
              "alongside the ones race control tied to the retirement "
              "directly."),
    )


def _provenance(season: int) -> tuple[int, int, int, int]:
    """(measured, reported, looked-but-blank, never-looked) for this season.

    The card has to be able to say which part of itself is an FIA record and
    which is a person reading the press — and to distinguish a retirement
    nobody has researched from one where the press simply never said.
    """
    from f1lib.dnf_causes import causes_df, FAMILIES, resolve_cause

    if _RACE.empty:
        return 0, 0, 0, 0
    r = _RACE[_RACE["season"] == season]
    r = r[r["Status"].astype(str).map(_bucket).astype(str).str.startswith("DNF")]
    measured = reported = 0
    for _, row in r.iterrows():
        got = resolve_cause(season, str(row.get("event_name", "")),
                            row.get("Abbreviation"),
                            row.get("Laps") if "Laps" in r.columns else None)
        if got["cause_source"] == "race_control":
            measured += 1
        elif got["cause_source"] == "press":
            reported += 1
    d = causes_df()
    looked = never = 0
    if not d.empty:
        s = d[pd.to_numeric(d["season"], errors="coerce") == season]
        fam = s["cause_family"].astype(str).str.strip().str.lower()
        chk = s["press_checked"].astype(str).str.strip()
        blank = ~fam.isin(FAMILIES)
        looked = int((blank & chk.ne("") & chk.ne("nan")).sum())
        never = int((blank & (chk.eq("") | chk.eq("nan"))).sum())
    return measured, reported, looked, never


def reliability_card(season: int):
    """Reliability card for the SEASON FORM section, or None if no archive."""
    piv = reliability_table(season)
    if piv.empty:
        return None
    from f1lib.incidents import has_incidents, CAUSAL_WINDOW

    measured, reported, looked, never = _provenance(season)
    if piv[_UNC_KEY].sum() > 0 and measured == 0 and reported == 0:
        note = (" This season's archive only records a generic retirement "
                "status, so DNFs show as 'unclassified' rather than split by "
                "cause.")
    elif measured or reported:
        note = (
            f" HOW THE CAUSES ARE KNOWN. The archive has recorded a bare "
            f"'Retired' for every non-finish since 2023, so no cause comes "
            f"from it. Two layers rebuild them and the SOLID/HATCHED split on "
            f"the bars is which one you are looking at. Solid = race control "
            f"(data/incidents.csv): a contemporaneous FIA record, and it only "
            f"ever establishes CONTACT — {measured} this season. A retirement "
            f"counts as one if a logged contact involving that driver sits "
            f"within {CAUSAL_WINDOW} laps of its last lap, or up to "
            f"{CAUSAL_WINDOW} laps after (race control's lap is the message's "
            f"PUBLICATION lap, and a driver cannot crash after retiring). "
            f"Hatched = curated from the press (data/dnf_causes.csv) — "
            f"{reported} this season — for the cars that simply stopped, which "
            f"draw no stewards' message and are therefore invisible to race "
            f"control. Press never outranks race control; it only fills holes. "
            f"COVERAGE, so the gaps are countable: {looked} retirement(s) were "
            f"researched and no source gave a cause, and {never} have not been "
            f"researched yet — both sit in 'unclassified', but only the second "
            f"is a to-do. A team's own explanation is recorded as a claim, not "
            f"a measurement.")
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
              "season, bucketed into a finish vs. the reason it failed to "
              "finish (mechanical, racing incident, solo accident, "
              "disqualification, unclassified, or did-not-start). Solid "
              "segments are established by race control, hatched ones are "
              "curated from the press. The % on each green "
              "bar is the team's finish rate. Why: reliability is points left "
              "on the table — a fast car that keeps breaking or crashing "
              "bleeds a championship." + note),
    )
