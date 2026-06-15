"""
moebooru.py - Adapter for Moebooru-based sites.
Covers: Yande.re, Konachan, older Danbooru forks
"""
from .base import BaseAdapter


class MoebooruAdapter(BaseAdapter):
    api_type = "moebooru"
    label = "Moebooru (yande.re, konachan)"

    def build_url(self, site_data: dict) -> str:
        return f"{site_data.get('url', '')}/post.json"

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        params = {"tags": tags, "limit": limit}
        params.update(self.get_pagination_params(page, limit))
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
        # Moebooru tags endpoint
        return [f"{base}/tag.json?limit=20&name=*{prefix}*"]

    def parse_tag_autocomplete(self, data) -> list[dict]:
        TYPE_MAP = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "circle", 6: "faults"}
        if not isinstance(data, list):
            return []
        return [
            {"name": t.get("name", ""), "type": TYPE_MAP.get(t.get("type", 0), "general"), "count": t.get("count", 0)}
            for t in data if t.get("name")
        ]
