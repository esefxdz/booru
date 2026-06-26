"""
cloudflare_bypasser/fingerprint.py — Browser identity & engine configuration.

Constants and helpers that define *what* the bypass looks like to
Cloudflare: User-Agent, TLS impersonation targets, browser-grade
headers, retry parameters, and the engine availability registry.

Extracted from session.py so the orchestrator stays thin.
"""

from __future__ import annotations

import logging

log = logging.getLogger("cloudflare_bypasser")

# ---------------------------------------------------------------------------
# Optional engine imports — never crash on ImportError
# ---------------------------------------------------------------------------
_HAS_CURL_CFFI = False
cffi_requests = None  # type: ignore
try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    pass

_HAS_CLOUDSCRAPER = False
_cloudscraper = None  # type: ignore
try:
    import cloudscraper as _cloudscraper
    _HAS_CLOUDSCRAPER = True
except ImportError:
    pass

_HAS_HTTPX = False
httpx = None  # type: ignore
try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    pass

_HAS_REQUESTS = False
_requests_lib = None  # type: ignore
try:
    import requests as _requests_lib
    _HAS_REQUESTS = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Browser identity
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

# ---------------------------------------------------------------------------
# curl-cffi impersonation targets
# ---------------------------------------------------------------------------
# Try latest Chrome first, then fall back.  Kept to 4 entries: walking a
# long list sequentially on every 403 was the main source of UI hangs.
# The session tracks which target last succeeded (_cffi_winner) and tries
# it first so the common path costs one attempt.
_IMPERSONATE_TARGETS = [
    "chrome131", "chrome124", "chrome120", "edge101",
]

# ---------------------------------------------------------------------------
# Retry / timeout parameters
# ---------------------------------------------------------------------------
_DEFAULT_TIMEOUT = 30
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 0.5  # seconds, doubles each retry

# ---------------------------------------------------------------------------
# Engine registry
# ---------------------------------------------------------------------------

# All known engine identifiers (order = default priority)
ENGINE_ORDER = ["curl_cffi", "cloudscraper", "httpx", "requests", "urllib"]

# Valid method choices for the settings dropdown
BYPASS_METHODS = ["auto"] + ENGINE_ORDER

# Human-readable labels for the settings UI
BYPASS_METHOD_LABELS = {
    "auto":         "Auto (try all engines)",
    "curl_cffi":    "curl_cffi \u2014 Chrome TLS fingerprint",
    "cloudscraper": "cloudscraper \u2014 JS challenge solver",
    "httpx":        "httpx \u2014 HTTP/2 modern client",
    "requests":     "requests \u2014 Classic HTTP client",
    "urllib":       "urllib \u2014 Stdlib fallback",
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
