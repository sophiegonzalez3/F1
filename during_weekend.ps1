# during_weekend.ps1 - one-click weekend refresh. Safe to run at ANY time:
# every step is idempotent and only reads/writes files under data\ - it never
# touches the running app, which re-reads data\ on the next Data-tab load
# (no restart needed).
#
# Runs scripts\during_weekend.py in the venv, which does the whole safe set:
#   1. caches every session of the event that has already run  (data\sessions\)
#   2. warms the circuit's track map                           (data\track_maps\)
#   3. tops up the calendar ribbon if the season is missing    (season_calendar.csv)
#   4. re-derives per-session weather for whatever is cached now
#   5. snapshots the betting market (data\odds_snapshots.csv) - a price is
#      only observable while the market is open, so this one cannot be
#      caught up later
#   6. prints the hand-curated checklist for the event (tyres, upgrades,
#      PU pool diff vs the FIA table, gearbox pool)
#
# Run it after each session of a live weekend (FP1 -> FP2 -> FP3 -> Sprint ->
# Quali) - the BRIEF tab's pace prediction sharpens with every session added.
#
# NOT this script's job (post-race only): .\restart-f1.ps1 after code changes,
# and  .venv\Scripts\python scripts\after_race.py  once the Race is cached.
#
# Usage:  right-click > Run with PowerShell,  or in a terminal:
#   .\during_weekend.ps1                                # latest event that has run
#   .\during_weekend.ps1 2026 "Hungarian Grand Prix"    # explicit event
#   .\during_weekend.ps1 --check-only                   # just the curated checklist
#   .\during_weekend.ps1 --no-track-map                 # skip the (slow) map warm-up

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $here

$python = Join-Path $here ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Can't find .venv python at $python - run setup first (see README)." }

# The checklist prints unicode (arrows, check marks); keep the console happy.
$env:PYTHONIOENCODING = "utf-8"

& $python scripts\during_weekend.py @args
exit $LASTEXITCODE
