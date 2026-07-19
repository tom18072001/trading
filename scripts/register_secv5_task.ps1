# ============================================================
# register_secv5_task.ps1 -- register (or refresh) the single
# Windows Task Scheduler task that runs the SecV5 daily email job.
#
# Task: \SectorFlow\SectorFlow_sector_signal_publish
# Runs: Mon-Fri at 17:00 local (Asia/Ho_Chi_Minh)
# Calls: scripts\jobs\job_sector_signal_publish.bat
#        -> main.py --publish  (signals)
#        -> generate_secv5.py  (unified-picks email)
#
# Why a separate script? cleanup_scheduled_tasks.ps1 re-registers
# ALL 8 canonical Section-8 jobs in one pass -- useful after a big
# sync, but too blunt if you only want to confirm the SecV5 job is
# live. This helper touches ONE task, is idempotent, and prints the
# task's next run time so you can see it scheduled.
#
# NOTE: Pure ASCII on purpose. Windows PowerShell 5.1 reads .ps1
# files with the active ANSI codepage unless the file has a UTF-8
# BOM, so non-ASCII characters were causing parser errors. Keep it
# ASCII.
#
# Usage (elevated PowerShell):
#     powershell -ExecutionPolicy Bypass -File scripts\register_secv5_task.ps1
#     powershell -ExecutionPolicy Bypass -File scripts\register_secv5_task.ps1 -WhatIf
#
# After running: open Task Scheduler -> Task Scheduler Library ->
# SectorFlow -> you should see SectorFlow_sector_signal_publish.
# ============================================================

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TradingRoot = "C:\Users\admin\Documents\claude\Trading",
    [string]$TaskTime    = "17:00"
)

$ErrorActionPreference = 'Stop'

$TaskFolder = "\SectorFlow\"
$TaskName   = "SectorFlow_sector_signal_publish"
$BatPath    = Join-Path $TradingRoot "scripts\jobs\job_sector_signal_publish.bat"

Write-Host "=== SecV5 daily job registration ===" -ForegroundColor Cyan
Write-Host "Trading root : $TradingRoot"
Write-Host "Task path    : $TaskFolder$TaskName"
Write-Host "Bat file     : $BatPath"
Write-Host "Run time     : $TaskTime Mon-Fri (local)"
Write-Host ""

if (-not (Test-Path $BatPath)) {
    Write-Host "FATAL: bat file not found at $BatPath" -ForegroundColor Red
    Write-Host "Make sure you're running from the Trading repo root and that" -ForegroundColor Red
    Write-Host "scripts\jobs\job_sector_signal_publish.bat exists." -ForegroundColor Red
    exit 1
}

# Verify the bat actually calls generate_secv5.py -- guards against
# a stale bat being registered by mistake.
$batText = Get-Content $BatPath -Raw
if ($batText -notmatch 'generate_secv5\.py') {
    Write-Host "FATAL: job_sector_signal_publish.bat does NOT reference generate_secv5.py." -ForegroundColor Red
    Write-Host "The bat must contain a line invoking generate_secv5.py." -ForegroundColor Red
    Write-Host "Current contents:" -ForegroundColor Red
    Write-Host $batText -ForegroundColor DarkGray
    exit 1
}
Write-Host "[check] bat references generate_secv5.py -- OK" -ForegroundColor Green

# Unregister any existing task at the same path so -Force (below)
# gives a clean re-register regardless of prior state.
$existing = Get-ScheduledTask -TaskPath $TaskFolder -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[drop] existing task $TaskFolder$TaskName (state=$($existing.State))" -ForegroundColor Yellow
    if ($PSCmdlet.ShouldProcess("$TaskFolder$TaskName", "Unregister (pre-replace)")) {
        Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskFolder -Confirm:$false
    }
} else {
    Write-Host "[info] no existing task at that path -- will create fresh" -ForegroundColor DarkGray
}

# Build the action, trigger, principal, settings.
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument ("/c `"{0}`"" -f $BatPath) `
    -WorkingDirectory $TradingRoot

$trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At $TaskTime

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Write-Host "[reg] registering $TaskFolder$TaskName" -ForegroundColor Green
if ($PSCmdlet.ShouldProcess("$TaskFolder$TaskName", "Register")) {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -TaskPath $TaskFolder `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description ("SecV5 daily unified-picks email. Runs at {0} Mon-Fri via job_sector_signal_publish.bat -> generate_secv5.py. See CLAUDE.md Section 8." -f $TaskTime) `
        -Force | Out-Null
}

# Report back so you can see it's live.
Write-Host ""
Write-Host "Current state:" -ForegroundColor Cyan
$reg = Get-ScheduledTask -TaskPath $TaskFolder -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $reg) {
    Write-Host "  ?? task not found after registration. Check Task Scheduler manually." -ForegroundColor Red
    exit 1
}

$info = Get-ScheduledTaskInfo -TaskPath $TaskFolder -TaskName $TaskName -ErrorAction SilentlyContinue
[pscustomobject]@{
    TaskPath  = $reg.TaskPath
    TaskName  = $reg.TaskName
    State     = $reg.State
    NextRun   = if ($info) { $info.NextRunTime } else { "<unknown>" }
    LastRun   = if ($info) { $info.LastRunTime } else { "<never>" }
    LastCode  = if ($info) { $info.LastTaskResult } else { $null }
} | Format-List

Write-Host "Done. To verify in Task Scheduler GUI:" -ForegroundColor Cyan
Write-Host "  1. Start -> Task Scheduler"
Write-Host "  2. Task Scheduler Library -> SectorFlow"
Write-Host "  3. Look for: $TaskName"
Write-Host ""
Write-Host "To force a test run right now (safe -- runs the bat, sends email):" -ForegroundColor DarkYellow
Write-Host "  Start-ScheduledTask -TaskPath '$TaskFolder' -TaskName '$TaskName'"
Write-Host ""
Write-Host "To preview without sending email, run by hand instead:" -ForegroundColor DarkYellow
Write-Host "  cd $TradingRoot"
Write-Host "  python generate_secv5.py --no-email"
Write-Host ""
