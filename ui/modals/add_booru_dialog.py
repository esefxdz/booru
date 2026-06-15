"""
ui/modals/add_booru_dialog.py

Dialog for adding a custom booru site by URL.
Includes AutoDetectThread which probes the target site with known
API patterns to automatically identify the engine and path.
"""
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QFormLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from ui import settings_view as settings
import boorus
import threading


from ui import colors

# Default API paths per engine — auto-filled when the user picks a type
# or when auto-detect succeeds, so they rarely need to touch this field
_DEFAULT_API_PATHS = {
    "gelbooru":    "/index.php",
    "danbooru":    "/posts.json",
    "moebooru":    "/post.json",
    "e621":        "/posts.json",
    "philomena":   "/api/v1/json/search/images",
    "szurubooru":  "/api/posts",
    "shimmie2":    "/api/json/index",
    "zerochan":    "/search",
    "html_scraper": "/index.php",
}


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: AutoDetectThread                                            ║
# ║  Background QThread that probes a URL with multiple known API      ║
# ║  patterns and emits (status_msg, api_type, api_path) when done.    ║
# ║  Stops at the first pattern that returns a recognisable response.  ║
# ╚══════════════════════════════════════════════════════════════════════╝
class AutoDetectThread(QThread):
    finished = pyqtSignal(str, str, str)  # (status_message, api_type, api_path)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — strips trailing slash so path concatenation        │
    # │  produces clean URLs like "https://site.com/posts.json"        │
    # └──────────────────────────────────────────────────────────────────┐
    def __init__(self, url):
        super().__init__()
        self.url = url.rstrip("/")
        # Set by AddBooruDialog.closeEvent() to signal the probe loop to stop
        # between requests so the thread exits quickly instead of waiting up
        # to 5 seconds for the current httpx timeout to expire.
        self.cancel_event = threading.Event()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  run  — tries a ranked list of (path, engine, checker) tuples.  │
    # │  For each one it GETs the URL and calls the checker function on │
    # │  the JSON response. The first tuple that passes is returned.    │
    # │  This avoids asking the user which engine their site runs.      │
    # └──────────────────────────────────────────────────────────────────┐
    def run(self):
        import httpx
        headers = {"User-Agent": settings.manager.get_user_agent()}

        def is_json_type(r, check):
            try:
                return check(r.json())
            except Exception:
                return False

        def is_gelbooru(r):
            # Gelbooru can return either JSON list or XML
            try:
                data = r.json()
                return isinstance(data, list) or (isinstance(data, dict) and "post" in data)
            except Exception:
                return "<?xml" in r.text and "<posts" in r.text

        # Each tuple: (api_path, engine_name, response_checker_function)
        tests = [
            ("/posts.json?limit=1",     "danbooru",   lambda r: is_json_type(r, lambda d: isinstance(d, list) or (isinstance(d, dict) and "posts" in d))),
            ("/post.json?limit=1",      "moebooru",   lambda r: is_json_type(r, lambda d: isinstance(d, list))),
            ("/index.php?page=dapi&s=post&q=index&limit=1", "gelbooru", is_gelbooru),
            ("/api/v1/json/search/images?q=*&per_page=1",   "philomena", lambda r: is_json_type(r, lambda d: isinstance(d, dict) and "images" in d)),
            ("/api/posts?limit=1",      "szurubooru", lambda r: is_json_type(r, lambda d: isinstance(d, dict) and "results" in d)),
            ("/api/json/index",         "shimmie2",   lambda r: is_json_type(r, lambda d: isinstance(d, list))),
        ]

        try:
            with httpx.Client(timeout=5.0, headers=headers, follow_redirects=True) as client:
                for path, expected_type, check_fn in tests:
                    # Check the cancel flag between each probe so closeEvent()
                    # can stop the loop quickly without waiting for a full timeout.
                    if self.cancel_event.is_set():
                        return
                    try:
                        r = client.get(self.url + path)
                        if r.status_code == 200 and check_fn(r):
                            base_path = path.split("?")[0]
                            self.finished.emit("Detection successful!", expected_type, base_path)
                            return
                    except Exception:
                        continue  # Try the next pattern if this one errors
            self.finished.emit("Could not automatically detect engine.", "", "")
        except Exception as e:
            self.finished.emit(f"Error checking site: {e}", "", "")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: AddBooruDialog                                              ║
# ║  Dialog for registering a new custom booru. The user provides a    ║
# ║  name and URL; auto-detect fills in the engine and API path.       ║
# ║  On confirm, a .py file is written to the boorus/ folder so the   ║
# ║  site persists across app restarts.                                ║
# ╚══════════════════════════════════════════════════════════════════════╝
class AddBooruDialog(QDialog):

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  __init__  — builds the form: name field, URL field with an     │
    # │  "Auto-Detect" button beside it, engine type dropdown, and API  │
    # │  path field that auto-fills when the type changes or detects    │
    # └──────────────────────────────────────────────────────────────────┘
    def __init__(self, parent_gui):
        super().__init__(parent_gui)
        self.parent_gui = parent_gui
        self.setWindowTitle("Add Custom Booru")
        self.setMinimumWidth(420)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setStyleSheet(f"background-color: {colors.PANEL_BG}; color: {colors.TEXT_SECONDARY};")
        # Always initialize so closeEvent and _on_detect_finished are safe to
        # call even if the user closes the dialog without clicking Auto-Detect.
        self.detect_thread = None
        self._closed = False

        from adapters import adapter_choices
        choices = adapter_choices()
        self.labels    = [lbl for _, lbl in choices]
        self.api_types = [at  for at, _  in choices]

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        self.name_ent = QLineEdit()
        self.name_ent.setPlaceholderText("my_booru  (no spaces)")
        form.addRow("Name:", self.name_ent)

        self.url_ent = QLineEdit()
        self.url_ent.setPlaceholderText("https://example.com")

        url_layout = QHBoxLayout()
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.addWidget(self.url_ent)

        # Auto-detect button probes the URL and fills in engine + path
        self.detect_btn = QPushButton("Auto-Detect")
        self.detect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.detect_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors.BUTTON_BG};
                color: {colors.TEXT_PRIMARY};
                border: 1px solid {colors.BORDER};
                border-radius: 4px;
                padding: 4px 8px;
            }}
            QPushButton:hover {{ background-color: {colors.BUTTON_HOVER}; }}
        """)
        self.detect_btn.clicked.connect(self._auto_detect)
        url_layout.addWidget(self.detect_btn)

        form.addRow("URL:", url_layout)

        self.api_combo = QComboBox()
        self.api_combo.addItems(self.labels)
        # Changing the dropdown auto-fills the API path with a sensible default
        self.api_combo.currentIndexChanged.connect(self._on_api_type_changed)
        form.addRow("API Type:", self.api_combo)

        self.path_ent = QLineEdit()
        self.path_ent.setPlaceholderText("/index.php")
        self.path_ent.setText("/index.php")
        form.addRow("API Path:", self.path_ent)

        layout.addLayout(form)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color: {colors.TEXT_MUTED};")
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

        add_btn = QPushButton("➕  ADD BOORU")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(f"background:{colors.ACCENT}; color:{colors.TEXT_PRIMARY}; font-weight:bold; padding:10px; border-radius:4px;")
        add_btn.clicked.connect(self._add_booru)
        layout.addWidget(add_btn)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _on_api_type_changed  — updates the API path field with the    │
    # │  known default for the selected engine so the user doesn't      │
    # │  need to memorise what path each booru engine uses              │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_api_type_changed(self, idx):
        api_type = self.api_types[idx]
        self.path_ent.setText(_DEFAULT_API_PATHS.get(api_type, "/index.php"))

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _auto_detect  — validates the URL then launches AutoDetect-    │
    # │  Thread in the background. Disables the button while running    │
    # │  to prevent double-clicks.                                      │
    # └──────────────────────────────────────────────────────────────────┘
    def _auto_detect(self):
        url = self.url_ent.text().strip()
        if not url:
            self._set_status("Please enter a URL first.", "red")
            return

        try:
            from validation import validate_url
            url = validate_url(url)
        except Exception as e:
            self._set_status(f"Invalid URL: {e}", "red")
            return

        self.detect_btn.setEnabled(False)
        self.detect_btn.setText("Checking...")
        self._set_status("Detecting engine...", "orange")

        self.detect_thread = AutoDetectThread(url)
        self.detect_thread.finished.connect(self._on_detect_finished)
        self.detect_thread.start()

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _on_detect_finished  — re-enables the detect button and        │
    # │  auto-selects the detected engine in the dropdown. Shows green  │
    # │  on success or orange if detection failed.                      │
    # └──────────────────────────────────────────────────────────────────┘
    def _on_detect_finished(self, msg, api_type, api_path):
        # Guard: if the dialog was already closed, do not touch any Qt widgets.
        # The thread may emit this signal after closeEvent() has returned if the
        # current httpx request hadn't finished by the time we called wait().
        if self._closed:
            return

        self.detect_btn.setEnabled(True)
        self.detect_btn.setText("Auto-Detect")

        if api_type:
            self._set_status(msg, "green")
            try:
                idx = self.api_types.index(api_type)
                self.api_combo.setCurrentIndex(idx)
                if api_path:
                    self.path_ent.setText(api_path)
            except ValueError:
                pass
        else:
            self._set_status(msg, "orange")

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  closeEvent  — cleanup background threads so they don't segfault │
    # │                                                                  │
    # │  Why we DON'T call quit() + wait() here:                        │
    # │    - quit() sends a message to the thread's Qt event loop, but  │
    # │      AutoDetectThread.run() never calls exec(), so there is no  │
    # │      event loop to receive it — quit() would be a complete no-op.│
    # │    - wait() would freeze the UI for up to 5s (the httpx timeout) │
    # │      while the user is trying to close a dialog they gave up on. │
    # │                                                                  │
    # │  Instead, we use a two-layer defence and let the thread die      │
    # │  naturally without blocking:                                     │
    # │    Layer 1: Disconnect the finished signal. Even if the thread   │
    # │      runs to completion and emits, the signal goes nowhere —     │
    # │      _on_detect_finished is never called.                        │
    # │    Layer 2: Set cancel_event so the probe loop stops starting    │
    # │      new HTTP requests between probes (fast-exits at the next    │
    # │      check). Cannot interrupt an in-flight httpx request, but    │
    # │      it bounds runaway work to at most one more probe (≤5s).     │
    # └──────────────────────────────────────────────────────────────────┘
    def closeEvent(self, event):
        # Mark the dialog as closed. _on_detect_finished checks this flag
        # as a secondary guard in case the signal was already in the Qt
        # event queue before we had a chance to disconnect it.
        self._closed = True
        if self.detect_thread is not None and self.detect_thread.isRunning():
            # Layer 1: Disconnect the signal so _on_detect_finished can never
            # be called, even if the thread runs to completion in the background.
            try:
                self.detect_thread.finished.disconnect(self._on_detect_finished)
            except RuntimeError:
                pass  # Already disconnected or signal was never connected

            # Layer 2: Set the cancel flag so the probe loop stops launching
            # new HTTP requests. Cannot interrupt an in-flight request, but
            # limits runaway background work to at most one more probe (≤5s).
            self.detect_thread.cancel_event.set()

            # Do NOT call quit() or wait() — quit() is a no-op because
            # AutoDetectThread.run() has no Qt event loop, and wait() would
            # freeze the UI for up to 5s (the httpx request timeout).
            # The thread will finish naturally and be garbage-collected.
        super().closeEvent(event)

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _add_booru  — validates name + URL, appends a numeric suffix   │
    # │  if the name already exists (e.g. danbooru_2), then writes a    │
    # │  new .py file to boorus/ and registers it in the in-memory     │
    # │  registry so the server bar icon appears immediately            │
    # └──────────────────────────────────────────────────────────────────┘
    def _add_booru(self):
        name     = self.name_ent.text().strip().lower().replace(" ", "_")
        url      = self.url_ent.text().strip().rstrip("/")
        api_type = self.api_types[self.api_combo.currentIndex()]
        api_path = self.path_ent.text().strip() or _DEFAULT_API_PATHS.get(api_type, "/index.php")

        try:
            from validation import validate_filename, validate_url
            name = validate_filename(name)
            url  = validate_url(url)
        except Exception as e:
            self._set_status(f"Invalid input: {e}", "red")
            return

        if not name or not url:
            self._set_status("Name and URL are required.", "red")
            return

        # If the name is taken, try name_2, name_3, ... until free.
        # Built-in boorus (e.g. "gelbooru") live in REGISTRY from startup —
        # adding one with the same URL but a different name is fine, but we
        # must never silently shadow an existing entry.
        orig_name = name
        counter = 2
        while name in boorus.REGISTRY:
            name = f"{orig_name}_{counter}"
            counter += 1

        try:
            # Invalidate any stale importlib cache from a previously-deleted
            # booru with the same name so the new file is imported fresh.
            boorus.invalidate_cache(name)

            # Register in memory first so write_booru_file() can read it.
            boorus.REGISTRY[name] = {
                "url":      url,
                "api_path": api_path,
                "post_key": None,
                "api_type": api_type,
            }

            # Use the centralised helper — it writes a clean template from
            # REGISTRY data and fsync()s it, the same path used by _save_engine.
            if not boorus.write_booru_file(name):
                boorus.REGISTRY.pop(name, None)
                self._set_status("Could not write booru file — check folder permissions.", "red")
                return

            # Add to the persistent sidebar order and save immediately.
            if name not in settings.manager.booru_order:
                settings.manager.booru_order.append(name)
                settings.manager.save()
            self.parent_gui.server_bar.rebuild_list()
            self.accept()
        except Exception as e:
            boorus.REGISTRY.pop(name, None)
            self._set_status(f"Error creating booru: {e}", "red")

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _set_status  — helper to update the status label text and      │
    # │  colour in one call instead of repeating setStyleSheet inline   │
    # └──────────────────────────────────────────────────────────────────┐
    def _set_status(self, msg: str, color: str):
        self.status_lbl.setText(msg)
        c = colors.DANGER if color == "red" else colors.SUCCESS if color == "green" else colors.WARNING
        self.status_lbl.setStyleSheet(f"color: {c};")

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  show_dialog  — convenience static wrapper                      │
    # └──────────────────────────────────────────────────────────────────┘
    @staticmethod
    def show_dialog(parent_gui):
        AddBooruDialog(parent_gui).exec()
