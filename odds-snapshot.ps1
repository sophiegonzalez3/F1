# odds-snapshot.ps1 - take one timestamped snapshot of the F1 betting market.
#
# Appends to data\odds_snapshots.csv. Safe to run at ANY time and as often as
# you like: it only ever appends, and between race weekends it writes nothing
# and exits 0 (Kalshi lists a race about a week ahead).
#
# THE SCHEDULED TASK IS NOT INSTALLED, ON PURPOSE
# -----------------------------------------------
# The routine collection is already covered without it: during_weekend.py
# snapshots on each session, and after_race.py reconstructs the whole weekend
# at HOURLY resolution from Kalshi's candlestick endpoint, which is public and
# free. Polling hourly all year would mostly duplicate that.
#
# The one thing it buys is independence from that endpoint. If Kalshi ever
# stops serving candlesticks, the backfill stops working and only live
# snapshots survive - so if you ever see `fetch_odds.py --backfill` come back
# empty for a race you know traded, run `-Install` that day. Prices before
# that point cannot be recovered.
#
# Usage:
#   .\odds-snapshot.ps1              # one snapshot now (win / podium / pole)
#   .\odds-snapshot.ps1 --all        # every F1 market incl. WDC + WCC
#   .\odds-snapshot.ps1 -Install     # register the hourly scheduled task
#   .\odds-snapshot.ps1 -Uninstall   # remove it

param(
    [switch]$Install,
    [switch]$Uninstall,
    [Parameter(ValueFromRemainingArguments = $true)] $Rest
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $here

$task = "F1 Odds Snapshot"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $task -Confirm:$false
    Write-Host "Removed scheduled task '$task'." -ForegroundColor Green
    exit 0
}

if ($Install) {
    $ps = (Get-Command powershell.exe).Source
    $action = New-ScheduledTaskAction -Execute $ps `
        -Argument "-NoProfile -WindowStyle Hidden -File `"$here\odds-snapshot.ps1`"" `
        -WorkingDirectory $here
    # Hourly, forever. Cheap (a handful of HTTP requests) and a no-op between
    # weekends, so there is no calendar logic to keep in sync - the market
    # itself decides when there is something to record.
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
        -RepetitionInterval (New-TimeSpan -Hours 1)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger `
        -Settings $settings -Description `
        "Hourly snapshot of F1 market-implied probabilities into data\odds_snapshots.csv" `
        -Force | Out-Null
    Write-Host "Registered '$task' - hourly, starting on the next hour." -ForegroundColor Green
    Write-Host "Check it with:  Get-ScheduledTask -TaskName '$task'"
    exit 0
}

$python = Join-Path $here ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Can't find .venv python at $python - run setup first (see README)." }

$env:PYTHONIOENCODING = "utf-8"
& $python scripts\fetch_odds.py @Rest
exit $LASTEXITCODE
