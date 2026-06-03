"""
download_images/ — Complete download and API client package.

Replaces the old monolithic ``downloader.py`` with one file per feature:

    engines.py          — 5 HTTP download engine functions
    smart_folders.py    — Tag-based folder organisation logic
    image_downloader.py — Main download_post() orchestrator
    network.py          — NetworkManager + CloudflareBlockError
    api_client.py       — Booru API search (search_posts)
    thumbnails.py       — Thumbnail fetching + PIL decode
    booru_client.py     — BooruDownloader class (composes everything)

Usage:
    from download_images import BooruDownloader
    from download_images import download_post, get_download_folder
"""

# ── BooruDownloader (main client object used by gui.py) ───────────
from download_images.booru_client import BooruDownloader

# ── Network errors ────────────────────────────────────────────────
from download_images.network import CloudflareBlockError

# ── Download engines ──────────────────────────────────────────────
from download_images.engines import (
    ENGINES,
    ENGINE_LABELS,
    DEFAULT_ENGINE,
    get_available_engines,
)

# ── Image download orchestrator ───────────────────────────────────
from download_images.image_downloader import (
    download_post,
    download_post_async,
)

# ── Smart folder resolution ──────────────────────────────────────
from download_images.smart_folders import (
    get_download_folder,
    get_bulk_folder,
)

__all__ = [
    "BooruDownloader",
    "CloudflareBlockError",
    "download_post",
    "download_post_async",
    "get_download_folder",
    "get_bulk_folder",
    "ENGINES",
    "ENGINE_LABELS",
    "DEFAULT_ENGINE",
    "get_available_engines",
]
