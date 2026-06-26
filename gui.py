"""
gui.py — BooruBrowser main window.

Responsibilities (and ONLY these):
  - Build the widget tree (sidebar, gallery, tag panel, overlay, stack)
  - Wire component signals together
  - Own application-level state (current page, bookmarks mode)
  - Thin slot methods that delegate to the controller or navigation manager

Everything else has been extracted:
  - Page routing             → ui/navigation.py
  - Keyboard shortcuts       → ui/hotkeys.py
  - Dark title bar           → ui/windows_utils.py
  - Booru removal            → boorus/__init__.py
  - Download overlay anchor  → ui/download_window.py (DownloadWindow.reposition)
"""

import logging
import os
import ctypes
import shutil

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLineEdit, QPushButton, QStackedWidget,
)
from PyQt6.QtCore import Qt, QPoint, QSettings
from PyQt6.QtGui import QFont, QColor, QIcon

from ui import colors
from ui import settings_view as settings
import boorus
import boorus as boorus_mod
from download_images import BooruDownloader
from controller import AppController
from displayers.overlay import MediaOverlay
from ui.sidebar import Sidebar
from ui.gallery import Gallery
from ui.tag_panel import TagPanel
from ui.search_bar import BooruSearchBar
from ui.server_bar import ServerBar
from ui.blacklist_view import BlacklistView
from ui.favorites_view import FavoritesView
from ui.download_window import DownloadWindow
from ui.downloads_view import DownloadsView
from ui.settings_view import SettingsView
from ui.cheat_sheet import CheatSheetView
from ui.navigation import NavigationManager
from ui.hotkeys import HotkeyManager
from ui.windows_utils import apply_dark_title_bar
from ui.bookmarks_main.bookmarks_db import db
from ui.browser_dialog import CloudflareBrowserDialog
from ui.modals import AddBooruDialog, BulkDownloadDialog
from cloudflare_bypasser import store as cf_store
from validation import validate_search_term
try:
    from displayers.legacy_window import UniversalViewer
except ImportError:
    UniversalViewer = None  # type: ignore


log = logging.getLogger(__name__)


class BooruGui(QMainWindow):
    """Thin main window — assembles components and routes signals."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Booru Browser v{settings.VERSION}")

        self.resize(1400, 900)

        # App icon
        icon_path = os.path.join(os.path.dirname(__file__), "appico.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        apply_dark_title_bar(int(self.winId()))

        # Window geometry persistence
        self.qsettings = QSettings("BooruBrowser", "BooruBrowser")
        if self.qsettings.value("geometry"):
            self.restoreGeometry(self.qsettings.value("geometry"))
        if self.qsettings.value("windowState"):
            self.restoreState(self.qsettings.value("windowState"))

        # ── Core components ──────────────────────────────────────
        self.downloader = BooruDownloader()
        self.controller = AppController(self.downloader)

        # ── Application state ────────────────────────────────────
        self.current_page = 1
        self.is_bookmarks_mode = False
        self.bookmark_filter = None

        # ── Build UI ─────────────────────────────────────────────
        self._build_ui()

        # ── Wire controller signals ──────────────────────────────
        self.controller.status_updated.connect(self._on_status_updated)
        self.controller.loading_started.connect(self._on_loading_started)
        self.controller.loading_finished.connect(self._on_loading_finished)
        self.controller.preview_ready.connect(self.gallery.add_item)
        self.controller.posts_fetched.connect(self._on_posts_fetched)
        self.controller.cf_blocked.connect(self._on_cf_blocked)

        # ── Wire gallery → infinite scroll ───────────────────────
        self.gallery.load_more_requested.connect(self._load_more)
        self.gallery.bookmark_toggled.connect(self._on_bookmark_toggled)

        # ── Download overlay ─────────────────────────────────────
        self.download_overlay = DownloadWindow(self.centralWidget())
        self.download_overlay.hide()
        self.downloader.download_started.connect(self.download_overlay.add_download)
        self.downloader.download_progress.connect(self.download_overlay.update_download)
        self.downloader.download_finished.connect(self.download_overlay.remove_download)
        self.downloader.download_failed.connect(self._on_download_failed_overlay)

        # ── Finalise ─────────────────────────────────────────────
        self.server_bar.rebuild_list()
        self.trigger_fetch(new=True)

    # ══════════════════════════════════════════════════════════════
    #  UI Construction
    # ══════════════════════════════════════════════════════════════

    def _build_ui(self):
        root = QWidget()
        root.setStyleSheet(f"background-color: {colors.MAIN_BG};")
        self.setCentralWidget(root)

        main_h = QHBoxLayout(root)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        # 1. Server Bar (far left)
        self.server_bar = ServerBar(self)
        main_h.addWidget(self.server_bar)

        # 2. Sidebar
        self.sidebar = Sidebar(self)
        main_h.addWidget(self.sidebar)

        # 3. Main content area
        content_v = QVBoxLayout()
        content_v.setContentsMargins(0, 0, 0, 0)
        content_v.setSpacing(0)
        main_h.addLayout(content_v, 1)

        #   3a. Top bar (search)
        self.topbar = QWidget()
        self.topbar.setFixedHeight(64)
        self.topbar.setStyleSheet("background-color: transparent;")
        top_h = QHBoxLayout(self.topbar)
        top_h.setContentsMargins(24, 16, 24, 0)
        top_h.setSpacing(12)

        self.search_bar = BooruSearchBar(self)
        self.search_bar.searchTriggered.connect(lambda: self.trigger_fetch(new=True))
        top_h.addWidget(self.search_bar, 1)

        self.bulk_dl_btn = QPushButton("Bulk Download")
        self.bulk_dl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bulk_dl_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {colors.TEXT_PRIMARY};
                border: 1px solid {colors.BORDER};
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {colors.BUTTON_BG}; }}
        """)
        self.bulk_dl_btn.clicked.connect(self._on_bulk_dl)
        top_h.addWidget(self.bulk_dl_btn)

        content_v.addWidget(self.topbar)

        #   3b. Stacked pages
        self.stack = QStackedWidget()

        self.gallery_page = QWidget()
        gallery_layout = QHBoxLayout(self.gallery_page)
        gallery_layout.setContentsMargins(0, 0, 0, 0)
        gallery_layout.setSpacing(0)

        self.gallery = Gallery(self)
        gallery_layout.addWidget(self.gallery, 1)

        self.tag_panel = TagPanel(self)
        gallery_layout.addWidget(self.tag_panel)

        self.stack.addWidget(self.gallery_page)       # 0
        self.blacklist_view = BlacklistView(self)
        self.stack.addWidget(self.blacklist_view)      # 1
        self.favorites_view = FavoritesView(self)
        self.stack.addWidget(self.favorites_view)      # 2
        self.settings_view = SettingsView(self)
        self.stack.addWidget(self.settings_view)       # 3
        self.downloads_view = DownloadsView(self)
        self.stack.addWidget(self.downloads_view)      # 4
        self.cheat_sheet_view = CheatSheetView(self)
        self.stack.addWidget(self.cheat_sheet_view)    # 5

        content_v.addWidget(self.stack, 1)

        # 4. Media overlay (top-level, above stack)
        self.overlay = MediaOverlay(self)

        # 5. Navigation manager (page routing)
        self.nav = NavigationManager(self.stack, self.overlay, self.topbar, self)

        # 6. Hotkeys
        self._hotkeys = HotkeyManager(self)
        self._hotkeys.register("Ctrl+F", self.search_bar.entry.setFocus)
        self._hotkeys.register("Right", lambda: self.change_page(1))
        self._hotkeys.register("Left", lambda: self.change_page(-1))
        self._hotkeys.register("Ctrl+S", self._on_bulk_dl)

    # ══════════════════════════════════════════════════════════════
    #  Page navigation (thin proxies to NavigationManager)
    # ══════════════════════════════════════════════════════════════

    def show_gallery(self):
        self.nav.go_gallery()

    def show_blacklist(self):
        self.blacklist_view.load_blacklist()
        self.nav.go_blacklist()

    def show_favorites(self):
        self.favorites_view.load_favorites()
        self.nav.go_favorites()

    def show_settings(self):
        self.settings_view.load_settings()
        self.nav.go_settings()

    def show_api_settings(self, name: str):
        self.nav.go_api_settings(name, self)

    def show_downloads(self):
        self.nav.go_downloads()

    def show_cheat_sheet(self):
        self.nav.go_cheat_sheet()

    # ══════════════════════════════════════════════════════════════
    #  Search / pagination
    # ══════════════════════════════════════════════════════════════

    def trigger_fetch(self, new: bool = False):
        if self.is_bookmarks_mode:
            db.load_bookmarks()
        tags = self.search_bar.text()
        try:
            tags = validate_search_term(tags)
        except Exception as e:
            self._on_status_updated(f"Invalid search terms: {e}", colors.DANGER)
            return
        if new:
            self.current_page = 1
        self._update_page_label()
        self.controller.trigger_fetch(
            tags, self.current_page, self.is_bookmarks_mode, self.bookmark_filter
        )

    def _load_more(self):
        if self.controller.is_loading:
            return
        tags = self.search_bar.text()
        try:
            tags = validate_search_term(tags)
        except Exception as e:
            self._on_status_updated(f"Invalid search terms: {e}", colors.DANGER)
            return
        self.current_page += 1
        self._update_page_label()
        self.controller.trigger_fetch_append(
            tags, self.current_page,
            self.is_bookmarks_mode, self.bookmark_filter
        )

    def change_page(self, delta: int):
        if self.controller.is_loading:
            return
        self.current_page = max(1, self.current_page + delta)
        self.trigger_fetch()

    def search_for_tag(self, tag: str):
        cur = self.search_bar.text()
        self.search_bar.setText(f"{cur} {tag}".strip())
        self.trigger_fetch(new=True)

    def toggle_bookmarks_mode(self):
        self.is_bookmarks_mode = not self.is_bookmarks_mode
        self.bookmark_filter = None
        if self.is_bookmarks_mode:
            self.search_bar.input.setPlaceholderText("Filter bookmarks by booru\u2026")
            self.tag_panel.set_results_count("Bookmarks")
        else:
            self.search_bar.input.setPlaceholderText("Search...")
            self.tag_panel.set_results_count("0 Results")
        self.server_bar.update_button_styles()
        self.show_gallery()
        self.trigger_fetch(new=True)

    def select_booru(self, name: str):
        if self.is_bookmarks_mode:
            self.is_bookmarks_mode = False
            self.sidebar.update_active_booru()
        settings.manager.active_booru = name
        settings.manager.save()
        self.server_bar.update_button_styles()
        self.sidebar.update_active_booru()
        self.show_gallery()
        self.trigger_fetch(new=True)

    def add_tag(self, tag: str):
        self.search_bar.add_tag_chip(tag)
        self.trigger_fetch(new=True)

    def _update_page_label(self):
        if settings.manager.infinite_scroll:
            self.sidebar.set_pagination_visible(False)
        else:
            self.sidebar.set_pagination_visible(True)
            self.sidebar.page_lbl.setText(f"Pg {self.current_page}")

    # ══════════════════════════════════════════════════════════════
    #  Booru management
    # ══════════════════════════════════════════════════════════════

    def remove_booru(self, name: str):
        # Remove from settings sidebar order
        if name in settings.manager.booru_order:
            settings.manager.booru_order.remove(name)
            settings.manager.save()

        # Delegate the file/registry cleanup
        fallback = boorus.remove_booru(name)

        # UI updates
        self.server_bar.rebuild_list()
        if settings.manager.active_booru == name:
            settings.manager.active_booru = fallback or "danbooru"
            settings.manager.save()
            self.server_bar.update_button_styles()
            self.sidebar.update_active_booru()
            self.trigger_fetch(new=True)

    # ══════════════════════════════════════════════════════════════
    #  Media
    # ══════════════════════════════════════════════════════════════

    def open_preview(self, post):
        self.tag_panel.update_tags(post)
        if settings.manager.use_legacy_viewer:
            try:
                UniversalViewer(self, post)
            except (NameError, TypeError):
                log.info("Legacy viewer not found, using overlay.")
                self.overlay.show_post(post)
        else:
            self.overlay.show_post(post)

    # ══════════════════════════════════════════════════════════════
    #  Controller signal slots
    # ══════════════════════════════════════════════════════════════

    def _on_status_updated(self, text: str, color: str):
        self.sidebar.status_lbl.setText(text)
        self.sidebar.status_lbl.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: bold;"
        )

    def _on_loading_started(self):
        self.gallery.clear()
        self.tag_panel.clear_tags()

    def _on_loading_finished(self):
        self.gallery.check_infinite_scroll_fill()

    def _on_posts_fetched(self, posts):
        self.tag_panel.set_results_count(f"{len(posts)} Results")
        if posts:
            self.gallery.prepare_skeletons(posts)

    def _on_cf_blocked(self, booru_name: str, error_msg: str):
        site = boorus_mod.REGISTRY.get(booru_name, {})
        url = site.get("url", "")
        if not url:
            return
        dlg = CloudflareBrowserDialog(url, booru_name, self)
        dlg.cookies_captured.connect(
            lambda cookies: self._on_cf_cookies_saved(booru_name)
        )
        dlg.exec()

    def _on_cf_cookies_saved(self, booru_name: str):
        self.server_bar.rebuild_list()
        self.trigger_fetch(new=True)

    def _on_bookmark_toggled(self, post: dict, is_now_bookmarked: bool):
        """Handle bookmark toggle — DB write + sidebar refresh."""
        pid = post.get("id")
        if is_now_bookmarked:
            db.add_bookmark(post)
        else:
            db.remove_bookmark(pid)
        if hasattr(self, "sidebar"):
            self.sidebar.refresh_bookmark_count()

    def _on_download_failed_overlay(self, task_id: str, error_msg: str):
        # Show failure briefly in the overlay, then remove
        if task_id in self.download_overlay.bars:
            bar = self.download_overlay.bars[task_id]
            bar.pct_lbl.setText("Failed")
            bar.pct_lbl.setStyleSheet(f"color: {colors.DANGER}; font-size: 11px;")
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(3000, lambda: self.download_overlay.remove_download(task_id))

    # ══════════════════════════════════════════════════════════════
    #  Window events
    # ══════════════════════════════════════════════════════════════

    def mousePressEvent(self, event):
        focused = self.focusWidget()
        if isinstance(focused, QLineEdit):
            focused.clearFocus()
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'overlay') and self.overlay.isVisible():
            self.overlay.setGeometry(self.stack.rect())
        if hasattr(self, 'download_overlay'):
            sidebar_w = self.sidebar.width() if self.sidebar.isVisible() else 0
            server_w = self.server_bar.width() if self.server_bar.isVisible() else 0
            self.download_overlay.reposition(sidebar_w, server_w)

    def closeEvent(self, event):
        self.qsettings.setValue("geometry", self.saveGeometry())
        self.qsettings.setValue("windowState", self.saveState())
        tmp = settings.manager.get_download_dir() / "temp_media"
        if tmp.exists():
            try:
                shutil.rmtree(tmp)
            except Exception:
                pass
        self.controller.shutdown()
        event.accept()

    # ══════════════════════════════════════════════════════════════
    #  Modal launchers
    # ══════════════════════════════════════════════════════════════

    def _on_add_booru(self):
        AddBooruDialog(self).exec()

    def _on_global_settings(self):
        self.show_settings()

    def _on_bulk_dl(self):
        current_tags = self.search_bar.text().strip()
        BulkDownloadDialog(self, current_tags).exec()
