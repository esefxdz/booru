"""Which proxy a request uses: the app setting, else the system proxy (like a browser)."""
from __future__ import annotations

import functools
import urllib.request
from urllib.parse import urlsplit


def _system_proxies() -> dict:
    # HTTP(S)_PROXY env vars, else the Windows Internet Options proxy.
    return urllib.request.getproxies()


@functools.lru_cache(maxsize=256)
def _bypassed(host: str) -> bool:
    from core.validation import is_private_host
    if is_private_host(host):           # localhost / LAN boorus never go through it
        return True
    try:
        return bool(urllib.request.proxy_bypass(host))   # may do a DNS lookup: cached
    except Exception:
        return False


def effective_proxy(url: str = "") -> str:
    """Proxy URL for *url*, or "" for a direct connection."""
    from core import settings
    app = (getattr(settings.manager, "proxy_url", "") or "").strip()
    if app:
        return app
    proxies = _system_proxies()
    if not proxies:
        return ""
    parts = urlsplit(url) if url else None
    if parts and parts.hostname and _bypassed(parts.hostname.lower()):
        return ""
    scheme = (parts.scheme if parts and parts.scheme else "https").lower()
    proxy = proxies.get(scheme) or proxies.get("https") or proxies.get("http") or ""
    if proxy and "://" not in proxy:
        proxy = "http://" + proxy
    return proxy
