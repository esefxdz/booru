"""
cloudflare_bypasser/store.py

Bypass-data persistence layer.

Reads and writes to ``settings.manager.bypass_data`` — the single source of
truth for per-booru Cloudflare clearance cookies and the User-Agent that was
active when the CAPTCHA was solved.

Keeping all persistence logic here means that if the storage backend ever
changes (e.g. encrypting bypass_data with the keyring), only this file needs
to be updated.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Avoid a circular import at module load time; settings is always present
    # at runtime because main.py initialises it first.
    pass

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_bypass_data(booru_name: str) -> dict:
    """
    Return the stored bypass dictionary for *booru_name*.

    Returns an empty dict when nothing is stored so callers can always use
    ``.get()`` safely without a fallback check.
    """
    from ui import settings_view as settings
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


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def save_bypass(booru_name: str, cookies: dict, user_agent: str) -> None:
    """
    Persist captured *cookies* and *user_agent* for *booru_name*.

    Both are required for the bypass to work: Cloudflare ties the clearance
    cookie to the exact UA fingerprint that solved the challenge.
    """
    from ui import settings_view as settings
    settings.manager.bypass_data[booru_name] = {
        "cookies":    cookies,
        "user_agent": user_agent,
    }
    settings.manager.save()


def clear_bypass(booru_name: str) -> None:
    """
    Remove all stored bypass data for *booru_name*.

    Call this when:
    - The user manually clears the bypass in the settings dialog.
    - A request fails with 403/429 (the clearance has expired).
    """
    from ui import settings_view as settings
    settings.manager.bypass_data.pop(booru_name, None)
    settings.manager.save()
