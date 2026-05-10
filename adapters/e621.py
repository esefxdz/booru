"""
e621.py - Adapter for e621 / e926 (furry boorus).
Covers: e621.net, e926.net (with nested JSON structure and species tags)
"""
from .base import BaseAdapter


class E621Adapter(BaseAdapter):
    api_type = "e621"
    label = "e621 / e926"

    def build_url(self, site_data: dict) -> str:
        return f"{site_data['url']}/posts.json"

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        params = {"tags": tags, "limit": limit}
        params.update(self.get_pagination_params(page, limit))
        if creds.get("api_key") and creds.get("user_id"):
            params["login"] = creds["user_id"]
            params["api_key"] = creds["api_key"]
        return params

    def parse_response(self, r, site_data: dict) -> list:
        try:
            data = r.json()
            if isinstance(data, dict):
                return data.get("posts", [])
            return []
        except Exception:
            return []

    def get_preview_url(self, post: dict) -> str:
        preview = post.get("preview", {})
        return preview.get("url") if isinstance(preview, dict) else ""

    def get_file_url(self, post: dict) -> str:
        file_obj = post.get("file", {})
        return file_obj.get("url") if isinstance(file_obj, dict) else ""

    def get_sample_url(self, post: dict) -> str:
        sample = post.get("sample", {})
        url = sample.get("url") if isinstance(sample, dict) else ""
        return url or self.get_file_url(post)

    def get_tags(self, post: dict) -> list:
        tag_obj = post.get("tags", {})
        if isinstance(tag_obj, dict):
            result = []
            for cats in tag_obj.values():
                if isinstance(cats, list):
                    result.extend(cats)
            return result
        return []

    # ##################################################################
    # Used by the downloader to determine the smart folder name (artist/character/etc)
    def get_categorized_tags(self, post: dict) -> dict:
        tag_obj = post.get("tags", {})
        if not isinstance(tag_obj, dict):
            return {"artist": [], "copyright": [], "meta": [], "general": []}
        return {
            "artist": tag_obj.get("artist", []),
            "copyright": tag_obj.get("copyright", []),
            "character": tag_obj.get("character", []),
            "meta": tag_obj.get("meta", []),
            "general": tag_obj.get("general", []) + tag_obj.get("species", []),
        }
    # ##################################################################

    def get_tag_autocomplete_urls(self, site_data: dict, prefix: str) -> list[str]:
        base = site_data.get("url", "")
        return [f"{base}/tags.json?search[name_matches]={prefix}*&limit=20&search[order]=count"]

    def parse_tag_autocomplete(self, data) -> list[dict]:
        TYPE_MAP = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "general", 7: "meta"}
        if not isinstance(data, list):
            return []
        return [
            {"name": t.get("name", ""), "type": TYPE_MAP.get(t.get("category", 0), "general"), "count": t.get("post_count", 0)}
            for t in data if t.get("name")
        ]
