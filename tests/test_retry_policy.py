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


# Request counts below are what one request does against a server that always
# answers the same way (measured, then pinned). Engine order in auto mode is
# curl_cffi, cloudscraper, httpx, requests, urllib. curl_cffi tries a second
# fingerprint only when the first gets a 403, so it costs 2 hits on a 403 and
# 1 hit on anything else. The sync path skips httpx (it is only a fallback
# there). A "round" is one pass over the engines; rounds repeat only while
# every failure was transient (no response / 5xx).
_BIG_HTML = b"<html>" + b"x" * 500 + b"</html>"
_CF_CHALLENGE = b"<html>" + b"x" * 300 + b"<title>Just a moment...</title> cf-chl-bypass</html>"


def _blocked_get(server, mode, body):
    _Counter.status, _Counter.body = 403, body
    s = _session(server)
    if mode == "async":
        return s, asyncio.run(s.get(server + "/x"))
    return s, s.get_sync(server + "/x")


# async: curl_cffi 2 (two fingerprints) + cloudscraper + httpx + requests +
# urllib = 6, one round. sync: the same minus httpx = 5.
@pytest.mark.parametrize("mode,expected", [("async", 6), ("sync", 5)])
@pytest.mark.parametrize("body", [b"forbidden", _CF_CHALLENGE], ids=["tiny-403", "big-html-cf-403"])
def test_blocked_403_runs_each_engine_once_then_circuit_opens(server, mode, expected, body):
    s, r = _blocked_get(server, mode, body)
    assert r.is_blocked
    # Exactly one round: a challenge is definitive, so no backoff rounds
    # (the old code ran 3 rounds: 24 hits async, 45 sync).
    assert _Counter.hits == expected, _Counter.hits
    first = _Counter.hits
    # Circuit is open: the same session and a fresh one make no requests.
    r2 = asyncio.run(s.get(server + "/y")) if mode == "async" else s.get_sync(server + "/y")
    assert r2.is_blocked and _Counter.hits == first
    asyncio.run(_session(server).get(server + "/z"))
    assert _Counter.hits == first


def test_403_with_big_non_cloudflare_body_is_accepted_not_blocked(server):
    # Not a challenge (big body, no CF markers): the first engine's answer is
    # accepted. curl_cffi saw a 403 on both fingerprints = 2 hits, no more
    # engines, and the circuit stays closed.
    _Counter.status, _Counter.body = 403, _BIG_HTML
    r = asyncio.run(_session(server).get(server + "/x"))
    assert r.status_code == 403 and not r.is_blocked
    assert _Counter.hits == 2
    assert not sess._blocked_until


# async: round 1 = 5 engine calls (1 hit each, curl_cffi does not retry a 503);
# round 2 is cut off by _MAX_ENGINE_ATTEMPTS=8 after 3 more (curl_cffi,
# cloudscraper, httpx) = 8 hits.
def test_transient_5xx_is_still_retried_but_capped(server):
    _Counter.status, _Counter.body = 503, _BIG_HTML
    r = asyncio.run(_session(server).get(server + "/flaky"))
    assert r.status_code == 503 and not r.is_blocked
    assert _Counter.hits == sess._MAX_ENGINE_ATTEMPTS == 8
    assert not sess._blocked_until          # a 5xx is not a block


# sync: two rounds of the 4 sync engines = 8 attempts (the cap), then the
# httpx fallback runs through get(only_engines=["httpx"]), which has its own
# budget and makes 3 hits (3 rounds of one engine) = 11 hits total. That is
# more than _MAX_ENGINE_ATTEMPTS: the cap is per loop, not per get_sync call.
def test_transient_5xx_get_sync_hits(server):
    _Counter.status, _Counter.body = 503, _BIG_HTML
    r = _session(server).get_sync(server + "/flaky")
    assert r.status_code == 503
    assert _Counter.hits == 8 + 3, _Counter.hits


def test_success_closes_circuit(server):
    s = _session(server)
    asyncio.run(s.get(server + "/x"))                  # opens the circuit
    sess._blocked_until.clear()                         # cooldown elapsed
    _Counter.status, _Counter.body = 200, b'{"ok": true}'
    r = asyncio.run(s.get(server + "/x"))
    assert r.status_code == 200 and not sess._blocked_until
