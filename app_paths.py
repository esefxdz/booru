"""
app_paths.py — where BooruBrowser keeps user data.

Portable by default: data lives next to the exe (or the repo root when run
from source), so the whole folder can be moved to a USB stick.

That folder is not usable when the exe sits in Program Files or another
read-only location (the app used to crash before showing a window), or when
it was started from inside a zip / a temp folder (data would be written to a
directory Windows deletes later). In those cases data goes to
``%LOCALAPPDATA%\\BooruBrowser`` instead.

``data_dir()`` is computed once per process and logged at startup.
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path

APP_NAME = "BooruBrowser"


def app_dir() -> Path:
    """Folder that holds the exe (frozen) or the source tree."""
    if getattr(sys, "frozen", False):
        return Path(os.path.dirname(sys.executable)).resolve()
    return Path(__file__).resolve().parent


def fallback_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME") \
        or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


def _is_temporary(path: Path) -> bool:
    """True for %TEMP% (where Explorer runs an exe opened inside a zip)."""
    try:
        tmp = Path(tempfile.gettempdir()).resolve()
        return path == tmp or tmp in path.parents
    except OSError:
        return False


def _is_writable(path: Path) -> bool:
    """Actually try to create a file (os.access lies on Windows ACLs)."""
    probe = path / f".write-test-{uuid.uuid4().hex}"
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("x")
        probe.unlink()
        return True
    except OSError:
        return False


def choose_data_dir(candidate: Path, fallback: Path) -> tuple[Path, str]:
    """Return (dir, reason). Pure apart from the write probe, so it is testable."""
    if _is_temporary(candidate):
        reason = "app folder is a temporary folder (run from inside a zip?)"
    elif not _is_writable(candidate):
        reason = "app folder is not writable"
    else:
        return candidate, "portable (next to the app)"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback, reason


@lru_cache(maxsize=1)
def data_dir() -> Path:
    path, reason = choose_data_dir(app_dir(), fallback_dir())
    _chosen_reason[0] = reason
    return path


_chosen_reason = ["not chosen yet"]


def data_dir_reason() -> str:
    data_dir()
    return _chosen_reason[0]
