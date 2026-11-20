"""BypassSession.download_sync: fetch a URL straight to a file."""

from __future__ import annotations

import logging
import os
from typing import Optional

from cloudflare_bypasser.engines import (
    BypassResponse,
    _extract_cookies,
    _lower_headers,
    _refuse_non_http,
)
from cloudflare_bypasser.fingerprint import (
    _DEFAULT_TIMEOUT,
    _HAS_CURL_CFFI,
    _IMPERSONATE_TARGETS,
    cffi_requests,
)
from core.validation import redact_secrets as _redact

log = logging.getLogger("cloudflare_bypasser")


def _unlink_quiet(path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


class FileDownloadMixin:
    """download_sync for BypassSession (uses its engines, cookies and breaker)."""

    def download_sync(
        self,
        url: str,
        dest,
        headers: dict | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> BypassResponse:
        """Fetch *url* into the file *dest* without holding it in memory.

        curl_cffi streams in chunks; in stream mode its float ``timeout`` is
        a connect timeout plus an idle timeout (no total cap), so a slow but
        flowing transfer finishes. Data goes to ``<dest>.part`` and is
        renamed only when complete, so *dest* never holds a partial file.
        Anything the streaming path cannot settle (curl_cffi missing, a
        non-200 answer, a transport error) goes through :meth:`get_sync`
        (circuit breaker, retries, other engines) and its body is written
        out. Returns a BypassResponse; on 200 ``content`` is empty, the data
        being in *dest*.
        """
        self._enter()
        try:
            refused = _refuse_non_http(url)
            if refused is not None:
                return refused
            open_resp = self._circuit_open(url)
            if open_resp is not None:
                return open_resp
            if _HAS_CURL_CFFI and "curl_cffi" in self._get_engine_order():
                resp = self._stream_curl_cffi(url, dest, self._build_headers(headers), timeout)
                if resp is not None:
                    return resp
            resp = self._get_sync(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                part = f"{dest}.part"
                try:
                    with open(part, "wb") as f:
                        f.write(resp.content)
                    os.replace(part, dest)
                except BaseException:
                    _unlink_quiet(part)
                    raise
                resp.content = b""
            return resp
        finally:
            self._leave()

    def _stream_curl_cffi(self, url, dest, headers, timeout) -> Optional[BypassResponse]:
        """Stream a 200 answer to *dest*. None means "use the normal path"."""
        proxy = self.proxy_url
        proxies = {"http": proxy, "https": proxy} if proxy else None
        target = self._cffi_winner if self._cffi_winner in _IMPERSONATE_TARGETS \
            else _IMPERSONATE_TARGETS[0]
        if target not in self._cffi_sync_sessions:
            self._cffi_sync_sessions[target] = cffi_requests.Session(
                impersonate=target, proxies=proxies, verify=True)
        session = self._cffi_sync_sessions[target]
        part = f"{dest}.part"
        try:
            r = session.get(url, headers=headers, cookies=self._cookies_for(url),
                            timeout=timeout, allow_redirects=True, stream=True)
        except Exception as e:
            log.debug("curl_cffi stream failed for %s: %s", _redact(url), _redact(e))
            return None
        try:
            if r.status_code != 200:
                return None
            total = int(r.headers.get("Content-Length", 0) or 0)
            got = 0
            with open(part, "wb") as f:
                for chunk in r.iter_content():
                    f.write(chunk)
                    got += len(chunk)
            if total and got < total:
                raise IOError(f"incomplete download: {got} of {total} bytes")
            os.replace(part, dest)
        except Exception as e:
            _unlink_quiet(part)
            log.debug("curl_cffi stream aborted for %s: %s", _redact(url), _redact(e))
            return None
        finally:
            r.close()
        resp = BypassResponse(b"", "", 200, r.url, None, f"curl_cffi/{target}",
                              _extract_cookies(r), headers=_lower_headers(r.headers))
        self._accept("curl_cffi", url, resp)
        return resp
