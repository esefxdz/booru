"""search_posts tolerates malformed API payloads."""
import asyncio

from adapters import get_adapter
from download_images.api_client import search_posts


class _Resp:
    status_code = 200
    is_blocked = False

    def __init__(self, data):
        self._data = data
        self.text = ""

    def json(self):
        return self._data


def _run(api_type, payload):
    async def fetch(url, params=None):
        return _Resp(payload)
    site = {"url": "https://example.com", "api_path": "/index.php", "post_key": None, "api_type": api_type}
    return asyncio.run(search_posts(get_adapter(api_type), site, fetch, "tag", 10))


def test_non_dict_entries_dropped():
    out = _run("danbooru", [{"id": 1}, "junk", 5, None, ["x"], {"id": 2}])
    assert [p["id"] for p in out] == [1, 2]


def test_single_object_post_wrapped():
    assert _run("gelbooru", {"post": {"id": 9}}) == [{"id": 9}]


def test_wrong_shape_gives_empty_list():
    assert _run("e621", {"posts": "nope"}) == []
