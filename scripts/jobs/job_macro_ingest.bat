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
REM job: macro_ingest       cron: 0 * * * *      (hourly, §8)
call "%~dp0_env.bat"
%PY% -u main.py --macro >> "%JOB_LOG_DIR%\macro_ingest.log" 2>&1
exit /b %errorlevel%
