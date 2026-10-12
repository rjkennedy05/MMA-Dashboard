param(
  [string]$TaskName = "MMA Dashboard Daily Sync",
  [datetime]$RunAt = "7:30 AM",
  [string]$HistoryTaskName = "MMA Dashboard Weekly History Maintenance",
  [datetime]$HistoryRunAt = "11:00 AM"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SyncScript = Join-Path $ProjectRoot "api\sync\weekly_sync.py"
$HistoryScript = Join-Path $ProjectRoot "api\sync\history_maintenance.py"
$PythonCommand = Get-Command python -ErrorAction Stop
$PythonPath = $PythonCommand.Source

if (-not (Test-Path $SyncScript)) {
  throw "Sync script not found: $SyncScript"
}
if (-not (Test-Path $HistoryScript)) {
  throw "History maintenance script not found: $HistoryScript"
}

$Action = New-ScheduledTaskAction `
  -Execute $PythonPath `
  -Argument "`"$SyncScript`" --mode daily" `
  -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -Daily -At $RunAt
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
  -Argument "`"$HistoryScript`"" `
  -WorkingDirectory $ProjectRoot

$HistoryTrigger = New-ScheduledTaskTrigger `
  -Weekly `
  -DaysOfWeek Sunday `
  -At $HistoryRunAt

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
Write-Host "Runs daily at $($RunAt.ToString('h:mm tt')) and catches up when the PC was off."
Write-Host "Installed scheduled task: $HistoryTaskName"
Write-Host "Runs Sundays at $($HistoryRunAt.ToString('h:mm tt')) and audits upcoming fighter history."
Write-Host "Project: $ProjectRoot"
