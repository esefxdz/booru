"""Server-supplied ids, extensions and URLs must never escape the target
folder or reach a non-http(s) scheme."""
import pytest

import validation as v
from download_images import image_downloader


# ── require_http_url ────────────────────────────────────────────────────
@pytest.mark.parametrize("url,base,expected", [
    ("https://a.com/x.jpg", None, "https://a.com/x.jpg"),
    ("//cdn.a.com/x.jpg", None, "https://cdn.a.com/x.jpg"),
    ("/data/x.png", "https://szuru.example", "https://szuru.example/data/x.png"),
    ("data/x.png", "https://szuru.example/", "https://szuru.example/data/x.png"),
])
def test_http_urls_accepted_and_resolved(url, base, expected):
    assert v.require_http_url(url, base) == expected


@pytest.mark.parametrize("url", [
    "file:///C:/Windows/win.ini", "data:text/html,x", "javascript:x", "av://lavfi:x",
    "", "   ", "/relative/without/base", "https://a.com/x\r\nInjected: 1",
])
def test_non_http_urls_rejected(url):
    with pytest.raises(v.ValidationError):
        v.require_http_url(url)


# ── safe_post_id / media_extension / safe_media_path ────────────────────
@pytest.mark.parametrize("pid", [12345, "12345", "abc_DEF-9"])
def test_normal_ids_kept(pid):
    assert v.safe_post_id(pid) == str(pid)


@pytest.mark.parametrize("pid", [
    r"..\..\..\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\x",
    "../../etc/passwd", "a/b", "C:x", "", None, "x" * 65, "con\x00",
])
def test_hostile_ids_hashed(pid):
    out = v.safe_post_id(pid)
    assert out.startswith("id_") and "/" not in out and "\\" not in out and ".." not in out


@pytest.mark.parametrize("url,ext", [
    ("https://a/x.JPG", ".jpg"), ("https://a/x.webm?y=1", ".webm"), ("https://a/x", ".jpg"),
    ("https://a/x.bat", ".bin"), ("https://a/x.exe", ".bin"), ("https://a/x.lnk", ".bin"),
    ("https://a/x.zip", ".zip"),
])
def test_media_extension_allowlist(url, ext):
    assert v.media_extension(url) == ext


def test_audit_startup_folder_attack_stays_in_folder(tmp_path):
    dest = v.safe_media_path(
        tmp_path,
        r"..\..\..\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\x",
        "https://evil.example/payload.bat",
    )
    assert dest.parent == tmp_path and dest.suffix == ".bin"


# ── download_post end-to-end with a fake engine ─────────────────────────
class _Downloader:
    def __init__(self, url):
        self.url = url

    def get_file_url(self, post):
        return self.url


@pytest.fixture
def fake_engine(monkeypatch):
    calls = []

    def engine(url, dest, headers, on_progress=None):
        calls.append((url, dest))
        dest.write_bytes(b"data")
        return True

    monkeypatch.setitem(image_downloader.ENGINE_FNS, "fake", engine)
    return calls


def test_download_post_writes_inside_folder(tmp_path, fake_engine):
    post = {"id": "../../escape", "_booru": "safebooru"}
    ok = image_downloader.download_post(post, tmp_path, _Downloader("https://a/x.bat"), engine="fake")
    assert ok
    files = list(tmp_path.iterdir())
    assert len(files) == 1 and files[0].suffix == ".bin"
    assert not (tmp_path.parent / "escape.bat").exists()


def test_download_post_refuses_file_scheme(tmp_path, fake_engine):
    ok = image_downloader.download_post({"id": 1}, tmp_path, _Downloader("file:///C:/secret.txt"), engine="fake")
    assert not ok and fake_engine == []


def test_failed_download_leaves_no_file(tmp_path, monkeypatch):
    def broken(url, dest, headers, on_progress=None):
        dest.write_bytes(b"half")
        raise ConnectionError("dropped")

    monkeypatch.setitem(image_downloader.ENGINE_FNS, "broken", broken)
    ok = image_downloader.download_post({"id": 7}, tmp_path, _Downloader("https://a/7.png"), engine="broken")
    assert not ok and list(tmp_path.iterdir()) == []   # no truncated 7.png left behind


def test_bypass_session_refuses_file_scheme():
    from cloudflare_bypasser.session import _refuse_non_http
    r = _refuse_non_http("file:///C:/Windows/win.ini")
    assert r is not None and r.status_code == 0 and r.content == b""
    assert _refuse_non_http("https://safebooru.org/index.php") is None


def test_double_click_downloads_once_and_file_is_intact(tmp_path, monkeypatch):
    import threading
    import time
    calls = []

    def slow_engine(url, dest, headers, on_progress=None):
        calls.append(threading.current_thread().name)
        with open(dest, "wb") as f:
            for i in range(20):
                f.write(bytes([65 + len(calls) - 1]) * 100)   # thread-specific bytes
                time.sleep(0.005)
        return True

    monkeypatch.setitem(image_downloader.ENGINE_FNS, "slow", slow_engine)
    post = {"id": 42, "_booru": "safebooru"}
    results = []
    ts = [threading.Thread(target=lambda: results.append(
        image_downloader.download_post(post, tmp_path, _Downloader("https://a/42.png"), engine="slow")))
        for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results == [True, True, True]
    assert len(calls) == 1, "the same post was downloaded concurrently"
    data = (tmp_path / "42.png").read_bytes()
    assert len(data) == 2000 and len(set(data)) == 1     # one stream, not a mix
    assert not list(tmp_path.glob("*.part"))
