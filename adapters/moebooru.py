"""
moebooru.py - Adapter for Moebooru-based sites.
Covers: Yande.re, Konachan, older Danbooru forks
"""
from .base import BaseAdapter


class MoebooruAdapter(BaseAdapter):
    api_type = "moebooru"
    label = "Moebooru (yande.re, konachan)"

    def build_url(self, site_data: dict) -> str:
        return f"{site_data['url']}/post.json"

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        params = {"tags": tags, "limit": limit, "page": page + 1}
        if creds.get("api_key") and creds.get("user_id"):
            params["login"] = creds["user_id"]
            params["password_hash"] = creds["api_key"]
        return params

    def parse_response(self, r, site_data: dict) -> list:
        try:
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def get_preview_url(self, post: dict) -> str:
        return post.get("preview_url") or post.get("sample_url") or post.get("file_url") or ""

    def get_file_url(self, post: dict) -> str:
        return post.get("file_url") or post.get("sample_url") or ""

    def get_sample_url(self, post: dict) -> str:
        return post.get("sample_url") or post.get("file_url") or ""

    def get_tags(self, post: dict) -> list:
        tags = post.get("tags", "")
        return tags.replace(",", " ").split() if tags else []
