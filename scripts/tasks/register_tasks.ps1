# ============================================================
# register_tasks.ps1 -- (re)register every SectorFlow scheduled task.
#
# Scheduled tasks are CODE, not hand-edited configuration. After moving the
# project (or on a new machine) run this once from an elevated PowerShell:
#
#     powershell -ExecutionPolicy Bypass -File scripts\tasks\register_tasks.ps1
#
# All actions point at scripts\jobs\*.bat relative to THIS script's location,
# so the project root is never hardcoded. (Post-mortem 2026-07-19: the tasks
# carried an absolute path and broke with result 103 after a folder move.)
# ============================================================
#Requires -RunAsAdministrator

$ErrorActionPreference = 'Stop'

# scripts\tasks\ -> project root is two levels up.
$Root    = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$JobsDir = Join-Path $Root 'scripts\jobs'
$TaskPath = '\SectorFlow\'

# name -> @{ At; Daily; RepMin; RepDurMin }  (times are local, Asia/Ho_Chi_Minh)
$Jobs = [ordered]@{
  'macro_ingest'          = @{ At='00:01'; Daily=$true; RepMin=60;  RepDurMin=1439 }
  'sector_intraday_flow'  = @{ At='09:00'; Daily=$true; RepMin=15;  RepDurMin=390 }
  'sector_risk_sentinel'  = @{ At='09:00'; Daily=$true; RepMin=30;  RepDurMin=390 }
  'sector_eod_rollup'     = @{ At='16:00'; Daily=$true }
  'regime_classify'       = @{ At='16:30'; Daily=$true }
  'rotation_predict'      = @{ At='16:45'; Daily=$true }
  'sector_signal_publish' = @{ At='17:00'; Daily=$true }
  'freshness_check'       = @{ At='18:00'; Daily=$true }
  'rotation_train'        = @{ At='02:00'; Daily=$true }
}

foreach ($name in $Jobs.Keys) {
  $cfg = $Jobs[$name]
  $bat = Join-Path $JobsDir "job_$name.bat"
  if (-not (Test-Path $bat)) { Write-Warning "skip $name -- missing $bat"; continue }

  $action  = New-ScheduledTaskAction -Execute 'cmd.exe' `
               -Argument "/c `"$bat`"" -WorkingDirectory $Root
  $trigger = New-ScheduledTaskTrigger -Daily -At $cfg.At
  if ($cfg.RepMin) {
    # PS 5.1 cannot express daily+repetition directly; graft the repetition
    # block from a throwaway once-trigger onto the daily trigger.
    $rep = New-ScheduledTaskTrigger -Once -At $cfg.At `
             -RepetitionInterval (New-TimeSpan -Minutes $cfg.RepMin) `
             -RepetitionDuration (New-TimeSpan -Minutes $cfg.RepDurMin)
    $trigger.Repetition = $rep.Repetition
  }
  $settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable `
                 -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
                 -MultipleInstances IgnoreNew
  $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
                 -LogonType Interactive -RunLevel Limited

  Register-ScheduledTask -TaskName "SectorFlow_$name" -TaskPath $TaskPath `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Force | Out-Null
  Write-Host "registered SectorFlow_$name  ($($cfg.At), rep=$($cfg.RepMin)min)"
}

Write-Host "`nDone. Verify with:  Get-ScheduledTask -TaskPath '$TaskPath'"
