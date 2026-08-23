# Repoints every \SectorFlow\ scheduled task from
#   cmd.exe /c "<job>.bat"                (console window pops up every run)
# to
#   wscript.exe "run_hidden_wait.vbs" "<job>.bat"   (no window, same exit code)
#
# Must run ELEVATED - the tasks are registered with RunLevel=Highest.
# Use apply_hidden_jobs.bat, which self-elevates.

$ErrorActionPreference = 'Stop'
$jobs = $PSScriptRoot
$vbs  = Join-Path $jobs 'run_hidden_wait.vbs'

if (-not (Test-Path $vbs)) { throw "Missing launcher: $vbs" }

$ok = 0; $fail = 0
Get-ScheduledTask -TaskPath '\SectorFlow\' | ForEach-Object {
    $t   = $_
    $cur = $t.Actions[0]

    if ($cur.Execute -match 'wscript') {
        Write-Host ("SKIP  {0} (already hidden)" -f $t.TaskName) -ForegroundColor DarkGray
        return
    }

    $bat = ($cur.Arguments -replace '^\s*/c\s*', '').Trim().Trim('"')
    if (-not (Test-Path $bat)) {
        Write-Host ("SKIP  {0} - bat not found: {1}" -f $t.TaskName, $bat) -ForegroundColor Yellow
        $script:fail++; return
    }

    # The _hidden_ marker matters: each job_*.bat also self-hides when it is
    # started without it (see the guard block at the top of those files).
    # Passing the marker here stops a pointless second relaunch once the
    # task action itself goes through the VBS launcher.
    $act = New-ScheduledTaskAction -Execute 'wscript.exe' `
                                   -Argument ('"{0}" "{1}" _hidden_' -f $vbs, $bat)
    try {
        Set-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Action $act -ErrorAction Stop | Out-Null
        Write-Host ("OK    {0}" -f $t.TaskName) -ForegroundColor Green
        $script:ok++
    } catch {
        Write-Host ("FAIL  {0} - {1}" -f $t.TaskName, $_.Exception.Message) -ForegroundColor Red
        $script:fail++
    }
}

Write-Host ""
Write-Host ("Done. changed={0} failed={1}" -f $ok, $fail)
Write-Host ""
Write-Host "Current actions:"
Get-ScheduledTask -TaskPath '\SectorFlow\' |
    ForEach-Object { "  {0,-34} {1} {2}" -f $_.TaskName, $_.Actions[0].Execute, $_.Actions[0].Arguments }
Write-Host ""
Read-Host "Press Enter to close"
