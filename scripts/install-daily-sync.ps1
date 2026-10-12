param(
  [string]$TaskName = "MMA Dashboard Daily Sync",
  [datetime]$RunAt = "7:30 AM",
  [string]$HistoryTaskName = "MMA Dashboard Weekly History Maintenance",
  [datetime]$HistoryRunAt = "11:00 AM"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SyncScript = Join-Path $ProjectRoot "scripts\scheduled_sync.py"
$HistoryScript = $SyncScript
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
  $PythonPath = $VenvPython
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
  $PythonPath = & py -3.12 -c "import sys; print(sys.executable)"
  if ($LASTEXITCODE -ne 0) { throw "Install Python 3.12 before installing the scheduled tasks." }
} else {
  $PythonPath = (Get-Command python -ErrorAction Stop).Source
}
$PythonVersion = & $PythonPath -c "import sys; print(str(sys.version_info.major) + '.' + str(sys.version_info.minor))"
if ($PythonVersion -ne "3.12") { throw "Use Python 3.12 or this dashboard's .venv before installing the scheduled tasks." }

if (-not (Test-Path $SyncScript)) {
  throw "Sync script not found: $SyncScript"
}
if (-not (Test-Path $HistoryScript)) {
  throw "History maintenance script not found: $HistoryScript"
}

$Action = New-ScheduledTaskAction `
  -Execute $PythonPath `
  -Argument "`"$SyncScript`" --job daily --time $($RunAt.ToString('HH:mm'))" `
  -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$Settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 75)

Register-ScheduledTask `
  -TaskName $TaskName `
  -Description "Fast MMA Dashboard refresh for UFC/DWCS/PFL/ONE/LFA/BKFC catalogs, current cards, results, odds, and coverage." `
  -Action $Action `
  -Trigger $Trigger `
  -Settings $Settings `
  -Force | Out-Null

$HistoryAction = New-ScheduledTaskAction `
  -Execute $PythonPath `
  -Argument "`"$HistoryScript`" --job history --time $($HistoryRunAt.ToString('HH:mm'))" `
  -WorkingDirectory $ProjectRoot

$HistoryTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 15)

$HistorySettings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 4)

Register-ScheduledTask `
  -TaskName $HistoryTaskName `
  -Description "Refresh recent MMA history, detect missing upcoming-fighter records, and run API-Sports plus Sherdog fallback checks." `
  -Action $HistoryAction `
  -Trigger $HistoryTrigger `
  -Settings $HistorySettings `
  -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Runs daily at $($RunAt.ToString('h:mm tt')) Central Time and catches up when the PC was off."
Write-Host "Installed scheduled task: $HistoryTaskName"
Write-Host "Runs Sundays at $($HistoryRunAt.ToString('h:mm tt')) Central Time and audits upcoming fighter history."
Write-Host "Project: $ProjectRoot"
