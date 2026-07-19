@echo off
REM job: freshness_check    cron: 0 18 * * *    (daily, after signal_publish)
REM Exits non-zero when sector_flow_daily is stale -> visible in Task Scheduler.
call "%~dp0_env.bat"
%PY% -u scripts\check_freshness.py >> "%JOB_LOG_DIR%\freshness_check.log" 2>&1
exit /b %errorlevel%
