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

cd /d "%TRADING_ROOT%"
