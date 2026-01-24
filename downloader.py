import asyncio
import httpx
import os
import re
from pathlib import Path
from io import BytesIO
from PIL import Image
import config


class BooruDownloader:

    def __init__(self):
        self.site_data = config.BOORUS[config.ACTIVE_BOORU]
        self.headers = config.DEFAULT_HEADERS.copy()

        self.client = httpx.AsyncClient(
            headers=self.headers,
            timeout=config.TIMEOUT,
            http2=True
        )

        self.thumb_cache = {}

    # ---------------------------------------------------------
    # POSTS METADATA
    # ---------------------------------------------------------

    async def get_image_urls(self, tags, limit, page=0):
        url = f"{self.site_data['url']}{self.site_data['api_path']}"

        search_tags = tags.strip()

        if config.BLACKLIST:
            blacklist = " ".join(f"-{t}" for t in config.BLACKLIST.split())
            search_tags = f"{search_tags} {blacklist}"

        params = {
            "page": "dapi",
            "s": "post",
            "q": "index",
            "json": 1,
            "tags": search_tags,
            "limit": limit,
            "pid": page
        }

        creds = config.CREDENTIALS.get(config.ACTIVE_BOORU, {})
        if creds.get("api_key"):
            params["api_key"] = creds.get("api_key")
            params["user_id"] = creds.get("user_id")

        try:
            r = await self.client.get(url, params=params)
            if r.status_code != 200:
                return []

            data = r.json()

            if isinstance(data, list):
                return data

            key = self.site_data.get("post_key")
            if key and key in data:
                return data[key]

            return data.get("post", [])

        except Exception:
            return []

    # ---------------------------------------------------------
    # THUMBNAILS
    # ---------------------------------------------------------

    async def fetch_previews(self, posts, callback):

        loop = asyncio.get_running_loop()

        async def fetch_one(post, index):
            post_id = post.get("id")

            if post_id in self.thumb_cache:
                callback(self.thumb_cache[post_id], post, index)
                return

            url = (
                post.get(config.PREVIEW_QUALITY)
                or post.get("preview_url")
                or post.get("sample_url")
                or post.get("file_url")
            )

            if not url:
                return

            if url.startswith("//"):
                url = "https:" + url

            try:
                r = await self.client.get(url, timeout=5.0)
                if r.status_code != 200:
                    return

                raw = r.content

                # decode PIL image in worker thread
                def decode():
                    img = Image.open(BytesIO(raw))
                    img.thumbnail(
                        (config.THUMBNAIL_SIZE, config.THUMBNAIL_SIZE),
                        Image.LANCZOS
                    )
                    return img

                img = await loop.run_in_executor(None, decode)

                self.thumb_cache[post_id] = img
                callback(img, post, index)

            except Exception:
                pass

        await asyncio.gather(
            *(fetch_one(post, i) for i, post in enumerate(posts))
        )

    # ---------------------------------------------------------
    # FULL DOWNLOAD
    # ---------------------------------------------------------

    async def download_task(self, client, post, folder):
        url = post.get("file_url") or post.get("content_url")
        if not url:
            return

        if url.startswith("//"):
            url = "https:" + url

        ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
        name = f"{post.get('id', 'image')}{ext}"
        path = folder / name

        try:
            r = await self.client.get(url, timeout=60)
            if r.status_code == 200:
                path.write_bytes(r.content)
        except Exception:
            pass

    # ---------------------------------------------------------
    # UTILS
    # ---------------------------------------------------------

    def get_valid_folder(self, tags):
        safe = re.sub(r'[<>:"/\\|?*]', "", tags)
        safe = safe.replace(" ", "_")[:100] or "unsorted"

        path = config.DOWNLOAD_DIR / config.ACTIVE_BOORU / safe
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_tag_list(self, post):
        tags = post.get("tags", "")
        if isinstance(tags, str):
            return tags.split()
        if isinstance(tags, list):
            return tags
        return []

    def save_credentials(self, name, uid, api_key):
        config.CREDENTIALS[name] = {
            "user_id": uid,
            "api_key": api_key
        }

        return self._update_config_file(
            "CREDENTIALS =",
            f"CREDENTIALS = {config.CREDENTIALS}\n"
        )

    def _update_config_file(self, prefix, newline):
        try:
            with open("config.py", "r", encoding="utf-8") as f:
                lines = f.readlines()

            with open("config.py", "w", encoding="utf-8") as f:
                for line in lines:
                    if line.strip().startswith(prefix):
                        f.write(newline)
                    else:
                        f.write(line)
            return True
        except Exception:
            return False

    async def close(self):
        try:
            await self.client.aclose()
        except Exception:
            pass
