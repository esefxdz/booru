from PyQt6.QtWidgets import QPushButton
from ui.browser_dialog.in_app_browser import InAppBrowser

from ui import colors

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                CLASS: SessionLoginBrowserDialog                     ║
# ║  Used when auto-login fails. Shows the site's real login page and   ║
# ║  adds a "Save & Close" button that the user clicks once they have   ║
# ║  successfully logged in.                                             ║
# ╚══════════════════════════════════════════════════════════════════════╝
class SessionLoginBrowserDialog(InAppBrowser):

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — loads the site's login URL and adds the manual     │
    # │  capture button to the toolbar                                  │
    # └──────────────────────────────────────────────────────────────────┐
    def __init__(self, url, booru_name, target_cookies, parent=None):
        super().__init__(url, f"Login — {booru_name}", parent)
        self.target_cookies = target_cookies  # List of names (e.g. ['user_id', 'pass_hash'])
        self._found = {}
        
        # Add a big "Capture Session" button to the top toolbar
        self.save_btn = QPushButton("✅  Logged in? Save & Close")
        self.save_btn.setStyleSheet(f"background: {colors.SUCCESS}; color: white; font-weight: bold; padding: 5px 15px;")
        self.save_btn.clicked.connect(self._manual_capture)
        # Find the layout and insert the button before the stretch/close btn
        self.layout().itemAt(0).layout().insertWidget(1, self.save_btn)

        # Connect the cookieAdded signal once at startup
        self.browser.page().profile().cookieStore().cookieAdded.connect(self._on_cookie_added)
        self.load_url(url)

    def _on_cookie_added(self, cookie):
        name = cookie.name().data().decode()
        if name in self.target_cookies:
            self._found[name] = cookie.value().data().decode()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _manual_capture  — triggered when the user clicks the green    │
    # │  button. Scans the current cookie jar for the specific keys     │
    # │  required by this booru's engine.                               │
    # └──────────────────────────────────────────────────────────────────┘
    def _manual_capture(self):
        # Force a refresh of the internal cookie cache
        self.browser.page().profile().cookieStore().loadAllCookies()
        # Give it a second to finish loading/processing then close
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(800, self.accept)

    def get_found_cookies(self):
        """Returns the dictionary of target cookies found during capture."""
        return self._found
