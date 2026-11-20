"""
ui/gallery_layout.py — Layout engines for the virtualised gallery.

Two layout strategies:
  - Grid: uniform square tiles arranged in columns
  - Masonry: waterfall layout where each tile is placed in the shortest
    column based on its intrinsic aspect ratio

Also contains the Y-index binary search used for O(log n) viewport
intersection queries.
"""

from __future__ import annotations

import bisect
from PyQt6.QtCore import QRect


class GalleryLayout:
    """Stateless layout calculator — call ``apply()`` with post data.

    Does NOT own any widgets or state.  Given a list of aspect ratios
    and layout parameters, fills a pre-allocated list of QRect objects.
    """

    @staticmethod
    def apply_grid(
        rects: list[QRect],
        n: int,
        col_count: int,
        spacing: int,
        tile_size: int,
    ) -> int:
        """Fill *rects* with uniform grid positions.  Returns total height."""
        while len(rects) < n:
            rects.append(QRect())

        for idx in range(n):
            row = idx // col_count
            col = idx % col_count
            x = spacing + col * (tile_size + spacing)
            y = spacing + row * (tile_size + spacing)
            rects[idx] = QRect(x, y, tile_size, tile_size)

        rows = (n + col_count - 1) // col_count if n else 0
        return rows * (tile_size + spacing) + spacing

    @staticmethod
    def apply_masonry(
        rects: list[QRect],
        n: int,
        aspect_ratios: dict[int, float],
        col_count: int,
        col_width: int,
        spacing: int,
    ) -> int:
        """Fill *rects* with waterfall/masonry positions.  Returns total height."""
        while len(rects) < n:
            rects.append(QRect())

        if n == 0:
            return 0

        col_count = max(1, col_count)
        col_width = max(50, col_width)

        min_h = col_width // 2
        max_h = col_width * 3
        col_bottoms = [spacing] * col_count

        for idx in range(n):
            ar = aspect_ratios.get(idx, 0.0)
            if ar > 0.01:
                h = max(min_h, min(int(col_width / ar), max_h))
            else:
                h = col_width  # square fallback

            col = min(range(col_count), key=lambda c: col_bottoms[c])
            x = spacing + col * (col_width + spacing)
            y = col_bottoms[col]

            rects[idx] = QRect(x, y, col_width, h)
            col_bottoms[col] = y + h + spacing

        return max(col_bottoms) + spacing

    # ── Y-index — O(log n) viewport intersection ────────────────

    @staticmethod
    def rebuild_y_index(rects: list[QRect]) -> list[tuple[int, int]]:
        """Return a sorted list of (y_top, post_index) for binary search."""
        return sorted(
            (rects[i].y(), i)
            for i in range(len(rects))
            if not rects[i].isNull()
        )

    @staticmethod
    def find_visible(
        y_index: list[tuple[int, int]],
        y_start: int,
        y_end: int,
    ) -> list[int]:
        """Return post indices whose rects overlap [y_start, y_end]."""
        if not y_index:
            return []
        ys = [entry[0] for entry in y_index]
        lo = bisect.bisect_left(ys, y_start)
        hi = bisect.bisect_right(ys, y_end)
        return [y_index[i][1] for i in range(max(0, lo - 1), min(len(y_index), hi + 1))]
