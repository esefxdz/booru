from PyQt6.QtWidgets import QWidget, QScrollArea, QVBoxLayout, QPushButton, QLabel
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
# ╚══════════════════════════════════════════════════════════════════════╝
class Gallery(QWidget):
    load_more_requested = pyqtSignal()

    # ── Virtualization tunables ────────────────────────────────
    # Items within BUFFER_ZONE of the viewport keep their bytes.
    # Items beyond EVICT_ZONE get their safe_bytes freed.
    _BUFFER_ZONE_PAGES = 2   # ±2 viewport heights: render zone
    _EVICT_ZONE_PAGES  = 4   # ±4 viewport heights: eviction threshold

    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self._items = []
        self._col_count = 4
        self._col_width = 250
        self._spacing = 16
        self._scroll_guard = False
        
        # QPixmap LRU — byte-bounded decoded pixmap cache
        self._px_cache = _PixmapLRU(_PX_CACHE_MAX_BYTES)

        # Y-sorted index for O(log n) viewport intersection.
        # Each entry is (y_top, item_index) sorted by y_top.
        self._y_index: list[tuple[int, int]] = []
        
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._do_refresh)

        # Eviction timer — runs periodically after scroll stops to
        # free safe_bytes from items that have scrolled far off-screen.
        self._evict_timer = QTimer(self)
        self._evict_timer.setSingleShot(True)
        self._evict_timer.setInterval(300)  # 300ms after last scroll
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
        self.scroll.setStyleSheet(f"QScrollArea {{ border: none; background-color: {colors.MAIN_BG}; }}")
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        self.container = QWidget()
        self.container.setStyleSheet("background-color: transparent;")
        self.container.setMinimumHeight(0)

        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll)

    def _on_scroll(self, value: int):
        self._update_viewport()

        # Schedule eviction check after scrolling settles
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
        if sb.maximum() <= 10 and len(self._items) > 0:
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
        if w < 100: w = self.width()

        target_sz = settings.manager.thumbnail_size
        if target_sz <= 0: target_sz = 250

        cols = max(1, w // target_sz)
        self._col_count = cols

        total_spacing = (cols + 1) * self._spacing
        self._col_width = (w - total_spacing) // cols
        if self._col_width < 50: self._col_width = 50

        self._recalculate_layout()
        self._rebuild_y_index()
        self._update_viewport()

    def _recalculate_layout(self):
        if settings.manager.masonry_mode:
            self._apply_masonry()
        else:
            self._apply_grid()

    def _apply_grid(self):
        sz = self._col_width
        for idx, item in enumerate(self._items):
            row = idx // self._col_count
            col = idx % self._col_count
            x = self._spacing + col * (sz + self._spacing)
            y = self._spacing + row * (sz + self._spacing)
            item['rect'] = QRect(x, y, sz, sz)

        rows = (len(self._items) + self._col_count - 1) // self._col_count
        max_h = rows * (sz + self._spacing) + self._spacing
        self.container.setMinimumHeight(max_h)

    def _apply_masonry(self):
        col_heights = [self._spacing] * self._col_count

        for item in self._items:
            min_col = 0
            min_h = col_heights[0]
            for i in range(1, self._col_count):
                if col_heights[i] < min_h:
                    min_h = col_heights[i]
                    min_col = i

            x = self._spacing + min_col * (self._col_width + self._spacing)
            y = min_h

            h = int(self._col_width * item['aspect'])
            item['rect'] = QRect(x, y, self._col_width, h)
            col_heights[min_col] += h + self._spacing

        max_h = max(col_heights) if col_heights else 0
        self.container.setMinimumHeight(max_h)

    # ══════════════════════════════════════════════════════════════
    #  Y-INDEX — O(log n) viewport intersection via binary search
    # ══════════════════════════════════════════════════════════════

    def _rebuild_y_index(self):
        """Rebuild the sorted Y-index from current item rects.

        Each entry is (y_top, item_index). Sorted by y_top so we
        can bisect to quickly find items that overlap the viewport.
        """
        self._y_index = sorted(
            (item['rect'].y(), idx)
            for idx, item in enumerate(self._items)
            if not item['rect'].isNull()
        )

    def _find_visible_indices(self, y_start: int, y_end: int) -> list[int]:
        """Return indices of items whose rects overlap [y_start, y_end].

        Uses binary search on _y_index for O(log n + k) where k is
        the number of visible items — much faster than scanning all
        items when the gallery has thousands of entries.
        """
        if not self._y_index:
            return []

        # We need items whose rect.bottom() >= y_start AND rect.y() <= y_end.
        # _y_index is sorted by y_top. An item at y_top is visible if
        # y_top + height >= y_start, i.e. y_top >= y_start - max_possible_height.
        # To be safe, we use a generous lower bound.
        max_item_height = self._col_width * 3  # masonry items rarely exceed 3:1
        search_start = y_start - max_item_height

        lo = bisect.bisect_left(self._y_index, (search_start,))
        
        result = []
        for i in range(lo, len(self._y_index)):
            y_top, idx = self._y_index[i]
            if y_top > y_end:
                break  # everything past here is below the viewport
            item = self._items[idx]
            rect = item['rect']
            if rect.y() + rect.height() >= y_start:
                result.append(idx)
        return result

    # ══════════════════════════════════════════════════════════════
    #  VIRTUALIZATION — evict bytes from far-off-screen items
    # ══════════════════════════════════════════════════════════════

    def _evict_offscreen_bytes(self):
        """Free safe_bytes from items that have scrolled far off-screen.

        Items beyond EVICT_ZONE viewports from the current scroll
        position get their raw JPEG bytes nulled out. They revert to
        skeleton state and will be reloaded from thumb_cache if the
        user scrolls back to them.

        This is the core fix for Tech Debt #1: without this, scrolling
        through 50 pages keeps 2500 items × ~50KB = 125 MB of raw
        JPEG bytes in Python memory forever.
        """
        vp_y = self.scroll.verticalScrollBar().value()
        vp_h = self.scroll.viewport().height()
        if vp_h <= 0:
            return

        evict_margin = vp_h * self._EVICT_ZONE_PAGES
        evict_top = vp_y - evict_margin
        evict_bottom = vp_y + vp_h + evict_margin

        evicted = 0
        for item in self._items:
            if item.get('safe_bytes') is None:
                continue  # already a skeleton
            rect = item['rect']
            if rect.isNull():
                continue
            # If this item is entirely outside the eviction zone, free it
            if rect.y() + rect.height() < evict_top or rect.y() > evict_bottom:
                item['safe_bytes'] = None
                item['animated'] = False  # re-animate when it comes back
                evicted += 1

        if evicted > 0:
            # Also trim the QPixmap LRU — the evicted items' decoded
            # pixmaps will be naturally pushed out as new ones enter.
            pass  # LRU handles its own eviction

    def _reload_from_cache(self, post_id):
        """Try to reload thumbnail bytes from thumb_cache for a previously evicted item.

        Returns the JPEG bytes if found, or None if the thumbnail isn't cached
        (should be rare — thumb_cache L2 persists to disk).
        """
        import thumb_cache
        return thumb_cache.get(post_id)

    def _update_viewport(self):
        vp_y = self.scroll.verticalScrollBar().value()
        vp_h = self.scroll.viewport().height()
        buffer_margin = vp_h * self._BUFFER_ZONE_PAGES
        vis_top = vp_y - buffer_margin
        vis_bottom = vp_y + vp_h + buffer_margin

        # Use Y-index for fast lookup if available, fallback to linear scan
        if self._y_index:
            visible_indices = set(self._find_visible_indices(vis_top, vis_bottom))
        else:
            visible_indices = {
                i for i, item in enumerate(self._items)
                if not item['rect'].isNull() and item['rect'].intersects(
                    QRect(0, int(vis_top), self.scroll.viewport().width(), int(vis_bottom - vis_top))
                )
            }

        for idx, item in enumerate(self._items):
            btn = item.get('btn')
            star = item.get('star')
            rect = item['rect']
            if btn is None or rect.isNull():
                continue

            if idx in visible_indices:
                # Position the permanent widget
                btn.setGeometry(rect)
                btn.setIconSize(rect.size())
                star_sz = max(24, rect.width() // 8)
                star.setFixedSize(star_sz, star_sz)
                star.move(rect.width() - star_sz - 8, 8)
                self._style_star(star, settings.manager.is_post_bookmarked(item['post'].get('id')), 16)

                # If evicted, try to reload from cache
                if item.get('safe_bytes') is None:
                    reloaded = self._reload_from_cache(item['post'].get('id'))
                    if reloaded is not None:
                        item['safe_bytes'] = reloaded

                # Resource virtualization: set or clear the pixmap
                if item.get('safe_bytes'):
                    pixmap = self._get_l1_pixmap(item['post'].get('id'), item['safe_bytes'])
                    btn.setIcon(QIcon(pixmap))
                    btn.setStyleSheet("border: none; background: transparent; padding: 0;")
                    if not item.get('animated'):
                        import ui.animations as anims
                        anims.animate_fade_in(btn, duration=500)
                        item['animated'] = True
                else:
                    btn.setIcon(QIcon())
                    btn.setStyleSheet(
                        f"border: none; background-color: {colors.BUTTON_BG}; "
                        f"border-radius: 12px; padding: 0;"
                    )
                btn.show()
            else:
                # Resource virtualization: clear pixmap to free VRAM, keep widget alive
                btn.setIcon(QIcon())
                btn.hide()

    def _on_btn_clicked(self, post, btn):
        import ui.animations as anims
        anims.animate_button_press(btn)
        self.open_preview(post)

    def _get_l1_pixmap(self, post_id, safe_bytes):
        # Try the decoded pixmap cache first (instant, no decode cost)
        cached = self._px_cache.get(post_id)
        if cached is not None:
            return cached

        # Decode JPEG bytes → QPixmap, scale down, round corners
        pixmap = QPixmap()
        pixmap.loadFromData(safe_bytes)
        max_w = max(400, settings.manager.thumbnail_size * 2)
        if pixmap.width() > max_w:
            pixmap = pixmap.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
        rounded = self._round_pixmap(pixmap)

        # Store in the byte-bounded LRU
        self._px_cache.put(post_id, rounded)
        return rounded

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

    def prepare_skeletons(self, posts):
        """Create permanent widgets for posts while images are downloading.

        Each post gets its own QPushButton + star button, created once and
        never recycled.  Signals are connected here and never disconnected.
        This is Resource Virtualization — the widgets are permanent, only
        the QPixmap content is virtualized on scroll.
        """
        for post in posts:
            post_id = post.get('id')
            if any(item['post'].get('id') == post_id for item in self._items):
                continue

            w = post.get('image_width', 0)
            h = post.get('image_height', 0)
            aspect = (h / w) if w else 1.0

            # Create permanent button — never recycled
            btn = QPushButton(self.container)
            btn.setFlat(True)
            btn.setStyleSheet(
                f"border: none; background-color: {colors.BUTTON_BG}; "
                f"border-radius: 12px; padding: 0;"
            )
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.hide()

            star = QPushButton(btn)
            star.setText("★")
            star.setCursor(Qt.CursorShape.PointingHandCursor)
            star.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

            # Signals connected ONCE — never disconnected or recycled
            btn.clicked.connect(lambda checked, p=post, b=btn: self._on_btn_clicked(p, b))
            star.clicked.connect(lambda checked, p=post, s=star: self._toggle_bookmark_direct(p, s))

            self._items.append({
                'post': post,
                'aspect': aspect,
                'safe_bytes': None,
                'rect': QRect(),
                'animated': False,
                'btn': btn,
                'star': star,
            })
        self._do_refresh()

    @pyqtSlot(bytes, dict, int)
    def add_item(self, safe_bytes: bytes, post: dict, idx: int):
        post_id = post.get("id")

        # Pre-decode and cache the pixmap
        self._px_cache.put(post_id, self._decode_and_round(safe_bytes))

        # Find the skeleton and fill it with image data
        for item in self._items:
            if item['post'].get('id') == post_id:
                item['safe_bytes'] = safe_bytes
                self._update_viewport()
                return

        # Fallback: skeleton wasn't prepared — create the widget now
        self.prepare_skeletons([post])
        for item in self._items:
            if item['post'].get('id') == post_id:
                item['safe_bytes'] = safe_bytes
                break
        self._update_viewport()

    def _decode_and_round(self, safe_bytes: bytes) -> QPixmap:
        """Decode JPEG bytes → scaled, rounded QPixmap for display."""
        pixmap = QPixmap()
        pixmap.loadFromData(safe_bytes)
        max_w = max(400, settings.manager.thumbnail_size * 2)
        if pixmap.width() > max_w:
            pixmap = pixmap.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
        return self._round_pixmap(pixmap)

    def _style_star(self, star_btn, is_bookmarked, font_sz):
        color = colors.FAVORITE if is_bookmarked else colors.TEXT_PRIMARY
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
        if settings.manager.is_post_bookmarked(pid):
            settings.manager.remove_bookmark(pid)
            self._style_star(star_btn, False, 16)
        else:
            settings.manager.add_bookmark(post)
            self._style_star(star_btn, True, 16)

    def clear(self):
        # Destroy all permanent widgets
        for item in self._items:
            btn = item.get('btn')
            if btn:
                btn.hide()
                btn.deleteLater()
        self._items.clear()
        self._y_index.clear()
        self.container.setMinimumHeight(0)

        # Release all decoded QPixmaps immediately (no lingering memory)
        self._px_cache.clear()

    def open_preview(self, post):
        self.main_app.open_preview(post)
