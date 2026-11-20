"""Replaced BypassSessions release their clients (curl_cffi sessions etc.)."""
import asyncio
import http.server
import threading

import pytest

import boorus
import cloudflare_bypasser
from cloudflare_bypasser import get_session, store
from cloudflare_bypasser.session import BypassSession

BOORU = "closetest"


class _Sync:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


class _Async:
    def __init__(self):
        self.closed = 0

    async def close(self):
        self.closed += 1


class _Slow(http.server.BaseHTTPRequestHandler):
    started = threading.Event()
    release = threading.Event()

    def do_GET(self):
        type(self).started.set()
        type(self).release.wait(10)
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def booru(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Slow.started.clear()
    _Slow.release.clear()
    base = f"http://127.0.0.1:{srv.server_port}"
    from core import settings
    m = settings.manager
    monkeypatch.setitem(boorus.REGISTRY, BOORU, {"url": base, "api_type": "danbooru"})
    monkeypatch.setattr(m, "cf_bypass_method", "urllib", raising=False)
    monkeypatch.setattr(m, "use_rate_limit", False, raising=False)
    monkeypatch.setattr(m, "proxy_url", "", raising=False)
    m.bypass_data.pop(BOORU, None)
    cloudflare_bypasser._session_cache.pop(BOORU, None)
    yield base
    _Slow.release.set()
    m.bypass_data.pop(BOORU, None)
    cloudflare_bypasser._session_cache.pop(BOORU, None)
    srv.shutdown()
    srv.server_close()


def test_replaced_idle_session_is_closed(booru):
    old = get_session(BOORU)
    cffi = _Sync()
    old._cffi_sync_sessions["chrome"] = cffi
    store.save_bypass(BOORU, {"cf_clearance": "NEW"}, "UA/new")   # fingerprint changes
    assert get_session(BOORU) is not old
    assert cffi.closed == 1 and not old._cffi_sync_sessions


def test_replaced_busy_session_is_closed_after_its_request(booru):
    old = get_session(BOORU)
    cffi = _Sync()
    old._cffi_sync_sessions["chrome"] = cffi
    out = []
    t = threading.Thread(target=lambda: out.append(old.get_sync(booru + "/slow")))
    t.start()
    assert _Slow.started.wait(5)
    store.save_bypass(BOORU, {"cf_clearance": "NEW"}, "UA/new")
    assert get_session(BOORU) is not old
    assert cffi.closed == 0                    # still in use: not closed under it
    _Slow.release.set()
    t.join(10)
    assert out and out[0].status_code == 200
    assert cffi.closed == 1


def test_invalidate_and_solved_release_the_dropped_session(booru):
    for drop in (cloudflare_bypasser.invalidate_session, cloudflare_bypasser.bypass_solved):
        s = get_session(BOORU)
        cffi = _Sync()
        s._cffi_sync_sessions["chrome"] = cffi
        drop(BOORU)
        assert cffi.closed == 1


def test_close_releases_sync_and_async_curl_sessions():
    s = BypassSession()
    sync, a = _Sync(), _Async()
    s._cffi_sync_sessions["chrome"] = sync
    s._cffi_sessions["chrome"] = a
    asyncio.run(s.close())
    assert sync.closed == 1 and a.closed == 1
    assert not s._cffi_sync_sessions and not s._cffi_sessions


def test_retire_closes_async_clients_on_their_loop():
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    try:
        s = BypassSession()
        a = _Async()
        s._loop_ref = loop
        s._cffi_sessions["chrome"] = a
        s.retire()
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0.05), loop).result(5)
        assert a.closed == 1
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(5)
        loop.close()
