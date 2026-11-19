"""Autocomplete URLs must percent-encode the typed prefix."""
import pytest
from urllib.parse import urlsplit, parse_qsl

from adapters.danbooru import DanbooruAdapter
from adapters.e621 import E621Adapter
from adapters.gelbooru import GelbooruAdapter
from adapters.html_scraper import HtmlScraperAdapter
from adapters.moebooru import MoebooruAdapter
from adapters.philomena import PhilomenaAdapter
from adapters.shimmie2 import Shimmie2Adapter
from adapters.szurubooru import SzurubooruAdapter
from adapters.zerochan import ZerochanAdapter

ADAPTERS = [DanbooruAdapter, E621Adapter, GelbooruAdapter, HtmlScraperAdapter,
            MoebooruAdapter, PhilomenaAdapter, Shimmie2Adapter,
            SzurubooruAdapter, ZerochanAdapter]
SITE = {"url": "https://example.test"}


@pytest.mark.parametrize("cls", ADAPTERS)
@pytest.mark.parametrize("prefix", ["a&b", "x#y", "two words", "caf\u00e9", "a+b=c"])
def test_prefix_is_encoded(cls, prefix):
    urls = cls().get_tag_autocomplete_urls(SITE, prefix)
    assert urls
    for u in urls:
        parts = urlsplit(u)
        assert parts.fragment == ""
        assert " " not in u and "\u00e9" not in u
        values = [v for _, v in parse_qsl(parts.query, keep_blank_values=True)]
        assert any(prefix in v for v in values), u


@pytest.mark.parametrize("cls", ADAPTERS)
def test_wildcard_star_preserved(cls):
    urls = cls().get_tag_autocomplete_urls(SITE, "ab*")
    assert any("ab*" in u for u in urls)
