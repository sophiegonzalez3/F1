# F1 Dashboard

An interactive Formula 1 analytics dashboard built with [Dash](https://dash.plotly.com/)/Plotly. It loads race-weekend session data (practice, qualifying, race) and presents tyre-stint analysis, lap-time pace, telemetry, a race-control timeline with transcribed team radio, car-upgrade tracking, and historical results.

Data comes from [FastF1](https://docs.fastf1.dev/) and the F1 live-timing archive. Fetched sessions are cached locally as Parquet so the app starts fast and works offline once a session has been pulled once.

---

## Prerequisites

- **Python 3.12** (the project is developed and pinned against 3.12; `pandas` is held below 3.0 — see [requirements.txt](requirements.txt)).
- **Git**.
- ~1 GB free disk for the bundled data and FastF1's cache.
- Internet access the first time you load a session that isn't already cached.

---

## Setup

Clone the repository and move into it:

```bash
git clone https://github.com/sophiegonzalez3/F1.git
cd F1
```

Then create a virtual environment and install dependencies.

### Windows (PowerShell)

```powershell
# 1. Create a virtual environment
python -m venv .venv

# 2. Activate it
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt
```

### macOS / Linux

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **Always run the app from the virtual environment.** `pandas` is pinned to the
> 2.x line on purpose — the enrichment pipeline in `f1lib/processing.py` relies on
> pandas 2.x groupby behaviour and breaks on pandas 3.0.

---

## Running the app

```bash
python app.py            # threaded server, single data load
python app.py --debug    # Dash debug mode + hot reload (slower, loads data twice)
```

Then open **http://127.0.0.1:8050** in your browser.

Tab layouts are memoized per data-load + filter combination, so returning to
an already-visited tab is instant; changing sessions in the Data tab
invalidates the cache automatically.

For development, install the dev dependencies and run the tests:

```bash
pip install -r requirements-dev.txt
pytest
```

On first launch the app preloads the **most recent event** of the current season
(every available session for it, even mid-weekend), discovered from the FastF1
schedule — see `_default_session_info()` in [f1lib/state.py](f1lib/state.py). If those
sessions are already cached under `data/sessions/` (most are bundled in the repo),
startup is near-instant. If a session isn't cached, FastF1 fetches it from the
network the first time — this can take a minute or two — and stores it as Parquet
for next time.

You can switch which event is loaded at runtime from the **Data** tab inside the
app: pick a season and an event, and loading pulls all of that event's available
sessions — no restart needed.

---

## Updating for a new race weekend

When a new Grand Prix rolls out, this is the end-to-end checklist to fold it into
the dashboard. Two runners do the mechanical work — one during the weekend, one
after the race — and the rest is the hand-maintained data. Run every command from
the repo root inside the venv.

1. **During the weekend**, after each session (FP1 → FP2 → FP3 → Sprint → Quali):

   ```bash
   python scripts/during_weekend.py            # defaults to the latest event that has run
   ```

   It caches every session that has run to `data/sessions/`, warms the circuit's
   track map, tops up `season_calendar.csv`, and prints which hand-curated CSVs
   still need this event. The BRIEF tab's pace prediction sharpens with each
   session added. (Loading the event in the app's **Data** tab does the same
   caching, interactively.)

2. **Add the hand-maintained data** the checklist asks for — the two that are
   per-event:
   - `data/tyre_allocations.csv` — the event's Pirelli C-compound nomination
     (soft/medium/hard → C1–C5), from the Pirelli press release. Feeds the
     "SOFT C5" chips on the strategy cards.
   - `data/upgrades.csv` — the event's car-development packages from the FIA
     "Car Presentation Submissions" PDF (download + `pdftotext -layout`, then
     map team names to `TEAM_COLORS` keys). The UPGRADES tab hot-reloads on
     file mtime, so no restart is needed.

   Every curated file, its source and its cadence is documented in
   [`read_local.md`](read_local.md).

3. **After the race is cached**, rebuild the derived tables:

   ```bash
   python scripts/after_race.py   # pit stops → results archive → team pace → driver pace → race stats → ATR → PU top-speed → mistakes
   ```

   Stops at the first failure; every step is idempotent, and `--skip <key>`
   drops one. (`scripts/compute_circuit_characteristics.py` and
   `compute_corner_classes.py` stay separate — new circuit / once a season.)

4. **Review the team radio** — soon, the mp3s are purged upstream after a few
   weeks. Run the `radio-review` skill for the meeting (fetch → transcribe →
   hand-review); it writes reviewed transcripts and marks the meeting
   `reviewed=True`. See `.claude/skills/radio-review/SKILL.md`.

5. **Pre-bake the Quali 3D replay** (optional — makes the QUALI 3D view load
   instantly for the new circuit):
   ```bash
   python scripts/build_quali_scenes.py <season> "<Meeting Name>"
   ```

6. **Older-cache upkeep** (only if you notice the symptom):
   - Racing-line / replay view blank for the event → `python scripts/refetch_positions.py`
   - RACE-tab season-1 fallback or year-on-year comparison missing →
     `python scripts/fetch_previous_races.py`

See [`scripts/README.md`](scripts/README.md) for the full per-script reference.

---

## Project layout

| Path | What it is |
|------|------------|
| [app.py](app.py) | The Dash app — UI, tabs, and callbacks. Entry point. |
| [compute_mistakes.py](compute_mistakes.py) | The micro-mistake scan (last step of `after_race.py`); at the root because it predates `scripts/`. |
| `f1lib/` | The library the app imports (see key modules below). |
| `tabs/` | Tab modules split out of app.py (overview, teams, practice, teammates, season, qualifying, upgrades, fingerprints); see `tabs/__init__.py` for the migration recipe. New tabs start here. |
| `scripts/` | Standalone maintenance / data-update jobs you run by hand — see [`scripts/README.md`](scripts/README.md). |
| `tests/` | Pytest suite for the enrichment pipeline and loaders (`pytest`; FutureWarnings are errors — the pandas-3 tripwire). |
| `data/` | Bundled, version-controlled datasets (Parquet/CSV) — see below. |
| `cache/` | FastF1's raw API cache. **Not** version-controlled; regenerated on demand. |

Key modules inside `f1lib/`:

| Module | What it is |
|--------|------------|
| [f1lib/state.py](f1lib/state.py) | Owns the loaded-session data + enrichment pipeline (`rebuild_state`). Tab modules read `state.laps` etc. |
| [f1lib/components.py](f1lib/components.py) | Shared UI building blocks: Plotly theme, `card`, `kpi`, table styles. |
| [f1lib/standings.py](f1lib/standings.py) | Historical-results archive + championship standings helpers and widgets. |
| [f1lib/figures.py](f1lib/figures.py) | Shared chart builders (lap evolution, flag/rain bands) and team aggregations. |
| [f1lib/config.py](f1lib/config.py) | Team/compound colours, analysis parameters, and data/cache paths. |
| [f1lib/data_loader.py](f1lib/data_loader.py) | Loads sessions via FastF1, maps columns, and caches to Parquet. |
| [f1lib/processing.py](f1lib/processing.py) | Lap cleaning, stint analysis, telemetry enrichment, etc. |
| [f1lib/radio_loader.py](f1lib/radio_loader.py) | Fetches + transcribes team radio (faster-whisper), tags topics. |
| [f1lib/pitstops_loader.py](f1lib/pitstops_loader.py) | Fetches real per-stop pit data (stationary + pit-lane times). |

### `data/` contents

- `sessions/` — per-session Parquet (laps, telemetry, weather, results, race control).
- `historical_results/` — race/quali/sprint results and championship standings (2021→present).
- `radio/` — downloaded team-radio mp3s plus their transcripts.
- `pitstops/` — real per-stop pit data (live-timing PitStopSeries → true stationary times; Jolpica fallback → pit-lane durations).
- `track_maps/`, `circuit_characteristics.csv` — circuit reference data.
- `circuit_characteristics_computed.csv` — telemetry-measured circuit scores (speed, full-throttle %, lateral load, tyre deg); overlays the manual CSV at startup. Regenerate with `scripts/compute_circuit_characteristics.py`.
- `upgrades.csv` — car-upgrade log sourced from FIA Car Presentation PDFs.
- `tyre_allocations.csv` — Pirelli C-compound nomination per event (soft/medium/hard → C1–C5), hand-maintained from Pirelli press releases. Feeds the "SOFT C5" chips on the strategy cards.
- `team_pace_by_event.csv` — per (season, round, team): qualifying gap to pole, corrected race-pace gap, points. Built by `scripts/compute_team_pace.py`; powers the SEASON tab and the Upgrade Impact analysis.

---

## Helper scripts (optional)

These refresh or extend the bundled data. You don't need them to run the app —
only when you want new events. The standalone ones live in `scripts/` (full
reference in [`scripts/README.md`](scripts/README.md)); `fetch_historical_results`
lives in `f1lib/` because the app imports it too, so it runs as a module.

```bash
# Pull historical race/quali/sprint results + standings for the configured seasons
python -m f1lib.fetch_historical_results

# Rebuild the per-event DRIVER pace table (teammate-relative driver ratings the
# BRIEF prediction and the DUEL/race forecast read)
python -m f1lib.driver_ratings

# Fetch real pit-stop times for every cached race that's missing them
python scripts/fetch_pitstops.py                  # add --dry-run to preview

# Rebuild older session caches so telemetry includes X/Y track position
# (needed for the racing-line view on sessions cached before that feature)
python scripts/refetch_positions.py

# Backfill the previous season's Race for every cached meeting (so the RACE
# tab's season fallback and year-on-year comparisons work offline)
python scripts/fetch_previous_races.py            # add --dry-run to preview

# Recompute the telemetry-measured circuit characteristics after caching new events
python scripts/compute_circuit_characteristics.py

# Rebuild the per-event team pace table (SEASON tab + Upgrade Impact analysis)
# — run after fetch_historical_results and/or caching new races
python scripts/compute_team_pace.py
```

Team radio is fetched and transcribed on demand by `f1lib/radio_loader.py` when you
open the **Race** tab for a race that has audio. The first time is slow (it
downloads clips and runs local Whisper transcription), then it's cached. Only
recent races expose audio — older events return 403 from the archive.

---

## Troubleshooting

- **`ModuleNotFoundError` on startup** — the virtual environment isn't activated, or `pip install -r requirements.txt` hasn't been run inside it.
- **App starts but a session is empty / slow** — that session wasn't cached and FastF1 is fetching it. Give it a minute; check the console logs (the app logs at INFO level).
- **Racing-line view is blank for an event** — that session was cached before X/Y position data was added. Run `python scripts/refetch_positions.py`.
- **Team radio missing for a race** — only recent races have downloadable audio; older ones are unavailable (403). Transcription quality/speed is controlled by `RADIO_WHISPER_MODEL` in [f1lib/config.py](f1lib/config.py).

---

## Support

If this project was useful to you, consider supporting its development.

⭐ Starring the [repository](https://github.com/sophiegonzalez3/F1) is also greatly appreciated.

☕ Support my coffee consumption on Ko-fi: [ko-fi.com/sophiegonzalez3](https://ko-fi.com/sophiegonzalez3)
