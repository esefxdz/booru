"""Favicon cache filenames must be plain files (no ':port' NTFS streams)."""
import httpx

from ui.server_bar import favicon_fetcher as ff


def _run(tmp_path, monkeypatch, url):
    monkeypatch.setattr(ff, "_cache_dir", lambda: tmp_path)
    calls = []

    class R:
        status_code = 200
        content = b"x" * 200

    def fake_get(u, timeout=None):
        calls.append(u)
        return R()

    monkeypatch.setattr(httpx, "get", fake_get)
    got = []
    f = ff.FaviconFetcher("site", url)
    f.finished.connect(lambda n, p: got.append(p))
    f.run()
    return got, calls


def test_port_not_in_cache_filename(tmp_path, monkeypatch):
    got, calls = _run(tmp_path, monkeypatch, "http://192.168.1.5:8080")
    assert got and ":" not in got[0].replace("\\", "/").split("/")[-1]
    assert [p.name for p in tmp_path.iterdir()] == ["192.168.1.5_8080.png"]
    # the network request still targets the real host:port
    assert calls == ["https://icons.duckduckgo.com/ip3/192.168.1.5:8080.ico"]


def test_plain_domain_keeps_existing_cache_name(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, "https://danbooru.donmai.us/")
    assert [p.name for p in tmp_path.iterdir()] == ["danbooru.donmai.us.png"]
