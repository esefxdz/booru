import os
import sys

def _setup_logging():
    """Wire up rotating file logs so crashes are diagnosable in packaged builds."""
    import logging
    from logging.handlers import RotatingFileHandler
    from pathlib import Path

    if getattr(sys, 'frozen', False):
        log_dir = Path(os.path.dirname(sys.executable))
    else:
        log_dir = Path(os.path.dirname(os.path.abspath(__file__)))

    log_file = log_dir / "error.txt"

    handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    
    handlers = [handler]
    if sys.stdout is not None and sys.stderr is not None:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception

_setup_logging()

# Disable GPU hardware acceleration in WebEngine to prevent black screens on Windows
# without having to disable the Chromium sandbox (--no-sandbox).
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

# 4.1 High-DPI & Scaling Support
if hasattr(Qt.HighDpiScaleFactorRoundingPolicy, 'PassThrough'):
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

# WebEngine MUST be imported before QApplication is created.
from PyQt6.QtWebEngineWidgets import QWebEngineView as _WEV  # noqa: F401

from ui import settings_view as settings
import boorus
from gui import BooruGui

import ui.colors as colors
from pathlib import Path

def main():

    settings.manager.initialize()

    # Share contexts to prevent "virtualization" errors on some systems
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    
    qss_path = Path(__file__).parent / "ui" / "assets" / "theme.qss"
    with open(qss_path, "r", encoding="utf-8") as f:
        theme = f.read()
        for k, v in colors.__dict__.items():
            if k.isupper() and isinstance(v, str):
                theme = theme.replace(f"{{{k}}}", v)
    
    app.setStyleSheet(theme)
    app.setFont(QFont("Segoe UI", 10))

    window = BooruGui()
    window.show()

    exit_code = app.exec()

    # ── Clean shutdown: close the SQLite cache connection ──────────
    import thumb_cache
    thumb_cache.shutdown()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

#