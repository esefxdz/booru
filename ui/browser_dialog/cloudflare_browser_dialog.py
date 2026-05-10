from PyQt6.QtCore import pyqtSignal, QTimer
from ui.browser_dialog.in_app_browser import InAppBrowser

# ╔══════════════════════════════════════════════════════════════════════╗
# ║                  CLASS: CloudflareBrowserDialog                     ║
# ║  Specialised browser that listens specifically for the               ║
# ║  'cf_clearance' cookie. Once found, it automatically closes and     ║
# ║  emits the cookies back to the settings dialog.                      ║
# ╚══════════════════════════════════════════════════════════════════════╝
class CloudflareBrowserDialog(InAppBrowser):
    # Emits a dictionary of all cookies once cf_clearance is found
    cookies_captured = pyqtSignal(dict)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — starts a recurring timer to check the cookie jar   │
    # │  every second. We have to poll because QWebEngine doesn't have  │
    # │  a "cookie changed" signal that's easy to use for this.         │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, url, booru_name, parent=None):
        super().__init__(url, f"Cloudflare Bypass — {booru_name}", parent)
        self.booru_name = booru_name
        self._captured = False
        self._found_cookies = {}
        
        # Connect to the cookie store's signal BEFORE loading
        self.browser.page().profile().cookieStore().cookieAdded.connect(self._on_cookie_added)
        self.load_url(url)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _on_cookie_added  — callback from QWebEngine when a new cookie  │
    # │  is set. Once we see 'cf_clearance', we wait briefly to capture  │
    # │  any other companion cookies then close the dialog.              │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_cookie_added(self, cookie):
        if self._captured: return
        
        name = cookie.name().data().decode()
        value = cookie.value().data().decode()
        self._found_cookies[name] = value
        
        if name == "cf_clearance":
            self._captured = True
            # Use a tiny delay so we catch any other cookies being set simultaneously
            QTimer.singleShot(500, lambda: self._finalize(self._found_cookies))

    def _finalize(self, cookies):
        self.cookies_captured.emit(cookies)
        self.accept()
