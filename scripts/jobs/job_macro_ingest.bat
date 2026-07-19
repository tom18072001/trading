@echo off
REM job: macro_ingest       cron: 0 * * * *      (hourly, §8)
call "%~dp0_env.bat"
%PY% -u main.py --macro >> "%JOB_LOG_DIR%\macro_ingest.log" 2>&1
exit /b %errorlevel%
