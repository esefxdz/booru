import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QCursor

from ui import settings_view as settings
import boorus
from ui import colors
from ui.icons import Icons

class SidebarItem(QPushButton):
    def __init__(self, text, icon_name, is_active=False):
        super().__init__(text)
        self.icon_name = icon_name
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.set_active(is_active)

    def set_active(self, is_active):
        self.setProperty("active", is_active)
        self.style().unpolish(self)
        self.style().polish(self)
        
        color = colors.TEXT_PRIMARY if is_active else colors.TEXT_MUTED
        self.setIcon(Icons.get(self.icon_name, color))
        self.setIconSize(QSize(20, 20))

        if is_active:
            self.setStyleSheet(f"background-color: {colors.ACCENT}; color: {colors.TEXT_PRIMARY}; text-align: left; padding: 8px 12px; border-radius: 4px; font-weight: 600; font-size: 14px;")
        else:
            self.setStyleSheet(f"background-color: transparent; color: {colors.TEXT_MUTED}; text-align: left; padding: 8px 12px; border-radius: 4px; font-weight: 600; font-size: 14px;")

class Sidebar(QWidget):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setFixedWidth(240)
        self.setStyleSheet(f"background-color: {colors.PANEL_BG};")
        self._items = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(4)
        self.header_layout = QHBoxLayout()
        self.header_layout.setContentsMargins(4, 0, 4, 16)
        self.header_icon = QLabel()
        self.header_icon.setPixmap(Icons.get("box", colors.TEXT_SECONDARY, 24).pixmap(24, 24))
        self.header_label = QLabel()
        self.header_label.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: bold; font-size: 15px;")
        self.header_layout.addWidget(self.header_icon)
        self.header_layout.addWidget(self.header_label, 1)
        layout.addLayout(self.header_layout)
        self.btn_home = self._add_item("Home", "home", True)
        self.btn_home.clicked.connect(self.main_app.show_gallery)
        layout.addWidget(self._hline())
        self.btn_bookmarks = self._add_item("Your bookmarks", "bookmarks")
        self.btn_bookmarks.clicked.connect(self.main_app.toggle_bookmarks_mode)
        self.btn_blacklist = self._add_item("Your blacklist", "blacklist")
        self.btn_blacklist.clicked.connect(self.main_app.show_blacklist)
        self.btn_tags = self._add_item("Favorite tags", "tags")
        self.btn_tags.clicked.connect(self.main_app.show_favorites)
        self.btn_downloads = self._add_item("Downloads", "download")
        self.btn_downloads.clicked.connect(self.main_app.show_downloads)
        layout.addWidget(self._hline())
        self.btn_settings = self._add_item("Settings", "settings")
        self.btn_settings.clicked.connect(self.main_app.show_settings)
        
        self.btn_cheat = self._add_item("Cheat Sheet", "forum") # Or another icon like 'book' or 'help' if available, forum is close enough
        self.btn_cheat.clicked.connect(self.main_app.show_cheat_sheet)
        
        layout.addStretch(1)
        self.status_lbl = QLabel("")
        self._refresh_status()
        self.status_lbl.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 11px; font-weight: bold;")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_lbl)
        self.nav_widget = QWidget()
        nav = QHBoxLayout(self.nav_widget)
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(4)
        btn_prev = QPushButton("◀")
        btn_prev.setFixedSize(32, 28)
        btn_prev.setStyleSheet(f"background: {colors.INPUT_BG}; color: {colors.TEXT_PRIMARY}; border-radius: 4px;")
        btn_prev.clicked.connect(lambda: self.main_app.change_page(-1))
        nav.addWidget(btn_prev)
        self.page_lbl = QLabel("Pg 1")
        self.page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_lbl.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-weight: bold;")
        nav.addWidget(self.page_lbl)
        btn_next = QPushButton("▶")
        btn_next.setFixedSize(32, 28)
        btn_next.setStyleSheet(f"background: {colors.INPUT_BG}; color: {colors.TEXT_PRIMARY}; border-radius: 4px;")
        btn_next.clicked.connect(lambda: self.main_app.change_page(1))
        nav.addWidget(btn_next)
        layout.addWidget(self.nav_widget)
        layout.addStretch(1)

        self.update_active_booru()

    def _add_item(self, text, icon_name, is_active=False):
        btn = SidebarItem(text, icon_name, is_active)
        self.layout().addWidget(btn)
        self._items.append(btn)
        btn.clicked.connect(lambda checked, b=btn: self._set_active_item(b))
        return btn

    def _set_active_item(self, active_btn):
        for btn in self._items:
            btn.set_active(btn == active_btn)

    def _hline(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background-color: {colors.BORDER}; margin: 8px 0;")
        line.setFixedHeight(2)
        return line

    def set_pagination_visible(self, visible: bool):
        self.nav_widget.setVisible(visible)

    def update_active_booru(self):
        name = settings.manager.active_booru
        data = boorus.REGISTRY.get(name, {})
        display_name = data.get("url", name).replace("https://", "").replace("http://", "").strip("/")
        self.header_label.setText(display_name)
        from PyQt6.QtGui import QIcon
        if hasattr(self.main_app, 'server_bar') and name in self.main_app.server_bar.icon_cache:
            self.header_icon.setPixmap(QIcon(self.main_app.server_bar.icon_cache[name]).pixmap(24, 24))
        else:
            self.header_icon.setPixmap(Icons.get("box", colors.TEXT_SECONDARY, 24).pixmap(24, 24))
        self._set_active_item(self.btn_home)

    def _refresh_status(self):
        from ui.bookmarks_main.bookmarks_db import db
        count = len(db.get_all_bookmarks())
        self.status_lbl.setText(f"📌 {count} bookmarks" if count else "Ready")
        self.status_lbl.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 11px; font-weight: bold;")

    def refresh_bookmark_count(self):
        self._refresh_status()
