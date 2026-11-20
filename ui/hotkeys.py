from __future__ import annotations

from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtCore import QObject


class HotkeyManager(QObject):

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._shortcuts: list[QShortcut] = []

    def register(self, keys: str, callback) -> QShortcut:
        """Register a shortcut and return it so callers can disable it."""
        shortcut = QShortcut(QKeySequence(keys), self.parent())
        shortcut.activated.connect(callback)
        self._shortcuts.append(shortcut)
        return shortcut

    def clear(self) -> None:
        for sc in self._shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts.clear()
