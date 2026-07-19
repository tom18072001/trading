@echo off
REM job: rotation_train   cron: 0 2 * * *   (§8; runs daily — monthly schedule
REM                                          per §16.4 lives in the service)
call "%~dp0_env.bat"
%PY% -u main.py --train >> "%JOB_LOG_DIR%\rotation_train.log" 2>&1
exit /b %errorlevel%
