"""HTTP download engines (urllib, requests, httpx, curl_cffi), each ``fn(url, dest, headers, on_progress) -> bool``. TLS certificates are always verified."""

from __future__ import annotations

import logging
import ssl
import threading
import urllib.error
import urllib.request
from pathlib import Path

from core.validation import SameSiteRedirectHandler
from typing import Callable

log = logging.getLogger("image_downloader")


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
    """The configured proxy ("" = direct); read per download so changes apply at once."""
    try:
        from core import settings
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
    # urllib returns fewer bytes on an early close instead of raising.
    if total and downloaded < total:
        raise IOError(f"incomplete download: {downloaded} of {total} bytes")


def _download_urllib(url: str, dest: Path, headers: dict,
                     on_progress: Callable | None = None) -> bool:
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    handlers: list = [urllib.request.HTTPSHandler(context=ctx), SameSiteRedirectHandler()]
    proxy = _proxy_url()
    if proxy:
        if not proxy.lower().startswith(("http://", "https://")):
            # urllib has no SOCKS support; fail rather than silently go direct.
            log.error("urllib: proxy %r is not HTTP; choose another download engine", proxy.split("@")[-1])
            return False
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        # Without this, build_opener would use the HTTP(S)_PROXY / system proxy.
        handlers.append(urllib.request.ProxyHandler({}))
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


# requests.Session is not thread-safe and downloads run on several threads,
# so each thread gets its own session.
_requests_local = threading.local()
_requests_sessions: list = []  # for shutdown()
_requests_sessions_lock = threading.Lock()


def _requests_session():
    import requests as _req
    s = getattr(_requests_local, "session", None)
    if s is None:
        s = _requests_local.session = _req.Session()
        with _requests_sessions_lock:
            _requests_sessions.append(s)
    return s


def _download_requests(url: str, dest: Path, headers: dict,
                       on_progress: Callable | None = None) -> bool:
    import requests as _req

    proxy = _proxy_url()
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        with _requests_session().get(url, headers=headers, stream=True, timeout=_TIMEOUT,
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


_httpx_client = None
_httpx_client_key = None


def _download_httpx(url: str, dest: Path, headers: dict,
                    on_progress: Callable | None = None) -> bool:
    import httpx
    global _httpx_client, _httpx_client_key
    from core import settings

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


def _download_curl_cffi(url: str, dest: Path, headers: dict,
                        on_progress: Callable | None = None) -> bool:
    """curl_cffi with Chrome TLS impersonation.

    In stream mode the timeout is connect plus idle only, so slow big files finish.
    """
    from curl_cffi import requests as cffi_req

    proxy = _proxy_url()
    with cffi_req.Session(impersonate="chrome136") as s:
        try:
            r = s.request("GET", url, headers=headers, timeout=_TIMEOUT, stream=True,
                          allow_redirects=True,
                          proxies={"http": proxy, "https": proxy} if proxy else None)
        except Exception as e:
            if _is_tls_error(e):
                log.error("curl_cffi: TLS certificate verification failed for %s: %s", url, e)
                return False
            raise
        try:
            if r.status_code != 200:
                log.warning("curl_cffi: HTTP %s for %s", r.status_code, url)
                return False
            total = int(r.headers.get("Content-Length", 0) or 0)
            # iter_content ignores (and warns about) chunk_size.
            _write_stream(dest, r.iter_content(), total, on_progress)
        finally:
            r.close()   # stops the transfer thread on early exit
    return True


ENGINE_FNS: dict[str, Callable] = {
    "urllib":     _download_urllib,
    "requests":   _download_requests,
    "httpx":      _download_httpx,
    "curl_cffi":  _download_curl_cffi,
}


def shutdown():
    global _httpx_client
    with _requests_sessions_lock:
        for s in _requests_sessions:
            s.close()
        _requests_sessions.clear()
    _requests_local.__dict__.clear()
    if _httpx_client is not None:
        _httpx_client.close()
        _httpx_client = None


def get_available_engines() -> list[str]:
    import importlib.util
    available = ["urllib"]
    for name in ("requests", "httpx", "curl_cffi"):
        if importlib.util.find_spec(name) is not None:
            available.append(name)
    return available
