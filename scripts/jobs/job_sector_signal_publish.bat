@echo off
REM --- self-hide (2026-08-22) ------------------------------------------
REM Task Scheduler launches this as `cmd.exe /c`, which ALWAYS creates a
REM visible console, and repointing the task action needs admin. So the
REM job detaches itself through run_hidden.vbs and returns immediately:
REM the console lives ~0.2s instead of the whole run.
REM
REM run_hidden.vbs is deliberate here (fire-and-forget). The waiting
REM variant would keep cmd.exe - and its window - alive for the whole
REM job, which is the very thing we are removing. Losing Task Scheduler's
REM "do not start a new instance" guard is safe because utils/vnstock_gate
REM job_lock() now enforces that across processes.
REM
REM The _hidden_ marker stops a second relaunch once the task itself is
REM repointed to wscript (scripts/jobs/apply_hidden_jobs.bat).
if /i not "%~1"=="_hidden_" (
  wscript.exe "%~dp0run_hidden.vbs" "%~f0" _hidden_
  exit /b 0
)
REM ---------------------------------------------------------------------
REM job: sector_signal_publish   cron: 0 17 * * 1-5   (§8)
REM Two-step: (1) publish signals; (2) send the unified email to
REM REPORT_EMAIL_TO (see .env). Logs are kept side-by-side so a failure
REM in step 1 is visible without having to open the email log.
REM
REM History: the generator was once versioned (secv2..secv5). Those copies
REM were deleted; on 2026-08-22 the survivor was renamed to generate_report.py
REM and the version suffix was dropped everywhere. It is the sole generator.
call "%~dp0_env.bat"
%PY% -u main.py --publish > "%JOB_LOG_DIR%\sector_signal_publish.log" 2>&1
if errorlevel 1 goto :publish_failed
%PY% -u generate_report.py > "%JOB_LOG_DIR%\sector_signal_email.log" 2>&1
exit /b %errorlevel%

:publish_failed
echo [signal_publish] publish step failed (see log) — skipping email. >> "%JOB_LOG_DIR%\sector_signal_publish.log"
exit /b 1
