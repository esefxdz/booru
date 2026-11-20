from PyQt6.QtWidgets import QPushButton
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QCursor, QIcon
from core import settings
from ui.style.icons import Icons
from ui.server_bar.favicon_fetcher import FaviconFetcher

from ui.style import colors
import ui.animations as anims
from cloudflare_bypasser import store as cf_store

class BooruButton(QPushButton):

    def __init__(self, booru_name, data, server_bar):
        super().__init__()
        self.booru_name = booru_name
        self.data = data
        self.server_bar = server_bar
        self.setFixedSize(48, 48)
        self.setIconSize(QSize(28, 28))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(data.get('url', booru_name))
        
        self.update_style()
        
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.server_bar._on_context_menu(self.booru_name)
        )
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self):
        anims.animate_button_press(self)
        self.server_bar.main_gui.select_booru(self.booru_name)

    def update_style(self):
        cached_icon = self.server_bar.icon_cache.get(self.booru_name)
        if cached_icon:
            self.setIcon(QIcon(cached_icon))
        else:
            if self.booru_name == settings.manager.active_booru:
                self.setIcon(Icons.get("box", colors.TEXT_PRIMARY))
            else:
                self.setIcon(Icons.get("box", colors.TEXT_SECONDARY))
            
            if self.booru_name not in self.server_bar.fetchers and self.data.get("url"):
                fetcher = FaviconFetcher(self.booru_name, self.data["url"])
                fetcher.finished.connect(self.server_bar._on_icon_ready)
                fetcher.finished.connect(fetcher.deleteLater)
                self.server_bar.fetchers[self.booru_name] = fetcher
                fetcher.start()

        is_active = (
            self.booru_name == settings.manager.active_booru
            and not self.server_bar.main_gui.is_bookmarks_mode
        )

        cf_ok = cf_store.has_active_bypass(self.booru_name)
        cf_color = colors.SUCCESS if cf_ok else colors.WARNING
        cf_border = f"border-bottom: 3px solid {cf_color};" if not is_active else ""

        if is_active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.ACCENT};
                    border-radius: 16px;
                    {cf_border}
                }}
            """)
        else:
            # Fully rounded by default, squarifies on hover — matches Discord behavior
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.MAIN_BG};
                    border-radius: 24px;
                    {cf_border}
                }}
                QPushButton:hover {{
                    background-color: {colors.ACCENT};
                    border-radius: 16px;
                }}
            """)
        self.setToolTip(
            f"{self.booru_name}\n"
            f"{'✓ Cloudflare bypass active' if cf_ok else '⚠ Cloudflare bypass needed — right-click to solve CAPTCHA'}"
        )
