"""Run `generate_report.py` on demand, from a button (backlog step 6).

The daily email only ever went out from Task Scheduler at 17:00 (§8). If the
job failed, or you changed something and wanted today's mail again, the only
way was a terminal on this machine.

Why subprocess and not an import: `generate_report.py` is 1,629 lines of
module-level code driven by `sys.argv` with no `main()` (§20.3 P3-2). Importing
it would run the whole report — including the SMTP send — as a side effect of
the import statement, once per process, and never again. A subprocess is the
honest way to call a script that is a script.

Same thread + status-poll shape as services/insight_refresh.py, minus the
stages: there is one stage, and it takes 30-90s.

ponytail: one run at a time, status kept in memory only. If a second operator
or a restart-survivable history is ever wanted, this becomes a table like
`model_runs`. Today the log file on disk is the durable record.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable

from config import BASE_DIR

log = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMEOUT_SEC = 900
_TAIL_CHARS = 2000

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "report_date": None,
    "started_at": None,
    "finished_at": None,
    "ok": None,
    "returncode": None,
    "tail": "",
}


def _default_runner(argv: list[str]) -> tuple[int, str]:
    p = subprocess.run(  # noqa: S603 — argv is built here, never from the caller
        [sys.executable, "generate_report.py", *argv],
        cwd=BASE_DIR, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=_TIMEOUT_SEC,
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def get_status() -> dict[str, Any]:
    with _lock:
        s = dict(_state)
    if s["running"] and s["started_at"]:
        s["elapsed_sec"] = round(time.time() - s["started_at"], 1)
    return s


def send_report(
    report_date: str | None = None,
    send_email: bool = True,
    runner: Callable[[list[str]], tuple[int, str]] | None = None,
) -> dict[str, Any]:
    """Kick a background report run. Returns immediately.

    A second call while one is in flight is a no-op that reports the run
    already going — clicking twice must not send two emails.
    """
    if report_date is not None and not _DATE_RE.match(report_date):
        raise ValueError(f"report_date must be YYYY-MM-DD, got {report_date!r}")

    argv = ([report_date] if report_date else []) + ([] if send_email else ["--no-email"])
    run = runner or _default_runner

    with _lock:
        if _state["running"]:
            return {**_state, "already_running": True}
        _state.update(running=True, report_date=report_date, started_at=time.time(),
                      finished_at=None, ok=None, returncode=None, tail="")

    def _worker() -> None:
        try:
            code, out = run(argv)
            ok, tail = code == 0, out[-_TAIL_CHARS:]
        except Exception as e:                       # timeout, missing python, ...
            log.exception("[report] run failed")
            code, ok, tail = -1, False, str(e)
        with _lock:
            _state.update(running=False, finished_at=time.time(),
                          ok=ok, returncode=code, tail=tail)

    threading.Thread(target=_worker, daemon=True, name="report-send").start()
    return {**get_status(), "already_running": False}


def reset_for_tests() -> None:
    with _lock:
        _state.update(running=False, report_date=None, started_at=None,
                      finished_at=None, ok=None, returncode=None, tail="")
