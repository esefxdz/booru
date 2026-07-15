"""
updater/checker.py — Checks GitHub Releases for a newer version.

Runs in a background QThread.  Emits ``update_available`` if the latest
GitHub release tag is greater than the local version.  Designed for a
portable app — no binary replacement, just notification + link.
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from updater.version import __version__

log = logging.getLogger("updater")

# ── Default check URL — your GitHub Releases API ──────────────────
# Format: https://api.github.com/repos/OWNER/REPO/releases/latest
# Returns JSON with "tag_name", "html_url", "body", etc.
_DEFAULT_RELEASES_URL = "https://api.github.com/repos/esefxdz/booru/releases/latest"

# ── HTTP timeout (seconds) ────────────────────────────────────────
_TIMEOUT = 10


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Worker thread                                                      ║
# ╚══════════════════════════════════════════════════════════════════════╝

class _CheckThread(QThread):
    """Fetch the latest release tag from GitHub in a background thread."""
    finished = pyqtSignal(object)  # emits dict or None

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    def run(self) -> None:
        try:
            req = urllib.request.Request(
                self._url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "BooruBrowser",
                },
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                self.finished.emit(json.loads(resp.read().decode("utf-8")))
        except Exception:
            log.debug("Update check failed", exc_info=True)
            self.finished.emit(None)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Public updater                                                     ║
# ╚══════════════════════════════════════════════════════════════════════╝

class Updater(QObject):
    """
    Non-blocking update checker for a portable GitHub-distributed app.

    Usage::

        updater = Updater(parent)
        updater.update_available.connect(
            lambda ver, url, notes: print(f"New version: {ver}")
        )
        updater.check()
    """

    update_available = pyqtSignal(str, str, str)  # version, download_url, notes

    def __init__(self, parent: QObject | None = None, releases_url: str = _DEFAULT_RELEASES_URL) -> None:
        super().__init__(parent)
        self._releases_url = releases_url
        self._thread: _CheckThread | None = None

    def check(self) -> None:
        """Start a background update check.  No-op if already running."""
        if self._thread is not None and self._thread.isRunning():
            return
        self._thread = _CheckThread(self._releases_url)
        self._thread.finished.connect(self._on_result)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    # ── Internal ──────────────────────────────────────────────────

    def _on_result(self, data: dict | None) -> None:
        if data is None:
            return
        remote = _tag_to_version(data.get("tag_name", ""))
        if not remote or not _is_newer(remote, __version__):
            return
        url = data.get("html_url", "")
        notes = data.get("body", "")
        log.info("Update available: %s → %s", __version__, remote)
        self.update_available.emit(remote, url, notes)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tag_to_version(tag: str) -> str:
    """Strip a leading 'v' from a release tag, e.g. 'v1.2.0' → '1.2.0'."""
    tag = tag.strip()
    if tag.lower().startswith("v"):
        return tag[1:]
    return tag


def _parse_version(v: str) -> tuple[int, ...]:
    parts: list[int] = []
    for segment in v.replace("-", ".").replace("_", ".").split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            break
    return tuple(parts)


def _is_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)
