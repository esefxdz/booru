"""
displayers/actions.py — Action buttons for the media overlay.

Provides a row of buttons (Bookmark, Download, Share, Original) to
interact with the currently displayed post.
"""
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
        
        self._is_bookmarked = settings.manager.is_post_bookmarked(self.post_id)
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
        if self._is_bookmarked:
            settings.manager.remove_bookmark(self.post_id)
            self._is_bookmarked = False
        else:
            settings.manager.add_bookmark(self.post)
            self._is_bookmarked = True
        self._update_bm_style()
        self.sidebar.overlay.parent_gui.gallery._update_viewport()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _download  — fetches the original file in a background thread │
    # │  and safely updates the UI text using QTimer.singleShot.       │
    # └──────────────────────────────────────────────────────────────────┘
    def _download(self):
        if not self.post: return
        self.dl_btn.setText("...")
        parent_gui = self.sidebar.overlay.parent_gui
        
        def work():
            try:
                dl_dir = parent_gui.downloader.get_download_folder_for_post(self.post)
                file_url = parent_gui.downloader.get_file_url(self.post)
                ext = os.path.splitext(file_url.split("?")[0])[1] or ".jpg"
                path = dl_dir / f"{self.post_id}{ext}"
                
                from displayers.media_viewer import _resolve_url, _fetch_bytes
                import boorus
                
                post_booru = self.post.get("_booru", settings.manager.active_booru)
                site_data = boorus.REGISTRY.get(post_booru, {})
                resolved_url = _resolve_url(file_url, site_data)
                
                data = _fetch_bytes(resolved_url)
                path.write_bytes(data)
                QTimer.singleShot(0, lambda: self.dl_btn.setText("Done"))
            except Exception as e:
                print(f"[actions] Download error: {e}")
                QTimer.singleShot(0, lambda: self.dl_btn.setText("Failed"))
                
        threading.Thread(target=work, daemon=True).start()

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
        
        def reset():
            import time; time.sleep(2)
            QTimer.singleShot(0, lambda: self.share_btn.setText("Share"))
        threading.Thread(target=reset, daemon=True).start()

    def _view_original(self):
        if not self.post: return
        self.orig_btn.setText("...")
        self.sidebar.overlay.media_viewer.load_post(self.post, original=True)
