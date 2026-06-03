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
        }
        params.update(self.get_pagination_params(page, limit))
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

    # ##################################################################
    # Used by the downloader to determine the smart folder name (artist/character/etc)
    def get_categorized_tags(self, post: dict) -> dict:
        tags = self.get_tags(post)
        cats = {"artist": [], "character": [], "copyright": [], "meta": [], "general": []}
        for t in tags:
            if t.startswith("artist:"):
                cats["artist"].append(t.replace("artist:", "").strip())
            elif t.startswith("character:"):
                cats["character"].append(t.replace("character:", "").strip())
            else:
                cats["general"].append(t)
        return cats
    # ##################################################################


    def get_tag_autocomplete_urls(self, site_data: dict, prefix: str) -> list[str]:
        base = site_data.get("url", "")
        return [f"{base}/api/v1/json/search/tags?q={prefix}*"]

    def parse_tag_autocomplete(self, data) -> list[dict]:
        if isinstance(data, dict):
            tags = data.get("tags", [])
        else:
            tags = data if isinstance(data, list) else []
            
        res = []
        for t in tags:
            if not isinstance(t, dict): continue
            category = t.get("category", "general")
            # Convert philomena specific categories if needed, but they use text like "character"
            res.append({
                "name": t.get("name", ""),
                "type": category,
                "count": t.get("images", 0)
            })
        return res
