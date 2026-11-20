"""Update notification via the GitHub Releases API; never downloads or replaces files."""

from updater.version import __version__
from updater.checker import Updater

__all__ = ["__version__", "Updater"]
