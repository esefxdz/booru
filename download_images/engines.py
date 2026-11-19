"""
download_images/engines.py — HTTP download engine functions.

Each engine is a plain function with the same signature:
    fn(url, dest_path, headers, on_progress) -> bool

Engines are ordered from most reliable to most advanced:
  1. urllib       — Python stdlib.  Always available.
  2. requests     — Popular library.  Good redirect/cookie handling.
  3. httpx        — Modern client.  HTTP/2 support.
  4. curl_cffi    — TLS fingerprint impersonation.  Bypasses CF CDNs.

SSL policy
----------
Certificates are always verified. A verification failure is exactly what a
man-in-the-middle looks like, and these requests can carry session cookies,
so the download fails with a logged error instead of retrying insecurely.
"""

from __future__ import annotations

import logging
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from validation import SameSiteRedirectHandler
from typing import Callable

log = logging.getLogger("image_downloader")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Constants                                                          ║
# ╚══════════════════════════════════════════════════════════════════════╝

ENGINES: list[str] = ["urllib", "requests", "httpx", "curl_cffi"]

ENGINE_LABELS: dict[str, str] = {
    "urllib":      "urllib (Built-in — most reliable)",
    "requests":    "requests (Popular — good redirects)",
    "httpx":       "httpx (Modern — HTTP/2 support)",
    "curl_cffi":   "curl_cffi (Advanced — TLS impersonation)",
}

DEFAULT_ENGINE = "urllib"

_TIMEOUT = 60
_CHUNK = 65536


def _proxy_url() -> str:
    """The user's configured proxy ("" = direct). Read on every download so a
    settings change applies immediately."""
    try:
        from ui import settings_view as settings
        return (getattr(settings.manager, "proxy_url", "") or "").strip()
    except Exception:
        return ""


def _is_tls_error(e: BaseException) -> bool:
    if isinstance(e, ssl.SSLError):
        return True
    if isinstance(getattr(e, "reason", None), ssl.SSLError):
        return True
    text = str(e).lower()
    return "certificate" in text or "ssl" in text


def _write_stream(dest: Path, chunks, total: int, on_progress: Callable | None) -> None:
    downloaded = 0
    with open(dest, "wb") as f:
        for chunk in chunks:
            if not chunk:
                continue
            f.write(chunk)
            downloaded += len(chunk)
            if on_progress and total:
                on_progress(downloaded, total)


# ═══════════════════════════════════════════════════════════════════════
#  Engine 1 — urllib (Python stdlib, always available)
# ═══════════════════════════════════════════════════════════════════════

def _download_urllib(url: str, dest: Path, headers: dict,
                     on_progress: Callable | None = None) -> bool:
    """Download using Python's built-in urllib."""
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    handlers: list = [urllib.request.HTTPSHandler(context=ctx), SameSiteRedirectHandler()]
    proxy = _proxy_url()
    if proxy:
        if not proxy.lower().startswith(("http://", "https://")):
            # urllib has no SOCKS support. Fail instead of silently going direct.
            log.error("urllib: proxy %r is not HTTP; choose another download engine", proxy.split("@")[-1])
            return False
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    try:
        resp = opener.open(req, timeout=_TIMEOUT)
    except urllib.error.HTTPError as e:
        log.warning("urllib: HTTP %s for %s", e.code, url)
        return False
    except (ssl.SSLError, urllib.error.URLError) as e:
        if _is_tls_error(e):
            log.error("urllib: TLS certificate verification failed for %s: %s", url, e)
            return False
        raise

    with resp:
        if resp.status != 200:
            log.warning("urllib: HTTP %s for %s", resp.status, url)
            return False
        total = int(resp.headers.get("Content-Length", 0) or 0)
        _write_stream(dest, iter(lambda: resp.read(_CHUNK), b""), total, on_progress)
    return True


# ═══════════════════════════════════════════════════════════════════════
#  Engine 2 — requests (popular third-party library)
# ═══════════════════════════════════════════════════════════════════════

_requests_session = None


def _download_requests(url: str, dest: Path, headers: dict,
                       on_progress: Callable | None = None) -> bool:
    """Download using the ``requests`` library."""
    import requests as _req
    global _requests_session
    if _requests_session is None:
        _requests_session = _req.Session()

    proxy = _proxy_url()
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        with _requests_session.get(url, headers=headers, stream=True, timeout=_TIMEOUT,
                                   proxies=proxies) as r:
            if r.status_code != 200:
                log.warning("requests: HTTP %s for %s", r.status_code, url)
                return False
            total = int(r.headers.get("Content-Length", 0) or 0)
            _write_stream(dest, r.iter_content(chunk_size=_CHUNK), total, on_progress)
        return True
    except _req.exceptions.SSLError as e:
        log.error("requests: TLS certificate verification failed for %s: %s", url, e)
        return False


# ═══════════════════════════════════════════════════════════════════════
#  Engine 3 — httpx (modern client, optional HTTP/2)
# ═══════════════════════════════════════════════════════════════════════

_httpx_client = None
_httpx_client_key = None


def _download_httpx(url: str, dest: Path, headers: dict,
                    on_progress: Callable | None = None) -> bool:
    """Download using ``httpx`` with streaming."""
    import httpx
    global _httpx_client, _httpx_client_key
    from ui import settings_view as settings

    use_h2 = getattr(settings.manager, "use_http2", False)
    proxy = _proxy_url()
    key = (use_h2, proxy)
    if _httpx_client is None or _httpx_client_key != key:
        if _httpx_client is not None:
            _httpx_client.close()
        _httpx_client = httpx.Client(timeout=_TIMEOUT, follow_redirects=True, http2=use_h2,
                                     proxy=proxy or None)
        _httpx_client_key = key

    try:
        with _httpx_client.stream("GET", url, headers=headers) as r:
            if r.status_code != 200:
                log.warning("httpx: HTTP %s for %s", r.status_code, url)
                return False
            total = int(r.headers.get("Content-Length", 0) or 0)
            _write_stream(dest, r.iter_bytes(_CHUNK), total, on_progress)
        return True
    except httpx.ConnectError as e:
        if _is_tls_error(e):
            log.error("httpx: TLS certificate verification failed for %s: %s", url, e)
            return False
        raise


# ═══════════════════════════════════════════════════════════════════════
#  Engine 4 — curl_cffi (Chrome TLS fingerprint impersonation)
# ═══════════════════════════════════════════════════════════════════════

def _download_curl_cffi(url: str, dest: Path, headers: dict,
                        on_progress: Callable | None = None) -> bool:
    """Download using ``curl_cffi`` with Chrome TLS impersonation."""
    from curl_cffi import requests as cffi_req

    try:
        proxy = _proxy_url()
        r = cffi_req.get(url, headers=headers, impersonate="chrome136",
                         timeout=_TIMEOUT, allow_redirects=True,
                         proxies={"http": proxy, "https": proxy} if proxy else None)
    except Exception as e:
        if _is_tls_error(e):
            log.error("curl_cffi: TLS certificate verification failed for %s: %s", url, e)
            return False
        raise

    if r.status_code != 200:
        log.warning("curl_cffi: HTTP %s for %s", r.status_code, url)
        return False
    content = r.content
    with open(dest, "wb") as f:
        f.write(content)
    if on_progress:
        on_progress(len(content), len(content))
    return True


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Engine registry — maps engine name to its download function        ║
# ╚══════════════════════════════════════════════════════════════════════╝

ENGINE_FNS: dict[str, Callable] = {
    "urllib":     _download_urllib,
    "requests":   _download_requests,
    "httpx":      _download_httpx,
    "curl_cffi":  _download_curl_cffi,
}


def shutdown():
    """Close any globally cached sessions to avoid unclosed socket warnings on exit."""
    global _requests_session, _httpx_client
    if _requests_session is not None:
        _requests_session.close()
        _requests_session = None
    if _httpx_client is not None:
        _httpx_client.close()
        _httpx_client = None


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Availability checker — which engines are importable right now?      ║
# ╚══════════════════════════════════════════════════════════════════════╝

def get_available_engines() -> list[str]:
    """Return list of engines that can actually run on this system."""
    import importlib.util
    available = ["urllib"]  # always present
    for name in ("requests", "httpx", "curl_cffi"):
        if importlib.util.find_spec(name) is not None:
            available.append(name)
    return available
