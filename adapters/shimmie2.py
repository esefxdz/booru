"""
shimmie2.py - Adapter for Shimmie2-based sites.
Older booru engine with simpler JSON/HTML APIs.
"""
from .base import BaseAdapter


class Shimmie2Adapter(BaseAdapter):
    api_type = "shimmie2"
    label = "Shimmie2 (older booru engine)"

    def build_url(self, site_data: dict) -> str:
        return f"{site_data['url']}/api/json/index"

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        params = {
            "search": tags if tags else "*",
            "limit": limit,
            "page": page,
        }
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
