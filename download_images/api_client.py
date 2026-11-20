"""Booru API search: builds the query, handles 401/Cloudflare, returns post dicts."""

from __future__ import annotations
import logging

from core import settings
from download_images.network import CloudflareBlockError


async def search_posts(adapter, site_data, fetch_fn, tags, limit, page=0):
    """Return post dicts from the booru API, or [] on error. *fetch_fn* is ``async fn(url, params=...)``."""
    url   = adapter.build_url(site_data)
    creds = settings.manager.get_credential(settings.manager.active_booru) or {}

    search_tags = tags.strip()
    if settings.manager.blacklist:
        blacklist = " ".join(f"-{t}" for t in settings.manager.blacklist.split())
        search_tags = f"{search_tags} {blacklist}"
    if settings.manager.favorites:
        favorites = " ".join(settings.manager.favorites.split())
        search_tags = f"{search_tags} {favorites}"

    params = adapter.build_params(search_tags, limit, page, creds)
    from cloudflare_bypasser import bypass_snapshot
    stored_before = bypass_snapshot(settings.manager.active_booru)
    try:
        r = await fetch_fn(url, params=params)

        if r.status_code == 401:
            booru = settings.manager.active_booru
            if creds:
                logging.error("[api_client] Auth failed (401) with stored credentials — they may be expired")
            else:
                logging.warning("[api_client] %s requires an API key — get one from the site and add it in Settings > Credentials", booru)
            # Retry anonymously in case the stored key is stale.
            if creds:
                params_no_auth = adapter.build_params(search_tags, limit, page, {})
                r = await fetch_fn(url, params=params_no_auth)

        if hasattr(r, "is_blocked") and r.is_blocked:
            booru = settings.manager.active_booru
            # Only a real challenge page invalidates the stored clearance: not a
            # synthetic "circuit-open" (nothing was sent), not a plain 403, and
            # not unless_changed_since a newer solve.
            if (getattr(r, "engine_used", None) != "circuit-open"
                    and getattr(r, "is_cf_challenge", False)):
                from cloudflare_bypasser import invalidate_session
                invalidate_session(booru, unless_changed_since=stored_before)
            raise CloudflareBlockError(
                f"'{booru}' is behind Cloudflare protection. "
                f"Right-click the booru icon -> Cloudflare tab -> "
                f"solve the CAPTCHA to unlock access."
            )

        if r.status_code != 200:
            booru = settings.manager.active_booru
            if r.status_code == 403:
                logging.warning("[api_client] %s returned 403 Forbidden — the site may be blocking automated access (Cloudflare)", booru)
            elif r.status_code == 404:
                logging.warning("[api_client] %s returned 404 — the API endpoint may be wrong or the site is down", booru)
            elif r.status_code == 401:
                logging.warning("[api_client] %s requires authentication — add an API key in Settings > Credentials", booru)
            else:
                logging.warning("[api_client] HTTP %d from %s", r.status_code, url)
            return []

        booru_name = settings.manager.active_booru
        adapter_name = getattr(adapter, "api_type", "unknown")

        result = adapter.parse_response(r, site_data)
        if isinstance(result, dict):
            result = [result]  # some sites return a lone object for one hit
        if isinstance(result, list):
            # Downstream calls post.get(): drop non-dict entries from malformed responses.
            dropped = sum(1 for p in result if not isinstance(p, dict))
            if dropped:
                logging.warning("[api_client] %s: dropped %d malformed post entries", booru_name, dropped)
            result = [p for p in result if isinstance(p, dict)]
        if not isinstance(result, list):
            logging.warning(
                "[api_client] %s/%s parse_response returned %s (expected list) — API may have changed",
                booru_name, adapter_name, type(result).__name__,
            )
            return []
        return result
    except CloudflareBlockError:
        raise
    except Exception as e:
        booru = settings.manager.active_booru
        adapter_name = getattr(adapter, "api_type", "unknown")
        import json
        if isinstance(e, json.JSONDecodeError):
            logging.error(
                "[api_client] %s/%s returned invalid JSON from %s: %s",
                booru, adapter_name, url, e,
            )
            from download_images.network import BooruAPIError
            raise BooruAPIError(
                f"'{booru}' ({adapter_name}) returned invalid data instead of JSON. "
                "The site might be down, or the API URL is wrong."
            )
        logging.error(
            "[api_client] %s/%s parse error for %s: %s",
            booru, adapter_name, url, e,
        )
        return []
