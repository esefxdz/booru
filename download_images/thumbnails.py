"""
download_images/thumbnails.py — Thumbnail fetching and PIL decoding.

Fetches preview images from booru CDNs, decodes + resizes them using
PIL in a bounded thread pool, caches the result in SQLite, and fires
a callback for each decoded thumbnail so the gallery can update.

Concurrency model
-----------------
The network semaphore throttles the combined network+decode pipeline.
Each coroutine holds its semaphore slot across the HTTP fetch *and* the
PIL decode, so the total number of in-flight images (bytes in RAM +
thread-pool work) stays bounded.

When the user disables the semaphore in settings we still enforce a
fallback cap of 24 concurrent fetches — enough for buttery-smooth
loading without looking like a DDoS to Cloudflare (Chrome's own
per-host limit is also 24).

All callbacks are collected during the gather and flushed in one burst
afterwards so Qt receives every signal before painting → thumbnails
appear in a single frame rather than cascading in waves.  If the gather
itself crashes (e.g. CDN connection reset on Windows) we still flush
whatever thumbnails made it through so the gallery is never empty.

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
        # Even with the user-facing semaphore OFF we MUST cap in-flight
        # HTTP requests.  Without any throttle 50+ connections hit the
        # CDN simultaneously, which looks like a DDoS to Cloudflare —
        # they RST connections and asyncio on Windows/Python 3.13
        # chokes on WinError 995.  24 is Chrome's per-host limit.
        _FALLBACK_LIMIT = 24
        sem = asyncio.Semaphore(_FALLBACK_LIMIT)

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

    # ── Two-phase result collector ─────────────────────────────
    #  Coroutines append results here.  We flush in two waves:
    #    1. A timer fires after ~100 ms and flushes whatever is
    #       ready → instant first paint (feels "snappy").
    #    2. After gather finishes we flush the remainder → final
    #       paint completes the gallery.
    #  Both flushes happen in tight loops so Qt receives signals
    #  in bursty batches rather than a one-by-one cascade.
    results: list = []
    _wave1_done = False

    async def _flush_wave1():
        """Fire callbacks for whatever thumbnails are ready after a short window."""
        nonlocal _wave1_done
        await asyncio.sleep(0.10)  # 100 ms — long enough to batch, short enough to feel instant
        if _wave1_done or _cancelled() or not results:
            return
        _wave1_done = True
        wave = results[:]
        results.clear()
        for img_bytes, post, index in wave:
            try:
                callback(img_bytes, post, index)
            except Exception:
                log.exception("[thumbnails] wave-1 callback error for post %s", post.get("id"))

    # ── Per-post coroutine ─────────────────────────────────────────
    async def fetch_one(post, index):
        if _cancelled():
            return

        post_id   = post.get("id")
        booru     = post.get("_booru", "unknown")
        cache_key = f"{booru}:{post_id}"

        # 1. Cache check (instant on L1 hit, single SQLite row on L2 hit)
        cached = thumb_cache.get(cache_key)
        if cached is not None:
            results.append((cached, post, index))
            return

        # 2. Resolve preview URL
        url = adapter.get_preview_url(post)
        if not url:
            return
        if url.startswith("//"):
            url = "https:" + url

        # 3. Process with concurrency limit (network + CPU combined)
        # Wrapping both in the semaphore ensures we don't fetch 50 images
        # instantly and then hold them all in memory while 4 CPU cores
        # slowly decode them.
        async with sem:
            if _cancelled():
                return
            
            # --- NETWORK ---
            try:
                raw = await _fetch_raw(url, booru)
            except Exception as exc:
                log.error("[thumbnails] fetch error for post %s: %s", post_id, exc)
                return

            if raw is None or _cancelled():
                return

            # --- CPU DECODE + CACHE (all off the event loop) ---
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
                # SQLite write happens on the worker thread — never blocks the event loop
                thumb_cache.put(cache_key, img_bytes)
                return img_bytes

            try:
                img_bytes = await loop.run_in_executor(_DECODE_EXECUTOR, _decode_and_cache)
            except Exception as exc:
                log.error("[thumbnails] decode error for post %s: %s", post_id, exc)
                return

            results.append((img_bytes, post, index))

    # ── Launch the wave-1 timer alongside the gather ────────────
    wave1_task = asyncio.ensure_future(_flush_wave1())

    try:
        await asyncio.gather(*(fetch_one(post, i) for i, post in enumerate(posts)))
    except Exception:
        # If the event loop hit a low-level error (e.g. WinError 995
        # from a CDN connection reset), we still flush whatever
        # thumbnails made it through so the gallery isn't empty.
        log.exception("[thumbnails] gather crashed — flushing partial results")
    finally:
        wave1_task.cancel()
        try:
            await wave1_task
        except (asyncio.CancelledError, Exception):
            pass

    # ── Wave 2: flush any thumbnails that arrived after wave 1 ──
    if not _cancelled() and results:
        for img_bytes, post, index in results:
            try:
                callback(img_bytes, post, index)
            except Exception:
                log.exception("[thumbnails] wave-2 callback error for post %s", post.get("id"))
