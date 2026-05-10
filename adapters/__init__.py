"""
adapters/ — API adapters for different booru software families.

Supported booru types:
  - Gelbooru: safebooru, gelbooru, rule34, xbooru, realbooru, hypnohub, + most custom sites
  - Danbooru: danbooru.donmai.us, safebooru_donmai
  - Moebooru: yande.re, konachan.com (and forks)
  - e621: e621.net, e926.net (furry boorus)
  - Szurubooru: modern booru engine
  - Philomena: derpibooru, ponerpics (MLP boorus)
  - Shimmie2: older booru engine
  - Zerochan: HTML-based imageboard
  - HTML Scraper: fallback for unknown sites
"""

from .base import BaseAdapter, NormalizedPost
from .gelbooru import GelbooruAdapter
from .danbooru import DanbooruAdapter
from .moebooru import MoebooruAdapter
from .e621 import E621Adapter
from .szurubooru import SzurubooruAdapter
from .philomena import PhilomenaAdapter
from .shimmie2 import Shimmie2Adapter
from .zerochan import ZerochanAdapter
from .html_scraper import HtmlScraperAdapter

# --- Adapter Registry ---
ADAPTERS: dict = {
    "gelbooru": GelbooruAdapter(),
    "danbooru": DanbooruAdapter(),
    "moebooru": MoebooruAdapter(),
    "e621": E621Adapter(),
    "szurubooru": SzurubooruAdapter(),
    "philomena": PhilomenaAdapter(),
    "shimmie2": Shimmie2Adapter(),
    "zerochan": ZerochanAdapter(),
    "html_scraper": HtmlScraperAdapter(),
}


def get_adapter(api_type: str):
    """
    Return the adapter for the given api_type.
    Falls back to HTML scraper, then Gelbooru if not found.
    """
    if api_type in ADAPTERS:
        return ADAPTERS[api_type]
    # Fallback to HTML scraper for unknown types, then Gelbooru
    return ADAPTERS.get("html_scraper", ADAPTERS["gelbooru"])


def adapter_choices() -> list:
    """
    Returns [(api_type, label), ...] for UI dropdowns.
    Sorted by popularity.
    """
    order = ["gelbooru", "danbooru", "e621", "moebooru", "szurubooru", 
             "philomena", "shimmie2", "zerochan", "html_scraper"]
    return [(api_type, ADAPTERS[api_type].label) for api_type in order if api_type in ADAPTERS]


__all__ = [
    "BaseAdapter",
    "NormalizedPost",
    "GelbooruAdapter",
    "DanbooruAdapter",
    "MoebooruAdapter",
    "E621Adapter",
    "SzurubooruAdapter",
    "PhilomenaAdapter",
    "Shimmie2Adapter",
    "ZerochanAdapter",
    "HtmlScraperAdapter",
    "ADAPTERS",
    "get_adapter",
    "adapter_choices",
]

