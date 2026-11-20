"""Lightweight httpx client for thumbnail CDNs; needs only the stored cf_clearance cookie, not the full bypass stack."""

from __future__ import annotations

import logging

log = logging.getLogger("thumb_client")


class _LightResponse:
    """Minimal response wrapper for thumbnails._fetch_raw."""
    __slots__ = ("status_code", "content", "text")

    def __init__(self, resp):
        self.status_code = resp.status_code
        self.content = resp.content
        self.text = resp.text


# booru -> (fingerprint, client); rebuilt when cookies, HTTP/2 or proxy change.
_clients: dict[str, tuple[str, object]] = {}

# booru -> monotonic expiry; lets callers skip the lightweight client after a failure.
_lightweight_blocked: dict[str, float] = {}
_BLOCKED_TTL = 60.0  # seconds


def _make_client_fp(cookies: dict, use_http2: bool, proxy_url: str) -> str:
    """Fingerprint of everything that affects client construction."""
    cookie_part = ",".join(f"{k}={v}" for k, v in sorted(cookies.items()))
    return f"{cookie_part}|h2={int(use_http2)}|px={proxy_url or ''}"


async def _get_client(booru: str, cookies: dict, use_http2: bool, proxy_url: str):
    """Cached client for *booru*, or a new one. Lock-free: a creation race just replaces the entry."""
    import httpx
    from cloudflare_bypasser import store as cf_store
    from core import settings

    fp = _make_client_fp(cookies, use_http2, proxy_url)

    existing = _clients.get(booru)
    if existing is not None:
        old_fp, client = existing
        if old_fp == fp:
            return client
        try:
            await client.aclose()
        except Exception:
            pass

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
        # No client-level cookies (they would go to every host); thumb_fetch adds them same-site only.
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
    """Fetch with the lightweight client; returns a _LightResponse, or None (callers fall back to the bypass session).

    *extra_cookies* are merged over the stored bypass cookies.
    """
    try:
        from cloudflare_bypasser import store as cf_store
        from core import settings

        cookies = dict(cf_store.get_cookies(booru) or {})
        if extra_cookies:
            cookies.update(extra_cookies)
        use_http2 = getattr(settings.manager, "use_http2", False)
        import boorus
        from core.proxy import effective_proxy
        proxy_url = effective_proxy(boorus.REGISTRY.get(booru, {}).get("url", ""))

        client = await _get_client(booru, cookies, use_http2, proxy_url)

        from core.validation import same_site
        import boorus
        site_url = boorus.REGISTRY.get(booru, {}).get("url", "")
        req_headers = None
        if cookies and same_site(url, site_url):
            req_headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}

        resp = await client.get(url, timeout=timeout, headers=req_headers)

        if resp.status_code != 200:
            log.debug("thumb_client: bad status %d for %s", resp.status_code, url)
            mark_lightweight_blocked(booru)
            return None

        # Content-Type isn't checked; the caller validates the bytes.
        return _LightResponse(resp)

    except Exception as e:
        log.debug("thumb_client: fetch failed for %s: %s", url, e)
        mark_lightweight_blocked(booru)
        return None


async def close_all():
    for _, (__, client) in list(_clients.items()):
        try:
            await client.aclose()
        except Exception:
            pass
    _clients.clear()
    _lightweight_blocked.clear()


def is_lightweight_blocked(booru: str) -> bool:
    import time
    expiry = _lightweight_blocked.get(booru, 0)
    return time.monotonic() < expiry


def mark_lightweight_blocked(booru: str) -> None:
    import time
    _lightweight_blocked[booru] = time.monotonic() + _BLOCKED_TTL
