"""Right-hand info sidebar of the media overlay."""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollArea

from ui.viewer.details import FileDetails
from ui.viewer.actions import ActionButtons
from ui.viewer.post_displayer_tags import ClickableTagsDropdown
from ui.style import colors


class OverlaySidebar(QWidget):

    def __init__(self, overlay):
        super().__init__()
        self.overlay = overlay
        self.post = None
        
        self.setFixedWidth(350)
        self.setStyleSheet(f"background-color: {colors.MAIN_BG}; border-left: 1px solid {colors.BORDER};")
        
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(15, 15, 15, 15)
        self.content_layout.setSpacing(20)
        
        self.details = FileDetails(self)
        self.content_layout.addWidget(self.details)
        
        self.actions = ActionButtons(self)
        self.content_layout.addWidget(self.actions)
        
        self.tags = ClickableTagsDropdown(self)
        self.content_layout.addWidget(self.tags, 1)
        
        self.scroll.setWidget(self.content_widget)
        self._main_layout.addWidget(self.scroll)

    def load_post(self, post):
        self.post = post
        self.details.load_post(post)
        self.actions.load_post(post)
        self.tags.load_post(post)

    def set_original_loaded(self, loaded):
        self.actions.set_original_loaded(loaded)
