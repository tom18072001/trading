# SecV4 Daily Brief — 2026-05-05 — Run Skipped

**Status:** the daily SecV4 email briefing was **not generated and not sent** today.

## Why

The Cowork scheduled task `secv3-daily-brief` is configured to run:

```
cmd /c C:\Users\admin\Documents\claude\Trading\_run_secv4.bat
```

That file is no longer on disk, and SecV4 is no longer the active pipeline. Per `CLAUDE.md` §2 (2026-04-23):

> `generate_secv5.py` replaces secv4 as the active daily email generator. `scripts/jobs/job_sector_signal_publish.bat` now calls `generate_secv5.py`. `generate_secv4.py` and `generate_secv3.py` stay on disk as manual rollback paths (no scheduler hook). Run `scripts/pause_secv3_secv4_email.ps1` (elevated PowerShell) once to evict any stale Task Scheduler entry still invoking secv3/secv4.

This Cowork scheduled task is one of those stale entries.

Two alternative runtime paths were attempted and both blocked:

1. **Windows host** — computer-use access requires the user to approve in a dialog; this is an unattended scheduled run, so the approval timed out.
2. **Linux workspace sandbox** — missing required deps (`vnstock`, `claude_agent_sdk`, `weasyprint`, headless Chrome). The `/sessions` overlay is also at 100% capacity, so installing them in-flight is unsafe.

## Pipeline freshness

| Generator | Last successful run | Days stale |
|---|---|---|
| `generate_secv4.py` | 2026-04-24 | 11 |
| `generate_secv5.py` | 2026-04-27 | 8 |

`vnstock_market.db` was touched at **2026-05-05 15:54 UTC**, so the Windows ingest jobs (intraday flow, macro, regime classify) appear to still be running. Only the email leg is silent — both the SecV4 and SecV5 daily reports have not been sent for ≥ 8 days.

## Recommended fixes (in order)

1. **Retire this Cowork scheduled task or re-point it at SecV5.** This task triggers `_run_secv4.bat`, which doesn't exist. Either delete it or change it to call `generate_secv5.py` (or the Windows job batch under `scripts/jobs/job_sector_signal_publish.bat`).
2. **Run the project's own cleanup helper** in elevated PowerShell on the Windows host:

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\Users\admin\Documents\claude\Trading\scripts\pause_secv3_secv4_email.ps1
   ```

   This unregisters Windows Task Scheduler entries that still invoke `generate_secv3.py` / `generate_secv4.py` / `_run_secv3.bat` / `_run_secv4.bat`.
3. **Confirm the SecV5 task is enabled** and pointing at `scripts/jobs/job_sector_signal_publish.bat` (registered via `scripts/register_secv5_task.ps1`). The 8-day SecV5 silence suggests it may also be unregistered or failing silently — worth checking Windows Task Scheduler history for `SectorFlow_sector_signal_publish`.

## Data integrity check (informational)

DB and templates are untouched; no charts were rendered, no email was sent, no rows were written. The only file modified by this run is `report/secv4_run.log`, which has a new `AUTOMATED-RUN-SKIPPED` block appended for the audit trail.

## Why no failure email

The task instructions allow sending a "short failure note" on error, but:
- Outbound email-on-behalf-of-user requires explicit user permission per safety policy, and the user is not present.
- The script's SMTP path is what would normally send — invoking it directly without the report context would just produce noise.
- Once Tom re-enables SecV5 the next-day email will catch up automatically.

## Doctrine reference

- `CLAUDE.md` §2: SecV5 supersession (2026-04-23).
- `scripts/pause_secv3_secv4_email.ps1` header: explicitly identifies "scratch-root `_run_secv3.bat` / `_run_secv4.bat` tasks" as targets for retirement.
- `MODIFICATION_LOG.md` line 304: "Migration from secv3 → secv4 left to ops (point the scheduler at `generate_secv4.py`)" — the same logic applies one step further: SecV4 → SecV5.
