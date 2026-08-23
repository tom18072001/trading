# ============================================
# utils/vnstock_gate.py
# ============================================
# One choke point for every outbound vnstock/KBS call.
#
# Why this exists (post-mortem 2026-08-22):
#   sector_ingest_service paced itself with a bare `time.sleep(3.2)` after
#   each SYMBOL, but each symbol costs TWO api calls (quote.history +
#   trading.price_board). That is ~37 calls/min against a KBS guest tier
#   that allows ~20/min, so every intraday run walked straight into
#   "Rate limit exceeded". Worse, vnstock raises SystemExit on a 429, the
#   caller swallowed it and moved on, so a rate-limited run burned through
#   all 75 symbols at full speed and wrote 0 rows.
#
# Two mechanisms live here:
#   1. throttle()  - process-wide token bucket, counts CALLS not symbols.
#   2. job_lock()  - cross-process mutex, so two scheduled jobs can never
#                    spend the same per-minute budget at the same time.
#
# picks_universe_service.py still carries its own private copy of a
# token bucket (_kbs_throttle). It works and is left alone deliberately;
# new code should use this module instead.

from __future__ import annotations

import collections
import os
import threading
import time
from contextlib import contextmanager
from typing import Callable, TypeVar

T = TypeVar("T")

# KBS guest tier is ~20 req/min. Default to 18 for headroom.
MAX_PER_MIN = int(os.environ.get("VNSTOCK_MAX_PER_MIN", "18"))
WINDOW_SEC = 60.0

# Backoff schedule after a 429, in seconds.
BACKOFF = (30.0, 75.0, 150.0)

_CALLS: collections.deque[float] = collections.deque()
_LOCK = threading.Lock()


def _log(msg: str) -> None:
    print(f"[vnstock-gate] {msg}", flush=True)


def throttle() -> None:
    """Block until fewer than MAX_PER_MIN calls sit in the last 60 seconds."""
    while True:
        with _LOCK:
            now = time.monotonic()
            while _CALLS and (now - _CALLS[0]) > WINDOW_SEC:
                _CALLS.popleft()
            if len(_CALLS) < MAX_PER_MIN:
                _CALLS.append(now)
                return
            sleep_for = WINDOW_SEC - (now - _CALLS[0]) + 0.2
        # sleep outside the lock so other threads are not stacked behind it
        time.sleep(max(sleep_for, 0.1))


def _is_rate_limit(exc: BaseException) -> bool:
    if isinstance(exc, SystemExit):
        return True
    text = str(exc).lower()
    return "rate limit" in text or "429" in text or "too many request" in text


def call(fn: Callable[..., T], *args, what: str = "call", **kwargs) -> T | None:
    """Throttled call with backoff-retry on rate limiting.

    Returns None when the call could not be completed. Never raises for
    an API-side failure - scheduled jobs should degrade, not crash.
    """
    for attempt, wait in enumerate((*BACKOFF, None)):
        throttle()
        try:
            return fn(*args, **kwargs)
        except BaseException as exc:  # vnstock raises SystemExit on 429
            if not _is_rate_limit(exc):
                _log(f"{what} failed: {type(exc).__name__}: {exc}")
                return None
            if wait is None:
                _log(f"{what} still rate-limited after {attempt} retries, giving up")
                return None
            _log(f"{what} rate-limited, backing off {wait:.0f}s "
                 f"(retry {attempt + 1}/{len(BACKOFF)})")
            time.sleep(wait)
    return None


# ---------------------------------------------------------------------------
# Cross-process mutex
# ---------------------------------------------------------------------------
# The token bucket above is per-process. Scheduled jobs are separate
# processes (intraday every 15m, risk-sentinel every 30m, macro hourly),
# and a slow intraday run can still be going when the next one fires.
# Without a mutex they each think they own the full 18 calls/min.
#
# Uses an OS-level file lock, which Windows releases automatically when the
# holding process dies - so a crashed job can never leave a stale lock.

def _try_lock(fh) -> bool:
    fh.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fh) -> None:
    fh.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def job_lock(name: str = "vnstock", wait_sec: float | None = None):
    """Serialise vnstock-spending jobs across processes.

    Yields True when the lock was taken, False when the wait ran out.
    A job that gets False should log and exit cleanly - the next scheduled
    firing will pick the work up.
    """
    if wait_sec is None:
        wait_sec = float(os.environ.get("VNSTOCK_LOCK_WAIT", "420"))

    import tempfile
    path = os.path.join(tempfile.gettempdir(), f"sectorflow-{name}.lock")
    fh = open(path, "a+")
    deadline = time.monotonic() + wait_sec
    acquired = False
    waited = False
    try:
        while True:
            if _try_lock(fh):
                acquired = True
                break
            if time.monotonic() >= deadline:
                break
            if not waited:
                _log(f"another job holds '{name}', waiting up to {wait_sec:.0f}s")
                waited = True
            time.sleep(3.0)
        if acquired and waited:
            _log(f"acquired '{name}'")
        yield acquired
    finally:
        if acquired:
            _unlock(fh)
        fh.close()


@contextmanager
def guarded(job_name: str):
    """job_lock + a uniform skip message. Wraps one scheduled command."""
    with job_lock() as got:
        if not got:
            _log(f"skipping {job_name}: vnstock busy, will retry next run")
            yield False
        else:
            yield True
