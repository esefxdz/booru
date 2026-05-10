from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QHBoxLayout, QLabel, QProgressBar, QWidget
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile
from PyQt6.QtCore import Qt, pyqtSignal, QUrl

from ui import colors

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                      CLASS: InAppBrowser                             ║
# ║  A simple embedded browser widget with a loading bar and status      ║
# ║  text. Used as the base for Cloudflare bypass and login dialogs.    ║
# ╚══════════════════════════════════════════════════════════════════════╝
class InAppBrowser(QDialog):
    # Base class doesn't emit much, but subclasses use the page signals
    
    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — sets up a QWebEngineView and a standard browser     │
    # │  UI (URL label, progress bar, close button)                     │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, url, title="Browser", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1000, 700)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setStyleSheet(f"QDialog {{ background-color: {colors.PANEL_BG}; }}")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # ── Toolbar ────────────────────────────────────────────────────
        toolbar_widget = QWidget()
        toolbar_widget.setStyleSheet(f"background-color: {colors.MAIN_BG}; border-bottom: 1px solid {colors.BORDER};")
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
        self.progress.setFixedHeight(2)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(f"""
            QProgressBar {{ background: transparent; border: none; }} 
            QProgressBar::chunk {{ background: {colors.ACCENT}; }}
        """)
        layout.addWidget(self.progress)
        
        # ── Web View ───────────────────────────────────────────────────
        self.browser = QWebEngineView()
        self.browser.loadProgress.connect(self.progress.setValue)
        self.browser.loadFinished.connect(lambda: self.progress.hide())
        self.browser.loadStarted.connect(lambda: self.progress.show())
        
        layout.addWidget(self.browser)

    def load_url(self, url):
        """Loads a URL into the embedded browser."""
        if isinstance(url, str) and not url.startswith("http"):
            url = "https://" + url
        self.url_lbl.setText(url if isinstance(url, str) else url.toString())
        self.browser.setUrl(QUrl(url) if isinstance(url, str) else url)

    def get_user_agent(self):
        """Returns the current browser User-Agent string."""
        return self.browser.page().profile().httpUserAgent()
