"""
ui/gallery.py — Virtualised, widget-pooled thumbnail gallery.

Posts are stored as pure data dicts.  A fixed pool of recycled
(tile, star) QPushButton pairs is maintained by ``TilePool``.
On each scroll event only posts in the ±2 viewport buffer zone
are assigned a slot.  Posts that leave the zone release their slot.

Sub-systems extracted:
  - Pixmap LRU cache    → ui/pixmap_cache.py
  - Widget tile pool    → ui/tile_pool.py
  - Layout + Y-index    → ui/gallery_layout.py
  - Bookmark toggling   → signal emitted; handled by gui.py
"""

from __future__ import annotations

import logging
from PyQt6.QtWidgets import (
    QWidget, QScrollArea, QVBoxLayout, QPushButton, QLabel,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, pyqtSignal, QRect
from PyQt6.QtGui import QPixmap, QIcon, QPainter, QPainterPath

from ui import settings_view as settings
from ui import colors
from ui.pixmap_cache import PixmapLRU, DEFAULT_MAX_BYTES as PX_CACHE_DEFAULT
from ui.tile_pool import TilePool
from ui.gallery_layout import GalleryLayout
import thumb_cache
import ui.animations as anims

log = logging.getLogger(__name__)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║                         CLASS: Gallery                              ║
# ╚══════════════════════════════════════════════════════════════════════╝
class Gallery(QWidget):
    """Scrollable, virtualised thumbnail gallery with widget-pool recycling."""

    load_more_requested = pyqtSignal()
    bookmark_toggled = pyqtSignal(dict, bool)  # post, is_now_bookmarked

    # ── Virtualization tunables ────────────────────────────────
    _BUFFER_ZONE_PAGES = 2
    _EVICT_ZONE_PAGES = 4
    _POOL_MIN = 60
    _POOL_MAX = 150

    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app

        # ── Layout tunables ────────────────────────────────────
        self._col_count = 4
        self._col_width = 250
        self._spacing = 16
        self._scroll_guard = False

        # ── Pixmap cache ───────────────────────────────────────
        self._px_cache = PixmapLRU(PX_CACHE_DEFAULT)

        # ── Post data (no widgets — pure data) ─────────────────
        self._posts: list[dict] = []
        self._post_id_set: set = set()
        self._post_id_to_idx: dict = {}
        self._rects: list[QRect] = []
        self._post_bytes: dict = {}       # post_idx → JPEG bytes
        self._post_bookmarked: dict = {}  # post_idx → bool
        self._post_animated: set = set()
        self._aspect_ratios: dict[int, float] = {}

        # ── Y-index for O(log n) viewport queries ──────────────
        self._y_index: list[tuple[int, int]] = []

        # ── Build widget tree ──────────────────────────────────
        self._build_ui()

        # ── Tile pool (recycled widget pairs) ──────────────────
        self._tiles = TilePool(self.container, self._POOL_MIN, self._POOL_MAX)

        # ── Scroll ─────────────────────────────────────────────
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # ── Deferred refresh timer (coalesces rapid relayouts) ─
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(50)
        self._refresh_timer.timeout.connect(self._do_refresh)

        # ── Deferred eviction timer (coalesces rapid scroll events) ─
        self._evict_timer = QTimer(self)
        self._evict_timer.setSingleShot(True)
        self._evict_timer.setInterval(200)
        self._evict_timer.timeout.connect(self._evict_offscreen_bytes)

    # ══════════════════════════════════════════════════════════════
    #  UI Construction
    # ══════════════════════════════════════════════════════════════

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {colors.MAIN_BG}; }}"
        )

        self.container = QWidget()
        self.container.setStyleSheet(f"background: {colors.MAIN_BG};")
        self.scroll.setWidget(self.container)

        self._empty_lbl = QLabel("No results", self.container)
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(
            f"color: {colors.TEXT_SECONDARY}; font-size: 18px;"
        )
        self._empty_lbl.setGeometry(0, 80, 400, 40)
        self._empty_lbl.hide()

        layout.addWidget(self.scroll)

    # ══════════════════════════════════════════════════════════════
    #  Window resize — recalculate column count
    # ══════════════════════════════════════════════════════════════

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_timer.start()  # coalesce rapid resizes into one relayout

    # ══════════════════════════════════════════════════════════════
    #  Scroll + viewport virtualization
    # ══════════════════════════════════════════════════════════════

    def _on_scroll(self, value: int):
        self._update_viewport()
        self._evict_timer.start()

        if not settings.manager.infinite_scroll or self._scroll_guard:
            return
        sb = self.scroll.verticalScrollBar()
        if value >= sb.maximum() - 400:
            self._scroll_guard = True
            self.load_more_requested.emit()
            QTimer.singleShot(1500, lambda: setattr(self, "_scroll_guard", False))

    def check_infinite_scroll_fill(self):
        """If the viewport isn't full after a fetch, request more posts."""
        if not settings.manager.infinite_scroll or self._scroll_guard:
            return
        QTimer.singleShot(100, self._check_fill)

    def _check_fill(self):
        sb = self.scroll.verticalScrollBar()
        if sb.maximum() <= 10 and len(self._posts) > 0:
            self._scroll_guard = True
            self.load_more_requested.emit()

    # ══════════════════════════════════════════════════════════════
    #  Layout refresh
    # ══════════════════════════════════════════════════════════════

    def refresh_layout(self):
        """Public entry point — called by settings view when layout mode changes."""
        self._refresh_timer.start()  # coalesced relayout

    def _do_refresh(self):
        """Recalculate layout, then update which slots are visible."""
        self._refresh_timer.stop()  # cancel any pending timer — we're doing it now
        self._evict_timer.stop()
        self._col_width = settings.manager.thumbnail_size
        available_w = self.scroll.viewport().width()
        # Account for spacing so the rightmost tile does not overflow
        self._col_count = max(1, (available_w + self._spacing) // (self._col_width + self._spacing))
        tile_sz = max(50, self._col_width)

        use_masonry = getattr(settings.manager, "masonry_mode", False)
        if use_masonry:
            GalleryLayout.apply_masonry(
                self._rects, len(self._posts),
                self._aspect_ratios,
                self._col_count, self._col_width, self._spacing,
            )
        else:
            h = GalleryLayout.apply_grid(
                self._rects, len(self._posts),
                self._col_count, self._spacing, tile_sz,
            )
            self.container.setMinimumHeight(max(h, 0))

        self._empty_lbl.setVisible(len(self._posts) == 0)
        self._y_index = GalleryLayout.rebuild_y_index(self._rects)

        # Grow pool if needed
        wanted = self._tiles.compute_pool_size(
            self.scroll.viewport().width(),
            self.scroll.viewport().height(),
            self._col_width,
            self._BUFFER_ZONE_PAGES,
            use_masonry,
        )
        self._tiles.grow_if_needed(wanted)

        self._update_viewport()

    def _update_viewport(self):
        """Map/unmap pool slots based on current scroll position."""
        vp = self.scroll.verticalScrollBar()
        vp_y, vp_h = vp.value(), self.scroll.viewport().height()
        buffer_margin = vp_h * self._BUFFER_ZONE_PAGES

        wanted = set(
            GalleryLayout.find_visible(
                self._y_index,
                vp_y - buffer_margin,
                vp_y + vp_h + buffer_margin,
            )
        ) if self._y_index else set()

        target_pool = max(
            self._tiles.compute_pool_size(
                self.scroll.viewport().width(), vp_h, self._col_width,
                self._BUFFER_ZONE_PAGES,
                getattr(settings.manager, "masonry_mode", False),
            ),
            len(wanted),
        )
        self._tiles.grow_if_needed(target_pool)

        currently_mapped = set(self._tiles.post_to_slot.keys())

        # Release scrolled-out posts
        for post_idx in (currently_mapped - wanted):
            slot_idx = self._tiles.post_to_slot.get(post_idx)
            if slot_idx is not None:
                self._tiles.release(slot_idx)

        # Update geometry for already-mapped posts (resize / column change)
        for post_idx in (wanted & currently_mapped):
            slot_idx = self._tiles.post_to_slot.get(post_idx)
            if slot_idx is None or post_idx >= len(self._rects):
                continue
            btn, star = self._tiles[slot_idx]
            rect = self._rects[post_idx]
            btn.setGeometry(rect)
            btn.setIconSize(rect.size())

        # Assign free slots to newly-visible posts (closest to centre first)
        vp_centre = vp_y + vp_h / 2
        def _dist_to_centre(pidx: int) -> float:
            r = self._rects[pidx]
            return abs(r.y() + r.height() / 2 - vp_centre)

        for post_idx in sorted(wanted - currently_mapped, key=_dist_to_centre):
            if post_idx >= len(self._rects):
                continue
            if not self._tiles.free_slots:
                log.warning(
                    "[gallery] Pool exhausted (%d slots, %d wanted).",
                    len(self._tiles), len(wanted),
                )
                break
            slot_idx = self._tiles.free_slots.pop()

            pixmap = self._get_or_make_pixmap(post_idx)
            self._tiles.assign(
                slot_idx, post_idx, self._rects[post_idx],
                pixmap,
                self._post_bookmarked.get(post_idx, False),
                post_idx in self._post_animated,
                lambda checked, p=self._posts[post_idx], b=self._tiles[slot_idx][0]: self._on_btn_clicked(p, b),
                lambda checked, p=self._posts[post_idx], s=self._tiles[slot_idx][1]: self._on_star_clicked(p, s),
            )
            if pixmap is not None:
                self._post_animated.add(post_idx)

    def _evict_offscreen_bytes(self):
        """Free JPEG bytes from posts far outside the viewport buffer."""
        vp = self.scroll.verticalScrollBar()
        vp_y, vp_h = vp.value(), self.scroll.viewport().height()
        if vp_h <= 0:
            return
        margin = vp_h * self._EVICT_ZONE_PAGES
        evict_top = vp_y - margin
        evict_bottom = vp_y + vp_h + margin

        for idx in list(self._post_bytes.keys()):
            if idx >= len(self._rects):
                continue
            r = self._rects[idx]
            if r.isNull():
                continue
            if r.y() + r.height() < evict_top or r.y() > evict_bottom:
                del self._post_bytes[idx]
                self._post_animated.discard(idx)

    # ══════════════════════════════════════════════════════════════
    #  Public API
    # ══════════════════════════════════════════════════════════════

    def prepare_skeletons(self, posts):
        """Register posts as pure data. No widgets are created here."""
        from ui.bookmarks_main.bookmarks_db import db
        incoming_ids = [str(p.get("id")) for p in posts if p.get("id")]
        bookmarked_set = db.are_posts_bookmarked(incoming_ids)

        for post in posts:
            post_id = post.get("id")
            if post_id in self._post_id_set:
                continue
            self._post_id_set.add(post_id)

            idx = len(self._posts)
            self._posts.append(post)
            self._post_id_to_idx[post_id] = idx
            self._rects.append(QRect())
            self._post_bookmarked[idx] = str(post_id) in bookmarked_set
            if idx not in self._aspect_ratios:
                self._aspect_ratios[idx] = self._get_aspect_ratio(post)

        self._do_refresh()

    @pyqtSlot(bytes, dict, int)
    def add_item(self, safe_bytes: bytes, post: dict, idx: int):
        """Called when a thumbnail finishes downloading."""
        post_id = post.get("id")

        # Pre-decode and cache the pixmap
        pixmap = self._decode_pixmap(safe_bytes)
        self._px_cache.put(post_id, pixmap)

        post_idx = self._post_id_to_idx.get(post_id)
        if post_idx is not None:
            self._post_bytes[post_idx] = safe_bytes
            slot_idx = self._tiles.post_to_slot.get(post_idx)
            if slot_idx is not None:
                # Refresh the tile in-place
                rect = self._rects[post_idx] if post_idx < len(self._rects) else QRect()
                self._tiles.assign(
                    slot_idx, post_idx, rect, pixmap,
                    self._post_bookmarked.get(post_idx, False),
                    post_idx in self._post_animated,
                    lambda checked, p=post, b=self._tiles[slot_idx][0]: self._on_btn_clicked(p, b),
                    lambda checked, p=post, s=self._tiles[slot_idx][1]: self._on_star_clicked(p, s),
                )
                self._post_animated.add(post_idx)
            return

        # Fallback: post wasn't pre-registered
        self.prepare_skeletons([post])
        post_idx = self._post_id_to_idx.get(post_id)
        if post_idx is not None:
            self._post_bytes[post_idx] = safe_bytes
        self._update_viewport()

    def clear(self):
        """Release all slots and wipe post data. Pool widgets survive."""
        for slot_idx in list(self._tiles.slot_to_post.keys()):
            self._tiles.release(slot_idx)

        self._posts.clear()
        self._post_id_set.clear()
        self._post_id_to_idx.clear()
        self._rects.clear()
        self._aspect_ratios.clear()
        self._post_bytes.clear()
        self._post_bookmarked.clear()
        self._post_animated.clear()
        self._y_index.clear()
        self.container.setMinimumHeight(0)
        self._px_cache.clear()
        self._evict_timer.stop()

    def open_preview(self, post):
        self.main_app.open_preview(post)

    def get_adjacent_post(self, post_id, direction: str = "next"):
        """Return the prev/next post dict, or None if at the boundary.

        Used by the overlay for prev_post / next_post navigation so
        external code never touches ``_posts`` or ``_post_id_to_idx``.
        """
        idx = self._post_id_to_idx.get(post_id)
        if idx is None:
            return None
        target = idx - 1 if direction == "prev" else idx + 1
        if 0 <= target < len(self._posts):
            return self._posts[target]
        return None

    def refresh_visible_stars(self):
        """Re-render bookmark stars for all currently assigned tiles.

        Used after a bookmark toggle so the star icons update without
        a full viewport rebuild.
        """
        self._update_viewport()

    # ══════════════════════════════════════════════════════════════
    #  Helpers
    # ══════════════════════════════════════════════════════════════

    def _on_btn_clicked(self, post, btn):
        anims.animate_button_press(btn)
        self.open_preview(post)

    def _on_star_clicked(self, post, star_btn):
        """Emit signal so gui.py handles the DB write."""
        pid = post.get("id")
        # Toggle: figure out new state
        post_idx = self._post_id_to_idx.get(pid)
        is_now_bookmarked = not self._post_bookmarked.get(post_idx, False)
        if post_idx is not None:
            self._post_bookmarked[post_idx] = is_now_bookmarked
        self._style_star(star_btn, is_now_bookmarked, 16)
        self.bookmark_toggled.emit(post, is_now_bookmarked)

    def _get_or_make_pixmap(self, post_idx: int) -> QPixmap | None:
        """Return the decoded QPixmap for a post, or None if not loaded."""
        post_id = self._posts[post_idx].get("id") if post_idx < len(self._posts) else None
        if post_id is None:
            return None

        # Try L1 cache first
        cached = self._px_cache.get(post_id)
        if cached is not None:
            return cached

        # Try raw bytes
        safe_bytes = self._post_bytes.get(post_idx)
        if safe_bytes is None:
            # Try reloading from thumb_cache (L1 memory / L2 disk)
            safe_bytes = thumb_cache.get(str(post_id))
            if safe_bytes is not None:
                self._post_bytes[post_idx] = safe_bytes

        if safe_bytes is not None:
            pixmap = self._decode_pixmap(safe_bytes)
            self._px_cache.put(post_id, pixmap)
            return pixmap

        return None

    def _decode_pixmap(self, safe_bytes: bytes) -> QPixmap:
        """Decode JPEG bytes → scaled, rounded QPixmap (single code path)."""
        pixmap = QPixmap()
        pixmap.loadFromData(safe_bytes)
        max_w = max(400, settings.manager.thumbnail_size * 2)
        if pixmap.width() > max_w:
            pixmap = pixmap.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
        return _round_pixmap(pixmap)

    def _get_aspect_ratio(self, post: dict) -> float:
        """Extract aspect ratio from post metadata (width/height)."""
        w = post.get("image_width") or post.get("width") or 0
        h = post.get("image_height") or post.get("height") or 0
        if w > 0 and h > 0:
            return w / h
        return 0.0

    def _style_star(self, star_btn, is_bookmarked, font_sz):
        color_val = colors.FAVORITE if is_bookmarked else colors.TEXT_PRIMARY
        opacity = 0.7 if is_bookmarked else 0.4
        star_btn.setStyleSheet(f"""
            QPushButton {{
                color: {color_val};
                font-size: {font_sz}px;
                background-color: rgba(0, 0, 0, {opacity});
                border-radius: {font_sz}px;
                border: 1px solid rgba(255,255,255,0.1);
            }}
            QPushButton:hover {{
                color: {colors.FAVORITE};
                background-color: rgba(0, 0, 0, 0.9);
                border: 1px solid {colors.FAVORITE};
            }}
        """)


def _round_pixmap(pixmap: QPixmap, radius: int = 12) -> QPixmap:
    """Return a copy of *pixmap* with rounded corners."""
    target = QPixmap(pixmap.size())
    target.fill(Qt.GlobalColor.transparent)
    painter = QPainter(target)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return target
