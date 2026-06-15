import logging
import os
import ctypes
from ui import colors
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLineEdit, QPushButton, QFrame, QListWidget, QListWidgetItem, QLabel,
    QStackedWidget,
)
from PyQt6.QtCore import Qt, QSize, QTimer, QThread, pyqtSlot, pyqtSignal, QPoint
from PyQt6.QtGui import QFont, QColor, QIcon

from ui import settings_view as settings
import boorus
from download_images import BooruDownloader
from controller import AppController
from displayers.overlay import MediaOverlay
from ui.sidebar import Sidebar
from ui.gallery import Gallery
from ui.tag_panel import TagPanel
from ui.search_bar import BooruSearchBar
from ui.server_bar import ServerBar
from ui.icons import Icons
from ui.blacklist_view import BlacklistView
from ui.favorites_view import FavoritesView
from ui.settings_view import SettingsView
from ui.cheat_sheet import CheatSheetView
from validation import validate_search_term





class BooruGui(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Booru Browser v{settings.VERSION}")

        self.resize(1400, 900)
        
        # Set App Icon
        icon_path = os.path.join(os.path.dirname(__file__), "appico.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        # Apply Windows Dark Title Bar
        self._apply_dark_title_bar()

        self.downloader = BooruDownloader()
        self.controller = AppController(self.downloader)

        self.current_page = 1
        self.is_bookmarks_mode = False
        self.bookmark_filter = None

        self._build_ui()

        self.controller.status_updated.connect(self._on_status_updated)
        self.controller.loading_started.connect(self._on_loading_started)
        self.controller.loading_finished.connect(self._on_loading_finished)
        self.controller.preview_ready.connect(self.gallery.add_item)
        self.controller.posts_fetched.connect(self._on_posts_fetched)
        self.controller.cf_blocked.connect(self._on_cf_blocked)
        self.gallery.load_more_requested.connect(self._load_more)

        # ── Floating download progress overlay (bottom-right corner) ──
        from ui.download_window import DownloadWindow
        self.download_overlay = DownloadWindow(self.centralWidget())
        self.download_overlay.hide()
        self._reposition_download_overlay()

        self.downloader.download_started.connect(self.download_overlay.add_download)
        self.downloader.download_progress.connect(self.download_overlay.update_download)
        self.downloader.download_finished.connect(self.download_overlay.remove_download)
        self.downloader.download_failed.connect(self._on_download_failed_overlay)

        self.server_bar.rebuild_list()
        self.trigger_fetch(new=True)

    def open_preview(self, post):
        self.tag_panel.update_tags(post)
        if settings.manager.use_legacy_viewer:
            try:
                from displayers.legacy_window import UniversalViewer
                UniversalViewer(self, post)
            except ImportError:
                logging.info("Legacy viewer not found, using overlay.")
                self.overlay.show_post(post)
        else:
            self.overlay.show_post(post)

    # ─────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QWidget()
        root.setStyleSheet(f"background-color: {colors.MAIN_BG};")
        self.setCentralWidget(root)

        main_h = QHBoxLayout(root)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        # 1. Server Bar (Far Left)
        self.server_bar = ServerBar(self)
        main_h.addWidget(self.server_bar)

        # 2. Sidebar (Middle Left)
        self.sidebar = Sidebar(self)
        main_h.addWidget(self.sidebar)

        # 3. Main Content (Right)
        content_v = QVBoxLayout()
        content_v.setContentsMargins(0, 0, 0, 0)
        content_v.setSpacing(0)
        main_h.addLayout(content_v, 1)

        #   3a. Top Bar (Search)
        self.topbar = QWidget()
        self.topbar.setFixedHeight(64)
        self.topbar.setStyleSheet("background-color: transparent;")
        top_h = QHBoxLayout(self.topbar)
        top_h.setContentsMargins(24, 16, 24, 0)
        top_h.setSpacing(12)

        search_wrap = QWidget()
        search_wrap.setStyleSheet("background: transparent;")
        search_v = QVBoxLayout(search_wrap)
        search_v.setContentsMargins(0, 0, 0, 0)
        search_v.setSpacing(0)

        self.search_bar = BooruSearchBar(self)
        self.search_bar.searchTriggered.connect(lambda: self.trigger_fetch(new=True))
        search_v.addWidget(self.search_bar)
        top_h.addWidget(search_wrap, 1)

        content_v.addWidget(self.topbar)

        #   3c. Main Stack (Gallery vs Blacklist vs etc)
        self.stack = QStackedWidget()
        
        # Gallery Page
        self.gallery_page = QWidget()
        gallery_layout = QHBoxLayout(self.gallery_page)
        gallery_layout.setContentsMargins(0, 0, 0, 0)
        gallery_layout.setSpacing(0)
        
        self.gallery = Gallery(self)
        gallery_layout.addWidget(self.gallery, 1)
        
        self.tag_panel = TagPanel(self)
        gallery_layout.addWidget(self.tag_panel)
        
        self.stack.addWidget(self.gallery_page)
        
        # Blacklist Page
        self.blacklist_view = BlacklistView(self)
        self.stack.addWidget(self.blacklist_view)
        
        # Favorites Page
        self.favorites_view = FavoritesView(self)
        self.stack.addWidget(self.favorites_view)
        
        # Settings Page
        self.settings_view = SettingsView(self)
        self.stack.addWidget(self.settings_view)
        
        # Downloads Page
        from ui.downloads_view import DownloadsView
        self.downloads_view = DownloadsView(self)
        self.stack.addWidget(self.downloads_view)

        # Cheat Sheet Page
        self.cheat_sheet_view = CheatSheetView(self)
        self.stack.addWidget(self.cheat_sheet_view)
        
        content_v.addWidget(self.stack, 1)

        # 4. Media Overlay (Top level)
        self.overlay = MediaOverlay(self)

        # 4.3 Full Keyboard Accessibility - Global Hotkeys
        self._setup_hotkeys()

    def _setup_hotkeys(self):
        from PyQt6.QtGui import QKeySequence, QShortcut

        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self.search_bar.entry.setFocus)
        QShortcut(QKeySequence("Right"), self).activated.connect(lambda: self.change_page(1))
        QShortcut(QKeySequence("Left"), self).activated.connect(lambda: self.change_page(-1))
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._on_bulk_dl)

    # ─────────────────────────────────────────────────────────
    # Public helpers
    # ─────────────────────────────────────────────────────────
    def mousePressEvent(self, event):
        # Clear focus when clicking empty space
        focused = self.focusWidget()
        if isinstance(focused, QLineEdit):
            focused.clearFocus()
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'overlay') and self.overlay.isVisible():
            self.overlay.setGeometry(self.stack.rect())
        if hasattr(self, 'download_overlay'):
            self._reposition_download_overlay()

    def _reposition_download_overlay(self):
        """Keep the floating download widget anchored to the bottom-right."""
        overlay = self.download_overlay
        margin = 16
        w = overlay.width() or 232
        h = overlay.height() or overlay.sizeHint().height()
        x = self.width() - w - margin
        y = self.height() - h - margin
        overlay.move(x, y)
        overlay.raise_()

    def trigger_fetch(self, new: bool = False):
        if self.is_bookmarks_mode:
            from ui.bookmarks_main.bookmarks_db import db
            db.load_bookmarks()
        tags = self.search_bar.text()
        # Validate search terms
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
        """Called by gallery when user scrolls near bottom (infinite scroll)."""
        if self.controller.is_loading:
            return
        tags = self.search_bar.text()
        # Validate search terms
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

    def _update_page_label(self):
        if settings.manager.infinite_scroll:
            self.sidebar.set_pagination_visible(False)
        else:
            self.sidebar.set_pagination_visible(True)
            self.sidebar.page_lbl.setText(f"Pg {self.current_page}")

    def change_page(self, delta: int):
        # Prevent next page fetch while still fetching
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
        self.bookmark_filter = None # Bookmarks are universal
        
        if self.is_bookmarks_mode:
            self.search_bar.input.setPlaceholderText("Filter bookmarks by booru…")
            self.tag_panel.set_results_count("Bookmarks")
        else:
            self.search_bar.input.setPlaceholderText("Search...")
            self.tag_panel.set_results_count("0 Results")
            
        self.server_bar.update_button_styles() # Refresh to show/hide selection
        self.show_gallery()
        self.trigger_fetch(new=True)

    def select_booru(self, name: str):
        # If in bookmarks mode, exit it and go to the selected booru
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

    def show_gallery(self):
        self.stack.setCurrentIndex(0)
        self.topbar.show()

    def _close_overlay_if_open(self):
        """Dismiss the media overlay before switching to a full-screen page.

        The overlay is a plain child widget of self.stack that is manually
        raise_()-ed on top.  Switching the QStackedWidget page does NOT hide
        it automatically, which causes it to float on top of whatever page
        just became active.  Calling close_overlay() before every page
        switch is the correct, surgical fix.
        """
        if hasattr(self, 'overlay') and self.overlay.isVisible():
            self.overlay.close_overlay()

    def show_blacklist(self):
        self._close_overlay_if_open()
        self.blacklist_view.load_blacklist()
        self.stack.setCurrentWidget(self.blacklist_view)
        # Hide search/header as they don't apply to blacklist editing
        self.topbar.hide()

    def show_favorites(self):
        self._close_overlay_if_open()
        self.favorites_view.load_favorites()
        self.stack.setCurrentWidget(self.favorites_view)
        self.topbar.hide()

    def show_settings(self):
        self._close_overlay_if_open()
        self.settings_view.load_settings()
        self.stack.setCurrentWidget(self.settings_view)
        self.topbar.hide()

    def show_downloads(self):
        self._close_overlay_if_open()
        self.stack.setCurrentWidget(self.downloads_view)
        self.topbar.hide()

    def show_cheat_sheet(self):
        self._close_overlay_if_open()
        self.stack.setCurrentWidget(self.cheat_sheet_view)
        self.topbar.hide()

    def remove_booru(self, name: str):
        import os
        # Remove from in-memory registry
        if name in boorus.REGISTRY:
            del boorus.REGISTRY[name]
        # Remove from sidebar order
        if name in settings.manager.booru_order:
            settings.manager.booru_order.remove(name)
            settings.manager.save()
        # Delete the .py file
        booru_file = settings.BASE_DIR / "boorus" / f"{name}.py"
        if os.path.exists(booru_file):
            try:
                os.remove(booru_file)
            except Exception as e:
                logging.error("[gui] Error deleting booru file: %s", e)
        # Invalidate any stale importlib cache + .pyc so a later re-add
        # with the same name picks up the fresh file.
        boorus.invalidate_cache(name)
        self.server_bar.rebuild_list()
        if settings.manager.active_booru == name:
            settings.manager.active_booru = (
                list(boorus.REGISTRY.keys())[0] if boorus.REGISTRY else "danbooru"
            )
            settings.manager.save()
            self.server_bar.update_button_styles()
            self.sidebar.update_active_booru()
            self.trigger_fetch(new=True)

    # ─────────────────────────────────────────────────────────
    # Slots
    # ─────────────────────────────────────────────────────────
    @pyqtSlot(str, str)
    def _on_status_updated(self, text: str, color: str):
        self.sidebar.status_lbl.setText(text)
        self.sidebar.status_lbl.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: bold;"
        )

    @pyqtSlot()
    def _on_loading_started(self):
        self.gallery.clear()
        self.tag_panel.clear_tags()

    @pyqtSlot()
    def _on_loading_finished(self):
        self.gallery.check_infinite_scroll_fill()

    @pyqtSlot(list)
    def _on_posts_fetched(self, posts):
        self.tag_panel.set_results_count(f"{len(posts)} Results")
        if posts:
            self.gallery.prepare_skeletons(posts)

    @pyqtSlot(str, str)
    def _on_cf_blocked(self, booru_name: str, error_msg: str):
        """Cloudflare blocked the current booru — offer to solve CAPTCHA."""
        from ui.browser_dialog import CloudflareBrowserDialog
        from cloudflare_bypasser import store as cf_store
        import boorus as boorus_mod

        # Get the booru URL from the registry so we open the right site
        site = boorus_mod.REGISTRY.get(booru_name, {})
        url = site.get("url", "")
        if not url:
            return

        # Open the embedded browser so the user can solve the CAPTCHA
        dlg = CloudflareBrowserDialog(url, booru_name, self)
        dlg.cookies_captured.connect(
            lambda cookies: self._on_cf_cookies_saved(booru_name)
        )
        dlg.exec()

        # After dialog closes (regardless of success), retry the fetch
        # so that if cookies were captured, the booru now works
        QTimer.singleShot(500, lambda: self.trigger_fetch(new=True))

    def _on_cf_cookies_saved(self, booru_name: str):
        """Called after cookies were captured and saved by the bypass dialog."""
        self.sidebar.status_lbl.setText(f"✅ {booru_name} bypass active — retrying…")
        self.sidebar.status_lbl.setStyleSheet("color: #4CAF50; font-size: 11px; font-weight: bold;")
        # Refresh the booru buttons so the tooltip shows "bypass active"
        self.server_bar.rebuild_list()

    # ─────────────────────────────────────────────────────────
    # Floating download overlay
    # ─────────────────────────────────────────────────────────
    def _on_download_failed_overlay(self, task_id, error):
        """Show a brief error in the download widget, then remove it."""
        dw = self.sidebar.download_window
        if task_id in dw.bars:
            bar = dw.bars[task_id]
            bar.pct_lbl.setText("Failed")
            bar.pct_lbl.setStyleSheet(f"color: {colors.DANGER}; font-size: 11px;")
            QTimer.singleShot(3000, lambda: dw.remove_download(task_id))

    # ─────────────────────────────────────────────────────────
    # Window close
    # ─────────────────────────────────────────────────────────
    def closeEvent(self, event):
        import shutil
        tmp = settings.manager.get_download_dir() / "temp_media"
        if tmp.exists():
            try:
                shutil.rmtree(tmp)
            except Exception:
                pass
        event.accept()

    # ─────────────────────────────────────────────────────────
    # Modals
    # ─────────────────────────────────────────────────────────
    def _on_add_booru(self):
        from ui.modals import AddBooruDialog
        AddBooruDialog(self).exec()

    def _on_global_settings(self):
        self.show_settings()

    def _on_bulk_dl(self):
        from ui.modals import BulkDownloadDialog
        current_tags = self.search_bar.text().strip()
        BulkDownloadDialog(self, current_tags).exec()

    def _apply_dark_title_bar(self):
        """Applies Windows Immersive Dark Mode to the title bar."""
        try:
            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            # Works on Windows 10 build 18985+ and Windows 11
            hwnd = int(self.winId())
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            rendering_policy = ctypes.c_int(1) # 1 = Enable
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 
                DWMWA_USE_IMMERSIVE_DARK_MODE, 
                ctypes.byref(rendering_policy), 
                ctypes.sizeof(rendering_policy)
            )
        except Exception as e:
            logging.error(f"[gui] Failed to set dark title bar: {e}")