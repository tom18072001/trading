# ============================================================================
# scripts/tasks/fix_task_schedules.ps1
# ============================================================================
# Puts the SectorFlow scheduled tasks back on the Mon-Fri schedule that
# CLAUDE.md section 8 specifies.
#
#   powershell -ExecutionPolicy Bypass -File scripts\tasks\fix_task_schedules.ps1
#   ... -WhatIf     shows the plan and changes nothing
#
# Why (measured 2026-08-23): every one of the 8 tasks was registered with a
# DAILY trigger, so all of them fired on Saturday 2026-08-22 with the market
# shut. That burns the KBS request budget on a closed market and -- worse --
# the EOD rollup wrote a Saturday row built from Friday's bar. 150 weekend and
# holiday rows had accumulated in sector_flow_daily by the time anyone looked.
#
# macro_ingest (0 * * * *) and rotation_train (0 2 * * *) are every-day by
# design in section 8 and are deliberately left alone.
#
# Needs elevation: the tasks run at RunLevel=Highest, so Set-ScheduledTask on
# them returns "Access is denied" from a normal shell. This script re-launches
# itself elevated, which costs one UAC click.
# ============================================================================

[CmdletBinding()]
param([switch] $WhatIf, [switch] $Elevated)

$ErrorActionPreference = 'Stop'

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin) -and -not $WhatIf) {
    if ($Elevated) { throw "Re-launch did not gain admin rights; aborting." }
    Write-Host ''
    Write-Host '  Needs admin to change RunLevel=Highest tasks -- relaunching.' -ForegroundColor Yellow
    $argList = @('-ExecutionPolicy','Bypass','-File',"`"$PSCommandPath`"",'-Elevated')
    Start-Process powershell -Verb RunAs -ArgumentList $argList
    return
}

$TaskPath  = '\SectorFlow\'
$Weekdays  = @('Monday','Tuesday','Wednesday','Thursday','Friday')

# name -> at, repeat every (or $null), repeat for (or $null)
$Plan = [ordered]@{
    'SectorFlow_sector_intraday_flow'  = @{ At='09:00'; Every='00:15:00'; For='06:00:00' }
    'SectorFlow_sector_risk_sentinel'  = @{ At='09:00'; Every='00:30:00'; For='06:00:00' }
    'SectorFlow_sector_eod_rollup'     = @{ At='16:00'; Every=$null;      For=$null }
    'SectorFlow_regime_classify'       = @{ At='16:30'; Every=$null;      For=$null }
    'SectorFlow_rotation_predict'      = @{ At='16:45'; Every=$null;      For=$null }
    'SectorFlow_sector_signal_publish' = @{ At='17:00'; Every=$null;      For=$null }
}

Write-Host ''
Write-Host '  Plan' -ForegroundColor Cyan
Write-Host '  ----' -ForegroundColor DarkGray
foreach ($n in $Plan.Keys) {
    $p = $Plan[$n]
    $rep = if ($p.Every) { " every $($p.Every) for $($p.For)" } else { '' }
    Write-Host ("    {0,-34} Mon-Fri {1}{2}" -f $n, $p.At, $rep)
}
Write-Host '    (macro_ingest and rotation_train left every-day, per section 8)' -ForegroundColor DarkGray

if ($WhatIf) {
    Write-Host ''
    Write-Host '  -WhatIf: nothing changed.' -ForegroundColor DarkGray
    return
}

Write-Host ''
Write-Host '  Applying' -ForegroundColor Cyan
Write-Host '  --------' -ForegroundColor DarkGray

$ok = 0; $bad = 0
foreach ($n in $Plan.Keys) {
    $p = $Plan[$n]
    try {
        $existing = Get-ScheduledTask -TaskPath $TaskPath -TaskName $n -ErrorAction Stop

        if ($p.Every) {
            # A weekly trigger cannot be given a repetition directly by the
            # cmdlet, so borrow the Repetition object from a -Once trigger.
            $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At $p.At
            $donor   = New-ScheduledTaskTrigger -Once -At $p.At `
                          -RepetitionInterval ([TimeSpan]$p.Every) `
                          -RepetitionDuration ([TimeSpan]$p.For)
            $trigger.Repetition = $donor.Repetition
        } else {
            $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Weekdays -At $p.At
        }

        Set-ScheduledTask -TaskPath $TaskPath -TaskName $n -Trigger $trigger | Out-Null
        Write-Host ("    ok    {0}" -f $n) -ForegroundColor DarkGreen
        $ok++
    }
    catch {
        Write-Host ("    FAIL  {0} : {1}" -f $n, $_.Exception.Message) -ForegroundColor Red
        $bad++
    }
}

Write-Host ''
Write-Host '  Result' -ForegroundColor Cyan
Write-Host '  ------' -ForegroundColor DarkGray
Get-ScheduledTask -TaskPath $TaskPath | ForEach-Object {
    $t = @($_.Triggers)[0]
    $days = if ($t.DaysOfWeek) { $t.DaysOfWeek } else { 'every day' }
    $rep  = if ($t.Repetition.Interval) { " rep=$($t.Repetition.Interval)" } else { '' }
    $next = ($_ | Get-ScheduledTaskInfo).NextRunTime
    Write-Host ("    {0,-34} {1,-24} days={2}{3}  next={4}" -f `
        $_.TaskName, $t.CimClass.CimClassName, $days, $rep, $next)
}

Write-Host ''
Write-Host ("  {0} changed, {1} failed" -f $ok, $bad) -ForegroundColor $(if ($bad) { 'Red' } else { 'Green' })
Write-Host ''
if ($Elevated) {
    Write-Host '  Press Enter to close.' -ForegroundColor DarkGray
    [void][Console]::ReadLine()
}
