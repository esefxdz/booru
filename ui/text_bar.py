from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton, QLabel, QGraphicsDropShadowEffect, QFrame
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint, QTimer
from PyQt6.QtGui import QColor
from ui.icons import Icons
import ui.animations as anims


from ui import colors
#this is for favorite tags and blacklist tags

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                       CLASS: BooruTextBar                           ║
# ╚══════════════════════════════════════════════════════════════════════╝
class BooruTextBar(QWidget):
    submitted = pyqtSignal(str)  # Emitted when Enter is pressed

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__                                                        │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, parent, placeholder="Enter text..."):
        super().__init__(parent)
        self.setup_ui(placeholder)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  setup_ui                                                        │
    # └──────────────────────────────────────────────────────────────────┘
    def setup_ui(self, placeholder):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Main container with border and background
        self.container = QFrame()
        self.container.setFixedHeight(48)
        self.container.setObjectName("TextContainer")
        self.container.setStyleSheet(f"""
            QFrame#TextContainer {{
                background-color: {colors.BUTTON_BG};
                border: 2px solid transparent;
                border-radius: 12px;
            }}
        """)
        
        container_layout = QHBoxLayout(self.container)
        container_layout.setContentsMargins(12, 0, 12, 0)
        container_layout.setSpacing(8)

        # Icon
        self.icon_lbl = QLabel()
        self.icon_lbl.setPixmap(Icons.get("search", colors.TEXT_MUTED).pixmap(20, 20))
        container_layout.addWidget(self.icon_lbl)

        # Input field
        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                border: none;
                color: {colors.TEXT_PRIMARY};
                font-size: 16px;
                selection-background-color: {colors.ACCENT};
            }}
        """)
        self.input.returnPressed.connect(self._on_return)
        container_layout.addWidget(self.input, 1)

        # Clear Button
        self.clear_btn = QPushButton()
        self.clear_btn.setIcon(Icons.get("close", colors.TEXT_MUTED))
        self.clear_btn.setFixedSize(24, 24)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setStyleSheet("background: transparent; border: none;")
        self.clear_btn.clicked.connect(self.clear)
        self.clear_btn.hide()
        container_layout.addWidget(self.clear_btn)

        layout.addWidget(self.container)

        # Shadow
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(15)
        self.shadow.setXOffset(0)
        self.shadow.setYOffset(4)
        self.shadow.setColor(QColor(0, 0, 0, 0))  # Start invisible
        self.setGraphicsEffect(self.shadow)

        self.input.textChanged.connect(self._on_text_changed)
        self.input.installEventFilter(self)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  eventFilter                                                     │
    # └──────────────────────────────────────────────────────────────────┘
    def eventFilter(self, obj, event):
        if obj == self.input:
            if event.type() == event.Type.FocusIn:
                self._set_active_style(True)
            elif event.type() == event.Type.FocusOut:
                self._set_active_style(False)
        return super().eventFilter(obj, event)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _set_active_style                                               │
    # └──────────────────────────────────────────────────────────────────┘
    def _set_active_style(self, active):
        if active:
            self.container.setStyleSheet(f"""
                QFrame#TextContainer {{
                    background-color: {colors.MAIN_BG};
                    border: 2px solid {colors.ACCENT};
                    border-radius: 12px;
                }}
            """)
            self.shadow.setColor(QColor(0, 0, 0, 150))
            self.icon_lbl.setPixmap(Icons.get("search", colors.ACCENT).pixmap(20, 20))
        else:
            self.container.setStyleSheet(f"""
                QFrame#TextContainer {{
                    background-color: {colors.BUTTON_BG};
                    border: 2px solid transparent;
                    border-radius: 12px;
                }}
            """)
            self.shadow.setColor(QColor(0, 0, 0, 0))
            self.icon_lbl.setPixmap(Icons.get("search", colors.TEXT_MUTED).pixmap(20, 20))

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _on_text_changed                                                │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_text_changed(self, text):
        self.clear_btn.setVisible(bool(text))

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _on_return                                                      │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_return(self):
        self.submitted.emit(self.input.text())

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  clear                                                           │
    # └──────────────────────────────────────────────────────────────────┘
    def clear(self):
        self.input.clear()
        self.input.setFocus()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  text                                                            │
    # └──────────────────────────────────────────────────────────────────┘
    def text(self):
        return self.input.text()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  setText                                                         │
    # └──────────────────────────────────────────────────────────────────┘
    def setText(self, text):
        self.input.setText(text)
