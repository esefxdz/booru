"""Pill-shaped tag widget shared by BlacklistView and FavoritesView."""
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal

from ui.style.icons import Icons


from ui.style import colors

class TagChip(QFrame):
    removed = pyqtSignal(str)

    def __init__(self, tag: str, parent=None):
        super().__init__(parent)
        self.tag = tag
        self.setObjectName("TagChip")
        self.setStyleSheet(f"""
            #TagChip {{
                background-color: {colors.BUTTON_HOVER};
                border-radius: 14px;
                padding: 4px 8px;
                border: 1px solid {colors.BUTTON_BG};
            }}
            #TagChip:hover {{
                background-color: {colors.BUTTON_BG};
                border: 1px solid {colors.ACCENT};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 6, 2)
        layout.setSpacing(6)

        self.label = QLabel(tag)
        self.label.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-weight: 500; background: transparent;")
        layout.addWidget(self.label)

        self.del_btn = QPushButton()
        self.del_btn.setIcon(Icons.get("blacklist", colors.TEXT_MUTED, 14))
        self.del_btn.setFixedSize(18, 18)
        self.del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.del_btn.setStyleSheet("background: transparent; border: none;")
        self.del_btn.clicked.connect(lambda: self.removed.emit(self.tag))
        layout.addWidget(self.del_btn)
