@echo off
REM job: sector_intraday_flow   cron: */15 9-15 * * 1-5   (§8)
call "%~dp0_env.bat"
%PY% -u main.py --intraday >> "%JOB_LOG_DIR%\sector_intraday_flow.log" 2>&1
exit /b %errorlevel%
