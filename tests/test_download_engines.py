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
    calls = []

    def fake_urlopen(req, timeout=None, context=None):
        calls.append(context)
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        raise urllib.error.URLError(ssl.SSLCertVerificationError("self-signed"))

    monkeypatch.setattr(engines.urllib.request, "urlopen", fake_urlopen)
    assert engines._download_urllib("https://mitm.example/x.jpg", tmp_path / "x", {}) is False
    assert len(calls) == 1


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
