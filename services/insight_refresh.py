"""Background runner for POST /api/insight/refresh.

The refresh pipeline (publish signals → rebuild HOSE picks-universe via
KBS → run the Claude trader agent → reassemble the /daily payload) routinely
exceeds the frontend's 5-minute axios timeout. Running it synchronously inside
the request handler means the UI sees a hard `timeout of 300000ms exceeded`
and the user has no way to recover other than retrying (and triggering the
same problem).

This module turns the pipeline into a background job:

  * POST /api/insight/refresh  → kicks a thread, returns immediately with a
    `run_id` + current stage. Second click while running returns the *same*
    run_id (no duplicate work, no wasted KBS calls).
  * GET  /api/insight/refresh/status  → progress snapshot + final payload
    once the run has completed.

Stages match the sync pipeline 1:1, so the UI can render a stage label:

  queued → publishing_signals → rebuilding_universe → trader_agent → assembling → done
                                                                            ↘ error

Thread-safety: all mutations go through `_lock`. Only one run may be in flight
at a time — the second caller just reads the running run's state.

This file deliberately has no dependency on FastAPI; the router imports the
public helpers directly so the runner is unit-testable in isolation.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


# ---------- Stage constants ------------------------------------------------

STAGE_QUEUED          = "queued"
STAGE_PUBLISH         = "publishing_signals"
STAGE_UNIVERSE        = "rebuilding_universe"
STAGE_AGENT           = "trader_agent"
STAGE_ASSEMBLE        = "assembling"
STAGE_DONE            = "done"
STAGE_ERROR           = "error"

_ALL_STAGES = (
    STAGE_QUEUED, STAGE_PUBLISH, STAGE_UNIVERSE,
    STAGE_AGENT, STAGE_ASSEMBLE, STAGE_DONE,
)


# ---------- Run state ------------------------------------------------------

@dataclass
class RefreshRun:
    run_id: str
    started_at: float
    stage: str = STAGE_QUEUED
    stage_started_at: float = 0.0
    progress_done: int = 0
    progress_total: int = 0
    progress_label: str = ""
    # Partial results threaded through the pipeline
    published_signals: int | None = None
    publish_error: str | None = None
    agent_error: str | None = None
    # Final API payload (matches the old sync /refresh response). Populated
    # only on STAGE_DONE.
    payload: dict[str, Any] | None = None
    error: str | None = None
    finished_at: float | None = None
    # Cumulative log of stage transitions — useful for diagnosing slow runs.
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_status_dict(self) -> dict[str, Any]:
        now = time.time()
        return {
            "run_id": self.run_id,
            "stage": self.stage,
            "stage_label": self.progress_label,
            "progress": {
                "done": self.progress_done,
                "total": self.progress_total,
                "pct": (
                    round(100.0 * self.progress_done / self.progress_total, 1)
                    if self.progress_total > 0 else None
                ),
            },
            "started_at": self.started_at,
            "elapsed_sec": round((self.finished_at or now) - self.started_at, 2),
            "published_signals": self.published_signals,
            "publish_error": self.publish_error,
            "agent_error": self.agent_error,
            "error": self.error,
            "is_running": self.stage not in (STAGE_DONE, STAGE_ERROR),
            "is_done": self.stage == STAGE_DONE,
            "is_error": self.stage == STAGE_ERROR,
            # Only surface the full payload once the run has finished — keeps
            # the polling response light while the job is still running.
            "payload": self.payload if self.stage == STAGE_DONE else None,
            "history": list(self.history),
        }


# ---------- Runner singleton ----------------------------------------------

class InsightRefreshRunner:
    """Manages at most one in-flight refresh at a time.

    Call `start()` to kick off a new run (or get the id of the currently
    running one). Call `status(run_id=None)` to read state — if no id is
    given, returns the most recent run. Once a run finishes it stays in
    memory until the next `start()` replaces it, so the UI can still fetch
    the completed payload after the polling loop ends.
    """

    def __init__(self, pipeline: "Callable[[RefreshRun], dict[str, Any]] | None" = None) -> None:
        self._lock = threading.Lock()
        self._current: RefreshRun | None = None
        self._thread: threading.Thread | None = None
        # Pipeline callable is injected for tests. Default is the real one
        # wired to PicksUniverseService + TraderAgent + insight_daily().
        self._pipeline = pipeline or _default_pipeline

    def start(self) -> RefreshRun:
        with self._lock:
            cur = self._current
            if cur is not None and cur.stage not in (STAGE_DONE, STAGE_ERROR):
                # Idempotent: return the running run so the UI can keep polling.
                log.info("[insight-refresh] start: already running run_id=%s stage=%s",
                         cur.run_id, cur.stage)
                return cur

            run = RefreshRun(
                run_id=uuid.uuid4().hex[:12],
                started_at=time.time(),
                stage=STAGE_QUEUED,
                stage_started_at=time.time(),
                progress_label="Đang khởi tạo…",
            )
            self._current = run

        t = threading.Thread(
            target=self._worker, args=(run,), name=f"insight-refresh-{run.run_id}",
            daemon=True,
        )
        self._thread = t
        t.start()
        log.info("[insight-refresh] started run_id=%s", run.run_id)
        return run

    def status(self, run_id: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            cur = self._current
        if cur is None:
            return None
        if run_id is not None and cur.run_id != run_id:
            # Caller is asking about an old run we no longer have — surface a
            # not-found marker instead of the current run, which would confuse
            # the UI into thinking its earlier run is still progressing.
            return {"run_id": run_id, "stage": "unknown", "is_running": False,
                    "is_done": False, "is_error": False,
                    "error": "run_id not found (superseded by newer refresh)"}
        return cur.to_status_dict()

    # ---------- worker ----------

    def _worker(self, run: RefreshRun) -> None:
        try:
            payload = self._pipeline(run)
            with self._lock:
                run.payload = payload
                _advance(run, STAGE_DONE, "Hoàn tất")
                run.finished_at = time.time()
            log.info("[insight-refresh] done run_id=%s dur=%.1fs",
                     run.run_id, run.finished_at - run.started_at)
        except BaseException as e:
            log.exception("[insight-refresh] run_id=%s failed: %s", run.run_id, e)
            with self._lock:
                run.error = f"{type(e).__name__}: {e}"
                _advance(run, STAGE_ERROR, f"Lỗi: {run.error}")
                run.finished_at = time.time()


# ---------- Shared state transition helper (module-private) ---------------

def _advance(run: RefreshRun, stage: str, label: str,
             done: int = 0, total: int = 0) -> None:
    """Record a stage transition. Caller must hold the runner lock."""
    now = time.time()
    run.history.append({
        "stage": run.stage,
        "exited_at": now,
        "duration_sec": round(now - run.stage_started_at, 2),
    })
    run.stage = stage
    run.stage_started_at = now
    run.progress_label = label
    run.progress_done = done
    run.progress_total = total


def set_progress(run: RefreshRun, stage: str, label: str,
                 done: int = 0, total: int = 0) -> None:
    """Public progress setter used by the pipeline. Thread-safe."""
    with _runner_global()._lock:
        _advance(run, stage, label, done, total)


def update_progress_counts(run: RefreshRun, done: int, total: int,
                           label: str | None = None) -> None:
    """Update just the progress counts within the current stage (no stage
    transition). Used by the universe builder's per-ticker callback."""
    with _runner_global()._lock:
        run.progress_done = done
        run.progress_total = total
        if label is not None:
            run.progress_label = label


# ---------- Default pipeline ----------------------------------------------

def _default_pipeline(run: RefreshRun) -> dict[str, Any]:
    """Run the real refresh pipeline and return the /daily payload shape.

    Imports are lazy so unit tests can inject a fake pipeline without pulling
    in the SQLAlchemy engine and vnstock.
    """
    from database.connection import SessionLocal
    from database.models import SectorFlowDaily, SectorRegime, SectorSignal
    from services.picks_universe_service import get_picks_universe
    from services.sector_signal_service import SectorSignalService
    from services.trader_agent import get_trader_agent

    # --- Stage 1: publish signals ---
    set_progress(run, STAGE_PUBLISH, "Đang xuất tín hiệu xếp hạng…")
    published = 0
    publish_error: str | None = None
    sess = SessionLocal()
    try:
        try:
            df = SectorSignalService(sess).publish()
            published = int(len(df))
        except BaseException as e:
            publish_error = f"{type(e).__name__}: {e}"
            log.warning("[insight-refresh] publish failed: %s", publish_error)
    finally:
        sess.close()
    run.published_signals = published
    run.publish_error = publish_error

    # --- Stage 2: rebuild universe (slow — this is the bulk of the run) ---
    set_progress(run, STAGE_UNIVERSE, "Đang dựng universe HOSE…")
    service = get_picks_universe()
    service.invalidate()

    def _universe_progress(done: int, total: int, note: str = "") -> None:
        label = f"Đang dựng universe HOSE ({done}/{total})"
        if note:
            label += f" · {note}"
        update_progress_counts(run, done, total, label=label)

    snapshot = service.get_snapshot(force=True, on_progress=_universe_progress)

    # --- Stage 3: trader agent ---
    set_progress(run, STAGE_AGENT,
                 "Minh đang phân tích thị trường…", done=0, total=1)
    agent_error: str | None = None
    try:
        snap_dict = {
            "as_of": snapshot.as_of.isoformat() if hasattr(snapshot.as_of, "isoformat") else str(snapshot.as_of),
            "top_buys": [p.to_dict() for p in snapshot.top_buys],
            "top_sells": [p.to_dict() for p in snapshot.top_sells],
            "freshness": {**snapshot.freshness.to_dict(), "is_valid": snapshot.is_valid},
        }
        sess = SessionLocal()
        try:
            regime_row = (
                sess.query(SectorRegime).order_by(SectorRegime.date.desc()).first()
            )
            as_of_str = snap_dict["as_of"]
            signals = (
                sess.query(SectorSignal)
                .filter(SectorSignal.date == as_of_str)
                .order_by(SectorSignal.rank.asc())
                .all()
            )
            flow_rows = (
                sess.query(SectorFlowDaily)
                .filter(SectorFlowDaily.date == as_of_str)
                .all()
            )
        finally:
            sess.close()
        ctx = {
            "as_of": snap_dict["as_of"],
            "regime": ({
                "label": regime_row.regime_label,
                "confidence": float(regime_row.confidence or 0),
                "date": regime_row.date,
            } if regime_row else None),
            "sector_signals": [
                {"sector_code": s.sector_code, "action": s.action,
                 "score": float(s.score or 0), "rank": s.rank}
                for s in signals
            ],
            "flow_daily": {
                r.sector_code: {
                    "flow_z20": float(r.flow_z20) if r.flow_z20 is not None else None,
                    "foreign_hit_20d": float(r.foreign_hit_20d) if r.foreign_hit_20d is not None else None,
                    "rs_vnindex_20d": float(r.rs_vnindex_20d) if r.rs_vnindex_20d is not None else None,
                    "accumulation_age": int(r.accumulation_age or 0),
                }
                for r in flow_rows
            },
        }
        get_trader_agent().invalidate()
        report = get_trader_agent().analyze_sync(snap_dict, ctx)
        log.info("[insight-refresh] trader_agent done is_valid=%s gist=%r",
                 report.is_valid, report.gist[:80])
        update_progress_counts(run, done=1, total=1,
                               label="Minh đã có nhận định")
    except BaseException as e:
        agent_error = f"{type(e).__name__}: {e}"
        log.exception("[insight-refresh] trader_agent failed: %s", agent_error)
    run.agent_error = agent_error

    # --- Stage 4: assemble /daily payload ---
    set_progress(run, STAGE_ASSEMBLE, "Đang tổng hợp kết quả…")
    from api.routers.insight import insight_daily
    data = insight_daily()
    payload = {
        **data,
        "refresh": {
            "published_signals": run.published_signals,
            "publish_error": run.publish_error,
            "price_cache_cleared": True,
            "agent_error": run.agent_error,
            "run_id": run.run_id,
        },
    }
    return payload


# ---------- Module-level accessor -----------------------------------------

_RUNNER: InsightRefreshRunner | None = None
_RUNNER_LOCK = threading.Lock()


def _runner_global() -> InsightRefreshRunner:
    global _RUNNER
    if _RUNNER is None:
        with _RUNNER_LOCK:
            if _RUNNER is None:
                _RUNNER = InsightRefreshRunner()
    return _RUNNER


def get_refresh_runner() -> InsightRefreshRunner:
    """Public accessor used by the router."""
    return _runner_global()


def reset_refresh_runner_for_tests(
    pipeline: "Callable[[RefreshRun], dict[str, Any]] | None" = None,
) -> InsightRefreshRunner:
    """Swap the module singleton with a fresh runner (optionally with an
    injected pipeline). Tests use this to avoid state bleed."""
    global _RUNNER
    with _RUNNER_LOCK:
        _RUNNER = InsightRefreshRunner(pipeline=pipeline)
    return _RUNNER


__all__ = [
    "InsightRefreshRunner",
    "RefreshRun",
    "STAGE_QUEUED",
    "STAGE_PUBLISH",
    "STAGE_UNIVERSE",
    "STAGE_AGENT",
    "STAGE_ASSEMBLE",
    "STAGE_DONE",
    "STAGE_ERROR",
    "get_refresh_runner",
    "reset_refresh_runner_for_tests",
    "set_progress",
    "update_progress_counts",
]
