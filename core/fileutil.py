"""
fileutil.py — crash- and race-safe file writes for user data files.

``atomic_write_text`` writes to a *unique* temp file in the target's folder,
fsyncs it, then ``os.replace``s it over the target. A crash mid-write leaves
the old file intact, and two writers can never truncate each other's temp
file (the old code used one fixed ``name.tmp`` per file).

Callers that do read-modify-write must still hold their own lock around the
whole cycle; this only makes the final write itself safe.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

# On Windows, antivirus / Search indexer briefly open freshly written files,
# which makes os.replace fail with PermissionError (WinError 5/32).
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
