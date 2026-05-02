"""
base.py - Base adapter interface for all booru APIs.
"""

class BaseAdapter:
    """Base class for all booru API adapters."""
    api_type: str = "base"
    label: str = "Base Adapter"

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

    def get_categorized_tags(self, post: dict) -> dict:
        """Return tags grouped by category. Default: all under 'general'."""
        return {
            "artist": [],
            "copyright": [],
            "meta": [],
            "general": self.get_tags(post),
        }
