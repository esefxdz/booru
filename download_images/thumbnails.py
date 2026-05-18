"""
download_images/thumbnails.py — Thumbnail fetching and PIL decoding.

Fetches preview images from booru CDNs, decodes + resizes them using
PIL in a bounded thread pool, caches the result in SQLite, and fires
a callback for each decoded thumbnail so the gallery can update.
"""

import asyncio
import concurrent.futures
from io import BytesIO

from PIL import Image

from ui import settings_view as settings
import thumb_cache


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Decode thread pool                                                 ║
# ║  Caps at 4 threads to prevent CPU spikes when fetching 50+ thumbs. ║
# ║  PIL image decoding is CPU-bound — keeping it off the event loop    ║
# ║  ensures the Qt UI stays responsive at 60 FPS.                      ║
# ╚══════════════════════════════════════════════════════════════════════╝

_DECODE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="thumb_decode"
)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  fetch_previews — concurrent thumbnail download + decode pipeline   ║
# ║                                                                     ║
# ║  For each post:                                                     ║
# ║    1. Check the SQLite cache → callback immediately if hit          ║
# ║    2. HTTP GET the preview URL via the bypass session               ║
# ║    3. Decode + resize in a thread pool (PIL is CPU-bound)           ║
# ║    4. Store in cache, fire callback with JPEG bytes                 ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def fetch_previews(posts, adapter, fetch_fn, callback):
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
    """
    loop = asyncio.get_running_loop()

    async def fetch_one(post, index):
        post_id = post.get("id")

        # ── Cache check ──────────────────────────────────────────
        cached = thumb_cache.get(post_id)
        if cached is not None:
            callback(cached, post, index)
            return

        # ── Resolve URL ──────────────────────────────────────────
        url = adapter.get_preview_url(post)
        if not url:
            return
        if url.startswith("//"):
            url = "https:" + url

        # ── Fetch + decode ───────────────────────────────────────
        try:
            r = await fetch_fn(url, timeout=10.0)
            if r.status_code != 200:
                print(f"[thumbnails] Fetch failed: HTTP {r.status_code} for {url}")
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

            # ── Cache + callback ─────────────────────────────────
            thumb_cache.put(post_id, img_bytes)
            callback(img_bytes, post, index)
        except Exception as e:
            print(f"[thumbnails] Error for post {post_id}: {e}")

    await asyncio.gather(*(fetch_one(post, i) for i, post in enumerate(posts)))
