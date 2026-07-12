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

OUTLIER_THRESHOLD  = 1.25   # Laps >25% slower than median excluded
FUEL_CORRECTION    = 0.035  # Seconds per lap per kg of fuel
RACE_FUEL_KG       = 105.0  # Starting fuel load for a Grand Prix distance
FUEL_BURN_PER_LAP  = 1.5    # kg/lap fallback burn rate (non-race sessions)

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
# CIRCUIT KEY BRIDGE
# ─────────────────────────────────────────────
# circuit_characteristics.csv uses French slugs (e.g. "monaco", "etats_unis")
# while event names slugify to English (e.g. "monaco_grand_prix"). This map
# bridges the two; used by app.py and compute_circuit_characteristics.py.
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
