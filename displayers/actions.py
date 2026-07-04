"""
displayers/actions.py — Action buttons for the media overlay.

Provides a row of buttons (Bookmark, Download, Share, Original) to
interact with the currently displayed post.
"""
import logging
import os
import threading
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QApplication
from PyQt6.QtCore import Qt, QTimer

from ui import colors
from ui import settings_view as settings


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: ActionButtons                                               ║
# ║  A horizontal strip of buttons. Handles the logic for downloading  ║
# ║  the file to the smart folders, copying its URL, or bookmarking.   ║
# ╚══════════════════════════════════════════════════════════════════════╝
class ActionButtons(QWidget):

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — constructs the button row.                         │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, sidebar):
        super().__init__()
        self.sidebar = sidebar
        self.post = None
        
        self._main_layout = QHBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(10)
        
        self.bm_btn = self._make_btn("Bookmark")
        self.bm_btn.clicked.connect(self._toggle_bookmark)
        
        self.dl_btn = self._make_btn("Download")
        self.dl_btn.clicked.connect(self._download)
        
        self.share_btn = self._make_btn("Share")
        self.share_btn.clicked.connect(self._share)
        
        self.orig_btn = self._make_btn("Original")
        self.orig_btn.clicked.connect(self._view_original)
        
        self._main_layout.addWidget(self.bm_btn)
        self._main_layout.addWidget(self.dl_btn)
        self._main_layout.addWidget(self.share_btn)
        self._main_layout.addWidget(self.orig_btn)

        # ── Connect download signals so the button reflects outcome ──
        self._pending_dl_tid = None
        self._dl_signals_connected = False

    def _connect_dl_signals(self):
        """Wire up the downloader signals (only once)."""
        if self._dl_signals_connected:
            return
        self._dl_signals_connected = True
        dl = self.sidebar.overlay.parent_gui.downloader
        dl.download_finished.connect(self._on_dl_finished)
        dl.download_failed.connect(self._on_dl_failed)

    def _on_dl_finished(self, task_id):
        if task_id == self._pending_dl_tid:
            self._set_dl_status("Done", colors.SUCCESS)

    def _on_dl_failed(self, task_id, error):
        if task_id == self._pending_dl_tid:
            self._set_dl_status("Failed", colors.DANGER)
        
    def _make_btn(self, text):
        btn = QPushButton(text)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.BUTTON_BG};
                color: {colors.TEXT_PRIMARY};
                border: none;
                border-radius: 4px;
                padding: 6px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {colors.BUTTON_HOVER}; }}
        """)
        return btn

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  load_post  — updates state for the newly selected post.       │
    # └──────────────────────────────────────────────────────────────────┘
    def load_post(self, post):
        self.post = post
        self.post_id = str(post.get('id', ''))
        self.dl_btn.setText("Download")
        self.orig_btn.setText("Original")
        self.orig_btn.show()
        
        from ui.bookmarks_main.bookmarks_db import db
        self._is_bookmarked = db.is_post_bookmarked(self.post_id)
        self._update_bm_style()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  set_original_loaded  — hides the 'Original' button when we    │
    # │  are already viewing the original file.                        │
    # └──────────────────────────────────────────────────────────────────┘
    def set_original_loaded(self, loaded):
        if loaded:
            self.orig_btn.hide()
        else:
            self.orig_btn.show()

    # ══════════════════════════════════════════════════════════════════
    #  PRIVATE — Actions
    # ══════════════════════════════════════════════════════════════════

    def _update_bm_style(self):
        self.bm_btn.setText("★" if self._is_bookmarked else "☆ Bookmark")
        c = colors.FAVORITE if self._is_bookmarked else colors.TEXT_PRIMARY
        self.bm_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.BUTTON_BG};
                color: {c};
                border: none;
                border-radius: 4px;
                padding: 6px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {colors.BUTTON_HOVER}; }}
        """)

    def _toggle_bookmark(self):
        if not self.post: return
        from ui.bookmarks_main.bookmarks_db import db
        if self._is_bookmarked:
            db.remove_bookmark(self.post_id)
            self._is_bookmarked = False
        else:
            db.add_bookmark(self.post)
            self._is_bookmarked = True
        self._update_bm_style()
        self.sidebar.overlay.parent_gui.gallery.refresh_visible_stars()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _download  — fetches the original file in a background thread │
    # │  and safely updates the UI text using QTimer.singleShot.       │
    # └──────────────────────────────────────────────────────────────────┘
    def _download(self):
        if not self.post: return
        self.dl_btn.setText("⏳ ...")
        parent_gui = self.sidebar.overlay.parent_gui
        self._connect_dl_signals()
        self._pending_dl_tid = str(self.post.get("id", ""))
        post = self.post  # capture reference — self.post may change
        
        def work():
            try:
                from download_images import get_download_folder
                dl_dir = get_download_folder(post, parent_gui.downloader)
                parent_gui.downloader.download_file(str(post.get("id", "")), post, dl_dir)
            except Exception as e:
                logging.error(f"[actions] Download error: {e}")
                parent_gui.downloader.download_failed.emit(str(post.get("id", "unknown")), str(e))
                
        threading.Thread(target=work, daemon=True).start()

    def _set_dl_status(self, text, color=None):
        """Thread-safe helper to update download button text."""
        self.dl_btn.setText(text)
        if color:
            self.dl_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {colors.BUTTON_BG};
                    color: {color};
                    border: none;
                    border-radius: 4px;
                    padding: 6px;
                    font-size: 12px;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background-color: {colors.BUTTON_HOVER}; }}
            """)
        # Reset after 3 seconds
        QTimer.singleShot(3000, lambda: self._reset_dl_btn())

    def _reset_dl_btn(self):
        """Restore the download button to its default state."""
        self.dl_btn.setText("Download")
        self.dl_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.BUTTON_BG};
                color: {colors.TEXT_PRIMARY};
                border: none;
                border-radius: 4px;
                padding: 6px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {colors.BUTTON_HOVER}; }}
        """)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _share  — copies URL to clipboard and resets button text.     │
    # └──────────────────────────────────────────────────────────────────┘
    def _share(self):
        if not self.post: return
        parent_gui = self.sidebar.overlay.parent_gui
        file_url = parent_gui.downloader.get_file_url(self.post)
        import boorus
        post_booru = self.post.get("_booru", settings.manager.active_booru)
        site_data = boorus.REGISTRY.get(post_booru, {})
        
        from displayers.media_viewer import _resolve_url
        resolved = _resolve_url(file_url, site_data)
        
        QApplication.clipboard().setText(resolved)
        self.share_btn.setText("Copied!")
        QTimer.singleShot(2000, lambda: self.share_btn.setText("Share"))

    def _view_original(self):
        if not self.post: return
        self.orig_btn.setText("...")
        self.sidebar.overlay.media_viewer.load_post(self.post, original=True)
