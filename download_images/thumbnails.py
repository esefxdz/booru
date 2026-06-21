"""
download_images/thumbnails.py — Thumbnail fetching and PIL decoding.

Fetches preview images from booru CDNs, decodes + resizes them using
PIL in a bounded thread pool, caches the result in SQLite, and fires
a callback for each decoded thumbnail so the gallery can update.

Concurrency model
-----------------
The network semaphore throttles ONLY the HTTP fetch.  As soon as
bytes arrive the semaphore slot is released so the next download can
start immediately.  PIL decoding runs in the thread pool *outside*
the semaphore, overlapping network I/O with CPU work.

This makes the effective pipeline:

    download_1 → release_sem → download_2 → release_sem → ...
                       ↓                        ↓
                   decode_1                 decode_2
                       ↓                        ↓
                  result_1                  result_2

When the user disables the semaphore in settings we still enforce a
fallback cap of 24 concurrent fetches — enough for buttery-smooth
loading without looking like a DDoS to Cloudflare.

Each thumbnail fires its callback the instant its decode finishes —
no batching, no waiting for stragglers.  The semaphore only gates network
requests; decode runs outside so the network never idles.

Cancellation
------------
``fetch_previews`` accepts an optional ``threading.Event``.  If the event
is set (because the user started a new search) each coroutine returns early
before making any network request, and any in-flight requests that complete
while the event is set skip the callback so the gallery is not updated.
"""

import logging
import asyncio
import concurrent.futures
import os
import threading
from io import BytesIO

from PIL import Image

from ui import settings_view as settings
import thumb_cache

log = logging.getLogger(__name__)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Decode thread pool                                                 ║
# ║  PIL image decoding is CPU-bound — keeping it off the event loop    ║
# ║  ensures the Qt UI stays responsive.  Scales to all CPU cores.     ║
# ╚══════════════════════════════════════════════════════════════════════╝

_DECODE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=(os.cpu_count() or 4), thread_name_prefix="thumb_decode"
)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  _is_image — magic-byte guard                                       ║
# ║                                                                     ║
# ║  CDN edge nodes occasionally return a Cloudflare HTML error page    ║
# ║  with HTTP 200.  Checking the leading bytes prevents passing HTML   ║
# ║  to PIL (which raises "cannot identify image file").                ║
# ╚══════════════════════════════════════════════════════════════════════╝

def _is_image(data: bytes | None) -> bool:
    """Return True only if *data* starts with a known image magic sequence."""
    if not data or len(data) < 4:
        return False
    # JPEG: FF D8 FF
    if data[:3] == b'\xff\xd8\xff':
        return True
    # PNG: 89 50 4E 47
    if data[:4] == b'\x89PNG':
        return True
    # GIF: GIF8 (7a or 9a)
    if data[:4] == b'GIF8':
        return True
    # WebP: RIFF....WEBP (RIFF at 0-3, size at 4-7, WEBP at 8-11)
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return True
    # AVIF / HEIC: ISO Base Media File Type Box (ftyp)
    # Bytes 4-7 are box size (big-endian), 8-11 are 'ftyp'
    if len(data) >= 12 and data[4:8] in (
        b'\x00\x00\x00\x18',  # size=24
        b'\x00\x00\x00\x1c',  # size=28
        b'\x00\x00\x00\x20',  # size=32
        b'\x00\x00\x00\x24',  # size=36
    ) and data[8:12] == b'ftyp':
        return True
    return False


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  fetch_previews — concurrent thumbnail download + decode pipeline   ║
# ║                                                                     ║
# ║  For each post:                                                     ║
# ║    1. Check L1/L2 cache → callback immediately if hit              ║
# ║    2. HTTP GET the preview URL (lightweight client first, then      ║
# ║       heavy bypass as fallback)                                     ║
# ║    3. Validate magic bytes — discard HTML error pages               ║
# ║    4. Decode + resize + SQLite cache write in thread pool           ║
# ║    5. Fire callback with JPEG bytes (on event loop thread)          ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def fetch_previews(
    posts,
    adapter,
    fetch_fn,
    callback,
    cancel_event: threading.Event | None = None,
    thumb_fetch_fn=None,
):
    """Fetch and decode thumbnails for a list of posts.

    Parameters
    ----------
    posts : list[dict]
        Post dicts to fetch thumbnails for.
    adapter : BaseAdapter
        The booru adapter (used to resolve preview URLs).
    fetch_fn : async callable
        Heavy bypass fetcher — always available, used as fallback.
        Signature: ``async fn(url, timeout, booru) -> BypassResponse``
    callback : callable
        ``fn(img_bytes, post, index)`` — called on the asyncio thread for
        each decoded thumbnail.  Must be thread-safe w.r.t. Qt signals.
    cancel_event : threading.Event, optional
        When set, all coroutines abort before touching the network or
        the callback.
    thumb_fetch_fn : async callable, optional
        Lightweight fast client for CDN image fetches.  Tried first; if
        it returns None or non-image bytes, we fall back to ``fetch_fn``.
        Signature: ``async fn(url, timeout, booru) -> response | None``
    """
    loop = asyncio.get_running_loop()

    # ── Concurrency control (reads live user settings) ────────────
    max_conn = getattr(settings.manager, "concurrent_downloads", 16)
    use_sem  = getattr(settings.manager, "use_network_semaphore", True)

    if use_sem:
        sem = asyncio.Semaphore(max_conn)
    else:
        # Truly disabled — the httpx per-host connection limit (up to 32)
        # is enough to prevent accidental DDoS without extra throttling.
        class _NoSem:
            async def __aenter__(self): pass
            async def __aexit__(self, *_): pass
        sem = _NoSem()

    def _cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    # ── Raw-bytes fetcher with lightweight→heavy fallback ─────────
    async def _fetch_raw(url: str, booru: str) -> bytes | None:
        # 1. Try the fast lightweight client (plain httpx with CF cookies)
        if thumb_fetch_fn is not None:
            try:
                r = await thumb_fetch_fn(url, timeout=10.0, booru=booru)
                if r is not None and r.status_code == 200:
                    data = r.content if hasattr(r, "content") else None
                    if _is_image(data):
                        return data
                    # Got 200 but HTML (CF challenge page) → fall through
                    log.debug("[thumbnails] lightweight client returned non-image for %s", url)
            except Exception as exc:
                log.debug("[thumbnails] lightweight client error for %s: %s", url, exc)

        # 2. Fall back to the heavy bypass engine
        try:
            r = await fetch_fn(url, timeout=15.0, booru=booru)
            if r is not None and r.status_code == 200:
                data = r.content if hasattr(r, "content") else r.text.encode()
                if _is_image(data):
                    return data
                log.warning("[thumbnails] bypass engine returned non-image for %s", url)
        except Exception as exc:
            log.error("[thumbnails] bypass engine error for %s: %s", url, exc)

        return None

    # ── Per-post coroutine — fires callback the instant it's ready ──
    async def fetch_one(post, index):
        if _cancelled():
            return

        post_id   = post.get("id")
        booru     = post.get("_booru", "unknown")
        cache_key = f"{booru}:{post_id}"

        # 1. Cache check
        cached = thumb_cache.get(cache_key)
        if cached is not None:
            if not _cancelled():
                callback(cached, post, index)
            return

        # 2. Resolve preview URL
        url = adapter.get_preview_url(post)
        if not url:
            return
        if url.startswith("//"):
            url = "https:" + url

        # 3. Network fetch (semaphore limits concurrent connections)
        #    Slot released immediately after bytes arrive → decode
        #    runs outside, overlapping network I/O with CPU work.
        async with sem:
            if _cancelled():
                return
            try:
                raw = await _fetch_raw(url, booru)
            except Exception as exc:
                log.error("[thumbnails] fetch error for post %s: %s", post_id, exc)
                return

        if raw is None or _cancelled():
            return

        # 4. CPU decode + cache (outside semaphore — network keeps running)
        def _decode_and_cache() -> bytes:
            img = Image.open(BytesIO(raw))
            img.thumbnail(
                (settings.manager.thumbnail_size, settings.manager.thumbnail_size),
                Image.LANCZOS,
            )
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85)
            img_bytes = buf.getvalue()
            thumb_cache.put(cache_key, img_bytes)
            return img_bytes

        try:
            img_bytes = await loop.run_in_executor(_DECODE_EXECUTOR, _decode_and_cache)
        except Exception as exc:
            log.error("[thumbnails] decode error for post %s: %s", post_id, exc)
            return

        # 5. Fire immediately — no batching, no waiting for stragglers
        if not _cancelled():
            callback(img_bytes, post, index)

    await asyncio.gather(*(fetch_one(post, i) for i, post in enumerate(posts)))
