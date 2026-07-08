"""Shared fixtures. Tests run against the bundled session Parquet when it is
present (it ships with the repo) and skip gracefully when it isn't — so the
suite works on a fresh clone before any data has been fetched."""
import sys
from pathlib import Path

import pandas as pd
import pytest

# repo root importable regardless of where pytest is invoked from
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RACE_LAPS = ROOT / "data" / "sessions" / "2026__Australian_Grand_Prix__Race__laps.parquet"


@pytest.fixture(scope="session")
def race_laps() -> pd.DataFrame:
    """Raw (pre-enrichment) laps of a bundled race session."""
    if not RACE_LAPS.exists():
        pytest.skip(f"bundled fixture not present: {RACE_LAPS.name}")
    return pd.read_parquet(RACE_LAPS)


@pytest.fixture(scope="session")
def enriched_race(race_laps) -> pd.DataFrame:
    from processing import clean_and_enrich_laps
    return clean_and_enrich_laps(race_laps.copy())
