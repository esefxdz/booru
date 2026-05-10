"""
ui/settings_view/section_network.py

Network & Downloads settings section: concurrent downloads, proxy, HTTP/2.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QCheckBox, QFrame
)
from PyQt6.QtCore import Qt
from ui import settings_view as settings
from ui import colors


class NetworkSection(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        # ── Concurrent Downloads ──────────────────────────────────────
        dl_card = QFrame()
        dl_card.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.PANEL_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 12px;
            }}
        """)
        dl_v = QVBoxLayout(dl_card)
        dl_v.setContentsMargins(20, 16, 20, 16)
        dl_v.setSpacing(8)

        title = QLabel("Concurrent Downloads")
        title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        dl_v.addWidget(title)

        desc = QLabel("Maximum simultaneous download connections. Higher = faster but may trigger rate limits.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px;")
        dl_v.addWidget(desc)

        self.concurrent_dl = QSpinBox()
        self.concurrent_dl.setRange(1, 200)
        self.concurrent_dl.setValue(settings.manager.concurrent_downloads)
        self.concurrent_dl.setFixedHeight(36)
        self.concurrent_dl.setStyleSheet(f"""
            QSpinBox {{
                background: {colors.INPUT_BG};
                color: {colors.TEXT_PRIMARY};
                border: 1px solid {colors.BUTTON_BG};
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 14px;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                background: {colors.BUTTON_BG};
                border: none;
                width: 20px;
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background: {colors.BUTTON_HOVER};
            }}
        """)
        dl_v.addWidget(self.concurrent_dl)

        layout.addWidget(dl_card)

        # ── Proxy ─────────────────────────────────────────────────────
        proxy_card = QFrame()
        proxy_card.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.PANEL_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 12px;
            }}
        """)
        proxy_v = QVBoxLayout(proxy_card)
        proxy_v.setContentsMargins(20, 16, 20, 16)
        proxy_v.setSpacing(8)

        proxy_title = QLabel("Proxy Configuration")
        proxy_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        proxy_v.addWidget(proxy_title)

        proxy_desc = QLabel("Route traffic through a SOCKS5/HTTP proxy. Leave empty to use direct connection.")
        proxy_desc.setWordWrap(True)
        proxy_desc.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px;")
        proxy_v.addWidget(proxy_desc)

        self.proxy_url = QLineEdit(settings.manager.proxy_url)
        self.proxy_url.setPlaceholderText("http://user:pass@host:port")
        self.proxy_url.setFixedHeight(36)
        proxy_v.addWidget(self.proxy_url)

        layout.addWidget(proxy_card)

        # ── Protocol Options ──────────────────────────────────────────
        proto_card = QFrame()
        proto_card.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.PANEL_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 12px;
            }}
        """)
        proto_v = QVBoxLayout(proto_card)
        proto_v.setContentsMargins(20, 16, 20, 16)
        proto_v.setSpacing(12)

        proto_title = QLabel("Protocol")
        proto_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        proto_v.addWidget(proto_title)

        self.use_http2 = QCheckBox("Enable HTTP/2 (May cause timeouts on some sites)")
        self.use_http2.setChecked(settings.manager.use_http2)
        self.use_http2.setStyleSheet(f"""
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
        proto_v.addWidget(self.use_http2)

        layout.addWidget(proto_card)
        layout.addStretch()

    def apply(self):
        settings.manager.concurrent_downloads = self.concurrent_dl.value()
        settings.manager.proxy_url = self.proxy_url.text().strip()
        settings.manager.use_http2 = self.use_http2.isChecked()

    def reset(self):
        self.concurrent_dl.setValue(50)
        self.proxy_url.setText("")
        self.use_http2.setChecked(False)
