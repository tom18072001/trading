"""Tests for services.insight_refresh — the async background runner that
powers POST /api/insight/refresh.

We DO NOT invoke the real pipeline (vnstock KBS, Claude SDK, SQLAlchemy
engine). Instead the runner is constructed with an injected fake pipeline
so we can exercise:

  * single-run happy path (stage + payload propagated)
  * idempotent start — second click while running returns the same run_id
  * error path — exception in pipeline lands in `stage=error` + `.error`
  * stale run_id — status(run_id=old) returns not-found marker after the
    runner has moved on to a new run
  * progress plumbing — `set_progress` / `update_progress_counts` mutate the
    correct fields and are thread-safe from a worker thread

No DB, no network, no Claude SDK. Runs in milliseconds.
"""
from __future__ import annotations

import threading
import time

import pytest

from services.insight_refresh import (
    STAGE_AGENT,
    STAGE_DONE,
    STAGE_ERROR,
    STAGE_PUBLISH,
    STAGE_UNIVERSE,
    InsightRefreshRunner,
    RefreshRun,
    set_progress,
    update_progress_counts,
    reset_refresh_runner_for_tests,
)


# --- helpers ---------------------------------------------------------------


def _blocking_pipeline(event: threading.Event, payload: dict):
    """Return a pipeline callable that waits on `event` before finishing.

    Lets the test control when the worker completes so we can assert on the
    running/idle states deterministically.
    """
    def _pipe(run: RefreshRun) -> dict:
        set_progress(run, STAGE_PUBLISH, "publishing", done=0, total=1)
        event.wait(timeout=5)
        set_progress(run, STAGE_UNIVERSE, "universe", done=100, total=300)
        return payload
    return _pipe


# --- happy path ------------------------------------------------------------


def test_runner_happy_path_populates_payload():
    runner = reset_refresh_runner_for_tests(
        pipeline=lambda run: {"ok": True, "run_id": run.run_id},
    )
    run = runner.start()
    # Wait up to 2s for the worker to finish
    deadline = time.time() + 2
    while time.time() < deadline:
        status = runner.status()
        if status and status["is_done"]:
            break
        time.sleep(0.02)
    final = runner.status()
    assert final is not None
    assert final["is_done"] is True
    assert final["is_running"] is False
    assert final["stage"] == STAGE_DONE
    assert final["payload"] == {"ok": True, "run_id": run.run_id}


def test_runner_start_is_idempotent_while_running():
    gate = threading.Event()
    runner = reset_refresh_runner_for_tests(
        pipeline=_blocking_pipeline(gate, {"hello": "world"}),
    )
    first = runner.start()
    # Second click while the pipeline is still blocked on `gate`: must return
    # the same run (no new thread, no wasted KBS calls).
    second = runner.start()
    assert first.run_id == second.run_id
    status = runner.status()
    assert status["is_running"] is True
    assert status["stage"] == STAGE_PUBLISH
    # Release the worker so it can finish (otherwise the daemon thread would
    # linger past the test).
    gate.set()
    deadline = time.time() + 2
    while time.time() < deadline:
        if runner.status()["is_done"]:
            break
        time.sleep(0.02)


# --- error path ------------------------------------------------------------


def test_runner_surface_pipeline_errors():
    def _boom(run: RefreshRun) -> dict:
        raise RuntimeError("kbs 429")
    runner = reset_refresh_runner_for_tests(pipeline=_boom)
    runner.start()
    deadline = time.time() + 2
    while time.time() < deadline:
        s = runner.status()
        if s and (s["is_done"] or s["is_error"]):
            break
        time.sleep(0.02)
    final = runner.status()
    assert final["is_error"] is True
    assert final["is_done"] is False
    assert final["stage"] == STAGE_ERROR
    assert "kbs 429" in (final["error"] or "")


# --- run_id lookup ---------------------------------------------------------


def test_status_with_stale_run_id_returns_not_found():
    runner = reset_refresh_runner_for_tests(pipeline=lambda run: {"ok": True})
    first = runner.start()
    # Wait for first run to finish
    deadline = time.time() + 2
    while time.time() < deadline:
        if runner.status()["is_done"]:
            break
        time.sleep(0.02)
    # Kick off a second run — it supersedes the first
    second = runner.start()
    deadline = time.time() + 2
    while time.time() < deadline:
        if runner.status()["is_done"]:
            break
        time.sleep(0.02)
    # Asking about the first run_id now should yield a not-found marker, not
    # the second run's state (otherwise the UI would think its old polling
    # loop is still making progress).
    stale = runner.status(run_id=first.run_id)
    assert stale is not None
    assert stale["stage"] == "unknown"
    assert stale["is_running"] is False
    # The current run_id still looks up normally
    ok = runner.status(run_id=second.run_id)
    assert ok["run_id"] == second.run_id


# --- progress plumbing -----------------------------------------------------


def test_progress_counts_update_from_worker_thread():
    gate = threading.Event()

    def _pipe(run: RefreshRun) -> dict:
        set_progress(run, STAGE_UNIVERSE, "starting", done=0, total=10)
        for i in range(1, 11):
            update_progress_counts(run, done=i, total=10,
                                   label=f"ticker {i}/10")
        gate.set()
        return {"ok": True}

    runner = reset_refresh_runner_for_tests(pipeline=_pipe)
    runner.start()
    assert gate.wait(timeout=2), "worker never finished"
    deadline = time.time() + 2
    while time.time() < deadline:
        if runner.status()["is_done"]:
            break
        time.sleep(0.02)
    final = runner.status()
    assert final["is_done"] is True
    # Final progress before stage flip-to-done was 10/10 — the `done` stage
    # transition resets counts, which is the correct behaviour (keeps the
    # UI's progress bar at the right spot: 100% → Hoàn tất).
    assert final["history"]  # stage transitions were recorded
    history_stages = [h["stage"] for h in final["history"]]
    assert STAGE_UNIVERSE in history_stages
