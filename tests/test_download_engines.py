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
