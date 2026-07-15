"""
ui/browser_dialog/auto_solver.py — Hidden Cloudflare auto-solver.

Uses an off-screen QWebEnginePage (no visible browser window) to load a
Cloudflare-protected URL and wait for the challenge to solve itself.
JS challenges and Turnstile widgets often auto-resolve without user
interaction — this captures that case silently.

On success, cookies + User-Agent are persisted via cloudflare_bypasser.store
and the ``solved`` signal fires.  If the challenge doesn't auto-solve within
the timeout, ``timed_out`` fires — the caller should then show the manual
CloudflareBrowserDialog for the user to solve the CAPTCHA.
"""

from __future__ import annotations

from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings
from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

_DEFAULT_TIMEOUT_MS = 30_000   # how long to wait for auto-solve
_POLL_INTERVAL_MS = 500        # JS cookie poll interval
_KILL_TIMEOUT_MS = 120_000     # hard kill (prevents zombie pages)


class CloudflareAutoSolver(QObject):
    """
    Attempt to solve a Cloudflare challenge without user interaction.

    Usage::

        solver = CloudflareAutoSolver("danbooru", "https://danbooru.donmai.us", parent)
        solver.solved.connect(lambda cookies, ua: print("solved!", cookies))
        solver.timed_out.connect(lambda: print("need manual CAPTCHA"))
        solver.start(timeout_ms=30_000)

    On ``solved``, cookies are already persisted via ``store.save_bypass()``.
    """

    solved = pyqtSignal(dict, str)   # cookies: dict, user_agent: str
    timed_out = pyqtSignal()

    def __init__(self, booru_name: str, url: str, parent: QObject | None = None):
        super().__init__(parent)
        self._booru_name = booru_name
        self._url = url
        self._captured = False
        self._found_cookies: dict[str, str] = {}

        # ── Per-booru isolated profile (matches CloudflareBrowserDialog) ──
        self._profile = QWebEngineProfile(f"cf_auto_{booru_name}", self)
        self._profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        self._profile.setHttpUserAgent(_CHROME_UA)
        self._profile.cookieStore().cookieAdded.connect(self._on_cookie_added)

        # ── Off-screen page (no QWebEngineView) ────────────────────────
        self._page = QWebEnginePage(self._profile, None)
        ws = self._page.settings()
        ws.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        ws.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        ws.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        self._page.loadFinished.connect(self._on_page_loaded)

        # ── Timers ─────────────────────────────────────────────────────
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_js_cookies)

        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)

        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.setInterval(_KILL_TIMEOUT_MS)
        self._kill_timer.timeout.connect(self._cleanup)

    # ── Public API ─────────────────────────────────────────────────────

    def start(self, timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> None:
        """Begin the auto-solve attempt.  Emits ``solved`` or ``timed_out``."""
        self._timeout_timer.start(timeout_ms)
        self._kill_timer.start()
        self._page.setUrl(QUrl(self._url))

    # ── Cookie signals ─────────────────────────────────────────────────

    def _on_cookie_added(self, cookie) -> None:
        if self._captured:
            return
        name = cookie.name().data().decode()
        value = cookie.value().data().decode()
        self._found_cookies[name] = value

        if name in _CF_COOKIE_NAMES or name.startswith("cf_"):
            self._finish()

    # ── JS polling ─────────────────────────────────────────────────────

    def _poll_js_cookies(self) -> None:
        if self._captured:
            self._poll_timer.stop()
            return
        self._page.runJavaScript(
            "document.cookie",
            lambda result: self._check_js_cookies(result or ""),
        )

    def _check_js_cookies(self, cookie_str: str) -> None:
        if self._captured:
            self._poll_timer.stop()
            return
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                self._found_cookies[k.strip()] = v.strip()

        cf_keys = [k for k in self._found_cookies if k.startswith("cf_") or k == "__cf_bm"]
        if cf_keys:
            self._finish()

    # ── Page lifecycle ─────────────────────────────────────────────────

    def _on_page_loaded(self, ok: bool) -> None:
        if self._captured or not ok:
            return
        if not self._poll_timer.isActive():
            self._poll_timer.start()
        # Some cookies arrive during redirects — scan the store after a delay
        QTimer.singleShot(2000, self._scan_cookie_store)

    def _scan_cookie_store(self) -> None:
        if self._captured:
            return
        self._profile.cookieStore().loadAllCookies()
        self._page.runJavaScript(
            "document.cookie",
            lambda result: self._check_js_cookies(result or ""),
        )

    # ── Finish / timeout ───────────────────────────────────────────────

    def _finish(self) -> None:
        if self._captured:
            return
        self._captured = True
        self._cleanup()

        from cloudflare_bypasser import store, invalidate_session
        cookies = dict(self._found_cookies)
        ua = self._profile.httpUserAgent() or _CHROME_UA
        store.save_bypass(self._booru_name, cookies, ua)
        invalidate_session(self._booru_name)
        self.solved.emit(cookies, ua)

    def _on_timeout(self) -> None:
        if self._captured:
            return
        self._captured = True
        self._cleanup()
        self.timed_out.emit()

    def _cleanup(self) -> None:
        self._poll_timer.stop()
        self._timeout_timer.stop()
        self._kill_timer.stop()
        try:
            self._page.deleteLater()
        except Exception:
            pass
        try:
            self._profile.deleteLater()
        except Exception:
            pass


# ── Known Cloudflare cookie names ─────────────────────────────────────
_CF_COOKIE_NAMES = frozenset({
    "cf_clearance", "__cf_bm", "cf_chl_rc_m", "cf_chl_rc_i",
    "cf_ob_info", "cf_use_ob", "cf_chl_2", "cf_chl_3",
    "cf_chl_prog", "cf_chl_seq",
})
