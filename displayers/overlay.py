"""
displayers/overlay.py — Full-screen media viewer overlay.

This is the top-level container that holds both the MediaViewer (left)
and the OverlaySidebar (right). It sits on top of the main gallery
and handles keyboard shortcuts for navigation.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QWidget, QHBoxLayout
from ui import colors

from displayers.media_viewer import MediaViewer
from displayers.sidebar import OverlaySidebar


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: MediaOverlay                                                ║
# ║  The main overlay container. Manages the left/right split and       ║
# ║  handles next/prev keyboard shortcuts.                              ║
# ╚══════════════════════════════════════════════════════════════════════╝
class MediaOverlay(QWidget):

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — starts hidden. Creates the layout.                 │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, parent_gui):
        super().__init__(parent_gui)
        self.parent_gui = parent_gui
        self.post = None
        self.hide()
        
        self.setStyleSheet(f"background-color: {colors.MAIN_BG};")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        
        self._main_layout = QHBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)
        
        # Left side: Media Viewer (image, video, GIF)
        self.media_viewer = MediaViewer(self)
        self._main_layout.addWidget(self.media_viewer, 1)
        
        # Right side: Metadata and Actions
        self.sidebar = OverlaySidebar(self)
        self._main_layout.addWidget(self.sidebar)

        # ── Close Button ──
        from PyQt6.QtWidgets import QPushButton
        self.close_btn = QPushButton("✕", self)
        self.close_btn.setFixedSize(36, 36)
        self.close_btn.setStyleSheet(f"background-color: {colors.BUTTON_BG}; color: {colors.TEXT_PRIMARY}; border-radius: 18px; font-weight: bold; font-size: 16px;")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.close_overlay)
        self.close_btn.move(20, 20)

        self._setup_shortcuts()
        
    def _setup_shortcuts(self):
        # Esc to close
        self.esc_shortcut = QShortcut(QKeySequence("Esc"), self)
        self.esc_shortcut.activated.connect(self.close_overlay)
        
        # A left, D right
        self.left_shortcut = QShortcut(QKeySequence("A"), self)
        self.left_shortcut.activated.connect(self.prev_post)
        
        self.right_shortcut = QShortcut(QKeySequence("D"), self)
        self.right_shortcut.activated.connect(self.next_post)
        
    # ┌──────────────────────────────────────────────────────────────────┐
    # │  show_post  — sizes the overlay to cover the whole window,      │
    # │  brings it to front, and delegates the post to children.        │
    # └──────────────────────────────────────────────────────────────────┘
    def show_post(self, post):
        self.post = post
        stack = self.parent_gui.stack
        self.setParent(stack)
        self.setGeometry(stack.rect())
        self.media_viewer.load_post(post)
        self.sidebar.load_post(post)
        self.show()
        self.raise_()
        self.setFocus()
        
    def close_overlay(self):
        self.media_viewer.stop()
        self.hide()
        
    # ┌──────────────────────────────────────────────────────────────────┐
    # │  prev_post / next_post  — locates the current post inside the   │
    # │  gallery's internal array, then navigates forwards/backwards.   │
    # │  Triggers infinite scroll if we reach the end.                  │
    # └──────────────────────────────────────────────────────────────────┘
    def prev_post(self):
        if not self.isVisible() or not self.post:
            return
        gallery = self.parent_gui.gallery
        post = gallery.get_adjacent_post(self.post.get("id"), "prev")
        if post is not None:
            self.show_post(post)

    def next_post(self):
        if not self.isVisible() or not self.post:
            return
        gallery = self.parent_gui.gallery
        post = gallery.get_adjacent_post(self.post.get("id"), "next")
        if post is not None:
            self.show_post(post)
        else:
            # Reached the last loaded post — ask gallery to load more
            gallery.load_more_requested.emit()
