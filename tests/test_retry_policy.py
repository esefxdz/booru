"""A blocked or failing site must not be hammered."""
import asyncio
import http.server
import threading

import pytest

from cloudflare_bypasser import circuit_breaker as cb
from cloudflare_bypasser import session as sess
from cloudflare_bypasser.session import BypassSession


class _Counter(http.server.BaseHTTPRequestHandler):
    status = 403
    body = b"forbidden"          # tiny 403: blocked, but not a CF challenge
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
    from core import settings
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
    # Both kinds stop the chain and pause the host (is_blocked). Only the
    # page with Cloudflare markers is evidence of a challenge, which is what
    # lets api_client clear a stored cf_clearance. A 9-byte "forbidden" may
    # be a CF firewall block or the site's own 403; either way another
    # fingerprint is worth one try and the host should not be hammered, but
    # it says nothing about the clearance, so it is no longer a challenge.
    assert r.is_blocked
    assert r.is_cf_challenge == (body == _CF_CHALLENGE)
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
    assert not cb._blocked_until


# async: round 1 = 5 engine calls (1 hit each, curl_cffi does not retry a 503);
# round 2 is cut off by _MAX_ENGINE_ATTEMPTS=8 after 3 more (curl_cffi,
# cloudscraper, httpx) = 8 hits.
def test_transient_5xx_is_still_retried_but_capped(server):
    _Counter.status, _Counter.body = 503, _BIG_HTML
    r = asyncio.run(_session(server).get(server + "/flaky"))
    assert r.status_code == 503 and not r.is_blocked
    assert _Counter.hits == sess._MAX_ENGINE_ATTEMPTS == 8
    assert not cb._blocked_until          # a 5xx is not a block


# sync: two rounds of the 4 sync engines = 8 attempts, which is the whole
# _MAX_ENGINE_ATTEMPTS budget. The httpx fallback shares that budget, so it
# has nothing left and does not run: 8 hits. (It used to get a budget of its
# own and add 3 more hits, 11 in total.)
def test_transient_5xx_get_sync_hits(server):
    _Counter.status, _Counter.body = 503, _BIG_HTML
    r = _session(server).get_sync(server + "/flaky")
    assert r.status_code == 503
    assert _Counter.hits == sess._MAX_ENGINE_ATTEMPTS == 8, _Counter.hits


# The fallback still runs when budget is left, but only with what is left:
# urllib x3 rounds (503) = 3 attempts, httpx gets the remaining 1, not 3.
def test_get_sync_httpx_fallback_uses_remaining_budget(server, monkeypatch):
    _Counter.status, _Counter.body = 503, _BIG_HTML
    s = _session(server)
    monkeypatch.setattr(s, "_get_engine_order", lambda: ["urllib", "httpx"])
    monkeypatch.setattr(sess, "_MAX_ENGINE_ATTEMPTS", 4)
    r = s.get_sync(server + "/flaky")
    assert r.status_code == 503
    assert _Counter.hits == 3 + 1, _Counter.hits


def test_success_closes_circuit(server):
    s = _session(server)
    asyncio.run(s.get(server + "/x"))                  # opens the circuit
    cb._blocked_until.clear()                         # cooldown elapsed
    _Counter.status, _Counter.body = 200, b'{"ok": true}'
    r = asyncio.run(s.get(server + "/x"))
    assert r.status_code == 200 and not cb._blocked_until
