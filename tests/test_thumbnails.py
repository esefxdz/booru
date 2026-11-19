"""Preview fetching: URL guard and decompression-bomb cap."""
import asyncio
from io import BytesIO

from PIL import Image

from download_images import thumbnails


class _Resp:
    status_code = 200

    def __init__(self, content):
        self.content = content


class _Adapter:
    def __init__(self, url):
        self.url = url

    def get_preview_url(self, post):
        return self.url


def _png(w, h):
    buf = BytesIO()
    Image.new("L", (w, h), 0).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _run(preview_url, payload, booru="safebooru"):
    import uuid
    requested, got = [], []

    async def fetch(url, timeout=None, booru=None):
        requested.append(url)
        return _Resp(payload)

    post = {"id": uuid.uuid4().hex[:12], "_booru": booru}   # unique: avoid thumb-cache hits
    asyncio.run(thumbnails.fetch_previews([post], _Adapter(preview_url), fetch,
                                          lambda img, p, i: got.append(img)))
    return requested, got


def test_normal_preview_is_decoded():
    requested, got = _run("https://safebooru.org/thumbnails/1/x.png", _png(300, 200))
    assert requested and len(got) == 1


def test_decompression_bomb_is_refused():
    bomb = _png(8000, 8000)          # 64 Mpx, only a few KB on the wire
    assert len(bomb) < 200_000
    requested, got = _run("https://safebooru.org/thumbnails/2/bomb.png", bomb)
    assert requested and got == []


def test_relative_preview_resolved_against_booru():
    requested, _ = _run("/thumbnails/3/x.png", _png(10, 10))
    assert requested == ["https://safebooru.org/thumbnails/3/x.png"]


def test_file_scheme_preview_never_fetched():
    requested, got = _run("file:///C:/Windows/win.ini", _png(10, 10))
    assert requested == [] and got == []


def test_huge_jpeg_is_shrunk_by_draft_not_refused():
    buf = BytesIO()
    Image.new("RGB", (8000, 6000), (10, 120, 200)).save(buf, format="JPEG", quality=50)
    big = buf.getvalue()            # 48 Mpx, over the cap before draft
    requested, got = _run("https://safebooru.org/thumbnails/4/big.jpg", big)
    assert requested and len(got) == 1
    assert Image.open(BytesIO(got[0])).width <= 300
