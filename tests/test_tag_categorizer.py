"""TagCategorizer: breaker length, failures not cached, atomic save."""
import json
import time

from download_images import tag_categorizer


class _Resp:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data or []

    def json(self):
        return self._data


def _make(tmp_path):
    c = tag_categorizer.TagCategorizer.__new__(tag_categorizer.TagCategorizer)
    import threading
    c.cache_file = tmp_path / "tag_cache.json"
    c._legacy_cache_file = tmp_path / "nolegacy.json"
    c.cache = {}
    c._unresolved = {}
    c._lock = threading.Lock()
    c._fetch_lock = threading.Lock()
    return c


def test_failed_lookup_is_not_cached_as_general(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(tag_categorizer.httpx, "get", boom)
    c = _make(tmp_path)
    res = c.categorize_tags(["some_new_artist"])
    assert res["general"] == ["some_new_artist"]
    assert "some_new_artist" not in c.cache
    if c.cache_file.exists():
        assert "some_new_artist" not in json.loads(c.cache_file.read_text())
    # once the network is back it gets its real category
    def ok(url, **k):
        return _Resp(200, [{"name": "some_new_artist", "category": 1}])
    monkeypatch.setattr(tag_categorizer.httpx, "get", ok)
    c._unresolved.clear()
    assert c.categorize_tags(["some_new_artist"])["artist"] == ["some_new_artist"]


def test_breaker_lasts_300_seconds_not_600(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(tag_categorizer.httpx, "get",
                        lambda url, **k: (calls.append(url), _Resp(403))[1])
    c = _make(tmp_path)
    t0 = 10_000.0
    monkeypatch.setattr(tag_categorizer.time, "monotonic", lambda: t0)
    c._fetch_from_danbooru(["a"])
    assert any("danbooru" in u for u in calls)
    assert c._danbooru_blocked_until == t0 + 300
    # 301 s later the breaker is over: danbooru is queried again
    calls.clear()
    monkeypatch.setattr(tag_categorizer.time, "monotonic", lambda: t0 + 301)
    c._fetch_from_danbooru(["b"])
    assert any("danbooru" in u for u in calls)
    # 100 s in, still blocked: danbooru skipped
    calls.clear()
    c._danbooru_blocked_until = t0 + 400
    monkeypatch.setattr(tag_categorizer.time, "monotonic", lambda: t0 + 301)
    c._fetch_from_danbooru(["c"])
    assert not any("danbooru" in u for u in calls)


def test_save_cache_goes_through_atomic_write(tmp_path, monkeypatch):
    seen = []
    real = tag_categorizer.atomic_write_text
    monkeypatch.setattr(tag_categorizer, "atomic_write_text",
                        lambda p, t, *a, **k: (seen.append(p), real(p, t, *a, **k))[1])
    c = _make(tmp_path)
    c.cache = {"x": "artist"}
    c._save_cache()
    assert seen == [c.cache_file]
    assert json.loads(c.cache_file.read_text()) == {"x": "artist"}
