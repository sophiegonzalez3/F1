"""
TRACK tab — circuit reference: profile radar, weekend guide, all-time history
card, mini-sector heatmap, circuit-characteristics table, corner + straight
lists, and the on-demand track map with corner labels, gear-shift heatmap,
elevation profile and DRS/active-aero zones. Plus the historical race and
qualifying results (every archived season, side by side).

Also owns the track-map fetch/cache (`get_track_map`) which the TELEMETRY tab
imports lazily for its corner markers.
Extracted from app.py.
"""
from __future__ import annotations

import json as _json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import (
    html, dcc, dash_table, callback, no_update,
    Input, Output, State,
)
import dash_bootstrap_components as dbc

import f1lib.state as state
from f1lib.components import (
    theme, card, kpi, GFX, TABLE_STYLE, styled_table,
    badge as _badge, abbr as _abbr, hex_to_rgba as _hex_to_rgba,
)
from f1lib.config import (
    TEAM_COLORS, COMPOUND_COLORS,
    CARD_BG, ACCENT, TEXT_MAIN, TEXT_DIM, GRID_CLR,
    MINI_SECTORS, FASTF1_CACHE_DIR,
    HIST_CIRCUIT_KEY_MAP,
)
from f1lib.processing import format_lap_time
from f1lib.figures import _tyre_history_chart
from tabs.circuit_stats import (
    measured_weekend_card, pole_evolution_card, tyre_allocation_card,
    pirelli_card,
)
from f1lib.standings import (
    HIST_RACE, HIST_QUALI, HIST_STANDINGS,
    _loaded_event, _loaded_circuit_key, _slugify_event,
    _track_avail_years, _circuit_race_years, _circuit_display_season,
    _loaded_meeting_season_round,
)

# mirror state so bare `laps`, `LOADED_SESSION_INFO`, CIRCUIT_CHARS references resolve
state.register(globals())


# CIRCUIT_CHARS is loaded in app.py's startup block. Expose it through a
# module-level attribute that stays in sync via `sync_circuit_chars()`,
# called by app.py right after it loads the CSV. Until then the getter
# returns an empty frame so this module can still import cleanly.
CIRCUIT_CHARS: pd.DataFrame = pd.DataFrame()


def sync_circuit_chars(df: pd.DataFrame) -> None:
    """Called by app.py after loading data/circuit_characteristics.csv so this
    module can share the same DataFrame view."""
    global CIRCUIT_CHARS
    CIRCUIT_CHARS = df


# ══════════════════════════════════════════════════════════════
# TRACK MAP — circuit layout, corner annotations, gear-shift map
# (recreates the FastF1 examples in Plotly; data fetched on demand
#  from a fast lap and cached to data/track_maps/ for instant reuse)
# ══════════════════════════════════════════════════════════════
import json as _json

TRACK_MAPS_DIR = Path("data/track_maps")

# Distinct colours for gears 1–8 (readable on the dark theme).
GEAR_COLORS = {
    1: "#3B82F6", 2: "#22D3EE", 3: "#10B981", 4: "#A3E635",
    5: "#FACC15", 6: "#FB923C", 7: "#EF4444", 8: "#E879F9",
}
from tabs.teammates import tab_teammates


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
    "australie":       {"length_km": 5.278, "corners": 14, "drs_zones": 4, "lap_record": "1:19.813", "lap_record_driver": "Charles Leclerc",     "lap_record_year": 2024},
    "bahrein":         {"length_km": 5.412, "corners": 15, "drs_zones": 3, "lap_record": "1:31.447", "lap_record_driver": "Pedro de la Rosa",    "lap_record_year": 2005},
    "chine":           {"length_km": 5.451, "corners": 16, "drs_zones": 2, "lap_record": "1:32.238", "lap_record_driver": "Michael Schumacher",  "lap_record_year": 2004},
    "emilie_romagne":  {"length_km": 4.909, "corners": 19, "drs_zones": 2, "lap_record": "1:15.484", "lap_record_driver": "Lewis Hamilton",      "lap_record_year": 2020},
    "miami":           {"length_km": 5.412, "corners": 19, "drs_zones": 3, "lap_record": "1:29.708", "lap_record_driver": "Max Verstappen",      "lap_record_year": 2023},
    "las_vegas":       {"length_km": 6.201, "corners": 17, "drs_zones": 2, "lap_record": "1:35.490", "lap_record_driver": "Oscar Piastri",       "lap_record_year": 2023},
}

# ── Notable corners by circuit ────────────────────────────────
_NOTABLE_CORNERS: dict = {
    "italie":          ["T1 Prima Variante (chicane)", "T4 Seconda Variante (chicane)", "T11 Parabolica (Curva Alboreto)"],
    "monaco":          ["T1 Sainte-Dévote", "T6 Massenet", "T10 Casino", "T17 Mirabeau", "T19 Fairmont Hairpin", "T23 Rascasse", "T25 Antony Noghes"],
    "grande_bretagne": ["T1 Abbey", "T2 Farm Curve", "T3 Village", "T4 The Loop", "T5 Aintree", "T6 Brooklands", "T7 Luffield", "T8 Woodcote", "T9 Copse", "T10-T14 Maggotts / Becketts / Chapel", "T15 Stowe", "T16 Vale", "T18 Club"],
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
    "australie":       ["T1-T3 opening complex", "T6 fast left", "T9-T10 sweepers", "T11-T12 high speed", "T13 final corner"],
    "bahrein":         ["T1 heavy braking", "T4 hairpin", "T8 left-hander", "T10 hairpin", "T11-T13 esses"],
    "chine":           ["T1-T4 snail spiral", "T6 hairpin", "T11-T13 long hairpin", "T14 onto back straight"],
    "emilie_romagne":  ["T2-T3 Tamburello chicane", "T5 Villeneuve", "T7-T8 Acque Minerali", "T9-T10 Variante Alta", "T14-T15 Rivazza"],
    "miami":           ["T1 Turn 1", "T4-T6 esses", "T7-T8 sweepers", "T11-T16 technical sector", "T17 final corner"],
    "las_vegas":       ["T1-T2 opening", "T5-T7 chicane", "T9 hairpin", "T12 Sphere corner", "T14 onto the Strip", "T16-T17 final"],
}

# ── Named straights by circuit ────────────────────────────────
# Each straight is (after_corner, name): it is the stretch of track between the
# corner with FastF1 number `after_corner` and the next corner (wrapping past the
# start/finish line for the final corner). Placed at the mid-point of the two
# corner positions on the layout plot. Corner numbering was verified against the
# cached track maps in data/track_maps/ — add more circuits after checking theirs.
_NAMED_STRAIGHTS: dict = {
    "grande_bretagne": [(5, "Wellington Straight"), (14, "Hangar Straight"),
                        (18, "Hamilton Straight")],
    "belgique":        [(4, "Kemmel Straight")],
}

# ── All-time circuit history & records ────────────────────────
# Curated Formula 1 records for each venue (through the 2025 season). The local
# results archive only spans 2021+, so these all-time facts are hand-maintained.
# most_wins / most_poles are (driver, count); count=None shows the name only.
_CIRCUIT_HISTORY: dict = {
    "grande_bretagne": {"first_gp": 1950, "most_wins": ("Lewis Hamilton", 9),
        "most_poles": ("Lewis Hamilton", None),
        "note": "Host of the first-ever Formula 1 World Championship race (13 May 1950). "
                "Lewis Hamilton is the most successful driver in British Grand Prix history."},
    "monaco": {"first_gp": 1950, "most_wins": ("Ayrton Senna", 6),
        "most_poles": ("Ayrton Senna", None), "most_constructor": "McLaren",
        "note": "Run through the streets of Monte Carlo since 1929; on the F1 calendar since 1950. "
                "The most prestigious race in the sport and the hardest place to overtake."},
    "italie": {"first_gp": 1950, "most_wins": ("Schumacher & Hamilton", 5),
        "most_poles": ("Lewis Hamilton", None), "most_constructor": "Ferrari",
        "note": "The 'Temple of Speed' — the fastest circuit on the calendar and, alongside "
                "Silverstone, a fixture since the 1950 championship."},
    "belgique": {"first_gp": 1950, "most_wins": ("Michael Schumacher", 6),
        "most_poles": ("Lewis Hamilton", None),
        "note": "Spa-Francorchamps: Schumacher took his first F1 win here in 1992 and a record "
                "six victories overall. Home of Eau Rouge / Raidillon and the Kemmel Straight."},
    "japon": {"first_gp": 1976, "most_wins": ("Michael Schumacher", 6),
        "most_poles": ("Michael Schumacher", None),
        "note": "Suzuka's figure-of-eight layout has decided numerous championships. "
                "Schumacher holds the record with six wins."},
    "hongrie": {"first_gp": 1986, "most_wins": ("Lewis Hamilton", 8),
        "most_poles": ("Lewis Hamilton", None),
        "note": "The tight, twisty Hungaroring — 'Monaco without the walls'. Hamilton owns the "
                "circuit with a record eight wins and the most poles."},
    "espagne": {"first_gp": 1991, "most_wins": ("Schumacher & Hamilton", 6),
        "most_poles": ("Lewis Hamilton", None),
        "note": "Barcelona-Catalunya is F1's benchmark test track — teams know every metre from "
                "winter testing, so it rewards outright car performance."},
    "autriche": {"first_gp": 1970, "most_wins": ("Max Verstappen", 5),
        "most_poles": ("Max Verstappen", None),
        "note": "The Red Bull Ring in the Styrian mountains: short, fast and Red Bull's home "
                "race, where Verstappen has dominated the modern era."},
    "pays_bas": {"first_gp": 1952, "most_wins": ("Max Verstappen", 3),
        "note": "Zandvoort returned to the calendar in 2021 with banked corners; Verstappen "
                "won the first three home races in front of the Orange Army."},
    "canada": {"first_gp": 1967, "most_wins": ("Lewis Hamilton", 7),
        "most_poles": ("Lewis Hamilton", None),
        "note": "The Circuit Gilles Villeneuve in Montréal, famous for the 'Wall of Champions'. "
                "Hamilton leads all drivers with seven wins here."},
    "singapour": {"first_gp": 2008, "most_wins": ("Sebastian Vettel", 5),
        "note": "F1's original night race (since 2008). A brutal, humid street fight around "
                "Marina Bay where Vettel took a record five wins."},
    "etats_unis": {"first_gp": 2012, "most_wins": ("Lewis Hamilton", 5),
        "note": "The Circuit of the Americas in Austin — a modern classic mixing Silverstone- "
                "and Hockenheim-inspired corners. (US GPs have run at many venues since 1959.)"},
    "mexique": {"first_gp": 1963, "most_wins": ("Max Verstappen", 5),
        "note": "The high-altitude Autódromo Hermanos Rodríguez — thin air hurts downforce and "
                "cooling. The stadium section is one of F1's great atmospheres."},
    "bresil": {"first_gp": 1973, "most_wins": ("Michael Schumacher", 4),
        "note": "Interlagos: an old-school, anti-clockwise rollercoaster that has hosted many "
                "title-deciders and is beloved for unpredictable weather."},
    "abu_dhabi": {"first_gp": 2009, "most_wins": ("Lewis Hamilton", 5),
        "note": "Yas Marina hosts the season finale under floodlights at dusk — the stage for "
                "the dramatic 2021 title decider."},
    "australie": {"first_gp": 1985, "most_wins": ("Michael Schumacher", 4),
        "note": "Melbourne's Albert Park has traditionally opened the season — a semi-street "
                "circuit round a lake, reprofiled in 2022 to be faster."},
    "bahrein": {"first_gp": 2004, "most_wins": ("Lewis Hamilton", 5),
        "note": "The desert Bahrain International Circuit, often the season opener and a "
                "regular pre-season test venue. Raced under lights since 2014."},
    "chine": {"first_gp": 2004, "most_wins": ("Lewis Hamilton", 6),
        "most_poles": ("Lewis Hamilton", None),
        "note": "The Shanghai International Circuit, shaped like the character 上 (shàng). "
                "Hamilton is the most successful driver here."},
    "azerbaidjan": {"first_gp": 2016, "most_poles": ("Charles Leclerc", None),
        "note": "The Baku City Circuit pairs medieval-castle tight sections with F1's longest "
                "flat-out run — chaos and safety cars are almost guaranteed."},
    "arabie_saoudite": {"first_gp": 2021,
        "note": "Jeddah's Corniche Circuit is the fastest street track in F1 — 27 corners of "
                "high-speed walls with barely a breath between them."},
    "qatar": {"first_gp": 2021,
        "note": "The flowing Lusail International Circuit, a former MotoGP venue, punishes "
                "tyres with its long, fast, sweeping corners."},
    "emilie_romagne": {"first_gp": 1980,
        "note": "Imola (Autodromo Enzo e Dino Ferrari) — an old-school, anti-clockwise circuit "
                "steeped in history and one of the few with no significant run-off."},
    "miami": {"first_gp": 2022, "most_wins": ("Max Verstappen", 2),
        "note": "The Miami International Autodrome laid out around the Hard Rock Stadium — a "
                "showpiece venue that anchors F1's growth in the United States."},
    "las_vegas": {"first_gp": 2023, "most_wins": ("Max Verstappen", 2),
        "note": "A high-speed night race down the Las Vegas Strip — F1's most glamorous "
                "spectacle, run in cold desert conditions that challenge tyre warm-up."},
}

# ── Race-weekend guide (pre-weekend orientation) ──────────────
# Typical, characteristic facts per venue — what a fan checks before the weekend.
# overtaking ∈ {Easy, Moderate, Hard, Very hard}; safety_car ∈ {Low, Medium, High};
# strategy is the usual number of stops; race distance is derived (laps × length).
# These are typical patterns, not guarantees — weather and incidents vary yearly.
_CIRCUIT_WEEKEND: dict = {
    "italie":          {"laps": 53, "overtaking": "Easy",      "safety_car": "Low",    "strategy": "1-stop",
        "note": "A low-downforce specialist track where slipstreaming makes overtaking easy. Tyre deg is low, so it's usually a one-stopper decided by top speed and the braking zones into the Rettifilo and Ascari chicanes."},
    "monaco":          {"laps": 78, "overtaking": "Very hard", "safety_car": "High",   "strategy": "1-stop",
        "note": "Qualifying is everything — overtaking is almost impossible, so track position and a clean Saturday define the race. Very high safety-car risk can flip the order in an instant."},
    "grande_bretagne": {"laps": 52, "overtaking": "Moderate",  "safety_car": "Medium", "strategy": "1–2 stop",
        "note": "Fast, flowing corners (Maggotts–Becketts) reward aero; the Hangar and Wellington straights plus two DRS zones give decent passing. British-summer weather can swing the strategy."},
    "belgique":        {"laps": 44, "overtaking": "Easy",      "safety_car": "Medium", "strategy": "1–2 stop",
        "note": "The longest lap on the calendar; the Kemmel Straight after Eau Rouge is a prime passing spot. Weather is famously fickle — it can rain on one part of the circuit and stay dry on another."},
    "japon":           {"laps": 53, "overtaking": "Hard",      "safety_car": "Low",    "strategy": "2-stop",
        "note": "A pure drivers' circuit — the high-speed Esses and 130R reward commitment. Overtaking is tricky, so qualifying position and tyre management are decisive."},
    "singapour":       {"laps": 62, "overtaking": "Hard",      "safety_car": "High",   "strategy": "1–2 stop",
        "note": "A hot, humid night race on a bumpy street circuit — one of the most physically demanding of the year. Safety cars are near-guaranteed and routinely reshuffle strategy."},
    "azerbaidjan":     {"laps": 51, "overtaking": "Easy",      "safety_car": "High",   "strategy": "1-stop",
        "note": "A 2.2 km flat-out run creates huge slipstream battles and late-braking passes into Turn 1; walls line the old-town section and a high safety-car rate produces frequent chaos."},
    "arabie_saoudite": {"laps": 50, "overtaking": "Moderate",  "safety_car": "High",   "strategy": "1-stop",
        "note": "The fastest street circuit in F1 — long flat-out sections with DRS give overtaking chances, but the walls are close and safety cars are common."},
    "hongrie":         {"laps": 70, "overtaking": "Very hard", "safety_car": "Low",    "strategy": "2-stop",
        "note": "Tight, twisty and narrow — 'Monaco without the walls'. Track position is king; expect an undercut-driven strategy race in the mid-summer heat."},
    "espagne":         {"laps": 66, "overtaking": "Hard",      "safety_car": "Low",    "strategy": "2-stop",
        "note": "The ultimate aero test track — dirty air makes following hard, so it rewards outright car performance and tyre management over wheel-to-wheel action."},
    "autriche":        {"laps": 71, "overtaking": "Easy",      "safety_car": "Medium", "strategy": "2-stop",
        "note": "A short lap with three DRS zones and long uphill straights makes passing easy; watch for track-limits lap deletions at the exit kerbs of the final corners."},
    "pays_bas":        {"laps": 72, "overtaking": "Hard",      "safety_car": "Medium", "strategy": "1–2 stop",
        "note": "Old-school, narrow and banked (Turns 3 & 14). Overtaking is difficult, so qualifying and the undercut are decisive; coastal wind shifts the grip through the day."},
    "qatar":           {"laps": 57, "overtaking": "Moderate",  "safety_car": "Low",    "strategy": "2–3 stop",
        "note": "Fast, flowing and very hard on tyres — Pirelli often caps stint length, forcing multiple stops. A night race in the desert on a smooth, high-energy surface."},
    "canada":          {"laps": 70, "overtaking": "Easy",      "safety_car": "High",   "strategy": "1-stop",
        "note": "A stop-go, low-grip semi-street circuit with long straights and heavy braking; the Wall of Champions catches drivers out and safety cars are common."},
    "etats_unis":      {"laps": 56, "overtaking": "Easy",      "safety_car": "Medium", "strategy": "1–2 stop",
        "note": "A bumpy, anti-clockwise mix of Silverstone- and Hockenheim-style corners with a big DRS straight; the uphill Turn 1 is a classic passing spot."},
    "mexique":         {"laps": 71, "overtaking": "Moderate",  "safety_car": "Medium", "strategy": "1-stop",
        "note": "At 2,240 m altitude the thin air cuts downforce and cooling; the enormous run to Turn 1 is one of the longest braking zones of the year, and the stadium section is electric."},
    "bresil":          {"laps": 71, "overtaking": "Easy",      "safety_car": "Medium", "strategy": "1–2 stop",
        "note": "Short, anti-clockwise and undulating with a great slipstream into Turn 1; changeable weather regularly produces classics. Usually a Sprint weekend."},
    "abu_dhabi":       {"laps": 58, "overtaking": "Moderate",  "safety_car": "Low",    "strategy": "1-stop",
        "note": "A twilight-to-night season finale; the 2021 redesign improved flow and overtaking. Falling track temperature through the race helps the tyres."},
    "australie":       {"laps": 58, "overtaking": "Moderate",  "safety_car": "Medium", "strategy": "1–2 stop",
        "note": "A fast, semi-street park circuit (reprofiled in 2022) with four DRS zones; the walls are close and safety cars can appear. Often the season opener."},
    "bahrein":         {"laps": 57, "overtaking": "Easy",      "safety_car": "Medium", "strategy": "2-stop",
        "note": "High tyre degradation on an abrasive surface under lights — a genuine two-stopper where rear-tyre management and traction out of the slow corners decide it."},
    "chine":           {"laps": 56, "overtaking": "Moderate",  "safety_car": "Medium", "strategy": "2-stop",
        "note": "The long back straight into the tight Turn 14 hairpin is a prime DRS passing zone; the snail-shell Turn 1–4 punishes the front-left tyre. Usually a Sprint weekend."},
    "emilie_romagne":  {"laps": 63, "overtaking": "Very hard", "safety_car": "Medium", "strategy": "1-stop",
        "note": "Narrow, old-school and anti-clockwise with aggressive kerbs and gravel traps — overtaking is very hard, so qualifying and the undercut are crucial."},
    "miami":           {"laps": 57, "overtaking": "Moderate",  "safety_car": "Medium", "strategy": "1-stop",
        "note": "A fast street-style circuit around the stadium with three DRS zones; a slow, technical middle sector contrasts with long flat-out runs. Can be extremely hot and humid."},
    "las_vegas":       {"laps": 50, "overtaking": "Easy",      "safety_car": "High",   "strategy": "1–2 stop",
        "note": "Enormous top speeds down the Strip in low-grip, cold-night conditions that make tyre warm-up and braking treacherous; safety cars are likely."},
}


def _corner_name_map(circuit_key) -> dict[int, str]:
    """Parse _NOTABLE_CORNERS ('T7 Eau Rouge', 'T1-T3 opening complex', …) into
    {corner_number: name} so named corners can be labelled on the track map."""
    import re
    out: dict[int, str] = {}
    for item in _NOTABLE_CORNERS.get(circuit_key, []):
        m = re.match(r"\s*T(\d+)(?:\s*[-–]\s*T?(\d+))?\s+(.*)", str(item))
        if not m:
            continue
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        name = m.group(3).strip()
        for n in range(a, b + 1):
            out.setdefault(n, name)
    return out

# ── All-time history & records card ───────────────────────────
def _history_card(circuit_key) -> html.Div:
    """Curated all-time F1 records for this venue (most wins, most poles, first
    GP, historical note). Returns an empty Div when no data is curated."""
    h = _CIRCUIT_HISTORY.get(circuit_key)
    if not h:
        return html.Div()

    def _person(pair):
        drv, n = pair
        return f"{drv} — {n}" if n else drv

    pills = []
    if h.get("first_gp"):
        pills.append(_stat_pill("FIRST F1 GP", str(h["first_gp"])))
    if h.get("most_wins"):
        pills.append(_stat_pill("MOST WINS", _person(h["most_wins"]), "#FFD700"))
    if h.get("most_poles"):
        pills.append(_stat_pill("MOST POLES", _person(h["most_poles"]), "#00D2BE"))
    if h.get("most_constructor"):
        pills.append(_stat_pill("TOP CONSTRUCTOR", h["most_constructor"]))

    children = [html.Div(pills, style={
        "display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "10px",
    })]
    if h.get("note"):
        children.append(html.P(h["note"], style={
            "color": TEXT_DIM, "fontSize": "0.8rem", "marginBottom": 0,
            "lineHeight": "1.45",
        }))
    return card(
        "Track History & Records",
        html.Div(children),
        info=("Data: curated all-time Formula 1 records for this venue (through the "
              "2025 season) — first championship Grand Prix, the driver with the most "
              "wins and poles here, and a short historical note. Why: the season "
              "leaderboards below only cover recent years, so this gives the deeper "
              "context of who has owned this circuit across F1 history."),
    )


# ── Race-weekend guide card ───────────────────────────────────
_OVERTAKE_CLR = {"Easy": "#2ECC71", "Moderate": "#FFD700",
                 "Hard": "#FF8700", "Very hard": "#E10600"}
_SC_CLR       = {"Low": "#2ECC71", "Medium": "#FFD700", "High": "#E10600"}


def _weekend_card(circuit_key) -> html.Div:
    """Pre-weekend orientation: race distance, overtaking difficulty, safety-car
    likelihood, typical strategy and what tends to decide the race."""
    w = _CIRCUIT_WEEKEND.get(circuit_key)
    if not w:
        return html.Div()
    meta = _FF1_CIRCUIT_META.get(circuit_key, {})

    pills = []
    if w.get("laps"):
        length = meta.get("length_km")
        val = f"{w['laps']} laps" + (f" · ~{round(w['laps'] * length)} km" if length else "")
        pills.append(_stat_pill("RACE DISTANCE", val))
    if w.get("overtaking"):
        pills.append(_stat_pill("OVERTAKING", w["overtaking"],
                                _OVERTAKE_CLR.get(w["overtaking"])))
    if w.get("safety_car"):
        pills.append(_stat_pill("SAFETY CAR", w["safety_car"],
                                _SC_CLR.get(w["safety_car"])))
    if w.get("strategy"):
        pills.append(_stat_pill("TYPICAL RACE", w["strategy"], "#00D2BE"))

    children = [html.Div(pills, style={
        "display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "10px",
    })]
    if w.get("note"):
        children.append(html.P([
            html.Span("What to watch — ", style={"color": TEXT_MAIN, "fontWeight": "700"}),
            w["note"],
        ], style={"color": TEXT_DIM, "fontSize": "0.8rem", "marginBottom": 0,
                  "lineHeight": "1.45"}))
    return card(
        "Race Weekend Guide",
        html.Div(children),
        info=("Data: curated, characteristic facts for this circuit — typical race "
              "distance, how hard overtaking is, safety-car likelihood and the usual "
              "tyre strategy, plus what tends to decide the race. Why: a quick "
              "orientation before the weekend. Note: overtaking, safety-car and "
              "strategy are typical patterns, not guarantees — weather and incidents "
              "vary year to year."),
    )


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
def _race_total_label(seconds: float) -> str:
    """Race-winner total time → 'h:mm:ss.s' (format_lap_time is for laps)."""
    if pd.isna(seconds) or seconds <= 0:
        return "—"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:04.1f}" if h >= 1 else f"{int(m)}:{s:04.1f}"


def _hist_year_column(sub: pd.DataFrame, sess_type: str, year: int) -> html.Div:
    """One compact classification column: position, team-coloured driver
    chip, time (leader) or gap. Race rows show Status when they didn't
    finish; quali time = best of Q1/Q2/Q3."""
    abbr_col = next((c for c in ("Abbreviation", "DriverId", "Driver")
                     if c in sub.columns), None)
    team_col = next((c for c in ("TeamName", "ConstructorName", "Team")
                     if c in sub.columns), None)
    sub = sub.copy()
    sub["_pos"] = pd.to_numeric(sub.get("Position"), errors="coerce")
    sub = sub.sort_values("_pos", na_position="last").reset_index(drop=True)

    rows = []
    if sess_type == "Qualifying":
        best = sub[[c for c in ("Q1", "Q2", "Q3") if c in sub.columns]].min(axis=1)
        pole = best.dropna().min()
        labels = [format_lap_time(t) if i == 0 and pd.notna(t) else
                  (f"+{t - pole:.3f}" if pd.notna(t) and pd.notna(pole) else "—")
                  for i, t in enumerate(best)]
    else:
        t = pd.to_numeric(sub.get("Time"), errors="coerce")
        status = sub.get("Status", pd.Series("", index=sub.index)).astype(str)
        labels = []
        for i in range(len(sub)):
            if i == 0 and pd.notna(t.iloc[i]):
                labels.append(_race_total_label(t.iloc[i]))       # winner: total
            elif pd.notna(t.iloc[i]):
                labels.append(f"+{t.iloc[i]:.1f}")                # gap to winner
            else:
                labels.append(status.iloc[i] if status.iloc[i] not in
                              ("", "nan", "Finished") else "—")   # DNF / +1 Lap

    for i, r in sub.iterrows():
        drv = str(r[abbr_col]).strip() if abbr_col else "?"
        team = str(r[team_col]).strip() if team_col else ""
        clr = TEAM_COLORS.get(team, "#808080")
        rows.append(html.Div([
            html.Span(f"{int(r['_pos'])}" if pd.notna(r["_pos"]) else "–",
                      style={"color": TEXT_DIM, "fontSize": "0.62rem",
                             "width": "16px", "textAlign": "right",
                             "marginRight": "5px", "flexShrink": "0"}),
            html.Span(drv, title=team, style={
                "background": clr, "color": "#fff", "borderRadius": "3px",
                "padding": "0px 5px", "fontSize": "0.66rem",
                "fontWeight": "700", "marginRight": "6px",
                "width": "38px", "textAlign": "center", "flexShrink": "0"}),
            html.Span(labels[i], style={"color": TEXT_MAIN,
                                        "fontSize": "0.64rem",
                                        "fontVariantNumeric": "tabular-nums",
                                        "whiteSpace": "nowrap"}),
        ], style={"display": "flex", "alignItems": "center",
                  "marginBottom": "3px"}))

    return html.Div([
        html.Div(str(year), style={
            "color": ACCENT, "fontWeight": "800", "fontSize": "0.85rem",
            "letterSpacing": "1px", "textAlign": "center",
            "borderBottom": f"2px solid {GRID_CLR}", "marginBottom": "8px",
            "paddingBottom": "4px"}),
        *rows,
    ], style={"minWidth": "148px", "flexShrink": "0"})


def _hist_all_years(df_h: pd.DataFrame, sess_type: str) -> html.Div:
    """Every archived season of this circuit side by side (newest first),
    horizontally scrollable, for at-a-glance year-on-year comparison."""
    years = sorted(df_h["season"].unique(), reverse=True)
    cols = [_hist_year_column(df_h[df_h["season"] == y], sess_type, int(y))
            for y in years]
    return html.Div(cols, style={"display": "flex", "gap": "14px",
                                 "overflowX": "auto",
                                 "paddingBottom": "6px"})


# _tyre_history_chart now lives in figures.py (shared by STINTS + TRACK)
from f1lib.figures import _tyre_history_chart


def _rotate(x, y, angle):
    """Rotate point(s) (x, y) by *angle* radians — matches FastF1's example."""
    ca, sa = np.cos(angle), np.sin(angle)
    return x * ca - y * sa, x * sa + y * ca


def _track_map_slug(text: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_").lower()


def _track_map_paths(season, event_name, session_id):
    base = TRACK_MAPS_DIR / f"{season}_{_track_map_slug(event_name)}_{session_id}"
    return {
        "line":    base.with_suffix(".parquet"),
        "corners": Path(str(base) + "_corners.parquet"),
        "marshal": Path(str(base) + "_marshal.parquet"),
        "meta":    base.with_suffix(".json"),
    }


# Columns the cached track-map *line* must carry for every plot (layout, gears,
# sectors, DRS). Caches written before sectors/DRS were added lack the last two;
# get_track_map treats those as a miss and re-fetches to upgrade them.
_TRACK_LINE_COLS = {"X", "Y", "gear", "Speed", "sector", "drs", "z"}


def _read_track_map_cache(paths) -> dict | None:
    """Load a cached track map from disk without any network access. Returns
    None when the cache is absent (callers check columns for completeness)."""
    if not (paths["line"].exists() and paths["meta"].exists()):
        return None
    line = pd.read_parquet(paths["line"])
    corners = (pd.read_parquet(paths["corners"])
               if paths["corners"].exists() else pd.DataFrame())
    marshal = (pd.read_parquet(paths["marshal"])
               if paths["marshal"].exists() else pd.DataFrame())
    with open(paths["meta"], "r", encoding="utf-8") as fh:
        meta = _json.load(fh)
    return {"line": line, "corners": corners, "marshal_sectors": marshal, **meta}


def get_track_map(season, event_name, session_id="Q", force=False) -> dict | None:
    """
    Return {line: DataFrame[X,Y,gear,Speed,sector,drs], corners: DataFrame,
            marshal_sectors: DataFrame, rotation, driver, laptime, event,
            session} for the fastest lap of the given session. Cached to
    data/track_maps/. Returns None if no lap/telemetry.
    """
    paths = _track_map_paths(season, event_name, session_id)

    if not force:
        cached = _read_track_map_cache(paths)
        if (cached is not None
                and _TRACK_LINE_COLS.issubset(cached["line"].columns)
                and paths["marshal"].exists()):
            return cached
        # else: cache missing or pre-dates sectors/DRS/marshal sectors → (re)fetch
        # to upgrade. The marshal parquet is written even when empty, so its mere
        # existence marks a cache produced by this version.

    import fastf1
    fastf1.Cache.enable_cache(str(Path(FASTF1_CACHE_DIR)))
    sess = fastf1.get_session(int(season), event_name, session_id)
    sess.load(laps=True, telemetry=True, weather=False, messages=False)

    lap = sess.laps.pick_fastest()
    if lap is None or (hasattr(lap, "empty") and getattr(lap, "empty", False)):
        return None
    tel = lap.get_telemetry()
    if tel is None or tel.empty or not {"X", "Y", "nGear"}.issubset(tel.columns):
        return None

    keep = ["X", "Y", "nGear", "Speed"] + [c for c in ("Z", "DRS", "SessionTime")
                                           if c in tel.columns]
    line = (tel[keep]
            .rename(columns={"nGear": "gear", "Z": "z"})
            .dropna(subset=["X", "Y"])
            .reset_index(drop=True))
    line["gear"] = line["gear"].fillna(0).astype(int)
    if "z" not in line.columns:           # altitude unavailable → no elevation map
        line["z"] = np.nan

    # DRS / active-aero open: FastF1 DRS codes 10/12/14 mean the flap is open.
    if "DRS" in line.columns:
        line["drs"] = line["DRS"].isin([10, 12, 14]).astype(int)
        line = line.drop(columns=["DRS"])
    else:
        line["drs"] = 0

    # Timing sectors (1/2/3) from the lap's cumulative sector session-times.
    def _lapval(k):
        try:
            return lap[k]
        except Exception:
            return None
    s1, s2 = _lapval("Sector1SessionTime"), _lapval("Sector2SessionTime")
    if "SessionTime" in line.columns and pd.notna(s1) and pd.notna(s2):
        st = line["SessionTime"]
        line["sector"] = np.where(st <= s1, 1, np.where(st <= s2, 2, 3)).astype(int)
    else:                                   # fallback: split the lap into thirds
        n = len(line); idx = np.arange(n)
        line["sector"] = np.where(idx < n / 3, 1,
                                  np.where(idx < 2 * n / 3, 2, 3)).astype(int)
    if "SessionTime" in line.columns:
        line = line.drop(columns=["SessionTime"])

    rotation = 0.0
    corners = pd.DataFrame()
    marshal = pd.DataFrame()
    _MARKER_COLS = ["Number", "Letter", "X", "Y", "Angle", "Distance"]
    try:
        ci = sess.get_circuit_info()
        rotation = float(ci.rotation)
        _corner_cols = [c for c in _MARKER_COLS if c in ci.corners.columns]
        corners = ci.corners[_corner_cols].copy()
        # Marshalling sectors — the real, per-circuit mini-sector boundaries F1's
        # own timing uses (count varies by track: 21 at Spa, 25 at Silverstone…).
        _ms = getattr(ci, "marshal_sectors", None)
        if _ms is not None and not _ms.empty:
            marshal = _ms[[c for c in _MARKER_COLS if c in _ms.columns]].copy()
    except Exception as exc:
        logging.warning("circuit_info unavailable for %s %s: %s", season, event_name, exc)

    laptime = lap["LapTime"]
    laptime_s = laptime.total_seconds() if pd.notna(laptime) else float("nan")
    meta = {
        "rotation": rotation,
        "driver":   str(lap.get("Driver", "")),
        "laptime":  format_lap_time(laptime_s),
        "event":    event_name,
        "season":   int(season),
        "session":  session_id,
    }

    TRACK_MAPS_DIR.mkdir(parents=True, exist_ok=True)
    line.to_parquet(paths["line"], index=False)
    if not corners.empty:
        corners.to_parquet(paths["corners"], index=False)
    # written even when empty — its existence marks a cache carrying marshal data
    marshal.to_parquet(paths["marshal"], index=False)
    with open(paths["meta"], "w", encoding="utf-8") as fh:
        _json.dump(meta, fh)

    return {"line": line, "corners": corners, "marshal_sectors": marshal, **meta}


def _track_map_layout(fig: go.Figure, title: str, height: int = 480) -> go.Figure:
    fig.update_layout(
        title=title, height=height,
        paper_bgcolor=CARD_BG, plot_bgcolor=CARD_BG,
        font=dict(color=TEXT_MAIN, family="Inter, sans-serif", size=11),
        margin=dict(l=20, r=20, t=60, b=20),
        showlegend=True,
        legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1),
    )
    axkw = dict(showgrid=False, zeroline=False, visible=False)
    fig.update_xaxes(**axkw)
    fig.update_yaxes(scaleanchor="x", scaleratio=1, **axkw)
    return fig


def _finish_line(xr, yr, length: float = 1100.0):
    """A short segment perpendicular to the track at the start/finish point
    (the fastest lap's telemetry begins on the start/finish line)."""
    dx = float(xr[1] - xr[0]); dy = float(yr[1] - yr[0])
    n  = (dx * dx + dy * dy) ** 0.5 or 1.0
    px, py = -dy / n, dx / n          # unit perpendicular to track direction
    h = length / 2.0
    return ([xr[0] - px * h, xr[0] + px * h],
            [yr[0] - py * h, yr[0] + py * h])


def _fig_track_map(tm: dict, corner_names: dict[int, str] | None = None,
                   straights: list | None = None) -> go.Figure:
    """Circuit layout coloured by timing sector, with the start/finish line, the
    numbered corner markers (corner names shown on hover) and any named straights
    (Hamilton Straight, Kemmel Straight, …) labelled on the layout."""
    line = tm["line"]
    ang  = tm["rotation"] / 180.0 * np.pi
    xr, yr = _rotate(line["X"].to_numpy(), line["Y"].to_numpy(), ang)
    corner_names = corner_names or {}
    straights = straights or []

    fig = go.Figure()

    # Track line coloured by timing sector (plain white if sectors absent).
    if "sector" in line.columns:
        sec = line["sector"].to_numpy()
        for s in (1, 2, 3):
            xs, ys = _track_segments(xr, yr, sec == s)
            if not xs:
                continue
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines",
                line=dict(color=SECTOR_COLORS[s], width=4),
                name=f"Sector {s}", connectgaps=False,
                hovertemplate=f"Sector {s}<extra></extra>",
            ))
    else:
        fig.add_trace(go.Scatter(
            x=xr, y=yr, mode="lines", line=dict(color=TEXT_MAIN, width=2),
            name="Track", hoverinfo="skip", showlegend=False,
        ))

    # Start / finish line.
    if len(xr) > 1:
        fx, fy = _finish_line(xr, yr)
        fig.add_trace(go.Scatter(
            x=fx, y=fy, mode="lines",
            line=dict(color="#FFFFFF", width=5),
            name="Start / Finish", hovertemplate="Start / Finish<extra></extra>",
        ))

    # Numbered corner markers (name on hover).
    corners = tm.get("corners")
    if corners is not None and not corners.empty:
        OFFSET = 600.0  # distance to push the label off the track (track units)
        conn_x, conn_y, mk_x, mk_y, labels, hovers = [], [], [], [], [], []
        for _, c in corners.iterrows():
            off_ang = c["Angle"] / 180.0 * np.pi
            ox, oy  = _rotate(OFFSET, 0.0, off_ang)
            tx, ty  = _rotate(c["X"] + ox, c["Y"] + oy, ang)   # label position
            cx, cy  = _rotate(c["X"], c["Y"], ang)             # on-track position
            conn_x += [cx, tx, None]; conn_y += [cy, ty, None]
            mk_x.append(tx); mk_y.append(ty)
            num    = int(c["Number"])
            letter = "" if pd.isna(c["Letter"]) else str(c["Letter"])
            labels.append(f"{num}{letter}")
            name = corner_names.get(num)
            hovers.append(f"Turn {num}{letter} — {name}" if name else f"Turn {num}{letter}")

        fig.add_trace(go.Scatter(
            x=conn_x, y=conn_y, mode="lines",
            line=dict(color=TEXT_DIM, width=1), hoverinfo="skip", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=mk_x, y=mk_y, mode="markers+text",
            marker=dict(size=20, color="#444", line=dict(color=TEXT_DIM, width=1)),
            text=labels, textfont=dict(color=TEXT_MAIN, size=9),
            textposition="middle center", hoverinfo="text", hovertext=hovers,
            name="Corners", showlegend=False,
        ))

    # Named straights — placed at the mid-point of the two corners that bracket
    # them (wrapping past the start/finish line for the final corner).
    if straights and corners is not None and not corners.empty:
        cdf  = corners.reset_index(drop=True)
        nums = cdf["Number"].astype(int).tolist()
        sx, sy, stext = [], [], []
        for after, nm in straights:
            if after not in nums:
                continue
            i = nums.index(after)
            j = (i + 1) % len(cdf)
            mx = (float(cdf["X"].iloc[i]) + float(cdf["X"].iloc[j])) / 2.0
            my = (float(cdf["Y"].iloc[i]) + float(cdf["Y"].iloc[j])) / 2.0
            rx, ry = _rotate(mx, my, ang)
            sx.append(rx); sy.append(ry); stext.append(nm)
        if sx:
            fig.add_trace(go.Scatter(
                x=sx, y=sy, mode="markers+text",
                marker=dict(size=8, color="#0A0A14", symbol="diamond",
                            line=dict(color="#E8C36A", width=1.4)),
                text=stext, textfont=dict(color="#E8C36A", size=11,
                                          family="Inter, sans-serif"),
                textposition="top center", hoverinfo="text", hovertext=stext,
                name="Straights", showlegend=False,
            ))

    title = f"Layout, Corners & Sectors — {tm['event']} {tm['season']}"
    fig = _track_map_layout(fig, title)
    fig.update_layout(legend=dict(
        title=dict(text="Sector", font=dict(color=TEXT_MAIN, size=10)),
        bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1,
        orientation="v",
    ))
    return fig


def _fig_gear_map(tm: dict) -> go.Figure:
    line = tm["line"]
    ang  = tm["rotation"] / 180.0 * np.pi
    xr, yr = _rotate(line["X"].to_numpy(), line["Y"].to_numpy(), ang)
    gear = line["gear"].to_numpy()

    fig = go.Figure()
    for g in range(1, 9):
        xs, ys = [], []
        for i in range(len(gear) - 1):
            if gear[i] == g:
                xs += [xr[i], xr[i + 1], None]
                ys += [yr[i], yr[i + 1], None]
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines",
            line=dict(color=GEAR_COLORS.get(g, "#808080"), width=4),
            name=f"Gear {g}", connectgaps=False,
            hovertemplate=f"Gear {g}<extra></extra>",
        ))

    drv = f" — {tm['driver']} {tm['laptime']}" if tm.get("driver") else ""
    title = f"Gear Shifts on Track{drv}"
    fig = _track_map_layout(fig, title)
    fig.update_layout(legend=dict(
        title=dict(text="Gear", font=dict(color=TEXT_MAIN, size=10)),
        bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1,
        orientation="v",
    ))
    return fig


# Distinct, dark-theme-readable colours for the three timing sectors.
SECTOR_COLORS = {1: "#E10600", 2: "#00B4D8", 3: "#FFD700"}


def _track_segments(xr, yr, mask):
    """Build disjoint line segments (with None breaks) for the points where
    *mask* is True — used to colour parts of the track line."""
    xs, ys = [], []
    n = len(mask)
    for i in range(n - 1):
        if mask[i]:
            xs += [xr[i], xr[i + 1], None]
            ys += [yr[i], yr[i + 1], None]
    return xs, ys


def _fig_elevation_map(tm: dict) -> go.Figure | None:
    """Track coloured by elevation (relief). FastF1 position units are 1/10 m,
    so Z is converted to metres relative to the lap's lowest point."""
    line = tm["line"]
    if "z" not in line.columns or line["z"].isna().all():
        return None
    ang = tm["rotation"] / 180.0 * np.pi
    xr, yr = _rotate(line["X"].to_numpy(), line["Y"].to_numpy(), ang)
    z = line["z"].to_numpy(dtype=float)
    rel = (z - np.nanmin(z)) / 10.0           # metres above the lowest point

    fig = go.Figure(go.Scatter(
        x=xr, y=yr, mode="markers",
        marker=dict(
            size=6, color=rel, colorscale="Turbo", showscale=True,
            colorbar=dict(
                title=dict(text="Δ elev (m)", font=dict(color=TEXT_MAIN, size=10)),
                tickfont=dict(color=TEXT_DIM, size=9), thickness=12, len=0.7,
            ),
        ),
        customdata=rel,
        hovertemplate="Elevation: +%{customdata:.1f} m<extra></extra>",
        showlegend=False,
    ))
    rng = float(np.nanmax(rel)) if rel.size else 0.0
    fig = _track_map_layout(fig, f"Track Elevation / Relief (range ≈ {rng:.0f} m)")
    fig.update_layout(showlegend=False)
    return fig


def _fig_drs_map(tm: dict) -> go.Figure | None:
    line = tm["line"]
    if "drs" not in line.columns:
        return None
    ang = tm["rotation"] / 180.0 * np.pi
    xr, yr = _rotate(line["X"].to_numpy(), line["Y"].to_numpy(), ang)
    drs = line["drs"].to_numpy().astype(int)

    fig = go.Figure()
    # Closed first (thin, dim) so the bright open zones sit on top.
    for state, clr, width, nm in [
        (0, TEXT_DIM,  2, "Closed"),
        (1, "#39FF14", 5, "DRS / active-aero open"),
    ]:
        xs, ys = _track_segments(xr, yr, drs == state)
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines",
            line=dict(color=clr, width=width),
            name=nm, connectgaps=False,
            hovertemplate=f"{nm}<extra></extra>",
        ))
    fig = _track_map_layout(fig, "DRS / Active-Aero Zones (fastest lap)")
    if drs.sum() == 0:                      # no open data (e.g. 2026 feed)
        fig.add_annotation(
            text="No DRS / active-aero activation recorded for this lap",
            xref="paper", yref="paper", x=0.5, y=0.02, showarrow=False,
            font=dict(size=10, color=TEXT_DIM),
        )
    fig.update_layout(legend=dict(
        bgcolor="rgba(0,0,0,0)", bordercolor=GRID_CLR, borderwidth=1,
        orientation="v",
    ))
    return fig


def _resolve_track_event(circuit_key: str, year):
    """Map a Track-Info circuit slug + year to a (season, event_name) FastF1
    can fetch, using the historical results table. Prefers the requested
    year, else the most recent season available for that circuit."""
    hist_keys = HIST_CIRCUIT_KEY_MAP.get(circuit_key, [circuit_key])
    if HIST_RACE.empty or "circuit_key" not in HIST_RACE.columns:
        return None, None
    sub = HIST_RACE[HIST_RACE["circuit_key"].isin(hist_keys)]
    if sub.empty:
        return None, None
    if year is not None and (sub["season"] == year).any():
        sub = sub[sub["season"] == year]
    row = sub.sort_values("season").iloc[-1]
    return int(row["season"]), str(row["event_name"])


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

    # Build dropdown options — sorted alphabetically by name so the list
    # stays navigable as new circuits are appended to the CSV.
    options = sorted(
        [{"label": row["grand_prix_fr"], "value": row["circuit_key"]}
         for _, row in CIRCUIT_CHARS.iterrows()],
        key=lambda o: o["label"],
    )
    # Default to the circuit of the meeting currently loaded in the Data tab,
    # so the tab opens on data the user is actually looking at.
    loaded_key  = _loaded_circuit_key()
    default_key = loaded_key if loaded_key else (options[0]["value"] if options else None)

    # Historical year options
    avail_years = sorted(set(
        list(HIST_RACE["season"].unique() if "season" in HIST_RACE.columns else []) +
        list(HIST_QUALI["season"].unique() if "season" in HIST_QUALI.columns else [])
    ), reverse=True)
    year_opts = [{"label": str(y), "value": int(y)} for y in avail_years]

    # Default season for the *selected* circuit: the current season when that
    # GP has already run, else the previous season (N-1). The whole page (incl.
    # the race tyre-strategy plot) follows this, and it re-syncs when the circuit
    # dropdown changes (see _sync_track_year).
    default_year = _circuit_display_season(default_key, avail_years)
    if default_year is None:
        default_year = year_opts[0]["value"] if year_opts else None

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
                    value=default_year,
                    clearable=False,
                    style={"backgroundColor": "#111", "fontSize": "0.85rem"},
                ),
            ], md=3),
        ], className="mb-3"),

        # ── Dynamic content area ─────────────────────────────
        html.Div(id="track-content"),
    ])


def _track_map_children(tm: dict, season, event_name, circuit_key=None) -> html.Div:
    """Rendered track-map block: note + layout/sectors, gears, elevation, DRS.
    Shared by the pre-load path and the on-demand button callback."""
    note = html.P(
        f"Fastest lap: {tm.get('driver','?')} · {tm.get('laptime','?')} · "
        f"{event_name} {season} {tm.get('session','')} qualifying",
        style={"color": TEXT_DIM, "fontSize": "0.74rem", "marginBottom": "8px"},
    )
    corner_names = _corner_name_map(circuit_key) if circuit_key else {}
    straights    = _NAMED_STRAIGHTS.get(circuit_key, []) if circuit_key else []
    rows = [dbc.Row([
        dbc.Col(dcc.Graph(figure=_fig_track_map(tm, corner_names, straights), config=GFX), md=6),
        dbc.Col(dcc.Graph(figure=_fig_gear_map(tm),                config=GFX), md=6),
    ])]
    elev_fig = _fig_elevation_map(tm)
    drs_fig  = _fig_drs_map(tm)
    second = []
    if elev_fig is not None:
        second.append(dbc.Col(dcc.Graph(figure=elev_fig, config=GFX), md=6))
    if drs_fig is not None:
        second.append(dbc.Col(dcc.Graph(figure=drs_fig, config=GFX), md=6))
    if second:
        rows.append(dbc.Row(second))
    return html.Div([note, *rows])


def _cached_track_map(circuit_key, year):
    """Return (children, season, event_name) for a track map *already cached* on
    disk (with all plot columns), without triggering a FastF1 download.
    (None, …) when not pre-cached or the cache pre-dates the sector/DRS data."""
    season, event_name = _resolve_track_event(circuit_key, year)
    if not event_name:
        return None, season, event_name
    for sid in ("Q", "R"):
        paths = _track_map_paths(season, event_name, sid)
        cached = _read_track_map_cache(paths)
        if cached is not None and _TRACK_LINE_COLS.issubset(cached["line"].columns):
            return (_track_map_children(cached, season, event_name, circuit_key),
                    season, event_name)
    return None, season, event_name


def _track_season_banner(hist_year, current_season, display_season,
                         is_loaded_circuit) -> html.Div:
    """Prominent banner stating which season the whole tab is showing, and why."""
    if current_season is not None and hist_year == current_season:
        note = "Current season — this Grand Prix has already run."
    elif (current_season is not None and display_season == hist_year
          and hist_year == current_season - 1):
        note = (f"The {current_season} race hasn't run yet, so the last "
                f"completed season ({hist_year}) is shown.")
    else:
        note = "Season manually selected."
    if is_loaded_circuit:
        note += "  This is the event loaded in the Data tab."
    return html.Div([
        html.Span("SHOWING SEASON", style={
            "color": TEXT_DIM, "fontSize": "0.62rem", "letterSpacing": "2px",
            "fontWeight": "700", "marginRight": "10px"}),
        html.Span(str(hist_year), style={
            "color": TEXT_MAIN, "fontSize": "1.25rem", "fontWeight": "900",
            "letterSpacing": "1px"}),
        html.Span("  ·  " + note, style={
            "color": TEXT_DIM, "fontSize": "0.78rem", "marginLeft": "8px"}),
    ], style={
        "background": CARD_BG, "border": f"1px solid {GRID_CLR}",
        "borderLeft": f"4px solid {ACCENT}", "borderRadius": "4px",
        "padding": "10px 14px", "marginBottom": "16px",
        "display": "flex", "alignItems": "baseline", "flexWrap": "wrap",
    })


# ── Track content callback ────────────────────────────────────
@callback(
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

    # ── Section 0: Season banner (which season this tab shows) ─
    _avail_years = _track_avail_years()
    current_season = max(_avail_years) if _avail_years else None
    display_season = _circuit_display_season(circuit_key, _avail_years)
    is_loaded_circuit = (_loaded_circuit_key() == circuit_key)
    season_banner = _track_season_banner(hist_year, current_season, display_season,
                                         is_loaded_circuit)

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
    alt = row.get("altitude_m")
    alt_pill = []
    if pd.notna(alt):
        # thin air above ~600 m starts costing real downforce and cooling
        alt_clr = ("#E10600" if alt >= 1500 else
                   "#FFD700" if alt >= 600 else None)
        alt_pill = [_stat_pill("ALTITUDE", f"{int(alt):,} m", alt_clr)]
    stats_pills = html.Div([
        _stat_pill("LENGTH",    f"{meta.get('length_km','—')} km"),
        _stat_pill("CORNERS",   str(meta.get("corners", "—"))),
        _stat_pill("DRS ZONES", str(meta.get("drs_zones", "—")), "#00D2BE"),
        *alt_pill,
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
            info=("Data: the circuit's named/numbered signature corners from "
                  "the circuit-characteristics reference file. Why: quick "
                  "orientation — these are the corners commentators and "
                  "telemetry analysis keep referring to."),
        )
    else:
        corners_section = html.Div()


    # ── Section 6: Track map (corner layout + gear shifts) ───
    # (Race tyre strategy moved to the dedicated RACE tab.)
    # Pre-load the map when it is already cached on disk (the loaded meeting's
    # map is warmed at data-load time), so it appears without a button click.
    preloaded_map, _tm_season, _tm_event = _cached_track_map(circuit_key, hist_year)
    track_map_section = card(
        "Track Map — Layout, Sectors, Gears, Elevation & DRS",
        info=("Data: the fastest qualifying lap's telemetry line for this circuit "
              "(FastF1) shown four ways — layout with numbered corners (names on "
              "hover), named straights, the start/finish line and timing sectors; "
              "gear per point; "
              "elevation/relief from the line's altitude; and DRS / active-aero "
              "zones. Note: elevation is the racing-line altitude, so it shows "
              "relief and gradient (climbs/descents) but not lateral banking."),
        children=html.Div([
            html.P([
                "Circuit layout (corners + named straights + sectors + start/finish), "
                "gears, elevation/relief and DRS / active-aero zones, built from the "
                "fastest qualifying lap (FastF1 telemetry). "
                + ("Pre-loaded from cache below."
                   if preloaded_map is not None else
                   "The first build for a circuit downloads telemetry (1–3 min); "
                   "it is cached afterwards for instant reuse."),
            ], style={"color": TEXT_DIM, "fontSize": "0.8rem", "marginBottom": "10px"}),
            dbc.Button("Regenerate track map" if preloaded_map is not None
                       else "Generate track map",
                       id="track-map-btn",
                       color="info", outline=True, size="sm",
                       style={"fontWeight": "700"}),
            dcc.Loading(
                type="circle", color=ACCENT,
                children=html.Div(preloaded_map, id="track-map-content",
                                  style={"marginTop": "12px"}),
            ),
        ]),
    )

    # ── Section 7: Historical results — all seasons side by side ──
    hist_blocks = []
    if not HIST_RACE.empty or not HIST_QUALI.empty:
        hist_keys = HIST_CIRCUIT_KEY_MAP.get(circuit_key, [circuit_key])

        def _filter_circuit(df):
            if df.empty or "circuit_key" not in df.columns:
                return pd.DataFrame()
            return df[df["circuit_key"].isin(hist_keys)].copy()

        for sess_type, df_h in [("Race", _filter_circuit(HIST_RACE)),
                                ("Qualifying", _filter_circuit(HIST_QUALI))]:
            if df_h.empty:
                hist_blocks.append(card(
                    f"Historical {sess_type} Results",
                    html.P(f"No historical {sess_type.lower()} data for this circuit yet. "
                           "Run fetch_historical_results.py to populate.",
                           style={"color": TEXT_DIM, "fontStyle": "italic"}),
                    info=(f"Data: official {sess_type.lower()} classifications "
                          "for this circuit from the historical archive (empty "
                          "until fetched). Why: past results here give context "
                          "for what a normal race weekend at this track looks "
                          "like."),
                ))
                continue
            hist_blocks.append(card(
                f"Historical {sess_type} Results  —  "
                f"{circuit_key.replace('_', ' ').title()}  ·  all seasons",
                _hist_all_years(df_h, sess_type),
                info=(f"Data: the official {sess_type.lower()} classification "
                      "for every archived season at this circuit, one compact "
                      "column per year (newest left) — position, team-coloured "
                      "driver chip (hover for the team name), and the "
                      "winner's/pole time with gaps below. Why: the whole "
                      "history side by side shows who goes well here year "
                      "after year without clicking through seasons."),
            ))
    else:
        hist_blocks.append(dbc.Alert(
            "Historical results not loaded. Run fetch_historical_results.py first.",
            color="secondary",
            style={"fontSize": "0.8rem"},
        ))

    # ── Assemble ──────────────────────────────────────────────
    measured_card = measured_weekend_card(circuit_key)
    pole_card = pole_evolution_card(circuit_key, HIST_QUALI)
    alloc_card = tyre_allocation_card(circuit_key)
    pir_card = pirelli_card(circuit_key)
    return html.Div([
        season_banner,
        header,
        stats_pills,
        _weekend_card(circuit_key),
        *( [measured_card] if measured_card is not None else [] ),
        _history_card(circuit_key),
        card("Circuit Profile", chars_block,
             info=("Data: the circuit's demand ratings (average speed, full throttle, "
                   "lateral load, tyre degradation, tyre difficulty), each scored 1–4 "
                   "from data/circuit_characteristics.csv and drawn as a radar. Why: a "
                   "fingerprint of what a track demands — useful context for why pace "
                   "and tyre behaviour differ between venues.")),
        corners_section,
        *( [pir_card] if pir_card is not None else [] ),
        *( [alloc_card] if alloc_card is not None else [] ),
        track_map_section,
        *( [pole_card] if pole_card is not None else [] ),
        *hist_blocks,
    ])


# ── Keep the season selector in step with the circuit ────────
@callback(
    Output("track-year-select", "value"),
    Input("track-circuit-select", "value"),
)
def _sync_track_year(circuit_key):
    """When the circuit changes, pick the season the whole page should show:
    current if that GP has run, else N-1 — so every plot stays aligned."""
    season = _circuit_display_season(circuit_key)
    return season if season is not None else no_update


# ── Track-map callback (on-demand FastF1 fetch + render) ─────
@callback(
    Output("track-map-content", "children"),
    Input("track-map-btn",      "n_clicks"),
    State("track-circuit-select", "value"),
    State("track-year-select",    "value"),
    prevent_initial_call=True,
)
def render_track_map(_n, circuit_key, year):
    if not circuit_key:
        return dbc.Alert("Select a circuit first.", color="warning",
                         style={"fontSize": "0.8rem"})

    season, event_name = _resolve_track_event(circuit_key, year)
    if not event_name:
        return dbc.Alert(
            "Couldn't map this circuit to a FastF1 event (no historical entry). "
            "Track maps need a season with results for this circuit.",
            color="warning", style={"fontSize": "0.8rem"})

    tm = None
    last_exc = None
    for sess_id in ("Q", "R"):           # quali gives the cleanest fast lap; fall back to race
        try:
            tm = get_track_map(season, event_name, sess_id)
            if tm is not None:
                break
        except Exception as exc:
            last_exc = exc
    if tm is None:
        msg = f"No telemetry available for {event_name} {season}."
        if last_exc:
            msg += f"  ({last_exc})"
        return dbc.Alert(msg, color="danger", style={"fontSize": "0.8rem"})

    return _track_map_children(tm, season, event_name, circuit_key)
