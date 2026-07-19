"""One-off failure notifier for the 2026-04-26 SecV5 daily-brief scheduled task.

Auxiliary script — does NOT touch trading logic or schema. Reads SMTP creds
from .env (REPORT_EMAIL_FROM / REPORT_EMAIL_PASSWORD / REPORT_EMAIL_TO),
sends a plain-text failure note + tail of the publish error log to Tom.
"""
from __future__ import annotations

import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(r"C:\Users\admin\Documents\claude\Trading")
ENV  = ROOT / ".env"
PUB_LOG = ROOT / "report" / "jobs" / "sector_signal_publish.log"
PUB_ERR = ROOT / "report" / "jobs" / "sector_signal_publish.log.err"


def load_env(p: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def tail(p: Path, n: int = 60) -> str:
    if not p.exists():
        return f"(missing: {p})"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-n:])


def main() -> int:
    env = load_env(ENV)
    sender   = env.get("REPORT_EMAIL_FROM", "")
    password = env.get("REPORT_EMAIL_PASSWORD", "")
    rcpts    = [r.strip() for r in env.get("REPORT_EMAIL_TO", "").split(",") if r.strip()]
    if not (sender and password and rcpts):
        print("[fail-notify] missing SMTP env vars", file=sys.stderr)
        return 2

    body = (
        "Cao bao SecV5 cho 2026-04-26 (Chu Nhat) FAILED.\n\n"
        "Trigger: scheduled-task 'secv3-daily-brief' (Cowork).\n"
        "Active path per CLAUDE.md (2026-04-23): generate_secv5.py.\n"
        "Original task spec referenced generate_secv4.py / _run_secv4.bat — that\n"
        "batch was archived to _trash_20260422 and SecV5 is the production path.\n\n"
        "RESULT: publish step failed; email step skipped.\n\n"
        "Root cause #1 (FIXED during this run):\n"
        "  .venv interpreter shim pointed at a missing uv-managed Python\n"
        "  (cpython-3.13.12). Restored via `uv python install 3.13.12`.\n"
        "  All scheduled jobs today (macro_ingest, regime_classify,\n"
        "  rotation_predict, sector_eod_rollup, sector_intraday_flow,\n"
        "  sector_risk_sentinel, sector_signal_publish) had been failing on\n"
        "  the same 'did not find executable' error since at least 5:00 PM.\n\n"
        "Root cause #2 (BLOCKER, NOT FIXED — needs Tom):\n"
        "  sqlite3.DatabaseError: database disk image is malformed\n"
        "  Hit in services/sector_signal_service.py::_stealth_sectors\n"
        "  on a SELECT … GROUP BY against SectorFlowDaily. Per CLAUDE.md\n"
        "  this is out of scope for the scheduled task to repair without\n"
        "  approval.\n\n"
        "Suggested next steps for Tom:\n"
        "  1. Run integrity check:\n"
        "       sqlite3 <db>  \"PRAGMA integrity_check;\"\n"
        "  2. If corruption is local, attempt:\n"
        "       sqlite3 <db> \".recover\" | sqlite3 <db>.recovered\n"
        "     and swap files; otherwise restore from last good backup\n"
        "     (DB lives on local disk per §18.4/18 hygiene rule).\n"
        "  3. Investigate why .venv shim went stale — likely a uv prune\n"
        "     or python uninstall earlier today.\n"
        "  4. Once DB is clean, re-run scripts\\jobs\\job_sector_signal_publish.bat\n"
        "     manually to send today's missed brief.\n\n"
        "No SMTP send was attempted for the daily brief itself — the\n"
        "publish failure stops generate_secv5 from being invoked at all,\n"
        "so there is no risk of a duplicate report.\n\n"
        "===== Tail: sector_signal_publish.log =====\n"
        f"{tail(PUB_LOG, 30)}\n\n"
        "===== Tail: sector_signal_publish.log.err =====\n"
        f"{tail(PUB_ERR, 80)}\n"
    )

    msg = EmailMessage()
    msg["From"]    = sender
    msg["To"]      = ", ".join(rcpts)
    msg["Subject"] = "[SecV5] FAILED 2026-04-26 — DB corruption (publish skipped)"
    msg.set_content(body)

    ctx = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
        s.ehlo(); s.starttls(context=ctx); s.ehlo()
        s.login(sender, password)
        s.send_message(msg)
    print(f"[fail-notify] [SENT] {', '.join(rcpts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
