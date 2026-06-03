"""
download_images/thumbnails.py — Thumbnail fetching and PIL decoding.

Fetches preview images from booru CDNs, decodes + resizes them using
PIL in a bounded thread pool, caches the result in SQLite, and fires
a callback for each decoded thumbnail so the gallery can update.

Concurrency
-----------
* HTTP requests are limited to ``_MAX_CONCURRENT`` simultaneous connections
  per search via ``asyncio.Semaphore``.  Firing all 50 requests at once
  against a single CDN triggers rate-limiting or temporary IP bans.
* PIL decoding is CPU-bound and runs in a ``ThreadPoolExecutor`` capped at
  4 workers so it cannot flood the GIL or spike the CPU.

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
import threading
from io import BytesIO

from PIL import Image

from ui import settings_view as settings
import thumb_cache


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Decode thread pool                                                 ║
# ║  Caps at 4 threads to prevent CPU spikes when fetching 50+ thumbs. ║
# ║  PIL image decoding is CPU-bound — keeping it off the event loop    ║
# ║  ensures the Qt UI stays responsive.                                ║
# ╚══════════════════════════════════════════════════════════════════════╝

_DECODE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="thumb_decode"
)

# Max simultaneous HTTP requests to a single CDN host per search.
# Keeps us well below booru rate-limit thresholds.
_MAX_CONCURRENT = 8


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  fetch_previews — concurrent thumbnail download + decode pipeline   ║
# ║                                                                     ║
# ║  For each post:                                                     ║
# ║    1. Check the SQLite cache → callback immediately if hit          ║
# ║    2. HTTP GET the preview URL via the bypass session               ║
# ║    3. Decode + resize in a thread pool (PIL is CPU-bound)           ║
# ║    4. Store in cache, fire callback with JPEG bytes                 ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def fetch_previews(posts, adapter, fetch_fn, callback, cancel_event: threading.Event | None = None):
    """Fetch and decode thumbnails for a list of posts.

    Parameters
    ----------
    posts : list[dict]
        Post dicts to fetch thumbnails for.
    adapter : BaseAdapter
        The booru adapter (used to resolve preview URLs).
    fetch_fn : async callable
        ``async fn(url, timeout=...) -> response`` — the HTTP fetcher.
    callback : callable
        ``fn(img_bytes, post, index)`` — called for each decoded thumb.
    cancel_event : threading.Event, optional
        When set, outstanding coroutines return immediately without
        making network requests or firing the callback.
    """
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(_MAX_CONCURRENT)

    def _cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    async def fetch_one(post, index):
        if _cancelled():
            return

        post_id = post.get("id")
        booru   = post.get("_booru", "unknown")
        cache_key = f"{booru}:{post_id}"

        # ── Cache check ──────────────────────────────────────────
        cached = thumb_cache.get(cache_key)
        if cached is not None:
            if not _cancelled():
                callback(cached, post, index)
            return

        # ── Resolve URL ──────────────────────────────────────────
        url = adapter.get_preview_url(post)
        if not url:
            return
        if url.startswith("//"):
            url = "https:" + url

        # ── Fetch + decode (rate-limited by semaphore) ───────────
        async with sem:
            if _cancelled():
                return
            try:
                r = await fetch_fn(url, timeout=10.0)
                if r.status_code != 200:
                    logging.error(f"[thumbnails] Fetch failed: HTTP {r.status_code} for {url}")
                    return
                raw = r.content if hasattr(r, "content") else r.text.encode()

                def decode():
                    img = Image.open(BytesIO(raw))
                    img.thumbnail(
                        (settings.manager.thumbnail_size, settings.manager.thumbnail_size),
                        Image.LANCZOS,
                    )
                    if img.mode in ("RGBA", "LA", "P"):
                        img = img.convert("RGB")
                    buf = BytesIO()
                    img.save(buf, format="JPEG", quality=85)
                    return buf.getvalue()

                img_bytes = await loop.run_in_executor(_DECODE_EXECUTOR, decode)

                # ── Cache + callback ─────────────────────────────
                if not _cancelled():
                    thumb_cache.put(cache_key, img_bytes)
                    callback(img_bytes, post, index)
            except Exception as e:
                logging.error(f"[thumbnails] Error for post {post_id}: {e}")

    await asyncio.gather(*(fetch_one(post, i) for i, post in enumerate(posts)))
