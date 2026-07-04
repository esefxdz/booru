"""
async_loop.py — Single global asyncio event loop for all background work.

Why this exists
---------------
Before this module, every FetchThread, BulkThread, and LoginThread created
its own ``asyncio.new_event_loop()``, ran work on it, then closed it.
At shutdown, ``main.py`` called ``asyncio.run(thumb_client.close_all())``
which created yet another loop.  Because ``httpx.AsyncClient`` captures the
event loop it was created on, clients became orphaned when their owning
thread's loop closed, causing occasional ``RuntimeError: attached to a
different loop`` on Windows / Python 3.13.

This module provides one persistent event loop running on a daemon thread
for the entire application lifetime.  All async work is submitted via
``asyncio.run_coroutine_threadsafe()`` and callers block on the returned
``concurrent.futures.Future``.

Usage
-----
    # In main.py, early:
    from async_loop import start, stop, run

    start()

    # Anywhere a QThread previously created its own loop:
    posts = run(downloader.get_image_urls(tags, limit, page))

    # At shutdown:
    run(thumb_client.close_all())
    stop()

Public API
----------
    start()   – create and start the global loop (call once in main.py)
    stop()    – stop and close the global loop (call once at shutdown)
    submit(coro) → concurrent.futures.Future
    run(coro) → T  – submit + block on result (replaces loop.run_until_complete)
"""

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
    """Create the global event loop and start it on a daemon thread.

    Idempotent — subsequent calls are no-ops.
    Must be called from the main thread before any async work is submitted.
    """
    global _LOOP, _THREAD, _STARTED

    with _LOCK:
        if _STARTED:
            return
        _STARTED = True

    _LOOP = asyncio.new_event_loop()
    _THREAD = threading.Thread(target=_LOOP.run_forever, name="async-loop", daemon=True)
    _THREAD.start()
    log.debug("Global async event loop started on thread %s", _THREAD.name)

    # Best-effort cleanup if the process exits without calling stop()
    atexit.register(_atexit_cleanup)


def stop(timeout: float = 5.0) -> None:
    """Stop the global event loop and join the daemon thread.

    Submits any remaining callbacks, cancels pending tasks, then closes
    the loop.  Safe to call multiple times.
    """
    global _LOOP, _THREAD, _STARTED, _SHUTTING_DOWN

    with _LOCK:
        if not _STARTED or _SHUTTING_DOWN:
            return
        _SHUTTING_DOWN = True

    loop = _LOOP
    thread = _THREAD

    if loop is None or thread is None:
        return

    # Collect all pending tasks (excluding the run_forever sentinel)
    try:
        pending = asyncio.all_tasks(loop)
    except RuntimeError:
        pending = set()

    if pending:
        log.debug("Cancelling %d pending async tasks…", len(pending))
        for task in pending:
            task.cancel()

    # Schedule the loop stop + a callback to wake the loop in case
    # run_forever is idle.
    loop.call_soon_threadsafe(_stop_and_close, loop)
    # The loop daemon thread will exit once run_forever returns.

    thread.join(timeout=timeout)
    if thread.is_alive():
        log.warning("Async loop thread did not stop within %.1fs", timeout)

    log.debug("Global async event loop stopped")


def _stop_and_close(loop: asyncio.AbstractEventLoop) -> None:
    """Callback scheduled on the loop to stop run_forever and close."""
    loop.stop()
    # Give stop() a moment to propagate, then close resources
    # (run_forever will return, and the daemon thread exits)


def submit(coro) -> concurrent.futures.Future:
    """Submit a coroutine to the global loop from any thread.

    Returns a ``concurrent.futures.Future`` that resolves when the
    coroutine completes.  The calling thread can block on
    ``future.result()`` to get the return value or exception.
    """
    if _LOOP is None or _SHUTTING_DOWN:
        raise RuntimeError("async_loop: global loop not running — call start() first")

    return asyncio.run_coroutine_threadsafe(coro, _LOOP)


def run(coro) -> _T:
    """Submit a coroutine and block until it completes, returning its result.

    This is the direct replacement for ``loop.run_until_complete(coro)``
    when used from a worker thread (QThread).

    Exceptions propagate to the caller.
    """
    future = submit(coro)
    return future.result()


def _atexit_cleanup() -> None:
    """Last-resort cleanup if the process exits without calling stop()."""
    global _SHUTTING_DOWN
    with _LOCK:
        if _SHUTTING_DOWN:
            return
        _SHUTTING_DOWN = True

    loop = _LOOP
    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(loop.stop)
