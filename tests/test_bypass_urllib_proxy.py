"""When core.proxy says direct, the bypass urllib engine does not add an
env/registry proxy on its own."""
import http.server
import socket
import threading

import pytest

from core import settings  # noqa: F401  # avoid circular import
from cloudflare_bypasser import engines


class _Ok(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"ok": 1}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Ok)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    srv.server_close()


def test_empty_app_proxy_ignores_system_proxy(server, monkeypatch):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead = s.getsockname()[1]
    s.close()
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.setenv(var, f"http://127.0.0.1:{dead}")
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    r = engines._try_urllib_sync(server + "/x", None, {}, {}, "", 3)
    assert r is not None and r.status_code == 200 and r.json() == {"ok": 1}
