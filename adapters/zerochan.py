"""
zerochan.py - Adapter for Zerochan (HTML-based API).
"""
import re
from .base import BaseAdapter


class ZerochanAdapter(BaseAdapter):
    api_type = "zerochan"
    label = "Zerochan (HTML parsing)"

    def get_pagination_params(self, page_index: int, limit: int) -> dict:
        return {"p": page_index + 1}

    def build_url(self, site_data: dict) -> str:
        return f"{site_data['url']}/search"

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        params = {"q": tags if tags else "*"}
        params.update(self.get_pagination_params(page, limit))
        return params

    def parse_response(self, r, site_data: dict) -> list:
        """Parse Zerochan HTML response to extract image data."""
        try:
            # Zerochan stores image data in JSON embedded in HTML
            # Look for patterns like <li data-tags="..." data-id="..." style="..."
            matches = re.findall(
                r'<li[^>]*data-id="(\d+)"[^>]*data-tags="([^"]*)"[^>]*>.*?'
                r'<img[^>]*src="([^"]+)"[^>]*alt="([^"]*)"',
                r.text,
                re.DOTALL | re.IGNORECASE
            )
            
            posts = []
            base_url = site_data["url"].rstrip("/")
            
            for post_id, tags_str, img_src, title in matches:
                # Zerochan serves thumbnails; construct full image URL
                if img_src.startswith("//"):
                    img_src = "https:" + img_src
                elif img_src.startswith("/"):
                    img_src = base_url + img_src
                
                # Convert thumbnail URL to full image
                file_url = img_src.replace("/thumbnail/", "/image/").replace(".webp", "")
                
                posts.append({
                    "id": post_id,
                    "file_url": file_url,
                    "preview_url": img_src,
                    "tags": tags_str.split(),
                    "title": title,
                })
            return posts
        except Exception:
            return []

    def get_preview_url(self, post: dict) -> str:
        return post.get("preview_url", "")

    def get_file_url(self, post: dict) -> str:
        return post.get("file_url", "")

    def get_sample_url(self, post: dict) -> str:
        return post.get("file_url", "")

    def get_tags(self, post: dict) -> list:
        tags = post.get("tags", [])
        if isinstance(tags, list):
            return tags
        elif isinstance(tags, str):
            return tags.split()
        return []

    # ##################################################################
    # Used by the downloader to determine the smart folder name (artist/character/etc)
    def get_categorized_tags(self, post: dict) -> dict:
        return {
            "artist": [],
            "character": [],
            "copyright": [],
            "meta": [],
            "general": self.get_tags(post),
        }
    # ##################################################################

    def get_tag_autocomplete_urls(self, site_data: dict, prefix: str) -> list[str]:
        base = site_data.get("url", "")
        return [f"{base}/suggest?q={prefix}"]

    def parse_tag_autocomplete(self, data) -> list[dict]:
        if not isinstance(data, list):
            return []
        # Zerochan returns ["tag1", "tag2"] or [{"name": "tag1"}] occasionally depending on API.
        res = []
        for t in data:
            if isinstance(t, str):
                res.append({"name": t, "type": "general", "count": 0})
            elif isinstance(t, dict) and "name" in t:
                res.append({"name": t["name"], "type": "general", "count": 0})
        return res
