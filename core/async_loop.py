"""One global asyncio event loop on a daemon thread, shared by all background work."""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import logging
import threading
from typing import TypeVar

log = logging.getLogger(__name__)

_T = TypeVar("_T")

_LOOP: asyncio.AbstractEventLoop | None = None
_THREAD: threading.Thread | None = None
_LOCK = threading.Lock()
_STARTED = False
_SHUTTING_DOWN = False


def start() -> None:
    """Start the global loop. Idempotent; call from the main thread first."""
    global _LOOP, _THREAD, _STARTED

    with _LOCK:
        if _STARTED:
            return
        _STARTED = True

    _LOOP = asyncio.new_event_loop()
    _THREAD = threading.Thread(target=_LOOP.run_forever, name="async-loop", daemon=True)
    _THREAD.start()
    log.debug("Global async event loop started on thread %s", _THREAD.name)

    atexit.register(_atexit_cleanup)


def stop(timeout: float = 5.0) -> None:
    """Cancel pending tasks and stop the loop. Safe to call repeatedly."""
    global _LOOP, _THREAD, _STARTED, _SHUTTING_DOWN

    with _LOCK:
        if not _STARTED or _SHUTTING_DOWN:
            return
        _SHUTTING_DOWN = True

    loop = _LOOP
    thread = _THREAD

    if loop is None or thread is None:
        return

    try:
        pending = asyncio.all_tasks(loop)
    except RuntimeError:
        pending = set()

    if pending:
        log.debug("Cancelling %d pending async tasks…", len(pending))
        for task in pending:
            task.cancel()

    loop.call_soon_threadsafe(_stop_and_close, loop)

    thread.join(timeout=timeout)
    if thread.is_alive():
        log.warning("Async loop thread did not stop within %.1fs", timeout)

    log.debug("Global async event loop stopped")


def _stop_and_close(loop: asyncio.AbstractEventLoop) -> None:
    loop.stop()


def submit(coro) -> concurrent.futures.Future:
    """Submit a coroutine to the global loop from any thread; returns a Future."""
    if _LOOP is None or _SHUTTING_DOWN:
        raise RuntimeError("async_loop: global loop not running — call start() first")

    return asyncio.run_coroutine_threadsafe(coro, _LOOP)


def run(coro) -> _T:
    """Submit a coroutine and block for its result (for worker threads)."""
    future = submit(coro)
    return future.result()


def _atexit_cleanup() -> None:
    global _SHUTTING_DOWN
    with _LOCK:
        if _SHUTTING_DOWN:
            return
        _SHUTTING_DOWN = True

    loop = _LOOP
    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(loop.stop)
