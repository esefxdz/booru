"""
base.py - Base adapter interface for all booru APIs.

Provides the BaseAdapter contract, a NormalizedPost dataclass for
standardized output, and helpers for pagination / rating normalization.
"""
from dataclasses import dataclass, field


@dataclass
class NormalizedPost:
    """Standardized post representation — every adapter MUST produce this."""
    id: str = ""
    file_url: str = ""
    preview_url: str = ""
    sample_url: str = ""
    tags: list = field(default_factory=list)
    rating: str = "unknown"        # safe | questionable | explicit | unknown
    score: int = 0
    source: str = ""
    _raw: dict = field(default_factory=dict, repr=False)
    _booru: str = ""


# Rating aliases produced by different engines → canonical value
_RATING_MAP = {
    "s": "safe", "safe": "safe", "general": "safe", "g": "safe",
    "q": "questionable", "questionable": "questionable", "suggestive": "questionable",
    "e": "explicit", "explicit": "explicit",
}


def _resolve_url(url: str) -> str:
    """Ensure protocol-relative URLs get an https: prefix."""
    if url and url.startswith("//"):
        return "https:" + url
    return url or ""


class BaseAdapter:
    """Base class for all booru API adapters."""
    api_type: str = "base"
    label: str = "Base Adapter"

    # -- Pagination style (overridden per-engine) --------------------------
    #    "page1"  → 1-indexed page numbers (Danbooru, Moebooru, e621, …)
    #    "pid"    → offset = page * limit   (Gelbooru DAPI, html_scraper)
    #    "offset" → raw offset              (Szurubooru)
    pagination_style: str = "page1"

    def get_pagination_params(self, page_index: int, limit: int) -> dict:
        """Convert a 0-based page_index into engine-specific params.
        The controller only ever passes page_index; the adapter does the math.
        """
        if self.pagination_style == "pid":
            return {"pid": page_index}
        elif self.pagination_style == "offset":
            return {"offset": page_index * limit}
        else:  # "page1" (default)
            return {"page": page_index + 1}

    # -- Core interface (must be overridden) --------------------------------

    def build_url(self, site_data: dict) -> str:
        """Build the API endpoint URL."""
        raise NotImplementedError

    def build_params(self, tags: str, limit: int, page: int, creds: dict) -> dict:
        """Build query parameters for API request."""
        raise NotImplementedError

    def parse_response(self, r, site_data: dict) -> list:
        """Parse API response into list of posts."""
        raise NotImplementedError

    def get_preview_url(self, post: dict) -> str:
        """Extract preview/thumbnail URL from post."""
        raise NotImplementedError

    def get_file_url(self, post: dict) -> str:
        """Extract full image/video URL from post."""
        raise NotImplementedError

    def get_sample_url(self, post: dict) -> str:
        """Extract medium sample URL from post."""
        raise NotImplementedError

    def get_tags(self, post: dict) -> list:
        """Extract list of tags from post."""
        raise NotImplementedError

    # -- Normalization helpers (opt-in) ------------------------------------

    def get_rating(self, post: dict) -> str:
        """Normalize rating string to safe|questionable|explicit|unknown."""
        raw = str(post.get("rating", "")).lower().strip()
        return _RATING_MAP.get(raw, "unknown")

    def normalize_post(self, post: dict) -> NormalizedPost:
        """Convert a raw API post dict into a NormalizedPost."""
        return NormalizedPost(
            id=str(post.get("id", "")),
            file_url=_resolve_url(self.get_file_url(post)),
            preview_url=_resolve_url(self.get_preview_url(post)),
            sample_url=_resolve_url(self.get_sample_url(post)),
            tags=self.get_tags(post),
            rating=self.get_rating(post),
            score=int(post.get("score", 0) or 0),
            source=str(post.get("source", "")),
            _raw=post,
        )

    def get_categorized_tags(self, post: dict) -> dict:
        """Return tags grouped by category. Default: all under 'general'."""
        return {
            "artist": [],
            "character": [],
            "copyright": [],
            "meta": [],
            "general": self.get_tags(post),
        }

    def get_tag_autocomplete_urls(self, site_data: dict, prefix: str) -> list[str]:
        """Return a list of URLs to try for tag autocomplete (fallback chain)."""
        return []

    def parse_tag_autocomplete(self, data) -> list[dict]:
        """Parse autocomplete response into [{name, type, count}] list."""
        return []
