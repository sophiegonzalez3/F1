"""
circuits.py
===========
Circuit identity — *which physical track* a Grand Prix was actually run on.

Why this exists
---------------
Everything in this repo used to key circuits off the slugified event name.
That works right up until the calendar does something normal for F1, and then
it fails silently. The event name and the circuit are independent facts, and
they come apart in three different directions:

1. **Same name, different circuit.** The "Spanish Grand Prix" was Barcelona
   through 2025 and is the Madring from 2026. The "Bahrain Grand Prix" is
   Sakhir — except in 2026, when the Middle East conflict moved it to Sepang
   and F1 kept the Bahrain name. Keying on the name pools two unrelated tracks.
2. **Different name, same circuit.** 2020 ran two races at Silverstone
   ("British" + "70th Anniversary") and two at the Red Bull Ring ("Austrian" +
   "Styrian"); Interlagos was "Brazilian" then "São Paulo"; Mexico City was
   "Mexican" then "Mexico City"; Barcelona is "Spanish" pre-2026 and
   "Barcelona" in 2026. Keying on the name splits one track's history.
3. **Same venue, different layout.** 2020 ran the Bahrain GP on the normal
   circuit and the Sakhir GP on the outer loop a week later. Same tarmac,
   different corners — corner 4 is not the same corner. These must *not* pool
   even though the venue is identical.

Only (2) is a merge, only (1) and (3) are splits, and no single slug can
express all three. Hence a `circuit_id`: a stable identity for a physical
*layout*, resolved per (event_name, season).

The safe default
----------------
An event with no rule gets its own identity, derived from its slug. That is
deliberate and is the invariant to preserve when extending this file:

    wrongly SPLITTING a circuit is visible and recoverable — samples look thin,
    and merging later is a one-line rule.
    wrongly MERGING two circuits is silent and corrupting — Madrid's corner 5
    is averaged into Barcelona's corner 5 and nothing ever looks wrong.

So a brand-new venue is automatically distinct, and only an explicit rule can
ever merge two names. `audit_calendar()` exists to catch the opposite mistake —
a *name* that quietly changed venue — by watching season_calendar.csv.

Extending
---------
Add a rule to `_RULES` when a Grand Prix changes venue, or when two names share
one layout. Rules are matched most-specific-first within an event; the first
whose season window contains the season wins.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from f1lib.config import HISTORICAL_DIR

# Season window is inclusive; None means open-ended.
_Rule = tuple[int | None, int | None, str]


def event_slug(event_name: str) -> str:
    """Slugify an event name the same way the results archive does."""
    text = str(event_name).lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text.strip("_")


# event slug → rules, most specific first. Anything absent resolves to its own
# slug (see module docstring: the default must never merge).
_RULES: dict[str, tuple[_Rule, ...]] = {
    # ── 1. same name, different circuit ────────────────────────────────
    # Barcelona through 2025, then the Madring from 2026.
    "spanish_grand_prix":        ((None, 2025, "barcelona_catalunya"),
                                  (2026, None, "madring")),
    # Sakhir normally; Sepang in 2026 only, when the race was relocated but
    # kept its name. If Bahrain returns to Sakhir in 2027 this needs no edit.
    "bahrain_grand_prix":        ((2026, 2026, "sepang"),
                                  (None, None, "sakhir")),

    # ── 2. different name, same circuit ────────────────────────────────
    "barcelona_grand_prix":      ((None, None, "barcelona_catalunya"),),
    "70th_anniversary_grand_prix": ((None, None, "silverstone"),),
    "british_grand_prix":        ((None, None, "silverstone"),),
    "styrian_grand_prix":        ((None, None, "red_bull_ring"),),
    "austrian_grand_prix":       ((None, None, "red_bull_ring"),),
    "brazilian_grand_prix":      ((None, None, "interlagos"),),
    "são_paulo_grand_prix":      ((None, None, "interlagos"),),
    "sao_paulo_grand_prix":      ((None, None, "interlagos"),),
    # track_map_slug() turns accents into underscores, so map filenames carry
    # this third spelling. Registered so map lookups resolve like the archive.
    "s_o_paulo_grand_prix":      ((None, None, "interlagos"),),
    "mexican_grand_prix":        ((None, None, "mexico_city"),),
    "mexico_city_grand_prix":    ((None, None, "mexico_city"),),

    # ── 3. same venue, different layout — deliberately NOT merged ──────
    # The 2020 Sakhir GP used the Bahrain outer loop: same tarmac, different
    # corners. Pooling it with `sakhir` would average unrelated corners.
    "sakhir_grand_prix":         ((None, None, "sakhir_outer"),),

    # ── one-off / renamed venues, named for the track rather than the race ──
    "emilia_romagna_grand_prix": ((None, None, "imola"),),
    "tuscan_grand_prix":         ((None, None, "mugello"),),
    "eifel_grand_prix":          ((None, None, "nurburgring"),),
    "portuguese_grand_prix":     ((None, None, "portimao"),),
    "turkish_grand_prix":        ((None, None, "istanbul"),),
    "russian_grand_prix":        ((None, None, "sochi"),),
    "german_grand_prix":         ((None, None, "hockenheim"),),
}

# FastF1's schedule spells some venues differently from season to season. These
# are cosmetic — same tarmac — and would otherwise make audit_calendar() cry
# wolf, which is worse than useless: an audit that always fails gets ignored.
# Only add a pair here once you have checked it really is the same circuit.
_LOCATION_ALIASES: dict[str, str] = {
    "yas island":   "yas marina",
    "miami":        "miami gardens",
    "monte carlo":  "monaco",
    "montreal":     "montréal",
    "sao paulo":    "são paulo",
    "singapore":    "marina bay",   # 2019 spelling; same Marina Bay street circuit
}


def _canon_location(location: str) -> str:
    loc = str(location).strip().lower()
    return _LOCATION_ALIASES.get(loc, loc)


# Human-facing labels. Only needed where the id isn't self-explanatory.
CIRCUIT_LABELS: dict[str, str] = {
    "barcelona_catalunya": "Circuit de Barcelona-Catalunya",
    "madring":             "Madring (Madrid)",
    "sakhir":              "Bahrain International Circuit",
    "sakhir_outer":        "Bahrain International Circuit (outer loop)",
    "sepang":              "Sepang International Circuit",
    "silverstone":         "Silverstone",
    "red_bull_ring":       "Red Bull Ring",
    "interlagos":          "Autódromo José Carlos Pace (Interlagos)",
    "mexico_city":         "Autódromo Hermanos Rodríguez",
    "imola":               "Autodromo Enzo e Dino Ferrari (Imola)",
    "mugello":             "Mugello",
    "nurburgring":         "Nürburgring",
    "portimao":            "Algarve International Circuit (Portimão)",
    "istanbul":            "Intercity Istanbul Park",
    "sochi":               "Sochi Autodrom",
    "hockenheim":          "Hockenheimring",
}


def circuit_id(event_name: str, season: int | None = None) -> str:
    """The physical circuit an event was run on, as a stable id.

    `season` matters whenever a race has moved venue — pass it. Omitting it
    resolves against the open-ended rule, which is the venue the event uses
    *normally*; for `spanish_grand_prix` that is pre-2026 Barcelona, so a
    season-less call on a relocated event is a best guess, not a fact.
    """
    slug = event_slug(event_name)
    rules = _RULES.get(slug)
    if not rules:
        return slug                      # unknown → its own identity

    if season is not None:
        season = int(season)
        for lo, hi, cid in rules:
            if (lo is None or season >= lo) and (hi is None or season <= hi):
                return cid

    # No season given: fall back to the most open-ended rule.
    for lo, hi, cid in rules:
        if lo is None and hi is None:
            return cid
    return rules[0][2]


def circuit_label(cid: str) -> str:
    """Display name for a circuit id."""
    return CIRCUIT_LABELS.get(cid, str(cid).replace("_", " ").title())


# circuit_id → the French slug the TRACK-tab reference data is keyed on
# (circuit_characteristics.csv, pirelli_ratings.csv, the curated dicts in
# tabs/track.py). Only ids whose French key isn't already reachable through
# config.HIST_CIRCUIT_KEY_MAP need a line here.
#
# Circuits deliberately absent — they have no curated reference rows, and must
# NOT borrow their parent venue's: sakhir_outer (2020 outer loop), sepang,
# mugello, nurburgring, portimao, istanbul, sochi, hockenheim. Absent resolves
# to None, which the TRACK tab renders as "no reference data" rather than
# quietly showing another circuit's numbers.
_FR_BY_CIRCUIT: dict[str, str] = {
    "barcelona_catalunya": "espagne",
    "madring":             "madrid",
    "sakhir":              "bahrein",
    "silverstone":         "grande_bretagne",
    "red_bull_ring":       "autriche",
    "interlagos":          "bresil",
    "mexico_city":         "mexique",
    "imola":               "emilie_romagne",
}

# Every circuit id the registry knows about, so french_key() can tell
# "registered but intentionally unmapped" from "never heard of it".
_RULES_CIRCUIT_IDS: frozenset[str] = frozenset(
    cid for rules in _RULES.values() for _, _, cid in rules
)


def french_key(event_name: str, season: int | None = None) -> str | None:
    """The TRACK-tab reference slug for an event, resolved *per season*.

    This is the season-aware replacement for looking an event up in
    `config.HIST_CIRCUIT_KEY_MAP`, which maps both `spanish_grand_prix` and
    `barcelona_grand_prix` to `espagne` and so would hand the 2026 Madrid race
    Barcelona's circuit profile, Pirelli ratings and lap record.

    Returns None when the circuit has no curated reference data — the caller
    should show nothing rather than fall back to a neighbour.
    """
    cid = circuit_id(event_name, season)
    if cid in _FR_BY_CIRCUIT:
        return _FR_BY_CIRCUIT[cid]
    if cid in _RULES_CIRCUIT_IDS:
        return None            # registered circuit, deliberately no reference row

    from f1lib.config import HIST_CIRCUIT_KEY_MAP
    for fr, slugs in HIST_CIRCUIT_KEY_MAP.items():
        if cid in slugs:
            return fr
    return None


def same_circuit(event_a: str, season_a: int | None,
                 event_b: str, season_b: int | None) -> bool:
    """True when two (event, season) pairs ran on the same physical layout."""
    return circuit_id(event_a, season_a) == circuit_id(event_b, season_b)


def has_explicit_rule(event_name: str) -> bool:
    """Whether this event's circuit is pinned by a rule rather than defaulted."""
    return event_slug(event_name) in _RULES


def add_circuit_id(df: pd.DataFrame,
                   event_col: str = "event_name",
                   season_col: str = "season",
                   out_col: str = "circuit_id") -> pd.DataFrame:
    """Attach a `circuit_id` column to any frame carrying event + season.

    The one supported way to key a multi-season aggregation on a circuit.
    """
    out = df.copy()
    if event_col not in out.columns:
        out[out_col] = ""
        return out
    seasons = (out[season_col] if season_col in out.columns
               else pd.Series([None] * len(out), index=out.index))
    out[out_col] = [
        circuit_id(e, s if pd.notna(s) else None)
        for e, s in zip(out[event_col], seasons)
    ]
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Audit
# ─────────────────────────────────────────────────────────────────────────────

def audit_calendar(calendar_csv: Path | str) -> list[str]:
    """Catch venue changes that no rule covers yet.

    season_calendar.csv records country + location per event, so a name whose
    location moves between seasons is a relocation — exactly the Madrid and
    Sepang cases. If a rule already resolves those seasons to different circuit
    ids we're fine; if the name still collapses to one id, the archive is about
    to pool two tracks and that is worth failing over.

    Returns human-readable problem strings (empty when clean).
    """
    problems: list[str] = []
    try:
        cal = pd.read_csv(calendar_csv)
    except Exception as exc:
        return [f"cannot read {calendar_csv}: {exc}"]

    need = {"season", "event", "location"}
    if not need.issubset(cal.columns):
        return [f"{calendar_csv} missing columns {need - set(cal.columns)}"]

    cal = cal.dropna(subset=["location"]).copy()
    cal["_loc"] = cal["location"].map(_canon_location)

    for event, grp in cal.groupby("event"):
        locations = sorted(grp["_loc"].unique())
        if len(locations) < 2:
            continue
        ids = {circuit_id(event, int(s)) for s in grp["season"].unique()}
        if len(ids) < len(locations):
            seasons_by_loc = {
                loc: sorted(int(s) for s in grp[grp["_loc"] == loc]["season"])
                for loc in locations
            }
            problems.append(
                f'"{event}" ran at {len(locations)} locations '
                f'({"; ".join(f"{k} {v}" for k, v in seasons_by_loc.items())}) '
                f"but resolves to only {len(ids)} circuit id(s) {sorted(ids)} — "
                f"add a season-scoped rule to f1lib/circuits.py::_RULES, or an "
                f"alias to _LOCATION_ALIASES if it is the same track renamed"
            )
    return problems


def audit_archive(archive_dir: Path | str | None = None) -> list[str]:
    """Report archive events that resolve to a circuit id by default.

    Not an error — a genuinely new venue *should* default to its own identity.
    It is a prompt to check whether the venue is really new or is an alias of
    a track already in the registry (which would want a merge rule).
    """
    archive_dir = Path(archive_dir or HISTORICAL_DIR)
    path = archive_dir / "race_results_all.parquet"
    if not path.exists():
        return []
    try:
        df = pd.read_parquet(path, columns=["season", "event_name"])
    except Exception as exc:
        return [f"cannot read {path.name}: {exc}"]

    return [
        f'"{ev}" (seasons {sorted(int(s) for s in grp["season"].unique())}) '
        f'has no rule — defaults to circuit id "{event_slug(ev)}"'
        for ev, grp in df.drop_duplicates(["season", "event_name"]).groupby("event_name")
        if not has_explicit_rule(ev)
    ]
