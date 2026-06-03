"""
download_images/image_downloader.py — Main download orchestrator.

This is the single entry point for downloading a post's image to disk.
It resolves the URL, builds headers, picks the engine, and delegates
the actual HTTP transfer to the engine function from engines.py.

Public API:
    download_post(post, folder, downloader, ...) -> bool
    download_post_async(...)                     -> bool   (async wrapper)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

from download_images.engines import ENGINE_FNS, DEFAULT_ENGINE

log = logging.getLogger("image_downloader")




# ╔══════════════════════════════════════════════════════════════════════╗
# ║  download_post — download one post's full-resolution image          ║
# ║                                                                     ║
# ║  Steps:                                                             ║
# ║    1. Resolve the file URL via the post's adapter                   ║
# ║    2. Build CDN-friendly headers (Referer, UA, CF cookies)          ║
# ║    3. Pick the engine from settings (or use the override)           ║
# ║    4. Call the engine function → write file to dest                 ║
# ║    5. Clean up partial files on failure                             ║
# ╚══════════════════════════════════════════════════════════════════════╝

def download_post(
    post: dict,
    folder: Path,
    downloader,
    engine: str | None = None,
    on_progress: Callable | None = None,
) -> bool:
    """Download the full-resolution image for *post* into *folder*.

    Returns True on success, False on failure.  Never raises.

    Parameters
    ----------
    post : dict
        Booru post dict (must have 'id' and a file URL).
    folder : Path
        Destination directory (must exist).
    downloader : BooruDownloader
        Used to resolve the file URL via the correct adapter.
    engine : str or None
        Override the download engine.  None = read from settings.
    on_progress : callable or None
        ``fn(downloaded_bytes, total_bytes)`` called during download.
    """
    from ui import settings_view as settings

    # ── Resolve URL and filename ──────────────────────────────────
    url = downloader.get_file_url(post)
    if not url:
        log.warning("No file URL for post %s", post.get("id"))
        return False

    ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
    post_id = str(post.get("id", "unknown"))
    dest = folder / f"{post_id}{ext}"

    # Skip if already downloaded
    if dest.exists() and dest.stat().st_size > 0:
        log.info("Already exists: %s", dest)
        return True

    # ── Resolve engine ────────────────────────────────────────────
    if engine is None:
        engine = getattr(settings.manager, "download_engine", DEFAULT_ENGINE)
    if engine not in ENGINE_FNS:
        engine = DEFAULT_ENGINE

    # ── Build request headers ─────────────────────────────────────
    headers = _build_headers(post)

    # ── Execute download ──────────────────────────────────────────
    log.info("Downloading post %s via %s -> %s", post_id, engine, dest.name)

    fn = ENGINE_FNS[engine]
    try:
        ok = fn(url, dest, headers, on_progress)
        if ok:
            log.info("Downloaded: %s (%s bytes)", dest.name, dest.stat().st_size)
        else:
            dest.unlink(missing_ok=True)
            log.warning("Download returned False for %s", url)
        return ok
    except Exception as e:
        dest.unlink(missing_ok=True)
        log.error("Download error (%s) for post %s: %s", engine, post_id, e)
        return False


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  download_post_async — async wrapper for use in QThread / asyncio   ║
# ╚══════════════════════════════════════════════════════════════════════╝

async def download_post_async(
    post: dict,
    folder: Path,
    downloader,
    engine: str | None = None,
    on_progress: Callable | None = None,
) -> bool:
    """Async wrapper around download_post.  Runs in a thread executor."""
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, download_post, post, folder, downloader, engine, on_progress
    )


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  _build_headers — CDN-friendly request headers                      ║
# ║                                                                     ║
# ║  Image CDNs need:                                                   ║
# ║    - A valid Referer (hotlink protection)                           ║
# ║    - The same User-Agent that solved the CF challenge               ║
# ║    - cf_clearance cookie injected as a Cookie header                ║
# ╚══════════════════════════════════════════════════════════════════════╝

def _build_headers(post: dict) -> dict:
    """Build HTTP headers for downloading a post's image."""
    from ui import settings_view as settings
    import boorus

    post_booru = post.get("_booru", settings.manager.active_booru)
    site_data = boorus.REGISTRY.get(post_booru, {})
    base_url = site_data.get("url", "")

    headers = {
        "User-Agent": settings.manager.get_user_agent(),
        "Referer": base_url + "/" if base_url else "",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
    }

    # Override UA with the one stored from the CF bypass (if any)
    from cloudflare_bypasser import store as cf_store
    bypass_ua = cf_store.get_user_agent(post_booru)
    if bypass_ua:
        headers["User-Agent"] = bypass_ua

    # Inject CF bypass cookies as a Cookie header
    bypass_cookies = cf_store.get_cookies(post_booru)
    if bypass_cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in bypass_cookies.items())
        headers["Cookie"] = cookie_str

    return headers
