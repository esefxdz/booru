"""
cloudflare_bypasser/__init__.py

Public API for the Cloudflare bypass engine.

Usage:
    from cloudflare_bypasser import get_session
    session = get_session("danbooru")
    resp = await session.get("https://danbooru.donmai.us/posts.json", params={...})

The engine automatically tries curl_cffi → cloudscraper → httpx → requests
→ urllib, with retry and exponential backoff.  It never returns None — even
total failure gives a BypassResponse with status_code=0.

Users can lock to a specific engine via settings → Network → Bypass Method.
"""

from __future__ import annotations
import logging

from cloudflare_bypasser.session import (
    BypassSession,
    BypassResponse,
    _Response,
    BYPASS_METHODS,
    BYPASS_METHOD_LABELS,
    ENGINE_ORDER,
    get_available_engines,
)
from cloudflare_bypasser import store as _store

# Ensure the logger exists so consumers can configure it
log = logging.getLogger("cloudflare_bypasser")


# ---------------------------------------------------------------------------
# Session cache — one long-lived BypassSession per booru
# ---------------------------------------------------------------------------
# Before this cache, every call to get_session() created a brand-new
# BypassSession (and with it, a new curl_cffi.AsyncSession + TLS handshake).
# Callers like media_viewer._fetch_bytes() would create a session, use it
# once, and discard it — throwing away accumulated cookies and forcing a
# fresh TLS handshake on every image load.
#
# Now sessions are cached by booru name with a fingerprint that captures
# cookies, UA, proxy, and bypass method.  When any of those change (e.g.
# after a new CF bypass), the fingerprint mismatches and a fresh session
# replaces the stale one automatically.

_session_cache: dict[str, tuple[str, BypassSession]] = {}


def _session_fingerprint(booru_name: str) -> str:
    """Fingerprint of all settings that affect session construction."""
    from ui import settings_view as settings
    cookies = _store.get_cookies(booru_name)
    ua = _store.get_user_agent(booru_name)
    proxy = settings.manager.proxy_url or ""
    method = getattr(settings.manager, "cf_bypass_method", "auto")
    cookie_part = ",".join(f"{k}={v}" for k, v in sorted(cookies.items()))
    return f"{ua}|{cookie_part}|{proxy}|{method}"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_session(booru_name: str) -> BypassSession:
    """
    Return a long-lived :class:`BypassSession` for *booru_name*.

    Sessions are cached per booru and automatically replaced when cookies,
    User-Agent, proxy, or bypass method change.  Callers should NOT close
    the returned session — it is managed by this module and cleaned up at
    shutdown via :func:`close_all_sessions`.

    Always returns a valid session with at least one working engine
    (urllib is always available).  Callers should never need to guard
    against None.
    """
    fp = _session_fingerprint(booru_name)
    existing = _session_cache.get(booru_name)
    if existing is not None:
        old_fp, session = existing
        if old_fp == fp:
            return session
        # Fingerprint changed — discard old session (resources are
        # cleaned up at shutdown via close_all_sessions).
        log.debug("get_session: invalidating cached session for %s (fp changed)", booru_name)

    from ui import settings_view as settings
    session = BypassSession(
        user_agent=_store.get_user_agent(booru_name),
        cookies=_store.get_cookies(booru_name),
        proxy_url=settings.manager.proxy_url,
        method=getattr(settings.manager, "cf_bypass_method", "auto"),
    )
    _session_cache[booru_name] = (fp, session)
    log.debug("get_session: new cached session for %s", booru_name)
    return session


def invalidate_session(booru_name: str) -> None:
    """Clear stored bypass data AND the cached session for *booru_name*."""
    _store.clear_bypass(booru_name)
    _session_cache.pop(booru_name, None)


async def close_all_sessions():
    """Close all cached bypass sessions — call at app shutdown."""
    for _, (__, session) in list(_session_cache.items()):
        try:
            await session.close()
        except Exception:
            pass
    _session_cache.clear()
    log.debug("close_all_sessions: %d sessions closed", len(_session_cache))


# ---------------------------------------------------------------------------
# Expose key types
# ---------------------------------------------------------------------------

__all__ = [
    "BypassSession",
    "BypassResponse",
    "get_session",
    "invalidate_session",
    "close_all_sessions",
    "get_available_engines",
    "BYPASS_METHODS",
    "BYPASS_METHOD_LABELS",
    "ENGINE_ORDER",
    "store",
]
