# ============================================================================
# tests/Test-ShortcutSweep.ps1
# ============================================================================
# Guards the one decision in create_desktop_shortcut.ps1 that deletes files:
# Get-ShortcutMatchReason. A false positive here removes an unrelated shortcut
# from the user's Desktop, so the rule is pinned by example.
#
#   pwsh -NoProfile -File tests/Test-ShortcutSweep.ps1
#
# Pure: no COM, no Desktop, no filesystem writes. Runs on any platform.
# ============================================================================

$ErrorActionPreference = 'Stop'

# Load only the function under test, without executing the installer body.
$scriptPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'create_desktop_shortcut.ps1'
if (-not (Test-Path $scriptPath)) {
    $scriptPath = Join-Path $PSScriptRoot 'create_desktop_shortcut.ps1'
}
$ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$null, [ref]$null)
foreach ($name in @('Get-ProjectPathPattern', 'Get-ShortcutMatchReason')) {
    $fn = $ast.Find({ param($n)
        $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $n.Name -eq $name }, $true)
    if (-not $fn) { throw "$name not found in $scriptPath" }
    . ([scriptblock]::Create($fn.Extent.Text))
}

$ProjectDir = 'C:\Users\admin\Documents\claude\Trading'
# Built by the script's own function, never re-derived here.
$Pattern    = Get-ProjectPathPattern -Path $ProjectDir
$OurName    = 'VN Trading.lnk'

$pass = 0; $fail = 0
function Check($label, $expectMatch, $name, $target, $wd = '', $argv = '') {
    $why = Get-ShortcutMatchReason -Name $name -Target $target -WorkingDirectory $wd `
               -Arguments $argv -ProjectPattern $script:Pattern -OurName $script:OurName
    $got = [bool]$why
    if ($got -eq $expectMatch) {
        $script:pass++
        Write-Host ("  PASS  {0}" -f $label) -ForegroundColor DarkGreen
    } else {
        $script:fail++
        Write-Host ("  FAIL  {0}`n        expected match={1}, got '{2}'" -f $label, $expectMatch, $why) -ForegroundColor Red
    }
}

Write-Host ''
Write-Host '  Shortcuts that MUST be swept' -ForegroundColor Cyan

Check 'the shortcut this script creates' $true `
    'VN Trading.lnk' "$ProjectDir\start-dev.bat" $ProjectDir

Check 'renamed copy still pointing at the project' $true `
    'Trading OLD.lnk' "$ProjectDir\start-dev.bat" $ProjectDir

Check 'cmd wrapper with the project only in its arguments' $true `
    'launch.lnk' 'C:\Windows\System32\cmd.exe' '' "/c `"$ProjectDir\start-dev.bat`""

Check 'project referenced only via working directory' $true `
    'run.lnk' 'C:\Windows\System32\cmd.exe' $ProjectDir '/c echo hi'

Check 'start-dev.bat from a previous project location' $true `
    'VN Trading old path.lnk' 'D:\old\Trading\start-dev.bat' 'D:\old\Trading'

Check 'name match even with a dead target' $true `
    'VN Trading.lnk' '' ''

Write-Host ''
Write-Host '  Shortcuts that MUST be left alone' -ForegroundColor Cyan

Check 'unrelated app that merely says Trading' $false `
    'My Trading Journal.lnk' 'C:\Program Files\Journal\journal.exe' 'C:\Program Files\Journal'

Check 'a different project also called Trading' $false `
    'Trading.lnk' 'C:\Users\admin\Desktop\OtherTrading\run.bat' 'C:\Users\admin\Desktop\OtherTrading'

Check 'plain browser shortcut' $false `
    'Chrome.lnk' 'C:\Program Files\Google\Chrome\Application\chrome.exe'

Check 'VN-prefixed but unrelated' $false `
    'VN Bank.lnk' 'C:\Apps\vnbank.exe' 'C:\Apps'

Check 'similarly named file in a sibling folder' $false `
    'dev.lnk' 'C:\Users\admin\Documents\claude\TradingBackup\start-dev2.bat' 'C:\Users\admin\Documents\claude\TradingBackup'

Write-Host ''
Write-Host '  File encoding (regression guard, 2026-08-22)' -ForegroundColor Cyan

# Windows PowerShell 5.1 decodes a BOM-less .ps1 using the system ANSI
# codepage, NOT UTF-8. On a Vietnamese Windows (CP1258) an em dash written as
# UTF-8 (E2 80 94) came back as three characters ending in U+201D -- and PS
# treats a curly double quote as a STRING DELIMITER. That closed a string
# early on line 196 and the parser desynchronised, reporting a bogus
# "string is missing the terminator" 40 lines later. The script would not run
# at all. Two independent defences, both checked here:
#   1. the file is pure ASCII, so no codepage can change its meaning;
#   2. it carries a UTF-8 BOM, so 5.1 decodes it as UTF-8 regardless.
$installer = $scriptPath

$bytes = [System.IO.File]::ReadAllBytes($installer)
$hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
if ($hasBom) { $pass++; Write-Host '  PASS  installer has a UTF-8 BOM' -ForegroundColor DarkGreen }
else { $fail++; Write-Host '  FAIL  installer has no UTF-8 BOM -- PowerShell 5.1 will read it as ANSI' -ForegroundColor Red }

$body = if ($hasBom) { $bytes[3..($bytes.Length - 1)] } else { $bytes }
$nonAscii = @($body | Where-Object { $_ -gt 127 })
if ($nonAscii.Count -eq 0) { $pass++; Write-Host '  PASS  installer is pure ASCII' -ForegroundColor DarkGreen }
else { $fail++; Write-Host "  FAIL  installer has $($nonAscii.Count) non-ASCII byte(s) -- use -- instead of an em dash" -ForegroundColor Red }

Write-Host ''
if ($fail -gt 0) {
    Write-Host ("  {0} passed, {1} FAILED" -f $pass, $fail) -ForegroundColor Red
    exit 1
}
Write-Host ("  {0} passed, 0 failed" -f $pass) -ForegroundColor Green
Write-Host ''
