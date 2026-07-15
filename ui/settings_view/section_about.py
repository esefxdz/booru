"""
ui/settings_view/section_about.py

About & Maintenance section: version info, update check, cache clearing,
reset to defaults.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QFrame
)
from PyQt6.QtCore import Qt, QTimer
from ui import settings_view as settings
from ui import colors
import thumb_cache
import webbrowser


class AboutSection(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        self._update_url: str | None = None
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

        # ── Updates ───────────────────────────────────────────────────
        update_card = QFrame()
        update_card.setStyleSheet(f"QFrame {{ background-color: {colors.PANEL_BG}; border: 1px solid {colors.BORDER}; border-radius: 12px; }}")
        update_v = QVBoxLayout(update_card)
        update_v.setContentsMargins(20, 16, 20, 16)
        update_v.setSpacing(12)

        update_title = QLabel("Updates")
        update_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        update_v.addWidget(update_title)

        update_desc = QLabel("Check if a newer version is available on GitHub.")
        update_desc.setWordWrap(True)
        update_desc.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px;")
        update_v.addWidget(update_desc)

        self.update_btn = QPushButton("🔄  Check for Updates")
        self.update_btn.setFixedHeight(40)
        self.update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_btn.setStyleSheet(f"""
            QPushButton {{ background: {colors.BUTTON_BG}; color: {colors.TEXT_SECONDARY}; border: 1px solid {colors.BORDER}; border-radius: 8px; font-weight: 600; }}
            QPushButton:hover {{ background: {colors.BUTTON_HOVER}; border-color: {colors.ACCENT}; }}
        """)
        self.update_btn.clicked.connect(self._check_for_updates)
        update_v.addWidget(self.update_btn)

        self.update_status = QLabel("")
        self.update_status.setStyleSheet(f"color: {colors.SUCCESS}; font-weight: bold; font-size: 12px;")
        self.update_status.hide()
        update_v.addWidget(self.update_status)

        layout.addWidget(update_card)

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

    # ── Update check ────────────────────────────────────────────────

    def _check_for_updates(self):
        self.update_btn.setEnabled(False)
        self.update_btn.setText("⏳  Checking...")
        self.update_status.hide()

        from updater import Updater
        self._updater = Updater(self)
        self._updater.update_available.connect(self._on_update_available)
        self._updater.update_available.connect(
            lambda v, u, n: self._updater.deleteLater()
        )
        # If no signal within 15s, treat as up-to-date
        self._update_timeout = QTimer(self)
        self._update_timeout.setSingleShot(True)
        self._update_timeout.timeout.connect(self._on_up_to_date)
        self._update_timeout.start(15000)

        self._updater.check()

    def _on_update_available(self, new_version: str, url: str, notes: str):
        self._update_timeout.stop()
        self._update_url = url
        self.update_btn.setEnabled(True)
        self.update_btn.setText("⬇  Download Update")
        self.update_btn.clicked.disconnect()
        self.update_btn.clicked.connect(lambda: webbrowser.open(url))
        self.update_status.setText(f"v{new_version} available — click the button to download")
        self.update_status.setStyleSheet(
            f"color: {colors.SUCCESS}; font-weight: bold; font-size: 12px;"
        )
        self.update_status.show()

    def _on_up_to_date(self):
        self.update_btn.setEnabled(True)
        self.update_btn.setText("🔄  Check for Updates")
        self.update_status.setText("You're up to date!")
        self.update_status.setStyleSheet(
            f"color: {colors.SUCCESS}; font-weight: bold; font-size: 12px;"
        )
        self.update_status.show()
        QTimer.singleShot(5000, self.update_status.hide)

    # ── Cache ───────────────────────────────────────────────────────

    def _clear_cache(self):
        try:
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
        pass

    def reset(self):
        pass
