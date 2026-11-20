"""Public API of the Cloudflare bypass engine: cached per-booru sessions."""

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
from cloudflare_bypasser.circuit_breaker import reset_circuit as _reset_circuit
from cloudflare_bypasser import store as _store

log = logging.getLogger("cloudflare_bypasser")


# One session per booru, replaced when its fingerprint (cookies, UA, proxy, method) changes.

_session_cache: dict[str, tuple[str, BypassSession]] = {}


def _session_fingerprint(booru_name: str) -> str:
    """Fingerprint of all settings that affect session construction."""
    from core import settings
    cookies = _store.get_cookies(booru_name)
    ua = _store.get_user_agent(booru_name)
    proxy = settings.manager.proxy_url or ""
    method = getattr(settings.manager, "cf_bypass_method", "auto")
    cookie_part = ",".join(f"{k}={v}" for k, v in sorted(cookies.items()))
    import boorus
    site = boorus.REGISTRY.get(booru_name, {}).get("url", "")
    return f"{ua}|{cookie_part}|{proxy}|{method}|{site}"


def get_session(booru_name: str) -> BypassSession:
    """Return the cached session for *booru_name*. Callers must not close it."""
    fp = _session_fingerprint(booru_name)
    existing = _session_cache.get(booru_name)
    if existing is not None:
        old_fp, session = existing
        if old_fp == fp:
            return session
        # Release the old session's clients once its in-flight requests finish.
        log.debug("get_session: invalidating cached session for %s (fp changed)", booru_name)
        _retire(session)

    from core import settings
    import boorus
    session = BypassSession(
        user_agent=_store.get_user_agent(booru_name),
        cookies=_store.get_cookies(booru_name),
        proxy_url=settings.manager.proxy_url,
        method=getattr(settings.manager, "cf_bypass_method", "auto"),
        site_url=boorus.REGISTRY.get(booru_name, {}).get("url", ""),
    )
    _session_cache[booru_name] = (fp, session)
    log.debug("get_session: new cached session for %s", booru_name)
    return session


def _retire(session) -> None:
    try:
        session.retire()
    except Exception:
        log.debug("retiring a replaced session failed", exc_info=True)


def _drop(booru_name: str) -> None:
    """Remove *booru_name*'s cached session and release it."""
    entry = _session_cache.pop(booru_name, None)
    if entry is not None:
        _retire(entry[1])


_UNSET = object()


def bypass_snapshot(booru_name: str):
    """Opaque token of the stored bypass data; pass it to :func:`invalidate_session`."""
    return _store.snapshot(booru_name)


def invalidate_session(booru_name: str, unless_changed_since=_UNSET) -> None:
    """Clear stored bypass data and the cached session for *booru_name*.

    With *unless_changed_since*, do nothing if the data changed since (a stale block)."""
    if unless_changed_since is _UNSET:
        _store.clear_bypass(booru_name)
    elif not _store.clear_bypass_if_unchanged(booru_name, unless_changed_since):
        log.debug("invalidate_session: %s re-solved since request started; keeping it", booru_name)
        return
    _drop(booru_name)


def bypass_solved(booru_name: str) -> None:
    """The user (or the auto-solver) just passed the challenge and the new
    cookies are already saved: drop the cached session WITHOUT touching the
    store, and reopen the host so the next request goes out."""
    _drop(booru_name)
    import boorus
    _reset_circuit(boorus.REGISTRY.get(booru_name, {}).get("url", ""))


async def close_all_sessions():
    """Close all cached bypass sessions — call at app shutdown."""
    for _, (__, session) in list(_session_cache.items()):
        try:
            await session.close()
        except Exception:
            log.debug("close_all_sessions: error closing session", exc_info=True)
    _session_cache.clear()


__all__ = [
    "BypassSession",
    "BypassResponse",
    "get_session",
    "invalidate_session",
    "bypass_snapshot",
    "bypass_solved",
    "close_all_sessions",
    "get_available_engines",
    "BYPASS_METHODS",
    "BYPASS_METHOD_LABELS",
    "ENGINE_ORDER",
    "store",
]
