"""
ui/search_bar/__init__.py

Re-exports search bar components so existing imports keep working:
    from ui.search_bar import BooruSearchBar
"""
from ui.search_bar.search_tag_chip import SearchTagChip
from ui.search_bar.search_bar import BooruSearchBar

__all__ = ["SearchTagChip", "BooruSearchBar"]
