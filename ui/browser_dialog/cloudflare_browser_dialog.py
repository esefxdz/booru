###########################################################################################
# ui/browser_dialog/cloudflare_browser_dialog.py — Cloudflare bypass dialog.
#
# Three-engine approach:
#   Engine 1 — In-app embedded browser (interactive CAPTCHA / Turnstile)
#   Engine 2 — Manual cookie paste with UA field
#   Engine 3 — Auto-import from system browsers (Chrome/Edge/Firefox/Brave)
#
# All engines produce (cookies, user_agent) → saved via cloudflare_bypasser.store.
###########################################################################################

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QWidget, QFrame,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings
from PyQt6.QtCore import pyqtSignal, QTimer, Qt, QUrl

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
        ws.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
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

        # ── Fallback: manual paste + auto-import ───────────────────────
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
        bar.setFixedHeight(32)
        bar.setStyleSheet(
            f"background-color: {colors.MAIN_BG}; "
            f"border-bottom: 1px solid {colors.BORDER};"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(15, 0, 15, 0)

        self._status_lbl = QLabel("⏳ Waiting for Cloudflare challenge…")
        self._status_lbl.setStyleSheet(
            f"color: {colors.TEXT_MUTED}; font-size: 11px; font-weight: bold;"
        )
        h.addWidget(self._status_lbl)
        h.addStretch()

        # Insert after the progress bar (index 2 in the layout)
        self.layout().insertWidget(2, bar)

    def _set_status(self, text: str, color: str = colors.TEXT_MUTED):
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: bold;"
        )

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
        name = cookie.name().data().decode()
        value = cookie.value().data().decode()
        self._found_cookies[name] = value

        # Capture on cf_clearance OR __cf_bm — either indicates CF clearance
        if name in ("cf_clearance", "__cf_bm"):
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
        # Always merge found cookies — useful even without cf_clearance
        self._found_cookies.update(cookies)
        # Trigger on cf_clearance OR __cf_bm
        if any(k in cookies for k in ("cf_clearance", "__cf_bm")):
            self._captured = True
            self._poll_timer.stop()
            key = "cf_clearance" if "cf_clearance" in cookies else "__cf_bm"
            self._set_status(f"✅ Cloudflare cookie captured ({key}) — closing…", colors.SUCCESS)
            QTimer.singleShot(800, lambda: self._finalize(self._found_cookies))

    # ═══════════════════════════════════════════════════════════════════
    #  Fallback Panel (Engine 2: Manual Paste + Engine 3: Auto-Import)
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

        # Engine 3: Auto-import button
        import_btn = QPushButton("🔍 Auto-Import from Browser")
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.setStyleSheet(
            f"background: {colors.ACCENT}; color: white; "
            f"font-weight: bold; border-radius: 4px; padding: 5px 12px; font-size: 11px;"
        )
        import_btn.clicked.connect(self._auto_import)
        btn_row.addWidget(import_btn)

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
    #  Engine 3 — Auto-Import from System Browsers
    # ═══════════════════════════════════════════════════════════════════

    def _auto_import(self):
        """Search system browsers for a cf_clearance cookie matching this booru."""
        self._warn_lbl.setText("🔍 Searching browser cookie stores…")
        self._warn_lbl.setStyleSheet(f"color: {colors.ACCENT}; font-size: 10px;")

        # Run in a timer so the UI updates before the (potentially slow) disk I/O
        QTimer.singleShot(50, self._do_auto_import)

    def _do_auto_import(self):
        # Extract the domain from the URL for matching
        try:
            from urllib.parse import urlparse
            current_url = self.browser.url().toString()
            domain = urlparse(current_url).hostname or self.booru_name
        except Exception:
            domain = self.booru_name

        results = _find_cf_clearance_all_browsers(domain)

        if not results:
            self._warn_lbl.setText(
                "❌ No cf_clearance found in any browser. "
                "Visit the site in Chrome/Firefox first, then try again."
            )
            self._warn_lbl.setStyleSheet(f"color: {colors.DANGER}; font-size: 10px;")
            return

        # Use the first valid result
        browser_name, cookie_val = next(iter(results.items()))
        self._cf_input.setText(cookie_val)
        self._warn_lbl.setText(f"✅ Found cf_clearance in {browser_name} — click Apply to use it")
        self._warn_lbl.setStyleSheet(f"color: {colors.SUCCESS}; font-size: 10px;")

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


# ═══════════════════════════════════════════════════════════════════════
#  Engine 3 helper — read cookies from system browsers
# ═══════════════════════════════════════════════════════════════════════

def _find_cf_clearance_all_browsers(domain: str) -> dict:
    """
    Search all known browser cookie stores for a cf_clearance cookie
    matching *domain*.  Returns {browser_name: cookie_value}.

    Safe to call even if browsers are locked or pywin32 is missing —
    every failure path returns an empty dict.
    """
    import sqlite3
    import shutil
    import tempfile
    from pathlib import Path

    results = {}

    # ── Chromium-based browsers ────────────────────────────────────
    chromium_browsers = {
        "Chrome": Path.home() / "AppData/Local/Google/Chrome/User Data/Default/Network/Cookies",
        "Edge":   Path.home() / "AppData/Local/Microsoft/Edge/User Data/Default/Network/Cookies",
        "Brave":  Path.home() / "AppData/Local/BraveSoftware/Brave-Browser/User Data/Default/Network/Cookies",
        "Opera":  Path.home() / "AppData/Roaming/Opera Software/Opera Stable/Network/Cookies",
    }

    for browser, db_path in chromium_browsers.items():
        if not db_path.exists():
            continue
        val = _read_chromium_cookie(db_path, domain)
        if val:
            results[browser] = val

    # ── Firefox ────────────────────────────────────────────────────
    ff_val = _read_firefox_cookie(domain)
    if ff_val:
        results["Firefox"] = ff_val

    return results


def _read_chromium_cookie(db_path, domain: str) -> str | None:
    """Read cf_clearance from a Chromium SQLite cookie DB.
    Copies the DB first since Chrome locks it while running.
    """
    import sqlite3
    import shutil
    import tempfile

    try:
        # Copy the locked DB to a temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        shutil.copy2(db_path, tmp.name)

        conn = sqlite3.connect(tmp.name)
        # Try unencrypted value first (works on some builds)
        row = conn.execute(
            "SELECT value, encrypted_value FROM cookies "
            "WHERE host_key LIKE ? AND name = 'cf_clearance' "
            "ORDER BY last_access_utc DESC LIMIT 1",
            (f"%{domain}%",)
        ).fetchone()
        conn.close()

        import os
        os.unlink(tmp.name)

        if not row:
            return None

        plain_val, encrypted_val = row

        # If the plain text value is populated, use it
        if plain_val:
            return plain_val

        # Otherwise try to decrypt the encrypted_value
        return _decrypt_chromium_value(encrypted_val)
    except Exception:
        return None


def _decrypt_chromium_value(encrypted_value: bytes) -> str | None:
    """Decrypt a Chromium DPAPI-encrypted cookie value on Windows."""
    if not encrypted_value:
        return None

    try:
        # v10/v20 = AES-256-GCM encrypted (Chrome 80+)
        if encrypted_value[:3] in (b"v10", b"v20"):
            return _decrypt_aes_gcm(encrypted_value)

        # Legacy DPAPI (pre Chrome 80)
        import win32crypt
        data, _ = win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)
        return data.decode("utf-8", errors="replace")
    except ImportError:
        # pywin32 not installed
        return None
    except Exception:
        return None


def _decrypt_aes_gcm(encrypted_value: bytes) -> str | None:
    """Decrypt AES-256-GCM encrypted cookie (Chrome 80+)."""
    try:
        import json
        import base64
        import win32crypt
        from pathlib import Path
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        # Find Local State to get the encryption key
        # Try Chrome first, then Edge, then Brave
        local_state_paths = [
            Path.home() / "AppData/Local/Google/Chrome/User Data/Local State",
            Path.home() / "AppData/Local/Microsoft/Edge/User Data/Local State",
            Path.home() / "AppData/Local/BraveSoftware/Brave-Browser/User Data/Local State",
        ]

        key = None
        for ls_path in local_state_paths:
            if ls_path.exists():
                with open(ls_path, "r", encoding="utf-8") as f:
                    local_state = json.load(f)
                encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
                # Remove "DPAPI" prefix (5 bytes)
                encrypted_key = encrypted_key[5:]
                key, _ = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)
                break

        if not key:
            return None

        # Decrypt: first 3 bytes = version, next 12 = nonce, rest = ciphertext + tag
        nonce = encrypted_value[3:15]
        ciphertext = encrypted_value[15:]
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8", errors="replace")
    except ImportError:
        return None
    except Exception:
        return None


def _read_firefox_cookie(domain: str) -> str | None:
    """Read cf_clearance from Firefox's cookies.sqlite."""
    import sqlite3
    import shutil
    import tempfile
    from pathlib import Path

    try:
        ff_profiles = Path.home() / "AppData/Roaming/Mozilla/Firefox/Profiles"
        if not ff_profiles.exists():
            return None

        # Find the default profile directory
        for profile_dir in ff_profiles.iterdir():
            if not profile_dir.is_dir():
                continue
            cookie_db = profile_dir / "cookies.sqlite"
            if not cookie_db.exists():
                continue

            # Copy to avoid locking issues
            tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            tmp.close()
            shutil.copy2(cookie_db, tmp.name)

            conn = sqlite3.connect(tmp.name)
            row = conn.execute(
                "SELECT value FROM moz_cookies "
                "WHERE host LIKE ? AND name = 'cf_clearance' "
                "ORDER BY lastAccessed DESC LIMIT 1",
                (f"%{domain}%",)
            ).fetchone()
            conn.close()

            import os
            os.unlink(tmp.name)

            if row and row[0]:
                return row[0]

        return None
    except Exception:
        return None
