# ============================================================
# cleanup_scheduled_tasks.ps1 -- sync Windows Task Scheduler with
# CLAUDE.md section 8. Runs on Windows (PowerShell, elevated).
#
# Behaviour:
#   1. UNREGISTER every stale Trading-related task:
#       - any task whose action points at a repo-root `_*.bat` (scratch)
#       - SecV2 / generate_secv2.py / run_secv2_daily.bat
#       - anything with "Trading" in its action that is NOT registered by
#         THIS script (identified by the `SectorFlow_` prefix in TaskName).
#   2. REGISTER the 8 canonical section 8 jobs, all under the task-path
#      `\SectorFlow\` with TaskName prefix `SectorFlow_`.
#   3. Leave section 16.5 stealth jobs OUT -- those services are still pending
#      (section 16.10 steps 11-18). When they land, append to $CanonicalJobs
#      below and re-run this script.
#
# Usage (PowerShell as Admin):
#     powershell -ExecutionPolicy Bypass -File scripts\cleanup_scheduled_tasks.ps1
#
# Flags:
#     -WhatIf     dry-run; show unregister / register diffs
#     -KeepLegacy skip step 1; only register the canonical set
# ============================================================

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TradingRoot = "C:\Users\admin\Documents\claude\Trading",
    [switch]$KeepLegacy
)

$ErrorActionPreference = 'Stop'
$TaskFolder   = "\SectorFlow\"
$NamePrefix   = "SectorFlow_"
$JobsDir      = Join-Path $TradingRoot "scripts\jobs"

if (-not (Test-Path $JobsDir)) {
    Write-Host "FATAL: jobs folder not found at $JobsDir" -ForegroundColor Red
    exit 1
}

Write-Host "=== SectorFlow scheduled-task sync ===" -ForegroundColor Cyan
Write-Host "Trading root : $TradingRoot"
Write-Host "Task folder  : $TaskFolder"
Write-Host "Jobs bat dir : $JobsDir"
Write-Host ""

# ---------- canonical section 8 job table -----------------------------------------
# Schedule strings use schtasks.exe semantics so they survive weird locales.
# Each row: key | bat file | ScheduledTask trigger builder.
$CanonicalJobs = @(
    @{
        Name    = "macro_ingest"
        Bat     = "job_macro_ingest.bat"
        Trigger = { New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) `
                      -RepetitionInterval (New-TimeSpan -Hours 1) `
                      -RepetitionDuration ([TimeSpan]::FromDays(3650)) }
        Cron    = "0 * * * *"
    },
    @{
        Name    = "sector_intraday_flow"
        Bat     = "job_sector_intraday_flow.bat"
        Trigger = {
            $t = New-ScheduledTaskTrigger -Daily -At "09:00" -DaysInterval 1
            $t.Repetition = (New-ScheduledTaskTrigger -Once -At "09:00" `
                -RepetitionInterval (New-TimeSpan -Minutes 15) `
                -RepetitionDuration (New-TimeSpan -Hours 6 -Minutes 30)).Repetition
            $t
        }
        Cron    = "*/15 9-15 * * 1-5"
    },
    @{
        Name    = "sector_eod_rollup"
        Bat     = "job_sector_eod_rollup.bat"
        Trigger = { New-ScheduledTaskTrigger -Daily -At "16:00" }
        Cron    = "0 16 * * 1-5"
    },
    @{
        Name    = "regime_classify"
        Bat     = "job_regime_classify.bat"
        Trigger = { New-ScheduledTaskTrigger -Daily -At "16:30" }
        Cron    = "30 16 * * 1-5"
    },
    @{
        Name    = "rotation_train"
        Bat     = "job_rotation_train.bat"
        Trigger = { New-ScheduledTaskTrigger -Daily -At "02:00" }
        Cron    = "0 2 * * *"
    },
    @{
        Name    = "rotation_predict"
        Bat     = "job_rotation_predict.bat"
        Trigger = { New-ScheduledTaskTrigger -Daily -At "16:45" }
        Cron    = "45 16 * * 1-5"
    },
    @{
        Name    = "sector_signal_publish"
        Bat     = "job_sector_signal_publish.bat"
        Trigger = { New-ScheduledTaskTrigger -Daily -At "17:00" }
        Cron    = "0 17 * * 1-5"
    },
    @{
        Name    = "sector_risk_sentinel"
        Bat     = "job_sector_risk_sentinel.bat"
        Trigger = {
            $t = New-ScheduledTaskTrigger -Daily -At "09:00" -DaysInterval 1
            $t.Repetition = (New-ScheduledTaskTrigger -Once -At "09:00" `
                -RepetitionInterval (New-TimeSpan -Minutes 30) `
                -RepetitionDuration (New-TimeSpan -Hours 6 -Minutes 30)).Repetition
            $t
        }
        Cron    = "*/30 9-15 * * 1-5"
    }
)

# ---------- step 1: unregister stale tasks ---------------------------------
if (-not $KeepLegacy) {
    Write-Host "[1/2] Unregistering stale tasks ..." -ForegroundColor Cyan

    $stale = @(Get-ScheduledTask | Where-Object {
        $exec = ($_.Actions | ForEach-Object Execute) -join " "
        $args = ($_.Actions | ForEach-Object Arguments) -join " "
        $both = "$exec $args"

        # only touch things clearly tied to this repo
        if (-not ($both -match [regex]::Escape($TradingRoot) -or
                  $_.TaskName -match '^(SectorFlow_|secv|rotation|stealth)')) {
            return $false
        }
        # keep canonical tasks we are about to re-register (they'll be
        # overwritten by Register-ScheduledTask below anyway -- cleaner to
        # unregister first so any renamed task is removed too).
        $true
    })

    if ($stale.Count -eq 0) {
        Write-Host "  already clean -- no matching tasks found." -ForegroundColor Green
    } else {
        foreach ($t in $stale) {
            Write-Host ("  [drop] {0}{1}" -f $t.TaskPath, $t.TaskName) -ForegroundColor Yellow
            if ($PSCmdlet.ShouldProcess("$($t.TaskPath)$($t.TaskName)", "Unregister")) {
                Unregister-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Confirm:$false
            }
        }
    }
    Write-Host ""
} else {
    Write-Host "[1/2] -KeepLegacy set -- skipping unregister step." -ForegroundColor DarkYellow
    Write-Host ""
}

# ---------- step 2: register canonical set --------------------------------
Write-Host "[2/2] Registering canonical section 8 jobs ..." -ForegroundColor Cyan

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
                -LogonType Interactive -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
                -DontStopIfGoingOnBatteries -StartWhenAvailable `
                -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

foreach ($job in $CanonicalJobs) {
    $bat = Join-Path $JobsDir $job.Bat
    if (-not (Test-Path $bat)) {
        Write-Host ("  [skip] {0} -- bat missing: {1}" -f $job.Name, $bat) -ForegroundColor Red
        continue
    }

    $taskName = "$NamePrefix$($job.Name)"
    $trigger  = & $job.Trigger
    $action   = New-ScheduledTaskAction -Execute "cmd.exe" `
                    -Argument ("/c `"{0}`"" -f $bat) `
                    -WorkingDirectory $TradingRoot

    Write-Host ("  [reg] {0,-28}  cron={1}" -f $taskName, $job.Cron) -ForegroundColor Green
    if ($PSCmdlet.ShouldProcess("$TaskFolder$taskName", "Register")) {
        Register-ScheduledTask -TaskName $taskName -TaskPath $TaskFolder `
            -Action $action -Trigger $trigger `
            -Principal $principal -Settings $settings `
            -Description ("SectorFlow canonical job ({0}). See CLAUDE.md section 8." -f $job.Cron) `
            -Force | Out-Null
    }
}

Write-Host ""
Write-Host "Done. Current SectorFlow tasks:" -ForegroundColor Cyan
Get-ScheduledTask -TaskPath $TaskFolder -ErrorAction SilentlyContinue |
    Select-Object TaskName, State,
        @{n="NextRun";e={(Get-ScheduledTaskInfo $_).NextRunTime}} |
    Format-Table -AutoSize

Write-Host ""
Write-Host "section 16.5 stealth jobs (stealth_scanner / lead_time_audit / flow_regime_report)" -ForegroundColor DarkYellow
Write-Host "are NOT registered -- services still pending (section 16.10 steps 11-18)." -ForegroundColor DarkYellow
