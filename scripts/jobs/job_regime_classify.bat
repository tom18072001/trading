@echo off
REM job: regime_classify   cron: 30 16 * * 1-5   (§8)
call "%~dp0_env.bat"
%PY% -u main.py --regime >> "%JOB_LOG_DIR%\regime_classify.log" 2>&1
exit /b %errorlevel%
