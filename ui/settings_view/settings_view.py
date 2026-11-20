"""Full-page settings widget with section navigation on the left."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QStackedWidget, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QCursor

from core import settings
from ui.style import colors
from ui.style.icons import Icons
import ui.animations as anims
from ui.settings_view.section_display import DisplaySection
from ui.settings_view.section_media import MediaSection
from ui.settings_view.section_network import NetworkSection
from ui.settings_view.section_downloads import DownloadsSection
from ui.settings_view.section_about import AboutSection


class SettingsView(QWidget):

    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setStyleSheet(f"background-color: {colors.MAIN_BG}; color: {colors.TEXT_SECONDARY};")

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 40)
        root.setSpacing(24)

        self._build_header(root)

        body = QHBoxLayout()
        body.setSpacing(24)
        root.addLayout(body, 1)

        self._nav_btns = []
        nav_widget = QWidget()
        nav_widget.setFixedWidth(200)
        nav_widget.setStyleSheet("background: transparent;")
        nav_v = QVBoxLayout(nav_widget)
        nav_v.setContentsMargins(0, 0, 0, 0)
        nav_v.setSpacing(4)

        self._add_nav("Display & UI",    "settings", nav_v, 0)
        self._add_nav("Media",           "explore",  nav_v, 1)
        self._add_nav("Network",         "download", nav_v, 2)
        self._add_nav("Downloads",       "download", nav_v, 3)
        self._add_nav("About",           "forum",    nav_v, 4)
        nav_v.addStretch()

        body.addWidget(nav_widget)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent;")

        self.sec_display   = DisplaySection()
        self.sec_media     = MediaSection()
        self.sec_network   = NetworkSection()
        self.sec_downloads = DownloadsSection()
        self.sec_about     = AboutSection()

        self.sections = [
            self.sec_display, self.sec_media, self.sec_network,
            self.sec_downloads, self.sec_about
        ]

        for sec in self.sections:
            self.stack.addWidget(sec)

        self.sec_about.reset_btn.clicked.connect(self._reset_all)

        self.scroll.setWidget(self.stack)
        body.addWidget(self.scroll, 1)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color: {colors.SUCCESS}; font-weight: bold;")
        self.status_lbl.hide()
        root.addWidget(self.status_lbl)

        self._select_nav(0)

    def _build_header(self, parent_layout):
        header = QHBoxLayout()
        title_v = QVBoxLayout()

        title = QLabel("Settings")
        title.setStyleSheet(f"font-size: 32px; font-weight: 800; color: {colors.TEXT_PRIMARY};")
        title_v.addWidget(title)

        subtitle = QLabel("Configure your Booru Browser experience.")
        subtitle.setStyleSheet(f"font-size: 14px; color: {colors.TEXT_MUTED};")
        title_v.addWidget(subtitle)

        header.addLayout(title_v)
        header.addStretch()

        self.save_btn = QPushButton("💾 Save Changes")
        self.save_btn.setFixedSize(160, 44)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.ACCENT}; color: {colors.TEXT_PRIMARY};
                font-size: 14px; font-weight: bold; border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {colors.ACCENT_HOVER}; }}
        """)
        self.save_btn.clicked.connect(self._save)
        header.addWidget(self.save_btn)

        parent_layout.addLayout(header)

    def _add_nav(self, label, icon_name, parent_layout, index):
        btn = QPushButton(f"  {label}")
        btn.setFixedHeight(38)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setIcon(Icons.get(icon_name, colors.TEXT_MUTED))
        btn.setIconSize(QSize(18, 18))
        btn.clicked.connect(lambda: self._select_nav(index))
        parent_layout.addWidget(btn)
        self._nav_btns.append(btn)

    def _select_nav(self, index):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_btns):
            if i == index:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {colors.ACCENT};
                        color: {colors.TEXT_PRIMARY};
                        text-align: left;
                        padding: 0 12px;
                        border-radius: 6px;
                        font-weight: 600;
                        font-size: 13px;
                        border: none;
                    }}
                """)
                btn.setIcon(Icons.get(self._icon_for(i), colors.TEXT_PRIMARY))
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        color: {colors.TEXT_MUTED};
                        text-align: left;
                        padding: 0 12px;
                        border-radius: 6px;
                        font-weight: 600;
                        font-size: 13px;
                        border: none;
                    }}
                    QPushButton:hover {{
                        background-color: {colors.BUTTON_BG};
                        color: {colors.TEXT_SECONDARY};
                    }}
                """)
                btn.setIcon(Icons.get(self._icon_for(i), colors.TEXT_MUTED))

    def _icon_for(self, index):
        icons = ["settings", "explore", "download", "download", "forum"]
        return icons[index] if index < len(icons) else "settings"

    def load_settings(self):
        self.status_lbl.hide()
        for sec in self.sections:
            if hasattr(sec, "load"):
                sec.load()
        self._select_nav(0)

    def _save(self):
        for sec in self.sections:
            sec.apply()

        if settings.manager.save():
            self.status_lbl.setText("✔ Settings saved successfully")
            self.status_lbl.setStyleSheet(f"color: {colors.SUCCESS}; font-weight: bold;")
            self.status_lbl.show()
            QTimer.singleShot(3000, self.status_lbl.hide)

            try:
                anims.animate_button_press(self.save_btn)
            except Exception:
                pass

            self.main_app.gallery.refresh_layout()
        else:
            self.status_lbl.setText("✕ Failed to save settings to disk")
            self.status_lbl.setStyleSheet(f"color: {colors.DANGER}; font-weight: bold;")
            self.status_lbl.show()

    def _reset_all(self):
        for sec in self.sections:
            sec.reset()
        self._save()
