import os
import sys

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

from ui import colors

# ── Discord-style dark theme ──────────────────────────────────────────────
DISCORD_QSS = f"""
/* ── Base ─────────────────────────────────────────── */
* {{
    font-family: 'Segoe UI', 'Whitney', 'Helvetica Neue', Arial, sans-serif;
    font-size: 14px;
    outline: none;
}}
QMainWindow, QDialog {{
    background-color: {colors.MAIN_BG};
    color: {colors.TEXT_SECONDARY};
}}
QWidget {{
    color: {colors.TEXT_SECONDARY};
}}
QScrollArea, QFrame {{
    background-color: transparent;
}}

/* ── Buttons ───────────────────────────────────────── */
QPushButton {{
    background-color: {colors.BUTTON_BG};
    color: {colors.TEXT_SECONDARY};
    border: 1px solid {colors.BUTTON_HOVER};
    border-radius: 4px;
    padding: 6px 12px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {colors.BUTTON_HOVER};
    border: 1px solid {colors.ACCENT};
}}
QPushButton:pressed {{
    background-color: {colors.BUTTON_PRESSED};
}}

/* ── Input ─────────────────────────────────────────── */
QLineEdit {{
    background-color: {colors.INPUT_BG};
    color: {colors.TEXT_PRIMARY};
    border: 1px solid {colors.BUTTON_BG};
    border-radius: 4px;
    padding: 6px 10px;
    selection-background-color: {colors.ACCENT};
}}
QLineEdit:focus {{
    border: 1px solid {colors.ACCENT};
    background-color: {colors.MAIN_BG};
}}

/* ── Dialogs ───────────────────────────────────────── */
QDialog {{
    background-color: {colors.MODAL_BG};
}}
QLabel {{
    color: {colors.TEXT_SECONDARY};
    background: transparent;
}}

/* ── Combo / Drop-down ─────────────────────────────── */
QComboBox {{
    background-color: {colors.INPUT_BG};
    color: {colors.TEXT_SECONDARY};
    border: 1px solid {colors.BUTTON_BG};
    border-radius: 4px;
    padding: 5px 10px;
}}
QComboBox QAbstractItemView {{
    background-color: {colors.INPUT_BG};
    color: {colors.TEXT_SECONDARY};
    selection-background-color: {colors.ACCENT};
    border: 1px solid {colors.BUTTON_BG};
}}

/* ── Scroll bars (global) ─────────────────────────── */
QScrollBar:vertical {{
    background: {colors.MAIN_BG};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {colors.BUTTON_BG};
    border-radius: 4px;
    min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{
    background: {colors.ACCENT};
}}
QScrollBar::handle:vertical:pressed {{
    background: {colors.ACCENT_HOVER};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: none;
    height: 0;
}}

QScrollBar:horizontal {{
    background: {colors.MAIN_BG};
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {colors.BUTTON_BG};
    border-radius: 4px;
    min-width: 40px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {colors.ACCENT};
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{
    background: none;
    width: 0;
}}

/* ── Splitter ──────────────────────────────────────── */
QSplitter::handle {{
    background-color: {colors.INPUT_BG};
    width: 2px;
}}

/* ── Tool tips ─────────────────────────────────────── */
QToolTip {{
    background-color: {colors.MAIN_BG};
    color: {colors.TEXT_SECONDARY};
    border: 1px solid {colors.ACCENT};
    border-radius: 4px;
    padding: 4px 8px;
}}
"""


def _setup_logging():
    """Wire up rotating file logs so crashes are diagnosable in packaged builds."""
    import logging
    from logging.handlers import RotatingFileHandler
    from pathlib import Path

    log_dir = Path(os.environ.get("APPDATA", ".")) / "BooruBrowser" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=5 * 1024 * 1024,   # 5 MB per file
        backupCount=3,               # keep last 3 rotated files
        encoding="utf-8",
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[handler, logging.StreamHandler()],  # file + console (when available)
    )


def main():
    _setup_logging()

    settings.manager.load()
    settings.manager.load_bookmarks()

    # Share contexts to prevent "virtualization" errors on some systems
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    app.setStyleSheet(DISCORD_QSS)
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