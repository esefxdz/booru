"""The Cloudflare circuit breaker, exercised the way the app uses it:
api_client.search_posts -> cloudflare_bypasser.get_session -> BypassSession.

A local HTTP server stands in for the booru; nothing leaves the machine.
"""
import asyncio
import http.server
import threading
from types import SimpleNamespace

import pytest

import boorus
from adapters import get_adapter
from cloudflare_bypasser import bypass_solved, get_session, store
from cloudflare_bypasser import session as sess
from download_images.api_client import search_posts
from download_images.network import CloudflareBlockError

BOORU = "cbtest"


class _Booru(http.server.BaseHTTPRequestHandler):
    blocked = True
    hits = 0

    def do_GET(self):
        type(self).hits += 1
        if type(self).blocked:
            status, body = 403, b"forbidden"          # tiny 403 = CF block
        else:
            status, body = 200, b'[{"id": 1}]'
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def booru(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Booru)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Booru.blocked, _Booru.hits = True, 0
    base = f"http://127.0.0.1:{srv.server_port}"

    from ui import settings_view as settings
    import cloudflare_bypasser
    m = settings.manager
    monkeypatch.setitem(boorus.REGISTRY, BOORU, {"url": base, "api_type": "danbooru"})
    monkeypatch.setattr(m, "active_booru", BOORU, raising=False)
    monkeypatch.setattr(m, "cf_bypass_method", "urllib", raising=False)  # 1 engine = 1 hit
    monkeypatch.setattr(m, "use_rate_limit", False, raising=False)
    monkeypatch.setattr(m, "proxy_url", "", raising=False)
    monkeypatch.setattr(m, "blacklist", "", raising=False)
    monkeypatch.setattr(m, "favorites", "", raising=False)
    monkeypatch.setattr(sess, "_RETRY_BACKOFF_BASE", 0.01)
    m.bypass_data.pop(BOORU, None)
    cloudflare_bypasser._session_cache.pop(BOORU, None)
    yield base
    m.bypass_data.pop(BOORU, None)
    cloudflare_bypasser._session_cache.pop(BOORU, None)
    srv.shutdown()


def _search():
    site = boorus.REGISTRY[BOORU]

    async def fetch(url, params=None):
        return await get_session(BOORU).get(url, params=params)

    return asyncio.run(search_posts(get_adapter("danbooru"), site, fetch, "tag", 10))


def _blocked_search():
    with pytest.raises(CloudflareBlockError):
        _search()


def test_new_search_after_block_sends_no_requests(booru):
    first_session = get_session(BOORU)
    _blocked_search()
    assert _Booru.hits == 1
    # api_client dropped the cached session; the new one must still know.
    assert get_session(BOORU) is not first_session
    for _ in range(5):
        _blocked_search()
    assert _Booru.hits == 1


def test_circuit_open_response_keeps_stored_clearance(booru):
    _blocked_search()                                  # real block: opens breaker
    hits = _Booru.hits
    # The user's clearance is (re)stored, e.g. by another flow, while the
    # breaker is still open. A synthetic circuit-open answer must not wipe it.
    store.save_bypass(BOORU, {"cf_clearance": "KEEP"}, "UA/1")
    _blocked_search()
    assert _Booru.hits == hits                         # no request went out
    assert store.get_cookies(BOORU) == {"cf_clearance": "KEEP"}


def test_captcha_success_reopens_host(booru):
    _blocked_search()
    store.save_bypass(BOORU, {"cf_clearance": "NEW"}, "UA/1")
    bypass_solved(BOORU)
    _Booru.blocked = False
    assert _search() == [{"id": 1}]
    assert _Booru.hits == 2
    assert store.get_cookies(BOORU) == {"cf_clearance": "NEW"}


def test_auto_solver_finish_keeps_saved_cookies_and_reopens(booru):
    from ui.browser_dialog.auto_solver import CloudflareAutoSolver
    _blocked_search()
    emitted = []
    stub = SimpleNamespace(
        _captured=False,
        _cleanup=lambda: None,
        _found_cookies={"cf_clearance": "SOLVED"},
        _profile=SimpleNamespace(httpUserAgent=lambda: "UA/2"),
        _booru_name=BOORU,
        solved=SimpleNamespace(emit=lambda c, u: emitted.append((c, u))),
    )
    CloudflareAutoSolver._finish(stub)
    assert emitted == [({"cf_clearance": "SOLVED"}, "UA/2")]
    assert store.get_cookies(BOORU) == {"cf_clearance": "SOLVED"}
    assert store.get_user_agent(BOORU) == "UA/2"
    _Booru.blocked = False
    assert _search() == [{"id": 1}]
    assert _Booru.hits == 2


def test_captcha_dialog_finalize_reopens_host(booru):
    from ui.browser_dialog.cloudflare_browser_dialog import CloudflareBrowserDialog
    _blocked_search()
    store.save_bypass(BOORU, {"cf_clearance": "PASTED"}, "UA/3")   # as _apply_pasted does
    stub = SimpleNamespace(
        booru_name=BOORU,
        cookies_captured=SimpleNamespace(emit=lambda c: None),
        accept=lambda: None,
    )
    CloudflareBrowserDialog._finalize(stub, {"cf_clearance": "PASTED"}, ua="UA/3")
    _Booru.blocked = False
    assert _search() == [{"id": 1}]
    assert _Booru.hits == 2
    assert store.get_cookies(BOORU) == {"cf_clearance": "PASTED"}


def test_reset_circuit_covers_cdn_hosts_of_the_site_only():
    sess._open_circuit("https://gelbooru.com/index.php?page=dapi")
    sess._open_circuit("https://img3.gelbooru.com/thumbnails/a.jpg")
    sess._open_circuit("https://danbooru.donmai.us/posts.json")
    sess.reset_circuit("https://gelbooru.com")
    assert not sess._circuit_is_open("https://gelbooru.com/x")
    assert not sess._circuit_is_open("https://img3.gelbooru.com/y")
    assert sess._circuit_is_open("https://danbooru.donmai.us/z")


def test_block_on_one_port_does_not_pause_another_booru_on_same_host(booru, monkeypatch):
    class _Other(http.server.BaseHTTPRequestHandler):
        hits = 0

        def do_GET(self):
            type(self).hits += 1
            body = b'[{"id": 2}]'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Other)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        other = "cbtest2"
        monkeypatch.setitem(boorus.REGISTRY, other,
                            {"url": f"http://127.0.0.1:{srv.server_port}", "api_type": "danbooru"})
        _blocked_search()                               # BOORU (other port) is blocked

        async def fetch(url, params=None):
            return await get_session(other).get(url, params=params)

        out = asyncio.run(search_posts(get_adapter("danbooru"), boorus.REGISTRY[other],
                                       fetch, "tag", 10))
        assert out == [{"id": 2}] and _Other.hits == 1
    finally:
        srv.shutdown()
        import cloudflare_bypasser
        cloudflare_bypasser._session_cache.pop("cbtest2", None)
