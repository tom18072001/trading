"""services/report_runner.py — the "Gửi báo cáo ngay" button (backlog step 6).

The one thing worth guarding: a second click must NOT send a second email.
Everything else here is argv construction and failure reporting.

No subprocess is ever spawned — `send_report(runner=...)` takes the runner as a
parameter for exactly this reason.
"""
from __future__ import annotations

import threading
import time

import pytest

from services import report_runner


@pytest.fixture(autouse=True)
def _clean():
    report_runner.reset_for_tests()
    yield
    report_runner.reset_for_tests()


def _wait_idle(timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if not report_runner.get_status()["running"]:
            return report_runner.get_status()
        time.sleep(0.01)
    raise AssertionError("run never finished")


def test_argv_default_is_bare_send():
    seen: list[list[str]] = []
    report_runner.send_report(runner=lambda a: (seen.append(a), (0, "ok"))[1])
    _wait_idle()
    assert seen == [[]]


def test_no_email_flag_and_date_are_passed_through():
    seen: list[list[str]] = []
    report_runner.send_report("2026-08-23", send_email=False,
                              runner=lambda a: (seen.append(a), (0, "ok"))[1])
    _wait_idle()
    assert seen == [["2026-08-23", "--no-email"]]


@pytest.mark.parametrize("bad", ["2026-8-23", "23/08/2026", "today", "2026-08-23; rm -rf /"])
def test_bad_date_is_rejected_before_anything_runs(bad):
    called = []
    with pytest.raises(ValueError):
        report_runner.send_report(bad, runner=lambda a: (called.append(a), (0, ""))[1])
    assert called == []
    assert report_runner.get_status()["running"] is False


def test_second_click_does_not_start_a_second_run():
    """The whole point of the feature's guard: two clicks, one email."""
    release = threading.Event()
    starts: list[list[str]] = []

    def slow(argv):
        starts.append(argv)
        release.wait(5)
        return 0, "sent"

    first = report_runner.send_report(runner=slow)
    assert first["already_running"] is False

    second = report_runner.send_report(runner=slow)
    assert second["already_running"] is True

    release.set()
    _wait_idle()
    assert len(starts) == 1


def test_nonzero_exit_reports_failure_with_the_tail():
    report_runner.send_report(runner=lambda a: (2, "SMTPAuthenticationError"))
    st = _wait_idle()
    assert st["ok"] is False
    assert st["returncode"] == 2
    assert "SMTPAuthenticationError" in st["tail"]


def test_runner_exception_is_reported_not_raised():
    """A timeout must land in the status, not kill the daemon thread silently."""
    def boom(argv):
        raise TimeoutError("timed out after 900s")

    report_runner.send_report(runner=boom)
    st = _wait_idle()
    assert st["ok"] is False
    assert st["returncode"] == -1
    assert "timed out" in st["tail"]


def test_tail_is_truncated():
    report_runner.send_report(runner=lambda a: (0, "x" * 10_000))
    st = _wait_idle()
    assert len(st["tail"]) == report_runner._TAIL_CHARS


def test_elapsed_only_while_running():
    release = threading.Event()
    report_runner.send_report(runner=lambda a: (release.wait(5), (0, ""))[1])
    assert "elapsed_sec" in report_runner.get_status()
    release.set()
    st = _wait_idle()
    assert "elapsed_sec" not in st
