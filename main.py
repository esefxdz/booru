import os
import sys

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import traceback
import thumb_cache
import download_images.engines as engines
import download_images.thumb_client as thumb_client

def _setup_logging():
    """Wire up rotating file logs so crashes are diagnosable in packaged builds."""
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

    # Silence noisy loggers that spam every HTTP request / retry
    for noisy in (
        "httpx", "httpcore", "h2", "urllib3", "curl_cffi",
        "asyncio",
    ):
        logging.getLogger(noisy).setLevel(logging.ERROR)

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        logging.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))
        
        # Show a critical error dialog so the user knows what crashed
        try:
            if QApplication.instance():
                tb = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Icon.Critical)
                msg.setWindowTitle("Fatal Error")
                msg.setText("The application encountered an unrecoverable error and must close.\n\n"
                            f"Check the log at: {log_file}")
                msg.setDetailedText(tb)
                msg.exec()
        except Exception:
            logging.critical("Could not show error dialog", exc_info=True)

    sys.excepthook = handle_exception

_setup_logging()

# ── Write a startup marker so we can confirm logging works ────────
logging.info("BooruBrowser starting (frozen=%s)", getattr(sys, 'frozen', False))

# ── Catch Qt-level messages (C++ crashes, qFatal, etc.) ──────────
# These bypass Python's exception system and would otherwise kill the
# app silently.  We log them so they appear in error.txt.
def _qt_message_handler(mode, context, message):
    if mode == 4:  # QtFatalMsg — would abort() without this
        logging.critical("Qt fatal: %s", message)
    elif mode == 3:  # QtCriticalMsg
        logging.error("Qt critical: %s", message)
    else:
        logging.debug("Qt [%d]: %s", mode, message)

from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
qInstallMessageHandler(_qt_message_handler)

# Disable GPU hardware acceleration in WebEngine to prevent black screens on Windows
# without having to disable the Chromium sandbox (--no-sandbox).
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtCore import Qt

# 4.1 High-DPI & Scaling Support
if hasattr(Qt.HighDpiScaleFactorRoundingPolicy, "PassThrough"):
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

# WebEngine MUST be imported before QApplication is created.
from PyQt6.QtWebEngineWidgets import QWebEngineView as _WEV  # noqa: F401

from ui import settings_view as settings
from gui import BooruGui

import ui.colors as colors

# ── Main Entry ──────────────────────────────────────────────





def main():
    import ctypes
    # Tell Windows this is a distinct app so the taskbar groups it correctly and uses our icon
    try:
        myappid = 'esef.boorubrowser.app.1'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        logging.debug("SetCurrentProcessExplicitAppUserModelID failed", exc_info=True)

    from async_loop import start as start_async_loop
    start_async_loop()

    settings.manager.initialize()

    # Share contexts to prevent "virtualization" errors on some systems
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)

    # ── WebEngine warmup ────────────────────────────────────────
    # Force Chromium to initialize NOW instead of lazily on first
    # user interaction.  If the GPU/driver/sandbox causes a crash
    # during init, it happens here with a visible error dialog
    # instead of randomly when the user clicks something.
    try:
        from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
        _warmup_profile = QWebEngineProfile("_startup_warmup", app)
        _warmup_page = QWebEnginePage(_warmup_profile, None)
        # Give Chromium a moment to spawn, then clean up
        _warmup_page.deleteLater()
        _warmup_profile.deleteLater()
        logging.info("WebEngine warmup OK")
    except Exception:
        logging.warning("WebEngine warmup failed", exc_info=True)
    
    # When frozen by PyInstaller, assets live in sys._MEIPASS (the temp
    # extraction dir).  At runtime we look there first, then fall back to
    # the source-tree location so running from source still works.
    _asset_base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))

    icon_path = _asset_base / "appico.png"
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

    # ── Clean shutdown: close the SQLite cache connection ──────────

    thumb_cache.shutdown()
    engines.shutdown()

    # Close the persistent thumbnail httpx connection pool and cached
    # CF bypass sessions.  All async work now runs on the shared global
    # event loop, so everything is submitted to that same loop — no
    # cross-loop errors.
    from async_loop import run as async_run, stop as stop_async_loop
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
        with open("FATAL_CRASH.txt", "w", encoding="utf-8") as f:
            f.write("Application failed to start entirely!\n")
            traceback.print_exc(file=f)
        sys.exit(1)