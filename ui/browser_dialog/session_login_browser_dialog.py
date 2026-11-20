from PyQt6.QtWidgets import QPushButton
from PyQt6.QtCore import QTimer

from ui.browser_dialog.in_app_browser import InAppBrowser
from ui.style import colors


class SessionLoginBrowserDialog(InAppBrowser):

    def __init__(self, url, booru_name, target_cookies, parent=None):
        super().__init__(url, f"Login — {booru_name}", parent)
        self.target_cookies = target_cookies  # List of names (e.g. ['user_id', 'pass_hash'])
        self._found = {}
        self._site_url = url  # only accept cookies issued for this site

        self.save_btn = QPushButton("✅  Logged in? Save & Close")
        self.save_btn.setStyleSheet(f"background: {colors.SUCCESS}; color: white; font-weight: bold; padding: 5px 15px;")
        self.save_btn.clicked.connect(self._manual_capture)
        toolbar_layout = self.layout().itemAt(0).widget().layout()
        toolbar_layout.insertWidget(1, self.save_btn)

        self._profile.cookieStore().cookieAdded.connect(self._on_cookie_added)
        self.load_url(url)

    def _on_cookie_added(self, cookie):
        name = cookie.name().data().decode()
        if name not in self.target_cookies:
            return
        # Generic names like PHPSESSID are set by ads/analytics frames too.
        # Only keep the cookie if its domain belongs to the booru's site.
        from core.validation import same_site
        domain = cookie.domain().lstrip(".")
        if not domain or not same_site(f"https://{domain}/", self._site_url):
            return
        self._found[name] = cookie.value().data().decode()

    def _manual_capture(self):
        self._profile.cookieStore().loadAllCookies()
        QTimer.singleShot(800, self.accept)

    def get_found_cookies(self):
        return self._found
