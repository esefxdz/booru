"""
html_scraper.py - HTML scraper fallback for Gelbooru-like sites.
Used as a fallback when JSON API fails.
"""
import re
from .base import BaseAdapter


class HtmlScraperAdapter(BaseAdapter):
    api_type = "html_scraper"
    label = "HTML Scraper (Gelbooru Fallback)"

    def build_url(self, site_data: dict) -> str:
        return f"{site_data['url']}/index.php"

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        return {
            "page": "post",
            "s": "list",
            "tags": tags,
            "pid": page * limit,
        }

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
