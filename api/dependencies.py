# ============================================
# api/dependencies.py
# FastAPI dependencies (DB session, background tasks)
# ============================================

import threading
import uuid
from typing import Generator

from sqlalchemy.orm import Session
from database.connection import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a DB session per request."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ==========================================
# BACKGROUND TASK MANAGER
# ==========================================
# Dùng cho long-running tasks (ML training, bulk data fetch)

_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()
_MAX_COMPLETED_TASKS = 100  # Prevent memory leak from accumulating completed tasks


def _cleanup_old_tasks():
    """Remove oldest completed/failed tasks if over limit."""
    completed = [
        (tid, t) for tid, t in _tasks.items()
        if t["status"] in ("completed", "failed")
    ]
    if len(completed) > _MAX_COMPLETED_TASKS:
        # Sort by completion order (oldest first) and remove excess
        for tid, _ in completed[:len(completed) - _MAX_COMPLETED_TASKS]:
            _tasks.pop(tid, None)


def create_background_task(target, args=(), kwargs=None) -> str:
    """
    Start a function in a background thread and track its status.

    Returns:
        str: task_id
    """
    task_id = str(uuid.uuid4())[:8]
    with _tasks_lock:
        _tasks[task_id] = {"status": "running", "message": "", "result": None}
        _cleanup_old_tasks()

    def wrapper():
        try:
            result = target(*args, **(kwargs or {}))
            with _tasks_lock:
                _tasks[task_id] = {"status": "completed", "message": "Done", "result": result}
        except Exception as e:
            with _tasks_lock:
                _tasks[task_id] = {"status": "failed", "message": str(e), "result": None}

    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()
    return task_id


def get_task_status(task_id: str) -> dict:
    """Get status of a background task."""
    with _tasks_lock:
        return _tasks.get(task_id, {"status": "not_found", "message": "Task not found"}).copy()
