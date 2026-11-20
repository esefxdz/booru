"""Per-host circuit breaker: after a Cloudflare block, pause that host."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

log = logging.getLogger("cloudflare_bypasser")

#: After a Cloudflare challenge, stop hitting that host for this long.
_BLOCK_COOLDOWN = 30.0


def _host_of(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


# Circuit-breaker state is module-level, not per BypassSession: api_client
# drops the cached session after a block, and a fresh session must not
# forget that the host is blocking us. Keyed by (host, port) so two
# self-hosted boorus on one machine do not pause each other. Touched from
# the asyncio thread and from worker threads (get_sync), hence the lock.
_blocked_until: dict[tuple[str, int], float] = {}   # (host, port) -> monotonic deadline
_blocked_lock = threading.Lock()
# Bumped by reset_circuit (a solved challenge), per site. A request captures
# it when it starts; if it changed by the time the request ends blocked, the
# block is stale (sent without the new clearance) and must not re-arm.
_solve_gen: dict[str, int] = {}                       # site_key(host) -> count


def _circuit_key(url: str) -> tuple[str, int]:
    from urllib.parse import urlparse
    try:
        u = urlparse(url)
        port = u.port
    except ValueError:
        return ("", 0)
    if port is None:
        port = 443 if (u.scheme or "").lower() == "https" else 80
    return ((u.hostname or "").lower(), port)


def _solve_key(url: str) -> str:
    from validation import site_key
    host = _host_of(url)
    return site_key(host) if host else ""


def solve_generation(url: str) -> int:
    """How many times the challenge was solved for *url*'s site."""
    key = _solve_key(url)
    with _blocked_lock:
        return _solve_gen.get(key, 0)


def _open_circuit(url: str, solve_gen: Optional[int] = None) -> None:
    """Open the breaker for *url*. With *solve_gen*, only if no challenge
    was solved since the request that saw the block captured it."""
    key = _solve_key(url) if solve_gen is not None else ""
    with _blocked_lock:
        if solve_gen is not None and _solve_gen.get(key, 0) != solve_gen:
            log.debug("Not opening circuit for %s: solved since request started", _host_of(url))
            return
        _blocked_until[_circuit_key(url)] = time.monotonic() + _BLOCK_COOLDOWN


def _close_circuit(url: str) -> None:
    with _blocked_lock:
        _blocked_until.pop(_circuit_key(url), None)


def _circuit_is_open(url: str) -> bool:
    key = _circuit_key(url)
    with _blocked_lock:
        until = _blocked_until.get(key)
        if until is None:
            return False
        if time.monotonic() < until:
            return True
        del _blocked_until[key]
        return False


def reset_circuit(site_url: str) -> None:
    """Close the breaker for every host on *site_url*'s site (the API host
    and its CDN hosts alike). Call after the user has solved the challenge."""
    from validation import site_key
    host = _host_of(site_url)
    if not host:
        return
    key = site_key(host)
    with _blocked_lock:
        _solve_gen[key] = _solve_gen.get(key, 0) + 1
        for k in [k for k in _blocked_until if k[0] == host or site_key(k[0]) == key]:
            del _blocked_until[k]


def reset_all_circuits() -> None:
    """Close every breaker (used by the test suite)."""
    with _blocked_lock:
        _blocked_until.clear()
        _solve_gen.clear()
