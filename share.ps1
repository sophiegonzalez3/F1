# share.ps1 — start the F1 dashboard so the permanent public link works.
#
# Your permanent link (never changes):  https://f1dash.tail88d107.ts.net
#
# Tailscale Funnel is already configured and always-on, so all this script
# does is run the app on port 8050. The public link works while this is
# running AND your PC is awake.
#
# Usage:  right-click > Run with PowerShell,  or  in a terminal:  .\share.ps1
# Press Ctrl+C to stop serving.

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $here

$python = Join-Path $here ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Can't find .venv python at $python" }

Write-Host "Starting the F1 app on http://localhost:8050 ..." -ForegroundColor Cyan
Write-Host "Public link: https://f1dash.tail88d107.ts.net" -ForegroundColor Green
Write-Host "(loading data takes a moment; keep this window open)`n" -ForegroundColor DarkGray

& $python app.py
