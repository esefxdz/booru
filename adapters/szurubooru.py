"""
szurubooru.py - Adapter for Szurubooru (modern booru engine).
"""
from .base import BaseAdapter


class SzurubooruAdapter(BaseAdapter):
    api_type = "szurubooru"
    label = "Szurubooru"

    def build_url(self, site_data: dict) -> str:
        return f"{site_data['url']}/api/posts"

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        params = {
            "query": tags if tags else "*",
            "limit": limit,
            "offset": page * limit,
        }
        return params

    def parse_response(self, r, site_data: dict) -> list:
        try:
            data = r.json()
            if isinstance(data, dict) and "results" in data:
                return data["results"]
            return []
        except Exception:
            return []

    def get_preview_url(self, post: dict) -> str:
        thumbnail = post.get("thumbnail")
        if isinstance(thumbnail, dict):
            return thumbnail.get("url") or ""
        return post.get("thumbnail", "")

    def get_file_url(self, post: dict) -> str:
        content = post.get("content")
        if isinstance(content, dict):
            return content.get("url") or ""
        return post.get("content", "")

    def get_sample_url(self, post: dict) -> str:
        # Szurubooru doesn't typically have samples, use full file
        return self.get_file_url(post)

    def get_tags(self, post: dict) -> list:
        tags = post.get("tags", [])
        if isinstance(tags, list):
            # Tags are typically objects with 'names' field
            result = []
            for tag in tags:
                if isinstance(tag, dict) and "names" in tag:
                    result.extend(tag["names"])
                elif isinstance(tag, str):
                    result.append(tag)
            return result
        return []
