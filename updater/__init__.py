"""
updater — Lightweight update-notification for a portable app.

Uses the GitHub Releases API to check if a newer version exists.
Shows a subtle status-bar notification — never downloads or replaces
files (the app is portable, users update manually).
"""

from updater.version import __version__
from updater.checker import Updater

__all__ = ["__version__", "Updater"]
