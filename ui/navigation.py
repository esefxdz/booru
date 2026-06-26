"""
ui/navigation.py — Page router for the main QStackedWidget.

Extracted from BooruGui so the main window doesn't own every
page-transition detail.  Owns the stack widget and exposes a
single ``go(page)`` dispatch plus convenience methods the
sidebar buttons connect to.

Usage
-----
    nav = NavigationManager(stack, overlay, topbar, parent)
    nav.go("gallery")
    nav.go("settings")
"""

from __future__ import annotations

from PyQt6.QtWidgets import QStackedWidget
from PyQt6.QtCore import QObject


class NavigationManager(QObject):
    """Routes page-switch requests to the QStackedWidget.

    Also handles:
      - Dismissing the media overlay before switching away from gallery
      - Showing/hiding the top bar (search row) per page
    """

    def __init__(
        self,
        stack: QStackedWidget,
        overlay,
        topbar,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._stack = stack
        self._overlay = overlay
        self._topbar = topbar

        # Page index constants — must match the order widgets are added
        self.GALLERY = 0
        self.BLACKLIST = 1
        self.FAVORITES = 2
        self.SETTINGS = 3
        self.DOWNLOADS = 4
        self.CHEAT_SHEET = 5

    # ── Public API ──────────────────────────────────────────────

    def go(self, page: str) -> None:
        """Generic router.  Use the named helpers below."""
        dispatch = {
            "gallery":     self.go_gallery,
            "blacklist":   self.go_blacklist,
            "favorites":   self.go_favorites,
            "settings":    self.go_settings,
            "downloads":   self.go_downloads,
            "cheat_sheet": self.go_cheat_sheet,
        }
        fn = dispatch.get(page)
        if fn is not None:
            fn()

    def go_gallery(self) -> None:
        self._stack.setCurrentIndex(self.GALLERY)
        self._topbar.show()

    def go_blacklist(self) -> None:
        self._dismiss_overlay()
        self._stack.setCurrentIndex(self.BLACKLIST)
        self._topbar.hide()

    def go_favorites(self) -> None:
        self._dismiss_overlay()
        self._stack.setCurrentIndex(self.FAVORITES)
        self._topbar.hide()

    def go_settings(self) -> None:
        self._dismiss_overlay()
        self._stack.setCurrentIndex(self.SETTINGS)
        self._topbar.hide()

    def go_downloads(self) -> None:
        self._dismiss_overlay()
        self._stack.setCurrentIndex(self.DOWNLOADS)
        self._topbar.hide()

    def go_cheat_sheet(self) -> None:
        self._dismiss_overlay()
        self._stack.setCurrentIndex(self.CHEAT_SHEET)
        self._topbar.hide()

    def go_api_settings(self, name: str, parent) -> None:
        """API settings is dynamic — created on demand per booru."""
        self._dismiss_overlay()
        # Remove any previous instance
        for i in range(self._stack.count() - 1, self.CHEAT_SHEET + 1, -1):
            w = self._stack.widget(i)
            if w is not None and not isinstance(w, type(self._stack.widget(self.CHEAT_SHEET))):
                self._stack.removeWidget(w)
                w.deleteLater()
                break

        from ui.api_settings_view import APISettingsView
        view = APISettingsView(parent, name)
        self._stack.addWidget(view)
        self._stack.setCurrentWidget(view)
        self._topbar.hide()

    # ── Helpers ─────────────────────────────────────────────────

    def _dismiss_overlay(self) -> None:
        """Hide the media overlay before switching to a non-gallery page.

        The overlay is a plain child widget manually raise()'d on top.
        Switching the QStackedWidget page does NOT hide it automatically,
        so we must close it explicitly before every page transition.
        """
        if self._overlay is not None and self._overlay.isVisible():
            self._overlay.close_overlay()
