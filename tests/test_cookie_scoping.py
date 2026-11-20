"""Bypass/session cookies must only reach the booru's own site."""
import asyncio
import http.server
import threading

import pytest

import boorus
from core import validation as v
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


# ── Bypass engines that use a requests-style cookie jar ─────────────────
def _bypass_jar_engines():
    from cloudflare_bypasser import engines as be
    out = []
    if be._HAS_REQUESTS:
        out.append(("requests", be._try_requests_sync))
    if be._HAS_CLOUDSCRAPER:
        out.append(("cloudscraper", be._try_cloudscraper_sync))
    return out


@pytest.mark.parametrize("name,fn", _bypass_jar_engines())
def test_bypass_jar_engines_drop_cookie_on_cross_site_redirect(servers, name, fn):
    a, b = servers
    _Recorder.redirect_to = f"http://127.0.0.2:{b}/final.png"
    r = fn(f"http://127.0.0.1:{a}/redirect", None, {"User-Agent": "t"},
           {"cf_clearance": "secret"}, "", 10)
    assert r is not None and r.status_code == 200
    assert _cookie_seen_by("127.0.0.1") == ["cf_clearance=secret"]
    assert _cookie_seen_by("127.0.0.2") == [None], f"{name} leaked the cookie"


@pytest.mark.parametrize("url", [
    r"https://evil.example\@gelbooru.com/x",      # urllib.parse: gelbooru.com, urllib3: evil.example
    "https://user@gelbooru.com/x",
    r"https://gelbooru.com:443\@evil.example/",
])
def test_ambiguous_urls_refused_and_never_same_site(url):
    assert v.same_site(url, "https://gelbooru.com") is False
    with pytest.raises(v.ValidationError):
        v.require_http_url(url)


def test_session_never_sends_cookies_to_ambiguous_url():
    s = BypassSession(cookies={"cf_clearance": "secret"}, site_url="https://gelbooru.com")
    assert s._cookies_for(r"https://evil.example\@gelbooru.com/x") == {}


# ── session cookies adopted only from same-site final URLs ─────────────
def test_remember_cookies_ignores_third_party_final_hop():
    from cloudflare_bypasser.engines import BypassResponse
    s = BypassSession(site_url="https://gelbooru.com")
    hop = BypassResponse(b"", "", 200, "https://tracker.example/x", None, "t", {"planted": "1"})
    s._remember_cookies("https://gelbooru.com/index.php", hop)
    assert "planted" not in s._merged_cookies
    ok = BypassResponse(b"", "", 200, "https://img3.gelbooru.com/x", None, "t", {"fine": "1"})
    s._remember_cookies("https://gelbooru.com/index.php", ok)
    assert s._merged_cookies.get("fine") == "1"


# ── programmatic login ──────────────────────────────────────────────────
class _Login(http.server.BaseHTTPRequestHandler):
    seen: list = []
    mode = "ok"
    other = ""

    def _rec(self, body=b""):
        _Login.seen.append((self.headers.get("Host").split(":")[0], self.command, self.path,
                            self.headers.get("Cookie"), body))

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._rec(body)
        if _Login.mode == "307-offsite":
            self.send_response(307)
            self.send_header("Location", _Login.other + "/steal")
        else:
            self.send_response(302)
            self.send_header("Location", "/index.php?page=account")
            self.send_header("Set-Cookie", "PHPSESSID=good; Path=/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._rec()
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


@pytest.fixture
def login_servers():
    srvs = []
    for _ in range(2):
        srv = http.server.ThreadingHTTPServer(("0.0.0.0", 0), _Login)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        srvs.append(srv)
    _Login.seen = []
    _Login.other = f"http://127.0.0.2:{srvs[1].server_port}"
    yield f"http://127.0.0.1:{srvs[0].server_port}"
    for s in srvs:
        s.shutdown()


def test_login_never_reposts_password_offsite(login_servers):
    from adapters.session_login import perform_login
    _Login.mode = "307-offsite"
    out = asyncio.run(perform_login(login_servers, "gelbooru", "alice", "hunter2"))
    assert out == {}
    assert all(host == "127.0.0.1" for host, *_ in _Login.seen), _Login.seen


def test_login_same_site_redirect_and_harvest(login_servers):
    from adapters.session_login import perform_login

    class _BS:
        user_agent = "UA"
        cookies = {"cf_clearance": "secret"}

    _Login.mode = "ok"
    out = asyncio.run(perform_login(login_servers, "gelbooru", "alice", "hunter2", _BS()))
    assert out == {"PHPSESSID": "good"}
    assert _Login.seen[0][3] == "cf_clearance=secret"     # sent on our own POST


def test_login_refuses_plain_http_to_public_host():
    from adapters.session_login import perform_login
    assert asyncio.run(perform_login("http://example.com", "gelbooru", "a", "b")) == {}


# --- dotless hosts (localhost, intranet names) ------------------------------

@pytest.mark.parametrize("site,sent_to,expected", [
    ("http://localhost:8080/x", "http://localhost:8080/y", "a=1"),
    ("http://nas:8080/x", "http://nas:8080/y", "a=1"),
    ("http://nas:8080/x", "http://other:8080/y", None),
    ("http://nas:8080/x", "http://nas.evil.com/y", None),
    ("http://nas:8080/x", "http://localhost:8080/y", None),
    ("http://localhost:8080/x", "https://example.com/y", None),
    ("https://gelbooru.com/x", "https://img.gelbooru.com/y", "a=1"),
    ("https://gelbooru.com/x", "https://evil.com/y", None),
])
def test_engine_cookie_jar_dotless_hosts(site, sent_to, expected):
    import urllib.request
    import requests
    from cloudflare_bypasser.engines import _set_site_scoped_cookies
    jar = requests.Session().cookies
    _set_site_scoped_cookies(jar, {"a": "1"}, site)
    req = urllib.request.Request(sent_to)
    jar.add_cookie_header(req)
    assert req.get_header("Cookie") == expected


@pytest.mark.parametrize("host,expected", [
    ("localhost", True), ("nas", True), ("my-nas", True), ("NAS.", True),
    ("printer.local", True), ("192.168.1.5", True), ("10.0.0.2", True),
    ("example.com", False), ("8.8.8.8", False), ("", False),
    ("2001:4860:4860::8888", False), ("::1", True),
    ("134744072", False), ("0x8080808", False), ("1", False),
])
def test_is_private_host(host, expected):
    assert v.is_private_host(host) is expected


def test_login_harvests_from_localhost():
    import socket
    from adapters.session_login import perform_login

    class _DualStack(http.server.ThreadingHTTPServer):
        address_family = socket.AF_INET6

        def server_bind(self):
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            super().server_bind()

    try:
        srv = _DualStack(("::", 0), _Login)
    except OSError:
        pytest.skip("no IPv6 dual-stack sockets")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Login.seen = []
    _Login.mode = "ok"
    site = f"http://localhost:{srv.server_port}"
    try:
        out = asyncio.run(perform_login(site, "gelbooru", "alice", "hunter2"))
    finally:
        srv.shutdown()
    assert _Login.seen, "login request never reached the localhost server"
    assert out == {"PHPSESSID": "good"}


def test_login_allows_plain_http_to_bare_lan_name(monkeypatch):
    import httpx
    from adapters.session_login import perform_login
    seen = []

    class _Resp:
        is_redirect = False
        url = "http://nas:8080/x"

    class _Client:
        def __init__(self, *a, **k):
            self.headers = {}
            self.cookies = httpx.Cookies()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **k):
            seen.append(url)
            self.cookies.set("PHPSESSID", "good", domain="nas.local", path="/")
            self.cookies.set("PHPSESSID2", "x", domain="evil.com", path="/")
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    out = asyncio.run(perform_login("http://nas:8080", "gelbooru", "a", "b"))
    assert seen and out == {"PHPSESSID": "good"}
