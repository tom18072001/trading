# ============================================================================
# create_desktop_shortcut.ps1 -- VN Sector Money-Flow
# ============================================================================
# Removes stale Trading shortcuts, then creates one clean Desktop launcher.
#
#   powershell -ExecutionPolicy Bypass -File create_desktop_shortcut.ps1
#   powershell -ExecutionPolicy Bypass -File create_desktop_shortcut.ps1 -Force
#   powershell -ExecutionPolicy Bypass -File create_desktop_shortcut.ps1 -DryRun
#
# Rewritten 2026-08-22. The previous version only ever created "VN Trading.lnk"
# and overwrote it in place, so every earlier shortcut -- renamed copies, the
# two loose .url files in the project root, anything left over from a moved
# project directory -- accumulated and kept pointing at paths that may no
# longer exist. This one sweeps first, shows you exactly what it matched, and
# never deletes anything it cannot tie back to this project.
#
# No admin rights needed: it only touches your own Desktop and this folder.
# ============================================================================

[CmdletBinding()]
param(
    # Delete matches without asking.
    [switch] $Force,
    # List what would happen and change nothing.
    [switch] $DryRun
)

$ErrorActionPreference = 'Stop'

$ProjectDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopPath  = [Environment]::GetFolderPath('Desktop')
$TargetBat    = Join-Path $ProjectDir 'start-dev.bat'
$IconPath     = Join-Path $ProjectDir 'frontend\public\favicon.ico'
$ShortcutName = 'VN Trading.lnk'
$ShortcutPath = Join-Path $DesktopPath $ShortcutName

function Write-Head($text) {
    Write-Host ''
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host "  $('-' * $text.Length)" -ForegroundColor DarkGray
}

if (-not (Test-Path $TargetBat)) {
    throw "start-dev.bat not found next to this script (looked in $ProjectDir). " +
          "Run this script from inside the project folder."
}

$WshShell = New-Object -ComObject WScript.Shell

# ---------------------------------------------------------------------------
# 1. Find stale shortcuts
# ---------------------------------------------------------------------------
# A shortcut is "ours" only if it resolves back to this project: its target or
# working directory sits under $ProjectDir, or it is an internet shortcut
# aimed at the dev ports. Name alone is never enough -- "Trading" is a common
# enough word that matching on it would risk deleting something unrelated.

$devUrlPattern = 'localhost:(5173|8000)|127\.0\.0\.1:(5173|8000)'
function Get-ProjectPathPattern {
    <#
      Regex that matches this project's path and nothing that merely starts
      with it. The lookahead is the whole point: without it a SIBLING folder
      named "TradingBackup", "Trading_old" or "Trading2" matches as a
      substring and its shortcuts get swept too. Caught by
      tests/Test-ShortcutSweep.ps1, which calls this function rather than
      rebuilding the pattern -- so the test can never drift from the code.
    #>
    param([string] $Path)
    return [Regex]::Escape($Path.TrimEnd('\')) + '(?=[\\/"''\s]|$)'
}

$projectEscaped = Get-ProjectPathPattern -Path $ProjectDir

function Get-ShortcutMatchReason {
    <#
      The single decision that authorises a delete. Kept as one pure function
      so it can be tested without COM or a real Desktop:
      tests/Test-ShortcutSweep.ps1 feeds it synthetic shortcuts.

      Returns a reason string when the shortcut belongs to this project, or
      $null when it must be left alone. Name alone is deliberately NOT enough
      -- "Trading" is a common word and a false positive here deletes
      somebody's unrelated shortcut.
    #>
    param(
        [string] $Name,
        [string] $Target,
        [string] $WorkingDirectory,
        [string] $Arguments,
        [string] $ProjectPattern,
        [string] $OurName
    )
    $blob = "$Target $WorkingDirectory $Arguments"
    if ($blob -match $ProjectPattern) { return 'points into this project folder' }
    if ($Name -eq $OurName)           { return 'same name as the shortcut we create' }
    if ($blob -match 'start-dev\.bat') { return 'launches start-dev.bat' }
    return $null
}

$searchRoots = @($DesktopPath)
if ($env:PUBLIC) {
    $publicDesktop = Join-Path $env:PUBLIC 'Desktop'
    if (Test-Path $publicDesktop) { $searchRoots += $publicDesktop }
}

$stale = [System.Collections.ArrayList]::new()

foreach ($root in $searchRoots) {
    Get-ChildItem -Path $root -Filter '*.lnk' -File -ErrorAction SilentlyContinue | ForEach-Object {
        $lnk = $_
        try   { $sc = $WshShell.CreateShortcut($lnk.FullName) }
        catch { return }

        $target = "$($sc.TargetPath)"
        $workdir = "$($sc.WorkingDirectory)"
        $scArgs  = "$($sc.Arguments)"

        $why = Get-ShortcutMatchReason -Name $lnk.Name -Target $target `
                   -WorkingDirectory $workdir -Arguments $scArgs `
                   -ProjectPattern $projectEscaped -OurName $ShortcutName

        if ($why) {
            $null = $stale.Add([PSCustomObject]@{
                Path   = $lnk.FullName
                Kind   = 'lnk'
                Detail = if ($target) { $target } else { '(no target)' }
                Why    = $why
            })
        }
    }

    Get-ChildItem -Path $root -Filter '*.url' -File -ErrorAction SilentlyContinue | ForEach-Object {
        $url = (Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue)
        if ($url -match $devUrlPattern) {
            $null = $stale.Add([PSCustomObject]@{
                Path   = $_.FullName
                Kind   = 'url'
                Detail = (($url -split "`n" | Where-Object { $_ -match '^URL=' }) -join '').Trim()
                Why    = 'opens a dev port of this app'
            })
        }
    }
}

# The two loose .url files that have sat in the project root since April.
foreach ($name in @('Trading Dashboard.url', 'Trading API Docs.url')) {
    $p = Join-Path $ProjectDir $name
    if (Test-Path $p) {
        $url = (Get-Content $p -Raw -ErrorAction SilentlyContinue)
        $null = $stale.Add([PSCustomObject]@{
            Path   = $p
            Kind   = 'url'
            Detail = (($url -split "`n" | Where-Object { $_ -match '^URL=' }) -join '').Trim()
            Why    = 'loose .url in the project root'
        })
    }
}

$stale = @($stale | Sort-Object Path -Unique)

# ---------------------------------------------------------------------------
# 2. Show, then remove
# ---------------------------------------------------------------------------
if ($stale.Count -eq 0) {
    Write-Head 'Nothing stale to remove'
    Write-Host '  No existing Trading shortcuts found.' -ForegroundColor DarkGray
}
else {
    Write-Head "Found $($stale.Count) shortcut(s) to remove"
    foreach ($s in $stale) {
        Write-Host "  - $($s.Path)" -ForegroundColor Yellow
        Write-Host "      $($s.Detail)" -ForegroundColor DarkGray
        Write-Host "      matched: $($s.Why)" -ForegroundColor DarkGray
    }

    $go = $true
    if ($DryRun) {
        $go = $false
        Write-Host ''
        Write-Host '  -DryRun: nothing was deleted.' -ForegroundColor DarkGray
    }
    elseif (-not $Force) {
        Write-Host ''
        $answer = Read-Host '  Delete these? [y/N]'
        $go = ($answer -match '^(y|yes)$')
        if (-not $go) { Write-Host '  Skipped deletion.' -ForegroundColor DarkGray }
    }

    if ($go) {
        foreach ($s in $stale) {
            try {
                Remove-Item -LiteralPath $s.Path -Force
                Write-Host "  removed  $($s.Path)" -ForegroundColor DarkGreen
            }
            catch {
                Write-Host "  FAILED   $($s.Path) -- $($_.Exception.Message)" -ForegroundColor Red
            }
        }
    }
}

# ---------------------------------------------------------------------------
# 3. Create the new launcher
# ---------------------------------------------------------------------------
if ($DryRun) {
    Write-Head 'Would create'
    Write-Host "  $ShortcutPath  ->  $TargetBat"
    return
}

$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath       = $TargetBat
$Shortcut.WorkingDirectory = $ProjectDir
$Shortcut.Description      = 'VN Sector Money-Flow -- backend :8000 + frontend :5173'
$Shortcut.WindowStyle      = 1

if (Test-Path $IconPath) {
    $Shortcut.IconLocation = $IconPath
} else {
    $Shortcut.IconLocation = 'shell32.dll,13'
}
$Shortcut.Save()

Write-Head 'Desktop shortcut created'
Write-Host "  Name    : VN Trading"
Write-Host "  Runs    : $TargetBat"
Write-Host "  Folder  : $ProjectDir"
if (Test-Path $IconPath) {
    Write-Host "  Icon    : $IconPath"
} else {
    Write-Host "  Icon    : shell32.dll,13 (favicon.ico not found)" -ForegroundColor DarkGray
}
Write-Host ''
Write-Host '  Double-click "VN Trading" on your Desktop to start both servers.' -ForegroundColor Green
Write-Host '  It opens http://localhost:5173 once they are up.'
Write-Host ''
