from PyQt6.QtWidgets import QWidget, QScrollArea, QVBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSlot, pyqtSignal, QRect
from PyQt6.QtGui import QPixmap, QIcon, QPainter, QPainterPath

from ui import settings_view as settings
from collections import OrderedDict
from ui import colors

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                         CLASS: Gallery                              ║
# ╚══════════════════════════════════════════════════════════════════════╝
class Gallery(QWidget):
    load_more_requested = pyqtSignal()

    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self._items = []
        self._col_count = 4
        self._col_width = 250
        self._spacing = 16
        self._scroll_guard = False
        
        # Tiered Cache (L1 Memory): Fixed number of decoded QPixmap objects
        self._l1_cache = OrderedDict()
        
        # Viewport Virtualization: Recycles image containers
        self._widget_pool = []
        
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._do_refresh)
        
        self.setup_ui()
        
        # Initialize pool
        for _ in range(150):
            btn = QPushButton(self.container)
            btn.setFlat(True)
            btn.setStyleSheet("border: none; background: transparent; padding: 0;")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
            star = QPushButton(btn)
            star.setText("★")
            star.setCursor(Qt.CursorShape.PointingHandCursor)
            star.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            
            self._widget_pool.append({'btn': btn, 'star': star, 'in_use': False, 'post_id': None})
            btn.hide()
            
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

    def _update_viewport(self):
        vp_y = self.scroll.verticalScrollBar().value()
        vp_h = self.scroll.viewport().height()
        # Render a bit outside the viewport to prevent flickering when scrolling fast
        visible_rect = QRect(0, vp_y - vp_h, self.scroll.viewport().width(), vp_h * 3)

        visible_items = [item for item in self._items if item['rect'].intersects(visible_rect)]
        visible_post_ids = {item['post'].get('id') for item in visible_items}

        # Release pool widgets that are no longer visible
        for pw in self._widget_pool:
            if pw['in_use'] and pw['post_id'] not in visible_post_ids:
                pw['in_use'] = False
                pw['btn'].hide()
                pw['post_id'] = None
                try: pw['btn'].clicked.disconnect() 
                except: pass
                try: pw['star'].clicked.disconnect()
                except: pass

        # Assign pool widgets to newly visible items
        for item in visible_items:
            post_id = item['post'].get('id')
            pw = next((w for w in self._widget_pool if w['in_use'] and w['post_id'] == post_id), None)
            
            if not pw:
                pw = next((w for w in self._widget_pool if not w['in_use']), None)
                if not pw:
                    continue # Pool exhausted (highly unlikely with 150 widgets)
                
                pw['in_use'] = True
                pw['post_id'] = post_id
                
                post = item['post']
                rect = item['rect']
                
                if item.get('safe_bytes'):
                    pixmap = self._get_l1_pixmap(post_id, item['safe_bytes'])
                    pw['btn'].setIcon(QIcon(pixmap))
                    pw['btn'].setStyleSheet("border: none; background: transparent; padding: 0;")
                else:
                    pw['btn'].setIcon(QIcon())
                    pw['btn'].setStyleSheet(f"border: none; background-color: {colors.BUTTON_BG}; border-radius: 12px; padding: 0;")
                
                pw['btn'].setIconSize(rect.size())
                pw['btn'].setGeometry(rect)
                
                star_sz = max(24, rect.width() // 8)
                pw['star'].setFixedSize(star_sz, star_sz)
                pw['star'].move(rect.width() - star_sz - 8, 8)
                is_bm = settings.manager.is_post_bookmarked(post_id)
                self._style_star(pw['star'], is_bm, 16)
                
                pw['btn'].clicked.connect(lambda checked, p=post, b=pw['btn']: self._on_btn_clicked(p, b))
                pw['star'].clicked.connect(lambda checked, p=post, s=pw['star']: self._toggle_bookmark_direct(p, s))
                
                if item.get('safe_bytes') and not item.get('animated'):
                    import ui.animations as anims
                    anims.animate_fade_in(pw['btn'], duration=500)
                    item['animated'] = True
                    
                pw['btn'].show()
            else:
                rect = item['rect']
                pw['btn'].setGeometry(rect)
                pw['btn'].setIconSize(rect.size())
                
                if item.get('safe_bytes'):
                    pixmap = self._get_l1_pixmap(post_id, item['safe_bytes'])
                    pw['btn'].setIcon(QIcon(pixmap))
                    pw['btn'].setStyleSheet("border: none; background: transparent; padding: 0;")
                    if not item.get('animated'):
                        import ui.animations as anims
                        anims.animate_fade_in(pw['btn'], duration=500)
                        item['animated'] = True
                else:
                    pw['btn'].setIcon(QIcon())
                    pw['btn'].setStyleSheet(f"border: none; background-color: {colors.BUTTON_BG}; border-radius: 12px; padding: 0;")
                    
                star_sz = max(24, rect.width() // 8)
                pw['star'].setFixedSize(star_sz, star_sz)
                pw['star'].move(rect.width() - star_sz - 8, 8)

    def _on_btn_clicked(self, post, btn):
        import ui.animations as anims
        anims.animate_button_press(btn)
        self.open_preview(post)

    def _get_l1_pixmap(self, post_id, safe_bytes):
        if post_id in self._l1_cache:
            self._l1_cache.move_to_end(post_id)
            return self._l1_cache[post_id]
            
        pixmap = QPixmap()
        pixmap.loadFromData(safe_bytes)
        max_w = max(400, settings.manager.thumbnail_size * 2)
        if pixmap.width() > max_w:
            pixmap = pixmap.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
        rounded = self._round_pixmap(pixmap)
        
        self._l1_cache[post_id] = rounded
        if len(self._l1_cache) > 500:
            self._l1_cache.popitem(last=False)
            
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
        """Prepare skeletal boxes for posts while images are downloading."""
        for post in posts:
            # Skip if we already have this post
            if any(item['post'].get('id') == post.get('id') for item in self._items):
                continue
                
            w = post.get('image_width', 0)
            h = post.get('image_height', 0)
            aspect = (h / w) if w else 1.0
            
            self._items.append({
                'post': post,
                'aspect': aspect,
                'safe_bytes': None, # None means it's a skeleton
                'rect': QRect(),
                'animated': False
            })
        self._do_refresh()

    @pyqtSlot(bytes, dict, int)
    def add_item(self, safe_bytes: bytes, post: dict, idx: int):
        post_id = post.get("id")
        
        pixmap = QPixmap()
        pixmap.loadFromData(safe_bytes)
        
        max_w = max(400, settings.manager.thumbnail_size * 2)
        if pixmap.width() > max_w:
            pixmap = pixmap.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
        rounded_pixmap = self._round_pixmap(pixmap)
        
        self._l1_cache[post_id] = rounded_pixmap
        if len(self._l1_cache) > 500:
            self._l1_cache.popitem(last=False)

        # Find the skeleton and fill it
        found = False
        for item in self._items:
            if item['post'].get('id') == post_id:
                item['safe_bytes'] = safe_bytes
                found = True
                break
                
        if not found:
            # Fallback if skeleton wasn't prepared
            orig_w = pixmap.width()
            orig_h = pixmap.height()
            aspect = orig_h / orig_w if orig_w > 0 else 1.0
            self._items.append({
                'post': post,
                'aspect': aspect,
                'safe_bytes': safe_bytes,
                'rect': QRect(),
                'animated': False
            })
            if len(self._items) % 5 == 0:
                self._do_refresh()
            else:
                self.refresh_layout()
        else:
            # Since the skeleton is filled, we just need to update the viewport so it redraws
            self._update_viewport()

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
        self._items.clear()
        self.container.setMinimumHeight(0)
        for pw in self._widget_pool:
            if pw['in_use']:
                pw['in_use'] = False
                pw['btn'].hide()
                pw['post_id'] = None
                try: pw['btn'].clicked.disconnect() 
                except: pass
                try: pw['star'].clicked.disconnect()
                except: pass

    def open_preview(self, post):
        self.main_app.open_preview(post)
