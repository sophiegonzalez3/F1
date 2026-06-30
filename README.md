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
> 2.x line on purpose — the enrichment pipeline in `processing.py` relies on
> pandas 2.x groupby behaviour and breaks on pandas 3.0.

---

## Running the app

```bash
python app.py
```

Then open **http://127.0.0.1:8050** in your browser.

On first launch the app loads the default sessions defined in `SESSION_INFO_LIST`
near the top of [app.py](app.py). If those sessions are already cached under
`data/sessions/` (most are bundled in the repo), startup is near-instant. If a
session isn't cached, FastF1 fetches it from the network the first time — this
can take a minute or two — and stores it as Parquet for next time.

You can swap which sessions are loaded at runtime from the **Data Selection** tab
inside the app — no restart needed.

---

## Project layout

| Path | What it is |
|------|------------|
| [app.py](app.py) | The Dash app — all UI, tabs, and callbacks. Entry point. |
| [config.py](config.py) | Team/compound colours, analysis parameters, and data/cache paths. |
| [data_loader.py](data_loader.py) | Loads sessions via FastF1, maps columns, and caches to Parquet. |
| [processing.py](processing.py) | Lap cleaning, stint analysis, telemetry enrichment, etc. |
| [radio_loader.py](radio_loader.py) | Fetches + transcribes team radio (faster-whisper). |
| `data/` | Bundled, version-controlled datasets (Parquet/CSV) — see below. |
| `cache/` | FastF1's raw API cache. **Not** version-controlled; regenerated on demand. |

### `data/` contents

- `sessions/` — per-session Parquet (laps, telemetry, weather, results, race control).
- `historical_results/` — race/quali/sprint results and championship standings (2021→present).
- `radio/` — downloaded team-radio mp3s plus their transcripts.
- `track_maps/`, `circuit_characteristics.csv` — circuit reference data.
- `upgrades.csv` — car-upgrade log sourced from FIA Car Presentation PDFs.

---

## Helper scripts (optional)

These refresh or extend the bundled data. You don't need them to run the app —
only when you want new events.

```bash
# Pull historical race/quali/sprint results + standings for the configured seasons
python fetch_historical_results.py

# Rebuild older session caches so telemetry includes X/Y track position
# (needed for the racing-line view on sessions cached before that feature)
python refetch_positions.py
```

Team radio is fetched and transcribed on demand by `radio_loader.py` when you
open the **Race** tab for a race that has audio. The first time is slow (it
downloads clips and runs local Whisper transcription), then it's cached. Only
recent races expose audio — older events return 403 from the archive.

---

## Troubleshooting

- **`ModuleNotFoundError` on startup** — the virtual environment isn't activated, or `pip install -r requirements.txt` hasn't been run inside it.
- **App starts but a session is empty / slow** — that session wasn't cached and FastF1 is fetching it. Give it a minute; check the console logs (the app logs at INFO level).
- **Racing-line view is blank for an event** — that session was cached before X/Y position data was added. Run `python refetch_positions.py`.
- **Team radio missing for a race** — only recent races have downloadable audio; older ones are unavailable (403). Transcription quality/speed is controlled by `RADIO_WHISPER_MODEL` in [config.py](config.py).

---

## Support

If this project was useful to you, consider supporting its development.

⭐ Starring the [repository](https://github.com/sophiegonzalez3/F1) is also greatly appreciated.

☕ Support my coffee consumption on Ko-fi: [ko-fi.com/sophiegonzalez3](https://ko-fi.com/sophiegonzalez3)
