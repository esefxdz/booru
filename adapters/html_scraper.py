"""
html_scraper.py - HTML scraper fallback for Gelbooru-like sites.
Used as a fallback when JSON API fails.
"""
import re
from .base import BaseAdapter


class HtmlScraperAdapter(BaseAdapter):
    api_type = "html_scraper"
    label = "HTML Scraper (Gelbooru Fallback)"
    pagination_style = "pid"

    def build_url(self, site_data: dict) -> str:
        return f"{site_data['url']}/index.php"

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        params = {
            "page": "post",
            "s": "list",
            "tags": tags,
        }
        params.update(self.get_pagination_params(page, limit))
        return params

    def parse_response(self, r, site_data: dict) -> list:
        """Parse HTML page for post data."""
        # Regex to find: <a href="...id=XXX"...><img src="...thumbnails/..." title="tag1 tag2..." />
        matches = re.findall(
            r'<a[^>]*href="[^"]+id=(\d+)"[^>]*>.*?'
            r'<img[^>]*src="([^"]+/thumbnails/[^"]+)"[^>]*title="([^"]*)"',
            r.text,
            re.IGNORECASE | re.DOTALL,
        )
        
        posts = []
        base_url = site_data["url"].rstrip("/")

        for pid, thumb, title in matches:
            # Reconstruct the thumbnail URL properly
            if thumb.startswith("//"):
                thumb = "https:" + thumb
            elif thumb.startswith("/"):
                thumb = base_url + thumb

            # Reconstruct the file URL by removing /thumbnails/ and thumbnail_ prefixes
            # Example: /thumbnails/24/44/thumbnail_12345.jpg -> /images/24/44/12345.jpg
            file_path = thumb.replace("/thumbnails/", "/images/").replace("thumbnail_", "")

            # Guess the extension based on tags
            if "webm" in title.lower():
                file_path = file_path.replace(".jpg", ".webm")
            elif "gif" in title.lower():
                file_path = file_path.replace(".jpg", ".gif")
            elif "png" in title.lower():
                file_path = file_path.replace(".jpg", ".png")

            posts.append({
                "id": pid,
                "file_url": file_path,
                "preview_url": thumb,
                "tags": title.strip(),
            })
        return posts

    def get_preview_url(self, post: dict) -> str:
        return post.get("preview_url", "")

    def get_file_url(self, post: dict) -> str:
        return post.get("file_url", "")

    def get_sample_url(self, post: dict) -> str:
        return post.get("file_url", "")

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
        return [
            f"{base}/index.php?page=autocomplete2&term={prefix}&type=tag_query&limit=15",
            f"{base}/autocomplete.php?q={prefix}"
        ]

    def parse_tag_autocomplete(self, data) -> list[dict]:
        if not isinstance(data, list):
            return []
        res = []
        for t in data:
            if not isinstance(t, dict): continue
            if "post_count" in t:
                res.append({
                    "name": t.get("value", ""),
                    "type": t.get("category", "general") if t.get("category") != "tag" else "general",
                    "count": int(t.get("post_count", 0))
                })
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
