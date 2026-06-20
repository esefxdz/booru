"""
download_images/engines.py — HTTP download engine functions.

Each engine is a plain function with the same signature:
    fn(url, dest_path, headers, on_progress) -> bool

Engines are ordered from most reliable to most advanced:
  1. urllib       — Python stdlib.  Always available.
  2. requests     — Popular library.  Good redirect/cookie handling.
  3. httpx        — Modern async-capable client.  HTTP/2 support.
  4. curl_cffi    — TLS fingerprint impersonation.  Bypasses CF CDNs.
  5. powershell   — Invoke-WebRequest.  No Python deps needed.

SSL policy
----------
Each engine tries with SSL verification enabled first.  If the connection
fails with an SSL error (common on CDNs with non-standard cert chains or
on corporate machines doing TLS inspection), it retries with
``verify=False`` and logs a WARNING so the user and developer can see it.
A silent unconditional ``verify=False`` would allow undetected MITM attacks
on hostile networks (hotel Wi-Fi, etc.).
"""

from __future__ import annotations

import logging
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

log = logging.getLogger("image_downloader")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Constants                                                          ║
# ╚══════════════════════════════════════════════════════════════════════╝

ENGINES: list[str] = ["urllib", "requests", "httpx", "curl_cffi", "powershell"]

ENGINE_LABELS: dict[str, str] = {
    "urllib":      "urllib (Built-in — most reliable)",
    "requests":    "requests (Popular — good redirects)",
    "httpx":       "httpx (Modern — HTTP/2 support)",
    "curl_cffi":   "curl_cffi (Advanced — TLS impersonation)",
    "powershell":  "PowerShell (System — no Python deps)",
}

DEFAULT_ENGINE = "urllib"


# ═══════════════════════════════════════════════════════════════════════
#  Engine 1 — urllib (Python stdlib, always available)
# ═══════════════════════════════════════════════════════════════════════

def _download_urllib(url: str, dest: Path, headers: dict,
                     on_progress: Callable | None = None) -> bool:
    """Download using Python's built-in urllib.

    Tries with SSL verification enabled first; falls back to
    ``CERT_NONE`` only on SSL failure, logging a warning.
    """
    req = urllib.request.Request(url, headers=headers)

    def _attempt(verify: bool) -> bool:
        ctx = ssl.create_default_context()
        if not verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        try:
            resp = urllib.request.urlopen(req, timeout=60, context=ctx)
        except urllib.error.HTTPError as e:
            log.warning("urllib: HTTP %s for %s", e.code, url)
            return False

        if resp.status != 200:
            log.warning("urllib: HTTP %s for %s", resp.status, url)
            return False

        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress and total:
                    on_progress(downloaded, total)
        return True

    try:
        return _attempt(verify=True)
    except ssl.SSLError:
        log.warning("urllib: SSL verification failed for %s — retrying without verification", url)
        return _attempt(verify=False)


# ═══════════════════════════════════════════════════════════════════════
#  Engine 2 — requests (popular third-party library)
# ═══════════════════════════════════════════════════════════════════════

_requests_session_verify_true = None
_requests_session_verify_false = None

def _download_requests(url: str, dest: Path, headers: dict,
                        on_progress: Callable | None = None) -> bool:
    """Download using the ``requests`` library."""
    import requests as _req
    global _requests_session_verify_true, _requests_session_verify_false

    def _attempt(verify: bool) -> bool:
        global _requests_session_verify_true, _requests_session_verify_false
        if verify:
            if _requests_session_verify_true is None:
                _requests_session_verify_true = _req.Session()
            session = _requests_session_verify_true
        else:
            if _requests_session_verify_false is None:
                _requests_session_verify_false = _req.Session()
                _requests_session_verify_false.verify = False
            session = _requests_session_verify_false

        with session.get(url, headers=headers, stream=True, timeout=60, verify=verify) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress and total:
                        on_progress(downloaded, total)
        return True

    try:
        return _attempt(verify=True)
    except _req.exceptions.SSLError:
        log.warning("requests: SSL verification failed for %s — retrying without verification", url)
        return _attempt(verify=False)


# ═══════════════════════════════════════════════════════════════════════
#  Engine 3 — httpx (modern async-capable client)
# ═══════════════════════════════════════════════════════════════════════

_httpx_client_verify_true = None
_httpx_client_verify_false = None

def _download_httpx(url: str, dest: Path, headers: dict,
                     on_progress: Callable | None = None) -> bool:
    """Download using ``httpx`` with streaming."""
    import httpx
    global _httpx_client_verify_true, _httpx_client_verify_false

    def _attempt(verify: bool) -> bool:
        global _httpx_client_verify_true, _httpx_client_verify_false
        from ui import settings_view as settings
        use_h2 = getattr(settings.manager, "use_http2", False)
        
        if verify:
            if _httpx_client_verify_true is None:
                _httpx_client_verify_true = httpx.Client(verify=True, timeout=60, follow_redirects=True, http2=use_h2)
            client = _httpx_client_verify_true
        else:
            if _httpx_client_verify_false is None:
                _httpx_client_verify_false = httpx.Client(verify=False, timeout=60, follow_redirects=True, http2=use_h2)
            client = _httpx_client_verify_false

        with client.stream("GET", url, headers=headers) as r:
            if r.status_code != 200:
                log.warning("httpx: HTTP %s for %s", r.status_code, url)
                return False
            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress and total:
                        on_progress(downloaded, total)
        return True

    try:
        return _attempt(verify=True)
    except httpx.ConnectError as e:
        if "SSL" in str(e) or "certificate" in str(e).lower():
            log.warning("httpx: SSL verification failed for %s — retrying without verification", url)
            return _attempt(verify=False)
        raise


# ═══════════════════════════════════════════════════════════════════════
#  Engine 4 — curl_cffi (Chrome TLS fingerprint impersonation)
# ═══════════════════════════════════════════════════════════════════════

def _download_curl_cffi(url: str, dest: Path, headers: dict,
                         on_progress: Callable | None = None) -> bool:
    """Download using ``curl_cffi`` with Chrome TLS impersonation."""
    from curl_cffi import requests as cffi_req

    def _attempt(verify: bool) -> bool:
        r = cffi_req.get(url, headers=headers, impersonate="chrome136",
                         timeout=60, verify=verify, allow_redirects=True)
        if r.status_code != 200:
            log.warning("curl_cffi: HTTP %s for %s", r.status_code, url)
            return False

        content = r.content
        with open(dest, "wb") as f:
            f.write(content)
        if on_progress:
            on_progress(len(content), len(content))
        return True

    try:
        return _attempt(verify=True)
    except Exception as e:
        if "ssl" in str(e).lower() or "certificate" in str(e).lower():
            log.warning("curl_cffi: SSL verification failed for %s — retrying without verification", url)
            return _attempt(verify=False)
        raise


# ═══════════════════════════════════════════════════════════════════════
#  Engine 5 — PowerShell Invoke-WebRequest (system-level, last resort)
# ═══════════════════════════════════════════════════════════════════════

def _download_powershell(url: str, dest: Path, headers: dict,
                          on_progress: Callable | None = None) -> bool:
    """Download using PowerShell's Invoke-WebRequest."""
    header_args = "; ".join(f"'{k}'='{v}'" for k, v in headers.items())
    ps_cmd = (
        f'$headers = @{{{header_args}}}; '
        f'[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; '
        f'Invoke-WebRequest -Uri "{url}" -OutFile "{dest}" '
        f'-Headers $headers -UseBasicParsing'
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        # If SSL is the cause, retry with SkipCertificateCheck
        if "ssl" in result.stderr.lower() or "certificate" in result.stderr.lower():
            log.warning("powershell: SSL error for %s — retrying with -SkipCertificateCheck", url)
            ps_cmd_nossl = ps_cmd + " -SkipCertificateCheck"
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd_nossl],
                capture_output=True, text=True, timeout=120,
            )
        if result.returncode != 0:
            log.warning("powershell: %s", result.stderr.strip())
            return False
    if on_progress and dest.exists():
        sz = dest.stat().st_size
        on_progress(sz, sz)
    return True


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Engine registry — maps engine name to its download function        ║
# ╚══════════════════════════════════════════════════════════════════════╝

ENGINE_FNS: dict[str, Callable] = {
    "urllib":     _download_urllib,
    "requests":   _download_requests,
    "httpx":      _download_httpx,
    "curl_cffi":  _download_curl_cffi,
    "powershell": _download_powershell,
}

def shutdown():
    """Close any globally cached sessions to avoid unclosed socket warnings on exit."""
    global _requests_session_verify_true, _requests_session_verify_false
    if _requests_session_verify_true is not None:
        _requests_session_verify_true.close()
    if _requests_session_verify_false is not None:
        _requests_session_verify_false.close()

    global _httpx_client_verify_true, _httpx_client_verify_false
    if _httpx_client_verify_true is not None:
        _httpx_client_verify_true.close()
    if _httpx_client_verify_false is not None:
        _httpx_client_verify_false.close()


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Availability checker — which engines are importable right now?      ║
# ╚══════════════════════════════════════════════════════════════════════╝

def get_available_engines() -> list[str]:
    """Return list of engines that can actually run on this system."""
    available = ["urllib"]  # always present
    try:
        import requests; available.append("requests")
    except ImportError:
        pass
    try:
        import httpx; available.append("httpx")
    except ImportError:
        pass
    try:
        import curl_cffi; available.append("curl_cffi")
    except ImportError:
        pass
    if shutil.which("powershell"):
        available.append("powershell")
    return available
