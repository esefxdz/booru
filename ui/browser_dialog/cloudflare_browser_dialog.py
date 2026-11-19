###########################################################################################
# ui/browser_dialog/cloudflare_browser_dialog.py — Cloudflare bypass dialog.
#
# Two-engine approach:
#   Engine 1 — In-app embedded browser (interactive CAPTCHA / Turnstile)
#   Engine 2 — Manual cookie paste with UA field
#
# All engines produce (cookies, user_agent) → saved via cloudflare_bypasser.store.
###########################################################################################

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QWidget,
)
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings
from PyQt6.QtCore import pyqtSignal, QTimer, Qt

from ui.browser_dialog.in_app_browser import InAppBrowser
from ui import colors

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)


class CloudflareBrowserDialog(InAppBrowser):
    cookies_captured = pyqtSignal(dict)

    def __init__(self, url, booru_name, parent=None):
        super().__init__(url, f"Cloudflare Bypass — {booru_name}", parent)
        self.booru_name = booru_name
        self._site_url = url
        self._captured = False
        self._found_cookies = {}

        # ── Per-booru isolated profile ─────────────────────────────────
        # Using a named profile prevents cookie bleed between boorus
        # and gives each booru its own localStorage/cookie jar.
        self._cf_profile = QWebEngineProfile(f"cf_bypass_{booru_name}", self)
        self._cf_profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        self._cf_profile.setHttpUserAgent(_CHROME_UA)

        # Enable all JS/DOM features CF needs
        page = QWebEnginePage(self._cf_profile, self.browser)
        ws = page.settings()
        ws.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        ws.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        self.browser.setPage(page)

        # ── Cookie detection: signal-based ─────────────────────────────
        cookie_store = self._cf_profile.cookieStore()
        cookie_store.cookieAdded.connect(self._on_cookie_added)

        # ── Cookie detection: JS polling (catches document.cookie set by Turnstile) ──
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll_js_cookies)

        # Stop polling after 120s to avoid zombie timers
        self._poll_kill = QTimer(self)
        self._poll_kill.setSingleShot(True)
        self._poll_kill.setInterval(120_000)
        self._poll_kill.timeout.connect(self._poll_timer.stop)

        # ── Status bar ─────────────────────────────────────────────────
        self._add_status_bar()

        # ── Fallback: manual cookie paste ──────────────────────────────
        self._add_fallback_panel()

        # ── Deferred URL load ──────────────────────────────────────────
        self._start_url = url

        # Wire load events for status updates
        self.browser.loadFinished.connect(self._on_page_loaded)

    def showEvent(self, event):
        """Load the URL only after the dialog is fully visible."""
        super().showEvent(event)
        if hasattr(self, "_start_url") and self._start_url:
            # Capture the value NOW — not by reference — so the lambda
            # doesn't read None after we clear _start_url below.
            url = self._start_url
            self._start_url = None  # only load once
            QTimer.singleShot(100, lambda u=url: self.load_url(u))

    # ═══════════════════════════════════════════════════════════════════
    #  Status Bar
    # ═══════════════════════════════════════════════════════════════════

    def _add_status_bar(self):
        bar = QWidget()
        bar.setFixedHeight(36)
        bar.setStyleSheet(
            f"background-color: {colors.ACCENT}22; "
            f"border-bottom: 1px solid {colors.BORDER};"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(15, 0, 15, 0)

        self._status_lbl = QLabel(
            f"🔐 Cloudflare is blocking {self.booru_name}.  "
            "Solve the \"Verify you are human\" challenge below — "
            "this window will close automatically once unlocked."
        )
        self._status_lbl.setStyleSheet(
            f"color: {colors.TEXT_PRIMARY}; font-size: 12px; font-weight: bold;"
        )
        self._status_lbl.setWordWrap(True)
        h.addWidget(self._status_lbl)
        h.addStretch()

        # "Solved" button — manual fallback when auto-detect misses
        self._solved_btn = QPushButton("✅ Solved — Capture Cookies")
        self._solved_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._solved_btn.setStyleSheet(f"""
            QPushButton {{
                background: {colors.SUCCESS};
                color: {colors.TEXT_PRIMARY};
                padding: 6px 14px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{ background: {colors.SUCCESS}CC; }}
        """)
        self._solved_btn.clicked.connect(self._manual_capture)
        h.addWidget(self._solved_btn)

        # Insert after the progress bar (index 2 in the layout)
        self.layout().insertWidget(2, bar)

    def _set_status(self, text: str, color: str = colors.TEXT_MUTED):
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: bold;"
        )

    def _manual_capture(self):
        """User clicked 'Solved' — grab all cookies now and finalize."""
        if self._captured:
            return
        self._captured = True
        self._poll_timer.stop()
        # Dump all cookies from the store + document.cookie
        self._cf_profile.cookieStore().loadAllCookies()
        self.browser.page().runJavaScript(
            "document.cookie",
            lambda result: self._finalize_from_scan(result or "")
        )

    def _finalize_from_scan(self, js_cookies: str):
        """Merge JS cookies with store cookies and finalize."""
        if js_cookies:
            for part in js_cookies.split(";"):
                part = part.strip()
                if "=" in part:
                    k, _, v = part.partition("=")
                    self._found_cookies[k.strip()] = v.strip()
        # Load all cookies signal will fire _on_cookie_added for each,
        # but give it a moment then finalize with whatever we have.
        QTimer.singleShot(500, lambda: self._finalize(self._found_cookies))

    # ═══════════════════════════════════════════════════════════════════
    #  Engine 1 — In-App Browser (cookie detection)
    # ═══════════════════════════════════════════════════════════════════

    def _on_page_loaded(self, ok):
        """Called when a page finishes loading — start JS polling and update status."""
        if not ok or self._captured:
            return

        # Start JS polling for document.cookie (catches Turnstile)
        if not self._poll_timer.isActive():
            self._poll_timer.start()
            self._poll_kill.start()

        # Check if the page is a Cloudflare challenge
        self.browser.page().runJavaScript(
            "document.title",
            lambda title: self._check_challenge_page(title or "")
        )

        # After CF redirect, cookies may already be set.  Actively scan
        # the cookie store after a short delay (the cookieAdded signal
        # sometimes misses cookies set during HTTP redirects).
        QTimer.singleShot(2000, self._scan_cookie_store)

    def _scan_cookie_store(self):
        """Query the profile cookie store + document.cookie for any CF token."""
        if self._captured:
            return
        url = self.browser.url().toString()
        if not url.startswith("http"):
            return
        # Ask the cookie store to emit all cookies (they arrive via
        # _on_cookie_added which accumulates them into _found_cookies).
        self._cf_profile.cookieStore().loadAllCookies()
        # Also do a JS-level check immediately
        self.browser.page().runJavaScript(
            "document.cookie",
            lambda result: self._check_js_cookies(result or "")
        )

    def _check_challenge_page(self, title: str):
        if self._captured:
            return
        title_lower = title.lower()
        if "just a moment" in title_lower or "attention required" in title_lower:
            self._set_status("🔐 Challenge detected — please solve the CAPTCHA", colors.FAVORITE)
        elif "cloudflare" in title_lower:
            self._set_status("🔐 Cloudflare page — waiting for clearance…", colors.FAVORITE)
        else:
            # May already be past the challenge
            self._set_status("🌐 Page loaded — checking for clearance cookie…", colors.ACCENT)

    def _on_cookie_added(self, cookie):
        if self._captured:
            return
        # Ad/analytics frames (or another site's cf_clearance) must not end
        # up stored under this booru's name.
        from validation import same_site
        domain = cookie.domain().lstrip(".")
        if not domain or not same_site(f"https://{domain}/", self._site_url):
            return
        name = cookie.name().data().decode()
        value = cookie.value().data().decode()
        self._found_cookies[name] = value

        # Capture on any Cloudflare-related cookie
        cf_names = (
            "cf_clearance", "__cf_bm", "cf_chl_rc_m", "cf_chl_rc_i",
            "cf_ob_info", "cf_use_ob", "cf_chl_2", "cf_chl_3",
            "cf_chl_prog", "cf_chl_seq",
        )
        if name in cf_names or name.startswith("cf_"):
            self._captured = True
            self._poll_timer.stop()
            self._set_status(f"✅ Cloudflare cookie captured ({name}) — closing…", colors.SUCCESS)
            QTimer.singleShot(800, lambda: self._finalize(self._found_cookies))

    def _poll_js_cookies(self):
        """Poll document.cookie for cf_clearance (Turnstile sets it via JS)."""
        if self._captured:
            self._poll_timer.stop()
            return
        self.browser.page().runJavaScript(
            "document.cookie",
            lambda result: self._check_js_cookies(result or "")
        )

    def _check_js_cookies(self, cookie_str: str):
        if self._captured:
            self._poll_timer.stop()
            return
        cookies = {}
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                cookies[k.strip()] = v.strip()
        # Always merge found cookies
        self._found_cookies.update(cookies)
        # Trigger on any CF-related cookie
        cf_keys = [k for k in cookies if k.startswith("cf_") or k == "__cf_bm"]
        if cf_keys:
            self._captured = True
            self._poll_timer.stop()
            self._set_status(f"✅ Cloudflare cookie captured ({cf_keys[0]}) — closing…", colors.SUCCESS)
            QTimer.singleShot(800, lambda: self._finalize(self._found_cookies))

    # ═══════════════════════════════════════════════════════════════════
    #  Fallback Panel (Engine 2: Manual Paste)
    # ═══════════════════════════════════════════════════════════════════

    def _add_fallback_panel(self):
        panel = QWidget()
        panel.setStyleSheet(
            f"background-color: {colors.MAIN_BG}; "
            f"border-top: 1px solid {colors.BORDER};"
        )
        v = QVBoxLayout(panel)
        v.setContentsMargins(15, 10, 15, 10)
        v.setSpacing(6)

        # ── Header ────────────────────────────────────────────────────
        header = QLabel("Not loading? Import cookies manually or from your browser:")
        header.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 11px;")
        v.addWidget(header)

        # ── cf_clearance input ────────────────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        cf_lbl = QLabel("cf_clearance:")
        cf_lbl.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-size: 11px;")
        cf_lbl.setFixedWidth(80)
        row1.addWidget(cf_lbl)

        self._cf_input = QLineEdit()
        self._cf_input.setPlaceholderText("Paste cf_clearance value from browser DevTools…")
        self._cf_input.setStyleSheet(f"""
            QLineEdit {{
                background: {colors.INPUT_BG};
                color: {colors.TEXT_PRIMARY};
                border: 1px solid {colors.BORDER};
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 11px;
            }}
        """)
        row1.addWidget(self._cf_input, 1)
        v.addLayout(row1)

        # ── User-Agent input ──────────────────────────────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        ua_lbl = QLabel("User-Agent:")
        ua_lbl.setStyleSheet(f"color: {colors.TEXT_SECONDARY}; font-size: 11px;")
        ua_lbl.setFixedWidth(80)
        row2.addWidget(ua_lbl)

        self._ua_input = QLineEdit()
        self._ua_input.setText(_CHROME_UA)
        self._ua_input.setPlaceholderText("Leave blank to use default Chrome UA")
        self._ua_input.setStyleSheet(f"""
            QLineEdit {{
                background: {colors.INPUT_BG};
                color: {colors.TEXT_MUTED};
                border: 1px solid {colors.BORDER};
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 11px;
            }}
        """)
        row2.addWidget(self._ua_input, 1)
        v.addLayout(row2)

        # ── Warning label + buttons ───────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._warn_lbl = QLabel("")
        self._warn_lbl.setStyleSheet(f"color: {colors.FAVORITE}; font-size: 10px;")
        btn_row.addWidget(self._warn_lbl, 1)


        # Engine 2: Manual apply button
        apply_btn = QPushButton("✅ Apply & Close")
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(
            f"background: {colors.SUCCESS}; color: white; "
            f"font-weight: bold; border-radius: 4px; padding: 5px 12px; font-size: 11px;"
        )
        apply_btn.clicked.connect(self._apply_pasted)
        btn_row.addWidget(apply_btn)

        v.addLayout(btn_row)
        self.layout().addWidget(panel)

    # ═══════════════════════════════════════════════════════════════════
    #  Engine 2 — Manual Paste
    # ═══════════════════════════════════════════════════════════════════

    def _apply_pasted(self):
        cf_val = self._cf_input.text().strip()
        if not cf_val:
            self._warn_lbl.setText("⚠ Paste a cf_clearance value first.")
            return

        # Soft warning — don't block the user
        if not cf_val.startswith("v1.") and len(cf_val) < 20:
            self._warn_lbl.setText("⚠ Value doesn't look like a cf_clearance token")

        ua = self._ua_input.text().strip() or _CHROME_UA
        cookies = {"cf_clearance": cf_val}
        cookies.update(self._found_cookies)
        self._captured = True
        self._poll_timer.stop()

        from cloudflare_bypasser import store
        store.save_bypass(self.booru_name, cookies, ua)
        self._set_status("✅ Manual cookies applied — closing…", colors.SUCCESS)
        # Pass the typed UA so _finalize does not overwrite with the profile UA
        QTimer.singleShot(500, lambda u=ua: self._finalize(cookies, ua=u))

    # ═══════════════════════════════════════════════════════════════════
    #  Finalize — save and close
    # ═══════════════════════════════════════════════════════════════════

    def _finalize(self, cookies, ua=None):
        # ua=None means in-browser capture: profile UA is what CF fingerprinted.
        # When ua is provided, the calling engine already saved with the correct UA.
        if ua is None:
            ua = self._cf_profile.httpUserAgent()
            from cloudflare_bypasser import store
            store.save_bypass(self.booru_name, cookies, ua)
        # else: already saved correctly -- do not overwrite
        self.cookies_captured.emit(cookies)
        self.accept()
