"""
philomena.py - Adapter for Philomena-based sites (MLP boorus).
Covers: Derpibooru, Ponerpics, etc.
"""
from .base import BaseAdapter


class PhilomenaAdapter(BaseAdapter):
    api_type = "philomena"
    label = "Philomena (MLP boorus)"

    def build_url(self, site_data: dict) -> str:
        return f"{site_data['url']}/api/v1/json/search/images"

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        params = {
            "q": tags if tags else "*",
            "per_page": limit,
            "page": page + 1,
        }
        if creds.get("api_key"):
            params["key"] = creds["api_key"]
        return params

    def parse_response(self, r, site_data: dict) -> list:
        try:
            data = r.json()
            if isinstance(data, dict) and "images" in data:
                return data["images"]
            return []
        except Exception:
            return []

    def get_preview_url(self, post: dict) -> str:
        representations = post.get("representations", {})
        if isinstance(representations, dict):
            return representations.get("thumb", "") or representations.get("small", "")
        return ""

    def get_file_url(self, post: dict) -> str:
        representations = post.get("representations", {})
        if isinstance(representations, dict):
            return representations.get("full", "") or representations.get("large", "")
        return ""

    def get_sample_url(self, post: dict) -> str:
        representations = post.get("representations", {})
        if isinstance(representations, dict):
            return representations.get("large", "") or representations.get("full", "")
        return ""

    def get_tags(self, post: dict) -> list:
        tags = post.get("tags", [])
        if isinstance(tags, list):
            # Tags are typically objects with 'name' field
            result = []
            for tag in tags:
                if isinstance(tag, dict) and "name" in tag:
                    result.append(tag["name"])
                elif isinstance(tag, str):
                    result.append(tag)
            return result
        return []
