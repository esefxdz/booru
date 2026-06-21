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
    thumb_fetch(url, booru, timeout) -> _LightResponse | None
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


def _make_client_fp(cookies: dict, use_http2: bool, proxy_url: str) -> str:
    """Fingerprint that captures all settings that affect client construction."""
    cookie_part = ",".join(f"{k}={v}" for k, v in sorted(cookies.items()))
    return f"{cookie_part}|h2={int(use_http2)}|px={proxy_url or ''}"


async def _get_client(booru: str, cookies: dict, use_http2: bool, proxy_url: str):
    """Return the cached httpx.AsyncClient for *booru*, or create one.

    Lock-free — the hot path is a dict lookup + string compare.  The
    rare race where two coroutines create clients simultaneously is
    harmless (the second just replaces the first in the dict).
    """
    import httpx
    from cloudflare_bypasser import store as cf_store
    from ui import settings_view as settings

    fp = _make_client_fp(cookies, use_http2, proxy_url)

    # ── Hot path: cached client, matching fingerprint ──────────
    existing = _clients.get(booru)
    if existing is not None:
        old_fp, client = existing
        if old_fp == fp:
            return client
        # Stale — close and fall through to rebuild
        try:
            await client.aclose()
        except Exception:
            pass

    # ── Build a new client ─────────────────────────────────────
    max_dl = getattr(settings.manager, "concurrent_downloads", 50)
    per_host = max(8, min(max_dl, 32))

    referer = ""
    try:
        import boorus
        info = boorus.REGISTRY.get(booru, {})
        base = info.get("url", "")
        if base:
            referer = base.rstrip("/") + "/"
    except Exception:
        pass

    image_headers = {
        "User-Agent": cf_store.get_user_agent(booru) or settings.manager.get_user_agent(),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    }
    if referer:
        image_headers["Referer"] = referer

    client = httpx.AsyncClient(
        http2=use_http2,
        follow_redirects=True,
        cookies=cookies or None,
        proxy=proxy_url or None,
        headers=image_headers,
        limits=httpx.Limits(
            max_connections=per_host * 5,
            max_keepalive_connections=per_host,
            keepalive_expiry=30,
        ),
        timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=10.0),
    )
    _clients[booru] = (fp, client)
    log.debug("thumb_client: new httpx client for %s (http2=%s, cookies=%d)", booru, use_http2, len(cookies))
    return client


async def thumb_fetch(url: str, booru: str = "unknown", timeout: float = 10.0, *, extra_cookies: dict | None = None):
    """
    Fetch a thumbnail URL with the lightweight persistent client.

    Returns a _LightResponse on success, or None on failure.
    Callers should fall back to the heavy BypassSession on None or non-200.

    Parameters
    ----------
    extra_cookies : dict | None
        Additional cookies merged on top of stored bypass cookies.
        Callers pass the API session's accumulated cookies so the
        lightweight client benefits from warmup/session cookies.
    """
    try:
        from cloudflare_bypasser import store as cf_store
        from ui import settings_view as settings

        cookies = dict(cf_store.get_cookies(booru) or {})
        if extra_cookies:
            cookies.update(extra_cookies)
        use_http2 = getattr(settings.manager, "use_http2", False)
        proxy_url = getattr(settings.manager, "proxy_url", "")

        client = await _get_client(booru, cookies, use_http2, proxy_url)

        resp = await client.get(url, timeout=timeout)

        if resp.status_code != 200:
            log.debug("thumb_client: bad status %d for %s", resp.status_code, url)
            return None

        # Don't gate on Content-Type — the caller validates bytes with _is_image()
        return _LightResponse(resp)

    except Exception as e:
        log.debug("thumb_client: fetch failed for %s: %s", url, e)
        return None


async def close_all():
    """Close all cached clients — call at app shutdown."""
    for _, (__, client) in list(_clients.items()):
        try:
            await client.aclose()
        except Exception:
            pass
    _clients.clear()
