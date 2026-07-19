# ============================================
# Create Desktop Shortcut for VN Trading App
# Run: powershell -ExecutionPolicy Bypass -File create_desktop_shortcut.ps1
# ============================================

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $DesktopPath "VN Trading.lnk"
$TargetBat = Join-Path $ProjectDir "start-dev.bat"
$IconPath = Join-Path $ProjectDir "frontend\public\favicon.ico"

# Create WScript.Shell COM object
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)

$Shortcut.TargetPath = $TargetBat
$Shortcut.WorkingDirectory = $ProjectDir
$Shortcut.Description = "VN Sector Money-Flow Trading System"
$Shortcut.WindowStyle = 1  # Normal window

# Use custom icon if available, else use default
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = $IconPath
} else {
    # Use a stock chart icon from shell32
    $Shortcut.IconLocation = "shell32.dll,13"
}

$Shortcut.Save()

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Desktop shortcut created successfully!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Location : $ShortcutPath"
Write-Host "  Target   : $TargetBat"
Write-Host "  Action   : Starts Backend (FastAPI :8000) + Frontend (Vite :5173)"
Write-Host ""
Write-Host "  Double-click 'VN Trading' on your Desktop to launch!" -ForegroundColor Cyan
Write-Host ""
