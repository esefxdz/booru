"""
download_images/api_client.py — Booru API search.

Sends a search query to the active booru's API and returns a list of
post dicts.  Handles blacklist/favorites injection, 401 retry without
credentials, and Cloudflare challenge wall detection.
"""

from __future__ import annotations

from ui import settings_view as settings
from download_images.network import CloudflareBlockError


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  search_posts — query a booru's API for post metadata               ║
# ║                                                                     ║
# ║  Steps:                                                             ║
# ║    1. Build search query (user tags + blacklist + favorites)        ║
# ║    2. Build params via the adapter (handles pagination, auth)       ║
# ║    3. Fetch via the bypass session                                  ║
# ║    4. Retry without creds on 401 (stale API key + valid bypass)     ║
# ║    5. Detect Cloudflare challenge walls → raise CloudflareBlockError║
# ║    6. Parse the response via the adapter → return list[dict]        ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def search_posts(adapter, site_data, fetch_fn, tags, limit, page=0):
    """Search the booru and return a list of post dicts.

    Parameters
    ----------
    adapter : BaseAdapter
        The booru adapter for this site.
    site_data : dict
        Registry entry (url, api_path, api_type, ...).
    fetch_fn : async callable
        ``async fn(url, params=...) -> response`` — the HTTP fetcher.
    tags : str
        User's search query.
    limit : int
        Max number of posts to return.
    page : int
        Zero-based page index.

    Returns
    -------
    list[dict]
        Post dicts from the API, or [] on error.
    """
    url   = adapter.build_url(site_data)
    creds = settings.manager.get_credential(settings.manager.active_booru) or {}

    # ── Build search query with blacklist + favorites ─────────────
    search_tags = tags.strip()
    if settings.manager.blacklist:
        blacklist = " ".join(f"-{t}" for t in settings.manager.blacklist.split())
        search_tags = f"{search_tags} {blacklist}"
    if settings.manager.favorites:
        favorites = " ".join(settings.manager.favorites.split())
        search_tags = f"{search_tags} {favorites}"

    # ── Send request ──────────────────────────────────────────────
    params = adapter.build_params(search_tags, limit, page, creds)
    try:
        r = await fetch_fn(url, params=params)

        # ── 401 retry: stale API key alongside a valid CF bypass ──
        if r.status_code == 401 and creds:
            print("[api_client] Auth failed (401), retrying without credentials...")
            params_no_auth = adapter.build_params(search_tags, limit, page, {})
            r = await fetch_fn(url, params=params_no_auth)

        # ── Cloudflare challenge wall detection ───────────────────
        if hasattr(r, "is_blocked") and r.is_blocked:
            booru = settings.manager.active_booru
            from cloudflare_bypasser import invalidate_session
            invalidate_session(booru)
            raise CloudflareBlockError(
                f"'{booru}' is behind Cloudflare protection. "
                f"Right-click the booru icon -> Cloudflare tab -> "
                f"solve the CAPTCHA to unlock access."
            )

        # ── Non-200 response ─────────────────────────────────────
        if r.status_code != 200:
            print(f"[api_client] HTTP {r.status_code} from {url}")
            return []

        return adapter.parse_response(r, site_data)
    except CloudflareBlockError:
        raise
    except Exception as e:
        print(f"[api_client] search_posts error: {e}")
        return []
