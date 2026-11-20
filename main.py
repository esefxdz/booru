import os
import sys

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import traceback
from storage import thumb_cache
import download_images.engines as engines
import download_images.thumb_client as thumb_client

def _setup_logging():
    from core.app_paths import data_dir
    log_file = None
    handlers = []
    try:
        # data_dir() can raise; fall back to stderr-only logging.
        log_file = data_dir() / "error.txt"
        handlers.append(RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        ))
    except Exception:
        pass
    if sys.stdout is not None and sys.stderr is not None:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

    for noisy in (
        "httpx", "httpcore", "h2", "urllib3", "curl_cffi",
        "asyncio",
    ):
        logging.getLogger(noisy).setLevel(logging.ERROR)

    # Created on the GUI thread (runs at import time).
    from PyQt6.QtCore import QObject, pyqtSignal

    class _ErrorDialogBridge(QObject):
        requested = pyqtSignal(str)

    dialog_bridge = _ErrorDialogBridge()

    def show_error_dialog(tb):
        try:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Fatal Error")
            msg.setText("The application encountered an unrecoverable error and must close.\n\n"
                        f"Check the log at: {log_file or '(file logging unavailable)'}")
            msg.setDetailedText(tb)
            msg.exec()
        except Exception:
            logging.critical("Could not show error dialog", exc_info=True)

    dialog_bridge.requested.connect(show_error_dialog)

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        logging.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))
        
        # Qt widgets need the GUI thread but this hook also fires for worker
        # threads, so request the dialog through a signal.
        try:
            if QApplication.instance():
                tb = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
                dialog_bridge.requested.emit(tb)
        except Exception:
            logging.critical("Could not show error dialog", exc_info=True)

    sys.excepthook = handle_exception

_setup_logging()

logging.info("BooruBrowser starting (frozen=%s)", getattr(sys, 'frozen', False))
try:
    from core.app_paths import data_dir, data_dir_reason
    logging.info("Data folder: %s (%s)", data_dir(), data_dir_reason())
except Exception:
    logging.exception("Could not determine data folder")

# Qt-level messages bypass Python exceptions; log them to error.txt.
def _qt_message_handler(mode, context, message):
    if mode == 4:  # QtFatalMsg — would abort() without this
        logging.critical("Qt fatal: %s", message)
    elif mode == 3:  # QtCriticalMsg
        logging.error("Qt critical: %s", message)
    else:
        logging.debug("Qt [%d]: %s", mode, message)

from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
qInstallMessageHandler(_qt_message_handler)

# Avoids black screens and silent qFatal crashes in WebEngine on Windows;
# --disable-gpu alone isn't enough, --in-process-gpu avoids GPU sandbox/spawn failures.
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--disable-gpu "
    "--in-process-gpu "
    "--disable-software-rasterizer"
)

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtCore import Qt

if hasattr(Qt.HighDpiScaleFactorRoundingPolicy, "PassThrough"):
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

# Must be imported before QApplication is created.
from PyQt6.QtWebEngineWidgets import QWebEngineView as _WEV  # noqa: F401

from core import settings
from ui.main_window import BooruGui

from ui.style import colors


def main():
    import ctypes
    # Distinct AppUserModelID so the taskbar groups and icons correctly.
    try:
        myappid = 'esef.boorubrowser.app.1'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        logging.debug("SetCurrentProcessExplicitAppUserModelID failed", exc_info=True)

    from core.async_loop import start as start_async_loop
    start_async_loop()

    settings.manager.initialize()

    # Avoids "virtualization" errors on some systems.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    
    # PyInstaller extracts assets to sys._MEIPASS; from source use the repo.
    _asset_base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))

    icon_path = _asset_base / "ui" / "assets" / "appico.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    qss_path = _asset_base / "ui" / "assets" / "theme.qss"
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

    thumb_cache.shutdown()
    engines.shutdown()

    # Close clients and sessions on the global loop they were created on.
    from core.async_loop import run as async_run, stop as stop_async_loop
    from cloudflare_bypasser import close_all_sessions
    try:
        async_run(thumb_client.close_all())
        async_run(close_all_sessions())
    except Exception:
        logging.debug("Shutdown cleanup failed", exc_info=True)
    finally:
        stop_async_loop()

    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        import sys
        try:
            from core.app_paths import data_dir
            crash_file = data_dir() / "FATAL_CRASH.txt"
        except Exception:
            import tempfile
            from pathlib import Path
            crash_file = Path(tempfile.gettempdir()) / "BooruBrowser_FATAL_CRASH.txt"
        with open(crash_file, "w", encoding="utf-8") as f:
            f.write("Application failed to start entirely!\n")
            traceback.print_exc(file=f)
        sys.exit(1)