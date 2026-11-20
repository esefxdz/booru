"""Crash- and race-safe file writes. Read-modify-write callers still need their own lock."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

# Antivirus/indexer can briefly lock fresh files on Windows (PermissionError on replace).
_REPLACE_RETRIES = 10
_REPLACE_DELAY = 0.05


def atomic_write_text(path, text: str, encoding: str = "utf-8") -> None:
    """Atomically replace *path* with *text*. Raises OSError on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(_REPLACE_DELAY * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
