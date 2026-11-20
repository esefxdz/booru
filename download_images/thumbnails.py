"""Thumbnail fetch and decode pipeline; the network semaphore gates only the HTTP fetch, decoding runs outside it."""

import logging
import asyncio
import concurrent.futures
import os
import threading
from io import BytesIO

from PIL import Image

from core import settings
from storage import thumb_cache

log = logging.getLogger(__name__)


# PIL decoding is CPU-bound; keep it off the event loop.

_DECODE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=(os.cpu_count() or 4), thread_name_prefix="thumb_decode"
)


# Refuse to decode previews over 40 Mpx (~160 MB as RGBA); real ones are under 1 Mpx.
MAX_THUMB_SOURCE_PIXELS = 40_000_000


def _safe_preview_url(url: str, booru: str) -> str:
    """Resolve against the booru; "" unless http(s)."""
    if not url:
        return ""
    from core.validation import ValidationError, require_http_url
    import boorus
    try:
        return require_http_url(url, boorus.REGISTRY.get(booru, {}).get("url"))
    except ValidationError as e:
        log.warning("[thumbnails] ignoring preview URL: %s", e)
        return ""


def _is_image(data: bytes | None) -> bool:
    """True only if *data* starts with a known image signature (CDNs sometimes send HTML with 200)."""
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
    # WebP: RIFF....WEBP
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return True
    # AVIF/HEIC: box size at 4-7, 'ftyp' at 8-11
    if len(data) >= 12 and data[4:8] in (
        b'\x00\x00\x00\x18',  # size=24
        b'\x00\x00\x00\x1c',  # size=28
        b'\x00\x00\x00\x20',  # size=32
        b'\x00\x00\x00\x24',  # size=36
    ) and data[8:12] == b'ftyp':
        return True
    return False


async def fetch_previews(
    posts,
    adapter,
    fetch_fn,
    callback,
    cancel_event: threading.Event | None = None,
    thumb_fetch_fn=None,
):
    """Fetch and decode thumbnails, calling ``callback(img_bytes, post, index)`` per post.

    The callback runs on the asyncio thread and must be thread-safe w.r.t. Qt signals.
    *thumb_fetch_fn* (lightweight) is tried first, then *fetch_fn* (bypass); setting
    *cancel_event* aborts before network access and suppresses callbacks.
    """
    loop = asyncio.get_running_loop()

    max_conn = getattr(settings.manager, "concurrent_downloads", 16)
    use_sem  = getattr(settings.manager, "use_network_semaphore", True)

    if use_sem:
        sem = asyncio.Semaphore(max_conn)
    else:
        # httpx's per-host connection limit is enough throttling.
        class _NoSem:
            async def __aenter__(self): pass
            async def __aexit__(self, *_): pass
        sem = _NoSem()

    def _cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    async def _fetch_raw(url: str, booru: str) -> bytes | None:
        from download_images.thumb_client import is_lightweight_blocked
        if thumb_fetch_fn is not None and not is_lightweight_blocked(booru):
            try:
                r = await thumb_fetch_fn(url, timeout=10.0, booru=booru)
                if r is not None and r.status_code == 200:
                    data = r.content if hasattr(r, "content") else None
                    if _is_image(data):
                        return data
                    # 200 but not an image (challenge page): fall through.
                    log.debug("[thumbnails] lightweight client returned non-image for %s", url)
            except Exception as exc:
                log.debug("[thumbnails] lightweight client error for %s: %s", url, exc)

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

    async def fetch_one(post, index):
        if _cancelled():
            return

        post_id   = post.get("id")
        booru     = post.get("_booru", "unknown")
        cache_key = f"{booru}:{post_id}"

        cached = thumb_cache.get(cache_key)
        if cached is not None:
            if not _cancelled():
                callback(cached, post, index)
            return

        url = _safe_preview_url(adapter.get_preview_url(post), booru)
        if not url:
            return

        # The slot is released once bytes arrive; decoding runs outside it.
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

        def _decode_and_cache() -> bytes:
            img = Image.open(BytesIO(raw))      # reads the header only
            size = settings.manager.thumbnail_size
            img.draft("RGB", (size, size))      # JPEG: decode at reduced size
            # Checked after draft(): big JPEGs still decode, PNG bombs are refused.
            if img.width * img.height > MAX_THUMB_SOURCE_PIXELS:
                raise ValueError(f"preview too large to decode ({img.width}x{img.height})")
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

        if not _cancelled():
            callback(img_bytes, post, index)

    await asyncio.gather(*(fetch_one(post, i) for i, post in enumerate(posts)))
