"""
displayers/details.py — Collapsible metadata sections.

Provides reusable components for displaying post metadata like ID,
resolution, and rating in a clean, space-saving format.
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel
from ui import colors


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: CollapsibleWidget                                           ║
# ║  A generic widget with a clickable header button that shows or     ║
# ║  hides its content area.                                            ║
# ╚══════════════════════════════════════════════════════════════════════╝
class CollapsibleWidget(QWidget):
    
    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — creates the toggle button and content container.   │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.toggle_btn = QPushButton(title)
        self.toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {colors.TEXT_PRIMARY};
                text-align: left;
                font-weight: bold;
                font-size: 14px;
                border: none;
                padding: 8px 0;
            }}
            QPushButton:hover {{
                color: {colors.ACCENT};
            }}
        """)
        self.toggle_btn.clicked.connect(self.toggle)
        self._main_layout.addWidget(self.toggle_btn)
        
        self.content_area = QWidget()
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.addWidget(self.content_area)
        
        self.is_expanded = True
        
    def toggle(self):
        self.is_expanded = not self.is_expanded
        self.content_area.setVisible(self.is_expanded)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: FileDetails                                                 ║
# ║  Subclasses CollapsibleWidget to show a simple text block with     ║
# ║  post ID, rating, resolution, and format.                           ║
# ╚══════════════════════════════════════════════════════════════════════╝
class FileDetails(CollapsibleWidget):
    
    def __init__(self, sidebar):
        super().__init__("File details")
        self.sidebar = sidebar
        
        self.info_lbl = QLabel()
        self.info_lbl.setWordWrap(True)
        self.info_lbl.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-size: 13px; line-height: 1.5;")
        self.content_layout.addWidget(self.info_lbl)
        
    # ┌──────────────────────────────────────────────────────────────────┐
    # │  load_post  — extracts basic metadata from the post dict.       │
    # └──────────────────────────────────────────────────────────────────┘
    def load_post(self, post):
        pid = post.get('id', 'Unknown')
        rating = post.get('rating', 'Unknown')
        w = post.get('image_width', '?')
        h = post.get('image_height', '?')
        ext = post.get('file_ext', '')
        if not ext and 'file_url' in post:
            ext = post['file_url'].split('?')[0].split('.')[-1]
        
        self.pid = pid
        self.rating = rating
        self.ext = ext
        self.w = w
        self.h = h
        
        self._update_text()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  update_resolution  — called by media_viewer when the actual    │
    # │  image is loaded and we know its true dimensions.               │
    # └──────────────────────────────────────────────────────────────────┘
    def update_resolution(self, w, h):
        self.w = w
        self.h = h
        self._update_text()
        
    def _update_text(self):
        text = f"ID: {self.pid}\nRating: {str(self.rating).capitalize()}\nResolution: {self.w}x{self.h}\nFormat: {str(self.ext).upper()}"
        self.info_lbl.setText(text)
