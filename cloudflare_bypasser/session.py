"""
cloudflare_bypasser/session.py

Bulletproof HTTP engine with multi-layer bypass strategy.

Priority chain (each request tries in order until one succeeds):
  1. curl_cffi  — Chrome TLS impersonation (beats JA3 fingerprinting)
  2. httpx      — HTTP/2 with browser-grade headers (beats basic WAFs)
  3. urllib     — stdlib last resort (always available)

Every layer adds realistic browser metadata (Sec-Fetch-*, Accept-Language,
DNT, etc.) so Cloudflare's heuristic scoring sees a real browser.
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Optional

log = logging.getLogger("cloudflare_bypasser")

# ---------------------------------------------------------------------------
# Try to import optional engines at module level — never crash on import
# ---------------------------------------------------------------------------
_HAS_CURL_CFFI = False
try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    cffi_requests = None  # type: ignore

_HAS_HTTPX = False
try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Realistic browser headers that Cloudflare expects to see on every request.
# Missing any of these causes CF to bump the bot-score significantly.
_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "DNT": "1",
    "Sec-CH-UA": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}

# curl-cffi impersonation targets — try latest first, fall back to older
_IMPERSONATE_TARGETS = ["chrome124", "chrome120", "chrome119", "chrome116"]

_DEFAULT_TIMEOUT = 30
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 0.5  # seconds, doubles each retry


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------
class BypassResponse:
    """
    Immutable response wrapper.  All data is captured eagerly so the caller
    never holds a dangling reference to a closed socket/session.
    """

    __slots__ = ("content", "text", "status_code", "url", "_json_data", "engine_used")

    def __init__(
        self,
        content: bytes,
        text: str,
        status_code: int,
        url: object,
        json_data: object,
        engine_used: str = "unknown",
    ) -> None:
        self.content = content
        self.text = text
        self.status_code = status_code
        self.url = url
        self._json_data = json_data
        self.engine_used = engine_used

    def json(self) -> object:
        if self._json_data is not None:
            return self._json_data
        import json as _json
        return _json.loads(self.text)

    @property
    def is_blocked(self) -> bool:
        """True when the response looks like a Cloudflare challenge page."""
        if self.status_code not in (403, 503):
            return False

        # Check both decoded text and raw bytes (response may be brotli-compressed)
        text_lower = self.text[:4000].lower() if self.text else ""
        content_lower = self.content[:4000].lower() if self.content else b""

        cf_markers_text = (
            "cf-mitigated", "cloudflare", "just a moment",
            "challenge-platform", "challenges.cloudflare.com",
            "ray id", "cf-ray",
        )
        cf_markers_bytes = (
            b"cf-mitigated", b"cloudflare", b"just a moment",
            b"challenge-platform", b"challenges.cloudflare.com",
            b"ray id", b"cf-ray",
        )

        for marker in cf_markers_text:
            if marker in text_lower:
                return True
        for marker in cf_markers_bytes:
            if marker in content_lower:
                return True

        # A 403 on a JSON API endpoint is almost certainly CF, not the app
        url_str = str(self.url).lower()
        if self.status_code == 403 and (
            ".json" in url_str
            or "api" in url_str
            or "dapi" in url_str
            or "index.php" in url_str
        ):
            return True

        return False

    def __repr__(self) -> str:
        return f"<BypassResponse [{self.status_code}] engine={self.engine_used} {self.url}>"


# Keep backward compat alias
_Response = BypassResponse


# ---------------------------------------------------------------------------
# Internal: engine-specific request implementations
# ---------------------------------------------------------------------------

async def _try_curl_cffi(
    url: str,
    params: dict | None,
    headers: dict,
    cookies: dict,
    proxy_url: str,
    timeout: int,
) -> Optional[BypassResponse]:
    """Attempt a request using curl_cffi with Chrome TLS impersonation."""
    if not _HAS_CURL_CFFI:
        return None

    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    last_err = None

    for target in _IMPERSONATE_TARGETS:
        try:
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
                # Eagerly capture everything
                content = resp.content
                text = resp.text
                status_code = resp.status_code
                final_url = resp.url
                try:
                    json_data = resp.json()
                except Exception:
                    json_data = None

            result = BypassResponse(content, text, status_code, final_url, json_data, f"curl_cffi/{target}")

            # If we got a real response (even 403), return it
            if status_code != 403:
                return result

            # 403 — try next impersonation target
            log.debug("curl_cffi/%s got 403 for %s, trying next target", target, url)
            last_err = result

        except Exception as e:
            log.debug("curl_cffi/%s failed for %s: %s", target, url, e)
            last_err = None
            continue

    return last_err  # return the 403 if all targets gave 403, else None


async def _try_httpx(
    url: str,
    params: dict | None,
    headers: dict,
    cookies: dict,
    proxy_url: str,
    timeout: int,
) -> Optional[BypassResponse]:
    """Attempt a request using httpx with HTTP/2."""
    if not _HAS_HTTPX:
        return None

    try:
        async with httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            timeout=timeout,
            cookies=cookies or None,
            proxy=proxy_url or None,
        ) as client:
            resp = await client.get(url, params=params, headers=headers)
            content = resp.content
            text = resp.text
            status_code = resp.status_code
            final_url = str(resp.url)
            try:
                json_data = resp.json()
            except Exception:
                json_data = None

        return BypassResponse(content, text, status_code, final_url, json_data, "httpx")
    except Exception as e:
        log.debug("httpx failed for %s: %s", url, e)
        return None


def _try_urllib_sync(
    url: str,
    params: dict | None,
    headers: dict,
    timeout: int,
) -> Optional[BypassResponse]:
    """Absolute last resort — stdlib urllib. No proxy/cookie/HTTP2 support."""
    import urllib.request
    import urllib.parse
    import urllib.error

    try:
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            text = content.decode("utf-8", errors="replace")
            status_code = resp.status
            final_url = resp.url
            try:
                import json as _json
                json_data = _json.loads(text)
            except Exception:
                json_data = None
        return BypassResponse(content, text, status_code, final_url, json_data, "urllib")
    except urllib.error.HTTPError as e:
        content = e.read() if hasattr(e, "read") else b""
        text = content.decode("utf-8", errors="replace")
        return BypassResponse(content, text, e.code, url, None, "urllib")
    except Exception as e:
        log.debug("urllib failed for %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# BypassSession
# ---------------------------------------------------------------------------
class BypassSession:
    """
    Multi-engine HTTP session with automatic failover.

    Parameters
    ----------
    user_agent : str
        The User-Agent string.  When captured from the WebEngine CAPTCHA flow,
        this must match exactly or CF will reject the clearance cookie.
    cookies : dict
        Cookies to send (including cf_clearance).
    proxy_url : str
        Optional proxy URL (http/https/socks5).
    """

    def __init__(
        self,
        user_agent: str = _DEFAULT_UA,
        cookies: dict | None = None,
        proxy_url: str = "",
    ) -> None:
        self.user_agent = user_agent or _DEFAULT_UA
        self.cookies = cookies or {}
        self.proxy_url = proxy_url

    def _build_headers(self, extra_headers: dict | None = None) -> dict:
        """Merge browser baseline headers with the session UA and any extras."""
        h = dict(_BROWSER_HEADERS)
        h["User-Agent"] = self.user_agent
        if extra_headers:
            h.update(extra_headers)
        return h

    # ------------------------------------------------------------------
    # Async interface
    # ------------------------------------------------------------------

    async def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> BypassResponse:
        """
        GET with automatic engine failover and retry.

        Tries curl_cffi → httpx → urllib.  Retries up to 3 times with
        exponential backoff on transient failures (5xx, timeouts).
        """
        merged_headers = self._build_headers(headers)
        last_response: Optional[BypassResponse] = None

        for attempt in range(1, _MAX_RETRIES + 1):
            # --- Engine 1: curl_cffi (best for CF bypass) ---
            resp = await _try_curl_cffi(
                url, params, merged_headers, self.cookies,
                self.proxy_url, timeout,
            )
            if resp and not resp.is_blocked and resp.status_code < 500:
                return resp
            if resp:
                last_response = resp

            # --- Engine 2: httpx (HTTP/2, good compat) ---
            resp = await _try_httpx(
                url, params, merged_headers, self.cookies,
                self.proxy_url, timeout,
            )
            if resp and not resp.is_blocked and resp.status_code < 500:
                return resp
            if resp:
                last_response = resp

            # --- Backoff before retry ---
            if attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                log.info("Attempt %d/%d failed for %s, retrying in %.1fs",
                         attempt, _MAX_RETRIES, url, wait)
                await asyncio.sleep(wait)

        # --- Engine 3: urllib last resort (sync, wrapped in executor) ---
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None,
            _try_urllib_sync, url, params, merged_headers, timeout,
        )
        if resp:
            return resp

        # If absolutely everything failed, return the best response we got
        if last_response:
            log.warning("All engines failed for %s, returning last response [%d]",
                        url, last_response.status_code)
            return last_response

        # Fabricate an error response so callers never get None
        log.error("Total failure for %s — no engine could reach the server", url)
        return BypassResponse(b"", "", 0, url, None, "none")

    # ------------------------------------------------------------------
    # Sync interface
    # ------------------------------------------------------------------

    def get_sync(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> BypassResponse:
        """Synchronous wrapper.  Creates a fresh event loop."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.get(url, params=params, headers=headers, timeout=timeout)
            )
        finally:
            loop.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def with_extra_cookies(self, extra: dict) -> "BypassSession":
        """Return a *new* session that merges extra cookies into the jar."""
        return BypassSession(self.user_agent, {**self.cookies, **extra}, self.proxy_url)

    def __repr__(self) -> str:
        has_cf = "cf_clearance" in self.cookies
        engines = []
        if _HAS_CURL_CFFI:
            engines.append("curl_cffi")
        if _HAS_HTTPX:
            engines.append("httpx")
        engines.append("urllib")
        return (
            f"<BypassSession cf={has_cf} "
            f"proxy={'yes' if self.proxy_url else 'no'} "
            f"engines=[{','.join(engines)}]>"
        )
