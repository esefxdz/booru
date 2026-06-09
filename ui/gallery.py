from PyQt6.QtWidgets import QWidget, QScrollArea, QVBoxLayout, QPushButton
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSlot, pyqtSignal, QRect
from PyQt6.QtGui import QPixmap, QIcon, QPainter, QPainterPath

from ui import settings_view as settings
from collections import OrderedDict
from ui import colors
import bisect


# ── QPixmap LRU (byte-bounded) ─────────────────────────────────
#
#   Holds decoded QPixmap objects ready for immediate display.
#   Unlike the old 500-entry cap, this tracks actual pixel memory
#   (width * height * 4 bytes/pixel) and evicts LRU entries when
#   the total exceeds _PX_CACHE_MAX_BYTES (48 MB default).
#
#   This is separate from thumb_cache (which stores raw JPEG bytes
#   in memory + SQLite).  The flow is:
#     thumb_cache.get(key) → raw JPEG bytes
#     _PixmapLRU.get(key)  → decoded QPixmap (display-ready)
# ────────────────────────────────────────────────────────────────
_PX_CACHE_MAX_BYTES = 48 * 1024 * 1024  # 48 MB


class _PixmapLRU:
    """Byte-bounded LRU cache for decoded QPixmap thumbnails."""

    __slots__ = ("_data", "_sizes", "_total", "_max")

    def __init__(self, max_bytes: int = _PX_CACHE_MAX_BYTES):
        self._data: OrderedDict[str, QPixmap] = OrderedDict()
        self._sizes: dict[str, int] = {}   # key → estimated byte size
        self._total: int = 0
        self._max: int = max_bytes

    @staticmethod
    def _estimate(pm: QPixmap) -> int:
        """Estimate the memory footprint of a QPixmap (ARGB32 = 4 bpp)."""
        return max(pm.width() * pm.height() * 4, 1)

    def get(self, key) -> QPixmap | None:
        key = str(key)
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def put(self, key, pixmap: QPixmap) -> None:
        key = str(key)
        size = self._estimate(pixmap)

        # Update existing
        if key in self._data:
            self._total -= self._sizes[key]
            self._data.move_to_end(key)
        self._data[key] = pixmap
        self._sizes[key] = size
        self._total += size

        # Evict LRU until under budget
        while self._total > self._max and self._data:
            oldest_key, _ = self._data.popitem(last=False)
            self._total -= self._sizes.pop(oldest_key, 0)

    def clear(self) -> None:
        self._data.clear()
        self._sizes.clear()
        self._total = 0


# ╔══════════════════════════════════════════════════════════════════════╗
# ║                         CLASS: Gallery                              ║
# ║                                                                     ║
# ║  True widget-pool virtualization.                                   ║
# ║                                                                     ║
# ║  Posts are stored as pure data dicts in self._posts. No QPushButton ║
# ║  is created per post. Instead, a fixed pool of recycled tile        ║
# ║  widgets is maintained. On each scroll event, only the posts in     ║
# ║  the ±2 viewport buffer zone are mapped to pool slots. Posts that   ║
# ║  leave the zone are unmapped (slot returned to the free list).      ║
# ║                                                                     ║
# ║  Pool size is dynamic: (cols × rows × 3), clamped to [60, 150].    ║
# ║  The pool grows when the viewport expands but never shrinks.        ║
# ╚══════════════════════════════════════════════════════════════════════╝
class Gallery(QWidget):
    load_more_requested = pyqtSignal()

    # ── Virtualization tunables ────────────────────────────────
    _BUFFER_ZONE_PAGES = 2   # ±2 viewport heights: render zone
    _EVICT_ZONE_PAGES  = 4   # ±4 viewport heights: JPEG byte eviction
    _POOL_MIN          = 60  # minimum pool size regardless of viewport
    _POOL_MAX          = 150 # maximum pool size to cap memory usage

    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app

        # ── Layout tunables ────────────────────────────────────
        self._col_count   = 4
        self._col_width   = 250
        self._spacing     = 16
        self._scroll_guard = False

        # ── QPixmap LRU — byte-bounded decoded pixmap cache ───
        self._px_cache = _PixmapLRU(_PX_CACHE_MAX_BYTES)

        # ── Post data storage (no widgets here) ───────────────
        #
        # _posts[i]         — the raw post dict
        # _post_id_set      — O(1) deduplication on insert
        # _post_id_to_idx   — O(1) reverse lookup: post_id → index
        # _rects[i]         — pre-calculated layout QRect
        # _post_bytes[i]    — JPEG thumbnail bytes (absent = not loaded yet)
        # _post_bookmarked  — cached bookmark state to avoid DB round-trips
        # _post_animated    — tracks which posts have had their fade-in played
        #
        self._posts: list[dict]     = []
        self._post_id_set: set      = set()
        self._post_id_to_idx: dict  = {}
        self._rects: list[QRect]    = []
        self._post_bytes: dict      = {}   # post_idx → bytes
        self._post_bookmarked: dict = {}   # post_idx → bool
        self._post_animated: set    = set()

        # ── Widget pool ───────────────────────────────────────
        #
        # _pool[slot_idx]   — (tile_QPushButton, star_QPushButton) pair
        # _free_slots       — pool indices not currently mapped to any post
        # _slot_to_post     — slot_idx → post_idx (currently mapped)
        # _post_to_slot     — post_idx → slot_idx (reverse, for fast lookup)
        #
        self._pool: list[tuple]    = []
        self._free_slots: list[int] = []
        self._slot_to_post: dict   = {}
        self._post_to_slot: dict   = {}

        # ── Y-sorted index for O(log n) viewport intersection ─
        self._y_index: list[tuple[int, int]] = []

        # ── Timers ────────────────────────────────────────────
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._do_refresh)

        # Eviction timer — runs after scroll settles to free JPEG bytes
        # from posts far outside the eviction zone.
        self._evict_timer = QTimer(self)
        self._evict_timer.setSingleShot(True)
        self._evict_timer.setInterval(300)
        self._evict_timer.timeout.connect(self._evict_offscreen_bytes)

        self.setup_ui()
        QTimer.singleShot(100, self.refresh_layout)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background-color: {colors.MAIN_BG}; }}"
        )
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        self.container = QWidget()
        self.container.setStyleSheet("background-color: transparent;")
        self.container.setMinimumHeight(0)

        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll)

    # ══════════════════════════════════════════════════════════════
    #  POOL MANAGEMENT
    # ══════════════════════════════════════════════════════════════

    def _compute_pool_size(self) -> int:
        """Calculate the ideal pool size based on current viewport dimensions.

        Formula: (columns × visible_rows × 3), clamped to [_POOL_MIN, _POOL_MAX].
        The ×3 factor ensures the buffer zone (±2 pages) always has free slots.
        """
        vp_w = self.scroll.viewport().width()
        vp_h = self.scroll.viewport().height()
        if vp_w <= 0 or vp_h <= 0 or self._col_width <= 0:
            return self._POOL_MIN
        cols = max(1, vp_w // self._col_width)
        rows = max(1, vp_h // self._col_width) + 1
        target = cols * rows * 3
        return max(self._POOL_MIN, min(self._POOL_MAX, target))

    def _grow_pool_if_needed(self, target_size: int):
        """Allocate new pool slots until pool reaches target_size.

        Slots are created as hidden QPushButton pairs (tile + star child).
        Signals are NOT connected here — they are connected in _assign_slot()
        each time a slot is recycled to a new post.
        """
        while len(self._pool) < target_size:
            slot_idx = len(self._pool)

            btn = QPushButton(self.container)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.hide()

            star = QPushButton(btn)
            star.setText("★")
            star.setCursor(Qt.CursorShape.PointingHandCursor)
            star.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

            self._pool.append((btn, star))
            self._free_slots.append(slot_idx)

    def _assign_slot(self, post_idx: int, slot_idx: int):
        """Configure pool slot *slot_idx* to display post at *post_idx*.

        Disconnects any stale signals from the previous assignment, repositions
        the widget to the post's rect, connects fresh click handlers, and sets
        the thumbnail icon (or skeleton background if not yet loaded).
        """
        post = self._posts[post_idx]
        rect = self._rects[post_idx]
        btn, star = self._pool[slot_idx]

        # ── Disconnect stale signals from previous post ────────
        try:
            btn.clicked.disconnect()
        except Exception:
            pass
        try:
            star.clicked.disconnect()
        except Exception:
            pass

        # ── Position and size ──────────────────────────────────
        btn.setGeometry(rect)
        btn.setIconSize(rect.size())
        star_sz = max(24, rect.width() // 8)
        star.setFixedSize(star_sz, star_sz)
        star.move(rect.width() - star_sz - 8, 8)

        # ── Connect to the new post ────────────────────────────
        btn.clicked.connect(lambda checked, p=post, b=btn: self._on_btn_clicked(p, b))
        star.clicked.connect(
            lambda checked, p=post, s=star: self._toggle_bookmark_direct(p, s)
        )

        # ── Load thumbnail ─────────────────────────────────────
        safe_bytes = self._post_bytes.get(post_idx)
        if safe_bytes is None:
            # Try to reload from the two-tier thumbnail cache (L1 memory / L2 disk)
            reloaded = self._reload_from_cache(post.get('id'))
            if reloaded is not None:
                self._post_bytes[post_idx] = reloaded
                safe_bytes = reloaded

        if safe_bytes:
            pixmap = self._get_l1_pixmap(post.get('id'), safe_bytes)
            btn.setIcon(QIcon(pixmap))
            btn.setStyleSheet("border: none; background: transparent; padding: 0;")
            if post_idx not in self._post_animated:
                import ui.animations as anims
                anims.animate_fade_in(btn, duration=500)
                self._post_animated.add(post_idx)
        else:
            # Skeleton state: grey placeholder while thumbnail is downloading
            btn.setIcon(QIcon())
            btn.setStyleSheet(
                f"border: none; background-color: {colors.BUTTON_BG}; "
                f"border-radius: 12px; padding: 0;"
            )

        self._style_star(star, self._post_bookmarked.get(post_idx, False), 16)
        btn.show()

        # ── Update mappings ────────────────────────────────────
        self._slot_to_post[slot_idx] = post_idx
        self._post_to_slot[post_idx] = slot_idx

    def _release_slot(self, slot_idx: int):
        """Return pool slot *slot_idx* to the free list.

        Hides the widget, clears its icon, disconnects signals, and removes
        the slot↔post mappings so the slot is safe to reassign.
        """
        btn, star = self._pool[slot_idx]
        btn.setIcon(QIcon())
        btn.hide()
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
        self._free_slots.append(slot_idx)

    # ══════════════════════════════════════════════════════════════
    #  SCROLL / INFINITE SCROLL
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
        if not settings.manager.infinite_scroll or self._scroll_guard:
            return
        QTimer.singleShot(100, self._check_bounds)

    def _check_bounds(self):
        if not settings.manager.infinite_scroll or self._scroll_guard:
            return
        sb = self.scroll.verticalScrollBar()
        if sb.maximum() <= 10 and len(self._posts) > 0:
            self._scroll_guard = True
            self.load_more_requested.emit()
            QTimer.singleShot(1500, lambda: setattr(self, "_scroll_guard", False))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_layout()
        self.check_infinite_scroll_fill()

    def refresh_layout(self):
        self._refresh_timer.start(50)

    def _do_refresh(self):
        w = self.scroll.viewport().width()
        if w < 100:
            w = self.width()

        target_sz = settings.manager.thumbnail_size
        if target_sz <= 0:
            target_sz = 250

        cols = max(1, w // target_sz)
        self._col_count = cols

        total_spacing = (cols + 1) * self._spacing
        self._col_width = (w - total_spacing) // cols
        if self._col_width < 50:
            self._col_width = 50

        self._recalculate_layout()
        self._rebuild_y_index()
        self._update_viewport()

    # ══════════════════════════════════════════════════════════════
    #  LAYOUT — uniform grid (masonry removed; was broken)
    # ══════════════════════════════════════════════════════════════

    def _recalculate_layout(self):
        self._apply_grid()

    def _apply_grid(self):
        """Place every post into a uniform grid and record its rect."""
        sz = self._col_width
        n  = len(self._posts)

        # Resize _rects to match current post count
        while len(self._rects) < n:
            self._rects.append(QRect())

        for idx in range(n):
            row = idx // self._col_count
            col = idx % self._col_count
            x = self._spacing + col * (sz + self._spacing)
            y = self._spacing + row * (sz + self._spacing)
            self._rects[idx] = QRect(x, y, sz, sz)

        rows  = (n + self._col_count - 1) // self._col_count if n else 0
        max_h = rows * (sz + self._spacing) + self._spacing
        self.container.setMinimumHeight(max(max_h, 0))

    # ══════════════════════════════════════════════════════════════
    #  Y-INDEX — O(log n) viewport intersection via binary search
    # ══════════════════════════════════════════════════════════════

    def _rebuild_y_index(self):
        """Rebuild the sorted Y-index from current rect positions.

        Each entry is (y_top, post_index), sorted by y_top so binary search
        can quickly find which posts overlap any given vertical range.
        """
        self._y_index = sorted(
            (self._rects[i].y(), i)
            for i in range(len(self._rects))
            if not self._rects[i].isNull()
        )

    def _find_visible_indices(self, y_start: int, y_end: int) -> list[int]:
        """Return post indices whose rects overlap [y_start, y_end].

        O(log n + k) where k is the number of matching posts.
        """
        if not self._y_index:
            return []

        # Items can start above y_start and still overlap — search back
        # by the maximum possible item height (square tiles = _col_width).
        max_item_height = self._col_width
        search_start    = y_start - max_item_height

        lo = bisect.bisect_left(self._y_index, (search_start,))

        result = []
        for i in range(lo, len(self._y_index)):
            y_top, idx = self._y_index[i]
            if y_top > y_end:
                break  # everything past here is below the viewport
            rect = self._rects[idx]
            if rect.y() + rect.height() >= y_start:
                result.append(idx)
        return result

    # ══════════════════════════════════════════════════════════════
    #  VIRTUALIZATION — pool-based viewport update
    # ══════════════════════════════════════════════════════════════

    def _update_viewport(self):
        """Map/unmap pool slots based on the current scroll position.

        Posts in the buffer zone (±2 viewport heights) are assigned a pool
        slot and displayed.  Posts outside that zone are unmapped — their
        slot is returned to the free list and can be reused for other posts.
        """
        vp_y = self.scroll.verticalScrollBar().value()
        vp_h = self.scroll.viewport().height()
        buffer_margin = vp_h * self._BUFFER_ZONE_PAGES
        vis_top    = vp_y - buffer_margin
        vis_bottom = vp_y + vp_h + buffer_margin

        # Grow pool if the viewport has become larger since last check
        target_pool = self._compute_pool_size()
        self._grow_pool_if_needed(target_pool)

        # Determine which post indices should be mapped
        if self._y_index:
            wanted = set(self._find_visible_indices(vis_top, vis_bottom))
        else:
            wanted = set()

        currently_mapped = set(self._post_to_slot.keys())

        # ── Release slots for posts that scrolled out ──────────
        for post_idx in (currently_mapped - wanted):
            self._release_slot(self._post_to_slot[post_idx])

        # ── Update geometry for already-mapped posts ───────────
        # (needed when the window is resized or column count changes)
        for post_idx in (wanted & currently_mapped):
            slot_idx = self._post_to_slot[post_idx]
            btn, star = self._pool[slot_idx]
            rect = self._rects[post_idx]
            btn.setGeometry(rect)
            btn.setIconSize(rect.size())

        # ── Assign free slots to newly visible posts ───────────
        for post_idx in sorted(wanted - currently_mapped):
            if not self._free_slots:
                # Pool is exhausted — this shouldn't happen if sized correctly.
                # Log so we can tune the pool constants if it ever does.
                import logging
                logging.warning(
                    "[gallery] Pool exhausted (%d slots, %d wanted). "
                    "Consider raising _POOL_MAX.",
                    len(self._pool), len(wanted),
                )
                break
            slot_idx = self._free_slots.pop()
            self._assign_slot(post_idx, slot_idx)

    def _evict_offscreen_bytes(self):
        """Free JPEG bytes from posts far outside the eviction zone.

        Posts beyond ±4 viewport heights have their raw bytes removed from
        _post_bytes. They remain registered in _posts (their metadata and
        rect are preserved). If the user scrolls back, the thumbnail is
        reloaded from thumb_cache (L1 memory or L2 SQLite disk).
        """
        vp_y = self.scroll.verticalScrollBar().value()
        vp_h = self.scroll.viewport().height()
        if vp_h <= 0:
            return

        evict_margin = vp_h * self._EVICT_ZONE_PAGES
        evict_top    = vp_y - evict_margin
        evict_bottom = vp_y + vp_h + evict_margin

        for idx in list(self._post_bytes.keys()):
            if idx >= len(self._rects):
                continue
            rect = self._rects[idx]
            if rect.isNull():
                continue
            if rect.y() + rect.height() < evict_top or rect.y() > evict_bottom:
                del self._post_bytes[idx]
                self._post_animated.discard(idx)

    def _reload_from_cache(self, post_id):
        """Reload thumbnail bytes from the two-tier cache (L1 memory / L2 disk)."""
        import thumb_cache
        return thumb_cache.get(post_id)

    # ══════════════════════════════════════════════════════════════
    #  PUBLIC API
    # ══════════════════════════════════════════════════════════════

    def prepare_skeletons(self, posts):
        """Register posts as pure data. No widgets are created here.

        Widgets are only ever allocated from the pool when a post scrolls
        into the ±2 viewport buffer zone, and returned when it leaves.
        This replaces the old approach of creating a permanent QPushButton
        per post, which caused Qt layout thrash and RAM growth under
        infinite scroll.
        """
        from ui.bookmarks_main.bookmarks_db import db
        for post in posts:
            post_id = post.get('id')
            if post_id in self._post_id_set:
                continue
            self._post_id_set.add(post_id)

            idx = len(self._posts)
            self._posts.append(post)
            self._post_id_to_idx[post_id] = idx
            self._rects.append(QRect())
            self._post_bookmarked[idx] = db.is_post_bookmarked(post_id)

        self._do_refresh()

    @pyqtSlot(bytes, dict, int)
    def add_item(self, safe_bytes: bytes, post: dict, idx: int):
        """Called by the download thread when a thumbnail finishes downloading."""
        post_id = post.get("id")

        # Pre-decode and cache the pixmap for instant display
        self._px_cache.put(post_id, self._decode_and_round(safe_bytes))

        post_idx = self._post_id_to_idx.get(post_id)
        if post_idx is not None:
            self._post_bytes[post_idx] = safe_bytes
            # If this post is currently in a pool slot, refresh it immediately
            slot_idx = self._post_to_slot.get(post_idx)
            if slot_idx is not None:
                self._assign_slot(post_idx, slot_idx)
            return

        # Fallback: post was not pre-registered (e.g. skeleton was skipped)
        self.prepare_skeletons([post])
        post_idx = self._post_id_to_idx.get(post_id)
        if post_idx is not None:
            self._post_bytes[post_idx] = safe_bytes
        self._update_viewport()

    def clear(self):
        """Release all pool slots and clear post data. Pool widgets stay alive.

        Keeping the pool alive avoids the allocation cost on the next search.
        All post data, rects, bytes, and bookmark states are wiped.
        """
        # Release all active slots back to the free list
        for slot_idx in list(self._slot_to_post.keys()):
            self._release_slot(slot_idx)

        # Clear all post data
        self._posts.clear()
        self._post_id_set.clear()
        self._post_id_to_idx.clear()
        self._rects.clear()
        self._post_bytes.clear()
        self._post_bookmarked.clear()
        self._post_animated.clear()
        self._y_index.clear()
        self.container.setMinimumHeight(0)

        # Release decoded QPixmap memory immediately
        self._px_cache.clear()

    def open_preview(self, post):
        self.main_app.open_preview(post)

    # ══════════════════════════════════════════════════════════════
    #  HELPERS
    # ══════════════════════════════════════════════════════════════

    def _on_btn_clicked(self, post, btn):
        import ui.animations as anims
        anims.animate_button_press(btn)
        self.open_preview(post)

    def _get_l1_pixmap(self, post_id, safe_bytes):
        """Return a decoded QPixmap from the LRU cache, decoding if necessary."""
        cached = self._px_cache.get(post_id)
        if cached is not None:
            return cached

        pixmap = QPixmap()
        pixmap.loadFromData(safe_bytes)
        max_w = max(400, settings.manager.thumbnail_size * 2)
        if pixmap.width() > max_w:
            pixmap = pixmap.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
        rounded = self._round_pixmap(pixmap)
        self._px_cache.put(post_id, rounded)
        return rounded

    def _decode_and_round(self, safe_bytes: bytes) -> QPixmap:
        """Decode JPEG bytes → scaled, rounded QPixmap for display."""
        pixmap = QPixmap()
        pixmap.loadFromData(safe_bytes)
        max_w = max(400, settings.manager.thumbnail_size * 2)
        if pixmap.width() > max_w:
            pixmap = pixmap.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
        return self._round_pixmap(pixmap)

    def _round_pixmap(self, pixmap, radius=12):
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

    def _style_star(self, star_btn, is_bookmarked, font_sz):
        color   = colors.FAVORITE if is_bookmarked else colors.TEXT_PRIMARY
        opacity = 0.7 if is_bookmarked else 0.4
        star_btn.setStyleSheet(f"""
            QPushButton {{
                color: {color};
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

    def _toggle_bookmark_direct(self, post, star_btn):
        pid = post.get("id")
        from ui.bookmarks_main.bookmarks_db import db
        is_now_bookmarked = not db.is_post_bookmarked(pid)
        if is_now_bookmarked:
            db.add_bookmark(post)
        else:
            db.remove_bookmark(pid)
        # Update cached state via O(1) index
        post_idx = self._post_id_to_idx.get(pid)
        if post_idx is not None:
            self._post_bookmarked[post_idx] = is_now_bookmarked
        self._style_star(star_btn, is_now_bookmarked, 16)
