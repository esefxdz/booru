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

from validation import redact_secrets as _redact

log = logging.getLogger("cloudflare_bypasser")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║                         BypassResponse                              ║
# ╚══════════════════════════════════════════════════════════════════════╝

class BypassResponse:
    """
    Immutable response wrapper.  All data is captured eagerly so the caller
    never holds a dangling reference to a closed socket/session.
    """

    __slots__ = ("content", "text", "status_code", "url", "_json_data", "engine_used", "cookies",
                 "headers")

    def __init__(
        self,
        content: bytes,
        text: str,
        status_code: int,
        url: object,
        json_data: object,
        engine_used: str = "unknown",
        cookies: dict | None = None,
        headers: dict | None = None,
    ) -> None:
        self.content = content
        self.text = text
        self.status_code = status_code
        self.url = url
        self._json_data = json_data
        self.engine_used = engine_used
        self.cookies = cookies or {}
        # Response headers, keys lower-cased ({} when the engine gave none).
        self.headers = headers or {}

    def json(self) -> object:
        if self._json_data is not None:
            return self._json_data
        import json as _json
        return _json.loads(self.text)

    @property
    def is_blocked(self) -> bool:
        """True when the site is refusing us: a Cloudflare challenge, or a
        403 that may be a block (tiny or undecodable body).

        This decides only "stop trying other engines and pause the host".
        It is NOT evidence that a stored clearance is bad; see
        :attr:`is_cf_challenge` for that.
        """
        if self.status_code not in (403, 503, 429):
            return False
        if self.is_cf_challenge:
            return True

        # A tiny 403 may be a Cloudflare firewall block ("error code: 1020")
        # or the origin's own refusal; either way another fingerprint is
        # worth one try and the host should not be hammered.
        if self.status_code == 403 and len(self.content) < 200:
            return True

        # Detect garbage / undecoded responses — some engines (cloudscraper)
        # return raw compressed bytes as "text" when Content-Encoding
        # (brotli/gzip) fails to decode.
        if self.status_code == 403 and len(self.text) > 50:
            first_char = self.text.strip()[0] if self.text.strip() else ''
            if first_char not in '<{[{"':
                return True

        return False

    @property
    def is_cf_challenge(self) -> bool:
        """True only on positive evidence of a Cloudflare challenge page: the
        ``cf-mitigated: challenge`` header or challenge markers in the body.

        Callers clear the stored cf_clearance on this, so a plain site 403
        (no evidence) must not trigger it.
        """
        if self.status_code not in (403, 503, 429):
            return False
        if str(self.headers.get("cf-mitigated", "")).strip().lower() == "challenge":
            return True

        # Check both decoded text and raw bytes (response may be brotli-compressed)
        text_lower = self.text[:4000].lower() if self.text else ""
        content_lower = self.content[:4000].lower() if self.content else b""

        for marker in _CF_MARKERS:
            if marker in text_lower or marker.encode() in content_lower:
                return True

        if "cf-ray" in text_lower and ("challenge" in text_lower or "captcha" in text_lower):
            return True

        if self.status_code == 403 and len(self.content) < 500 and b"cloudflare" in content_lower:
            return True

        return False

    def __repr__(self) -> str:
        return f"<BypassResponse [{self.status_code}] engine={self.engine_used} {_redact(self.url)}>"


_CF_MARKERS = (
    "cf-mitigated", "just a moment",
    "challenge-platform", "challenges.cloudflare.com",
    "checking your browser", "enable javascript",
    "cf-chl-bypass", "cf-chl-out",
    "turnstile", "cf_captcha",
)


def _lower_headers(h) -> dict:
    """Plain dict of response headers with lower-cased keys (any engine)."""
    try:
        if h is None:
            return {}
        return {str(k).lower(): str(v) for k, v in h.items()}
    except Exception:
        return {}


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
    except Exception as e:
        log.debug("cookie extraction failed: %s", e)
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
    # On a 403 try one other fingerprint, not all of them (each is a request).
    targets = targets[:2]

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
            result = BypassResponse(content, text, status_code, final_url, json_data, f"curl_cffi/{target}", cookies_resp,
                            headers=_lower_headers(getattr(resp, "headers", None)))

            if status_code != 403:
                return result

            log.debug("curl_cffi/%s got 403 for %s, trying next target", target, _redact(url))
            last_err = result

        except Exception as e:
            log.debug("curl_cffi/%s failed for %s: %s", target, _redact(url), _redact(e))
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
    # On a 403 try one other fingerprint, not all of them (each is a request).
    targets = targets[:2]

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
            result = BypassResponse(content, text, status_code, final_url, json_data, f"curl_cffi/{target}", cookies_resp,
                            headers=_lower_headers(getattr(resp, "headers", None)))

            if status_code != 403:
                return result

            log.debug("curl_cffi_sync/%s got 403 for %s, trying next target", target, _redact(url))
            last_err = result

        except Exception as e:
            log.debug("curl_cffi_sync/%s failed for %s: %s", target, _redact(url), _redact(e))
            last_err = None
            continue

    return last_err


# ---------------------------------------------------------------------------
# cloudscraper (sync)
# ---------------------------------------------------------------------------

def _set_site_scoped_cookies(jar, cookies: dict, url: str) -> None:
    """Put *cookies* in a requests-style *jar*, bound to *url*'s site.

    ``jar.update(dict)`` creates cookies with no domain, which http.cookiejar
    sends to every host, so they followed redirects to third parties. Binding
    them to ``.<registrable domain>`` keeps same-site CDN redirects working
    and stops them anywhere else.
    """
    if not cookies:
        return
    import ipaddress
    from urllib.parse import urlparse
    from validation import site_key
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return
    try:
        ipaddress.ip_address(host)
        domain = host                      # IP address: that exact host only
    except ValueError:
        key = site_key(host)
        if "." in key:
            domain = "." + key
        else:
            # Dotless host (localhost, an intranet name): cookiejar matches it
            # as "<host>.local", so bind to that. cookiejar also sends it to a
            # host literally named "<host>.local" and its subdomains (mDNS);
            # other dotless or dotted hosts never get it.
            domain = key + ".local"
    for k, v in cookies.items():
        jar.set(k, v, domain=domain, path="/")


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

        _set_site_scoped_cookies(scraper.cookies, cookies, url)

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
        return BypassResponse(content, text, status_code, final_url, json_data, "cloudscraper", cookies_resp,
                            headers=_lower_headers(getattr(resp, "headers", None)))
    except Exception as e:
        log.debug("cloudscraper failed for %s: %s", _redact(url), _redact(e))
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
            # The shared client has no cookie jar of its own (it would send
            # cookies to every host); the caller passes scoped cookies.
            if cookies:
                headers = {**headers, "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}
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
        return BypassResponse(content, text, status_code, final_url, json_data, "httpx", cookies_resp,
                            headers=_lower_headers(getattr(resp, "headers", None)))
    except Exception as e:
        log.debug("httpx failed for %s: %s", _redact(url), _redact(e))
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
        _set_site_scoped_cookies(session.cookies, cookies, url)

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
        return BypassResponse(content, text, status_code, final_url, json_data, "requests", cookies_resp,
                            headers=_lower_headers(getattr(resp, "headers", None)))
    except Exception as e:
        log.debug("requests failed for %s: %s", _redact(url), _redact(e))
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

        import http.cookiejar
        from validation import SameSiteRedirectHandler
        # Was HTTPCookieProcessor(HTTPCookieProcessor()), which raised on every
        # request, so this "always available" fallback never worked.
        cookie_jar = http.cookiejar.CookieJar()
        handlers: list = [
            urllib.request.HTTPCookieProcessor(cookie_jar),
            SameSiteRedirectHandler(),   # don't forward Cookie to other sites
        ]

        if proxy_url:
            proxy_handler = urllib.request.ProxyHandler({
                "http": proxy_url,
                "https": proxy_url,
            })
            handlers.append(proxy_handler)
        else:
            # No app proxy means a direct connection. Without this,
            # build_opener adds a default ProxyHandler that picks up
            # HTTP(S)_PROXY and the Windows registry proxy, unlike the
            # other engines given proxies=None.
            handlers.append(urllib.request.ProxyHandler({}))

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
        return BypassResponse(content, text, status_code, final_url, json_data, "urllib", cookies_resp,
                            headers=_lower_headers(getattr(resp, "headers", None)))
    except urllib.error.HTTPError as e:
        content = e.read() if hasattr(e, "read") else b""
        text = content.decode("utf-8", errors="replace")
        return BypassResponse(content, text, e.code, url, None, "urllib", {},
                              headers=_lower_headers(getattr(e, "headers", None)))
    except Exception as e:
        log.debug("urllib failed for %s: %s", _redact(url), _redact(e))
        return None


def _refuse_non_http(url) -> Optional[BypassResponse]:
    """Return a status-0 response for anything that is not an absolute
    http(s) URL. Server-supplied URLs reach this layer, and urllib/curl
    would otherwise open file:// and similar schemes."""
    from validation import ValidationError, require_http_url
    try:
        require_http_url(url)
        return None
    except ValidationError as e:
        log.warning("Refusing request: %s", e)
        return BypassResponse(b"", "", 0, str(url), None, "refused")
