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

# curl-cffi impersonation targets — try latest Chrome first, then fall back.
# Kept to 4 entries: walking a long list sequentially on every 403 was the
# main source of UI hangs.  The session tracks which target last succeeded
# (_cffi_winner) and tries it first so the common path costs one attempt.
_IMPERSONATE_TARGETS = [
    "chrome131", "chrome124", "chrome120", "edge101",
]

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
        # (brotli/gzip) fails to decode.  A legitimate API response always
        # starts with '[', '{', '<', or is empty.  Anything else at 403 is
        # an undecoded CF challenge page.
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

        # Cloudflare-specific response headers in HTML
        if "cf-ray" in text_lower and ("challenge" in text_lower or "captcha" in text_lower):
            return True

        # Detect CF block pages that return minimal body with 403
        if self.status_code == 403 and len(self.content) < 500 and b"cloudflare" in content_lower:
            return True

        return False

    def __repr__(self) -> str:
        return f"<BypassResponse [{self.status_code}] engine={self.engine_used} {self.url}>"


# Keep backward compat alias
_Response = BypassResponse


# ---------------------------------------------------------------------------
# Internal: cookie extraction
# ---------------------------------------------------------------------------

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
    session_cache: dict | None = None,
    winner_hint: str | None = None,
) -> Optional[BypassResponse]:
    """Attempt a request using curl_cffi with Chrome TLS impersonation."""
    if not _HAS_CURL_CFFI:
        return None

    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    last_err = None

    # Try the last successful target first — avoids walking the full list on
    # every request when one target reliably works for this session.
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
            
            # Eagerly capture everything outside the if/else blocks
            content = resp.content
            text = resp.text
            status_code = resp.status_code
            final_url = resp.url
            try:
                json_data = resp.json()
            except Exception:
                json_data = None

            cookies = _extract_cookies(resp)
            result = BypassResponse(content, text, status_code, final_url, json_data, f"curl_cffi/{target}", cookies)

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
    """Synchronous curl_cffi engine — uses persistent sync Sessions so
    get_sync() callers get connection reuse without touching an event loop."""
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

        cookies_resp = _extract_cookies(resp)
        return BypassResponse(content, text, status_code, final_url, json_data, "cloudscraper", cookies_resp)
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
    client: httpx.AsyncClient | None = None,
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
        cookies_resp = _extract_cookies(resp)
        return BypassResponse(content, text, status_code, final_url, json_data, "urllib", cookies_resp)
    except urllib.error.HTTPError as e:
        content = e.read() if hasattr(e, "read") else b""
        text = content.decode("utf-8", errors="replace")
        return BypassResponse(content, text, e.code, url, None, "urllib", {})
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
        
        self._httpx_client = None
        self._cffi_sessions = {}
        self._cffi_sync_sessions = {}  # sync Session cache for get_sync() — never loop-bound
        self._loop_id = None
        self._successful_engine = None
        self._last_request_time = 0.0
        self._rate_limit_lock = None  # asyncio.Lock, created lazily per event loop
        self._cookie_jar = {}         # accumulated cookies from responses (warmup + API calls)
        self._cffi_winner: str | None = None  # last curl_cffi target that worked; tried first next time
        
    def _check_loop(self):
        """Invalidate cached clients if the event loop has changed.
        We hold a strong reference to the loop object to prevent memory address
        reuse (which would make id() checks falsely return True for new loops).
        """
        try:
            current_loop = asyncio.get_running_loop()
            if getattr(self, "_loop_ref", None) is not current_loop:
                self._httpx_client = None
                self._cffi_sessions.clear()
                self._rate_limit_lock = None  # force re-creation on new loop
                self._loop_ref = current_loop
        except RuntimeError:
            pass

    async def warmup(self, base_url: str, timeout: int = _DEFAULT_TIMEOUT) -> dict:
        """Visit the site homepage to establish cookies and a Referer chain.

        Cloudflare's ML scoring penalises requests that hit API endpoints
        directly without ever loading the main site.  This method makes a
        lightweight GET to *base_url* (e.g. ``https://danbooru.donmai.us``)
        with browser-like navigation headers, captures any cookies the server
        sets (``__cf_bm``, session cookies, etc.), and feeds them into
        subsequent API calls.

        Returns the accumulated cookie jar so callers can persist it.
        """
        nav_headers = {**self._build_headers(), **_NAVIGATION_HEADERS}
        resp = await self.get(base_url, headers=nav_headers, timeout=timeout, bypass_rate_limit=True)
        if resp.cookies:
            self._cookie_jar.update(resp.cookies)
            log.debug("warmup captured %d cookies from %s", len(resp.cookies), base_url)
        if resp.status_code in (200, 301, 302, 303, 307, 308):
            log.info("warmup %s → %d (cookies: %d)", base_url, resp.status_code, len(self._cookie_jar))
        else:
            log.warning("warmup %s → %d (may be blocked)", base_url, resp.status_code)
        return dict(self._cookie_jar)

    def warmup_sync(self, base_url: str, timeout: int = _DEFAULT_TIMEOUT) -> dict:
        """Synchronous version of :meth:`warmup`."""
        nav_headers = {**self._build_headers(), **_NAVIGATION_HEADERS}
        resp = self.get_sync(base_url, headers=nav_headers, timeout=timeout)
        if resp.cookies:
            self._cookie_jar.update(resp.cookies)
            log.debug("warmup_sync captured %d cookies from %s", len(resp.cookies), base_url)
        return dict(self._cookie_jar)

    async def close(self):
        """Close any persistent underlying clients. Must be called if reused across multiple requests."""
        if self._httpx_client is not None:
            await self._httpx_client.aclose()
            self._httpx_client = None
        for s in self._cffi_sessions.values():
            s.close() # curl_cffi AsyncSession close is sync
        self._cffi_sessions.clear()

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
                url, params, headers, self._merged_cookies, self.proxy_url, timeout,
                self._cffi_sessions, winner_hint=self._cffi_winner,
            )
        elif engine == "cloudscraper":
            return await loop.run_in_executor(
                None,
                _try_cloudscraper_sync,
                url, params, headers, self._merged_cookies, self.proxy_url, timeout,
            )
        elif engine == "httpx":
            if self._httpx_client is None and _HAS_HTTPX:
                self._httpx_client = httpx.AsyncClient(
                    http2=True,
                    follow_redirects=True,
                    timeout=timeout,
                    cookies=self._merged_cookies or None,
                    proxy=self.proxy_url or None,
                )
            return await _try_httpx(
                url, params, headers, self._merged_cookies, self.proxy_url, timeout, self._httpx_client
            )
        elif engine == "requests":
            return await loop.run_in_executor(
                None,
                _try_requests_sync,
                url, params, headers, self._merged_cookies, self.proxy_url, timeout,
            )
        elif engine == "urllib":
            return await loop.run_in_executor(
                None,
                _try_urllib_sync,
                url, params, headers, self._merged_cookies, self.proxy_url, timeout,
            )
        return None

    # ------------------------------------------------------------------
    # Cookie helpers
    # ------------------------------------------------------------------

    @property
    def _merged_cookies(self) -> dict:
        """Stored cookies + warmup/response accumulated cookies."""
        merged = {**self.cookies}
        merged.update(self._cookie_jar)
        return merged

    # ------------------------------------------------------------------
    # Async interface
    # ------------------------------------------------------------------

    async def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        bypass_rate_limit: bool = False,
    ) -> BypassResponse:
        """
        GET with automatic engine failover and retry.

        In ``auto`` mode, tries curl_cffi → cloudscraper → httpx → requests
        → urllib.  Retries up to 3 times with exponential backoff on
        transient failures (5xx, timeouts).
        """
        self._check_loop()
        from ui import settings_view as settings

        if not bypass_rate_limit and getattr(settings.manager, "use_rate_limit", False):
            if self._rate_limit_lock is None:
                self._rate_limit_lock = asyncio.Lock()
            delay_needed = 0
            delay = getattr(settings.manager, "rate_limit_delay", 0.25)
            async with self._rate_limit_lock:
                now = time.time()
                elapsed = now - self._last_request_time
                if elapsed < delay:
                    delay_needed = delay - elapsed
                    self._last_request_time = now + delay_needed
                else:
                    self._last_request_time = now
            if delay_needed > 0:
                await asyncio.sleep(delay_needed)

        merged_headers = self._build_headers(headers)
        last_response: Optional[BypassResponse] = None
        
        # In auto mode, try the previously successful engine first
        engines = self._get_engine_order()
        if self.method == "auto" and self._successful_engine and self._successful_engine in engines:
            # Reorder so successful engine is first
            engines.remove(self._successful_engine)
            engines.insert(0, self._successful_engine)

        for attempt in range(1, _MAX_RETRIES + 1):
            for engine in engines:
                resp = await self._run_async_engine(
                    engine, url, params, merged_headers, timeout,
                )
                if resp and not resp.is_blocked and resp.status_code < 500:
                    if self.method == "auto":
                        self._successful_engine = engine
                    # Remember which curl_cffi target worked so next call skips the fallback loop
                    if engine == "curl_cffi" and resp.engine_used and "/" in resp.engine_used:
                        self._cffi_winner = resp.engine_used.split("/", 1)[1]
                    if resp.cookies:
                        self._cookie_jar.update(resp.cookies)
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
        """Synchronous wrapper.

        Tries sync engines first (curl_cffi → cloudscraper → requests →
        urllib) using persistent sync sessions for connection reuse.  Falls
        back to the full async engine chain only when httpx HTTP/2 is needed
        or when locked to an async-only engine.
        """
        merged_headers = self._build_headers(headers)

        # ── Pick engine list ──────────────────────────────────────────
        engines = self._get_engine_order()
        # Remove httpx from the sync-first pass (it has no sync session cache)
        sync_engines = [e for e in engines if e != "httpx"]
        last_response: Optional[BypassResponse] = None

        # ── Try sync engines directly (no asyncio overhead) ───────────
        for attempt in range(1, _MAX_RETRIES + 1):
            for engine in sync_engines:
                resp = self._try_sync_engine(engine, url, params, merged_headers, timeout)
                if resp and not resp.is_blocked and resp.status_code < 500:
                    if self.method == "auto":
                        self._successful_engine = engine
                    if engine == "curl_cffi" and resp.engine_used and "/" in resp.engine_used:
                        self._cffi_winner = resp.engine_used.split("/", 1)[1]
                    if resp.cookies:
                        self._cookie_jar.update(resp.cookies)
                    return resp
                if resp:
                    last_response = resp
            if attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                time.sleep(wait)

        # ── Fallback: full async chain (needed for httpx or locked method) ──
        if last_response is None or "httpx" in engines:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.get(url, params=params, headers=headers, timeout=timeout),
                    )
                    async_resp = future.result(timeout=timeout + 10)
            else:
                async_resp = asyncio.run(
                    self.get(url, params=params, headers=headers, timeout=timeout)
                )
            if async_resp and async_resp.status_code > 0:
                return async_resp

        # ── Total failure ─────────────────────────────────────────────
        if last_response:
            return last_response
        return BypassResponse(b"", "", 0, url, None, "none")

    def _try_sync_engine(
        self, engine: str, url: str, params: dict | None,
        headers: dict, timeout: int,
    ) -> Optional[BypassResponse]:
        """Dispatch a single synchronous engine attempt (no asyncio)."""
        if engine == "curl_cffi":
            return _try_curl_cffi_sync(
                url, params, headers, self._merged_cookies, self.proxy_url,
                timeout, self._cffi_sync_sessions, winner_hint=self._cffi_winner,
            )
        elif engine == "cloudscraper":
            return _try_cloudscraper_sync(
                url, params, headers, self._merged_cookies, self.proxy_url, timeout,
            )
        elif engine == "requests":
            return _try_requests_sync(
                url, params, headers, self._merged_cookies, self.proxy_url, timeout,
            )
        elif engine == "urllib":
            return _try_urllib_sync(
                url, params, headers, self._merged_cookies, self.proxy_url, timeout,
            )
        return None

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
