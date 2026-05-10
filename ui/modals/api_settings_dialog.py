"""
ui/modals/api_settings_dialog.py

Per-booru credentials and authentication settings dialog.
Opened by right-clicking any booru icon in the server bar.

Tabs:
  🔑 API Key      — username / API key or szurubooru token
  🍪 Session Login — cookie-based login (only for supported engines)
  🛡 Cloudflare   — in-app browser for cf_clearance bypass
  ⚙ Engine       — switch the API engine for this booru
  ℹ Info/Delete  — read-only info + delete button
"""
import os
import asyncio
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QMessageBox, QTabWidget,
    QWidget, QFormLayout, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from validation import ValidationError

from ui import settings_view as settings
import boorus


from ui import colors

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: APISettingsDialog                                           ║
# ║  The full settings panel for a single booru. Dynamically builds    ║
# ║  the credential fields based on which engine the booru uses, and   ║
# ║  only shows the Session Login tab for engines that support it.     ║
# ╚══════════════════════════════════════════════════════════════════════╝
class APISettingsDialog(QDialog):

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — looks up the booru's api_type from the registry,   │
    # │  checks session-login support, then builds a QTabWidget with    │
    # │  one tab per settings category (credential fields vary by type) │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, parent_gui, name: str):
        super().__init__(parent_gui)
        self.parent_gui = parent_gui
        self.name = name
        self.api_type = boorus.REGISTRY.get(name, {}).get("api_type", "gelbooru")

        from adapters.session_login import supports_session_login, get_session_cookie_names
        self._supports_session = supports_session_login(self.api_type)
        self._session_cookie_names = get_session_cookie_names(self.api_type)

        self.setWindowTitle(f"⚙  {name}  Settings")
        self.setMinimumWidth(400)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setStyleSheet(f"background-color: {colors.PANEL_BG}; color: {colors.TEXT_SECONDARY};")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Bold booru name + dimmed engine type in the title row
        title = QLabel(f"<b>{name}</b>  <span style='color:{colors.TEXT_MUTED}'>({self.api_type})</span>")
        title.setStyleSheet(f"font-size: 14px; color: {colors.TEXT_SECONDARY};")
        layout.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {colors.BORDER};")
        layout.addWidget(sep)

        tabs = QTabWidget()
        tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid {colors.BORDER}; border-radius: 4px; }}
            QTabBar::tab {{ background: {colors.BUTTON_BG}; color: {colors.TEXT_MUTED}; padding: 8px 12px; }}
            QTabBar::tab:selected {{ background: {colors.ACCENT}; color: {colors.TEXT_PRIMARY}; }}
        """)
        layout.addWidget(tabs)

        # ── Tab 1: API Key ─────────────────────────────────────────────
        # Credential fields vary by engine: szurubooru uses token auth,
        # others use a username + API key pair
        api_tab = QWidget()
        api_form = QFormLayout(api_tab)
        api_form.setSpacing(8)

        creds = settings.manager.get_credential(name) or {}

        if self.api_type in ("gelbooru", "danbooru", "moebooru", "e621", "philomena"):
            self._user_id = QLineEdit(creds.get("user_id", ""))
            self._user_id.setPlaceholderText("Username / User ID")
            api_form.addRow("Username:", self._user_id)

        if self.api_type != "szurubooru":
            self._api_key = QLineEdit(creds.get("api_key", ""))
            self._api_key.setPlaceholderText("API Key / Password Hash")
            self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
            api_form.addRow("API Key:", self._api_key)

        if self.api_type == "szurubooru":
            # Szurubooru uses a different token-based auth model
            auth = settings.manager.auth_tokens.get(name, {})
            self._szuru_user = QLineEdit(auth.get("user", ""))
            self._szuru_user.setPlaceholderText("Your Szurubooru username")
            self._szuru_token = QLineEdit(auth.get("token", ""))
            self._szuru_token.setPlaceholderText("API Token (from your profile)")
            self._szuru_token.setEchoMode(QLineEdit.EchoMode.Password)
            api_form.addRow("Username:", self._szuru_user)
            api_form.addRow("API Token:", self._szuru_token)

        save_api_btn = QPushButton("💾  Save API Credentials")
        save_api_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_api_btn.setStyleSheet(f"background:{colors.ACCENT}; color:{colors.TEXT_PRIMARY}; font-weight:bold; padding:8px; border-radius:4px;")
        save_api_btn.clicked.connect(self._save_api)
        api_form.addRow(save_api_btn)
        tabs.addTab(api_tab, "🔑 API Key")

        # ── Tab 2: Session Login (only for PHP/cookie-based engines) ───
        if self._supports_session:
            sess_tab = QWidget()
            sess_layout = QVBoxLayout(sess_tab)
            sess_layout.setSpacing(8)

            info = QLabel(
                "Log in with your account credentials.\n"
                "The app will automatically capture your session cookie."
            )
            info.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 11px;")
            info.setWordWrap(True)
            sess_layout.addWidget(info)

            sess_form = QFormLayout()
            self._sess_user = QLineEdit()
            self._sess_user.setPlaceholderText("Your username")
            self._sess_pass = QLineEdit()
            self._sess_pass.setPlaceholderText("Your password")
            self._sess_pass.setEchoMode(QLineEdit.EchoMode.Password)
            sess_form.addRow("Username:", self._sess_user)
            sess_form.addRow("Password:", self._sess_pass)
            sess_layout.addLayout(sess_form)

            # Live status label updated by login thread callbacks
            self._sess_status = QLabel("")
            self._sess_status.setWordWrap(True)
            sess_layout.addWidget(self._sess_status)

            login_btn = QPushButton("🚀  Login (Automatic)")
            login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            login_btn.setStyleSheet(f"background:{colors.SUCCESS}; color:{colors.TEXT_PRIMARY}; font-weight:bold; padding:8px; border-radius:4px;")
            login_btn.clicked.connect(self._do_session_login)
            sess_layout.addWidget(login_btn)

            browser_btn = QPushButton("🌐  Login in Browser (Manual)")
            browser_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            browser_btn.setStyleSheet(f"background:{colors.BUTTON_BG}; color:{colors.TEXT_SECONDARY}; padding:8px; border-radius:4px;")
            browser_btn.clicked.connect(self._do_browser_login)
            sess_layout.addWidget(browser_btn)

            # Show active session info if one is already stored
            cur_session = settings.manager.session_keys.get(name, {})
            if cur_session:
                active_lbl = QLabel(f"✓ Active session: {list(cur_session.keys())}")
                active_lbl.setStyleSheet(f"color: {colors.SUCCESS}; font-size: 11px;")
                sess_layout.addWidget(active_lbl)

                clear_btn = QPushButton("✕  Clear Session")
                clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                clear_btn.setStyleSheet(f"background:{colors.DANGER}; color:{colors.TEXT_PRIMARY}; padding:6px; border-radius:4px;")
                clear_btn.clicked.connect(lambda: self._clear_session())
                sess_layout.addWidget(clear_btn)

            sess_layout.addStretch()
            tabs.addTab(sess_tab, "🍪 Session Login")

        # ── Tab 3: Cloudflare Bypass ───────────────────────────────────
        cf_tab = QWidget()
        cf_layout = QVBoxLayout(cf_tab)
        cf_layout.setSpacing(8)

        cf_info = QLabel(
            "If this site is behind Cloudflare, use the in-app browser below.\n"
            "Complete the CAPTCHA and the bypass cookie will be captured automatically."
        )
        cf_info.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 11px;")
        cf_info.setWordWrap(True)
        cf_layout.addWidget(cf_info)

        bypass = settings.manager.bypass_data.get(name, {})
        if bypass.get("cf_clearance") or bypass.get("cookies"):
            # A valid bypass is already stored — offer to clear it
            cf_active = QLabel("✓ Cloudflare bypass is active")
            cf_active.setStyleSheet(f"color: {colors.SUCCESS};")
            cf_layout.addWidget(cf_active)

            cf_clear_btn = QPushButton("✕  Clear Bypass")
            cf_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cf_clear_btn.setStyleSheet(f"background:{colors.DANGER}; color:{colors.TEXT_PRIMARY}; padding:6px; border-radius:4px;")
            cf_clear_btn.clicked.connect(self._clear_cf)
            cf_layout.addWidget(cf_clear_btn)
        else:
            cf_inactive = QLabel("✗ No bypass active")
            cf_inactive.setStyleSheet(f"color: {colors.WARNING};")
            cf_layout.addWidget(cf_inactive)

        cf_btn = QPushButton("🛡  Open Cloudflare Bypass Browser")
        cf_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cf_btn.setStyleSheet(f"background:{colors.DANGER}; color:{colors.TEXT_PRIMARY}; font-weight:bold; padding:8px; border-radius:4px;")
        cf_btn.clicked.connect(self._run_cf_bypass)
        cf_layout.addWidget(cf_btn)
        cf_layout.addStretch()
        tabs.addTab(cf_tab, "🛡 Cloudflare")

        # ── Tab 4: Engine Type ─────────────────────────────────────────
        engine_tab = QWidget()
        engine_layout = QVBoxLayout(engine_tab)
        engine_layout.setSpacing(12)

        engine_info = QLabel(
            "Change the underlying engine used to communicate with this site.\n"
            "This is useful if a site changes its software or if you added it with the wrong type."
        )
        engine_info.setStyleSheet(f"color: {colors.TEXT_MUTED}; font-size: 11px;")
        engine_info.setWordWrap(True)
        engine_layout.addWidget(engine_info)

        engine_form = QFormLayout()
        from adapters import adapter_choices
        choices = adapter_choices()
        self.engine_types = [at for at, _ in choices]
        engine_labels = [lbl for _, lbl in choices]

        self._engine_combo = QComboBox()
        self._engine_combo.addItems(engine_labels)
        if self.api_type in self.engine_types:
            self._engine_combo.setCurrentIndex(self.engine_types.index(self.api_type))

        engine_form.addRow("Booru Engine:", self._engine_combo)
        engine_layout.addLayout(engine_form)

        save_engine_btn = QPushButton("💾  Save Engine Change")
        save_engine_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_engine_btn.setStyleSheet(f"background:{colors.SUCCESS}; color:{colors.TEXT_PRIMARY}; font-weight:bold; padding:8px; border-radius:4px;")
        save_engine_btn.clicked.connect(self._save_engine)
        engine_layout.addWidget(save_engine_btn)
        engine_layout.addStretch()
        tabs.addTab(engine_tab, "⚙ Engine")

        # ── Tab 5: Info / Delete ───────────────────────────────────────
        info_tab = QWidget()
        info_layout = QVBoxLayout(info_tab)
        info_layout.setSpacing(8)

        reg = boorus.REGISTRY.get(name, {})
        info_form = QFormLayout()
        info_form.addRow("URL:",      QLabel(reg.get("url", "?")))
        info_form.addRow("API Type:", QLabel(reg.get("api_type", "?")))
        info_form.addRow("API Path:", QLabel(reg.get("api_path", "?")))
        info_layout.addLayout(info_form)
        info_layout.addStretch()

        # Only show delete if the booru has a file on disk (built-ins don't)
        booru_file = settings.BASE_DIR / "boorus" / f"{name}.py"
        if os.path.exists(booru_file):
            del_btn = QPushButton("🗑  Delete This Booru")
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setStyleSheet(f"background:{colors.DANGER}; color:{colors.TEXT_PRIMARY}; padding:8px; border-radius:4px;")
            del_btn.clicked.connect(self._delete_booru)
            info_layout.addWidget(del_btn)

        tabs.addTab(info_tab, "ℹ Info / Delete")

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"background:{colors.BUTTON_BG}; color:{colors.TEXT_SECONDARY}; padding:8px; border-radius:4px;")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  showEvent  — plays a slide-up entrance animation each time the │
    # │  dialog opens                                                   │
    # └──────────────────────────────────────────────────────────────────┘
    def showEvent(self, event):
        super().showEvent(event)
        import ui.animations as anims
        anims.animate_slide_up_fade(self, duration=300, offset=15)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _save_api  — reads credential fields (which differ per engine) │
    # │  sanitises them via the validation module, and stores them      │
    # │  in settings. Szurubooru writes to AUTH_TOKENS; all others use  │
    # │  set_credential which encrypts using the OS keychain.          │
    # └──────────────────────────────────────────────────────────────────┘
    def _save_api(self):
        if self.api_type == "szurubooru":
            user  = self._szuru_user.text().strip()
            token = self._szuru_token.text().strip()
            if not user or not token:
                QMessageBox.warning(self, "Error", "Username and token are required.")
                return
            settings.manager.auth_tokens[self.name] = {"user": user, "token": token}
        else:
            user_id = getattr(self, "_user_id", None)
            api_key = getattr(self, "_api_key", None)
            user_id = user_id.text().strip() if user_id else ""
            api_key = api_key.text().strip() if api_key else ""
            if user_id and api_key:
                try:
                    from validation import validate_filename
                    user_id = validate_filename(user_id)
                    api_key = validate_filename(api_key)
                    settings.manager.set_credential(self.name, user_id, api_key)
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Invalid credentials: {e}")
                    return
        settings.manager.save()
        QMessageBox.information(self, "Saved", "Credentials saved successfully.")

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _save_engine  — changes the api_type both in the in-memory    │
    # │  registry and in the booru's .py file so it survives restart.  │
    # │  Reads the file line-by-line and rewrites only the API_TYPE     │
    # │  line to avoid stomping on custom edits to other fields.        │
    # └──────────────────────────────────────────────────────────────────┘
    def _save_engine(self):
        new_engine = self.engine_types[self._engine_combo.currentIndex()]
        if new_engine == self.api_type:
            QMessageBox.information(self, "No Change", "Engine is already set to this type.")
            return

        if self.name in boorus.REGISTRY:
            boorus.REGISTRY[self.name]["api_type"] = new_engine

        booru_file = settings.BASE_DIR / "boorus" / f"{self.name}.py"
        if os.path.exists(booru_file):
            try:
                with open(booru_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                with open(booru_file, "w", encoding="utf-8") as f:
                    for line in lines:
                        if line.startswith("API_TYPE"):
                            f.write(f'API_TYPE = "{new_engine}"\n')
                        else:
                            f.write(line)
            except Exception as e:
                print(f"Error updating booru file engine: {e}")

        self.api_type = new_engine
        QMessageBox.information(
            self, "Saved",
            f"Engine switched to {new_engine}.\nPlease reopen this dialog to see updated credential fields."
        )

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _do_session_login  — validates credentials, then spawns a      │
    # │  LoginThread (inner QThread) to perform the login asynchron-    │
    # │  ously without freezing the UI. On success the session cookie   │
    # │  is stored in settings.manager.session_keys for this booru.            │
    # └──────────────────────────────────────────────────────────────────┘
    def _do_session_login(self):
        from adapters.session_login import perform_login
        username = self._sess_user.text().strip()
        password = self._sess_pass.text().strip()

        try:
            from validation import validate_filename
            if not username or not password:
                raise ValidationError("Username and password are required")
            username = validate_filename(username)
            password = validate_filename(password)
        except Exception as e:
            self._sess_status.setText(f"⚠ Invalid input: {e}")
            self._sess_status.setStyleSheet(f"color: {colors.DANGER};")
            return

        site_url = boorus.REGISTRY[self.name]["url"]
        api_type = self.api_type

        self._sess_status.setText("⏳ Attempting login…")
        self._sess_status.setStyleSheet(f"color: {colors.WARNING};")

        # Inner thread: runs the async login coroutine on a new event loop
        class LoginThread(QThread):
            done = pyqtSignal(dict)
            def __init__(self, url, atype, user, pwd):
                super().__init__()
                self._url, self._atype, self._user, self._pwd = url, atype, user, pwd
            def run(self):
                loop = asyncio.new_event_loop()
                result = loop.run_until_complete(
                    perform_login(self._url, self._atype, self._user, self._pwd)
                )
                loop.close()
                self.done.emit(result)

        def on_done(cookies: dict):
            if cookies:
                settings.manager.session_keys[self.name] = cookies
                settings.manager.save()
                self._sess_status.setText(f"✓ Logged in! Session: {list(cookies.keys())}")
                self._sess_status.setStyleSheet(f"color: {colors.SUCCESS}; font-weight: bold;")
            else:
                self._sess_status.setText("✗ Auto-login failed — try the Browser login below.")
                self._sess_status.setStyleSheet(f"color: {colors.DANGER};")

        self._login_thread = LoginThread(site_url, api_type, username, password)
        self._login_thread.done.connect(on_done)
        self._login_thread.start()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _do_browser_login  — opens SessionLoginBrowserDialog so the    │
    # │  user can log in manually via a real browser embed. The dialog  │
    # │  captures the session cookie automatically and returns it.      │
    # └──────────────────────────────────────────────────────────────────┘
    def _do_browser_login(self):
        from adapters.session_login import get_login_url, get_session_cookie_names
        from ui.browser_dialog import SessionLoginBrowserDialog

        login_url    = get_login_url(boorus.REGISTRY[self.name]["url"], self.api_type)
        cookie_names = get_session_cookie_names(self.api_type)

        dlg = SessionLoginBrowserDialog(login_url, self.name, cookie_names, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cookies = dlg.get_found_cookies()
            if cookies:
                settings.manager.session_keys[self.name] = cookies
                settings.manager.save()
                self._sess_status.setText(f"✓ Session captured: {list(cookies.keys())}")
                self._sess_status.setStyleSheet(f"color: {colors.SUCCESS}; font-weight: bold;")

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _clear_session  — removes the stored session cookie, forcing   │
    # │  the next request to go through a fresh login flow              │
    # └──────────────────────────────────────────────────────────────────┘
    def _clear_session(self):
        settings.manager.session_keys.pop(self.name, None)
        settings.manager.save()
        self.accept()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _run_cf_bypass  — opens the in-app Chromium browser pointed at │
    # │  this booru's URL. When cf_clearance arrives, saves it together │
    # │  with the real User-Agent string so future httpx requests can   │
    # │  pass the Cloudflare challenge without the browser.             │
    # └──────────────────────────────────────────────────────────────────┘
    def _run_cf_bypass(self):
        from ui.browser_dialog import CloudflareBrowserDialog
        from cloudflare_bypasser import store as cf_store
        url = boorus.REGISTRY[self.name]["url"]
        dlg = CloudflareBrowserDialog(url, self.name, self)

        def on_captured(cookies: dict):
            # Persist cookies + the exact UA that solved the challenge
            cf_store.save_bypass(self.name, cookies, dlg.get_user_agent())

        dlg.cookies_captured.connect(on_captured)
        dlg.exec()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _clear_cf  — invalidates the in-memory bypass session and      │
    # │  removes the stored cookies so the next request gets a fresh    │
    # │  challenge (useful when cf_clearance expires)                   │
    # └──────────────────────────────────────────────────────────────────┘
    def _clear_cf(self):
        from cloudflare_bypasser import invalidate_session
        invalidate_session(self.name)
        self.accept()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _delete_booru  — delegates to the main GUI's remove_booru      │
    # │  which handles both the registry entry and the .py file         │
    # └──────────────────────────────────────────────────────────────────┘
    def _delete_booru(self):
        self.parent_gui.remove_booru(self.name)
        self.accept()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  show_dialog  — convenience static wrapper                      │
    # └──────────────────────────────────────────────────────────────────┘
    @staticmethod
    def show_dialog(parent_gui, name: str):
        APISettingsDialog(parent_gui, name).exec()
