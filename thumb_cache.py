"""
thumb_cache.py — Persistent SQLite thumbnail cache.

Survives app restarts. Falls through to network on miss.
Key: "{booru}:{post_id}:{res}"  (same as in-memory key, serialized)
"""
import sqlite3
import time
from pathlib import Path

from ui import settings_view as settings

_DB_PATH: Path = None
_MAX_BYTES = 500 * 1024 * 1024  # 500 MB default limit


def _db() -> sqlite3.Connection:
    global _DB_PATH
    if _DB_PATH is None:
        cache_dir = Path(settings._SETTINGS_DIR) / "thumb_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        _DB_PATH = cache_dir / "cache.db"

    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS thumbs (
            key       TEXT PRIMARY KEY,
            data      BLOB NOT NULL,
            created   INTEGER NOT NULL
        )
    """)
    conn.commit()
    return conn


def get(key: str) -> bytes | None:
    try:
        conn = _db()
        row = conn.execute("SELECT data FROM thumbs WHERE key=?", (key,)).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        print(f"[thumb_cache] get error: {e}")
        return None


def put(key: str, data: bytes) -> None:
    try:
        conn = _db()
        conn.execute(
            "INSERT OR REPLACE INTO thumbs (key, data, created) VALUES (?,?,?)",
            (key, data, int(time.time())),
        )
        conn.commit()
        _evict_if_needed(conn)
        conn.close()
    except Exception as e:
        print(f"[thumb_cache] put error: {e}")


def _evict_if_needed(conn: sqlite3.Connection) -> None:
    """Delete oldest rows if total DB size exceeds the limit."""
    try:
        total = conn.execute("SELECT SUM(LENGTH(data)) FROM thumbs").fetchone()[0] or 0
        if total > _MAX_BYTES:
            # Delete oldest 10% to avoid thrashing
            target = int(_MAX_BYTES * 0.9)
            while total > target:
                row = conn.execute(
                    "SELECT key, LENGTH(data) FROM thumbs ORDER BY created ASC LIMIT 1"
                ).fetchone()
                if not row:
                    break
                conn.execute("DELETE FROM thumbs WHERE key=?", (row[0],))
                total -= row[1]
            conn.commit()
    except Exception:
        pass


def clear() -> None:
    """Wipe all cached thumbnails."""
    try:
        conn = _db()
        conn.execute("DELETE FROM thumbs")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[thumb_cache] clear error: {e}")
