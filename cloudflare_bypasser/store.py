"""Per-booru Cloudflare clearance cookies and User-Agent, stored in settings.manager.bypass_data."""

from __future__ import annotations
import copy
import threading
from typing import TYPE_CHECKING
from core import settings

if TYPE_CHECKING:
    # Deferred to avoid a circular import.
    pass

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

# Saves come from the Qt thread (captcha flows), conditional clears from the
# network thread; this makes compare-and-clear atomic against a save.
_lock = threading.Lock()


def get_bypass_data(booru_name: str) -> dict:
    """Stored bypass dict for *booru_name*, or {}."""
    return settings.manager.bypass_data.get(booru_name) or {}


def get_cookies(booru_name: str) -> dict:
    """Return just the cookie dict for *booru_name* (may be empty)."""
    data = get_bypass_data(booru_name)
    cookies = data.get("cookies") or {}
    # Legacy: some entries only have cf_clearance stored directly
    if not cookies and data.get("cf_clearance"):
        cookies = {"cf_clearance": data["cf_clearance"]}
    return cookies


def get_user_agent(booru_name: str) -> str:
    """Return the stored User-Agent, falling back to a sane Chrome default."""
    return get_bypass_data(booru_name).get("user_agent") or _DEFAULT_UA


def has_active_bypass(booru_name: str) -> bool:
    """Return True when a cf_clearance or cookie set is stored for *booru_name*."""
    data = get_bypass_data(booru_name)
    return bool(data.get("cf_clearance") or data.get("cookies"))


def save_bypass(booru_name: str, cookies: dict, user_agent: str) -> None:
    """Persist both: Cloudflare ties the clearance cookie to the UA that solved it."""
    with _lock:
        settings.manager.bypass_data[booru_name] = {
            "cookies":    cookies,
            "user_agent": user_agent,
        }
    settings.manager.save()


def clear_bypass(booru_name: str) -> None:
    """Remove all stored bypass data for *booru_name*."""
    settings.manager.bypass_data.pop(booru_name, None)
    settings.manager.save()


def snapshot(booru_name: str):
    """A copy of what is stored for *booru_name* now (None if nothing)."""
    with _lock:
        return copy.deepcopy(settings.manager.bypass_data.get(booru_name))


def clear_bypass_if_unchanged(booru_name: str, expected) -> bool:
    """Clear only if the data still equals *expected* (a snapshot), so a stale block keeps a fresh clearance."""
    with _lock:
        current = settings.manager.bypass_data.get(booru_name)
        if current != expected:
            return False
        settings.manager.bypass_data.pop(booru_name, None)
    settings.manager.save()
    return True
