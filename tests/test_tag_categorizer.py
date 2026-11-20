"""Tag categories come from the booru itself (no Danbooru/e621 lookups)."""
import json
import threading

import pytest

import boorus
from adapters import get_adapter
from download_images import tag_categorizer

SAFEBOORU_HTML = """
<ul id="tag-sidebar">
  <li><h6>Copyright</h6></li>
  <li class="tag-type-copyright tag">
    <a href="index.php?page=wiki&s=list&search=original">?</a>
    <a href="index.php?page=post&amp;s=list&amp;tags=original">original</a>
    <span class="tag-count">778628</span>
  </li>
  <li class="tag-type-artist tag">
    <a href="index.php?page=post&amp;s=list&amp;tags=some_artist">some artist</a></li>
  <li class="tag-type-character tag">
    <a href="index.php?page=post&amp;s=list&amp;tags=hatsune_miku">hatsune miku</a></li>
  <li class="tag-type-metadata tag">
    <a href="index.php?page=post&amp;s=list&amp;tags=absurdres">absurdres</a></li>
  <li class="tag-type-general tag">
    <a href="index.php?page=post&amp;s=list&amp;tags=sky%28day%29">sky(day)</a></li>
</ul>
"""


@pytest.fixture
def cat(tmp_path, monkeypatch):
    c = tag_categorizer.TagCategorizer.__new__(tag_categorizer.TagCategorizer)
    c.cache_file = tmp_path / "tag_cache.json"
    c._legacy_cache_file = tmp_path / "nolegacy.json"
    c.cache = {}
    c._lock = threading.Lock()
    monkeypatch.setattr(tag_categorizer, "_categorizer", c)
    return c


def test_gelbooru_parses_tag_types_from_post_page():
    a = get_adapter("gelbooru")
    assert a.parse_tag_types(SAFEBOORU_HTML) == {
        "original": "copyright", "some_artist": "artist", "hatsune_miku": "character",
        "absurdres": "meta", "sky(day)": "general",
    }
    url = a.tag_types_url({"id": 7329358}, {"url": "https://safebooru.org"})
    assert url == "https://safebooru.org/index.php?page=post&s=view&id=7329358"


def test_unknown_tags_are_general_and_not_cached(cat):
    res = cat.categorize_tags(["brand_new_tag", "absurdres"])
    assert res["general"] == ["brand_new_tag"]
    assert res["meta"] == ["absurdres"]           # offline heuristic
    assert "brand_new_tag" not in cat.cache


def test_categorize_post_reads_the_booru_page_once(cat, monkeypatch):
    calls = []

    class _Sess:
        def get_sync(self, url, **k):
            calls.append(url)
            return type("R", (), {"status_code": 200, "text": SAFEBOORU_HTML})()

    import cloudflare_bypasser
    monkeypatch.setattr(cloudflare_bypasser, "get_session", lambda name: _Sess())
    monkeypatch.setitem(boorus.REGISTRY, "sb", {"url": "https://safebooru.org",
                                                "api_type": "gelbooru"})
    post = {"id": 5, "_booru": "sb", "tags": "original some_artist hatsune_miku sky(day)"}
    res = tag_categorizer.categorize_post(post)
    assert res["artist"] == ["some_artist"]
    assert res["character"] == ["hatsune_miku"]
    assert res["copyright"] == ["original"]
    assert calls == ["https://safebooru.org/index.php?page=post&s=view&id=5"]
    # every tag is cached now: a second post with the same tags makes no request
    tag_categorizer.categorize_post(dict(post, id=6))
    assert len(calls) == 1
    assert json.loads(cat.cache_file.read_text())["some_artist"] == "artist"


def test_categorize_post_survives_a_failed_lookup(cat, monkeypatch):
    class _Sess:
        def get_sync(self, url, **k):
            return type("R", (), {"status_code": 403, "text": ""})()

    import cloudflare_bypasser
    monkeypatch.setattr(cloudflare_bypasser, "get_session", lambda name: _Sess())
    monkeypatch.setitem(boorus.REGISTRY, "sb", {"url": "https://safebooru.org",
                                                "api_type": "gelbooru"})
    res = tag_categorizer.categorize_post({"id": 5, "_booru": "sb", "tags": "a b"})
    assert res["general"] == ["a", "b"]
    assert not cat.cache


def test_native_categories_skip_the_lookup(cat, monkeypatch):
    import cloudflare_bypasser
    monkeypatch.setattr(cloudflare_bypasser, "get_session",
                        lambda name: pytest.fail("no request expected"))
    monkeypatch.setitem(boorus.REGISTRY, "e", {"url": "https://e926.net", "api_type": "e621"})
    post = {"id": 1, "_booru": "e", "tags": {"artist": ["x"], "general": ["y"]}}
    assert tag_categorizer.categorize_post(post)["artist"] == ["x"]


def test_save_cache_goes_through_atomic_write(cat, monkeypatch):
    seen = []
    real = tag_categorizer.atomic_write_text
    monkeypatch.setattr(tag_categorizer, "atomic_write_text",
                        lambda p, t, *a, **k: (seen.append(p), real(p, t, *a, **k))[1])
    cat.cache = {"x": "artist"}
    cat._save_cache()
    assert seen == [cat.cache_file]
    assert json.loads(cat.cache_file.read_text()) == {"x": "artist"}
