"""_run_on_shared_loop must never re-run a coroutine the loop already awaited."""
import asyncio
import threading
import time

import pytest

import async_loop
from cloudflare_bypasser.session import BypassSession


@pytest.fixture
def shared_loop(monkeypatch):
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    monkeypatch.setattr(async_loop, "_LOOP", loop)
    monkeypatch.setattr(async_loop, "_SHUTTING_DOWN", False)
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    t.join(5)
    loop.close()


def test_runtime_error_in_coroutine_returns_none_and_runs_once(shared_loop):
    calls = []

    async def boom():
        calls.append(1)
        raise RuntimeError("attached to a different loop")

    assert BypassSession._run_on_shared_loop(boom(), 1) is None
    assert calls == [1]


def test_success_returns_value(shared_loop):
    async def ok():
        return 42

    assert BypassSession._run_on_shared_loop(ok(), 1) == 42


def test_timeout_cancels_the_coroutine(shared_loop):
    state = {}

    async def slow():
        state["started"] = True
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    # The wait is timeout + 10 s, so -9.9 gives a 0.1 s wait.
    assert BypassSession._run_on_shared_loop(slow(), -9.9) is None
    deadline = time.time() + 3
    while "cancelled" not in state and time.time() < deadline:
        time.sleep(0.01)
    assert state.get("started") and state.get("cancelled")


def test_no_loop_falls_back_to_local_run(monkeypatch):
    monkeypatch.setattr(async_loop, "_LOOP", None)
    monkeypatch.setattr(async_loop, "_SHUTTING_DOWN", False)

    async def ok():
        return "local"

    assert BypassSession._run_on_shared_loop(ok(), 1) == "local"


def test_shutting_down_does_not_spawn_throwaway_loop(shared_loop, monkeypatch):
    monkeypatch.setattr(async_loop, "_SHUTTING_DOWN", True)
    ran = []

    async def work():
        ran.append(1)

    assert BypassSession._run_on_shared_loop(work(), 1) is None
    assert ran == []
