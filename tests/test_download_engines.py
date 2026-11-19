"""Download engines: no insecure retry, no shell engine, real local transfers."""
import http.server
import ssl
import threading
import urllib.error

import pytest

from download_images import engines


def test_powershell_engine_removed():
    assert "powershell" not in engines.ENGINES
    assert "powershell" not in engines.ENGINE_FNS
    assert "powershell" not in engines.get_available_engines()


def test_urllib_tls_failure_is_not_retried_insecurely(tmp_path, monkeypatch):
    opens = []
    real_build_opener = engines.urllib.request.build_opener

    def fake_build_opener(*handlers):
        https = [h for h in handlers if isinstance(h, engines.urllib.request.HTTPSHandler)]
        assert https and https[0]._context.verify_mode == ssl.CERT_REQUIRED
        assert https[0]._context.check_hostname
        opener = real_build_opener(*handlers)

        def failing_open(req, timeout=None):
            opens.append(req.full_url)
            raise urllib.error.URLError(ssl.SSLCertVerificationError("self-signed"))

        opener.open = failing_open
        return opener

    monkeypatch.setattr(engines.urllib.request, "build_opener", fake_build_opener)
    assert engines._download_urllib("https://mitm.example/x.jpg", tmp_path / "x", {}) is False
    assert opens == ["https://mitm.example/x.jpg"]   # exactly one attempt, no insecure retry


# ── Real transfers against a local HTTP server ──────────────────────────
class _Handler(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        _Handler.seen.append((self.server.server_port, self.path, self.headers.get("Cookie")))
        body = b"IMAGEDATA" * 100
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    _Handler.seen.clear()
    yield srv
    srv.shutdown()


@pytest.mark.parametrize("name", [e for e in engines.ENGINES if e in engines.get_available_engines()])
def test_engine_downloads_file(server, tmp_path, name):
    url = f"http://127.0.0.1:{server.server_port}/img.jpg"
    dest = tmp_path / "img.jpg"
    progress = []
    ok = engines.ENGINE_FNS[name](url, dest, {"User-Agent": "test"}, lambda d, t: progress.append((d, t)))
    assert ok and dest.read_bytes() == b"IMAGEDATA" * 100
    assert progress and progress[-1][0] == progress[-1][1] == 900


# ── Proxy setting is honoured by every engine ───────────────────────────
class _Proxy(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        _Proxy.seen.append(self.path)          # absolute-form when used as a proxy
        body = b"VIA-PROXY"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def proxy(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Proxy)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Proxy.seen = []
    from ui import settings_view as settings
    monkeypatch.setattr(settings.manager, "proxy_url", f"http://127.0.0.1:{srv.server_port}", raising=False)
    yield srv
    srv.shutdown()
    engines.shutdown()


@pytest.mark.parametrize("name", [e for e in engines.ENGINES if e in engines.get_available_engines()])
def test_engine_uses_configured_proxy(proxy, tmp_path, name):
    # 203.0.113.0/24 is TEST-NET-3: unroutable, so success proves the proxy was used
    url = "http://203.0.113.7/img.png"
    dest = tmp_path / "img.png"
    assert engines.ENGINE_FNS[name](url, dest, {"User-Agent": "t"})
    assert dest.read_bytes() == b"VIA-PROXY"
    assert _Proxy.seen == [url]


def test_urllib_refuses_socks_proxy_instead_of_going_direct(tmp_path, monkeypatch):
    from ui import settings_view as settings
    monkeypatch.setattr(settings.manager, "proxy_url", "socks5://127.0.0.1:9", raising=False)
    assert engines._download_urllib("http://203.0.113.7/x.png", tmp_path / "x", {}) is False


class _Truncating(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "1000")   # promise 1000 bytes...
        self.end_headers()
        self.wfile.write(b"x" * 300)                   # ...send 300 and hang up
        self.wfile.flush()
        self.close_connection = True

    def log_message(self, *a):
        pass


@pytest.mark.parametrize("name", [e for e in engines.ENGINES if e in engines.get_available_engines()])
def test_truncated_download_is_not_accepted(tmp_path, name):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Truncating)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/img.jpg"
        try:
            ok = engines.ENGINE_FNS[name](url, tmp_path / "img.jpg", {"User-Agent": "t"})
        except Exception:
            ok = False
        assert ok is False, f"{name} accepted a 300/1000-byte file"
    finally:
        srv.shutdown()


def test_requests_session_is_per_thread():
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        ids = set(pool.map(lambda _: id(engines._requests_session()), range(8)))
    assert len(ids) > 1
    engines.shutdown()


# ── curl_cffi streams with an idle timeout, not a total one ─────────────
class _Slow(http.server.BaseHTTPRequestHandler):
    """/trickle: 12 x 100 bytes, one every 0.25 s (~3 s total, never idle).
    /stall: headers + 100 of 1000 bytes, then silence until teardown."""
    release = threading.Event()

    def do_GET(self):
        import time
        self.send_response(200)
        self.send_header("Content-Length", "1200" if self.path.startswith("/trickle") else "1000")
        self.end_headers()
        if self.path.startswith("/trickle"):
            for _ in range(12):
                self.wfile.write(b"t" * 100)
                self.wfile.flush()
                time.sleep(0.25)
        else:
            self.wfile.write(b"s" * 100)
            self.wfile.flush()
            _Slow.release.wait(30)

    def log_message(self, *a):
        pass


@pytest.fixture
def slow_server(monkeypatch):
    # 1 s, the finest curl_cffi allows (its idle time is ceil()'d seconds).
    monkeypatch.setattr(engines, "_TIMEOUT", 1)
    _Slow.release.clear()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Slow)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    _Slow.release.set()
    srv.shutdown()


_needs_cffi = pytest.mark.skipif("curl_cffi" not in engines.get_available_engines(),
                                 reason="curl_cffi not installed")


@_needs_cffi
def test_curl_cffi_slow_but_flowing_download_finishes(slow_server, tmp_path):
    # Takes ~3 s with a 1 s timeout: the old total timeout cut it off.
    url = f"http://127.0.0.1:{slow_server.server_port}/trickle.jpg"
    dest = tmp_path / "t.jpg"
    progress = []
    assert engines._download_curl_cffi(url, dest, {"User-Agent": "t"},
                                       lambda d, t: progress.append((d, t)))
    assert dest.read_bytes() == b"t" * 1200
    assert progress[-1] == (1200, 1200) and len(progress) > 1   # streamed, not one blob


@_needs_cffi
def test_curl_cffi_stalled_download_times_out_and_leaves_no_file(slow_server, tmp_path, monkeypatch):
    import time
    from download_images import image_downloader

    class _Dl:
        def get_file_url(self, post):
            return f"http://127.0.0.1:{slow_server.server_port}/stall.jpg"

    monkeypatch.setattr(image_downloader, "_build_headers", lambda post, url="": {"User-Agent": "t"})
    t0 = time.monotonic()
    ok = image_downloader.download_post({"id": 5}, tmp_path, _Dl(), engine="curl_cffi")
    assert not ok
    # libcurl averages speed over ~5 s, so a 1 s idle limit fires after ~7 s.
    assert time.monotonic() - t0 < 15          # the idle timeout fired; it did not hang
    assert list(tmp_path.iterdir()) == []      # no 5.jpg and no 5.jpg.part
