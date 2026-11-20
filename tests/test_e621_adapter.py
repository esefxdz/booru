"""e621 adapter reads both the old posts.json shape and the 2026 one."""
from adapters import get_adapter
from tests.test_api_client_parsing import _run

NEW_POST = {
    "id": 6870384,
    "files": {
        "meta": {"md5": "a287", "ext": "webm", "size": 8026465},
        "original": {"width": 1916, "height": 1080,
                     "url": "https://static1.e621.net/data/a2/87/a287.webm"},
        "preview": {"jpg": "https://static1.e621.net/data/preview/a2/87/a287.jpg",
                    "webp": "https://static1.e621.net/data/preview/a2/87/a287.webp"},
        "sample": {"jpg": "https://static1.e621.net/data/sample/a2/87/a287.jpg"},
    },
    "rating": "s",
    "tags": ["blue_eyes", "hi_res", "dastik228"],
}

OLD_POST = {
    "id": 1,
    "file": {"url": "https://static1.e621.net/data/aa/bb/x.png", "ext": "png"},
    "preview": {"url": "https://static1.e621.net/data/preview/aa/bb/x.jpg"},
    "sample": {"url": "https://static1.e621.net/data/sample/aa/bb/x.jpg"},
    "tags": {"general": ["cat"], "species": ["felid"], "artist": ["someone"]},
    "rating": "s",
}


def test_new_format_list_response_is_parsed():
    out = _run("e621", [NEW_POST, "junk"])
    assert [p["id"] for p in out] == [6870384]


def test_new_format_urls_and_tags():
    a = get_adapter("e621")
    assert a.get_file_url(NEW_POST) == "https://static1.e621.net/data/a2/87/a287.webm"
    assert a.get_preview_url(NEW_POST) == "https://static1.e621.net/data/preview/a2/87/a287.jpg"
    assert a.get_sample_url(NEW_POST) == "https://static1.e621.net/data/sample/a2/87/a287.jpg"
    assert a.get_tags(NEW_POST) == ["blue_eyes", "hi_res", "dastik228"]
    assert a.get_categorized_tags(NEW_POST)["general"] == ["blue_eyes", "hi_res", "dastik228"]


def test_old_format_still_works():
    a = get_adapter("e621")
    assert [p["id"] for p in _run("e621", {"posts": [OLD_POST]})] == [1]
    assert a.get_file_url(OLD_POST) == "https://static1.e621.net/data/aa/bb/x.png"
    assert a.get_preview_url(OLD_POST) == "https://static1.e621.net/data/preview/aa/bb/x.jpg"
    assert a.get_sample_url(OLD_POST) == "https://static1.e621.net/data/sample/aa/bb/x.jpg"
    assert sorted(a.get_tags(OLD_POST)) == ["cat", "felid", "someone"]
    assert a.get_categorized_tags(OLD_POST)["artist"] == ["someone"]
