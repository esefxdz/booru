"""
ui/modals/global_settings_dialog.py

Application-wide settings dialog.
Allows users to configure display preferences, network settings, and media engines.

Restored from original + new features added in previous sessions.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QSpinBox, QFormLayout,
    QFrame, QWidget, QScrollArea, QSlider, QMessageBox
)
from PyQt6.QtCore import Qt
from ui import settings_view as settings
from ui import colors
import ui.animations as anims

class GlobalSettingsDialog(QDialog):
    def __init__(self, parent_gui):
        super().__init__(parent_gui)
        self.parent_gui = parent_gui
        self.setWindowTitle("⚙  Global Settings")
        self.setFixedSize(480, 620)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setStyleSheet(f"background-color: {colors.MODAL_BG}; color: {colors.TEXT_SECONDARY};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title
        title = QLabel("Global Configuration")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {colors.TEXT_PRIMARY};")
        layout.addWidget(title)

        # Scroll Area for many settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self.form = QFormLayout(container)
        self.form.setSpacing(12)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # ── Display & UI ──────────────────────────────────────────────
        self._add_section("Display & UI")

        # Thumbnail Size — original had 11 choices (150 → 500)
        self.thumb_size = QComboBox()
        self.size_choices = ["150", "180", "200", "220", "250", "280", "300", "350", "400", "450", "500"]
        self.thumb_size.addItems([f"~{s}px" for s in self.size_choices])
        cur_sz = str(settings.manager.thumbnail_size)
        idx = self.size_choices.index(cur_sz) if cur_sz in self.size_choices else 4
        self.thumb_size.setCurrentIndex(idx)
        self.form.addRow("Gallery Grid Size:", self.thumb_size)

        # Thumbnail Resolution — original was a slider (150-1200)
        res_widget = QWidget()
        res_widget.setStyleSheet("background: transparent;")
        res_v = QVBoxLayout(res_widget)
        res_v.setContentsMargins(0, 0, 0, 0)
        res_v.setSpacing(4)

        res_header = QHBoxLayout()
        res_header.addWidget(QLabel("Download Quality:"))
        self.res_val_lbl = QLabel(f"{settings.manager.thumbnail_res}px")
        self.res_val_lbl.setStyleSheet(f"color: {colors.SUCCESS}; font-weight: bold;")
        res_header.addWidget(self.res_val_lbl, 0, Qt.AlignmentFlag.AlignRight)
        res_v.addLayout(res_header)

        self.res_slider = QSlider(Qt.Orientation.Horizontal)
        self.res_slider.setMinimum(150)
        self.res_slider.setMaximum(1200)
        self.res_slider.setValue(settings.manager.thumbnail_res)
        self.res_slider.valueChanged.connect(lambda v: self.res_val_lbl.setText(f"{v}px"))
        res_v.addWidget(self.res_slider)

        info_lbl = QLabel("Resolution > Size = Supersampling (Very HD but slower).")
        info_lbl.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 10px;")
        res_v.addWidget(info_lbl)

        self.form.addRow(res_widget)

        self.infinite_scroll = QCheckBox("Enable Infinite Scroll")
        self.infinite_scroll.setChecked(settings.manager.infinite_scroll)
        self.form.addRow("", self.infinite_scroll)

        self.masonry_mode = QCheckBox("Masonry Layout (Variable Height)")
        self.masonry_mode.setChecked(settings.manager.masonry_mode)
        self.form.addRow("", self.masonry_mode)

        self.reduced_motion = QCheckBox("Reduced Motion (Fewer Animations)")
        self.reduced_motion.setChecked(settings.manager.reduced_motion)
        self.form.addRow("", self.reduced_motion)

        # ── Media & Playback ──────────────────────────────────────────
        self._add_section("Media & Playback")

        self.video_engine = QComboBox()
        self.video_engine.addItems(["Qt (Built-in)", "VLC (Internal)", "MPV (Fast)"])
        engine_map = {"qt": 0, "vlc": 1, "mpv": 2}
        self.video_engine.setCurrentIndex(engine_map.get(settings.manager.video_engine, 0))
        self.form.addRow("Video Engine:", self.video_engine)

        self.legacy_viewer = QCheckBox("Use Legacy Viewer (Separate Window)")
        self.legacy_viewer.setChecked(settings.manager.use_legacy_viewer)
        self.form.addRow("", self.legacy_viewer)

        # ── Network & Downloads ───────────────────────────────────────
        self._add_section("Network & Downloads")

        self.concurrent_dl = QSpinBox()
        self.concurrent_dl.setRange(1, 200)
        self.concurrent_dl.setValue(settings.manager.concurrent_downloads)
        self.form.addRow("Concurrent Downloads:", self.concurrent_dl)

        self.proxy_url = QLineEdit(settings.manager.proxy_url)
        self.proxy_url.setPlaceholderText("http://user:pass@host:port")
        self.form.addRow("Proxy URL:", self.proxy_url)

        self.use_http2 = QCheckBox("Enable HTTP/2 (May cause timeouts on some sites)")
        self.use_http2.setChecked(settings.manager.use_http2)
        self.form.addRow("", self.use_http2)

        # ── Download Folders ──────────────────────────────────────────
        self._add_section("Download Folders")

        self.smart_folders = QCheckBox("Enable Smart Folders (auto-organize by tags)")
        self.smart_folders.setChecked(settings.manager.use_smart_folders)
        self.form.addRow("", self.smart_folders)

        self.artist_folder_cb = QCheckBox("Prefer artist folder over character folder")
        self.artist_folder_cb.setChecked(settings.manager.download_folder_use_artist_folder)
        self.form.addRow("", self.artist_folder_cb)

        scroll.setWidget(container)
        layout.addWidget(scroll)

        # Buttons
        btns = QHBoxLayout()
        
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setStyleSheet(f"background: {colors.BUTTON_BG}; color: {colors.TEXT_MUTED}; padding: 8px;")
        reset_btn.clicked.connect(self._reset_defaults)
        btns.addWidget(reset_btn)
        
        btns.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(f"background: {colors.BUTTON_BG}; color: {colors.TEXT_SECONDARY}; padding: 8px 15px;")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)

        save_btn = QPushButton("Save & Apply")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(f"background: {colors.ACCENT}; color: {colors.TEXT_PRIMARY}; font-weight: bold; padding: 8px 25px;")
        save_btn.clicked.connect(self._save)
        btns.addWidget(save_btn)

        layout.addLayout(btns)

    def _add_section(self, title: str):
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {colors.ACCENT}; font-weight: bold; margin-top: 10px; border-bottom: 1px solid {colors.BORDER};")
        self.form.addRow(lbl)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            anims.animate_slide_up_fade(self, duration=300, offset=20)
        except Exception:
            pass

    def _reset_defaults(self):
        self.thumb_size.setCurrentIndex(4)  # 250
        self.res_slider.setValue(720)
        self.infinite_scroll.setChecked(False)
        self.masonry_mode.setChecked(False)
        self.reduced_motion.setChecked(False)
        self.video_engine.setCurrentIndex(0)  # Qt
        self.legacy_viewer.setChecked(False)
        self.concurrent_dl.setValue(50)
        self.proxy_url.setText("")
        self.use_http2.setChecked(False)
        self.smart_folders.setChecked(False)
        self.artist_folder_cb.setChecked(False)

    def _save(self):
        # Display
        self.parent_gui  # just to keep reference
        settings.manager.thumbnail_size = int(self.size_choices[self.thumb_size.currentIndex()])
        settings.manager.thumbnail_res = self.res_slider.value()
        settings.manager.infinite_scroll = self.infinite_scroll.isChecked()
        settings.manager.masonry_mode = self.masonry_mode.isChecked()
        settings.manager.reduced_motion = self.reduced_motion.isChecked()
        
        # Media
        engines = ["qt", "vlc", "mpv"]
        settings.manager.video_engine = engines[self.video_engine.currentIndex()]
        settings.manager.use_legacy_viewer = self.legacy_viewer.isChecked()
        
        # Network
        settings.manager.concurrent_downloads = self.concurrent_dl.value()
        settings.manager.proxy_url = self.proxy_url.text().strip()
        settings.manager.use_http2 = self.use_http2.isChecked()
        
        # Download folders
        settings.manager.use_smart_folders = self.smart_folders.isChecked()
        settings.manager.download_folder_use_artist_folder = self.artist_folder_cb.isChecked()
        
        if settings.manager.save():
            # Apply immediate visual changes
            self.parent_gui.gallery.refresh_layout()
            self.parent_gui.trigger_fetch(new=True)
            self.accept()
        else:
            QMessageBox.critical(self, "Error", "Failed to save settings to disk.")

    @staticmethod
    def show_dialog(parent_gui):
        GlobalSettingsDialog(parent_gui).exec()
