import asyncio
import httpx
import os
import re
from collections import OrderedDict
from pathlib import Path
from io import BytesIO
from PIL import Image
from ui import settings_view as settings
import boorus
from adapters import get_adapter

import thumb_cache


class CloudflareBlockError(Exception):
    """Raised when a booru is behind an active Cloudflare challenge wall."""
    pass

class NetworkManager:
    _semaphores = {}
    _last_limit = 0

    @classmethod
    def get_semaphore(cls):
        try:
            import asyncio
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None

        if cls._last_limit != settings.manager.concurrent_downloads:
            cls._semaphores.clear()
            cls._last_limit = settings.manager.concurrent_downloads

        if loop not in cls._semaphores:
            cls._semaphores[loop] = asyncio.Semaphore(settings.manager.concurrent_downloads)
            
        return cls._semaphores[loop]

    @classmethod
    async def fetch(cls, session, url, params=None, headers=None):
        if settings.manager.use_network_semaphore:
            async with cls.get_semaphore():
                return await session.get(url, params=params, headers=headers)
        else:
            return await session.get(url, params=params, headers=headers)


class BooruDownloader:

    def __init__(self):
        self.headers = settings.DEFAULT_HEADERS.copy()

    @property
    def site_data(self):
        return boorus.REGISTRY.get(settings.manager.active_booru, {})

    def _get_client_args(self):
        """Returns kwargs (headers, cookies) for httpx client based on active bypass data."""
        from cloudflare_bypasser import store as cf_store
        headers = self.headers.copy()
        booru = settings.manager.active_booru
        ua = cf_store.get_user_agent(booru)
        if ua:
            headers["User-Agent"] = ua
        cookies = cf_store.get_cookies(booru)
        return {"headers": headers, "cookies": cookies, "timeout": settings.TIMEOUT, "http2": True}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _fetch(self, url, params=None, timeout=None):
        """Unified fetcher — exclusively uses curl-cffi stealth sessions.
        Mixing httpx and curl-cffi on the same IP flags the session in Cloudflare.
        """
        from cloudflare_bypasser import get_session
        session = get_session(settings.manager.active_booru)

        # Standard headers
        headers = self.headers.copy()
        
        # Add modern browser fetch metadata for maximum stealth
        if params is not None:
            # API requests
            headers.update({
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                "Accept-Language": "en-US,en;q=0.9",
            })
        else:
            # Image/Thumbnail requests (CDNs require Referer to prevent hotlink 403s)
            adapter = self._adapter()
            base_url = adapter.build_url(self.site_data).split("/index.php")[0].split("/posts.json")[0]
            if not base_url.endswith("/"):
                base_url += "/"
                
            headers.update({
                "Referer": base_url,
                "Sec-Fetch-Dest": "image",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Site": "cross-site",
                "Accept-Language": "en-US,en;q=0.9",
            })
        
        return await NetworkManager.fetch(session, url, params=params, headers=headers)

    def _adapter(self):
        """Return the correct adapter for the currently active site."""
        return get_adapter(self.site_data.get("api_type", "gelbooru"))

    def _get_adapter_for_post(self, post: dict):
        """Return the adapter specific to the booru this post came from."""
        booru = post.get("_booru", settings.manager.active_booru)
        booru_data = boorus.REGISTRY.get(booru, {})
        api_type = booru_data.get("api_type", "gelbooru")
        return get_adapter(api_type)


    def _cache_get(self, key):
        return thumb_cache.get(key)

    def _cache_set(self, key, value):
        thumb_cache.put(key, value)

    # ------------------------------------------------------------------
    # Post field accessors (delegates to adapter)
    # ------------------------------------------------------------------

    def get_preview_url(self, post: dict) -> str:
        url = self._get_adapter_for_post(post).get_preview_url(post)
        if url and url.startswith("//"):
            url = "https:" + url
        return url or ""

    def get_sample_url(self, post: dict) -> str:
        url = self._get_adapter_for_post(post).get_sample_url(post)
        if url and url.startswith("//"):
            url = "https:" + url
        return url or ""

    def get_file_url(self, post: dict) -> str:
        url = self._get_adapter_for_post(post).get_file_url(post)
        if url and url.startswith("//"):
            url = "https:" + url
        return url or ""

    def get_tag_list(self, post: dict) -> list:
        return self._get_adapter_for_post(post).get_tags(post)

    # ------------------------------------------------------------------
    # Posts metadata
    # ------------------------------------------------------------------

    async def get_image_urls(self, tags, limit, page=0):
        adapter  = self._adapter()
        url      = adapter.build_url(self.site_data)
        creds    = settings.manager.get_credential(settings.manager.active_booru) or {}

        search_tags = tags.strip()
        if settings.manager.blacklist:
            blacklist = " ".join(f"-{t}" for t in settings.manager.blacklist.split())
            search_tags = f"{search_tags} {blacklist}"
            
        if settings.manager.favorites:
            favorites = " ".join(settings.manager.favorites.split())
            search_tags = f"{search_tags} {favorites}"

        params = adapter.build_params(search_tags, limit, page, creds)
        try:
            r = await self._fetch(url, params=params)
            
            # If 401 Unauthorized, try again without credentials 
            # (Danbooru often errors if stale credentials are sent alongside a valid session bypass)
            if r.status_code == 401 and creds:
                print(f"[downloader] Auth failed (401), retrying without credentials...")
                params_no_auth = adapter.build_params(search_tags, limit, page, {})
                r = await self._fetch(url, params=params_no_auth)

            # Detect Cloudflare challenge walls — surface a clear message
            if hasattr(r, "is_blocked") and r.is_blocked:
                booru = settings.manager.active_booru
                raise CloudflareBlockError(
                    f"'{booru}' is behind Cloudflare protection. "
                    f"Right-click the booru icon → Cloudflare tab → "
                    f"solve the CAPTCHA to unlock access."
                )

            if r.status_code != 200:
                print(f"[downloader] HTTP {r.status_code} from {url}")
                return []
            return adapter.parse_response(r, self.site_data)
        except CloudflareBlockError:
            raise  # let this propagate to the controller
        except Exception as e:
            print(f"[downloader] get_image_urls error: {e}")
            return []

    # ------------------------------------------------------------------
    # Thumbnails
    # ------------------------------------------------------------------

    async def fetch_previews(self, posts, callback):
        loop    = asyncio.get_running_loop()
        adapter = self._adapter()

        async def fetch_one(post, index):
            post_id = post.get("id")
            cached  = self._cache_get(post_id)
            if cached is not None:
                callback(cached, post, index)
                return

            url = adapter.get_preview_url(post)
            if not url:
                return
            if url.startswith("//"):
                url = "https:" + url

            try:
                r = await self._fetch(url, timeout=10.0)
                if r.status_code != 200:
                    print(f"[downloader] Thumbnail fetch failed: HTTP {r.status_code} for {url}")
                    return
                raw = r.content if hasattr(r, "content") else r.text.encode()

                def decode():
                    img = Image.open(BytesIO(raw))
                    img.thumbnail((settings.manager.thumbnail_size, settings.manager.thumbnail_size), Image.LANCZOS)
                    if img.mode in ("RGBA", "LA", "P"):
                        img = img.convert("RGB")
                    buf = BytesIO()
                    img.save(buf, format="JPEG", quality=85)
                    return buf.getvalue()

                img_bytes = await loop.run_in_executor(None, decode)
                self._cache_set(post_id, img_bytes)
                callback(img_bytes, post, index)
            except Exception as e:
                print(f"[downloader] fetch_one error for post {post_id}: {e}")

        await asyncio.gather(*(fetch_one(post, i) for i, post in enumerate(posts)))

    # ------------------------------------------------------------------
    # Full download
    # ------------------------------------------------------------------

    async def download_task(self, post, folder):
        url = self.get_file_url(post)
        if not url:
            return

        ext  = os.path.splitext(url.split("?")[0])[1] or ".jpg"
        name = f"{post.get('id', 'image')}{ext}"
        path = folder / name
        client_args = self._get_client_args()

        try:
            r = await self._fetch(url, timeout=60)
            if r.status_code == 200:
                raw = r.content if hasattr(r, "content") else r.text.encode()
                path.write_bytes(raw)
            else:
                print(f"[downloader] Download failed: HTTP {r.status_code} for {url}")
        except Exception as e:
            print(f"[downloader] download_task error for post {post.get('id')}: {e}")

    # ------------------------------------------------------------------
    # Utils
    # ------------------------------------------------------------------

    def get_download_folder_for_post(self, post: dict) -> Path:
        """Smart folder naming for single-post downloads: character/artist/5-tags.

        Uses a two-pass strategy:
          1. Ask the adapter for pre-categorized tags (works for Danbooru, e621)
          2. If artist/character are empty, fall back to TagCategorizer which
             queries Danbooru's tag DB + heuristics + local cache — this
             covers Gelbooru, Moebooru, Shimmie2, and every other booru
             whose API doesn't expose tag categories.
        """
        from validation import validate_directory_name

        # --- STATIC DOWNLOAD FEATURE (DEFAULT) ---
        if not settings.manager.use_smart_folders:
            path = settings.manager.get_download_dir() / "unsorted"
            path.mkdir(parents=True, exist_ok=True)
            return path
        # ------------------------------------------

        booru = post.get("_booru", settings.manager.active_booru)
        tags = self.get_tag_list(post)
        adapter = self._get_adapter_for_post(post)

        try:
            cats = self._categorize_post_tags(adapter, post, tags)
        except Exception as e:
            print(f"[downloader] Tag categorization failed: {e}")
            cats = {"artist": [], "character": [], "copyright": [], "meta": [], "general": tags}

        # 1. Determine folder name based on preference
        folder_name = self._pick_folder_name(cats)

        # 2. Heuristic fallback (if categories are still empty)
        if not folder_name and tags:
            # Use first 5 tags, capped at 60 chars to stay within Windows path limits
            tag_join = "_".join(tags[:5])
            if len(tag_join) > 60:
                tag_join = tag_join[:57] + "..."
            folder_name = tag_join

        # 3. Sanitize names
        try:
            safe_booru = validate_directory_name(booru)
        except Exception:
            safe_booru = "unknown_booru"

        try:
            safe_name = validate_directory_name(folder_name or "unsorted")
        except Exception:
            safe_name = "unsorted"

        # 4. Create and return path
        try:
            path = settings.manager.get_download_dir() / safe_booru / safe_name
            path.mkdir(parents=True, exist_ok=True)
            return path
        except Exception as e:
            # Ultimate fallback to booru root if subfolder creation fails
            print(f"[downloader] Folder creation failed for '{safe_name}': {e}")
            fallback_path = settings.manager.get_download_dir() / safe_booru
            fallback_path.mkdir(parents=True, exist_ok=True)
            return fallback_path

    def _categorize_post_tags(self, adapter, post: dict, tags: list) -> dict:
        """Get categorized tags — adapter first, then TagCategorizer fallback.

        The adapter path works instantly for Danbooru and e621 (their APIs
        return pre-sorted ``tag_string_artist`` / ``tags.artist`` fields).

        For every other booru the adapter returns empty artist/character
        lists, so we fall back to the TagCategorizer which queries
        Danbooru's tag database, applies heuristics (``_artist`` /
        ``_character`` suffixes), and caches results locally.
        """
        cats = adapter.get_categorized_tags(post)

        # If the adapter already gave us artist or character data, trust it
        if cats.get("artist") or cats.get("character"):
            return cats

        # Fallback: use TagCategorizer (Danbooru API + heuristic + cache)
        if not tags:
            return cats

        try:
            from tag_categorizer import categorizer
            import asyncio

            # TagCategorizer.categorize_tags is async — run it safely
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # We're inside an event loop already (Qt thread) — run
                # the categorizer in a thread pool to avoid blocking
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        categorizer.categorize_tags(tags),
                    )
                    cats = future.result(timeout=10)
            else:
                cats = asyncio.run(categorizer.categorize_tags(tags))

        except Exception as e:
            print(f"[downloader] TagCategorizer fallback failed: {e}")
            # Return the adapter's original (all-general) result
        return cats

    def _pick_folder_name(self, cats: dict) -> str | None:
        """Pick the best folder name from categorized tags."""
        if settings.manager.download_folder_use_artist_folder:
            # Prefer artist, then character
            if cats.get("artist"):
                return cats["artist"][0]
            if cats.get("character"):
                return cats["character"][0]
        else:
            # Prefer character, then artist
            if cats.get("character"):
                return cats["character"][0]
            if cats.get("artist"):
                return cats["artist"][0]

        # Try copyright as a last resort before the tag-join fallback
        if cats.get("copyright"):
            return cats["copyright"][0]

        return None

    def get_valid_folder(self, tags: str) -> Path:
        """For bulk downloads: use exact searched tags as folder name."""
        from validation import validate_directory_name

        try:
            safe = validate_directory_name(tags.strip()) or "unsorted"
        except:
            safe = "unsorted"

        path = settings.manager.get_download_dir() / settings.manager.active_booru / safe
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_credentials(self, name, uid, api_key):
        settings.manager.set_credential(name, uid, api_key)

    async def close(self):
        pass
