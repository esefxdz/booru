from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QHBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal
from ui import colors

class DownloadProgressBar(QWidget):
    """A single progress bar for a file download."""
    def __init__(self, filename, parent=None):
        super().__init__(parent)
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(5, 5, 5, 5)
        self._main_layout.setSpacing(2)

        # Top row: Filename and percentage text
        self.top_row = QHBoxLayout()
        self.filename_lbl = QLabel(filename)
        self.filename_lbl.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-size: 11px; font-weight: bold;")
        self.pct_lbl = QLabel("0%")
        self.pct_lbl.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-size: 11px;")
        
        self.top_row.addWidget(self.filename_lbl)
        self.top_row.addStretch()
        self.top_row.addWidget(self.pct_lbl)
        self._main_layout.addLayout(self.top_row)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {colors.MAIN_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {colors.ACCENT};
                border-radius: 3px;
            }}
        """)
        self._main_layout.addWidget(self.progress)

    def update_progress(self, current, total):
        if total > 0:
            pct = int((current / total) * 100)
            self.progress.setValue(pct)
            self.pct_lbl.setText(f"{pct}%")
            if pct >= 100:
                self.pct_lbl.setText("Done")
                self.pct_lbl.setStyleSheet(f"color: {colors.SUCCESS}; font-size: 11px;")


class DownloadWindow(QWidget):
    """
    Floating or docked widget displaying active download progress bars.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bars = {}  # Map of task_id -> DownloadProgressBar

        self.setStyleSheet(f"""
            DownloadWindow {{
                background-color: {colors.PANEL_BG};
                border: 3px solid {colors.ACCENT};  /* Thick border as requested */
                border-radius: 8px;
            }}
        """)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMaximumWidth(216)

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(10, 10, 10, 10)
        self._main_layout.setSpacing(5)

        self.title_lbl = QLabel("Downloads")
        self.title_lbl.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        self._main_layout.addWidget(self.title_lbl)

    def add_download(self, task_id, filename):
        bar = DownloadProgressBar(filename)
        self.bars[task_id] = bar
        self._main_layout.addWidget(bar)
        self.show()

    def update_download(self, task_id, current, total):
        if task_id in self.bars:
            self.bars[task_id].update_progress(current, total)

    def remove_download(self, task_id):
        if task_id in self.bars:
            bar = self.bars.pop(task_id)
            self._main_layout.removeWidget(bar)
            bar.deleteLater()
        
        # Hide if no downloads are active
        if not self.bars:
            self.hide()
