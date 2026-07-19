"""Endpoint-level smoke tests for the async /api/insight/refresh contract.

These tests inject a fake pipeline via `reset_refresh_runner_for_tests` so
the handler never hits KBS / Claude / the DB.

Goals:
  * POST /api/insight/refresh returns 200 with a run_id immediately.
  * GET  /api/insight/refresh/status?run_id=... reports is_running, then
    flips to is_done with the payload attached.
  * Second POST while the first is running returns the same run_id and
    `already_running=True`.
"""
from __future__ import annotations

import threading
import time

import pytest

from fastapi.testclient import TestClient

from api.main import app
from services.insight_refresh import (
    RefreshRun,
    reset_refresh_runner_for_tests,
    set_progress,
    STAGE_PUBLISH,
)


@pytest.fixture
def client():
    return TestClient(app)


def _fast_pipeline(run: RefreshRun) -> dict:
    set_progress(run, STAGE_PUBLISH, "mock publish", done=0, total=0)
    return {
        "date": "2026-04-20",
        "narrative": "mock",
        "deltas": [], "actions": [], "picks": [],
        "refresh": {
            "published_signals": 7, "publish_error": None,
            "price_cache_cleared": True, "agent_error": None,
            "run_id": run.run_id,
        },
    }


def test_refresh_returns_run_id_and_status_completes(client):
    reset_refresh_runner_for_tests(pipeline=_fast_pipeline)

    resp = client.post("/api/insight/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body
    assert body["already_running"] is False
    run_id = body["run_id"]

    # Poll until the pipeline finishes
    deadline = time.time() + 3
    final = None
    while time.time() < deadline:
        r = client.get("/api/insight/refresh/status", params={"run_id": run_id})
        assert r.status_code == 200
        final = r.json()
        if final["is_done"] or final["is_error"]:
            break
        time.sleep(0.05)

    assert final is not None
    assert final["is_done"] is True
    assert final["is_error"] is False
    assert final["payload"] is not None
    assert final["payload"]["refresh"]["run_id"] == run_id
    assert final["payload"]["refresh"]["published_signals"] == 7


def test_refresh_second_click_returns_existing_run(client):
    gate = threading.Event()

    def _slow(run: RefreshRun) -> dict:
        set_progress(run, STAGE_PUBLISH, "waiting", done=0, total=1)
        gate.wait(timeout=3)
        return {"refresh": {"run_id": run.run_id}}

    reset_refresh_runner_for_tests(pipeline=_slow)

    first = client.post("/api/insight/refresh").json()
    second = client.post("/api/insight/refresh").json()
    assert first["run_id"] == second["run_id"]
    # The second start observed a run already in flight
    assert second["already_running"] is True
    gate.set()
    # Wait for completion so the daemon thread doesn't linger
    deadline = time.time() + 3
    while time.time() < deadline:
        s = client.get("/api/insight/refresh/status",
                       params={"run_id": first["run_id"]}).json()
        if s["is_done"] or s["is_error"]:
            break
        time.sleep(0.05)


def test_refresh_status_idle_when_never_started(client):
    # Fresh runner, no start — status endpoint must return idle marker.
    reset_refresh_runner_for_tests(pipeline=_fast_pipeline)
    r = client.get("/api/insight/refresh/status")
    assert r.status_code == 200
    body = r.json()
    assert body["stage"] == "idle"
    assert body["is_running"] is False
    assert body["is_done"] is False
    assert body["payload"] is None
