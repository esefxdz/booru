"""
danbooru.py - Adapter for Danbooru-based sites.
Covers: Danbooru, SafebooruDonmai
"""
from .base import BaseAdapter


class DanbooruAdapter(BaseAdapter):
    api_type = "danbooru"
    label = "Danbooru (danbooru.donmai.us)"

    def build_url(self, site_data: dict) -> str:
        return f"{site_data['url']}/posts.json"

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        params = {"tags": tags, "limit": limit, "page": page + 1}
        if creds.get("api_key") and creds.get("user_id"):
            params["login"] = creds["user_id"]
            params["api_key"] = creds["api_key"]
        return params

    def parse_response(self, r, site_data: dict) -> list:
        try:
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def get_preview_url(self, post: dict) -> str:
        return post.get("preview_file_url") or post.get("large_file_url") or post.get("file_url") or ""

    def get_file_url(self, post: dict) -> str:
        return post.get("file_url") or post.get("large_file_url") or ""

    def get_sample_url(self, post: dict) -> str:
        return post.get("large_file_url") or post.get("file_url") or ""

    def get_tags(self, post: dict) -> list:
        for field in ("tag_string", "tag_string_general"):
            val = post.get(field, "")
            if val:
                return val.replace(",", " ").split()
        return []

    def get_categorized_tags(self, post: dict) -> dict:
        def split(field):
            return post.get(field, "").replace(",", " ").split()
        return {
            "artist": split("tag_string_artist"),
            "copyright": split("tag_string_copyright") + split("tag_string_character"),
            "meta": split("tag_string_meta"),
            "general": split("tag_string_general"),
        }
