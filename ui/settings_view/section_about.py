"""
ui/settings_view/section_about.py

About & Maintenance section: version info, cache clearing, reset to defaults.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QFrame
)
from PyQt6.QtCore import Qt, QTimer
from ui import settings_view as settings
from ui import colors
import thumb_cache


class AboutSection(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        # ── App Info ──────────────────────────────────────────────────
        info_card = QFrame()
        info_card.setStyleSheet(f"QFrame {{ background-color: {colors.PANEL_BG}; border: 1px solid {colors.BORDER}; border-radius: 12px; }}")
        info_v = QVBoxLayout(info_card)
        info_v.setContentsMargins(20, 16, 20, 16)
        info_v.setSpacing(8)

        app_title = QLabel(f"Booru Browser  v{settings.VERSION}")
        app_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 800; font-size: 18px;")
        info_v.addWidget(app_title)

        subtitle = QLabel("A modern desktop client for browsing image boards.")
        subtitle.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 13px;")
        info_v.addWidget(subtitle)

        layout.addWidget(info_card)

        # ── Cache Management ──────────────────────────────────────────
        cache_card = QFrame()
        cache_card.setStyleSheet(f"QFrame {{ background-color: {colors.PANEL_BG}; border: 1px solid {colors.BORDER}; border-radius: 12px; }}")
        cache_v = QVBoxLayout(cache_card)
        cache_v.setContentsMargins(20, 16, 20, 16)
        cache_v.setSpacing(12)

        cache_title = QLabel("Cache Management")
        cache_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        cache_v.addWidget(cache_title)

        cache_desc = QLabel("Clear cached thumbnails to free disk space. Thumbnails will be re-downloaded as needed.")
        cache_desc.setWordWrap(True)
        cache_desc.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px;")
        cache_v.addWidget(cache_desc)

        self.clear_cache_btn = QPushButton("🗑  Clear Thumbnail Cache")
        self.clear_cache_btn.setFixedHeight(40)
        self.clear_cache_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_cache_btn.setStyleSheet(f"""
            QPushButton {{ background: {colors.BUTTON_BG}; color: {colors.TEXT_SECONDARY}; border: 1px solid {colors.BORDER}; border-radius: 8px; font-weight: 600; }}
            QPushButton:hover {{ background: {colors.BUTTON_HOVER}; border-color: {colors.ACCENT}; }}
        """)
        self.clear_cache_btn.clicked.connect(self._clear_cache)
        cache_v.addWidget(self.clear_cache_btn)

        self.cache_status = QLabel("")
        self.cache_status.setStyleSheet(f"color: {colors.SUCCESS}; font-weight: bold; font-size: 12px;")
        self.cache_status.hide()
        cache_v.addWidget(self.cache_status)

        layout.addWidget(cache_card)

        # ── Danger Zone ───────────────────────────────────────────────
        danger_card = QFrame()
        danger_card.setStyleSheet(f"QFrame {{ background-color: {colors.PANEL_BG}; border: 1px solid {colors.DANGER}; border-radius: 12px; }}")
        danger_v = QVBoxLayout(danger_card)
        danger_v.setContentsMargins(20, 16, 20, 16)
        danger_v.setSpacing(12)

        danger_title = QLabel("⚠  Danger Zone")
        danger_title.setStyleSheet(f"color: {colors.DANGER}; font-weight: 700; font-size: 14px;")
        danger_v.addWidget(danger_title)

        danger_desc = QLabel("Resetting will revert ALL settings to their original defaults. This cannot be undone.")
        danger_desc.setWordWrap(True)
        danger_desc.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px;")
        danger_v.addWidget(danger_desc)

        self.reset_btn = QPushButton("Reset All Settings to Defaults")
        self.reset_btn.setFixedHeight(40)
        self.reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {colors.DANGER}; border: 1px solid {colors.DANGER}; border-radius: 8px; font-weight: 600; }}
            QPushButton:hover {{ background: {colors.DANGER}; color: {colors.TEXT_PRIMARY}; }}
        """)
        danger_v.addWidget(self.reset_btn)

        layout.addWidget(danger_card)
        layout.addStretch()

    def _clear_cache(self):
        try:
            # Grab stats before clearing so we can show how much was freed
            pre = thumb_cache.stats()
            thumb_cache.clear()

            freed_mb = (pre["l1_bytes"] + pre["l2_bytes"]) / (1024 * 1024)
            self.cache_status.setText(
                f"Cache cleared  ({pre['l1_entries'] + pre['l2_entries']} entries, "
                f"{freed_mb:.1f} MB freed)"
            )
            self.cache_status.setStyleSheet(
                f"color: {colors.SUCCESS}; font-weight: bold; font-size: 12px;"
            )
            self.cache_status.show()
            QTimer.singleShot(5000, self.cache_status.hide)

        except Exception as e:
            self.cache_status.setText(f"Error: {e}")
            self.cache_status.setStyleSheet(
                f"color: {colors.DANGER}; font-weight: bold; font-size: 12px;"
            )
            self.cache_status.show()

    def apply(self):
        pass  # About section has no persistent settings

    def reset(self):
        pass  # Handled by the parent via reset_btn signal
