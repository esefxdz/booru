"""Downloads a post's full-resolution file to disk via the chosen engine."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from download_images.engines import ENGINE_FNS, DEFAULT_ENGINE

log = logging.getLogger("image_downloader")

# One lock per destination file so duplicate downloads don't share a .part file.
_dest_locks: dict[str, threading.Lock] = {}
_dest_locks_guard = threading.Lock()


def _lock_for(dest: Path) -> threading.Lock:
    key = str(dest).lower()
    with _dest_locks_guard:
        return _dest_locks.setdefault(key, threading.Lock())


def download_post(
    post: dict,
    folder: Path,
    downloader,
    engine: str | None = None,
    on_progress: Callable | None = None,
) -> bool:
    """Download *post* into the existing *folder*. Returns success; never raises.

    *engine* overrides the setting; *on_progress* is ``fn(downloaded, total)``.
    """
    url = downloader.get_file_url(post)
    if not url:
        log.warning("No file URL for post %s", post.get("id"))
        return False

    from core.validation import ValidationError, require_http_url, safe_media_path

    post_id = post.get("id", "unknown")
    try:
        url = require_http_url(url)
        # Server-supplied id/extension must not reach the path unchecked.
        dest = safe_media_path(folder, post_id, url)
    except ValidationError as e:
        log.warning("Refusing download for post %r: %s", post_id, e)
        return False

    with _lock_for(dest):
        # Inside the lock: a concurrent download may have just finished.
        if dest.exists() and dest.stat().st_size > 0:
            log.info("Already exists: %s", dest)
            return True
        return _download_to(url, dest, post, post_id, engine, on_progress)


def _download_to(url, dest: Path, post: dict, post_id, engine, on_progress) -> bool:
    from core import settings

    if engine is None:
        engine = getattr(settings.manager, "download_engine", DEFAULT_ENGINE)
    if engine not in ENGINE_FNS:
        engine = DEFAULT_ENGINE

    headers = _build_headers(post, url)

    log.info("Downloading post %s via %s -> %s", post_id, engine, dest.name)

    fn = ENGINE_FNS[engine]
    # Write to .part and rename, so an interrupted download leaves no truncated file.
    part = dest.with_name(dest.name + ".part")
    try:
        ok = fn(url, part, headers, on_progress)
        if ok and part.exists() and part.stat().st_size > 0:
            part.replace(dest)
            log.info("Downloaded: %s (%s bytes)", dest.name, dest.stat().st_size)
            return True
        part.unlink(missing_ok=True)
        log.warning("Download failed or empty for %s", url)
        return False
    except Exception as e:
        part.unlink(missing_ok=True)
        log.error("Download error (%s) for post %s: %s", engine, post_id, e)
        return False


async def download_post_async(
    post: dict,
    folder: Path,
    downloader,
    engine: str | None = None,
    on_progress: Callable | None = None,
) -> bool:
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, download_post, post, folder, downloader, engine, on_progress
    )


def _build_headers(post: dict, url: str = "") -> dict:
    """Request headers for *url*; bypass cookies only when it is on the booru's own site."""
    from core import settings
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

    # Use the UA that solved the Cloudflare challenge.
    from cloudflare_bypasser import store as cf_store
    bypass_ua = cf_store.get_user_agent(post_booru)
    if bypass_ua:
        headers["User-Agent"] = bypass_ua

    from core.validation import same_site
    bypass_cookies = cf_store.get_cookies(post_booru) if same_site(url, base_url) else {}
    if bypass_cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in bypass_cookies.items())
        headers["Cookie"] = cookie_str

    return headers
