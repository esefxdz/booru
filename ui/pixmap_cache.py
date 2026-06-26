"""
ui/pixmap_cache.py — Byte-bounded LRU cache for decoded QPixmap thumbnails.

Extracted from ui/gallery.py so the cache is self-contained and testable
independently of the gallery widget.
"""

from __future__ import annotations

from collections import OrderedDict
from PyQt6.QtGui import QPixmap

# Default memory budget: 48 MB of decoded pixmap data.
# Each 250×250 ARGB32 pixmap is ~250 KB, so this holds ~190 thumbnails.
DEFAULT_MAX_BYTES = 48 * 1024 * 1024


class PixmapLRU:
    """Byte-bounded LRU cache for decoded QPixmap thumbnails.

    Tracks actual pixel memory (width × height × 4 bytes/pixel) and
    evicts the least-recently-used entries when the total exceeds
    *max_bytes*.
    """

    __slots__ = ("_data", "_sizes", "_total", "_max")

    def __init__(self, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self._data: OrderedDict[str, QPixmap] = OrderedDict()
        self._sizes: dict[str, int] = {}
        self._total: int = 0
        self._max: int = max_bytes

    @staticmethod
    def _estimate(pm: QPixmap) -> int:
        """Estimate memory footprint (ARGB32 = 4 bytes per pixel)."""
        return max(pm.width() * pm.height() * 4, 1)

    # ── Public API ──────────────────────────────────────────────

    def get(self, key) -> QPixmap | None:
        key = str(key)
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def put(self, key, pixmap: QPixmap) -> None:
        key = str(key)
        size = self._estimate(pixmap)
        if key in self._data:
            self._total -= self._sizes[key]
            self._data.move_to_end(key)
        self._data[key] = pixmap
        self._sizes[key] = size
        self._total += size
        while self._total > self._max and self._data:
            oldest_key, _ = self._data.popitem(last=False)
            self._total -= self._sizes.pop(oldest_key, 0)

    def clear(self) -> None:
        self._data.clear()
        self._sizes.clear()
        self._total = 0
