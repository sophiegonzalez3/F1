# `scripts/` — manual maintenance & data-update commands

Standalone jobs you run **by hand** to refresh data or validate models. Nothing
in the running dashboard (`app.py` / `tabs/`) imports these — they only read and
write files under `data/`. Shared library code lives in `f1lib/`; these scripts
import it.

> **Onboarding a new race weekend?** Follow the ordered checklist in the root
> [README → "Updating for a new race weekend"](../README.md#updating-for-a-new-race-weekend),
> and see [`read_local.md`](../read_local.md) for the full cadence calendar plus
> the hand-curated data sources. The tables below are the per-script reference.

## Running them

Always use the project venv, from the **repo root**:

```
.venv/Scripts/python scripts/<name>.py [args]
```

Each script inserts the repo root on `sys.path`, so running it by path (as
above) resolves `f1lib` correctly. `python -m scripts.<name>` works too.
Most take `--dry-run`/`--help`; check the script's own docstring for details.

> Modules that the app imports but that are *also* runnable stay in `f1lib/`,
> not here: `python -m f1lib.fetch_historical_results` (results archive),
> `python -m f1lib.driver_ratings` (driver pace table), and the radio loader
> (`python -m f1lib.radio_loader <season> "<Meeting>"`, normally driven by the
> `radio-review` skill). `compute_mistakes.py` sits at the repo root.

## The two runners — start here

| When | Command | What it wraps |
|---|---|---|
| **During a race weekend**, after each session | `during_weekend.py [season] ["Meeting"]` | caches the sessions that have run → warms the track map → tops up the calendar → prints the hand-curated checklist for that event |
| **After the race** is cached | `after_race.py` | the whole derived chain: pit stops → results archive → team pace → driver pace → race stats → ATR → PU top-speed → micro-mistakes |

Everything below is either a step of those two, or something you run on a
slower cadence (yearly / on-symptom).

---

## Weekend runners

| Script | What it does | Run it when |
|---|---|---|
| `during_weekend.py` | Headless equivalent of picking the event in the app's Data tab: caches every session of the event that has run, warms `data/track_maps/`, refreshes `season_calendar.csv` if the season is missing, then prints which hand-curated CSVs still need this event. Works at any point of a sprint or conventional weekend. Args: `[season] ["Meeting"]` (exact FastF1 name), `--check-only`, `--no-track-map`. | After each session of a live weekend (FP1 → FP2 → FP3 → Sprint → Quali). Re-running is cheap; the BRIEF pace prediction sharpens each time. |
| `after_race.py` | Runs the whole post-race chain in dependency order, stopping at the first failure, then prints the by-hand follow-ups. Args: `--skip <key>` (repeatable), `--skip-mistakes`, `--list`. | Once the Race is cached. Radio review, curated CSVs and quali-scene baking stay manual — it reminds you. |

## Fetch / backfill raw data

| Script | What it does | Run it when |
|---|---|---|
| `fetch_pitstops.py` | Fetches real per-stop pit data (live-timing PitStopSeries → true stationary times, Jolpica fallback → pit-lane times) for every cached race missing it → `data/pitstops/`. Args: `--season`, `--force`, `--dry-run`, or `<season> "<Meeting>"`. | Step 1 of `after_race.py`. Standalone when the pit league looks short a race — the app only fetches this when you open that race's RACE tab. |
| `fetch_calendar.py` | Writes `data/season_calendar.csv` (round, event, date, sprint flag) from FastF1's schedule — the SEASON tab's calendar ribbon. Args: `--seasons 2026`. | Once per season, and again if the calendar is revised mid-season (cancelled/rescheduled round). |
| `fetch_practice_laps.py` | Backfills practice-session **laps only** (no telemetry) into `data/sessions_lite/`. Args: `--seasons 2024 2025`, `--dry-run`. | You want the pace-prediction model to see more historical practice weekends. |
| `fetch_previous_races.py` | Backfills the **previous season's Race** for every cached meeting. Args: `--dry-run`, `--sessions "Race,Qualifying"`. | The RACE tab needs its season‑1 fallback (current year's race not run yet). |
| `refetch_positions.py` | Re-fetches cached sessions so telemetry includes **X/Y track position**, rebuilding the parquet caches in place. Args: `--all`. | The racing-line / replay view is empty for older events (caches predate the X/Y merge). |

## Compute derived data (writes the files the app reads)

| Script | Writes | Run it when |
|---|---|---|
| `compute_team_pace.py` | `data/team_pace_by_event.csv` | After caching a new race — refreshes the pace tables and feeds the backtests. (`after_race.py` step 3.) |
| `compute_race_stats.py` | `race_stats.csv`, `track_limits.csv`, `lap1_league.csv`, `pit_league.csv` | After caching a new race, and after `fetch_pitstops.py`. (Step 5.) |
| `compute_atr.py` | `data/atr_allowance.csv` | After a new race — and specifically after the first race past 30 June (creates the H2 window) and after the season opener. (Step 6.) |
| `compute_pu_topspeed.py` | `data/pu_topspeed.csv` (SEASON Engine Championship card) | After caching a new race. Args: `--season 2026`, `--verbose`. (Step 7.) |
| `compute_circuit_characteristics.py` | `data/circuit_characteristics_computed.csv` | Only when a new circuit enters the calendar, one is resurfaced, or telemetry coverage grows. Args: `--verbose`. |
| `compute_corner_classes.py` | `data/corner_speed_classes.json` (fixed slow/medium/fast km/h thresholds) | Once per season, from a full season of cached track maps. Deliberately NOT per-race: the thresholds must stay fixed for cross-event comparison. Args: `--season`, `--verbose`. |
| `build_quali_scenes.py` | `data/track_scenes/`, `data/replays/` | Before shipping new circuits so the QUALI 3D replay loads instantly. Args: `--force`, or `<season> "<Meeting>"` for one. |

`compute_mistakes.py` (repo root) writes `data/mistakes_all.parquet` +
`mistakes_pressure_all.parquet`; it is the slow last step of `after_race.py`
and needs a cached track map for the circuit — which `during_weekend.py` warms.

## Validate models (backtests)

| Script | What it does | Run it when |
|---|---|---|
| `backtest_pace_model.py` | Replays every cached weekend to score the progressive pace model → `data/backtest_pace_model.csv`. Args: `--seasons`, `--tune`. | After changing `f1lib/pace_model.py` or `pace_features.py`, to confirm it still beats the naive baseline. |
| `backtest_race_forecast.py` | Validates the race-result forecast's pace + grid + passability blend. | After changing `f1lib/race_forecast.py` or `driver_ratings.py`. |

## Team radio

| Script | What it does | Run it when |
|---|---|---|
| `radio_review.py` | `dump` prints every clip with race context; `apply <corrections.json>` writes hand corrections (marks the meeting `reviewed`). | Reviewing transcripts — normally driven by the `radio-review` skill. Fetch soon after the race: the mp3s are purged upstream. |
