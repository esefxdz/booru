"""Full-screen media overlay holding the viewer and sidebar."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QWidget, QHBoxLayout
from ui.style import colors

from ui.viewer.media_viewer import MediaViewer
from ui.viewer.sidebar import OverlaySidebar


class MediaOverlay(QWidget):

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
        
        self.media_viewer = MediaViewer(self)
        self._main_layout.addWidget(self.media_viewer, 1)
        
        self.sidebar = OverlaySidebar(self)
        self._main_layout.addWidget(self.sidebar)

        from PyQt6.QtWidgets import QPushButton
        self.close_btn = QPushButton("✕", self)
        self.close_btn.setFixedSize(36, 36)
        self.close_btn.setStyleSheet(f"background-color: {colors.BUTTON_BG}; color: {colors.TEXT_PRIMARY}; border-radius: 18px; font-weight: bold; font-size: 16px;")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.close_overlay)
        self.close_btn.move(20, 20)

        self._setup_shortcuts()
        
    def _setup_shortcuts(self):
        self.esc_shortcut = QShortcut(QKeySequence("Esc"), self)
        self.esc_shortcut.activated.connect(self.close_overlay)
        
        self.left_shortcut = QShortcut(QKeySequence("A"), self)
        self.left_shortcut.activated.connect(self.prev_post)
        
        self.right_shortcut = QShortcut(QKeySequence("D"), self)
        self.right_shortcut.activated.connect(self.next_post)
        
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
        
    def prev_post(self):
        if not self.isVisible() or not self.post:
            return
        gallery = self.parent_gui.gallery
        post = gallery.get_adjacent_post(self.post, "prev")
        if post is not None:
            self.show_post(post)

    def next_post(self):
        if not self.isVisible() or not self.post:
            return
        gallery = self.parent_gui.gallery
        post = gallery.get_adjacent_post(self.post, "next")
        if post is not None:
            self.show_post(post)
        else:
            # Reached the last loaded post — ask gallery to load more
            gallery.load_more_requested.emit()
