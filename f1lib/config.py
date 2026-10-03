"""
F1 Dashboard – Configuration
Team colors, compound colors, and analysis parameters.
"""

# ─────────────────────────────────────────────
# TEAM COLORS  (traditional livery)
# ─────────────────────────────────────────────
TEAM_COLORS: dict[str, str] = {
    "Ferrari":        "#DC0000",
    "Red Bull Racing":"#0600EF",
    "Mercedes":       "#00D2BE",
    "McLaren":        "#FF8700",
    "Aston Martin":   "#006F62",
    "Alpine":         "#FFC0CB",
    "Williams":       "#005AFF",
    "Racing Bulls":   "#2B4562",
    # Haas and Audi were both greys (#B0B0B0 / #828788) only ΔE 13.5 apart —
    # indistinguishable in a chart. Haas takes its dark red and Audi the peach
    # from its secondary livery colour. See TEAM_COLORS_BY_SEASON for the one
    # season range where Haas cannot use red.
    "Haas F1 Team":   "#B03050",
    "Audi":           "#F2836B",
    "Cadillac":       "#C0A020",
    "Sauber":         "#00E701",

    # ── Alternate / historical team names ────────────────────
    # Older seasons in the historical archive (and some data sources) name the
    # same constructors differently. Without these, those teams fall through to
    # the grey "#808080" fallback — producing the inconsistent, partly-grey
    # leaderboards seen when a circuit's most recent data is a past season.
    # Each alias is coloured to match its lineage so a team keeps one identity
    # across every season and circuit.
    "RB":                 "#2B4562",   # Racing Bulls (2024 name)
    "AlphaTauri":         "#2B4562",   # Racing Bulls lineage (2021–23)
    "Kick Sauber":        "#00E701",   # Sauber (2024–25 name)
    "Alfa Romeo":         "#900000",   # Sauber lineage, Alfa-Romeo red (2022)
    "Alfa Romeo Racing":  "#900000",   # Sauber lineage, Alfa-Romeo red (2021)
}

# ── Season-conditional overrides ─────────────────────────────────
# Haas's dark red only works from 2024 on. Through 2023 the Sauber entry raced
# as Alfa Romeo in a near-identical red (#900000, ΔE 9.5 from Haas's red), so
# any 2021-23 chart would put two reds side by side that read as one team. Those
# seasons get Haas's silver instead — which is also what the car actually looked
# like then. From 2024 the entry is Kick Sauber green and the clash disappears.
HAAS_LEGACY_SILVER  = "#D8D8D8"
HAAS_LEGACY_SEASONS = (2021, 2022, 2023)

TEAM_COLORS_BY_SEASON: dict[int, dict[str, str]] = {
    s: {"Haas F1 Team": HAAS_LEGACY_SILVER} for s in HAAS_LEGACY_SEASONS
}

TEAM_COLOR_FALLBACK = "#808080"


def team_color(team, season=None, default: str = TEAM_COLOR_FALLBACK) -> str:
    """Livery colour for a team, honouring any season-specific override.

    Call this instead of reading TEAM_COLORS directly wherever the rendered
    data can come from the historical archive (2021 onwards) — passing the
    season is what keeps Haas from colliding with Alfa Romeo's red. Charts that
    only ever show the current season can keep using TEAM_COLORS.

    `season` accepts an int or a str (lap frames carry it as a string); anything
    unparseable simply falls through to the default palette.
    """
    if season is not None:
        try:
            override = TEAM_COLORS_BY_SEASON.get(int(season))
        except (TypeError, ValueError):
            override = None
        if override and team in override:
            return override[team]
    return TEAM_COLORS.get(team, default)

COMPOUND_COLORS: dict[str, str] = {
    "SOFT":   "#FF3333",
    "MEDIUM": "#FFD700",
    "HARD":   "#E8E8E8",
    "INTER":  "#39B54A",
    "WET":    "#0067FF",
}

# ─────────────────────────────────────────────
# ANALYSIS PARAMETERS
# ─────────────────────────────────────────────
MIN_LAPS_SOFT   = 5
MIN_LAPS_MEDIUM = 8
MIN_LAPS_HARD   = 10

# When a driver has NO valid stint on a compound (thin practice running),
# their single longest stint with at least this many clean laps is kept as a
# clearly-flagged FALLBACK (Fallback_Stint in analyze_stints) — whatever the
# compound's own minimum above. Rendered with a distinct texture, never mixed
# silently with valid stints.
FALLBACK_MIN_LAPS = 5

OUTLIER_THRESHOLD  = 1.25   # Laps >25% slower than median excluded
FUEL_CORRECTION    = 0.035  # Seconds per lap per kg of fuel
FUEL_BURN_PER_LAP  = 1.5    # kg/lap fallback burn rate (non-race sessions)

# Starting fuel load for a Grand Prix distance — SEASON-DEPENDENT.
# The 2026 power-unit regulations cut the maximum race fuel mass sharply (the
# PU draws far more of its energy electrically), so the 100-110 kg of the
# previous era no longer applies. Held as one constant, the correction
# over-states 2026 fuel burn by ~50%: 105 × 0.035 = 3.68 s of correction spread
# across a race where ~2.45 s belongs. That does not distort a same-lap
# team-vs-team comparison, but it systematically flatters any driver whose
# clean laps sit early in the race (long first stint, one-stopper) against one
# who ran clean late — i.e. it makes the correction strategy-dependent.
# Seasons not listed fall back to RACE_FUEL_KG_DEFAULT.
#
# SOURCE NOTE: 70.0 is the widely-reported 2026 maximum race fuel mass, not a
# figure read off the regulation text. It is the right order of magnitude and
# unambiguously closer than 105, but confirm it against the FIA Technical
# Regulations before treating any absolute fuel-corrected lap time as exact.
# Relative (team-vs-team, same lap) comparisons are insensitive to the value.
RACE_FUEL_KG_BY_SEASON: dict[int, float] = {
    2026: 70.0,
}
RACE_FUEL_KG_DEFAULT = 105.0
# Back-compat alias: the pre-2026 value, for any caller still reading the
# scalar. New code should call race_fuel_kg(season).
RACE_FUEL_KG = RACE_FUEL_KG_DEFAULT


def race_fuel_kg(season) -> float:
    """Starting race fuel load (kg) for a season.

    Accepts the season as int or str (lap frames carry it as a string) and
    falls back to the pre-2026 default for anything unrecognised, so a frame
    with no season column still corrects the way it always did.
    """
    try:
        return RACE_FUEL_KG_BY_SEASON.get(int(season), RACE_FUEL_KG_DEFAULT)
    except (TypeError, ValueError):
        return RACE_FUEL_KG_DEFAULT

# Track-evolution estimation (processing.enrich_track_evolution)
TRACK_EVO_BINS     = 10     # session-time bins for the evolution regression
TRACK_EVO_MIN_LAPS = 80     # min clean laps in a session to attempt the fit
SPEED_PERCENTILE   = 95
BRAKE_THRESHOLD    = 10
THROTTLE_THRESHOLD = 95
MINI_SECTORS       = 20     # equal-distance segments per lap for mini-sector analysis

# ─────────────────────────────────────────────
# SEASON
# ─────────────────────────────────────────────
# The season the dashboard treats as "current": startup preloads its most
# recent event, and the DATA tab defaults its event picker to it.
CURRENT_SEASON = 2026

# ─────────────────────────────────────────────
# DATA & CACHE PATHS
# ─────────────────────────────────────────────
# Persistent, app-readable Parquet datasets live under data/.
# Only FastF1's opaque raw-API cache lives under cache/.
SESSIONS_DIR     = "data/sessions"             # per-session Parquet (data_loader.py)
SESSIONS_LITE_DIR = "data/sessions_lite"       # laps+weather-only Parquet backfill (fetch_practice_laps.py) — model/backtest input, not read by the app loader
HISTORICAL_DIR   = "data/historical_results"   # historical race/quali results
FASTF1_CACHE_DIR = "cache/fastf1"              # FastF1's own raw-data cache
RADIO_DIR        = "data/radio"                # team-radio mp3s + transcripts (radio_loader.py)
PITSTOPS_DIR     = "data/pitstops"             # real per-stop pit data (pitstops_loader.py)

# Team-radio transcription (radio_loader.py). faster-whisper model size:
# tiny.en / base.en (fast) · small.en (balanced) · medium.en (accurate).
# Benchmarked Jul 2026 on real race clips: large-v3 / large-v3-turbo do NOT
# beat medium.en on F1's heavily compressed radio audio (turbo is worse) —
# the audio quality is the ceiling, so medium.en + VAD + vocab prompt it is.
RADIO_WHISPER_MODEL = "medium.en"

# ─────────────────────────────────────────────
# PACE-TABLE COLUMN BRIDGE
# ─────────────────────────────────────────────
# data/team_pace_by_event.csv renamed two columns when the dashboard split its
# vocabulary into SPEED (one flat-out lap) and PACE (a rate held over many
# laps) — see components.PACE_MEASURES. Everything that reads the table applies
# this map on load, so a CSV written by an older compute_team_pace.py, or one
# restored from a backup, still works without being regenerated first.
#
# The old names are assembled from fragments on purpose: written as literals
# they are exactly what a project-wide rename rewrites, which is how this
# mapping silently flattened to identity the first time it was written.
PACE_LEGACY_COLUMNS: dict[str, str] = {
    "quali_" + "pace_pct": "onelap_speed_pct",
    "quali_" + "gap_pct":  "quali_result_gap_pct",
}


def apply_pace_legacy_columns(df):
    """Rename legacy pace-table columns in place-safe fashion.

    Never clobbers a column that already carries the current name, so a table
    holding both (a partial hand-edit) keeps the current one.
    """
    ren = {old: new for old, new in PACE_LEGACY_COLUMNS.items()
           if old in df.columns and new not in df.columns}
    return df.rename(columns=ren) if ren else df


# ─────────────────────────────────────────────
# CIRCUIT KEY BRIDGE
# ─────────────────────────────────────────────
# circuit_characteristics.csv uses French slugs (e.g. "monaco", "etats_unis")
# while event names slugify to English (e.g. "monaco_grand_prix"). This map
# bridges the two.
#
# SEASON-BLIND — do not use it to decide which circuit an event ran at. It maps
# both "spanish_grand_prix" and "barcelona_grand_prix" to "espagne", which is
# right for 2019-2025 and wrong for 2026, when the Spanish GP moved to the
# Madring. Use f1lib.circuits.french_key(event, season), which resolves through
# the circuit registry and returns None when a venue has no reference row
# rather than lending it a neighbour's. This dict remains only as the fallback
# french_key() consults for events with no registry rule.
HIST_CIRCUIT_KEY_MAP: dict[str, list[str]] = {
    "abu_dhabi":       ["abu_dhabi_grand_prix"],
    "arabie_saoudite": ["saudi_arabian_grand_prix"],
    "autriche":        ["austrian_grand_prix"],
    "azerbaidjan":     ["azerbaijan_grand_prix"],
    "belgique":        ["belgian_grand_prix"],
    "bresil":          ["s\xe3o_paulo_grand_prix", "brazilian_grand_prix"],
    "canada":          ["canadian_grand_prix"],
    "espagne":         ["spanish_grand_prix", "barcelona_grand_prix"],
    "etats_unis":      ["united_states_grand_prix"],
    "grande_bretagne": ["british_grand_prix"],
    "hongrie":         ["hungarian_grand_prix"],
    "italie":          ["italian_grand_prix"],
    "japon":           ["japanese_grand_prix"],
    "mexique":         ["mexico_city_grand_prix", "mexican_grand_prix"],
    "monaco":          ["monaco_grand_prix"],
    "pays_bas":        ["dutch_grand_prix"],
    "qatar":           ["qatar_grand_prix"],
    "singapour":       ["singapore_grand_prix"],
    "australie":       ["australian_grand_prix"],
    "bahrein":         ["bahrain_grand_prix"],
    "chine":           ["chinese_grand_prix"],
    "emilie_romagne":  ["emilia_romagna_grand_prix"],
    "miami":           ["miami_grand_prix"],
    "las_vegas":       ["las_vegas_grand_prix"],
}

# ─────────────────────────────────────────────
# DASHBOARD LAYOUT
# ─────────────────────────────────────────────
DARK_BG   = "#0D0D0D"
CARD_BG   = "#1A1A2E"
ACCENT    = "#E10600"
TEXT_MAIN = "#FFFFFF"
TEXT_DIM  = "#AAAAAA"
GRID_CLR  = "#2A2A3E"

# ─────────────────────────────────────────────
# NON-TEAM CHART COLOURS
# ─────────────────────────────────────────────
# Reserved for series that do NOT stand for a constructor — model vs market,
# one-lap vs long-run, air vs track temperature, a forecast distribution.
# Reusing a livery hex for these is what made the BRIEF forecast look like it
# was about Mercedes and McLaren. Nothing here is within ΔE 20 of a team colour.
#
# Which to reach for:
#   NEUTRAL / NEUTRAL_ALT — the default. A lone series, a baseline, "everything
#       else". Grey reads as "this is not a team" more strongly than any hue.
#   SERIES_1..3 — when two or more non-team categories must be told apart at a
#       glance and both matter equally. Two greys would recreate exactly the
#       Haas/Audi problem (ΔE 13), so a pair gets violet + sky instead.
NEUTRAL     = "#C9CDD4"   # light silver — default non-team series
NEUTRAL_ALT = "#7E8AA0"   # cool slate — second neutral, ΔE 25 from NEUTRAL

SERIES_1 = "#A78BFA"      # violet
SERIES_2 = "#5EC8F2"      # sky
SERIES_3 = "#E85BC0"      # magenta
SERIES_COLORS = (SERIES_1, SERIES_2, SERIES_3)

# Ordinal status ramp. Green→amber→red still carries the good/bad reading, but
# these are deliberately NOT Mercedes teal (#00D2BE) and McLaren orange
# (#FF8700), which is what the DATA and TRACK tabs were using verbatim.
STATUS_OK   = "#34D399"
STATUS_WARN = "#F5B942"
STATUS_BAD  = "#F2545B"


def get_driver_color(team: str, is_primary: bool = True) -> str:
    base = TEAM_COLORS.get(team, TEAM_COLOR_FALLBACK)
    return base if is_primary else base + "AA"


def get_min_laps_for_compound(compound) -> int:
    if compound is None:
        return MIN_LAPS_MEDIUM
    c = str(compound).upper()
    if "SOFT"   in c: return MIN_LAPS_SOFT
    if "HARD"   in c: return MIN_LAPS_HARD
    return MIN_LAPS_MEDIUM
