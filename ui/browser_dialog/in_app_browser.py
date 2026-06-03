###########################################################################################
# ui/browser_dialog/in_app_browser.py — Base embedded browser widget.
#
# Provides a QWebEngineView with a toolbar (URL label, progress bar, close
# button). Used as the base class for Cloudflare bypass and session login
# dialogs.
###########################################################################################

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QPushButton, QHBoxLayout, QLabel,
    QProgressBar, QWidget,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
from PyQt6.QtCore import Qt, QUrl

from ui import colors


# ╔══════════════════════════════════════════════════════════════════════╗
# ║                      CLASS: InAppBrowser                             ║
# ║  A simple embedded browser widget with a loading bar and status      ║
# ║  text. Used as the base for Cloudflare bypass and login dialogs.    ║
# ╚══════════════════════════════════════════════════════════════════════╝
class InAppBrowser(QDialog):

    def __init__(self, url, title="Browser", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1100, 750)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setStyleSheet(f"QDialog {{ background-color: {colors.PANEL_BG}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Toolbar ────────────────────────────────────────────────────
        toolbar_widget = QWidget()
        toolbar_widget.setStyleSheet(
            f"background-color: {colors.MAIN_BG}; "
            f"border-bottom: 1px solid {colors.BORDER};"
        )
        toolbar_widget.setFixedHeight(40)
        toolbar = QHBoxLayout(toolbar_widget)
        toolbar.setContentsMargins(15, 0, 15, 0)

        self.url_lbl = QLabel(url if isinstance(url, str) else url.toString())
        self.url_lbl.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 11px;")
        toolbar.addWidget(self.url_lbl)

        toolbar.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.BUTTON_BG};
                color: {colors.TEXT_SECONDARY};
                border-radius: 4px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{ background-color: {colors.BUTTON_HOVER}; }}
        """)
        close_btn.clicked.connect(self.reject)
        toolbar.addWidget(close_btn)

        layout.addWidget(toolbar_widget)

        # ── Progress Bar ───────────────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setFixedHeight(3)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(f"""
            QProgressBar {{ background: transparent; border: none; }}
            QProgressBar::chunk {{ background: {colors.ACCENT}; }}
        """)
        layout.addWidget(self.progress)

        # ── Configure the default profile ──────────────────────────────
        # Enable persistent cookies + real Chrome UA so CF challenges work.
        # Stored as self._profile so subclasses can access it.
        self._profile = QWebEngineProfile.defaultProfile()
        profile = self._profile
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        profile.setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        )

        # ── Web View ───────────────────────────────────────────────────
        self.browser = QWebEngineView()

        # Enable all JS/DOM features CF needs
        ws = self.browser.page().settings()
        ws.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        ws.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        ws.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

        self.browser.loadProgress.connect(self.progress.setValue)
        self.browser.loadFinished.connect(lambda ok: self.progress.hide())
        self.browser.loadStarted.connect(lambda: self.progress.show())
        self.browser.urlChanged.connect(
            lambda qurl: self.url_lbl.setText(qurl.toString())
        )

        layout.addWidget(self.browser)

    def load_url(self, url):
        """Loads a URL into the embedded browser. Accepts str or QUrl."""
        if url is None:
            return
        # Normalize to str first — callers may pass either type
        if not isinstance(url, str):
            url = url.toString()
        if not url.startswith("http"):
            url = "https://" + url
        self.url_lbl.setText(url)
        self.browser.setUrl(QUrl(url))

    def get_user_agent(self):
        """Returns the current browser User-Agent string."""
        return self.browser.page().profile().httpUserAgent()
