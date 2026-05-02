"""
gelbooru.py - Adapter for Gelbooru-based sites.
Covers: Gelbooru, Safebooru, Rule34, xBooru, RealBooru, HypnoHub, etc.
"""
from .base import BaseAdapter


class GelbooruAdapter(BaseAdapter):
    api_type = "gelbooru"
    label = "Gelbooru (most sites)"

    def build_url(self, site_data: dict) -> str:
        return f"{site_data['url']}{site_data.get('api_path', '/index.php')}"

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        params = {
            "page": "dapi", "s": "post", "q": "index",
            "json": 1, "tags": tags, "limit": limit, "pid": page,
        }
        if creds.get("api_key"):
            params["api_key"] = creds["api_key"]
            params["user_id"] = creds["user_id"]
        return params

    def parse_response(self, r, site_data: dict) -> list:
        try:
            data = r.json()
            if isinstance(data, list):
                return data
            key = site_data.get("post_key")
            if key and key in data:
                return data[key]
            return data.get("post", [])
        except Exception:
            return []

    def get_preview_url(self, post: dict) -> str:
        return post.get("preview_url") or post.get("sample_url") or post.get("file_url") or ""

    def get_file_url(self, post: dict) -> str:
        return post.get("file_url") or post.get("content_url") or ""

    def get_sample_url(self, post: dict) -> str:
        return post.get("sample_url") or post.get("file_url") or ""

    def get_tags(self, post: dict) -> list:
        tags = post.get("tags", "")
        if isinstance(tags, str):
            return tags.replace(",", " ").split()
        if isinstance(tags, list):
            return [str(t).replace(",", "") for t in tags]
        return []
