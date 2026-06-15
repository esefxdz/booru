"""
danbooru.py - Adapter for Danbooru-based sites.
Covers: Danbooru, SafebooruDonmai
"""
from .base import BaseAdapter


class DanbooruAdapter(BaseAdapter):
    api_type = "danbooru"
    label = "Danbooru (danbooru.donmai.us)"

    def build_url(self, site_data: dict) -> str:
        return f"{site_data.get('url', '')}/posts.json"

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
        # Danbooru splits tags across category-specific fields.  The old
        # code only read tag_string_general, silently dropping artist,
        # character, copyright, and meta tags.
        tag_fields = (
            "tag_string_general", "tag_string_artist", "tag_string_character",
            "tag_string_copyright", "tag_string_meta",
        )
        all_tags = []
        for field in tag_fields:
            val = post.get(field, "")
            if val:
                all_tags.extend(val.replace(",", " ").split())
        return all_tags

    # ##################################################################
    # Used by the downloader to determine the smart folder name (artist/character/etc)
    def get_categorized_tags(self, post: dict) -> dict:
        def split(field):
            return post.get(field, "").replace(",", " ").split()
        return {
            "artist": split("tag_string_artist"),
            "character": split("tag_string_character"),
            "copyright": split("tag_string_copyright"),
            "meta": split("tag_string_meta"),
            "general": split("tag_string_general"),
        }
    # ##################################################################

    def get_tag_autocomplete_urls(self, site_data: dict, prefix: str) -> list[str]:
        base = site_data.get("url", "")
        return [
            f"{base}/autocomplete.json?search[query]={prefix}&search[type]=tag_query&limit=15",
            f"{base}/tags.json?search[name_matches]={prefix}*&limit=15"
        ]

    def parse_tag_autocomplete(self, data) -> list[dict]:
        TYPE_MAP = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}
        if not isinstance(data, list):
            return []
            
        res = []
        for t in data:
            if "type" in t and "value" in t:
                # Format 1: autocomplete.json -> {"type":"tag-word","value":"1girl","category":0,"post_count":7830183}
                cat = t.get("category", 0)
                if "tag" in t and isinstance(t["tag"], dict):
                    cat = t["tag"].get("category", cat)
                res.append({
                    "name": t["value"],
                    "type": TYPE_MAP.get(cat, "general"),
                    "count": t.get("post_count", 0)
                })
            elif "name" in t:
                # Format 2: tags.json fallback
                res.append({
                    "name": t["name"],
                    "type": TYPE_MAP.get(t.get("category", 0), "general"),
                    "count": t.get("post_count", 0)
                })
        return res
