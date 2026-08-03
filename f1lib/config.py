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
    "Haas F1 Team":   "#B0B0B0",
    "Audi":           "#828788",
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


def get_driver_color(team: str, is_primary: bool = True) -> str:
    base = TEAM_COLORS.get(team, "#808080")
    return base if is_primary else base + "AA"


def get_min_laps_for_compound(compound) -> int:
    if compound is None:
        return MIN_LAPS_MEDIUM
    c = str(compound).upper()
    if "SOFT"   in c: return MIN_LAPS_SOFT
    if "HARD"   in c: return MIN_LAPS_HARD
    return MIN_LAPS_MEDIUM
