"""Bypass/session cookies must only reach the booru's own site."""
import asyncio
import http.server
import threading

import pytest

import boorus
import validation as v
from cloudflare_bypasser.session import BypassSession
from download_images import engines, image_downloader, thumb_client


# ── pure helpers ────────────────────────────────────────────────────────
@pytest.mark.parametrize("url,site,expected", [
    ("https://img3.gelbooru.com/x.jpg", "https://gelbooru.com", True),
    ("https://cdn.donmai.us/x.jpg", "https://danbooru.donmai.us", True),
    ("https://files.yande.re/x.jpg", "https://yande.re", True),
    ("https://evil.example/x.jpg", "https://gelbooru.com", False),
    ("https://gelbooru.com.evil.example/x", "https://gelbooru.com", False),
    ("https://a.co.uk/x", "https://b.co.uk", False),
    ("", "https://gelbooru.com", False),
    ("https://gelbooru.com/x", "", False),
])
def test_same_site(url, site, expected):
    assert v.same_site(url, site) is expected


def test_session_scopes_cookies():
    s = BypassSession(cookies={"cf_clearance": "secret"}, site_url="https://gelbooru.com")
    assert s._cookies_for("https://img3.gelbooru.com/a.jpg") == {"cf_clearance": "secret"}
    assert s._cookies_for("https://evil.example/a.jpg") == {}


def test_session_without_site_sends_nothing():
    s = BypassSession(cookies={"cf_clearance": "secret"})
    assert s._cookies_for("https://anything.example/") == {}


def test_download_headers_scoped(monkeypatch):
    from cloudflare_bypasser import store
    monkeypatch.setattr(store, "get_cookies", lambda booru: {"cf_clearance": "secret"})
    post = {"_booru": "gelbooru"}
    assert "Cookie" in image_downloader._build_headers(post, "https://img3.gelbooru.com/x.jpg")
    assert "Cookie" not in image_downloader._build_headers(post, "https://evil.example/x.jpg")


# ── local servers: "site A" on 127.0.0.1, "site B" on 127.0.0.2 ─────────
class _Recorder(http.server.BaseHTTPRequestHandler):
    seen: list = []
    redirect_to = None

    def do_GET(self):
        _Recorder.seen.append((self.headers.get("Host"), self.path, self.headers.get("Cookie")))
        if self.path.startswith("/redirect") and _Recorder.redirect_to:
            self.send_response(302)
            self.send_header("Location", _Recorder.redirect_to)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def servers():
    srvs = []
    for _ in range(2):
        srv = http.server.ThreadingHTTPServer(("0.0.0.0", 0), _Recorder)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        srvs.append(srv)
    _Recorder.seen = []
    yield srvs[0].server_port, srvs[1].server_port
    for s in srvs:
        s.shutdown()


def _cookie_seen_by(port_host_prefix):
    return [c for host, _, c in _Recorder.seen if host.startswith(port_host_prefix)]


@pytest.mark.parametrize("name", [e for e in engines.ENGINES if e in engines.get_available_engines()])
def test_engine_drops_cookie_on_cross_site_redirect(servers, tmp_path, name):
    a, b = servers
    _Recorder.redirect_to = f"http://127.0.0.2:{b}/final.png"
    ok = engines.ENGINE_FNS[name](
        f"http://127.0.0.1:{a}/redirect", tmp_path / "x.png",
        {"Cookie": "cf_clearance=secret", "User-Agent": "t"},
    )
    assert ok
    assert _cookie_seen_by("127.0.0.1") == ["cf_clearance=secret"]
    assert _cookie_seen_by("127.0.0.2") == [None], f"{name} leaked the cookie"


def test_urllib_refuses_redirect_to_file_scheme(servers, tmp_path):
    a, _ = servers
    _Recorder.redirect_to = "file:///C:/Windows/win.ini"
    assert engines._download_urllib(f"http://127.0.0.1:{a}/redirect", tmp_path / "x", {}) is False


def test_thumb_client_scopes_cookies(servers, monkeypatch):
    a, b = servers
    _Recorder.redirect_to = None
    from cloudflare_bypasser import store
    monkeypatch.setattr(store, "get_cookies", lambda booru: {"cf_clearance": "secret"})
    monkeypatch.setitem(boorus.REGISTRY, "testbooru", {
        "url": f"http://127.0.0.1:{a}", "api_path": "/index.php", "post_key": None, "api_type": "gelbooru"})

    async def run():
        try:
            r1 = await thumb_client.thumb_fetch(f"http://127.0.0.1:{a}/t.png", booru="testbooru")
            r2 = await thumb_client.thumb_fetch(f"http://127.0.0.2:{b}/t.png", booru="testbooru")
            return r1, r2
        finally:
            await thumb_client.close_all()

    r1, r2 = asyncio.run(run())
    assert r1 is not None and r2 is not None
    assert _cookie_seen_by("127.0.0.1") == ["cf_clearance=secret"]
    assert _cookie_seen_by("127.0.0.2") == [None]


def test_bypass_urllib_engine_works_and_scopes_redirects(servers):
    """The bypass urllib fallback used to raise on every request."""
    from cloudflare_bypasser.engines import _try_urllib_sync
    a, b = servers
    _Recorder.redirect_to = f"http://127.0.0.2:{b}/final.png"
    r = _try_urllib_sync(f"http://127.0.0.1:{a}/redirect", None, {"User-Agent": "t"},
                         {"cf_clearance": "secret"}, "", 10)
    assert r is not None and r.status_code == 200
    assert _cookie_seen_by("127.0.0.1") == ["cf_clearance=secret"]
    assert _cookie_seen_by("127.0.0.2") == [None]
