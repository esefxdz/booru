"""
ui/settings_view/section_media.py

Media & Playback settings section: video engine, legacy viewer toggle.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QComboBox, QCheckBox, QFrame
)
from ui import settings_view as settings
from ui import colors


class MediaSection(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        # ── Video Engine ──────────────────────────────────────────────
        engine_card = QFrame()
        engine_card.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.PANEL_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 12px;
            }}
        """)
        engine_v = QVBoxLayout(engine_card)
        engine_v.setContentsMargins(20, 16, 20, 16)
        engine_v.setSpacing(8)

        title = QLabel("Video Engine")
        title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        engine_v.addWidget(title)

        desc = QLabel("Choose the video playback engine. MPV is fastest but requires external libraries.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px;")
        engine_v.addWidget(desc)

        self.video_engine = QComboBox()
        self.video_engine.addItems(["Qt (Built-in)", "VLC (Internal)", "MPV (Fast)"])
        engine_map = {"qt": 0, "vlc": 1, "mpv": 2}
        self.video_engine.setCurrentIndex(engine_map.get(settings.manager.video_engine, 0))
        self.video_engine.setFixedHeight(36)
        engine_v.addWidget(self.video_engine)

        layout.addWidget(engine_card)

        # ── Viewer Mode ───────────────────────────────────────────────
        viewer_card = QFrame()
        viewer_card.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.PANEL_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 12px;
            }}
        """)
        viewer_v = QVBoxLayout(viewer_card)
        viewer_v.setContentsMargins(20, 16, 20, 16)
        viewer_v.setSpacing(12)

        viewer_title = QLabel("Viewer Mode")
        viewer_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        viewer_v.addWidget(viewer_title)

        self.legacy_viewer = QCheckBox("Use Legacy Viewer (Separate Window)")
        self.legacy_viewer.setChecked(settings.manager.use_legacy_viewer)
        self.legacy_viewer.setStyleSheet(f"""
            QCheckBox {{
                color: {colors.TEXT_SECONDARY};
                font-size: 13px;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid {colors.BUTTON_HOVER};
                border-radius: 4px;
                background: {colors.INPUT_BG};
            }}
            QCheckBox::indicator:checked {{
                background: {colors.ACCENT};
                border-color: {colors.ACCENT};
            }}
        """)
        self.legacy_viewer.setToolTip("Opens images in a separate window instead of the overlay.")
        viewer_v.addWidget(self.legacy_viewer)

        layout.addWidget(viewer_card)
        layout.addStretch()

    def apply(self):
        engines = ["qt", "vlc", "mpv"]
        settings.manager.video_engine = engines[self.video_engine.currentIndex()]
        settings.manager.use_legacy_viewer = self.legacy_viewer.isChecked()

    def reset(self):
        self.video_engine.setCurrentIndex(0)
        self.legacy_viewer.setChecked(False)

    def load(self):
        engine_map = {"qt": 0, "vlc": 1, "mpv": 2}
        self.video_engine.setCurrentIndex(engine_map.get(settings.manager.video_engine, 0))
        self.legacy_viewer.setChecked(settings.manager.use_legacy_viewer)
