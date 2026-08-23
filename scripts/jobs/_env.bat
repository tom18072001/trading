@echo off
REM ============================================================
REM scripts\jobs\_env.bat - shared env for every scheduled job.
REM Sourced by each job_*.bat via `call %~dp0_env.bat`.
REM
REM Design rules (post-mortem 2026-07-19):
REM  1. NO absolute paths. Root is derived from this script's own
REM     location, so moving the project never breaks the jobs.
REM  2. Interpreter goes through `uv run`, which resolves the
REM     project venv from pyproject.toml/uv.lock and REBUILDS it
REM     if missing or orphaned. The previous direct .venv path
REM     silently broke for 25 days when the uv-managed base
REM     interpreter disappeared.
REM  3. Fallbacks: uv run -> .venv python -> PATH python.
REM ============================================================

REM Force UTF-8 for stdout/stderr. Without this the console falls back to
REM cp1258/cp437 and every vnstock row with Vietnamese text dies with
REM "'charmap' codec can't encode characters ..." (seen 2026-08).
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

REM scripts\jobs\ is two levels below the project root.
for %%I in ("%~dp0..\..") do set "TRADING_ROOT=%%~fI"

where uv >nul 2>&1
if %errorlevel%==0 (
  set "PY=uv run python"
) else if exist "%TRADING_ROOT%\.venv\Scripts\python.exe" (
  set "PY=%TRADING_ROOT%\.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

set "JOB_LOG_DIR=%TRADING_ROOT%\report\jobs"
if not exist "%JOB_LOG_DIR%" mkdir "%JOB_LOG_DIR%"

REM Log rotation. Jobs append with >>, so a log that never rotates only
REM grows - sector_intraday_flow.log reached 6.5 MB of repeated errors
REM before anyone noticed (2026-08). Roll at 5 MB, keep one generation.
REM Runs before the job opens its log, so the handle is never in use.
for %%L in ("%JOB_LOG_DIR%\*.log") do (
  if %%~zL GTR 5242880 (
    if exist "%%~fL.1" del /q "%%~fL.1"
    move /y "%%~fL" "%%~fL.1" >nul
  )
)

cd /d "%TRADING_ROOT%"
