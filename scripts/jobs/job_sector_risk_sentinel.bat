@echo off
REM job: sector_risk_sentinel   cron: */30 9-15 * * 1-5   (§8)
call "%~dp0_env.bat"
%PY% -u main.py --risk-sentinel >> "%JOB_LOG_DIR%\sector_risk_sentinel.log" 2>&1
exit /b %errorlevel%
