"""
ui/settings_view/section_network.py

Network & Downloads settings section: concurrent downloads, proxy, HTTP/2,
and Cloudflare bypass engine selection.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QCheckBox, QFrame, QComboBox, QDoubleSpinBox, QPushButton,
    QMessageBox
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
        from cloudflare_bypasser.session import BYPASS_METHODS, BYPASS_METHOD_LABELS, get_available_engines
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

        # ── Cloudflare Bypass Method ──────────────────────────────────
        cf_card = QFrame()
        cf_card.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.PANEL_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 12px;
            }}
        """)
        cf_v = QVBoxLayout(cf_card)
        cf_v.setContentsMargins(20, 16, 20, 16)
        cf_v.setSpacing(8)

        cf_title = QLabel("Cloudflare Bypass Engine")
        cf_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        cf_v.addWidget(cf_title)

        cf_desc = QLabel(
            "Choose which HTTP engine is used to bypass Cloudflare protection. "
            "\"Auto\" tries all available engines in order of effectiveness. "
            "Lock to a specific engine if you know what works best for your setup."
        )
        cf_desc.setWordWrap(True)
        cf_desc.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px;")
        cf_v.addWidget(cf_desc)

        self.cf_method = QComboBox()
        self.cf_method.setFixedHeight(36)
        self.cf_method.setStyleSheet(f"""
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

        # Populate the dropdown from the engine module
        available = get_available_engines()

        current_method = getattr(settings.manager, "cf_bypass_method", "auto")
        selected_index = 0

        for i, method in enumerate(BYPASS_METHODS):
            label = BYPASS_METHOD_LABELS.get(method, method)

            # Mark unavailable engines
            if method not in ("auto",) and method not in available:
                label = f"{label}  ⚠ not installed"

            self.cf_method.addItem(label, method)
            if method == current_method:
                selected_index = i

        self.cf_method.setCurrentIndex(selected_index)

        cf_v.addWidget(self.cf_method)

        # Show which engines are currently available
        avail_label = QLabel(f"Available engines: {', '.join(available)}")
        avail_label.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 11px; font-style: italic;")
        cf_v.addWidget(avail_label)

        layout.addWidget(cf_card)

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

        # ── User-Agent ────────────────────────────────────────────────
        ua_card = QFrame()
        ua_card.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.PANEL_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 12px;
            }}
        """)
        ua_v = QVBoxLayout(ua_card)
        ua_v.setContentsMargins(20, 16, 20, 16)
        ua_v.setSpacing(8)

        ua_title_layout = QHBoxLayout()
        ua_title = QLabel("Custom User-Agent")
        ua_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        ua_title_layout.addWidget(ua_title)

        ua_help_btn = QPushButton("?")
        ua_help_btn.setFixedSize(20, 20)
        ua_help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ua_help_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.BUTTON_BG};
                color: {colors.TEXT_SECONDARY};
                border-radius: 10px;
                font-weight: bold;
                font-size: 12px;
                padding: 0;
            }}
            QPushButton:hover {{
                background-color: {colors.ACCENT};
                color: {colors.TEXT_PRIMARY};
            }}
        """)
        ua_help_btn.clicked.connect(self._show_ua_guide)
        ua_title_layout.addWidget(ua_help_btn)
        ua_title_layout.addStretch()

        ua_v.addLayout(ua_title_layout)

        ua_desc = QLabel("Override the default app identifier. Leave empty to use the built-in modern browser string.")
        ua_desc.setWordWrap(True)
        ua_desc.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 12px;")
        ua_v.addWidget(ua_desc)

        self.custom_user_agent = QLineEdit(settings.manager.custom_user_agent)
        self.custom_user_agent.setPlaceholderText("Mozilla/5.0 ...")
        self.custom_user_agent.setFixedHeight(36)
        ua_v.addWidget(self.custom_user_agent)

        layout.addWidget(ua_card)

        # ── Network Limits ────────────────────────────────────────────
        limit_card = QFrame()
        limit_card.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.PANEL_BG};
                border: 1px solid {colors.BORDER};
                border-radius: 12px;
            }}
        """)
        limit_v = QVBoxLayout(limit_card)
        limit_v.setContentsMargins(20, 16, 20, 16)
        limit_v.setSpacing(8)

        limit_title_layout = QHBoxLayout()
        limit_title = QLabel("Rate Limits & Concurrency")
        limit_title.setStyleSheet(f"color: {colors.TEXT_PRIMARY}; font-weight: 700; font-size: 14px;")
        limit_title_layout.addWidget(limit_title)

        limit_help_btn = QPushButton("?")
        limit_help_btn.setFixedSize(20, 20)
        limit_help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        limit_help_btn.setStyleSheet(ua_help_btn.styleSheet())
        limit_help_btn.clicked.connect(self._show_limit_guide)
        limit_title_layout.addWidget(limit_help_btn)
        limit_title_layout.addStretch()
        limit_v.addLayout(limit_title_layout)

        cb_style = f"""
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
        """

        self.use_network_semaphore = QCheckBox("Enable Concurrent Download Throttling (Semaphore)")
        self.use_network_semaphore.setChecked(settings.manager.use_network_semaphore)
        self.use_network_semaphore.setStyleSheet(cb_style)
        limit_v.addWidget(self.use_network_semaphore)

        self.use_rate_limit = QCheckBox("Enable API Rate Limiting (Anti-Spam Delay)")
        self.use_rate_limit.setChecked(settings.manager.use_rate_limit)
        self.use_rate_limit.setStyleSheet(cb_style)
        limit_v.addWidget(self.use_rate_limit)

        delay_layout = QHBoxLayout()
        delay_label = QLabel("API Rate Limit Delay (seconds):")
        delay_label.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-size: 13px;")
        delay_layout.addWidget(delay_label)

        self.rate_limit_delay = QDoubleSpinBox()
        self.rate_limit_delay.setRange(0.0, 5.0)
        self.rate_limit_delay.setSingleStep(0.1)
        self.rate_limit_delay.setValue(settings.manager.rate_limit_delay)
        self.rate_limit_delay.setFixedHeight(36)
        self.rate_limit_delay.setStyleSheet(f"""
            QDoubleSpinBox {{
                background: {colors.INPUT_BG};
                color: {colors.TEXT_PRIMARY};
                border: 1px solid {colors.BUTTON_BG};
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 14px;
            }}
        """)
        delay_layout.addWidget(self.rate_limit_delay)
        delay_layout.addStretch()
        limit_v.addLayout(delay_layout)

        layout.addWidget(limit_card)

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

    def _show_ua_guide(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("What is a User-Agent?")
        msg.setText(
            "<b>What is a User-Agent?</b><br><br>"
            "Every time an app connects to a website, it sends a 'User-Agent' string that identifies it "
            "(e.g., 'Chrome on Windows' or 'Firefox on Mac').<br><br>"
            "<b>Why change it?</b><br>"
            "If BooruBrowser is temporarily blocked by Cloudflare or a booru server because it detected a scraper, "
            "you can escape the block by changing your User-Agent to match your actual real-world browser.<br><br>"
            "<b>How to get your own:</b><br>"
            "1. Open your main web browser (Chrome, Firefox, etc.)<br>"
            "2. Go to <b>whatismybrowser.com/detect/what-is-my-user-agent</b><br>"
            "3. Copy the string it gives you and paste it into the setting box here."
        )
        msg.setStyleSheet(f"background-color: {colors.MAIN_BG}; color: {colors.TEXT_PRIMARY};")
        msg.exec()

    def _show_limit_guide(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Rate Limits & Concurrency")
        msg.setText(
            "<b>What is the difference?</b><br><br>"
            "<b>Concurrent Download Throttling:</b> limits how many images download at the exact same time. "
            "If set to 50, only 50 images download at once. However, if the server is fast, the app might finish "
            "50 and immediately start another 50, creating a huge burst of traffic.<br><br>"
            "<b>API Rate Limiting:</b> introduces a forced delay (e.g., 0.25s) between requests. "
            "This stops the 'burst' traffic and keeps your IP address from getting temporarily banned "
            "for acting like a DDoS bot.<br><br>"
            "<i>Note: Disabling these limits may speed up the app, but heavily increases your risk of being IP banned by booru admins.</i>"
        )
        msg.setStyleSheet(f"background-color: {colors.MAIN_BG}; color: {colors.TEXT_PRIMARY};")
        msg.exec()

    def apply(self):
        settings.manager.concurrent_downloads = self.concurrent_dl.value()
        settings.manager.proxy_url = self.proxy_url.text().strip()
        settings.manager.use_http2 = self.use_http2.isChecked()
        settings.manager.cf_bypass_method = self.cf_method.currentData() or "auto"
        settings.manager.custom_user_agent = self.custom_user_agent.text().strip()
        settings.manager.use_network_semaphore = self.use_network_semaphore.isChecked()
        settings.manager.use_rate_limit = self.use_rate_limit.isChecked()
        settings.manager.rate_limit_delay = self.rate_limit_delay.value()

    def reset(self):
        self.concurrent_dl.setValue(50)
        self.proxy_url.setText("")
        self.use_http2.setChecked(False)
        self.custom_user_agent.setText("")
        self.use_network_semaphore.setChecked(True)
        self.use_rate_limit.setChecked(True)
        self.rate_limit_delay.setValue(0.25)
        # Reset bypass method to auto
        for i in range(self.cf_method.count()):
            if self.cf_method.itemData(i) == "auto":
                self.cf_method.setCurrentIndex(i)
                break

    def load(self):
        self.concurrent_dl.setValue(settings.manager.concurrent_downloads)
        self.proxy_url.setText(settings.manager.proxy_url)
        self.use_http2.setChecked(settings.manager.use_http2)
        self.custom_user_agent.setText(settings.manager.custom_user_agent)
        self.use_network_semaphore.setChecked(settings.manager.use_network_semaphore)
        self.use_rate_limit.setChecked(settings.manager.use_rate_limit)
        self.rate_limit_delay.setValue(settings.manager.rate_limit_delay)
        
        current_method = getattr(settings.manager, "cf_bypass_method", "auto")
        for i in range(self.cf_method.count()):
            if self.cf_method.itemData(i) == current_method:
                self.cf_method.setCurrentIndex(i)
                break
