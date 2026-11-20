from urllib.parse import quote as _urlquote
import logging
from .base import BaseAdapter


class E621Adapter(BaseAdapter):
    api_type = "e621"
    label = "e621 / e926"

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
            if isinstance(data, dict):
                return data.get("posts", [])
            return data if isinstance(data, list) else []  # 2026 format: a bare list
        except Exception as e:
            logging.getLogger("adapters").warning(
                "[e621] could not parse response from %s (HTTP %s): %s",
                str(getattr(r, "url", "?")).split("?")[0], getattr(r, "status_code", "?"), e)
            return []

    @staticmethod
    def _url(post: dict, old_key: str, new_key: str, new_field: str) -> str:
        # Old format: post[old_key]["url"]; 2026 format: post["files"][new_key][new_field].
        files = post.get("files")
        if isinstance(files, dict):
            obj = files.get(new_key)
            return (obj.get(new_field) or "") if isinstance(obj, dict) else ""
        obj = post.get(old_key)
        return (obj.get("url") or "") if isinstance(obj, dict) else ""

    def get_preview_url(self, post: dict) -> str:
        return self._url(post, "preview", "preview", "jpg")

    def get_file_url(self, post: dict) -> str:
        return self._url(post, "file", "original", "url")

    def get_sample_url(self, post: dict) -> str:
        return self._url(post, "sample", "sample", "jpg") or self.get_file_url(post)

    def get_tags(self, post: dict) -> list:
        tag_obj = post.get("tags", {})
        if isinstance(tag_obj, list):
            return [t for t in tag_obj if isinstance(t, str)]
        if isinstance(tag_obj, dict):
            result = []
            for cats in tag_obj.values():
                if isinstance(cats, list):
                    result.extend(cats)
            return result
        return []

    def get_categorized_tags(self, post: dict) -> dict:
        tag_obj = post.get("tags", {})
        if not isinstance(tag_obj, dict):
            return {"artist": [], "copyright": [], "character": [], "meta": [],
                    "general": self.get_tags(post)}
        return {
            "artist": tag_obj.get("artist", []),
            "copyright": tag_obj.get("copyright", []),
            "character": tag_obj.get("character", []),
            "meta": tag_obj.get("meta", []),
            "general": tag_obj.get("general", []) + tag_obj.get("species", []),
        }

    def get_tag_autocomplete_urls(self, site_data: dict, prefix: str) -> list[str]:
        base = site_data.get("url", "")
        q = _urlquote(prefix, safe="*")
        return [f"{base}/tags.json?search[name_matches]={q}*&limit=20&search[order]=count"]

    def parse_tag_autocomplete(self, data) -> list[dict]:
        TYPE_MAP = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "general", 7: "meta"}
        if not isinstance(data, list):
            return []
        return [
            {"name": t.get("name", ""), "type": TYPE_MAP.get(t.get("category", 0), "general"), "count": t.get("post_count", 0)}
            for t in data if t.get("name")
        ]
