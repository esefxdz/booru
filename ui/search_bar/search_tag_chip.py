from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal
from ui.style import colors
from ui.style.icons import Icons

class SearchTagChip(QFrame):
    changed = pyqtSignal(str, bool)
    removed = pyqtSignal(str)

    def __init__(self, tag: str, parent=None):
        super().__init__(parent)
        self.tag = tag.lstrip("-")
        self.is_neg = tag.startswith("-")
        
        self.setObjectName("SearchTagChip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 4, 2)
        layout.setSpacing(4)
        
        self.label = QLabel(self.tag)
        self.label.setStyleSheet("font-weight: 500; background: transparent;")
        layout.addWidget(self.label)
        
        self.del_btn = QPushButton()
        self.del_btn.setIcon(Icons.get("blacklist", colors.TEXT_PRIMARY, 12))
        self.del_btn.setFixedSize(16, 16)
        self.del_btn.setStyleSheet("background: transparent; border: none;")
        self.del_btn.clicked.connect(lambda: self.removed.emit(self.tag))
        layout.addWidget(self.del_btn)
        
        self._update_color()

    def _update_color(self):
        color = colors.DANGER if self.is_neg else colors.ACCENT
        self.setStyleSheet(f"""
            #SearchTagChip {{
                background-color: {color};
                border-radius: 12px;
                color: {colors.TEXT_PRIMARY};
            }}
            #SearchTagChip:hover {{
                background-color: {color}dd;
            }}
        """)

    def mousePressEvent(self, event):
        """Toggles between -tag and tag when the chip body is clicked."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_neg = not self.is_neg
            self._update_color()
            self.changed.emit(self.tag, self.is_neg)
        super().mousePressEvent(event)
