import asyncio
import httpx
import os
import re
from collections import OrderedDict
from pathlib import Path
from io import BytesIO
from PIL import Image
import settings
import boorus
from adapters import get_adapter

_CACHE_MAX = 300  # Max thumbnails in memory before evicting oldest


class BooruDownloader:

    def __init__(self):
        self.site_data = boorus.REGISTRY.get(settings.ACTIVE_BOORU, {})
        self.headers   = settings.DEFAULT_HEADERS.copy()
        self.thumb_cache: OrderedDict = OrderedDict()

    def _get_client_args(self):
        """Returns kwargs (headers, cookies) for httpx client based on active bypass data."""
        headers = self.headers.copy()
        cookies = {}
        bypass = settings.BYPASS_DATA.get(settings.ACTIVE_BOORU)
        if bypass:
            ua = bypass.get("user_agent")
            if ua:
                headers["User-Agent"] = ua
            if bypass.get("cf_clearance"):
                cookies["cf_clearance"] = bypass["cf_clearance"]
        return {"headers": headers, "cookies": cookies, "timeout": settings.TIMEOUT, "http2": True}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _adapter(self):
        """Return the correct adapter for the currently active site."""
        return get_adapter(self.site_data.get("api_type", "gelbooru"))

    def _cache_get(self, key):
        if key in self.thumb_cache:
            self.thumb_cache.move_to_end(key)
            return self.thumb_cache[key]
        return None

    def _cache_set(self, key, value):
        self.thumb_cache[key] = value
        self.thumb_cache.move_to_end(key)
        if len(self.thumb_cache) > _CACHE_MAX:
            self.thumb_cache.popitem(last=False)

    # ------------------------------------------------------------------
    # Post field accessors (delegates to adapter)
    # ------------------------------------------------------------------

    def get_file_url(self, post: dict) -> str:
        url = self._adapter().get_file_url(post)
        if url and url.startswith("//"):
            url = "https:" + url
        return url or ""

    def get_sample_url(self, post: dict) -> str:
        url = self._adapter().get_sample_url(post)
        if url and url.startswith("//"):
            url = "https:" + url
        return url or ""

    def get_preview_url(self, post: dict) -> str:
        url = self._adapter().get_preview_url(post)
        if url and url.startswith("//"):
            url = "https:" + url
        return url or ""

    def get_tag_list(self, post: dict) -> list:
        return self._adapter().get_tags(post)

    def get_categorized_tags(self, post: dict) -> dict:
        return self._adapter().get_categorized_tags(post)

    # ------------------------------------------------------------------
    # Posts metadata
    # ------------------------------------------------------------------

    async def get_image_urls(self, tags, limit, page=0):
        adapter  = self._adapter()
        url      = adapter.build_url(self.site_data)
        creds    = settings.CREDENTIALS.get(settings.ACTIVE_BOORU, {})

        search_tags = tags.strip()
        if settings.BLACKLIST:
            blacklist = " ".join(f"-{t}" for t in settings.BLACKLIST.split())
            search_tags = f"{search_tags} {blacklist}"

        params = adapter.build_params(search_tags, limit, page, creds)
        client_args = self._get_client_args()

        try:
            async with httpx.AsyncClient(**client_args) as client:
                r = await client.get(url, params=params)
            if r.status_code != 200:
                print(f"[downloader] HTTP {r.status_code} from {url}")
                return []
            return adapter.parse_response(r, self.site_data)
        except Exception as e:
            print(f"[downloader] get_image_urls error: {e}")
            return []

    # ------------------------------------------------------------------
    # Thumbnails
    # ------------------------------------------------------------------

    async def fetch_previews(self, posts, callback):
        loop    = asyncio.get_running_loop()
        adapter = self._adapter()
        client_args = self._get_client_args()

        async with httpx.AsyncClient(**client_args) as client:
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
                    r = await client.get(url, timeout=5.0)
                    if r.status_code != 200:
                        return
                    raw = r.content

                    def decode():
                        img = Image.open(BytesIO(raw))
                        img.thumbnail((settings.THUMBNAIL_SIZE, settings.THUMBNAIL_SIZE), Image.LANCZOS)
                        return img

                    img = await loop.run_in_executor(None, decode)
                    self._cache_set(post_id, img)
                    callback(img, post, index)
                except Exception as e:
                    print(f"[downloader] fetch_one error for post {post_id}: {e}")

            await asyncio.gather(*(fetch_one(post, i) for i, post in enumerate(posts)))

    # ------------------------------------------------------------------
    # Full download
    # ------------------------------------------------------------------

    async def download_task(self, client, post, folder):
        url = self.get_file_url(post)
        if not url:
            return

        ext  = os.path.splitext(url.split("?")[0])[1] or ".jpg"
        name = f"{post.get('id', 'image')}{ext}"
        path = folder / name
        client_args = self._get_client_args()

        try:
            async with httpx.AsyncClient(**client_args) as tmp:
                r = await tmp.get(url, timeout=60)
            if r.status_code == 200:
                path.write_bytes(r.content)
        except Exception as e:
            print(f"[downloader] download_task error for post {post.get('id')}: {e}")

    # ------------------------------------------------------------------
    # Utils
    # ------------------------------------------------------------------

    def get_valid_folder(self, tags):
        safe = re.sub(r'[<>:"/\\|?*]', "", tags)
        safe = safe.replace(" ", "_")[:100] or "unsorted"
        path = settings.DOWNLOAD_DIR / settings.ACTIVE_BOORU / safe
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_credentials(self, name, uid, api_key):
        settings.CREDENTIALS[name] = {"user_id": uid, "api_key": api_key}
        settings.set_credential(name, uid, api_key)
        settings.save()

    async def close(self):
        pass
