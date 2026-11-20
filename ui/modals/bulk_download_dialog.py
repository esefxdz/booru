"""Dialog that starts a bulk download of the current query."""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
from PyQt6.QtCore import Qt


from ui.style import colors

class BulkDownloadDialog(QDialog):

    def __init__(self, parent_gui, current_tags):
        super().__init__(parent_gui)
        self.parent_gui = parent_gui
        self.current_tags = current_tags
        self.setWindowTitle("Bulk Download")
        self.setFixedSize(340, 210)
        self.setStyleSheet(f"background-color: {colors.PANEL_BG}; color: {colors.TEXT_SECONDARY};")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Download limit:")
        title.setStyleSheet(f"font-weight: bold; color: {colors.TEXT_PRIMARY};")
        layout.addWidget(title)

        self.e = QLineEdit()
        self.e.setText("20")
        self.e.setStyleSheet(f"""
            QLineEdit {{
                background-color: {colors.INPUT_BG};
                color: {colors.TEXT_PRIMARY};
                border: 1px solid {colors.BORDER};
                border-radius: 4px;
                padding: 8px;
            }}
        """)
        layout.addWidget(self.e)

        hint = QLabel("⬇ Progress will appear in the Downloads tab.")
        hint.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        run_btn = QPushButton("🚀 START DOWNLOAD")
        run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        run_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.ACCENT};
                color: {colors.TEXT_PRIMARY};
                font-weight: bold;
                padding: 10px;
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {colors.ACCENT_HOVER}; }}
        """)
        run_btn.clicked.connect(self.run_bulk)
        layout.addWidget(run_btn)

    def run_bulk(self):
        try:
            limit = int(self.e.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Limit must be a number.")
            return

        self.parent_gui.controller.bulk_download(self.current_tags, limit)
        self.parent_gui.show_downloads()
        self.accept()

    @staticmethod
    def show_dialog(parent_gui, current_tags):
        BulkDownloadDialog(parent_gui, current_tags).exec()
