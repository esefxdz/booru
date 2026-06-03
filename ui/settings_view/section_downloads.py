"""
ui/settings_view/section_downloads.py

Download settings section: engine selection, smart folders, download path.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QFrame,
    QPushButton, QFileDialog, QComboBox,
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

        # ── Download Engine ───────────────────────────────────────────
        engine_card = QFrame()
        engine_card.setStyleSheet(f"QFrame {{ background-color: {colors.PANEL_BG}; border: 1px solid {colors.BORDER}; border-radius: 12px; }}")
        engine_v = QVBoxLayout(engine_card)
        engine_v.setContentsMargins(20, 16, 20, 16)
        engine_v.setSpacing(8)

        engine_title = QLabel("Download Engine")
        engine_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        engine_v.addWidget(engine_title)

        engine_desc = QLabel(
            "Choose which HTTP engine downloads image files to your PC. "
            "\"urllib\" is built into Python and works for almost every site. "
            "Use \"curl_cffi\" if downloads fail on Cloudflare-protected CDNs."
        )
        engine_desc.setWordWrap(True)
        engine_desc.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px;")
        engine_v.addWidget(engine_desc)

        self.engine_combo = QComboBox()
        self.engine_combo.setFixedHeight(36)
        self.engine_combo.setStyleSheet(f"""
            QComboBox {{
                background: {colors.INPUT_BG};
                color: {colors.TEXT_PRIMARY};
                border: 1px solid {colors.BUTTON_BG};
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 13px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 28px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid {colors.TEXT_MUTED};
                margin-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background: {colors.DROPDOWN_BG};
                color: {colors.TEXT_PRIMARY};
                border: 1px solid {colors.DROPDOWN_BORDER};
                selection-background-color: {colors.ACCENT};
                selection-color: {colors.TEXT_PRIMARY};
                padding: 4px;
                outline: none;
            }}
            QComboBox QAbstractItemView::item {{
                min-height: 28px;
                padding: 4px 8px;
            }}
        """)

        from download_images.engines import ENGINES, ENGINE_LABELS, get_available_engines
        available = get_available_engines()
        current = getattr(settings.manager, "download_engine", "urllib")
        selected_index = 0

        for i, eng in enumerate(ENGINES):
            label = ENGINE_LABELS.get(eng, eng)
            if eng not in available:
                label = f"{label}  (not installed)"
            self.engine_combo.addItem(label, eng)
            if eng == current:
                selected_index = i

        self.engine_combo.setCurrentIndex(selected_index)
        engine_v.addWidget(self.engine_combo)

        avail_lbl = QLabel(f"Available: {', '.join(available)}")
        avail_lbl.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 11px; font-style: italic;")
        engine_v.addWidget(avail_lbl)

        layout.addWidget(engine_card)

        # ── Folder Organization ───────────────────────────────────────
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

        note = QLabel("Only applies when Smart Folders is enabled.")
        note.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 11px; margin-left: 26px;")
        card_v.addWidget(note)

        layout.addWidget(card)

        # ── Download Location ─────────────────────────────────────────
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
        settings.manager.download_engine = self.engine_combo.currentData() or "urllib"
        
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
        # Reset engine to urllib
        for i in range(self.engine_combo.count()):
            if self.engine_combo.itemData(i) == "urllib":
                self.engine_combo.setCurrentIndex(i)
                break

    def load(self):
        self.smart_folders.setChecked(settings.manager.use_smart_folders)
        self.artist_folder.setChecked(settings.manager.download_folder_use_artist_folder)
        self.pval.setText(str(settings.manager.get_download_dir().resolve()))
        current = getattr(settings.manager, "download_engine", "urllib")
        for i in range(self.engine_combo.count()):
            if self.engine_combo.itemData(i) == current:
                self.engine_combo.setCurrentIndex(i)
                break
