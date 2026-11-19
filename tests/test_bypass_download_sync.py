"""BypassSession.download_sync streams to disk with an idle-style timeout."""
import http.server
import threading
import time

import pytest

from cloudflare_bypasser import session as sess_mod
from cloudflare_bypasser.session import BypassSession

pytest.importorskip("curl_cffi")

BODY = b"x" * 3000


class _Slow(http.server.BaseHTTPRequestHandler):
    release = threading.Event()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        if self.path == "/trickle":
            # Flows (a chunk per 0.5 s), total time > the 1 s timeout below.
            for i in range(0, len(BODY), 500):
                self.wfile.write(BODY[i:i + 500])
                self.wfile.flush()
                time.sleep(0.5)
        elif self.path == "/stall":
            self.wfile.write(BODY[:100])
            self.wfile.flush()
            self.release.wait(30)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    _Slow.release.clear()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Slow)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    _Slow.release.set()
    srv.shutdown()
    srv.server_close()


def _session():
    return BypassSession(method="curl_cffi", site_url="http://127.0.0.1")


def test_trickle_longer_than_timeout_finishes(server, tmp_path):
    dest = tmp_path / "v.mp4"
    t0 = time.time()
    resp = _session().download_sync(server + "/trickle", dest, timeout=1)
    assert time.time() - t0 > 1.5           # longer than the 1 s timeout
    assert resp.status_code == 200
    assert dest.read_bytes() == BODY
    assert not (tmp_path / "v.mp4.part").exists()


def test_stall_fails_and_leaves_no_file(server, tmp_path, monkeypatch):
    monkeypatch.setattr(sess_mod, "_MAX_ENGINE_ATTEMPTS", 1)
    monkeypatch.setattr(sess_mod, "_MAX_RETRIES", 1)
    dest = tmp_path / "v.mp4"
    resp = _session().download_sync(server + "/stall", dest, timeout=1)
    assert resp.status_code != 200
    assert list(tmp_path.iterdir()) == []   # neither v.mp4 nor v.mp4.part


def test_inflight_released(server, tmp_path):
    s = _session()
    s.download_sync(server + "/trickle", tmp_path / "a.mp4", timeout=1)
    assert s._inflight == 0
