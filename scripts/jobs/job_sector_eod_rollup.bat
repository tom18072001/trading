@echo off
REM job: sector_eod_rollup   cron: 0 16 * * 1-5   (§8)
call "%~dp0_env.bat"
%PY% -u main.py --eod-rollup >> "%JOB_LOG_DIR%\sector_eod_rollup.log" 2>&1
exit /b %errorlevel%
