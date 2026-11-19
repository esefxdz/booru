"""A blocked or failing site must not be hammered."""
import asyncio
import http.server
import threading

import pytest

from cloudflare_bypasser import session as sess
from cloudflare_bypasser.session import BypassSession


class _Counter(http.server.BaseHTTPRequestHandler):
    status = 403
    body = b"forbidden"          # tiny 403 = treated as a block
    hits = 0

    def do_GET(self):
        type(self).hits += 1
        self.send_response(self.status)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Counter)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Counter.hits = 0
    _Counter.status, _Counter.body = 403, b"forbidden"
    monkeypatch.setattr(sess, "_RETRY_BACKOFF_BASE", 0.01)
    from ui import settings_view as settings
    monkeypatch.setattr(settings.manager, "use_rate_limit", False, raising=False)
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _session(base):
    return BypassSession(site_url=base)


def test_blocked_async_get_is_bounded_and_then_circuit_opens(server):
    s = _session(server)
    r = asyncio.run(s.get(server + "/x"))
    assert r.is_blocked
    first = _Counter.hits
    assert 1 <= first <= sess._MAX_ENGINE_ATTEMPTS, first      # was 24
    r2 = asyncio.run(s.get(server + "/y"))
    assert r2.is_blocked and _Counter.hits == first             # no network while open


def test_blocked_get_sync_is_bounded_and_never_reruns_engines(server):
    s = _session(server)
    r = s.get_sync(server + "/x")
    assert r.is_blocked
    assert 1 <= _Counter.hits <= sess._MAX_ENGINE_ATTEMPTS, _Counter.hits   # was 45
    before = _Counter.hits
    s.get_sync(server + "/y")
    assert _Counter.hits == before


def test_plain_404_is_not_retried(server):
    _Counter.status, _Counter.body = 404, b"<html>" + b"x" * 500 + b"</html>"
    s = _session(server)
    r = asyncio.run(s.get(server + "/missing"))
    assert r.status_code == 404
    assert _Counter.hits <= sess._MAX_ENGINE_ATTEMPTS


def test_transient_5xx_is_still_retried_but_capped(server):
    _Counter.status, _Counter.body = 503, b"<html>" + b"x" * 500 + b"</html>"
    s = _session(server)
    asyncio.run(s.get(server + "/flaky"))
    assert sess._MAX_ENGINE_ATTEMPTS >= _Counter.hits > 1


def test_success_closes_circuit(server):
    s = _session(server)
    asyncio.run(s.get(server + "/x"))                  # opens the circuit
    sess._blocked_until.clear()                         # cooldown elapsed
    _Counter.status, _Counter.body = 200, b'{"ok": true}'
    r = asyncio.run(s.get(server + "/x"))
    assert r.status_code == 200 and not sess._blocked_until
