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
   python scripts/after_race.py   # pit stops → results archive → team pace → driver pace → race stats → ATR → PU top-speed → car profile → model backtest → mistakes
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

## "Pace" means four different things — say which

The word *pace* is unavoidable in F1 and dangerously overloaded: a car can lead
one measure and be mid-pack in another. Every card whose subject is a speed
therefore wears a colour-coded badge in its header naming the measure, with the
full definition on hover. The vocabulary is defined once in
[`f1lib/components.py`](f1lib/components.py) (`PACE_MEASURES`) and mirrored in
the beginner glossary — **new cards should pass `measure=` to `card()`**.

| Badge | Means | Measured as |
|-------|-------|-------------|
| `ONE-LAP` | Single flat-out lap: low fuel, fresh tyres, max attack — qualifying speed | Best single lap |
| `RACE PACE` | Sustained speed on race fuel and wearing tyres — what decides races | **Median** of clean green-flag laps, fuel- and track-corrected, dirty air excluded |
| `STINT PACE` | Race pace narrowed to one compound | Same, per stint/compound |
| `RESULT` | Where the car *ended up*, not how fast it was | Grid slot, classification, gap to pole |
| `PREDICTED` | A model estimate, not a measurement | Pace model, pre-session |

Two consequences worth knowing when reading `data/team_pace_by_event.csv`:

- `quali_gap_pct` (gap to pole) is a **RESULT**, not a pace. It compares a Q1
  lap on a green track against a Q3 lap on a rubbered one — worth ~1% of lap
  time in 2026, up to 1.5% at Monaco. Use `quali_pace_pct`, which fits
  `log(lap time) ~ team + Q-session` so every car is judged on the same track
  state, for anything about *car pace* or season momentum.
- Both `*_pace_pct` columns are expressed against the **field median**, not the
  fastest car. A floating best-car baseline means one team's off weekend moves
  everybody else's line; the median doesn't. Negative = faster than the median
  car.

## The pace model scores itself on the corrected measure

`f1lib/pace_model.py` builds its season-form prior from `quali_pace_pct` /
`race_pace_pct`, and `scripts/backtest_pace_model.py` scores its predictions
against the same two columns. They used to use the raw `*_gap_pct` pair, which
was wrong in a specific and measurable way: the Q1→Q3 artifact correlates
**+0.84** with a team's true pace, adding ~0.67 pp to Aston Martin and removing
0.59 from Mercedes. It was a rank-amplifier, so it made the ordering look
easier to predict than it is while adding error no model could have foreseen.

Switching both (2024-26, paired per event):

| | rank ρ | MAE vs the raw-FP baseline |
|---|---|---|
| ground-effect, one-lap | +0.016 (n.s.) | **0.53 → 0.29** |
| 2026-regs, one-lap | −0.019 (p=0.016) | **0.37 → 0.30** |

The 2026 ρ dip is real, not noise — and expected. Removing a rank-amplifying
artifact *should* lower apparent ordering skill; what matters is that error
relative to the naive baseline improved in both eras.

**Comparing runs across this change:** raw MAE is meaningless across it, because
the target moved. Use Spearman ρ (scale-free) or model-MAE ÷ baseline-MAE.
`tests/test_team_pace.py` pins the prior and the target to the same columns so
they can't drift apart again.

**Eras are not comparable.** 2026 is a new formula. `--tune` trains on 2024,
validates on 2025 (same era) and reports 2026 as a **holdout** — never tuned on,
so it tests whether constants fitted in one formula survive into another. A
different absolute error there is expected; the question the holdout answers is
whether the model still beats its baselines.

**The re-tune said keep the defaults**, and the run is worth not repeating:

- The tuned set scored slightly *worse* on the 2025 validation season and
  identically on the 2026 holdout. The existing constants were validated, not
  improved.
- **The long-run constants cannot be tuned on 2024 at all.** It has 2 / 1 / 0
  scoreable events at FP1 / FP2 / FP3, so the objective is byte-identical for
  every candidate value and the grid returns whichever it tried first — the
  `0.35` it "found" for long-run FP3 was fitted on zero events. `tune()` now
  counts events per stage first and keeps the default for anything under
  `MIN_TUNE_EVENTS`, printing which constants are unidentifiable.
- **One-lap FP1 is flat**: sweeping 0.40 → 1.00 moves the score by 0.002. A
  grid optimum sitting on a boundary is usually this, not a discovery.

If you re-tune after more races are cached, check the coverage table it prints
before believing any constant it reports.

## Car concept: only measure what holds up

`data/car_profile.csv` (`scripts/compute_car_profile.py`) decomposes each
weekend into the traits that make lap time — straight-line speed, cornering,
top-end fade, tyre wear, energy saving — and the STINTS tab's **Car Concept**
section reads it. Every axis is centred on the field that weekend, because
otherwise the circuit swamps the car.

The rule for adding an axis: it has to survive a **split-half reliability**
check before it is presented as a season trait. Average the odd rounds and the
even rounds separately, correlate the two, apply Spearman-Brown; below 0.6 it
does not ship as a trait. Current scores — energy saving 0.98, cornering 0.92,
top-end fade 0.77, straight-line 0.75, tyre wear 0.69. `tests/test_car_profile.py`
enforces this against the shipped table, so an axis that decays fails CI rather
than quietly misinforming.

Two hard-won details worth not re-learning:

- **Tyre wear only works if perturbed laps are filtered first.** Running
  `enrich_track_evolution` without `flag_perturbed_laps` lets safety-car laps
  into the degradation fit and reliability collapses from 0.69 to 0.17 — which
  looks exactly like "tyre wear isn't a real team trait". It is; the pipeline
  was wrong. `build_event()` has the correct order and a test pins it.
- **Nothing here measures battery state.** There is no state-of-charge channel
  in public telemetry. What is measurable is top-end fade (throttle pinned,
  speed falling), which cannot separate "out of deployment" from "hit its drag
  limit" — so that is what it is called.

## Which tab holds what

The split is by **how often the content changes**, not by subject:

- **SEASON** — everything that moves when a race happens: the calendar, the
  championship standings, the season form and momentum charts, the race-ops
  league tables, and the car-upgrade payoff.
- **CONTEXT** — read-once reference: the budget cap, ATR, technical directives,
  team finances, factories, the staff transfer market and the newcomer primer.

These lived together until the momentum charts ended up buried a third of the
way down a 35-card scroll behind material you had already read. If you add a
card, put it where its refresh cadence belongs.

SEASON's momentum block deliberately answers *what changed*, not *where things
stand* — the standings table already does the latter:

- **Momentum** — change in one-lap pace against change in points-per-round,
  first half of the rounds run so far vs second. The quadrants separate "the
  car got faster" from "the results got better", which are not the same thing.
- **Form Guide** — 3-round rolling points rate, and the gap to the leader per
  round. The cumulative points line is monotonic and hides recent form.
- **Saturday vs Sunday Character** — drawn as an arrow from the first half of
  the season to the second, not a single season-average dot.

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

Every file in `data/` is one of three kinds. Knowing which is which tells you
whether to edit it, regenerate it, or leave it alone.

**Hand-curated CSVs** — edited by hand, one verified `source` per row; no
script ever rebuilds them (sources and update cadences per file are documented
in `read_local.md`):

| File | Feeds |
|---|---|
| `tyre_allocations.csv` | Pirelli C-compound nomination per event (soft/medium/hard → C1–C5) — the "SOFT C5" chips on the strategy cards |
| `upgrades.csv` | SEASON upgrade board, from the FIA "Car Presentation Submissions" PDFs |
| `pu_penalties.csv` | SEASON PU component pool (`scripts/check_pu_table.py --write` can refresh the element counts from the FIA PDF; penalties stay manual) |
| `gearbox_penalties.csv` | SEASON gearbox pool — **still a labelled placeholder seed** |
| `team_penalties.csv` | SEASON stewards' ledger |
| `driver_info.csv` | SEASON driver market (penalty points, salaries, contracts) |
| `staff_moves.csv`, `team_staff.csv`, `dept_split_representative.csv` | SEASON HR section |
| `pirelli_ratings.csv` | TRACK "Pirelli's view" card |
| `circuit_characteristics.csv` | TRACK profile radar + altitude pill (hand-scored 1–4) |
| `testing_mileage.csv` | SEASON pre-season testing card |
| `team_finance.csv`, `budget_cap_compliance.csv` | SEASON finance cards |
| `facilities.csv`, `technical_directives.csv` | SEASON facilities / TD cards |

**Script-owned files** — do **not** hand-edit; regenerate with the owning
script (most run automatically as steps of `scripts/after_race.py`):

| File | Owning script |
|---|---|
| `race_stats.csv`, `track_limits.csv`, `lap1_league.csv`, `pit_league.csv` | `scripts/compute_race_stats.py` |
| `team_pace_by_event.csv` | `scripts/compute_team_pace.py` |
| `driver_pace_by_event.csv` | `python -m f1lib.driver_ratings` |
| `atr_allowance.csv` | `scripts/compute_atr.py` |
| `pu_topspeed.csv` | `scripts/compute_pu_topspeed.py` |
| `mistakes_all.parquet`, `mistakes_pressure_all.parquet`, `mistakes/` | `compute_mistakes.py` |
| `season_calendar.csv` | `scripts/fetch_calendar.py` (topped up by `during_weekend.py`) |
| `circuit_characteristics_computed.csv` | `scripts/compute_circuit_characteristics.py` — overlays the manual CSV at startup |
| `corner_speed_classes.json` | `scripts/compute_corner_classes.py` (once a season, deliberately fixed) |
| `backtest_pace_model.csv` | `scripts/backtest_pace_model.py` |
| `historical_results/` | `python -m f1lib.fetch_historical_results` |
| `pitstops/` | `scripts/fetch_pitstops.py` |

**Fetched/derived caches** — written on demand by the app or the weekend
runner; never edited, safe to regenerate:

- `sessions/` — per-session Parquet (laps, telemetry, weather, results, race control); `sessions_lite/` — practice laps only, for the pace model.
- `radio/` — downloaded team-radio mp3s plus their transcripts.
- `track_maps/` — cached circuit geometry (warmed by `during_weekend.py`).
- `replays/`, `track_scenes/`, `zone_pace/` — replay payloads, 3D scene geometry, zone-dominance grids.

The app re-reads CSVs on file-modification time, so editing a hand-curated
file or re-running a script needs **no app restart**.

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
