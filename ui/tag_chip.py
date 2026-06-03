"""
ui/tag_chip.py

Shared TagChip widget used by both BlacklistView and FavoritesView.
Extracted here so neither view needs to define the same class twice.
"""
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal

from ui.icons import Icons


from ui import colors

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: TagChip                                                     ║
# ║  A small pill-shaped widget representing one tag in a list.        ║
# ║  Shows the tag name on the left and a delete button on the right.  ║
# ║  Emits `removed(tag_name)` when the delete button is clicked.      ║
# ╚══════════════════════════════════════════════════════════════════════╝
class TagChip(QFrame):
    # Carries the tag string so the parent knows which chip was deleted
    removed = pyqtSignal(str)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — builds the chip: label on the left, small trash    │
    # │  icon button on the right, inside a rounded dark pill frame.    │
    # │  The whole frame highlights accent color on hover to signal it's │
    # │  interactive.                                                   │
    # └──────────────────────────────────────────────────────────────────┘
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

        # Tag name label — transparent background so the frame colour shows
        self.label = QLabel(tag)
        self.label.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-weight: 500; background: transparent;")
        layout.addWidget(self.label)

        # Small delete button that emits removed() with this chip's tag name
        self.del_btn = QPushButton()
        self.del_btn.setIcon(Icons.get("blacklist", colors.TEXT_MUTED, 14))
        self.del_btn.setFixedSize(18, 18)
        self.del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.del_btn.setStyleSheet("background: transparent; border: none;")
        self.del_btn.clicked.connect(lambda: self.removed.emit(self.tag))
        layout.addWidget(self.del_btn)
