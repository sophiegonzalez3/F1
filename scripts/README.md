# `scripts/` — manual maintenance & data-update commands

Standalone jobs you run **by hand** to refresh data or validate models. Nothing
in the running dashboard (`app.py` / `tabs/`) imports these — they only read and
write files under `data/`. Shared library code lives in `f1lib/`; these scripts
import it.

> **Onboarding a new race weekend?** Follow the ordered checklist in the root
> [README → "Updating for a new race weekend"](../README.md#updating-for-a-new-race-weekend).
> It ties these scripts together with the app's Data tab, the radio-review
> skill, and the hand-maintained CSVs. The tables below are the per-script
> reference.

## Running them

Always use the project venv, from the **repo root**:

```
.venv/Scripts/python scripts/<name>.py [args]
```

Each script inserts the repo root on `sys.path`, so running it by path (as
above) resolves `f1lib` correctly. `python -m scripts.<name>` works too.
Most take `--dry-run`/`--help`; check the script's own docstring for details.

> Modules that the app imports but that are *also* runnable stay in `f1lib/`,
> not here. The one you'll run manually is the radio loader — see the
> `radio-review` skill, or `.venv/Scripts/python -m f1lib.radio_loader <season> "<Meeting>"`.

---

## Fetch / backfill raw data

| Script | What it does | Run it when |
|---|---|---|
| `fetch_practice_laps.py` | Backfills practice-session **laps only** (no telemetry) into `data/sessions_lite/`. Args: `--seasons 2024 2025`, `--dry-run`. | You want the pace-prediction model to see more historical practice weekends. |
| `fetch_previous_races.py` | Backfills the **previous season's Race** for every cached meeting. Args: `--dry-run`, `--sessions "Race,Qualifying"`. | The RACE tab needs its season‑1 fallback (current year's race not run yet). |
| `refetch_positions.py` | Re-fetches cached sessions so telemetry includes **X/Y track position**, rebuilding the parquet caches in place. Args: `--all`. | The racing-line / replay view is empty for older events (caches predate the X/Y merge). |

## Compute derived data (writes CSVs the app reads)

| Script | What it does | Run it when |
|---|---|---|
| `compute_team_pace.py` | Builds the per-event team pace table → `data/team_pace_by_event.csv`. Args: `--season 2026`. | After caching a new race — refreshes the pace tables and feeds the backtests. |
| `compute_circuit_characteristics.py` | Derives circuit characteristics from cached telemetry → `data/circuit_characteristics_computed.csv`. Args: `--verbose`. | You've added circuits/telemetry and want measured scores instead of the hand-maintained table. |
| `build_quali_scenes.py` | Pre-bakes the Quali 3D Replay scenes + payloads for many circuits. Args: `--force`, or `<season> "<Meeting>"` for one. | Before shipping new circuits so the QUALI 3D replay loads instantly. |

## Validate models (backtests)

| Script | What it does | Run it when |
|---|---|---|
| `backtest_pace_model.py` | Replays every cached weekend to score the progressive pace model → `data/backtest_pace_model.csv`. Args: `--seasons`, `--tune`. | After changing `f1lib/pace_model.py` or `pace_features.py`, to confirm it still beats the naive baseline. |
| `backtest_race_forecast.py` | Validates the race-result forecast's pace + grid + passability blend. | After changing `f1lib/race_forecast.py` or `driver_ratings.py`. |

## Team radio

| Script | What it does | Run it when |
|---|---|---|
| `radio_review.py` | `dump` prints every clip with race context; `apply <corrections.json>` writes hand corrections (marks the meeting `reviewed`). | Reviewing transcripts — normally driven by the `radio-review` skill. |
