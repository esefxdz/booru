"""
ui/hotkeys.py — Global keyboard shortcuts for the main window.

Extracted from BooruGui._setup_hotkeys so shortcuts live in one
place and can be registered / changed without touching the window.
"""

from __future__ import annotations

from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtCore import QObject


class HotkeyManager(QObject):
    """Owns QShortcut objects for the application window.

    Usage
    -----
        hotkeys = HotkeyManager(window)
        hotkeys.register("Ctrl+F", search_bar.entry.setFocus)
        hotkeys.register("Right",  lambda: controller.change_page(1))
    """

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._shortcuts: list[QShortcut] = []

    def register(self, keys: str, callback) -> QShortcut:
        """Create a QShortcut that triggers *callback* when *keys* is pressed.

        Returns the shortcut so callers can call ``.setEnabled(False)``
        if they need to temporarily disable it.
        """
        shortcut = QShortcut(QKeySequence(keys), self.parent())
        shortcut.activated.connect(callback)
        self._shortcuts.append(shortcut)
        return shortcut

    def clear(self) -> None:
        """Remove all registered shortcuts."""
        for sc in self._shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts.clear()
