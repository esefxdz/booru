"""Background check of the latest GitHub release against the local version."""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from updater.version import __version__

log = logging.getLogger("updater")

_DEFAULT_RELEASES_URL = "https://api.github.com/repos/esefxdz/booru/releases/latest"

_TIMEOUT = 10


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


class Updater(QObject):
    """Non-blocking update checker; emits ``update_available`` when a newer release exists."""

    update_available = pyqtSignal(str, str, str)  # version, download_url, notes

    def __init__(self, parent: QObject | None = None, releases_url: str = _DEFAULT_RELEASES_URL) -> None:
        super().__init__(parent)
        self._releases_url = releases_url
        self._thread: _CheckThread | None = None

    def check(self) -> None:
        """Start a background check; no-op if one is running."""
        if self._thread is not None and self._thread.isRunning():
            return
        self._thread = _CheckThread(self._releases_url)
        self._thread.finished.connect(self._on_result)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_result(self, data: dict | None) -> None:
        if data is None:
            return
        remote = _tag_to_version(data.get("tag_name", ""))
        if not remote or not _is_newer(remote, __version__):
            return
        url = data.get("html_url", "")
        # The button hands this to webbrowser.open(): only ever an https page
        # on github.com, never another scheme / protocol handler.
        from urllib.parse import urlparse
        parsed = urlparse(url if isinstance(url, str) else "")
        if parsed.scheme != "https" or parsed.hostname != "github.com":
            log.warning("Ignoring update with unexpected release URL %r", url)
            return
        notes = data.get("body", "")
        log.info("Update available: %s → %s", __version__, remote)
        self.update_available.emit(remote, url, notes)


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
