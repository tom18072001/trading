"""utils.vnstock_gate - throttle, rate-limit retry, cross-process lock.

Regression cover for the 2026-08-22 fix: sector ingest paced by symbol
instead of by call, and overlapping scheduled jobs shared one quota.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from utils import vnstock_gate as g

ROOT = Path(__file__).resolve().parents[1]


def test_throttle_paces_by_call(monkeypatch):
    monkeypatch.setattr(g, "MAX_PER_MIN", 3)
    monkeypatch.setattr(g, "WINDOW_SEC", 2.0)
    g._CALLS.clear()
    t0 = time.monotonic()
    for _ in range(4):
        g.throttle()
    assert time.monotonic() - t0 >= 1.8


def test_rate_limit_is_retried(monkeypatch):
    monkeypatch.setattr(g, "BACKOFF", (0.01, 0.01))
    g._CALLS.clear()
    seen = {"n": 0}

    def flaky():
        seen["n"] += 1
        if seen["n"] < 3:
            raise SystemExit("Rate limit exceeded.")
        return "ok"

    assert g.call(flaky, what="t") == "ok"
    assert seen["n"] == 3


def test_gives_up_and_returns_none(monkeypatch):
    monkeypatch.setattr(g, "BACKOFF", (0.01,))
    g._CALLS.clear()

    def always():
        raise SystemExit("Rate limit exceeded.")

    assert g.call(always, what="t") is None


def test_non_rate_limit_error_is_not_retried(monkeypatch):
    g._CALLS.clear()
    seen = {"n": 0}

    def broken():
        seen["n"] += 1
        raise ValueError("bad payload")

    assert g.call(broken, what="t") is None
    assert seen["n"] == 1


HOLDER = (
    "import sys, time;"
    "sys.path.insert(0, sys.argv[1]);"
    "from utils.vnstock_gate import job_lock;"
    "ctx = job_lock('pytest-xproc', 5);"
    "print(ctx.__enter__(), flush=True);"
    "time.sleep(6);"
    "ctx.__exit__(None, None, None)"
)


def test_lock_excludes_a_second_process():
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(ROOT)],
                              cwd=str(ROOT), stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "True"
        with g.job_lock("pytest-xproc", wait_sec=2) as got:
            assert got is False
    finally:
        holder.wait(timeout=20)

    with g.job_lock("pytest-xproc", wait_sec=2) as got:
        assert got is True
