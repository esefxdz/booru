"""
cloudflare_bypasser/session.py — Multi-engine HTTP session orchestrator.

``BypassSession`` wires together browser identity (fingerprint.py) and
engine implementations (engines.py) into a single call with automatic
failover and retry.

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

from cloudflare_bypasser.fingerprint import (
    _DEFAULT_UA,
    _BROWSER_HEADERS,
    _NAVIGATION_HEADERS,
    BYPASS_METHODS,
    _DEFAULT_TIMEOUT,
    _MAX_RETRIES,
    _RETRY_BACKOFF_BASE,
    ENGINE_ORDER,
    _HAS_HTTPX,
    get_available_engines,
    httpx,
)
from cloudflare_bypasser.engines import (
    BypassResponse,
    _try_curl_cffi,
    _try_curl_cffi_sync,
    _try_cloudscraper_sync,
    _try_httpx,
    _try_requests_sync,
    _try_urllib_sync,
)

log = logging.getLogger("cloudflare_bypasser")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║                        BypassSession                                ║
# ╚══════════════════════════════════════════════════════════════════════╝

# Re-export public symbols from the sub-modules so existing importers
# (e.g. __init__.py, section_network.py) don't break.
from cloudflare_bypasser.fingerprint import (  # noqa: E402, F401
    BYPASS_METHODS,
    BYPASS_METHOD_LABELS,
    ENGINE_ORDER,
    get_available_engines,
)
from cloudflare_bypasser.engines import BypassResponse, _Response  # noqa: E402, F401


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
        self._cffi_sync_sessions = {}
        self._loop_id = None
        self._successful_engine = None
        self._last_request_time = 0.0
        self._rate_limit_lock = None
        self._cookie_jar = {}
        self._cffi_winner: str | None = None

    # ------------------------------------------------------------------
    # Loop-aware client invalidation
    # ------------------------------------------------------------------

    def _check_loop(self):
        """Invalidate cached clients if the event loop has changed."""
        try:
            current_loop = asyncio.get_running_loop()
            if getattr(self, "_loop_ref", None) is not current_loop:
                self._httpx_client = None
                self._cffi_sessions.clear()
                self._rate_limit_lock = None
                self._loop_ref = current_loop
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # Warmup
    # ------------------------------------------------------------------

    async def warmup(self, base_url: str, timeout: int = _DEFAULT_TIMEOUT) -> dict:
        """Visit the site homepage to establish cookies and a Referer chain."""
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

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self):
        """Close any persistent underlying clients."""
        if self._httpx_client is not None:
            await self._httpx_client.aclose()
            self._httpx_client = None
        for s in self._cffi_sessions.values():
            s.close()
        self._cffi_sessions.clear()

    # ------------------------------------------------------------------
    # Header construction
    # ------------------------------------------------------------------

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
                from ui import settings_view as settings
                use_h2 = getattr(settings.manager, "use_http2", False)
                self._httpx_client = httpx.AsyncClient(
                    http2=use_h2,
                    follow_redirects=True,
                    timeout=timeout,
                    cookies=self._merged_cookies or None,
                    proxy=self.proxy_url or None,
                )
            return await _try_httpx(
                url, params, headers, self._merged_cookies, self.proxy_url, timeout, self._httpx_client,
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

            if attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                log.info(
                    "Attempt %d/%d failed for %s, retrying in %.1fs",
                    attempt, _MAX_RETRIES, url, wait,
                )
                await asyncio.sleep(wait)

        if last_response:
            log.warning(
                "All engines failed for %s, returning last response [%d]",
                url, last_response.status_code,
            )
            return last_response

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

        engines = self._get_engine_order()
        sync_engines = [e for e in engines if e != "httpx"]
        last_response: Optional[BypassResponse] = None

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
