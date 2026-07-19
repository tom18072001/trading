# Daily Report Automation

Last updated: 2026-04-22.

## Generator

The active daily email generator is `generate_secv4.py` at the repo root.
`generate_secv3.py` is retained as the rollback path (`CLAUDE.md` §2) and
takes identical CLI arguments. The retired `scripts/daily_stale_report.py`,
`send_email_report.py`, and `generate_sector_flow_enhanced.py` have been
moved to `_trash_20260422/` and must not be re-introduced.

### Invocation
```
python generate_secv4.py                 # today (Asia/Ho_Chi_Minh), email enabled
python generate_secv4.py 2026-04-21      # specific date
python generate_secv4.py 2026-04-21 --no-email   # render only, skip SMTP
```

### Outputs
- `report/secv4_<YYYY-MM-DD>.html` — inline-styled HTML with embedded charts.
- `report/secv4_<YYYY-MM-DD>.pdf` — WeasyPrint render of the same HTML.
Both are attached to the email; the HTML body is also embedded inline so the
recipient can preview without opening the attachment.

## Email delivery

SMTP config lives in `.env` at the repo root:
```
REPORT_EMAIL_FROM=anhchitruong18@gmail.com
REPORT_EMAIL_PASSWORD=<16-char Gmail App Password>
REPORT_EMAIL_TO=anhchitruong18@gmail.com,hill.nguyen.1373@gmail.com
```
- Gmail requires an **App Password** (Account → Security → 2-Step Verification
  → App passwords). Normal account passwords will not work over SMTP-SSL:465.
- `REPORT_EMAIL_TO` is **comma-separated**. `generate_secv4.py` (and `generate_secv3.py`)
  split it on commas, put the entire list in the `To:` header, and pass the
  list to `smtplib.sendmail` so every address actually receives the message.
  Both recipients see each other — this is TO, not BCC.
- Default fallback (if the env var is unset) is the same two-address string.

## Scheduled run

Job name: `SectorFlow_sector_signal_publish` (cron `0 17 * * 1-5` Asia/Ho_Chi_Minh).
Registered by `scripts/cleanup_scheduled_tasks.ps1`. Wrapper:
`scripts/jobs/job_sector_signal_publish.bat`. It runs two steps:

1. `python main.py --publish` — writes the day's `sector_signals` rows. Logs to
   `report/jobs/sector_signal_publish.log`. If this step fails (non-zero exit),
   step 2 is **skipped** and the email is NOT sent — a `[signal_publish] publish
   step failed` line is appended to the same log.
2. `python generate_secv4.py` — renders + emails. Logs to
   `report/jobs/sector_signal_email.log`. SMTP confirmation line:
   `[secv4] [SENT] <recipients>`.

## Manual re-send

If the scheduled run failed (e.g., DB corruption, SMTP timeout), re-send
manually from the repo root:
```
.venv\Scripts\python.exe generate_secv4.py               # today
.venv\Scripts\python.exe generate_secv4.py YYYY-MM-DD    # backfill
```

## PDF engine

WeasyPrint is the only supported renderer. Install:
```
pip install weasyprint --break-system-packages
```
On Windows, WeasyPrint pulls GTK binaries automatically in recent versions.
If PDF generation fails the generator falls back to HTML-only email — no
silent failure.

## Known gotchas

- **DB corruption** on a network share: see `CLAUDE.md` §18.4/18. Symptom is
  `sqlite3.DatabaseError: database disk image is malformed`. Recover from
  `vnstock_market.db.healed_<DATE>` if present; otherwise re-run the 02:00
  `rotation_train` after restoring from backup.
- **Email silently skipped**: check `REPORT_EMAIL_FROM` / `REPORT_EMAIL_PASSWORD`
  are set — the generator prints `[secv4] SMTP creds missing — skipping email`
  and exits 0.
- **TraderAgent narrative missing**: `services/trader_agent.py` needs
  `claude_agent_sdk` + a working Claude CLI. In a sandbox without the CLI,
  the generator falls back to the algorithmic narrative (no Minh voiceover)
  and logs `[trader-agent] query failed`. Not a production regression.
