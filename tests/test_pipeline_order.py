"""Guards for two enrichment-pipeline invariants that have silently regressed.

1. ORDERING. `enrich_track_evolution` only excludes safety-car / VSC / yellow
   laps from its fit when `Perturbed_Lap` already exists, which means
   `flag_perturbed_laps` MUST run first. Get it wrong and the evolution model
   is fitted on caution laps; every corrected lap time downstream inherits it.
   compute_car_profile.py measured the damage at split-half reliability 0.17
   (noise) against 0.69 with the correct order — and its docstring has said so
   for a while. That did not stop three other race pipelines from shipping the
   wrong order anyway, because the failure is a log warning, not an error.
   Hence a test.

2. SEASON-AWARE FUEL. The race fuel load is not a constant across eras: 2026
   cut it sharply. A single hard-coded value over-corrects every 2026 lap by
   ~50%, which biases any comparison between drivers whose clean laps sit at
   different points in the race.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Every module that runs the race-lap enrichment chain. Adding a new one
# without the perturbed-lap flag is exactly the regression this pins.
RACE_PIPELINES = [
    "f1lib/state.py",
    "f1lib/driver_ratings.py",
    "f1lib/pace_features.py",
    "tabs/race.py",
    "scripts/compute_team_pace.py",
    "scripts/compute_car_profile.py",
    "scripts/compute_circuit_characteristics.py",
]


def _calls_in_scope(node) -> set[str]:
    """Names of every function called anywhere inside a scope node."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def _scopes_using(tree, fname: str):
    """Yield (scope_name, scope_node) for every function that calls `fname`.

    Module level counts as one scope, so a script that does its work outside a
    function is still covered.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if fname in _calls_in_scope(node):
                yield node.name, node


@pytest.mark.parametrize("relpath", RACE_PIPELINES)
def test_perturbed_laps_flagged_before_track_evolution(relpath):
    """Any function that fits track evolution must flag perturbed laps too.

    Deliberately a source-level check. The bug is an ordering mistake between
    two independent calls, it produces a warning rather than an exception, and
    the resulting numbers look entirely plausible — so nothing else catches it.
    """
    path = ROOT / relpath
    if not path.exists():
        pytest.skip(f"{relpath} not present")
    tree = ast.parse(path.read_text(encoding="utf-8"))

    scopes = list(_scopes_using(tree, "enrich_track_evolution"))
    assert scopes, (
        f"{relpath} is listed as a race pipeline but never calls "
        "enrich_track_evolution — update RACE_PIPELINES")

    for name, node in scopes:
        calls = _calls_in_scope(node)
        assert "flag_perturbed_laps" in calls, (
            f"{relpath}::{name} fits track evolution without calling "
            "flag_perturbed_laps first — the fit will include safety-car laps")


@pytest.mark.parametrize("relpath", [
    "f1lib/driver_ratings.py",
    "scripts/compute_team_pace.py",
])
def test_race_pace_median_excludes_perturbed_laps(relpath):
    """Flagging perturbed laps is not enough — they must also be dropped from
    the clean-lap pool the median is taken over. A VSC lap that squeaks under
    the 1.25x outlier ceiling is still a caution lap, and it has no business in
    a car-pace measurement."""
    src = (ROOT / relpath).read_text(encoding="utf-8")
    assert "Perturbed_Lap" in src, (
        f"{relpath} computes a race-pace median but never filters "
        "Perturbed_Lap out of the pool")


# ── season-aware race fuel ───────────────────────────────────

def test_race_fuel_kg_is_era_aware():
    from f1lib.config import race_fuel_kg, RACE_FUEL_KG_DEFAULT

    assert race_fuel_kg(2026) == 70.0
    assert race_fuel_kg(2024) == RACE_FUEL_KG_DEFAULT
    # lap frames carry the season as a string
    assert race_fuel_kg("2026") == 70.0
    # and nothing unparseable may blow up the enrichment chain
    assert race_fuel_kg(None) == RACE_FUEL_KG_DEFAULT
    assert race_fuel_kg("") == RACE_FUEL_KG_DEFAULT


def test_fuel_load_follows_the_season(race_laps):
    """The same race laps must carry a 2026 fuel load under a 2026 label and
    the legacy load under an older one. Pinned against the real fixture rather
    than a synthetic frame so the burn-rate clamp is exercised too."""
    from f1lib.config import RACE_FUEL_KG_DEFAULT
    from f1lib.processing import clean_and_enrich_laps

    laps26 = clean_and_enrich_laps(race_laps.copy())
    peak26 = laps26["FuelLoad_kg"].max()

    older = race_laps.copy()
    older["season"] = "2024"
    peak24 = clean_and_enrich_laps(older)["FuelLoad_kg"].max()

    # peak load is (total_laps - 1)/total_laps of the starting mass, so it sits
    # just under the constant — comfortably inside 10% either way.
    assert 0.9 * 70.0 <= peak26 <= 70.0
    assert 0.9 * RACE_FUEL_KG_DEFAULT <= peak24 <= RACE_FUEL_KG_DEFAULT
    assert peak24 > peak26 * 1.3, (
        "the 2026 fuel load should be far below the legacy one")


def test_practice_fuel_correction_is_centred_not_end_anchored(race_laps):
    """In practice the tank level is unknown, so the correction must be
    CENTRED on each stint — otherwise it pays a bonus for running longer.

    Anchoring on the stint's END assumes every run finishes empty, which
    credited a 25-lap race sim up to 1.3 s at its start against 0.5 s for a
    10-lap run. The median corrected lap then came out faster for no reason but
    length, and that median is exactly what the sandbagging detector reads.
    """
    from f1lib.processing import clean_and_enrich_laps

    fp = race_laps.copy()
    fp["session_name"] = "Practice 2_Test Grand Prix_2026"
    out = clean_and_enrich_laps(fp)

    per_stint = out.groupby(["DriverNo", "Stint"])["FuelLoad_kg"]
    means = per_stint.mean().dropna()
    assert len(means) > 3, "need several stints to judge"
    # every stint's correction straddles zero rather than sitting above it
    assert abs(float(means.mean())) < 1.0, (
        "practice fuel correction still carries a per-stint level offset")
    assert (out["FuelLoad_kg"] < 0).any(), (
        "a centred correction must go negative late in a stint")


def test_race_fuel_load_stays_physical(race_laps):
    """Centring applies to practice only. A race tank is known, never negative,
    and must keep its real magnitude."""
    from f1lib.processing import clean_and_enrich_laps
    out = clean_and_enrich_laps(race_laps.copy())
    assert (out["FuelLoad_kg"] >= 0).all()
    assert out["FuelLoad_kg"].max() > 10.0


def test_fuel_correction_without_a_season_column(race_laps):
    """Frames with no season column (ad-hoc slices, fixtures) must still
    correct — falling back to the legacy constant, i.e. unchanged behaviour."""
    from f1lib.config import RACE_FUEL_KG_DEFAULT
    from f1lib.processing import clean_and_enrich_laps

    bare = race_laps.copy().drop(columns=["season"])
    out = clean_and_enrich_laps(bare)
    assert out["FuelLoad_kg"].notna().all()
    assert out["FuelLoad_kg"].max() <= RACE_FUEL_KG_DEFAULT
