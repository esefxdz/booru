from PyQt6.QtWidgets import QListWidget, QGraphicsDropShadowEffect
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from ui import colors

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: AutocompleteList                                            ║
# ║  The floating dropdown list that appears below the search bar.     ║
# ║  Styled to blend with the app theme and given a shadow to          ║
# ║  visually float above the rest of the UI.                          ║
# ╚══════════════════════════════════════════════════════════════════════╝
class AutocompleteList(QListWidget):

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — hides itself initially, disables focus (so the     │
    # │  search bar keeps focus), hides scrollbars (height is managed   │
    # │  manually), and adds a drop shadow for the floating effect      │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, parent):
        super().__init__(parent)
        self.hide()
        # No focus: keyboard events stay in the search input, not here
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Both scrollbars off — we control height based on result count
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(f"""
            QListWidget {{
                background-color: {colors.DROPDOWN_BG};
                color: {colors.TEXT_SECONDARY};
                border: 1px solid {colors.DROPDOWN_BORDER};
                border-radius: 4px;
                font-size: 14px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 10px 14px;
                border-bottom: 1px solid {colors.DROPDOWN_SEP};
            }}
            QListWidget::item:last {{ border-bottom: none; }}
            QListWidget::item:hover {{ background-color: {colors.DROPDOWN_HOVER}; }}
            QListWidget::item:selected {{
                background-color: {colors.ACCENT};
                color: white;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(10)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(shadow)
