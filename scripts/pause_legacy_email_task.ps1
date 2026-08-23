# ============================================================
# pause_secv3_secv4_email.ps1 -- retire any scheduled task that
# still sends the SecV3 / SecV4 daily briefing email.
#
# Context (2026-04-23): Tom flipped the 17:00 sector_signal_publish
# job over to generate_secv5.py. The canonical Section-8 task
# (SectorFlow_sector_signal_publish) is already updated by
# scripts/cleanup_scheduled_tasks.ps1 because it points at the bat
# file, which now calls secv5. This helper handles the *other*
# historical tasks that may still be lurking:
#
#   * any scheduled task whose Action invokes generate_secv3.py
#   * any scheduled task whose Action invokes generate_secv4.py
#   * the scratch-root _run_secv3.bat / _run_secv4.bat tasks
#   * pre-cleanup SecV2 leftovers (defence in depth; cleanup.ps1
#     already covers these but we double-check)
#
# Use -WhatIf for a dry run.
#
# NOTE: This file is pure ASCII on purpose. Windows PowerShell 5.1
# reads .ps1 files with the active ANSI codepage unless the file
# has a UTF-8 BOM, so non-ASCII characters (em-dash, section sign)
# were causing parser errors. Keep it ASCII.
#
# Usage (elevated PowerShell):
#     powershell -ExecutionPolicy Bypass -File scripts\pause_secv3_secv4_email.ps1
#     powershell -ExecutionPolicy Bypass -File scripts\pause_secv3_secv4_email.ps1 -WhatIf
# ============================================================

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TradingRoot = "C:\Users\admin\Documents\claude\Trading"
)

$ErrorActionPreference = 'Stop'

Write-Host "=== SecV3 / SecV4 email pause helper ===" -ForegroundColor Cyan
Write-Host "Trading root : $TradingRoot"
Write-Host ""

# Patterns we want to kill.
$StalePatterns = @(
    'generate_secv3\.py',
    'generate_secv4\.py',
    '_run_secv3\.bat',
    '_run_secv4\.bat',
    'generate_secv2\.py',
    'run_secv2_daily\.bat'
)

$all = Get-ScheduledTask -ErrorAction SilentlyContinue
if (-not $all) {
    Write-Host "No scheduled tasks visible on this machine -- nothing to do." -ForegroundColor Yellow
    return
}

$stale = @()
foreach ($t in $all) {
    $execStr = ($t.Actions | ForEach-Object Execute) -join ' '
    $argStr  = ($t.Actions | ForEach-Object Arguments) -join ' '
    $both    = "$execStr $argStr"
    foreach ($pat in $StalePatterns) {
        if ($both -match $pat) {
            $stale += [pscustomobject]@{
                Path    = $t.TaskPath
                Name    = $t.TaskName
                Pattern = $pat
                Target  = $both
            }
            break
        }
    }
}

if ($stale.Count -eq 0) {
    Write-Host "No stale SecV2 / SecV3 / SecV4 email tasks found. All clean." -ForegroundColor Green
    Write-Host ""
    Write-Host "Reminder: run scripts\cleanup_scheduled_tasks.ps1 next to make sure" -ForegroundColor DarkYellow
    Write-Host "SectorFlow_sector_signal_publish is pointing at generate_secv5.py." -ForegroundColor DarkYellow
    return
}

Write-Host ("Found {0} stale task(s):" -f $stale.Count) -ForegroundColor Yellow
$stale | Format-Table Path, Name, Pattern -AutoSize

foreach ($s in $stale) {
    Write-Host ("[drop] {0}{1}  (matched: {2})" -f $s.Path, $s.Name, $s.Pattern) -ForegroundColor Yellow
    if ($PSCmdlet.ShouldProcess("$($s.Path)$($s.Name)", "Unregister")) {
        Unregister-ScheduledTask -TaskName $s.Name -TaskPath $s.Path -Confirm:$false
    }
}

Write-Host ""
Write-Host "Done. Next step -- re-run the canonical Section-8 sync so" -ForegroundColor Cyan
Write-Host "SectorFlow_sector_signal_publish is (re)registered against" -ForegroundColor Cyan
Write-Host "the freshly-updated job_sector_signal_publish.bat (now secv5):" -ForegroundColor Cyan
Write-Host ""
Write-Host "    powershell -ExecutionPolicy Bypass -File $TradingRoot\scripts\cleanup_scheduled_tasks.ps1" -ForegroundColor Green
Write-Host ""
