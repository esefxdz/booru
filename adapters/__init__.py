"""API adapters, one per booru software family."""

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
    """Adapter for *api_type*; unknown types fall back to the HTML scraper."""
    if api_type in ADAPTERS:
        return ADAPTERS[api_type]
    return ADAPTERS.get("html_scraper", ADAPTERS["gelbooru"])


def adapter_choices() -> list:
    """[(api_type, label), ...] for UI dropdowns, most popular first."""
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

