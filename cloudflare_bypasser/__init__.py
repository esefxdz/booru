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
# Public helpers
# ---------------------------------------------------------------------------

def get_session(booru_name: str) -> BypassSession:
    """
    Build a :class:`BypassSession` for *booru_name*.

    Always returns a valid session with at least one working engine
    (urllib is always available).  Callers should never need to guard
    against None.

    The bypass method is read from ``settings.manager.cf_bypass_method``
    and defaults to ``"auto"`` (try all engines in priority order).
    """
    from ui import settings_view as settings  # lazy — keeps the package importable before settings init
    return BypassSession(
        user_agent=_store.get_user_agent(booru_name),
        cookies=_store.get_cookies(booru_name),
        proxy_url=settings.manager.proxy_url,
        method=getattr(settings.manager, "cf_bypass_method", "auto"),
    )


def invalidate_session(booru_name: str) -> None:
    """Clear stored bypass data for *booru_name* (no-op if nothing stored)."""
    _store.clear_bypass(booru_name)


# ---------------------------------------------------------------------------
# Expose key types
# ---------------------------------------------------------------------------

__all__ = [
    "BypassSession",
    "BypassResponse",
    "get_session",
    "invalidate_session",
    "get_available_engines",
    "BYPASS_METHODS",
    "BYPASS_METHOD_LABELS",
    "ENGINE_ORDER",
    "store",
]
