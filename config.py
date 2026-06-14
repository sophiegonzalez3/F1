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
SPEED_PERCENTILE   = 95
BRAKE_THRESHOLD    = 10
THROTTLE_THRESHOLD = 95

# ─────────────────────────────────────────────
# DATA & CACHE PATHS
# ─────────────────────────────────────────────
# Persistent, app-readable Parquet datasets live under data/.
# Only FastF1's opaque raw-API cache lives under cache/.
SESSIONS_DIR     = "data/sessions"             # per-session Parquet (data_loader.py)
HISTORICAL_DIR   = "data/historical_results"   # historical race/quali results
FASTF1_CACHE_DIR = "cache/fastf1"              # FastF1's own raw-data cache

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
