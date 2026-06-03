"""
szurubooru.py - Adapter for Szurubooru (modern booru engine).
"""
from .base import BaseAdapter


class SzurubooruAdapter(BaseAdapter):
    api_type = "szurubooru"
    label = "Szurubooru"
    pagination_style = "offset"

    def build_url(self, site_data: dict) -> str:
        return f"{site_data['url']}/api/posts"

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        params = {
            "query": tags if tags else "*",
            "limit": limit,
        }
        params.update(self.get_pagination_params(page, limit))
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

    # ##################################################################
    # Used by the downloader to determine the smart folder name (artist/character/etc)
    def get_categorized_tags(self, post: dict) -> dict:
        tags = post.get("tags", [])
        res = {"artist": [], "character": [], "copyright": [], "meta": [], "general": []}
        if not isinstance(tags, list):
            return res
            
        for t in tags:
            if not isinstance(t, dict): continue
            names = t.get("names", [])
            if not names: continue
            name = names[0]
            cat = t.get("category", "general")
            
            if cat in res:
                res[cat].append(name)
            else:
                res["general"].append(name)
        return res
    # ##################################################################

    def get_tag_autocomplete_urls(self, site_data: dict, prefix: str) -> list[str]:
        base = site_data.get("url", "")
        return [f"{base}/api/tags?query={prefix}*"]

    def parse_tag_autocomplete(self, data) -> list[dict]:
        if not isinstance(data, dict):
            return []
        results = data.get("results", [])
        res = []
        for t in results:
            if not isinstance(t, dict): continue
            names = t.get("names", [])
            if not names: continue
            res.append({
                "name": names[0],
                "type": t.get("category", "general"),
                "count": t.get("usages", 0)
            })
        return res
