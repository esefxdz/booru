"""
cloudflare_bypasser/session.py

Bulletproof HTTP engine with multi-layer bypass strategy.

Priority chain in ``auto`` mode (each request tries in order until one succeeds):
  1. curl_cffi     — Chrome TLS impersonation (beats JA3 fingerprinting)
  2. cloudscraper  — JS challenge solver with browser UA rotation
  3. httpx         — HTTP/2 with browser-grade headers (beats basic WAFs)
  4. requests      — Battle-tested fallback with session cookies
  5. urllib        — stdlib last resort (always available)

Every layer adds realistic browser metadata (Sec-Fetch-*, Accept-Language,
DNT, etc.) so Cloudflare's heuristic scoring sees a real browser.

Users can lock to a specific engine via ``settings.manager.cf_bypass_method``.
"""

from __future__ import annotations
import asyncio
import logging
import time
import threading
from typing import Optional

log = logging.getLogger("cloudflare_bypasser")

_rate_limit_lock = threading.Lock()
_last_request_time = 0.0

# ---------------------------------------------------------------------------
# Try to import optional engines at module level — never crash on import
# ---------------------------------------------------------------------------
_HAS_CURL_CFFI = False
try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    cffi_requests = None  # type: ignore

_HAS_CLOUDSCRAPER = False
try:
    import cloudscraper as _cloudscraper
    _HAS_CLOUDSCRAPER = True
except ImportError:
    _cloudscraper = None  # type: ignore

_HAS_HTTPX = False
try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore

_HAS_REQUESTS = False
try:
    import requests as _requests_lib
    _HAS_REQUESTS = True
except ImportError:
    _requests_lib = None  # type: ignore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
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
    "Sec-CH-UA": '"Chromium";v="136", "Google Chrome";v="136", "Not-A.Brand";v="99"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# Separate header set for navigation requests (page loads, not API calls)
_NAVIGATION_HEADERS = {
    **_BROWSER_HEADERS,
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

# curl-cffi impersonation targets — try latest first, fall back to older
_IMPERSONATE_TARGETS = ["chrome136", "chrome124", "chrome120", "chrome119"]

_DEFAULT_TIMEOUT = 30
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 0.5  # seconds, doubles each retry

# All known engine identifiers (order = default priority)
ENGINE_ORDER = ["curl_cffi", "cloudscraper", "httpx", "requests", "urllib"]

# Valid method choices for the settings dropdown
BYPASS_METHODS = ["auto"] + ENGINE_ORDER

# Human-readable labels for the settings UI
BYPASS_METHOD_LABELS = {
    "auto":         "Auto (try all engines)",
    "curl_cffi":    "curl_cffi — Chrome TLS fingerprint",
    "cloudscraper": "cloudscraper — JS challenge solver",
    "httpx":        "httpx — HTTP/2 modern client",
    "requests":     "requests — Classic HTTP client",
    "urllib":       "urllib — Stdlib fallback",
}


def get_available_engines() -> list[str]:
    """Return a list of engine names that are actually importable."""
    engines = []
    if _HAS_CURL_CFFI:
        engines.append("curl_cffi")
    if _HAS_CLOUDSCRAPER:
        engines.append("cloudscraper")
    if _HAS_HTTPX:
        engines.append("httpx")
    if _HAS_REQUESTS:
        engines.append("requests")
    engines.append("urllib")  # always available
    return engines


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
            "cf-mitigated", "just a moment",
            "challenge-platform", "challenges.cloudflare.com",
        )
        cf_markers_bytes = (
            b"cf-mitigated", b"just a moment",
            b"challenge-platform", b"challenges.cloudflare.com",
        )

        for marker in cf_markers_text:
            if marker in text_lower:
                return True
        for marker in cf_markers_bytes:
            if marker in content_lower:
                return True

        # Check for Cloudflare-specific response headers baked into HTML
        # (the word "cloudflare" alone is too generic — many CDN pages mention it)
        if "cf-ray" in text_lower and ("challenge" in text_lower or "captcha" in text_lower):
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
        # Apply our headers on top (cloudscraper sets its own UA if we don't)
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

        return BypassResponse(content, text, status_code, final_url, json_data, "cloudscraper")
    except Exception as e:
        log.debug("cloudscraper failed for %s: %s", url, e)
        return None


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

        return BypassResponse(content, text, status_code, final_url, json_data, "requests")
    except Exception as e:
        log.debug("requests failed for %s: %s", url, e)
        return None


def _try_urllib_sync(
    url: str,
    params: dict | None,
    headers: dict,
    cookies: dict,
    proxy_url: str,
    timeout: int,
) -> Optional[BypassResponse]:
    """Last resort — stdlib urllib with cookie and proxy support."""
    import urllib.request
    import urllib.parse
    import urllib.error
    import http.cookiejar

    try:
        if params:
            url = url + "?" + urllib.parse.urlencode(params)

        # Build opener with cookie and proxy support
        cookie_jar = http.cookiejar.CookieJar()
        handlers: list = [urllib.request.HTTPCookieProcessor(cookie_jar)]

        if proxy_url:
            proxy_handler = urllib.request.ProxyHandler({
                "http": proxy_url,
                "https": proxy_url,
            })
            handlers.append(proxy_handler)

        opener = urllib.request.build_opener(*handlers)

        req = urllib.request.Request(url, headers=headers)

        # Inject cookies into the request header manually
        # (cookie jar won't have them pre-loaded)
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
    method : str
        Which bypass engine to use.  ``"auto"`` tries all in priority order.
        Any other value from :data:`BYPASS_METHODS` locks to that engine.
    """

    def __init__(
        self,
        user_agent: str = _DEFAULT_UA,
        cookies: dict | None = None,
        proxy_url: str = "",
        method: str = "auto",
    ) -> None:
        self.user_agent = user_agent or _DEFAULT_UA
        self.cookies = cookies or {}
        self.proxy_url = proxy_url
        self.method = method if method in BYPASS_METHODS else "auto"

    def _build_headers(self, extra_headers: dict | None = None) -> dict:
        """Merge browser baseline headers with the session UA and any extras."""
        h = dict(_BROWSER_HEADERS)
        h["User-Agent"] = self.user_agent
        if extra_headers:
            h.update(extra_headers)
        return h

    # ------------------------------------------------------------------
    # Engine dispatch
    # ------------------------------------------------------------------

    def _get_engine_order(self) -> list[str]:
        """Return the list of engines to try, respecting user's method choice."""
        if self.method == "auto":
            return list(ENGINE_ORDER)
        return [self.method]

    async def _run_async_engine(
        self,
        engine: str,
        url: str,
        params: dict | None,
        headers: dict,
        timeout: int,
    ) -> Optional[BypassResponse]:
        """Dispatch to the correct engine implementation."""
        loop = asyncio.get_running_loop()

        if engine == "curl_cffi":
            return await _try_curl_cffi(
                url, params, headers, self.cookies, self.proxy_url, timeout,
            )
        elif engine == "cloudscraper":
            return await loop.run_in_executor(
                None,
                _try_cloudscraper_sync,
                url, params, headers, self.cookies, self.proxy_url, timeout,
            )
        elif engine == "httpx":
            return await _try_httpx(
                url, params, headers, self.cookies, self.proxy_url, timeout,
            )
        elif engine == "requests":
            return await loop.run_in_executor(
                None,
                _try_requests_sync,
                url, params, headers, self.cookies, self.proxy_url, timeout,
            )
        elif engine == "urllib":
            return await loop.run_in_executor(
                None,
                _try_urllib_sync,
                url, params, headers, self.cookies, self.proxy_url, timeout,
            )
        return None

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

        In ``auto`` mode, tries curl_cffi → cloudscraper → httpx → requests
        → urllib.  Retries up to 3 times with exponential backoff on
        transient failures (5xx, timeouts).
        """
        from ui import settings_view as settings
        global _last_request_time

        if getattr(settings.manager, "use_rate_limit", False):
            delay_needed = 0
            delay = getattr(settings.manager, "rate_limit_delay", 0.25)
            with _rate_limit_lock:
                now = time.time()
                elapsed = now - _last_request_time
                if elapsed < delay:
                    delay_needed = delay - elapsed
                    _last_request_time = now + delay_needed
                else:
                    _last_request_time = now
            if delay_needed > 0:
                await asyncio.sleep(delay_needed)

        merged_headers = self._build_headers(headers)
        last_response: Optional[BypassResponse] = None
        engines = self._get_engine_order()

        for attempt in range(1, _MAX_RETRIES + 1):
            for engine in engines:
                resp = await self._run_async_engine(
                    engine, url, params, merged_headers, timeout,
                )
                if resp and not resp.is_blocked and resp.status_code < 500:
                    return resp
                if resp:
                    last_response = resp
                    log.debug(
                        "Engine %s returned %d for %s (blocked=%s)",
                        engine, resp.status_code, url, resp.is_blocked,
                    )

            # --- Backoff before retry ---
            if attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                log.info(
                    "Attempt %d/%d failed for %s, retrying in %.1fs",
                    attempt, _MAX_RETRIES, url, wait,
                )
                await asyncio.sleep(wait)

        # If absolutely everything failed, return the best response we got
        if last_response:
            log.warning(
                "All engines failed for %s, returning last response [%d]",
                url, last_response.status_code,
            )
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
        """Synchronous wrapper.  Detects existing loops to avoid conflicts."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're inside an existing event loop (e.g. Qt) — create a new
            # thread to run our own loop to avoid "loop already running"
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    self.get(url, params=params, headers=headers, timeout=timeout),
                )
                return future.result(timeout=timeout + 10)
        else:
            return asyncio.run(
                self.get(url, params=params, headers=headers, timeout=timeout)
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def with_extra_cookies(self, extra: dict) -> "BypassSession":
        """Return a *new* session that merges extra cookies into the jar."""
        return BypassSession(
            self.user_agent,
            {**self.cookies, **extra},
            self.proxy_url,
            self.method,
        )

    def __repr__(self) -> str:
        has_cf = "cf_clearance" in self.cookies
        engines = get_available_engines()
        return (
            f"<BypassSession cf={has_cf} "
            f"method={self.method} "
            f"proxy={'yes' if self.proxy_url else 'no'} "
            f"engines=[{','.join(engines)}]>"
        )
