"""
ui/settings_view/section_downloads.py

Download folder settings section: smart folders, artist folder preference.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QFrame, QPushButton, QFileDialog
)
from PyQt6.QtCore import Qt
from ui import settings_view as settings
from ui import colors


class DownloadsSection(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        card = QFrame()
        card.setStyleSheet(f"QFrame {{ background-color: {colors.PANEL_BG}; border: 1px solid {colors.BORDER}; border-radius: 12px; }}")
        card_v = QVBoxLayout(card)
        card_v.setContentsMargins(20, 16, 20, 16)
        card_v.setSpacing(12)

        title = QLabel("Download Organization")
        title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        card_v.addWidget(title)

        desc = QLabel("Configure how downloaded images are organized into folders.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px;")
        card_v.addWidget(desc)

        self.smart_folders = QCheckBox("Enable Smart Folders (auto-organize by tags)")
        self.smart_folders.setChecked(settings.manager.use_smart_folders)
        card_v.addWidget(self.smart_folders)

        self.artist_folder = QCheckBox("Prefer artist folder over character folder")
        self.artist_folder.setChecked(settings.manager.download_folder_use_artist_folder)
        card_v.addWidget(self.artist_folder)

        note = QLabel("↳ Only applies when Smart Folders is enabled.")
        note.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 11px; margin-left: 26px;")
        card_v.addWidget(note)

        layout.addWidget(card)

        # Download path info
        path_card = QFrame()
        path_card.setStyleSheet(f"QFrame {{ background-color: {colors.PANEL_BG}; border: 1px solid {colors.BORDER}; border-radius: 12px; }}")
        path_v = QVBoxLayout(path_card)
        path_v.setContentsMargins(20, 16, 20, 16)
        path_v.setSpacing(8)
        ptitle = QLabel("Download Location")
        ptitle.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        path_v.addWidget(ptitle)
        path_row = QHBoxLayout()
        self.pval = QLabel(str(settings.manager.get_download_dir().resolve()))
        self.pval.setWordWrap(True)
        self.pval.setStyleSheet(f"color: {colors.LINK}; font-size: 12px; font-family: Consolas, monospace;")
        self.pval.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_row.addWidget(self.pval, 1)

        self.btn_change_dir = QPushButton("Change Location")
        self.btn_change_dir.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_change_dir.setStyleSheet(f"""
            QPushButton {{ background: {colors.BUTTON_BG}; color: {colors.TEXT_SECONDARY}; border: 1px solid {colors.BORDER}; border-radius: 6px; padding: 6px 12px; }}
            QPushButton:hover {{ background: {colors.BUTTON_HOVER}; border-color: {colors.ACCENT}; }}
        """)
        self.btn_change_dir.clicked.connect(self._change_location)
        path_row.addWidget(self.btn_change_dir)

        path_v.addLayout(path_row)
        layout.addWidget(path_card)
        layout.addStretch()

    def _change_location(self):
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "Select Download Folder",
            str(settings.manager.get_download_dir()),
            QFileDialog.Option.ShowDirsOnly
        )
        if dir_path:
            self.pval.setText(dir_path)

    def apply(self):
        settings.manager.use_smart_folders = self.smart_folders.isChecked()
        settings.manager.download_folder_use_artist_folder = self.artist_folder.isChecked()
        
        # Only update if the user actually clicked change location and it's valid
        new_path = self.pval.text()
        if new_path and new_path != str(settings.DOWNLOAD_DIR.resolve()):
            settings.manager.custom_download_path = new_path
        elif new_path == str(settings.DOWNLOAD_DIR.resolve()):
            settings.manager.custom_download_path = ""

    def reset(self):
        self.smart_folders.setChecked(False)
        self.artist_folder.setChecked(False)
        self.pval.setText(str(settings.DOWNLOAD_DIR.resolve()))
