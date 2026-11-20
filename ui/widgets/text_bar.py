from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QPushButton, QLabel, QGraphicsDropShadowEffect, QFrame
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from ui.style.icons import Icons


from ui.style import colors

class BooruTextBar(QWidget):
    submitted = pyqtSignal(str)

    def __init__(self, parent, placeholder="Enter text..."):
        super().__init__(parent)
        self.setup_ui(placeholder)

    def setup_ui(self, placeholder):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

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

        self.icon_lbl = QLabel()
        self.icon_lbl.setPixmap(Icons.get("search", colors.TEXT_MUTED).pixmap(20, 20))
        container_layout.addWidget(self.icon_lbl)

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

        self.clear_btn = QPushButton()
        self.clear_btn.setIcon(Icons.get("close", colors.TEXT_MUTED))
        self.clear_btn.setFixedSize(24, 24)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setStyleSheet("background: transparent; border: none;")
        self.clear_btn.clicked.connect(self.clear)
        self.clear_btn.hide()
        container_layout.addWidget(self.clear_btn)

        layout.addWidget(self.container)

        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(15)
        self.shadow.setXOffset(0)
        self.shadow.setYOffset(4)
        self.shadow.setColor(QColor(0, 0, 0, 0))
        self.setGraphicsEffect(self.shadow)

        self.input.textChanged.connect(self._on_text_changed)
        self.input.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj == self.input:
            if event.type() == event.Type.FocusIn:
                self._set_active_style(True)
            elif event.type() == event.Type.FocusOut:
                self._set_active_style(False)
        return super().eventFilter(obj, event)

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

    def _on_text_changed(self, text):
        self.clear_btn.setVisible(bool(text))

    def _on_return(self):
        self.submitted.emit(self.input.text())

    def clear(self):
        self.input.clear()
        self.input.setFocus()

    def text(self):
        return self.input.text()

    def setText(self, text):
        self.input.setText(text)
