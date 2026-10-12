param(
  [string]$TaskName = "MMA Dashboard Daily Sync",
  [string]$HistoryTaskName = "MMA Dashboard Weekly History Maintenance"
)

$ErrorActionPreference = "Stop"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed scheduled task: $TaskName"
if (Get-ScheduledTask -TaskName $HistoryTaskName -ErrorAction SilentlyContinue) {
  Unregister-ScheduledTask -TaskName $HistoryTaskName -Confirm:$false
  Write-Host "Removed scheduled task: $HistoryTaskName"
}
