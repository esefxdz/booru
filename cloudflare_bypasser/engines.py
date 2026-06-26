"""
cloudflare_bypasser/engines.py — HTTP engine implementations.

Each ``_try_*`` function attempts a single HTTP request using a specific
engine (curl_cffi, cloudscraper, httpx, requests, urllib).  They all
return ``BypassResponse | None`` and never raise — failures are logged
and swallowed so the orchestrator can try the next engine.

Also contains ``BypassResponse`` (the immutable response wrapper) and
``_extract_cookies`` (cross-engine cookie extraction).

Extracted from session.py so the orchestrator stays thin.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.request
import urllib.error
from typing import Optional

from cloudflare_bypasser.fingerprint import (
    _HAS_CURL_CFFI,
    _HAS_CLOUDSCRAPER,
    _HAS_HTTPX,
    _HAS_REQUESTS,
    _IMPERSONATE_TARGETS,
    cffi_requests,
    _cloudscraper,
    httpx,
    _requests_lib,
)

log = logging.getLogger("cloudflare_bypasser")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║                         BypassResponse                              ║
# ╚══════════════════════════════════════════════════════════════════════╝

class BypassResponse:
    """
    Immutable response wrapper.  All data is captured eagerly so the caller
    never holds a dangling reference to a closed socket/session.
    """

    __slots__ = ("content", "text", "status_code", "url", "_json_data", "engine_used", "cookies")

    def __init__(
        self,
        content: bytes,
        text: str,
        status_code: int,
        url: object,
        json_data: object,
        engine_used: str = "unknown",
        cookies: dict | None = None,
    ) -> None:
        self.content = content
        self.text = text
        self.status_code = status_code
        self.url = url
        self._json_data = json_data
        self.engine_used = engine_used
        self.cookies = cookies or {}

    def json(self) -> object:
        if self._json_data is not None:
            return self._json_data
        import json as _json
        return _json.loads(self.text)

    @property
    def is_blocked(self) -> bool:
        """True when the response looks like a Cloudflare challenge page."""
        if self.status_code not in (403, 503, 429):
            return False

        # Quick heuristic: 403 with tiny body is almost certainly a block
        if self.status_code == 403 and len(self.content) < 200:
            return True

        # Check both decoded text and raw bytes (response may be brotli-compressed)
        text_lower = self.text[:4000].lower() if self.text else ""
        content_lower = self.content[:4000].lower() if self.content else b""

        # Detect garbage / undecoded responses — some engines (cloudscraper)
        # return raw compressed bytes as "text" when Content-Encoding
        # (brotli/gzip) fails to decode.
        if self.status_code == 403 and len(self.text) > 50:
            first_char = self.text.strip()[0] if self.text.strip() else ''
            if first_char not in '<{[{"':
                return True

        cf_markers_text = (
            "cf-mitigated", "just a moment",
            "challenge-platform", "challenges.cloudflare.com",
            "checking your browser", "enable javascript",
            "cf-chl-bypass", "cf-chl-out",
            "turnstile", "cf_captcha",
        )
        cf_markers_bytes = (
            b"cf-mitigated", b"just a moment",
            b"challenge-platform", b"challenges.cloudflare.com",
            b"checking your browser", b"enable javascript",
            b"cf-chl-bypass", b"cf-chl-out",
            b"turnstile", b"cf_captcha",
        )

        for marker in cf_markers_text:
            if marker in text_lower:
                return True
        for marker in cf_markers_bytes:
            if marker in content_lower:
                return True

        if "cf-ray" in text_lower and ("challenge" in text_lower or "captcha" in text_lower):
            return True

        if self.status_code == 403 and len(self.content) < 500 and b"cloudflare" in content_lower:
            return True

        return False

    def __repr__(self) -> str:
        return f"<BypassResponse [{self.status_code}] engine={self.engine_used} {self.url}>"


# Keep backward compat alias
_Response = BypassResponse


# ╔══════════════════════════════════════════════════════════════════════╗
# ║                      Cookie extraction                              ║
# ╚══════════════════════════════════════════════════════════════════════╝

def _extract_cookies(resp) -> dict:
    """Extract a plain dict of cookies from any HTTP response object."""
    try:
        # curl_cffi, requests, cloudscraper, httpx all support .cookies
        if hasattr(resp, "cookies"):
            jar = resp.cookies
            if hasattr(jar, "get_dict"):
                return {k: v for k, v in jar.get_dict().items()}
            if hasattr(jar, "items"):
                return {str(k): str(v) for k, v in jar.items()}
            if isinstance(jar, dict):
                return {str(k): str(v) for k, v in jar.items()}
        # urllib / stdlib — parse Set-Cookie header
        if hasattr(resp, "headers"):
            raw = resp.headers.get("Set-Cookie") or resp.headers.get("set-cookie") or ""
            if raw:
                result = {}
                for part in raw.split(";"):
                    part = part.strip()
                    if "=" in part and not any(
                        kw in part.lower()
                        for kw in ("path=", "domain=", "expires=", "max-age=", "secure", "httponly", "samesite")
                    ):
                        k, v = part.split("=", 1)
                        result[k.strip()] = v.strip()
                return result
    except Exception:
        pass
    return {}


# ╔══════════════════════════════════════════════════════════════════════╗
# ║                    Engine implementations                           ║
# ╚══════════════════════════════════════════════════════════════════════╝

# ---------------------------------------------------------------------------
# curl_cffi (async)
# ---------------------------------------------------------------------------

async def _try_curl_cffi(
    url: str,
    params: dict | None,
    headers: dict,
    cookies: dict,
    proxy_url: str,
    timeout: int,
    session_cache: dict | None = None,
    winner_hint: str | None = None,
) -> Optional[BypassResponse]:
    """Attempt a request using curl_cffi with Chrome TLS impersonation."""
    if not _HAS_CURL_CFFI:
        return None

    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    last_err = None

    targets = list(_IMPERSONATE_TARGETS)
    if winner_hint and winner_hint in targets and targets[0] != winner_hint:
        targets.remove(winner_hint)
        targets.insert(0, winner_hint)

    for target in targets:
        try:
            if session_cache is not None:
                if target not in session_cache:
                    session_cache[target] = cffi_requests.AsyncSession(
                        impersonate=target,
                        proxies=proxies,
                        verify=True,
                    )
                session = session_cache[target]
                resp = await session.get(
                    url,
                    params=params,
                    headers=headers,
                    cookies=cookies,
                    timeout=timeout,
                    allow_redirects=True,
                )
            else:
                async with cffi_requests.AsyncSession(
                    impersonate=target,
                    proxies=proxies,
                    verify=True,
                ) as session:
                    resp = await session.get(
                        url,
                        params=params,
                        headers=headers,
                        cookies=cookies,
                        timeout=timeout,
                        allow_redirects=True,
                    )

            content = resp.content
            text = resp.text
            status_code = resp.status_code
            final_url = resp.url
            try:
                json_data = resp.json()
            except Exception:
                json_data = None

            cookies_resp = _extract_cookies(resp)
            result = BypassResponse(content, text, status_code, final_url, json_data, f"curl_cffi/{target}", cookies_resp)

            if status_code != 403:
                return result

            log.debug("curl_cffi/%s got 403 for %s, trying next target", target, url)
            last_err = result

        except Exception as e:
            log.debug("curl_cffi/%s failed for %s: %s", target, url, e)
            last_err = None
            continue

    return last_err


# ---------------------------------------------------------------------------
# curl_cffi (sync)
# ---------------------------------------------------------------------------

def _try_curl_cffi_sync(
    url: str,
    params: dict | None,
    headers: dict,
    cookies: dict,
    proxy_url: str,
    timeout: int,
    session_cache: dict | None = None,
    winner_hint: str | None = None,
) -> Optional[BypassResponse]:
    """Synchronous curl_cffi engine — uses persistent sync Sessions."""
    if not _HAS_CURL_CFFI:
        return None

    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    last_err = None

    targets = list(_IMPERSONATE_TARGETS)
    if winner_hint and winner_hint in targets and targets[0] != winner_hint:
        targets.remove(winner_hint)
        targets.insert(0, winner_hint)

    for target in targets:
        try:
            if session_cache is not None:
                if target not in session_cache:
                    session_cache[target] = cffi_requests.Session(
                        impersonate=target,
                        proxies=proxies,
                        verify=True,
                    )
                session = session_cache[target]
                resp = session.get(
                    url,
                    params=params,
                    headers=headers,
                    cookies=cookies,
                    timeout=timeout,
                    allow_redirects=True,
                )
            else:
                with cffi_requests.Session(
                    impersonate=target,
                    proxies=proxies,
                    verify=True,
                ) as session:
                    resp = session.get(
                        url,
                        params=params,
                        headers=headers,
                        cookies=cookies,
                        timeout=timeout,
                        allow_redirects=True,
                    )

            content = resp.content
            text = resp.text
            status_code = resp.status_code
            final_url = resp.url
            try:
                json_data = resp.json()
            except Exception:
                json_data = None

            cookies_resp = _extract_cookies(resp)
            result = BypassResponse(content, text, status_code, final_url, json_data, f"curl_cffi/{target}", cookies_resp)

            if status_code != 403:
                return result

            log.debug("curl_cffi_sync/%s got 403 for %s, trying next target", target, url)
            last_err = result

        except Exception as e:
            log.debug("curl_cffi_sync/%s failed for %s: %s", target, url, e)
            last_err = None
            continue

    return last_err


# ---------------------------------------------------------------------------
# cloudscraper (sync)
# ---------------------------------------------------------------------------

def _try_cloudscraper_sync(
    url: str,
    params: dict | None,
    headers: dict,
    cookies: dict,
    proxy_url: str,
    timeout: int,
) -> Optional[BypassResponse]:
    """Attempt a request using cloudscraper (JS challenge solver)."""
    if not _HAS_CLOUDSCRAPER:
        return None

    try:
        scraper = _cloudscraper.create_scraper(
            browser={
                "browser": "chrome",
                "platform": "windows",
                "desktop": True,
            },
            delay=5,
        )
        scraper.headers.update(headers)

        if cookies:
            scraper.cookies.update(cookies)

        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

        resp = scraper.get(
            url,
            params=params,
            timeout=timeout,
            proxies=proxies,
            allow_redirects=True,
        )
        content = resp.content
        text = resp.text
        status_code = resp.status_code
        final_url = str(resp.url)
        try:
            json_data = resp.json()
        except Exception:
            json_data = None

        cookies_resp = _extract_cookies(resp)
        return BypassResponse(content, text, status_code, final_url, json_data, "cloudscraper", cookies_resp)
    except Exception as e:
        log.debug("cloudscraper failed for %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# httpx (async)
# ---------------------------------------------------------------------------

async def _try_httpx(
    url: str,
    params: dict | None,
    headers: dict,
    cookies: dict,
    proxy_url: str,
    timeout: int,
    client: "httpx.AsyncClient | None" = None,
) -> Optional[BypassResponse]:
    """Attempt a request using httpx with HTTP/2."""
    if not _HAS_HTTPX:
        return None

    try:
        if client is not None:
            resp = await client.get(url, params=params, headers=headers)
        else:
            async with httpx.AsyncClient(
                http2=True,
                follow_redirects=True,
                timeout=timeout,
                cookies=cookies or None,
                proxy=proxy_url or None,
            ) as c:
                resp = await c.get(url, params=params, headers=headers)

        content = resp.content
        text = resp.text
        status_code = resp.status_code
        final_url = str(resp.url)
        try:
            json_data = resp.json()
        except Exception:
            json_data = None

        cookies_resp = _extract_cookies(resp)
        return BypassResponse(content, text, status_code, final_url, json_data, "httpx", cookies_resp)
    except Exception as e:
        log.debug("httpx failed for %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# requests (sync)
# ---------------------------------------------------------------------------

def _try_requests_sync(
    url: str,
    params: dict | None,
    headers: dict,
    cookies: dict,
    proxy_url: str,
    timeout: int,
) -> Optional[BypassResponse]:
    """Attempt a request using the requests library."""
    if not _HAS_REQUESTS:
        return None

    try:
        session = _requests_lib.Session()
        session.headers.update(headers)
        if cookies:
            session.cookies.update(cookies)

        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

        resp = session.get(
            url,
            params=params,
            timeout=timeout,
            proxies=proxies,
            allow_redirects=True,
        )
        content = resp.content
        text = resp.text
        status_code = resp.status_code
        final_url = str(resp.url)
        try:
            json_data = resp.json()
        except Exception:
            json_data = None

        cookies_resp = _extract_cookies(resp)
        return BypassResponse(content, text, status_code, final_url, json_data, "requests", cookies_resp)
    except Exception as e:
        log.debug("requests failed for %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# urllib (sync)
# ---------------------------------------------------------------------------

def _try_urllib_sync(
    url: str,
    params: dict | None,
    headers: dict,
    cookies: dict,
    proxy_url: str,
    timeout: int,
) -> Optional[BypassResponse]:
    """Attempt a request using stdlib urllib (always available)."""
    try:
        from urllib.parse import urlencode

        if params:
            query = urlencode(params)
            url = f"{url}?{query}" if "?" not in url else f"{url}&{query}"

        cookie_jar = urllib.request.HTTPCookieProcessor()
        handlers: list = [urllib.request.HTTPCookieProcessor(cookie_jar)]

        if proxy_url:
            proxy_handler = urllib.request.ProxyHandler({
                "http": proxy_url,
                "https": proxy_url,
            })
            handlers.append(proxy_handler)

        opener = urllib.request.build_opener(*handlers)

        req = urllib.request.Request(url, headers=headers)

        if cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
            req.add_header("Cookie", cookie_str)

        with opener.open(req, timeout=timeout) as resp:
            content = resp.read()
            text = content.decode("utf-8", errors="replace")
            status_code = resp.status
            final_url = resp.url
            try:
                import json as _json
                json_data = _json.loads(text)
            except Exception:
                json_data = None
        cookies_resp = _extract_cookies(resp)
        return BypassResponse(content, text, status_code, final_url, json_data, "urllib", cookies_resp)
    except urllib.error.HTTPError as e:
        content = e.read() if hasattr(e, "read") else b""
        text = content.decode("utf-8", errors="replace")
        return BypassResponse(content, text, e.code, url, None, "urllib", {})
    except Exception as e:
        log.debug("urllib failed for %s: %s", url, e)
        return None
