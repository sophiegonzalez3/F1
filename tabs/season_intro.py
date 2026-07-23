"""
SEASON tab front door (newcomer Option C)
=========================================
Two panels pinned to the very top of the SEASON tab — the first thing anyone
lands on, and the least jargon-heavy part of the dashboard:

  1. story_so_far()   — a data-driven, plain-English recap of where the current
                        season stands (championship leaders, gaps, next race).
                        Always about the LATEST season (i.e. "now"), regardless
                        of the historical season dropdown lower down the tab.
  2. newcomer_primer()— a collapsed "New to F1?" explainer: how the sport and a
                        race weekend work, how points decide the title, and a
                        one-line map of every tab in this dashboard.

Both lean on f1lib/glossary.py for term hovers. See the [[newcomer-accessibility]]
memory for the wider plan (glossary + "in plain terms" strips are the other
two layers).
"""
from __future__ import annotations

import pandas as pd
from dash import html, callback, Input, Output, State
import dash_bootstrap_components as dbc

import f1lib.state as state
from f1lib.components import card
from f1lib.glossary import gloss
from f1lib.config import (
    ACCENT, CARD_BG, TEXT_MAIN, TEXT_DIM, GRID_CLR, TEAM_COLORS,
)
from f1lib.standings import (
    _driver_standings_after_round, _standings_after_round, HIST_DRIVER_STANDINGS,
)
from tabs.pace_data import season_calendar_df


def _fmt_team(t) -> str:
    t = str(t)
    for suf in (" F1 Team", " Racing"):
        if t.endswith(suf):
            t = t[: -len(suf)]
    return t


def _driver_names() -> dict[str, str]:
    """Abbreviation → full name, read from the loaded session's results (free,
    already in memory). Covers the current grid; unknown codes fall back to the
    abbreviation itself, so nothing ever renders blank."""
    r = getattr(state, "results_raw", None)
    if r is None or getattr(r, "empty", True):
        return {}
    if "Abbreviation" in r.columns and "FullName" in r.columns:
        return {str(a): str(n) for a, n in zip(r["Abbreviation"], r["FullName"])
                if str(n) and str(n) != "nan"}
    return {}


def _b(text, color=TEXT_MAIN):
    return html.Span(text, style={"fontWeight": "800", "color": color})


# ── Panel 1: the season story ────────────────────────────────

def story_so_far(season: int):
    """A short plain-English recap of the current championship picture. Returns
    a styled 'hero' card, or None if the standings archive can't answer."""
    ds = _driver_standings_after_round(season, None)   # {abbr: {pts, team}}
    ts = _standings_after_round(season, None)           # {team: pts}
    if not ds or not ts:
        return None
    names = _driver_names()

    # Championship leaders.
    dl = sorted(ds.items(), key=lambda kv: -kv[1]["pts"])
    d1_abbr, d1 = dl[0]
    d1_name = names.get(d1_abbr, d1_abbr)
    d1_team = _fmt_team(d1["team"])
    d1_clr = TEAM_COLORS.get(d1["team"], ACCENT)

    tl = sorted(ts.items(), key=lambda kv: -kv[1])
    t1_team, t1_pts = tl[0]
    t1_name = _fmt_team(t1_team)
    t1_clr = TEAM_COLORS.get(t1_team, ACCENT)

    # Calendar context: rounds done / total and the next race.
    cal = season_calendar_df()
    cal = cal[cal["season"] == season].copy() if not cal.empty else cal
    total = len(cal) if not cal.empty else None
    rounds_done = None
    if not HIST_DRIVER_STANDINGS.empty:
        sub = HIST_DRIVER_STANDINGS[HIST_DRIVER_STANDINGS["season"] == season]
        if not sub.empty:
            rounds_done = int(sub["round_number"].max())
    next_ev = None
    if not cal.empty:
        cal["_d"] = pd.to_datetime(cal["event_date"], errors="coerce")
        today = pd.Timestamp.now().normalize()
        up = cal[cal["_d"] >= today].sort_values("round")
        if not up.empty:
            next_ev = up.iloc[0]

    # ── Sentence 1: where we are in the calendar ──
    if rounds_done and total:
        prog = ["Round ", _b(f"{rounds_done} of {total}"), " done"]
    elif rounds_done:
        prog = [_b(f"{rounds_done}"), " rounds done"]
    else:
        prog = ["The ", _b(str(season)), " season is under way"]
    if next_ev is not None:
        when = next_ev["_d"]
        when_txt = when.strftime("%d %b") if pd.notna(when) else ""
        prog += [" — next up: ", _b(str(next_ev["event"])),
                 f" ({when_txt})." if when_txt else "."]
    else:
        prog += [" — the season is complete."]

    # ── Sentence 2: drivers' championship ──
    drv = ["In the ", *gloss("wdc", "drivers' championship"), ", ",
           _b(d1_name, d1_clr), " (", d1_team, ") leads with ",
           _b(f"{d1['pts']:.0f}"), " ", *gloss("points"), ]
    if len(dl) >= 2:
        d2_abbr, d2 = dl[1]
        gap = d1["pts"] - d2["pts"]
        d2_name = names.get(d2_abbr, d2_abbr)
        if gap >= 1:
            drv += [f", {gap:.0f} clear of ", _b(d2_name), "."]
        else:
            drv += [", level with ", _b(d2_name), " at the top."]
    else:
        drv += ["."]

    # ── Sentence 3: constructors' championship ──
    con = ["Among the teams, ", _b(t1_name, t1_clr), " top the ",
           *gloss("wcc", "constructors' championship"), " on ",
           _b(f"{t1_pts:.0f}"), " points"]
    if len(tl) >= 2:
        cgap = t1_pts - tl[1][1]
        con += [f", {cgap:.0f} ahead of ", _b(_fmt_team(tl[1][0])), "."] \
            if cgap >= 1 else [", tied with ", _b(_fmt_team(tl[1][0])), "."]
    else:
        con += ["."]

    para = {"color": TEXT_MAIN, "fontSize": "0.92rem", "lineHeight": "1.6",
            "marginBottom": "8px"}
    return html.Div([
        html.Div([
            html.Span("THE SEASON SO FAR", style={
                "color": ACCENT, "fontWeight": "900", "letterSpacing": "2px",
                "fontSize": "0.95rem"}),
            _primer_toggle_button(),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "alignItems": "center", "flexWrap": "wrap", "gap": "8px",
                  "marginBottom": "10px"}),
        html.P(prog, style=para),
        html.P(drv, style=para),
        html.P(con, style={**para, "marginBottom": 0}),
    ], style={
        "background": f"linear-gradient(135deg, {CARD_BG} 0%, #12122a 100%)",
        "border": f"1px solid {GRID_CLR}", "borderLeft": f"4px solid {ACCENT}",
        "borderRadius": "10px", "padding": "18px 22px", "marginBottom": "14px"})


# ── Panel 2: the "New to F1?" primer ─────────────────────────

def _primer_toggle_button():
    return dbc.Button(
        "New to F1?  ▾", id="newcomer-toggle", n_clicks=0, size="sm",
        color="link", style={
            "color": ACCENT, "fontWeight": "700", "fontSize": "0.85rem",
            "textDecoration": "none", "padding": "2px 8px",
            "border": f"1px solid {ACCENT}", "borderRadius": "6px"})


def _mini(title, body):
    return html.Div([
        html.Div(title, style={"color": ACCENT, "fontWeight": "800",
                               "fontSize": "0.82rem", "letterSpacing": "1px",
                               "marginBottom": "4px"}),
        html.Div(body, style={"color": TEXT_MAIN, "fontSize": "0.85rem",
                              "lineHeight": "1.55"}),
    ], style={"marginBottom": "14px"})


_TAB_MAP = [
    ("SEASON", "the whole-season picture. Championship tables and the calendar, "
               "but also the strategic engine room — budget-cap and wind-tunnel "
               "limits, whether each car upgrade actually worked, reliability, "
               "the driver market and staff moves. Where the season's story "
               "gets told (you're here)."),
    ("TRACK", "a scouting report on this weekend's circuit — its layout and "
              "corner types, what it physically demands of car and tyres, how "
              "pole times have fallen over the years, and which tyre compounds "
              "were brought."),
    ("WEEK END PRED", "the weekend as it builds. Reads the practice sessions "
                      "for real pace, flags who's sandbagging (hiding their "
                      "true speed), and runs a model that predicts the "
                      "qualifying order — then keeps score against what "
                      "actually happens."),
    ("TELEMETRY", "the lap under a microscope. Each car's speed, throttle and "
                  "braking through every corner, mini-sector time deltas, "
                  "racing lines, and a map of where on track each car is "
                  "strongest."),
    ("STINTS", "the tyre story, and the heart of race strategy — how fast each "
               "compound wears, where a set falls off the performance 'cliff', "
               "and how long runs really compare once fuel load and track "
               "evolution are stripped out."),
    ("QUALI", "Saturday's one-lap shootout. The starting grid and any "
              "penalties, the Q1-Q2-Q3 knockout, who left lap time unused — "
              "plus a 3D replay of the fastest lap on the real circuit."),
    ("RACE", "Sunday in full. An animated race replay, pit-stop execution, "
             "undercut/overcut duels, a what-if strategy simulator, wet-vs-dry "
             "crossovers, and even the transcribed team radio."),
    ("DUEL", "a head-to-head battle planner. Pick any two drivers and see where "
             "one is quicker, who owns which corner, where the target tends to "
             "crack under pressure, and the plan to beat them."),
    ("TEAM & TEAMATE", "team versus team, then the duel inside each garage — "
                       "constructor pace and momentum up top, and below it the "
                       "two team-mates in equal cars measured head-to-head."),
]


def newcomer_primer():
    """The collapsed 'New to F1?' explainer content (a dbc.Collapse body)."""
    weekend_flow = html.Div([
        html.Span("Practice", style={"fontWeight": "700"}),
        " → ",
        html.Span("Qualifying", style={"fontWeight": "700"}),
        " (Saturday — sets the starting order; the fastest single lap earns ",
        *gloss("pole position", "pole"), ") → ",
        html.Span("Race", style={"fontWeight": "700"}),
        " (Sunday — where the ", *gloss("points"),
        " are won). A few weekends add a short ", *gloss("sprint"), " race."],
        style={"marginBottom": "6px"})
    weekend_note = html.Div([
        "Practice is not a warm-up lap — it's where each team ",
        _b("sets its car up for this particular track"), ". Every circuit is "
        "different (tight street courses, long high-speed sweeps, heavy-braking "
        "stop-and-go — nothing like an oval), the weather shifts, and the cars "
        "themselves are ", _b("rebuilt and upgraded from race to race"),
        " all season — so the setup that worked last time may be wrong here. "
        "Teams use the practice hours to dial in wings, suspension and ",
        *gloss("compound", "tyres"), " against the clock before it counts."],
        style={"color": TEXT_DIM, "fontSize": "0.82rem", "lineHeight": "1.5"})
    weekend = html.Div([weekend_flow, weekend_note])

    tab_intro = html.Div(
        ["Nine tabs, running from the big picture down to the finest detail — "
         "roughly following a race weekend, from the season around it to a "
         "single corner within it:"],
        style={"color": TEXT_MAIN, "fontSize": "0.85rem", "lineHeight": "1.55",
               "marginBottom": "8px"})
    tab_list = html.Ul([
        html.Li([html.Span(name + " — ", style={"fontWeight": "700",
                                                 "color": TEXT_MAIN}), desc],
                style={"marginBottom": "7px", "color": TEXT_DIM,
                       "fontSize": "0.83rem", "lineHeight": "1.5"})
        for name, desc in _TAB_MAP
    ], style={"paddingLeft": "18px", "marginBottom": 0})
    tabs_block = html.Div([tab_intro, tab_list])

    how = html.Div([
        "Three things that help everywhere: hover any ",
        html.Span("underlined word", style={
            "borderBottom": "1px dotted currentColor", "cursor": "help"}),
        " for a plain definition; look for the ",
        html.Span("IN PLAIN TERMS", style={
            "color": ACCENT, "fontWeight": "700", "fontSize": "0.72rem",
            "letterSpacing": "1px"}),
        " box under a chart for what it's actually saying; and note that ",
        _b("each team keeps the same colour on every chart"),
        " (Ferrari red, McLaren orange, Mercedes teal, …), so you can follow "
        "one team from card to card across the whole dashboard."])

    return card("New to Formula 1? Start here", html.Div([
        _mini("What is Formula 1?", [
            "The top class of single-seater motor racing: ", _b("10 teams"),
            " (called ", *gloss("constructor", "constructors"),
            ") each enter ", _b("two cars"), ", racing roughly ",
            _b("24 times"), " a year at circuits around the world. The car "
            "first across the line wins the race."]),
        _mini("A race weekend", weekend),
        _mini("More than racing — it's a strategy sport", [
            "This is what the dashboard is really about. Races are rarely won "
            "on raw speed alone: F1 is a contest of ",
            _b("managing limited resources better than your rivals"),
            ". Every team runs to a fixed yearly ", _b("spending cap"),
            ", a capped pool of engine parts and ",
            *gloss("tyre allocation", "tyre sets"),
            ", wind-tunnel time rationed by championship position, and hundreds "
            "of staff. Winning comes from ",
            _b("out-developing, out-thinking and out-timing"), " the other "
            "side — when to ", *gloss("pit stop", "pit"), ", how to nurse ",
            *gloss("degradation", "tyre wear"), ", where to spend the budget. A "
            "well-timed strategy beats a faster car. If you only care who "
            "crosses the line first, that's the surface — the depth underneath "
            "is what everything here measures."]),
        _mini("How you win", [
            "There are ", _b("two titles"), " each year: the ",
            *gloss("wdc", "Drivers' Championship"), " for the best driver and "
            "the ", *gloss("wcc", "Constructors' Championship"),
            " for the best team (its two cars combined). After every race the "
            "top ten finishers score ", *gloss("points"), " — ",
            _b("25 for a win"), ", then 18, 15, 12, 10, 8, 6, 4, 2 and 1 for "
            "tenth place; ", *gloss("sprint", "sprint"), " races add a few more "
            "for the top eight. Totals build up across all ~24 races, so the "
            "champion is ", _b("whoever is most consistently fast over the "
            "whole season"), " — not just whoever wins the most.",
            html.Div([
                "And there's a hard edge to it: ",
                _b("finish eleventh or lower and you score nothing"),
                ". That cliff shapes everyone's strategy. A team with both cars "
                "near the cut-off may ",
                _b("sacrifice one race to protect the other"), " — a contrarian "
                "tyre call, an early stop, or having one driver deliberately "
                "hold up a rival. And for ",
                _b("midfield and back-of-grid teams"), ", whose whole season "
                "can turn on a handful of points, the maths flips entirely: it "
                "can be worth ", _b("gambling everything on one bold strategy"),
                ", or simply banking on chaos — a wet track, a ",
                *gloss("safety car"), ", a first-lap tangle ahead. One lucky "
                "afternoon can rewrite a season, like Alpine's shock double "
                "podium in wet Brazil 2024, which hauled them up the "
                "constructors' table in a single race.",
            ], style={"marginTop": "8px"}),
        ]),
        _mini("Two cars per team — and a delicate rivalry", [
            "Each team runs ", _b("two cars"), ", and because they are meant to "
            "be ", _b("identical machinery"), ", a driver's ",
            *gloss("teammate"), " is the fairest measure of how good they "
            "really are — and usually the ",
            _b("first person they're expected to beat"),
            ". That makes the two sides of a garage quietly political: they "
            "share data and both want the team to score, yet each is the "
            "other's closest yardstick, and who gets priority on upgrades, "
            "pit-stop order or strategy can decide a career. The ",
            _b("TEAM & TEAMATE"), " and ", _b("DUEL"),
            " tabs are built around these intra-team battles."]),
        _mini("Why tyres matter so much", [
            "Every car must make at least one ", *gloss("pit stop"),
            " to change ", *gloss("tyre allocation", "tyres"), ". Softer ",
            *gloss("compound", "tyres"), " are faster but wear out sooner, so "
            "deciding when to stop — the ", *gloss("undercut"),
            " and ", *gloss("overcut"), " — is a huge part of race strategy."]),
        _mini("The tabs — what each one is for", tabs_block),
        html.Div(how, style={"color": TEXT_DIM, "fontSize": "0.8rem",
                             "lineHeight": "1.5", "borderTop":
                             f"1px solid {GRID_CLR}", "paddingTop": "10px",
                             "marginTop": "4px"}),
    ]))


def season_intro_block(latest_season: int):
    """The full front-door block: the season story + the collapsible primer."""
    story = story_so_far(latest_season)
    parts = []
    if story is not None:
        parts.append(story)
    else:
        # No standings archive — still offer the primer via a bare button.
        parts.append(html.Div(_primer_toggle_button(),
                              style={"marginBottom": "10px"}))
    parts.append(dbc.Collapse(newcomer_primer(), id="newcomer-primer",
                              is_open=False))
    return html.Div(parts)


@callback(Output("newcomer-primer", "is_open"),
          Input("newcomer-toggle", "n_clicks"),
          State("newcomer-primer", "is_open"),
          prevent_initial_call=True)
def _toggle_primer(n, is_open):
    return not is_open
