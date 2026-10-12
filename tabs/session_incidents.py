"""
Crashes & failures in EVERY session — the SEASON-tab sibling of the race-only
reliability card.

The reliability card answers "how often did the car reach the chequered flag
on Sunday". It cannot see a driver who keeps putting the car in the wall in
practice, or a car that keeps stopping on Friday and is fixed by Sunday —
which is most of what "crash-prone" and "unreliable" mean. This card counts
every session: the race and the sprint from the results archives, practice
and qualifying from the stop detector (f1lib.session_stops) via the curated
data/dnf_causes.csv, where every row carries its `session`.

Two panels, one family each, so the question decides the panel:
  car     per TEAM, events imputable to the car or team (failures, a team
          calling a healthy car in)
  driver  per DRIVER, events imputable to the driver (crashes and offs with
          no other car)
Collisions (imputable to neither) and not-yet-attributed events are counted in
the hovers and the plain-terms line, not drawn: a bar must mean one thing.

Session is the segment, as LIGHTNESS steps of the family's hue (practice
dimmest, race brightest) — validated as an ordinal ramp against the card
surface. Hatched = mostly curated from the press, solid = an FIA record (the
archive's own status or race control), the same rule as the reliability card.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from f1lib.components import card, theme, GFX
from f1lib.config import CARD_BG, HISTORICAL_DIR, TEXT_DIM
from f1lib.dnf_causes import (CAR, COLLISION, DRIVER, DSQ, STATUS_FAMILY,
                              causes_df, normalise_family, resolve_cause)
from f1lib.incidents import session_of
from f1lib.session_stops import FALSE_ALARM, LOST_RUNNING, NON_RACE, STOPPED

GROUP = {"Practice 1": "Practice", "Practice 2": "Practice",
         "Practice 3": "Practice", "Sprint Shootout": "Qualifying",
         "Sprint Qualifying": "Qualifying", "Qualifying": "Qualifying",
         "Sprint": "Sprint", "Race": "Race"}
GROUPS = ("Practice", "Qualifying", "Sprint", "Race")
SHORT = {"Practice 1": "FP1", "Practice 2": "FP2", "Practice 3": "FP3",
         "Sprint Shootout": "SS", "Sprint Qualifying": "SQ",
         "Qualifying": "Q", "Sprint": "Sprint", "Race": "Race"}

# Ordinal ramps, dimmest -> brightest = Practice -> Race. Validated
# (dataviz validate_palette.js --ordinal --mode dark --surface #1A1A2E):
# monotone lightness, adjacent dL >= 0.06, light end >= 2:1, one hue. The
# car ramp ends on the reliability card's own car colour.
RAMP = {CAR: ("#7a5a16", "#a87c1c", "#d49c22", "#fab219"),
        DRIVER: ("#7a4418", "#a65c22", "#d17c3a", "#f4a266")}

_FINISHED = {"Finished", "Lapped", "+1 Lap", "+2 Laps", "+3 Laps",
             "+4 Laps", "+5 Laps", "+6 Laps"}
_SELF_DNS = {"Withdrew", "Illness"}
FIRST_SEASON = 2023          # practice / qualifying are only tracked from here


def _archive(name: str) -> pd.DataFrame:
    p = Path(HISTORICAL_DIR) / name
    try:
        return pd.read_parquet(p) if p.exists() else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def session_events(season: int) -> pd.DataFrame:
    """One row per event: event, round, session, group, driver, team, family
    ('' = not yet attributed), source (archive / race_control / press / ''),
    kind ('stop' = it ended the session for that car; 'lost' = running lost
    without a stop of its own: did not run / take part / no time set)."""
    rows = []
    for name, session in (("race_results_all.parquet", "Race"),
                          ("sprint_results_all.parquet", "Sprint")):
        r = _archive(name)
        if r.empty:
            continue
        r = r[(r["season"] == season) & r["Status"].notna()
              & ~r["Status"].isin(_FINISHED)]
        for _, x in r.iterrows():
            status = str(x["Status"]).strip()
            if status == "Illness":
                fam, src = DRIVER, "archive"
            elif status in _SELF_DNS:
                fam, src = "", ""
            elif status in STATUS_FAMILY:
                fam, src = STATUS_FAMILY[status], "archive"
            else:
                got = resolve_cause(season, str(x["event_name"]),
                                    x["Abbreviation"], x.get("Laps"),
                                    session=session)
                fam, src = got["cause_family"], got["cause_source"]
            rows.append({"event": str(x["event_name"]),
                         "round": x.get("round_number"), "session": session,
                         "driver": str(x["Abbreviation"]),
                         "team": str(x.get("TeamName", "")),
                         "family": fam, "source": src, "kind": "stop",
                         "status": status})
    d = causes_df()
    if not d.empty:
        d = d[(pd.to_numeric(d["season"], errors="coerce") == season)]
        d = d.assign(_sess=session_of(d))
        d = d[d["_sess"].isin(NON_RACE)
              & d["status_archive"].astype(str).ne(FALSE_ALARM)]
        for _, x in d.iterrows():
            fam = normalise_family(x.get("cause_family", ""))
            status = str(x.get("status_archive", ""))
            rows.append({"event": str(x["event"]), "round": x.get("round"),
                         "session": x["_sess"], "driver": str(x["driver"]),
                         "team": str(x.get("team", "")), "family": fam,
                         "source": "press" if fam else "",
                         "kind": "lost" if status in LOST_RUNNING else "stop",
                         "status": status})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["group"] = out["session"].map(GROUP)
    # one team name per driver-season, from the race archive, so a lite-store
    # practice row and the race row of the same car land on the same bar
    arch = _archive("race_results_all.parquet")
    if not arch.empty:
        name = (arch[arch["season"] == season].drop_duplicates("Abbreviation")
                .set_index("Abbreviation")["TeamName"].to_dict())
        out["team"] = [name.get(dv, tm) for dv, tm in
                       zip(out["driver"], out["team"])]
    return out


def _label(r) -> str:
    rnd = f"R{int(r['round'])} " if pd.notna(r.get("round")) else ""
    ev = str(r["event"]).replace(" Grand Prix", "")
    return f"{rnd}{ev} {SHORT.get(r['session'], r['session'])}"


def _panel(ev: pd.DataFrame, family: str, by: str, keep=None) -> go.Figure:
    """Stacked bars of `family` stops per `by` (team / driver), one segment
    per session group."""
    fig = go.Figure()
    e = ev[(ev["kind"] == "stop") & (ev["family"] == family)]
    if keep is not None:
        e = e[keep(e)]
    if e.empty:
        theme(fig, 260, "Nothing recorded for this selection")
        return fig
    tot = e.groupby(by).size().sort_values(ascending=True)
    ents = tot.index.tolist()
    for g, colour in zip(GROUPS, RAMP[family]):
        sub = e[e["group"] == g]
        if sub.empty:
            continue
        cnt = sub.groupby(by).size().reindex(ents, fill_value=0)
        lists = {k: "<br>".join(
                     _label(r) + (f" ({r['driver']})" if by == "team" else "")
                     + (" · press" if r["source"] == "press" else "")
                     for _, r in s.sort_values("round").iterrows())
                 for k, s in sub.groupby(by)}
        marker = dict(color=colour, line=dict(color=CARD_BG, width=2))
        if (sub["source"] == "press").mean() > 0.5:
            # light hatch: the lightness step IS the session, so the press
            # mark must not darken it (a 0.35 card-colour hatch merged the
            # practice and qualifying steps)
            marker["pattern"] = dict(shape="/", size=7, solidity=0.18,
                                     fgcolor="rgba(26,26,46,0.55)")
        fig.add_trace(go.Bar(
            y=ents, x=cnt.values, orientation="h", name=g, marker=marker,
            customdata=[lists.get(k, "") for k in ents],
            hovertemplate=(f"<b>%{{y}}</b> · {g}: %{{x}}<br>"
                           "%{customdata}<extra></extra>")))
    theme(fig, max(260, 26 * len(ents) + 120))
    fig.update_layout(barmode="stack", bargap=0.35,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                  xanchor="left", x=0, font=dict(size=10),
                                  traceorder="normal"),
                      margin=dict(l=110, r=16, t=40, b=40))
    fig.update_xaxes(title_text="Events (each ended that session for the car)",
                     dtick=1)
    fig.update_yaxes(title_text=None)
    return fig


def session_incidents_card(season: int, teams=None, drivers=None):
    """`teams` / `drivers` are the SEASON scopes from pace_data.season_scope.
    None when the season has no practice / qualifying coverage."""
    if season < FIRST_SEASON:
        return None
    ev = session_events(season)
    if ev.empty or not ev["session"].isin(NON_RACE).any():
        return None
    from tabs.pace_data import team_mask

    team_keep = (None if teams is None
                 else (lambda e: team_mask(e["team"], teams).to_numpy()))
    drv_keep = (None if drivers is None
                else (lambda e: e["driver"].isin(drivers).to_numpy()))
    stops = ev[ev["kind"] == "stop"]
    n_car = int((stops["family"] == CAR).sum())
    n_drv = int((stops["family"] == DRIVER).sum())
    n_col = int((stops["family"] == COLLISION).sum())
    n_unk = int((stops["family"] == "").sum())
    n_lost = int((ev["kind"] == "lost").sum())
    off_race = stops[stops["session"] != "Race"]

    def _top(fam, by):
        s = stops[stops["family"] == fam].groupby(by).size()
        return (s.idxmax(), int(s.max())) if not s.empty else (None, 0)
    car_top, car_n = _top(CAR, "team")
    drv_top, drv_n = _top(DRIVER, "driver")

    n_off = int(off_race["family"].isin([CAR, DRIVER]).sum())
    plain = (
        "The race isn't the only place a car breaks or a driver crashes, and "
        "a weekend with a crash on Friday is a weekend spent rebuilding. This "
        f"season: {n_car} car failures and {n_drv} driver crashes across all "
        f"sessions, {n_off} of them outside the race"
        + (f"; {car_top}'s cars stopped most often ({car_n})" if car_top else "")
        + (f", and {drv_top} crashed most often ({drv_n})" if drv_top else "")
        + f". {n_col} more stop{'s were' if n_col != 1 else ' was a'} "
        f"collision{'s' if n_col != 1 else ''}, and {n_unk} "
        f"{'are' if n_unk != 1 else 'is'} not yet attributed.")

    graphs = html.Div([
        html.Div([html.Div("Car failures — per team",
                           style={"color": TEXT_DIM, "fontSize": "0.75rem",
                                  "marginBottom": "2px"}),
                  dcc.Graph(figure=_panel(ev, CAR, "team", team_keep),
                            config=GFX)],
                 style={"flex": "1 1 380px", "minWidth": "0"}),
        html.Div([html.Div("Driver crashes — per driver",
                           style={"color": TEXT_DIM, "fontSize": "0.75rem",
                                  "marginBottom": "2px"}),
                  dcc.Graph(figure=_panel(ev, DRIVER, "driver", drv_keep),
                            config=GFX)],
                 style={"flex": "1 1 380px", "minWidth": "0"}),
    ], style={"display": "flex", "flexWrap": "wrap", "gap": "12px"})

    return card(
        "Crashes & Failures — Every Session",
        graphs,
        plain=plain,
        info=(
            "Data: every session of the season, each event tagged with the "
            "session it happened in. Race and sprint: every non-finish in the "
            "results archives, its cause from race control (a logged contact "
            "near the stop) or curated from the press (data/dnf_causes.csv). "
            "Practice, qualifying and sprint qualifying: a car that STOPPED ON "
            "TRACK, found from the timing feed by f1lib/session_stops.py — it "
            "was running when a red flag, VSC or safety car came out, logged no "
            "timing at all (not even a pit entry) for 5 minutes after the flag, "
            "and never ran again — then attributed from the press. Families "
            "say who the stop is imputable to, as on the reliability card: the "
            "car (any failure, or the team calling a healthy car in) or the "
            "driver (a crash or off with no other car). Solid = an FIA record, "
            "hatched = mostly curated from the press. NOT drawn: collisions "
            f"({n_col}, imputable to neither), stops whose cause is not yet "
            f"known ({n_unk}), disqualifications, and running lost without a "
            f"stop of its own — did not run / did not take part / no time set "
            f"({n_lost}), usually the CONSEQUENCE of an earlier crash or "
            "failure, so counting it would count that event twice. Limits: a "
            "car that limps back to the pits is invisible to the timing feed "
            "and only appears if the press reports it; a stop in the last "
            "minutes of a session cannot be told from the flag; practice is "
            "tracked from 2023. A reserve driver in FP1 counts for his own "
            "name in the driver panel and for the car in the team panel. "
            "Why: the race-only reliability card misses most of what makes "
            "a driver crash-prone or a car unreliable — and a Friday crash "
            "costs the running that sets the car up for Sunday."),
    )
