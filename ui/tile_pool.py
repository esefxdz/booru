"""
ui/tile_pool.py — Recycled widget pool for the virtualised gallery.

Instead of creating one QPushButton per post (which would cause Qt
layout thrash and unbounded RAM growth under infinite scroll), we
maintain a fixed pool of (tile, star) button pairs.  Posts that scroll
into view are *assigned* a free slot; posts that scroll out *release*
their slot back to the free list.

The pool starts empty, grows on demand, and never shrinks (the widgets
are reused for the lifetime of the Gallery).
"""

from __future__ import annotations

from PyQt6.QtWidgets import QPushButton, QWidget
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QIcon, QPixmap

from ui import colors
import ui.animations as anims


class TilePool:
    """Manages a fixed-size pool of recycled (tile, star) QPushButton pairs.

    Parameters
    ----------
    container : QWidget
        The parent widget that owns all pool children.
    pool_min : int
        Minimum number of slots regardless of viewport size.
    pool_max : int
        Hard cap to prevent unbounded memory use.
    """

    def __init__(
        self,
        container: QWidget,
        pool_min: int = 60,
        pool_max: int = 150,
    ) -> None:
        self._container = container
        self._pool_min = pool_min
        self._pool_max = pool_max

        # (tile_btn, star_btn) pairs
        self._pool: list[tuple[QPushButton, QPushButton]] = []
        # Indices of unused slots
        self._free_slots: list[int] = []

        # Reverse mappings for O(1) lookup
        self._slot_to_post: dict[int, int] = {}
        self._post_to_slot: dict[int, int] = {}

    # ── Read-only access for Gallery ────────────────────────────

    @property
    def slot_to_post(self) -> dict[int, int]:
        return self._slot_to_post

    @property
    def post_to_slot(self) -> dict[int, int]:
        return self._post_to_slot

    @property
    def free_slots(self) -> list[int]:
        return self._free_slots

    def __len__(self) -> int:
        return len(self._pool)

    def __getitem__(self, slot_idx: int) -> tuple[QPushButton, QPushButton]:
        return self._pool[slot_idx]

    # ── Sizing ──────────────────────────────────────────────────

    def compute_pool_size(
        self,
        viewport_width: int,
        viewport_height: int,
        col_width: int,
        buffer_zone_pages: int = 2,
        masonry_mode: bool = False,
    ) -> int:
        """Return the ideal pool size for the current viewport dimensions."""
        if viewport_width <= 0 or viewport_height <= 0 or col_width <= 0:
            return self._pool_min
        cols = max(1, viewport_width // col_width)
        # Masonry tiles can be shorter than square — use a conservative height
        tile_h = col_width // 2 if masonry_mode else col_width
        rows = max(1, viewport_height // max(tile_h, 1)) + 1
        target = cols * rows * (1 + 2 * buffer_zone_pages)
        return max(self._pool_min, min(target, self._pool_max))

    def grow_if_needed(self, target_size: int) -> None:
        """Allocate new pool slots until the pool reaches *target_size*."""
        while len(self._pool) < target_size:
            slot_idx = len(self._pool)

            btn = QPushButton(self._container)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.hide()

            star = QPushButton(btn)
            star.setText("\u2605")  # ★
            star.setCursor(Qt.CursorShape.PointingHandCursor)
            star.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

            self._pool.append((btn, star))
            self._free_slots.append(slot_idx)

    # ── Slot lifecycle ──────────────────────────────────────────

    def assign(
        self,
        slot_idx: int,
        post_idx: int,
        rect: QRect,
        pixmap: QPixmap | None,
        is_bookmarked: bool,
        already_animated: bool,
        on_clicked,
        on_star_clicked,
    ) -> None:
        """Bind *slot_idx* to display the post at *post_idx*.

        Disconnects stale signals, positions the tile, sets the icon
        (or skeleton background), and updates mappings.
        """
        btn, star = self._pool[slot_idx]

        # Disconnect previous post's signals
        try:
            btn.clicked.disconnect()
        except Exception:
            pass
        try:
            star.clicked.disconnect()
        except Exception:
            pass

        # Position
        btn.setGeometry(rect)
        btn.setIconSize(rect.size())
        star_sz = max(24, rect.width() // 8)
        star.setFixedSize(star_sz, star_sz)
        star.move(rect.width() - star_sz - 8, 8)

        # Connect new post
        btn.clicked.connect(on_clicked)
        star.clicked.connect(on_star_clicked)

        # Thumbnail or skeleton
        if pixmap is not None:
            btn.setIcon(QIcon(pixmap))
            border = f"2px solid {colors.FAVORITE}" if is_bookmarked else "none"
            btn.setStyleSheet(
                f"border: {border}; background: transparent; padding: 0; border-radius: 12px;"
            )
            if not already_animated:
                anims.animate_fade_in(btn, duration=500)
        else:
            btn.setIcon(QIcon())
            btn.setStyleSheet(
                f"border: none; background-color: {colors.BUTTON_BG}; "
                f"border-radius: 12px; padding: 0;"
            )

        btn.show()

        # Update mappings
        self._slot_to_post[slot_idx] = post_idx
        self._post_to_slot[post_idx] = slot_idx

    def release(self, slot_idx: int) -> None:
        """Return *slot_idx* to the free list."""
        btn, star = self._pool[slot_idx]
        btn.hide()
        btn.setIcon(QIcon())
        try:
            btn.clicked.disconnect()
        except Exception:
            pass
        try:
            star.clicked.disconnect()
        except Exception:
            pass

        post_idx = self._slot_to_post.pop(slot_idx, None)
        if post_idx is not None:
            self._post_to_slot.pop(post_idx, None)
        if slot_idx not in self._free_slots:
            self._free_slots.append(slot_idx)
