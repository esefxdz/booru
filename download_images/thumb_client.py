"""
download_images/thumb_client.py — Lightweight thumbnail HTTP client.

Why this exists
---------------
Thumbnail CDN servers (e.g. img3.gelbooru.com, img1.safebooru.org) are plain
static file servers sitting behind Cloudflare.  Once the main BypassSession has
solved the CF challenge and obtained a ``cf_clearance`` cookie, CDN requests
only need that cookie — they do NOT need TLS impersonation, JS challenge
solving, or the full curl_cffi / cloudscraper stack.

Using a single persistent ``httpx.AsyncClient`` with the CF cookie lets us:
  • Reuse a warm HTTP/2 connection pool (no per-request TLS handshake)
  • Fire 20+ concurrent thumbnail requests safely
  • Look exactly like a real browser tab loading images

The client is created lazily on first use and recreated automatically whenever
the CF cookies for a booru change (e.g. after a new bypass session).

Public API
----------
    thumb_fetch(url, booru, timeout) -> BypassResponse | None
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("thumb_client")


class _LightResponse:
    """Minimal response wrapper compatible with what thumbnails._fetch_raw expects."""
    __slots__ = ("status_code", "content", "text")

    def __init__(self, resp):
        self.status_code = resp.status_code
        self.content = resp.content
        self.text = resp.text


# ---------------------------------------------------------------------------
# Per-booru client registry
# ---------------------------------------------------------------------------
# Maps booru_name → (fingerprint, httpx.AsyncClient)
# Recreated if cookies, HTTP/2, or proxy settings change.
_clients: dict[str, tuple[str, object]] = {}
_client_lock: asyncio.Lock | None = None
_client_lock_loop_id: int | None = None  # id() of the loop that owns _client_lock


def _make_client_fp(cookies: dict, use_http2: bool, proxy_url: str) -> str:
    """Fingerprint that captures every setting that affects client construction.

    If any of these change the cached client is discarded and rebuilt so
    settings toggles (HTTP/2, proxy) take effect immediately.
    """
    cookie_part = ",".join(f"{k}={v}" for k, v in sorted(cookies.items()))
    return f"{cookie_part}|h2={int(use_http2)}|px={proxy_url or ''}"


async def _loop_lock() -> asyncio.Lock:
    """Return the module-level lock, creating it on the current event loop.

    If the existing lock was created on a different event loop (e.g. by a
    background thread that has since exited), it is discarded and a fresh
    lock is created on the current loop.  This makes ``close_all()`` safe
    to call from ``asyncio.run()`` at shutdown.
    """
    global _client_lock, _client_lock_loop_id

    try:
        current_loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        current_loop_id = -1  # no running loop

    if _client_lock is not None and _client_lock_loop_id != current_loop_id:
        # Lock was created on a different (possibly dead) loop — replace it
        _client_lock = None
        _client_lock_loop_id = None

    if _client_lock is None:
        _client_lock = asyncio.Lock()
        _client_lock_loop_id = current_loop_id

    return _client_lock


async def _get_client(booru: str, cookies: dict, use_http2: bool, proxy_url: str):
    """Return a live httpx.AsyncClient for *booru*, creating or replacing it as needed.

    Serialised by the module-level asyncio.Lock so concurrent fetches for the
    same booru do not race when cookies change or the client is first created.
    """
    import httpx
    from cloudflare_bypasser import store as cf_store
    from ui import settings_view as settings

    lock = await _loop_lock()
    async with lock:
        fp = _make_client_fp(cookies, use_http2, proxy_url)
        existing = _clients.get(booru)
        if existing is not None:
            old_fp, client = existing
            if old_fp == fp:
                return client
            # Settings or cookies changed — close the old client and rebuild
            try:
                await client.aclose()
            except Exception:
                pass

        # ── Per-host connection limit tracks the user's concurrency setting ──
        max_dl = getattr(settings.manager, "concurrent_downloads", 50)
        per_host = max(8, min(max_dl, 32))  # clamp to [8, 32] — below 8 is sluggish, above 32 risks CF blocks

        image_headers = {
            "User-Agent": cf_store.get_user_agent(booru) or (
                settings.manager.get_user_agent()
            ),
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
        }

        client = httpx.AsyncClient(
            http2=use_http2,
            follow_redirects=True,
            cookies=cookies or None,
            proxy=proxy_url or None,
            headers=image_headers,
            limits=httpx.Limits(
                max_connections=per_host * 5,        # 5 hosts' worth of headroom
                max_keepalive_connections=per_host,  # concurrent fetches per CDN host
                keepalive_expiry=30,
            ),
            timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=10.0),
        )
        _clients[booru] = (fp, client)
        log.debug("thumb_client: new httpx client for %s (http2=%s, cookies=%d)", booru, use_http2, len(cookies))
        return client


async def thumb_fetch(url: str, booru: str = "unknown", timeout: float = 10.0):
    """
    Fetch a thumbnail URL with the lightweight persistent client.

    Returns a BypassResponse-compatible object on success, or None on failure.
    Callers should fall back to the heavy BypassSession on None or non-200.
    """
    try:
        from cloudflare_bypasser import store as cf_store
        from ui import settings_view as settings

        cookies = cf_store.get_cookies(booru) or {}
        use_http2 = getattr(settings.manager, "use_http2", False)
        proxy_url = getattr(settings.manager, "proxy_url", "")

        client = await _get_client(booru, cookies, use_http2, proxy_url)

        resp = await client.get(url, timeout=timeout)

        if resp.status_code != 200:
            log.debug("thumb_client: bad status %d for %s", resp.status_code, url)
            return None

        # Don't gate on Content-Type — some CDNs omit it, return unusual
        # values, or use mixed case.  The caller (_fetch_raw) validates
        # the actual bytes with _is_image() which catches HTML/error pages
        # reliably.  Rejecting here just forces an unnecessary slow-path
        # fallback to the heavy bypass engine.
        return _LightResponse(resp)

    except Exception as e:
        log.debug("thumb_client: fetch failed for %s: %s", url, e)
        return None


async def close_all():
    """Close all cached clients — call at app shutdown.

    Safe to call even when no clients were ever created.  Uses the module
    lock to prevent races with in-flight ``_get_client`` calls (though at
    shutdown the app should already have cancelled all fetches).
    """
    lock = await _loop_lock()
    async with lock:
        for booru, (_, client) in list(_clients.items()):
            try:
                await client.aclose()
            except Exception:
                pass
        _clients.clear()
