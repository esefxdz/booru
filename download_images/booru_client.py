"""
download_images/booru_client.py — BooruDownloader class.

The main client object that the GUI instantiates and passes around.
It composes all the split modules:
  - network.py       → CloudflareBlockError, NetworkManager
  - api_client.py    → search_posts
  - thumbnails.py    → fetch_previews
  - image_downloader.py → download_post (used by actions.py directly)

This file is intentionally thin — it delegates everything to the
single-feature modules and only provides the wiring + URL resolution.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from ui import settings_view as settings
import boorus
from adapters import get_adapter

from download_images.network import NetworkManager


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  BooruDownloader — thin composition layer                           ║
# ║                                                                     ║
# ║  Responsibilities:                                                  ║
# ║    - Adapter resolution (active booru vs per-post booru)            ║
# ║    - HTTP fetching via CF bypass session + NetworkManager           ║
# ║    - Post field URL resolution (preview, sample, file)              ║
# ║    - Delegating search to api_client.search_posts                   ║
# ║    - Delegating thumbnails to thumbnails.fetch_previews             ║
# ╚══════════════════════════════════════════════════════════════════════╝

class BooruDownloader(QObject):

    # ── Signals for the DownloadWindow progress UI ────────────────
    download_started  = pyqtSignal(str, str)       # task_id, filename
    download_progress = pyqtSignal(str, int, int)  # task_id, current, total
    download_finished = pyqtSignal(str)            # task_id
    download_failed   = pyqtSignal(str, str)       # task_id, error_message

    def __init__(self):
        super().__init__()
        self.headers = settings.DEFAULT_HEADERS.copy()

    # ──────────────────────────────────────────────────────────────
    #  Adapter resolution
    # ──────────────────────────────────────────────────────────────

    @property
    def site_data(self):
        """Registry entry for the currently active booru."""
        return boorus.REGISTRY.get(settings.manager.active_booru, {})

    def _adapter(self):
        """Return the adapter for the currently active booru."""
        return get_adapter(self.site_data.get("api_type", "gelbooru"))

    def _get_adapter_for_post(self, post: dict):
        """Return the adapter for the booru a specific post came from."""
        booru = post.get("_booru", settings.manager.active_booru)
        booru_data = boorus.REGISTRY.get(booru, {})
        return get_adapter(booru_data.get("api_type", "gelbooru"))

    # ──────────────────────────────────────────────────────────────
    #  HTTP fetcher (CF bypass session + stealth headers)
    # ──────────────────────────────────────────────────────────────

    async def _fetch(self, url, params=None, timeout=None, booru=None, session_manager=None):
        """Fetch a URL through the Cloudflare bypass session.

        Used for API requests and thumbnail downloads.
        Full image downloads use download_images.engines instead.

        When *session_manager* is provided (by FetchThread/BulkThread), it
        is used to obtain a session.  Otherwise, the globally cached session
        from :func:`cloudflare_bypasser.get_session` is used — sessions are
        long-lived and must NOT be closed by callers.
        """
        booru_name = booru or settings.manager.active_booru
        if session_manager:
            session = session_manager(booru_name)
        else:
            from cloudflare_bypasser import get_session
            session = get_session(booru_name)

        headers = self.headers.copy()

        if params is not None:
            # API requests — JSON endpoint
            headers.update({
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                "Accept-Language": "en-US,en;q=0.9",
            })
            bypass_rate_limit = False
        else:
            # Image requests — CDN needs Referer for hotlink protection
            adapter = self._adapter()
            base_url = adapter.build_url(self.site_data)
            base_url = base_url.split("/index.php")[0].split("/posts.json")[0]
            if not base_url.endswith("/"):
                base_url += "/"
            headers.update({
                "Referer": base_url,
                "Sec-Fetch-Dest": "image",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Site": "cross-site",
                "Accept-Language": "en-US,en;q=0.9",
            })
            bypass_rate_limit = True

        return await NetworkManager.fetch(session, url, params=params, headers=headers, bypass_rate_limit=bypass_rate_limit)

    # ──────────────────────────────────────────────────────────────
    #  Post field accessors (delegate to adapter)
    # ──────────────────────────────────────────────────────────────

    def get_preview_url(self, post: dict) -> str:
        """Resolve the thumbnail / preview URL for a post."""
        url = self._get_adapter_for_post(post).get_preview_url(post)
        if url and url.startswith("//"):
            url = "https:" + url
        return url or ""

    def get_sample_url(self, post: dict) -> str:
        """Resolve the sample (medium-res) URL for a post."""
        url = self._get_adapter_for_post(post).get_sample_url(post)
        if url and url.startswith("//"):
            url = "https:" + url
        return url or ""

    def get_file_url(self, post: dict) -> str:
        """Resolve the full-resolution file URL for a post."""
        url = self._get_adapter_for_post(post).get_file_url(post)
        if url and url.startswith("//"):
            url = "https:" + url
        return url or ""

    def get_tag_list(self, post: dict) -> list:
        """Return the flat tag list for a post."""
        return self._get_adapter_for_post(post).get_tags(post)

    # ──────────────────────────────────────────────────────────────
    #  API search (delegates to api_client.py)
    # ──────────────────────────────────────────────────────────────

    async def get_image_urls(self, tags, limit, page=0, session_manager=None):
        """Search the active booru and return a list of post dicts."""
        from download_images.api_client import search_posts
        
        async def bound_fetch(url, params=None, timeout=None, booru=None):
            return await self._fetch(url, params=params, timeout=timeout, booru=booru, session_manager=session_manager)
            
        return await search_posts(
            self._adapter(), self.site_data, bound_fetch, tags, limit, page
        )

    # ──────────────────────────────────────────────────────────────
    #  Thumbnail fetching (delegates to thumbnails.py)
    # ──────────────────────────────────────────────────────────────

    async def fetch_previews(self, posts, callback, cancel_event=None, session_manager=None):
        """Fetch and decode thumbnails for a list of posts."""
        from download_images.thumbnails import fetch_previews
        from download_images.thumb_client import thumb_fetch

        async def bound_fetch(url, params=None, timeout=None, booru=None):
            return await self._fetch(url, params=params, timeout=timeout, booru=booru, session_manager=session_manager)

        # Pre-compute session cookies once per booru, not per thumbnail.
        # _merged_cookies merges stored + accumulated cookies — doing it
        # inside the closure would create a new dict for every thumbnail.
        _extra_cookies = {}
        def _get_extra(booru_name: str) -> dict:
            if booru_name not in _extra_cookies:
                extra = {}
                if session_manager:
                    try:
                        s = session_manager(booru_name)
                        extra = getattr(s, "_merged_cookies", {}) or {}
                    except Exception:
                        pass
                _extra_cookies[booru_name] = extra
            return _extra_cookies[booru_name]

        async def bound_thumb_fetch(url, timeout=None, booru=None):
            booru_name = booru or settings.manager.active_booru
            return await thumb_fetch(
                url, booru=booru_name, timeout=timeout or 10.0,
                extra_cookies=_get_extra(booru_name),
            )

        await fetch_previews(posts, self._adapter(), bound_fetch, callback, cancel_event, thumb_fetch_fn=bound_thumb_fetch)

    # ──────────────────────────────────────────────────────────────
    #  Credentials
    # ──────────────────────────────────────────────────────────────

    def save_credentials(self, name, uid, api_key):
        """Persist API credentials to secure storage."""
        settings.manager.set_credential(name, uid, api_key)

    # ──────────────────────────────────────────────────────────────
    #  Download orchestration (emits signals for progress UI)
    # ──────────────────────────────────────────────────────────────

    def download_file(self, task_id: str, post: dict, folder, engine: str | None = None):
        """Download a single post's file to *folder*, emitting progress signals.

        This is the main entry point for per-post downloads.  It runs
        synchronously (callers should wrap in a thread) and emits
        ``download_started``, ``download_progress``, ``download_finished``
        or ``download_failed`` as the transfer progresses.
        """
        import uuid
        from download_images.image_downloader import download_post

        tid = str(task_id) if task_id is not None else str(uuid.uuid4())[:8]
        filename = str(post.get("id", "unknown"))
        ext = post.get("file_ext", "")
        if not ext and "file_url" in post:
            ext = post["file_url"].rsplit("?", 1)[0].split(".")[-1]
        display_name = f"{filename}.{ext}" if ext else str(filename)

        self.download_started.emit(tid, display_name)

        def _on_progress(current, total):
            self.download_progress.emit(tid, current, total)

        try:
            ok = download_post(post, folder, self, engine=engine, on_progress=_on_progress)
            if ok:
                self.download_finished.emit(tid)
            else:
                self.download_failed.emit(tid, "Download engine returned failure")
        except Exception as e:
            self.download_failed.emit(tid, str(e))

    # ──────────────────────────────────────────────────────────────
    #  Cleanup
    # ──────────────────────────────────────────────────────────────

    async def close(self):
        """Close any long-lived connection pools held by this downloader."""
        from download_images import thumb_client
        await thumb_client.close_all()
