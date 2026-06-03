"""
ui/settings_view/section_display.py

Display & UI settings section: thumbnail size, resolution, masonry, infinite scroll, animations.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QCheckBox, QSlider, QFrame
)
from PyQt6.QtCore import Qt
from ui import settings_view as settings
from ui import colors


class DisplaySection(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        # ── Thumbnail Size ────────────────────────────────────────────
        size_card = self._card("Gallery Grid Size")
        size_v = QVBoxLayout(size_card)
        size_v.setContentsMargins(20, 16, 20, 16)
        size_v.setSpacing(8)

        size_title = QLabel("Gallery Grid Size")
        size_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        size_v.addWidget(size_title)

        desc = QLabel("Controls how large each thumbnail appears in the gallery grid.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px;")
        size_v.addWidget(desc)

        self.thumb_size = QComboBox()
        self.size_choices = ["150", "180", "200", "220", "250", "280", "300", "350", "400", "450", "500"]
        self.thumb_size.addItems([f"~{s}px" for s in self.size_choices])
        cur_sz = str(settings.manager.thumbnail_size)
        idx = self.size_choices.index(cur_sz) if cur_sz in self.size_choices else 4
        self.thumb_size.setCurrentIndex(idx)
        self.thumb_size.setFixedHeight(36)
        size_v.addWidget(self.thumb_size)

        layout.addWidget(size_card)

        # ── Thumbnail Resolution ──────────────────────────────────────
        res_card = self._card("Download Quality")
        res_v = QVBoxLayout(res_card)
        res_v.setContentsMargins(20, 16, 20, 16)
        res_v.setSpacing(8)

        res_title_row = QHBoxLayout()
        res_title = QLabel("Download Quality (Resolution)")
        res_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        res_title_row.addWidget(res_title)

        self.res_val_lbl = QLabel(f"{settings.manager.thumbnail_res}px")
        self.res_val_lbl.setStyleSheet(f"color: {colors.SUCCESS}; font-weight: bold; font-size: 14px;")
        res_title_row.addWidget(self.res_val_lbl, 0, Qt.AlignmentFlag.AlignRight)
        res_v.addLayout(res_title_row)

        self.res_slider = QSlider(Qt.Orientation.Horizontal)
        self.res_slider.setMinimum(150)
        self.res_slider.setMaximum(1200)
        self.res_slider.setValue(settings.manager.thumbnail_res)
        self.res_slider.valueChanged.connect(lambda v: self.res_val_lbl.setText(f"{v}px"))
        self.res_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: {colors.BUTTON_BG};
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {colors.ACCENT};
                width: 18px;
                height: 18px;
                margin: -6px 0;
                border-radius: 9px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {colors.ACCENT_HOVER};
            }}
            QSlider::sub-page:horizontal {{
                background: {colors.ACCENT};
                border-radius: 3px;
            }}
        """)
        res_v.addWidget(self.res_slider)

        info = QLabel("Resolution > Size = Supersampling (Very HD but slower).")
        info.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 11px;")
        res_v.addWidget(info)

        layout.addWidget(res_card)

        # ── Layout Options ────────────────────────────────────────────
        layout_card = self._card("Layout")
        layout_v = QVBoxLayout(layout_card)
        layout_v.setContentsMargins(20, 16, 20, 16)
        layout_v.setSpacing(12)

        layout_title = QLabel("Layout Options")
        layout_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        layout_v.addWidget(layout_title)

        self.infinite_scroll = self._checkbox("Enable Infinite Scroll",
            "Automatically load more posts as you scroll down.",
            settings.manager.infinite_scroll)
        layout_v.addWidget(self.infinite_scroll)

        self.masonry_mode = self._checkbox("Masonry Layout",
            "Variable-height tiles that preserve each image's aspect ratio.",
            settings.manager.masonry_mode)
        layout_v.addWidget(self.masonry_mode)

        self.reduced_motion = self._checkbox("Reduced Motion",
            "Disables most animations for accessibility or performance.",
            settings.manager.reduced_motion)
        layout_v.addWidget(self.reduced_motion)

        layout.addWidget(layout_card)
        layout.addStretch()

    def apply(self):
        """Write values back to settings.manager."""
        settings.manager.thumbnail_size = int(self.size_choices[self.thumb_size.currentIndex()])
        settings.manager.thumbnail_res = self.res_slider.value()
        settings.manager.infinite_scroll = self.infinite_scroll.isChecked()
        settings.manager.masonry_mode = self.masonry_mode.isChecked()
        settings.manager.reduced_motion = self.reduced_motion.isChecked()

    def reset(self):
        """Reset to defaults."""
        self.thumb_size.setCurrentIndex(4)  # 250
        self.res_slider.setValue(720)
        self.infinite_scroll.setChecked(False)
        self.masonry_mode.setChecked(False)
        self.reduced_motion.setChecked(False)

    def load(self):
        """Load current values from settings.manager to refresh stale UI state."""
        cur_sz = str(settings.manager.thumbnail_size)
        idx = self.size_choices.index(cur_sz) if cur_sz in self.size_choices else 4
        self.thumb_size.setCurrentIndex(idx)
        self.res_slider.setValue(settings.manager.thumbnail_res)
        self.infinite_scroll.setChecked(settings.manager.infinite_scroll)
        self.masonry_mode.setChecked(settings.manager.masonry_mode)
        self.reduced_motion.setChecked(settings.manager.reduced_motion)

    # ── Helpers ───────────────────────────────────────────────────
    def _card(self, _name):
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.PANEL_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 12px;
            }}
        """)
        return card

    def _checkbox(self, label, description, checked):
        w = QCheckBox(label)
        w.setChecked(checked)
        w.setStyleSheet(f"""
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
        w.setToolTip(description)
        return w
