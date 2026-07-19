@echo off
REM job: rotation_predict   cron: 45 16 * * 1-5   (§8)
call "%~dp0_env.bat"
%PY% -u main.py --rotation-predict >> "%JOB_LOG_DIR%\rotation_predict.log" 2>&1
exit /b %errorlevel%
