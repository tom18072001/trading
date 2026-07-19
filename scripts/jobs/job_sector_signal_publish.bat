@echo off
REM job: sector_signal_publish   cron: 0 17 * * 1-5   (§8)
REM Two-step: (1) publish signals; (2) send SecV5 unified email to
REM REPORT_EMAIL_TO (see .env). Logs are kept side-by-side so a failure
REM in step 1 is visible without having to open the email log.
REM
REM 2026-04-23: flipped from generate_secv4.py to generate_secv5.py per
REM Tom's directive — SecV5 unifies Daily Insight picks + ranker picks
REM so the email no longer disagrees with the dashboard.
REM 2026-06-18: generate_secv3.py and generate_secv4.py DELETED — secv5 is
REM now the sole generator (no rollback scripts on disk).
call "%~dp0_env.bat"
%PY% -u main.py --publish > "%JOB_LOG_DIR%\sector_signal_publish.log" 2>&1
if errorlevel 1 goto :publish_failed
%PY% -u generate_secv5.py > "%JOB_LOG_DIR%\sector_signal_email.log" 2>&1
exit /b %errorlevel%

:publish_failed
echo [signal_publish] publish step failed (see log) — skipping email. >> "%JOB_LOG_DIR%\sector_signal_publish.log"
exit /b 1
