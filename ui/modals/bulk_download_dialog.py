"""
ui/modals/bulk_download_dialog.py

Simple one-shot dialog that lets the user kick off a bulk download
of the current search query up to a specified image count limit.
"""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
from PyQt6.QtCore import Qt


from ui import colors

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: BulkDownloadDialog                                          ║
# ║  Takes the current active search tags and downloads up to N posts  ║
# ║  by delegating to the controller's bulk_download method.           ║
# ╚══════════════════════════════════════════════════════════════════════╝
class BulkDownloadDialog(QDialog):

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — builds a tiny form: a numeric limit input field    │
    # │  pre-filled with 20, and a START button wired to run_bulk       │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, parent_gui, current_tags):
        super().__init__(parent_gui)
        self.parent_gui = parent_gui
        self.current_tags = current_tags
        self.setWindowTitle("Bulk Download")
        self.setFixedSize(300, 180)
        self.setStyleSheet(f"background-color: {colors.PANEL_BG}; color: {colors.TEXT_SECONDARY};")

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Download limit:")
        title.setStyleSheet(f"font-weight: bold; color: {colors.TEXT_PRIMARY};")
        layout.addWidget(title)

        # Numeric input — how many posts to download in this batch
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

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  run_bulk  — parses the limit field as an integer and fires the │
    # │  controller's bulk_download which handles pagination and saving │
    # └──────────────────────────────────────────────────────────────────┘
    def run_bulk(self):
        try:
            limit = int(self.e.text())
            self.parent_gui.controller.bulk_download(self.current_tags, limit)
            self.accept()
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Limit must be a number.")

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  show_dialog  — convenience static wrapper so callers don't     │
    # │  need to instantiate the dialog themselves                      │
    # └──────────────────────────────────────────────────────────────────┘
    @staticmethod
    def show_dialog(parent_gui, current_tags):
        BulkDownloadDialog(parent_gui, current_tags).exec()
