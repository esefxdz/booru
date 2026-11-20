"""Dialog for adding a custom booru, with API auto-detection."""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QFormLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from core import settings
import boorus
import threading
import httpx
from adapters import adapter_choices
from core.validation import validate_url, validate_filename


from ui.style import colors

# Default API path per engine, auto-filled on engine pick or auto-detect.
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


class AutoDetectThread(QThread):
    finished = pyqtSignal(str, str, str)  # (status_message, api_type, api_path)

    def __init__(self, url):
        super().__init__()
        self.url = url.rstrip("/")
        # Set by closeEvent so the probe loop stops between requests.
        self.cancel_event = threading.Event()

    def run(self):
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
                    if self.cancel_event.is_set():
                        return
                    try:
                        r = client.get(self.url + path)
                        if r.status_code == 200 and check_fn(r):
                            base_path = path.split("?")[0]
                            self.finished.emit("Detection successful!", expected_type, base_path)
                            return
                    except Exception:
                        continue
            self.finished.emit("Could not automatically detect engine.", "", "")
        except Exception as e:
            self.finished.emit(f"Error checking site: {e}", "", "")


class AddBooruDialog(QDialog):

    def __init__(self, parent_gui):
        super().__init__(parent_gui)
        self.parent_gui = parent_gui
        self.setWindowTitle("Add Custom Booru")
        self.setMinimumWidth(420)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setStyleSheet(f"background-color: {colors.PANEL_BG}; color: {colors.TEXT_SECONDARY};")
        self.detect_thread = None
        self._closed = False

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

    def _on_api_type_changed(self, idx):
        api_type = self.api_types[idx]
        self.path_ent.setText(_DEFAULT_API_PATHS.get(api_type, "/index.php"))

    def _auto_detect(self):
        url = self.url_ent.text().strip()
        if not url:
            self._set_status("Please enter a URL first.", "red")
            return

        try:
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

    def _on_detect_finished(self, msg, api_type, api_path):
        # The thread may emit after closeEvent has returned.
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

    def closeEvent(self, event):
        # Secondary guard in case the signal was already queued before disconnect.
        self._closed = True
        if self.detect_thread is not None and self.detect_thread.isRunning():
            # Layer 1: disconnect so _on_detect_finished is never called.
            try:
                self.detect_thread.finished.disconnect(self._on_detect_finished)
            except RuntimeError:
                pass  # Already disconnected or signal was never connected

            # Layer 2: cancel flag stops new probes; an in-flight request can't be interrupted.
            self.detect_thread.cancel_event.set()

            # No quit()/wait(): run() has no event loop and wait() would freeze the UI for up to 5s.
        super().closeEvent(event)

    def _add_booru(self):
        name = self.name_ent.text().strip().lower().replace(" ", "_")
        url = self.url_ent.text().strip().rstrip("/")
        api_type = self.api_types[self.api_combo.currentIndex()]
        api_path = self.path_ent.text().strip() or _DEFAULT_API_PATHS.get(api_type, "/index.php")

        try:
            name = validate_filename(name)
            url = validate_url(url)
        except Exception as e:
            self._set_status(f"Invalid input: {e}", "red")
            return

        if not name or not url:
            self._set_status("Name and URL are required.", "red")
            return

        # Never shadow an existing registry entry; append _2, _3, ... until the name is free.
        orig_name = name
        counter = 2
        while name in boorus.REGISTRY:
            name = f"{orig_name}_{counter}"
            counter += 1

        try:
            try:
                boorus.add_booru(name, {
                    "url":      url,
                    "api_path": api_path,
                    "post_key": None,
                    "api_type": api_type,
                })
            except boorus.BooruValidationError as e:
                boorus.REGISTRY.pop(name, None)
                self._set_status(f"Invalid input: {e}", "red")
                return
            except OSError:
                boorus.REGISTRY.pop(name, None)
                self._set_status("Could not save booru — check folder permissions.", "red")
                return

            if name not in settings.manager.booru_order:
                settings.manager.booru_order.append(name)
                settings.manager.save()
            self.parent_gui.server_bar.rebuild_list()
            self.accept()
        except Exception as e:
            boorus.REGISTRY.pop(name, None)
            self._set_status(f"Error creating booru: {e}", "red")

    def _set_status(self, msg: str, color: str):
        self.status_lbl.setText(msg)
        c = colors.DANGER if color == "red" else colors.SUCCESS if color == "green" else colors.WARNING
        self.status_lbl.setStyleSheet(f"color: {c};")

    @staticmethod
    def show_dialog(parent_gui):
        AddBooruDialog(parent_gui).exec()
