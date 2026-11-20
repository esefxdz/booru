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
import concurrent.futures
import logging
import threading
import time
from typing import Optional
from core import settings

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

from cloudflare_bypasser.circuit_breaker import (
    _circuit_is_open,
    _close_circuit,
    _host_of,
    _open_circuit,
    solve_generation,
)
from cloudflare_bypasser.engines import _refuse_non_http
from cloudflare_bypasser.file_download import FileDownloadMixin

log = logging.getLogger("cloudflare_bypasser")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║                        BypassSession                                ║
# ╚══════════════════════════════════════════════════════════════════════╝

# Re-export public symbols from the sub-modules so existing importers
# (e.g. __init__.py, section_network.py) don't break.
from cloudflare_bypasser.fingerprint import (  # noqa: E402, F401
    BYPASS_METHOD_LABELS,
)
from cloudflare_bypasser.engines import _Response  # noqa: E402, F401


#: Most engine calls one get()/get_sync() makes, retries and get_sync's
#: httpx fallback included (was up to 24-45 network requests for one blocked
#: URL). It counts engine calls, not requests: curl_cffi may send a second
#: fingerprint on a 403 within one call.
_MAX_ENGINE_ATTEMPTS = 8
def _is_definitive(resp) -> bool:
    """A response that retrying will not change: any 4xx or a CF challenge."""
    return bool(resp) and (resp.is_blocked or 400 <= resp.status_code < 500)


class BypassSession(FileDownloadMixin):
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
    site_url : str
        The booru's base URL. Cookies are only attached to requests whose
        host is on the same registrable domain; other hosts (third-party
        CDNs, anything a server points us at) get none.
    site_url : str
        The booru's base URL. Cookies are only attached to requests whose
        host is on the same registrable domain; other hosts (third-party
        CDNs, anything a server points us at) get none.
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
        site_url: str = "",
    ) -> None:
        self.user_agent = user_agent or _DEFAULT_UA
        self.cookies = cookies or {}
        # Cookies are only sent to URLs on the same site as this booru.
        self.site_url = site_url
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
        # Requests in flight, and whether get_session has replaced us. A
        # replaced session is closed once its last request finishes.
        self._state_lock = threading.Lock()
        self._inflight = 0
        self._retired = False

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
        sessions = list(self._cffi_sessions.values())
        self._cffi_sessions.clear()
        for s in sessions:
            r = s.close()                 # curl_cffi AsyncSession.close is async
            if asyncio.iscoroutine(r):
                await r
        self._close_sync_sessions()

    def _close_sync_sessions(self) -> None:
        sessions = list(self._cffi_sync_sessions.values())
        self._cffi_sync_sessions.clear()
        for s in sessions:
            try:
                s.close()
            except Exception:
                log.debug("closing curl_cffi sync session failed", exc_info=True)

    def retire(self) -> None:
        """get_session replaced or dropped this session: release its clients.

        Another thread may still be mid-request on it (a thumbnail or media
        worker, or the event loop), and closing a curl handle under a running
        transfer is unsafe. So the close happens now only if nothing is in
        flight, otherwise when the last in-flight request returns.
        """
        with self._state_lock:
            self._retired = True
            idle = self._inflight == 0
        if idle:
            self._release()

    def _enter(self) -> None:
        with self._state_lock:
            self._inflight += 1

    def _leave(self) -> None:
        with self._state_lock:
            self._inflight -= 1
            release = self._retired and self._inflight == 0
        if release:
            self._release()

    def _release(self) -> None:
        """Close everything without blocking: sync sessions here, async
        clients on the loop they belong to."""
        self._close_sync_sessions()
        loop = getattr(self, "_loop_ref", None)
        if loop is None or (self._httpx_client is None and not self._cffi_sessions):
            return
        if loop.is_closed():
            self._httpx_client = None
            self._cffi_sessions.clear()
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self.close(), loop)
            fut.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        except RuntimeError:
            log.debug("could not schedule close of a replaced session", exc_info=True)

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
                url, params, headers, self._cookies_for(url), self.proxy_url, timeout,
                self._cffi_sessions, winner_hint=self._cffi_winner,
            )
        elif engine == "cloudscraper":
            return await loop.run_in_executor(
                None,
                _try_cloudscraper_sync,
                url, params, headers, self._cookies_for(url), self.proxy_url, timeout,
            )
        elif engine == "httpx":
            if self._httpx_client is None and _HAS_HTTPX:
                from core import settings
                use_h2 = getattr(settings.manager, "use_http2", False)
                self._httpx_client = httpx.AsyncClient(
                    http2=use_h2,
                    follow_redirects=True,
                    timeout=timeout,
                    proxy=self.proxy_url or None,
                )
            return await _try_httpx(
                url, params, headers, self._cookies_for(url), self.proxy_url, timeout, self._httpx_client,
            )
        elif engine == "requests":
            return await loop.run_in_executor(
                None,
                _try_requests_sync,
                url, params, headers, self._cookies_for(url), self.proxy_url, timeout,
            )
        elif engine == "urllib":
            return await loop.run_in_executor(
                None,
                _try_urllib_sync,
                url, params, headers, self._cookies_for(url), self.proxy_url, timeout,
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

    def _cookies_for(self, url: str) -> dict:
        """Cookies to send to *url*: all of them on the booru's own site,
        none anywhere else."""
        from core.validation import same_site
        if self.site_url and same_site(url, self.site_url):
            return self._merged_cookies
        return {}

    def _remember_cookies(self, url: str, resp) -> None:
        """Keep response cookies only when they came from the booru's site.

        Both the requested URL and the final URL after redirects must be
        same-site: resp.cookies reflects the last hop, so a redirect through
        a third-party host could otherwise plant its cookies here.
        """
        from core.validation import same_site
        final_url = str(getattr(resp, "url", "") or url)
        if (resp.cookies and self.site_url and same_site(url, self.site_url)
                and same_site(final_url, self.site_url)):
            self._cookie_jar.update(resp.cookies)

    # ------------------------------------------------------------------
    # Async interface
    # ------------------------------------------------------------------

    async def get(self, *args, **kwargs) -> BypassResponse:
        """See :meth:`_get`."""
        self._enter()
        try:
            return await self._get(*args, **kwargs)
        finally:
            self._leave()

    async def _get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        bypass_rate_limit: bool = False,
        only_engines: list[str] | None = None,
        _solve_since: Optional[int] = None,
        _max_attempts: Optional[int] = None,
    ) -> BypassResponse:
        """
        GET with automatic engine failover and retry.

        In ``auto`` mode, tries curl_cffi → cloudscraper → httpx → requests
        → urllib, at most _MAX_ENGINE_ATTEMPTS engine calls in total.
        The first good answer is returned at once; that includes an
        ordinary 4xx that is not a block. A block (Cloudflare challenge or a
        possible block, see BypassResponse.is_blocked) lets the remaining
        engines of the current round try once each, then no further round
        runs. Whole rounds are retried (with backoff) only when every
        failure was transient (no response, 5xx). A block left at the end
        opens a per-host circuit for _BLOCK_COOLDOWN seconds.
        """
        if _max_attempts is None:
            _max_attempts = _MAX_ENGINE_ATTEMPTS
        # Captured first: this session's cookies predate any solve after it.
        solve_gen = _solve_since if _solve_since is not None else solve_generation(url)
        self._check_loop()

        refused = _refuse_non_http(url)
        if refused is not None:
            return refused

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

        open_resp = self._circuit_open(url)
        if open_resp is not None:
            return open_resp

        # In auto mode, try the previously successful engine first
        engines = list(only_engines) if only_engines else self._get_engine_order()
        if (not only_engines and self.method == "auto" and self._successful_engine
                and self._successful_engine in engines):
            engines.remove(self._successful_engine)
            engines.insert(0, self._successful_engine)

        last_response: Optional[BypassResponse] = None
        attempts = 0
        for round_no in range(1, _MAX_RETRIES + 1):
            definitive = False
            for engine in engines:
                if attempts >= _max_attempts:
                    break
                attempts += 1
                resp = await self._run_async_engine(
                    engine, url, params, merged_headers, timeout,
                )
                if self._accept(engine, url, resp):
                    return resp
                if resp:
                    last_response = resp
                    definitive = definitive or _is_definitive(resp)
                    log.debug(
                        "Engine %s returned %d for %s (blocked=%s)",
                        engine, resp.status_code, url, resp.is_blocked,
                    )
            if definitive or attempts >= _max_attempts or round_no == _MAX_RETRIES:
                break
            wait = _RETRY_BACKOFF_BASE * (2 ** (round_no - 1))
            log.info("Attempt %d/%d failed for %s (transient), retrying in %.1fs",
                     round_no, _MAX_RETRIES, url, wait)
            await asyncio.sleep(wait)

        return self._give_up(url, last_response, solve_gen)

    # ------------------------------------------------------------------
    # Retry policy helpers (shared by get and get_sync)
    # ------------------------------------------------------------------

    def _accept(self, engine: str, url: str, resp) -> bool:
        """Record and accept a good response."""
        if not (resp and not resp.is_blocked and 0 < resp.status_code < 500):
            return False
        if self.method == "auto":
            self._successful_engine = engine
        if engine == "curl_cffi" and resp.engine_used and "/" in resp.engine_used:
            self._cffi_winner = resp.engine_used.split("/", 1)[1]
        self._remember_cookies(url, resp)
        _close_circuit(url)
        return True

    def _circuit_open(self, url: str) -> Optional[BypassResponse]:
        """While a host is known to be blocking us, answer without network I/O.

        Without this, every thumbnail on a page re-ran the whole engine
        chain against a site that had just served a challenge.
        """
        if _circuit_is_open(url):
            log.debug("Circuit open for %s; not sending request", _host_of(url))
            return BypassResponse(b"", "", 403, url, None, "circuit-open")
        return None

    def _give_up(self, url: str, last_response: Optional[BypassResponse],
                 solve_gen: Optional[int] = None) -> BypassResponse:
        if last_response:
            if last_response.is_blocked:
                _open_circuit(url, solve_gen)
            log.warning("All engines failed for %s, returning last response [%d]",
                        url, last_response.status_code)
            return last_response
        log.error("Total failure for %s — no engine could reach the server", url)
        return BypassResponse(b"", "", 0, url, None, "none")

    # ------------------------------------------------------------------
    # Sync interface
    # ------------------------------------------------------------------

    def get_sync(self, *args, **kwargs) -> BypassResponse:
        """See :meth:`_get_sync`."""
        self._enter()
        try:
            return self._get_sync(*args, **kwargs)
        finally:
            self._leave()

    def _get_sync(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> BypassResponse:
        """Synchronous wrapper.

        Tries the sync engines (curl_cffi, cloudscraper, requests, urllib),
        then, only if every one failed transiently and httpx is enabled,
        httpx on the shared event loop. The fallback gets only what is left
        of the _MAX_ENGINE_ATTEMPTS budget (none after two full rounds of
        the four sync engines).
        """
        solve_gen = solve_generation(url)
        refused = _refuse_non_http(url)
        if refused is not None:
            return refused
        open_resp = self._circuit_open(url)
        if open_resp is not None:
            return open_resp

        merged_headers = self._build_headers(headers)
        engines = self._get_engine_order()
        sync_engines = [e for e in engines if e != "httpx"]
        last_response: Optional[BypassResponse] = None
        attempts = 0
        definitive = False

        for round_no in range(1, _MAX_RETRIES + 1):
            for engine in sync_engines:
                if attempts >= _MAX_ENGINE_ATTEMPTS:
                    break
                attempts += 1
                resp = self._try_sync_engine(engine, url, params, merged_headers, timeout)
                if self._accept(engine, url, resp):
                    return resp
                if resp:
                    last_response = resp
                    definitive = definitive or _is_definitive(resp)
            if definitive or attempts >= _MAX_ENGINE_ATTEMPTS or round_no == _MAX_RETRIES:
                break
            time.sleep(_RETRY_BACKOFF_BASE * (2 ** (round_no - 1)))

        remaining = _MAX_ENGINE_ATTEMPTS - attempts
        if not definitive and "httpx" in engines and remaining > 0:
            async_resp = self._run_on_shared_loop(
                self.get(url, params=params, headers=headers, timeout=timeout,
                         only_engines=["httpx"], _solve_since=solve_gen,
                         _max_attempts=remaining),
                timeout,
            )
            if async_resp is not None and async_resp.status_code > 0:
                return async_resp

        return self._give_up(url, last_response, solve_gen)

    @staticmethod
    def _run_on_shared_loop(coro, timeout: int):
        """Run *coro* on the app's global event loop (never a throwaway one,
        which orphaned this session's clients). Returns None if that is not
        possible without blocking the loop itself."""
        try:
            asyncio.get_running_loop()
            coro.close()      # called from inside a loop: blocking here would deadlock
            return None
        except RuntimeError:
            pass
        from core import async_loop
        try:
            fut = async_loop.submit(coro)
        except RuntimeError:
            # submit() failed, so the coroutine was never scheduled. No global
            # loop (e.g. tests, standalone tools): run it locally. During app
            # shutdown do not start a throwaway loop.
            if getattr(async_loop, "_SHUTTING_DOWN", False):
                coro.close()
                return None
            return asyncio.run(coro)
        try:
            return fut.result(timeout=timeout + 10)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            log.debug("async fallback timed out")
            return None
        except Exception as e:
            # Already awaited on the loop: never run it a second time.
            log.debug("async fallback failed: %s", e)
            return None

    def _try_sync_engine(
        self, engine: str, url: str, params: dict | None,
        headers: dict, timeout: int,
    ) -> Optional[BypassResponse]:
        """Dispatch a single synchronous engine attempt (no asyncio)."""
        if engine == "curl_cffi":
            return _try_curl_cffi_sync(
                url, params, headers, self._cookies_for(url), self.proxy_url,
                timeout, self._cffi_sync_sessions, winner_hint=self._cffi_winner,
            )
        elif engine == "cloudscraper":
            return _try_cloudscraper_sync(
                url, params, headers, self._cookies_for(url), self.proxy_url, timeout,
            )
        elif engine == "requests":
            return _try_requests_sync(
                url, params, headers, self._cookies_for(url), self.proxy_url, timeout,
            )
        elif engine == "urllib":
            return _try_urllib_sync(
                url, params, headers, self._cookies_for(url), self.proxy_url, timeout,
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
            site_url=self.site_url,
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
