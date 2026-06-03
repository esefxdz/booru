"""
ui/settings_view/__init__.py

Exports the SettingsView page widget and the global settings manager.
"""
from ui.settings_view.settings_view import SettingsView
from ui.settings_view.manager import (
    manager,
    VERSION,
    SEARCH_LIMIT,
    TIMEOUT,
    DOWNLOAD_DIR,
    DEFAULT_HEADERS,
    BASE_DIR,
    _SETTINGS_DIR
)

__all__ = [
    "SettingsView",
    "manager",
    "VERSION",
    "SEARCH_LIMIT",
    "TIMEOUT",
    "DOWNLOAD_DIR",
    "DEFAULT_HEADERS",
    "BASE_DIR",
    "_SETTINGS_DIR"
]
