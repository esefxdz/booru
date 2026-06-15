"""
shimmie2.py - Adapter for Shimmie2-based sites.
Older booru engine with simpler JSON/HTML APIs.
"""
from .base import BaseAdapter


class Shimmie2Adapter(BaseAdapter):
    api_type = "shimmie2"
    label = "Shimmie2 (older booru engine)"

    def get_pagination_params(self, page_index: int, limit: int) -> dict:
        return {"page": page_index}  # Shimmie2 is 0-indexed

    def build_url(self, site_data: dict) -> str:
        return f"{site_data.get('url', '')}/api/json/index"

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        params = {
            "search": tags if tags else "*",
            "limit": limit,
        }
        params.update(self.get_pagination_params(page, limit))
        return params

    def parse_response(self, r, site_data: dict) -> list:
        try:
            data = r.json()
            # Shimmie2 typically returns {"posts": [...]} or a direct list
            if isinstance(data, dict):
                return data.get("posts", data.get("images", []))
            elif isinstance(data, list):
                return data
            return []
        except Exception:
            return []

    def get_preview_url(self, post: dict) -> str:
        # Try multiple possible field names
        return (
            post.get("preview_url")
            or post.get("thumbnail_url")
            or post.get("thumb_url")
            or post.get("preview")
            or ""
        )

    def get_file_url(self, post: dict) -> str:
        return post.get("image_url") or post.get("file_url") or post.get("url") or ""

    def get_sample_url(self, post: dict) -> str:
        return self.get_file_url(post)

    def get_tags(self, post: dict) -> list:
        tags = post.get("tags", "")
        if isinstance(tags, str):
            return tags.split()
        elif isinstance(tags, list):
            return tags
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
        return [f"{base}/api/internal/autocomplete?s={prefix}"]

    def parse_tag_autocomplete(self, data) -> list[dict]:
        if not isinstance(data, list):
            return []
        res = []
        for t in data:
            if isinstance(t, str):
                res.append({"name": t, "type": "general", "count": 0})
            elif isinstance(t, dict) and "name" in t:
                res.append({"name": t["name"], "type": "general", "count": t.get("count", 0)})
        return res
