# restart-f1.ps1 - one-click restart of the always-on F1 dashboard.
#
# Use this after code changes so the permanent public link picks them up:
#   https://f1dash.tail88d107.ts.net   (served on port 8050)
#
# It cycles the "F1 Dashboard" scheduled task the clean way:
#   1. stop the task
#   2. kill any lingering app.py python process (the classic Windows trap -
#      the old worker keeps squatting on port 8050 so the new one can't bind,
#      and the browser keeps talking to stale code)
#   3. wait for 8050 to be free
#   4. start the task again and wait for the app to come back up
#
# Usage:  right-click > Run with PowerShell,  or  in a terminal:  .\restart-f1.ps1
# (No need to keep the window open - the scheduled task hosts the app.)

$ErrorActionPreference = "Stop"
$task = "F1 Dashboard"

Write-Host "Stopping '$task'..." -ForegroundColor Cyan
try { Stop-ScheduledTask -TaskName $task } catch { Write-Host "  (task was not running)" -ForegroundColor DarkGray }

Write-Host "Killing any lingering app.py python process..." -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*app.py*' } |
    ForEach-Object {
        Write-Host "  killing PID $($_.ProcessId)" -ForegroundColor DarkGray
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Write-Host "Waiting for port 8050 to free up..." -ForegroundColor Cyan
$deadline = (Get-Date).AddSeconds(15)
while ((Get-Date) -lt $deadline) {
    if (-not (Get-NetTCPConnection -LocalPort 8050 -State Listen -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 500
}
if (Get-NetTCPConnection -LocalPort 8050 -State Listen -ErrorAction SilentlyContinue) {
    throw "Port 8050 is still held - run this script again or reboot."
}

Write-Host "Starting '$task'..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $task

Write-Host "Waiting for the app to come back up (loading data takes ~30-60s)..." -ForegroundColor Cyan
$deadline = (Get-Date).AddSeconds(120)
$up = $false
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:8050/" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $up = $true; break }
    } catch { }
    Start-Sleep -Seconds 3
}

if ($up) {
    Write-Host "`nDone. The dashboard is up." -ForegroundColor Green
    Write-Host "Public link: https://f1dash.tail88d107.ts.net" -ForegroundColor Green
    Write-Host "Remember: hard refresh the browser (Ctrl+F5) to clear cached assets." -ForegroundColor DarkGray
} else {
    Write-Host "`nStarted the task, but the app did not answer on 8050 within 2 min." -ForegroundColor Yellow
    Write-Host "Check logs\autostart.log for errors." -ForegroundColor Yellow
}
