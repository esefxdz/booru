"""
displayers/sidebar.py — Overlay info sidebar.

A dark right-aligned panel that contains all the metadata panels
(Details, Actions, Tags).
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollArea

from displayers.details import FileDetails
from displayers.actions import ActionButtons
from displayers.post_displayer_tags import ClickableTagsDropdown
from ui import colors
from PyQt6.QtCore import Qt


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: OverlaySidebar                                              ║
# ║  Houses all metadata and controls alongside the media viewer.       ║
# ╚══════════════════════════════════════════════════════════════════════╝
class OverlaySidebar(QWidget):

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — constructs the scrolling panel and its children.   │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, overlay):
        super().__init__()
        self.overlay = overlay
        self.post = None
        
        self.setFixedWidth(350)
        self.setStyleSheet(f"background-color: {colors.MAIN_BG}; border-left: 1px solid {colors.BORDER};")
        
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)
        
        # Scroll area for everything in sidebar
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(f"QScrollArea {{ border: none; background-color: transparent; }}")
        
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(15, 15, 15, 15)
        self.content_layout.setSpacing(20)
        
        # ── Sidebar Components ──
        self.details = FileDetails(self)
        self.content_layout.addWidget(self.details)
        
        self.actions = ActionButtons(self)
        self.content_layout.addWidget(self.actions)
        
        self.tags = ClickableTagsDropdown(self)
        self.content_layout.addWidget(self.tags, 1)  # tags fill remaining space
        
        self.scroll.setWidget(self.content_widget)
        self._main_layout.addWidget(self.scroll)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  load_post  — delegates post data to all child sections.        │
    # └──────────────────────────────────────────────────────────────────┘
    def load_post(self, post):
        self.post = post
        self.details.load_post(post)
        self.actions.load_post(post)
        self.tags.load_post(post)

    def set_original_loaded(self, loaded):
        self.actions.set_original_loaded(loaded)
