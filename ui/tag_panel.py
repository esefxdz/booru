from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QLabel, QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSlot, QSize


# ╔══════════════════════════════════════════════════════════════════════╗
# ║                         CLASS: TagPanel                             ║
# ╚══════════════════════════════════════════════════════════════════════╝
from ui import colors

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                         CLASS: TagPanel                             ║
# ╚══════════════════════════════════════════════════════════════════════╝
class TagPanel(QWidget):
    """Right panel: static tag display area."""

    WIDTH = 240

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__                                                        │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setFixedWidth(self.WIDTH)
        self.setStyleSheet(f"background-color: {colors.PANEL_BG};")
        self._build()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _build                                                          │
    # └──────────────────────────────────────────────────────────────────┘
    def _build(self):
        self._main_layout = QHBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        # Vertical divider
        self.divider = QFrame()
        self.divider.setFrameShape(QFrame.Shape.VLine)
        self.divider.setFixedWidth(1)
        self.divider.setStyleSheet(f"background-color: {colors.DIVIDER}; border: none;")
        self._main_layout.addWidget(self.divider)

        # Content widget
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet(f"background-color: {colors.PANEL_BG};")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 15, 10, 10)
        self.content_layout.setSpacing(0)

        # Results Header (Top of TagPanel)
        res_h = QHBoxLayout()
        res_h.setContentsMargins(0, 0, 0, 10)
        
        self.results_count_lbl = QLabel("0 Results")
        self.results_count_lbl.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-size: 16px; font-weight: 800;")
        res_h.addWidget(self.results_count_lbl)
        
        self.refresh_btn = QPushButton()
        from ui.icons import Icons
        self.refresh_btn.setIcon(Icons.get("refresh", colors.TEXT_MUTED))
        self.refresh_btn.setIconSize(QSize(18, 18))
        self.refresh_btn.setFixedSize(30, 30)
        self.refresh_btn.setStyleSheet("background: transparent; border: none;")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(lambda: self.main_app.trigger_fetch(new=True))
        res_h.addWidget(self.refresh_btn)
        
        self.content_layout.addLayout(res_h)

        lbl = QLabel("POST TAGS")
        lbl.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 11px; font-weight: bold;")
        self.content_layout.addWidget(lbl)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("background-color: transparent;")

        self.container = QWidget()
        self.container.setStyleSheet("background-color: transparent;")
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.container_layout.setContentsMargins(0, 5, 0, 0)
        self.container_layout.setSpacing(2)
        self.scroll.setWidget(self.container)
        self.content_layout.addWidget(self.scroll)

        self._main_layout.addWidget(self.content_widget)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  set_results_count                                               │
    # └──────────────────────────────────────────────────────────────────┘
    def set_results_count(self, text):
        self.results_count_lbl.setText(text)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  clear_tags                                                      │
    # └──────────────────────────────────────────────────────────────────┘
    def clear_tags(self):
        while self.container_layout.count():
            child = self.container_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  update_tags                                                     │
    # └──────────────────────────────────────────────────────────────────┘
    def update_tags(self, post):
        self.clear_tags()
        
        raw_score = post.get("score")
        if isinstance(raw_score, dict):
            self.current_score = str(raw_score.get("total", raw_score.get("up", "")))
        elif raw_score is not None:
            self.current_score = str(raw_score)
        else:
            self.current_score = ""

        cats = self.main_app.downloader._adapter().get_categorized_tags(post)

        total_tags = sum(len(v) for v in cats.values())
        is_flat = total_tags > 0 and len(cats["general"]) == total_tags

        if is_flat:
            self._render_tags(cats)
            import asyncio, threading

            def fetch_and_render():
                from tag_categorizer import categorizer
                loop = asyncio.new_event_loop()
                new_cats = loop.run_until_complete(
                    categorizer.categorize_tags(cats["general"])
                )
                from PyQt6.QtCore import QMetaObject, Q_ARG
                QMetaObject.invokeMethod(
                    self, "_render_tags_safe",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(dict, new_cats),
                )
                loop.close()

            threading.Thread(target=fetch_and_render, daemon=True).start()
        else:
            self._render_tags(cats)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _render_tags_safe  (thread-safe slot)                           │
    # └──────────────────────────────────────────────────────────────────┘
    @pyqtSlot(dict)
    def _render_tags_safe(self, cats):
        self._render_tags(cats)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _render_tags                                                    │
    # └──────────────────────────────────────────────────────────────────┘
    def _render_tags(self, cats):
        self.clear_tags()
        
        if getattr(self, "current_score", ""):
            score_lbl = QLabel(f"SCORE — {self.current_score}")
            score_lbl.setStyleSheet(
                f"color: {colors.TEXT_MUTED}; font-size: 11px; font-weight: bold; margin-top: 10px;"
            )
            self.container_layout.addWidget(score_lbl)

        cat_colors = {
            "artist":    colors.TAG_ARTIST,
            "character": colors.TAG_CHARACTER,
            "copyright": colors.TAG_COPYRIGHT,
            "meta":      colors.TAG_METADATA,
            "general":   colors.TAG_GENERAL,
        }
        labels = {
            "artist":    "ARTIST",
            "character": "CHARACTER",
            "copyright": "COPYRIGHT",
            "meta":      "METADATA",
            "general":   "GENERAL",
        }
        for cat in ("artist", "character", "copyright", "meta", "general"):
            tags = sorted(cats.get(cat, []))
            if not tags:
                continue

            lbl = QLabel(f"{labels[cat]} — {len(tags)}")
            lbl.setStyleSheet(
                f"color: {colors.TEXT_MUTED}; font-size: 11px; font-weight: bold; margin-top: 10px;"
            )
            self.container_layout.addWidget(lbl)

            for t in tags:
                if not t:
                    continue
                btn = QPushButton(f"  {t}")
                btn.setStyleSheet(f"""
                    QPushButton {{
                        color: {cat_colors[cat]};
                        text-align: left;
                        background: transparent;
                        border: none;
                        padding: 4px;
                        border-radius: 4px;
                        font-size: 13px;
                    }}
                    QPushButton:hover {{
                        background: {colors.DIVIDER};
                    }}
                """)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda checked, x=t: self.main_app.add_tag(x))
                self.container_layout.addWidget(btn)
