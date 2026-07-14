# autostart-f1.ps1 — launched by the "F1 Dashboard" scheduled task at login.
# Runs the app silently (no console window) and logs to logs\autostart.log.
# Not meant to be run by hand — use share.ps1 for a manual/visible start.

$here = "C:\Users\sophi\F1"
Set-Location $here

$python = Join-Path $here ".venv\Scripts\python.exe"
$logDir = Join-Path $here "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$log = Join-Path $logDir "autostart.log"

"`n===== F1 app starting $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') =====" | Out-File -FilePath $log -Append -Encoding utf8

# Run the app in the foreground of this hidden process so the scheduled task
# stays alive alongside it; all output (stdout+stderr) appended to the log.
& $python app.py *>> $log
