"""
gelbooru.py - Adapter for Gelbooru-based sites.
Covers: Gelbooru, Safebooru, Rule34, xBooru, RealBooru, HypnoHub, etc.
"""
from .base import BaseAdapter


class GelbooruAdapter(BaseAdapter):
    api_type = "gelbooru"
    label = "Gelbooru (most sites)"
    pagination_style = "pid"

    def build_url(self, site_data: dict) -> str:
        return f"{site_data.get('url', '')}{site_data.get('api_path', '/index.php')}"

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        params = {
            "page": "dapi", "s": "post", "q": "index",
            "json": 1, "tags": tags, "limit": limit,
        }
        params.update(self.get_pagination_params(page, limit))
        if creds.get("api_key"):
            params["api_key"] = creds["api_key"]
            params["user_id"] = creds["user_id"]
        return params

    def parse_response(self, r, site_data: dict) -> list:
        try:
            data = r.json()
            if isinstance(data, list):
                return data
            key = site_data.get("post_key")
            if key and key in data:
                return data[key]
            return data.get("post", [])
        except Exception:
            # Fallback to XML parsing for legacy booru.org / Gelbooru 0.1 sites that ignore json=1
            try:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(r.text)
                posts = []
                for p in root.findall('.//post'):
                    posts.append(p.attrib)
                return posts
            except Exception:
                return []

    def get_preview_url(self, post: dict) -> str:
        return post.get("preview_url") or post.get("sample_url") or post.get("file_url") or ""

    def get_file_url(self, post: dict) -> str:
        return post.get("file_url") or post.get("content_url") or ""

    def get_sample_url(self, post: dict) -> str:
        return post.get("sample_url") or post.get("file_url") or ""

    def get_tags(self, post: dict) -> list:
        tags = post.get("tags", "")
        if isinstance(tags, str):
            return tags.replace(",", " ").split()
        if isinstance(tags, list):
            return [str(t).replace(",", "") for t in tags]
        return []

    # ##################################################################
    # Used by the downloader to determine the smart folder name (artist/character/etc)
    def get_categorized_tags(self, post: dict) -> dict:
        tags = self.get_tags(post)
        cats = {"artist": [], "character": [], "copyright": [], "meta": [], "general": []}
        for t in tags:
            if ":" in t:
                # Handle namespaces like artist:name, character:name, etc.
                parts = t.split(":", 1)
                prefix = parts[0].lower()
                val = parts[1]
                if prefix in cats:
                    cats[prefix].append(val)
                else:
                    cats["general"].append(t)
            else:
                cats["general"].append(t)
        return cats
    # ##################################################################

    def get_tag_autocomplete_urls(self, site_data: dict, prefix: str) -> list[str]:
        base = site_data.get("url", "")
        api_path = site_data.get("api_path", "/index.php")
        return [
            f"{base}{api_path}?page=autocomplete2&term={prefix}&type=tag_query&limit=15",
            f"{base}/autocomplete.php?q={prefix}"
        ]

    def parse_tag_autocomplete(self, data) -> list[dict]:
        if not isinstance(data, list):
            return []
        res = []
        for t in data:
            if not isinstance(t, dict): continue
            # Format 1: autocomplete2 API -> {"label": "tag", "post_count": "123", "category": "tag"}
            if "post_count" in t:
                res.append({
                    "name": t.get("value", ""),
                    "type": t.get("category", "general") if t.get("category") != "tag" else "general",
                    "count": int(t.get("post_count", 0))
                })
            # Format 2: autocomplete.php -> {"label": "1girl (12345)", "value": "1girl"}
            elif "label" in t and "value" in t:
                lbl = t["label"]
                count = 0
                if "(" in lbl and lbl.endswith(")"):
                    try:
                        count = int(lbl.split("(")[-1].replace(")", ""))
                    except ValueError:
                        pass
                res.append({
                    "name": t["value"],
                    "type": "general",
                    "count": count
                })
        return res
