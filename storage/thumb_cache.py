"""Two-tier thumbnail cache: in-memory LRU (L1) over SQLite on disk (L2); one lock per tier."""

from __future__ import annotations
import logging

import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from core import settings

_L1_MAX_BYTES: int = 128 * 1024 * 1024    # 128 MB
_L2_MAX_BYTES: int = 1024 * 1024 * 1024  # 1 GB
_L2_EVICT_CHECK_EVERY: int = 100          # eviction scan every N writes
_L2_EVICT_RATIO: float = 0.10             # fraction evicted when over budget


# Not functools.lru_cache: eviction is by bytes, and clear/stats are needed.
class _L1:

    __slots__ = ("_data", "_bytes", "_max_bytes")

    def __init__(self, max_bytes: int = _L1_MAX_BYTES) -> None:
        self._data: OrderedDict[str, bytes] = OrderedDict()
        self._bytes: int = 0
        self._max_bytes: int = max_bytes

    def get(self, key: str) -> bytes | None:
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def put(self, key: str, data: bytes) -> None:
        size = len(data)

        if key in self._data:
            self._bytes -= len(self._data[key])
            self._data.move_to_end(key)
            self._data[key] = data
        else:
            self._data[key] = data

        self._bytes += size

        while self._bytes > self._max_bytes and self._data:
            _oldest_key, oldest_val = self._data.popitem(last=False)
            self._bytes -= len(oldest_val)

    def clear(self) -> None:
        self._data.clear()
        self._bytes = 0

    @property
    def entry_count(self) -> int:
        return len(self._data)

    @property
    def byte_count(self) -> int:
        return self._bytes


class _L2:

    def __init__(self, db_path: Path, max_bytes: int = _L2_MAX_BYTES) -> None:
        self._db_path = db_path
        self._max_bytes = max_bytes
        self._conn: sqlite3.Connection | None = None
        self._pending_touches: set[str] = set()
        self._puts_since_evict_check = 0

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn

        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,    # guarded by the caller's lock
        )

        self._conn.execute("PRAGMA journal_mode=WAL")

        # Old schema lacks size_bytes/last_access: drop it (it's only a cache).
        try:
            cols = {
                row[1] for row in
                self._conn.execute("PRAGMA table_info(thumbs)").fetchall()
            }
            if cols and "size_bytes" not in cols:
                logging.info("[thumb_cache] Migrating old cache schema...")
                self._conn.execute("DROP TABLE thumbs")
                self._conn.commit()
        except Exception:
            pass  # no table yet

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS thumbs (
                key          TEXT    PRIMARY KEY,
                data         BLOB   NOT NULL,
                size_bytes   INTEGER NOT NULL,
                created_at   INTEGER NOT NULL,
                last_access  INTEGER NOT NULL
            )
        """)

        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_thumbs_access
            ON thumbs (last_access)
        """)

        self._conn.commit()
        return self._conn

    def get(self, key: str) -> bytes | None:
        try:
            conn = self._ensure_conn()
            row = conn.execute(
                "SELECT data FROM thumbs WHERE key = ?", (key,)
            ).fetchone()

            if row is None:
                return None

            # Batch the last_access update instead of writing on every read.
            self._pending_touches.add(key)
            if len(self._pending_touches) >= 50:
                self._flush_touches(conn)

            return row[0]

        except Exception as e:
            logging.error(f"[thumb_cache] L2 get error: {e}")
            return None

    def put(self, key: str, data: bytes) -> None:
        try:
            conn = self._ensure_conn()
            now = int(time.time())
            conn.execute(
                """INSERT OR REPLACE INTO thumbs
                   (key, data, size_bytes, created_at, last_access)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, data, len(data), now, now),
            )
            
            self._flush_touches(conn)
            conn.commit()

            self._puts_since_evict_check += 1
            if self._puts_since_evict_check >= _L2_EVICT_CHECK_EVERY:
                self._puts_since_evict_check = 0
                self._maybe_evict(conn)

        except Exception as e:
            logging.error(f"[thumb_cache] L2 put error: {e}")

    def _maybe_evict(self, conn: sqlite3.Connection) -> None:
        try:
            total = conn.execute(
                "SELECT SUM(size_bytes) FROM thumbs"
            ).fetchone()[0] or 0

            if total <= self._max_bytes:
                return

            count = conn.execute(
                "SELECT COUNT(*) FROM thumbs"
            ).fetchone()[0] or 0

            drop_count = max(1, int(count * _L2_EVICT_RATIO))

            conn.execute("""
                DELETE FROM thumbs
                WHERE key IN (
                    SELECT key FROM thumbs
                    ORDER BY last_access ASC
                    LIMIT ?
                )
            """, (drop_count,))
            conn.commit()

        except Exception:
            pass  # eviction failure is non-fatal

    def clear(self) -> None:
        try:
            conn = self._ensure_conn()
            conn.execute("DELETE FROM thumbs")
            conn.execute("VACUUM")          # reclaim disk space
            conn.commit()
        except Exception as e:
            logging.error(f"[thumb_cache] L2 clear error: {e}")

    def stats(self) -> dict:
        try:
            conn = self._ensure_conn()
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM thumbs"
            ).fetchone()
            return {"entries": row[0], "bytes": row[1]}
        except Exception:
            return {"entries": 0, "bytes": 0}

    def _flush_touches(self, conn: sqlite3.Connection | None = None) -> None:
        if not self._pending_touches:
            return
        c = conn or self._ensure_conn()
        now = int(time.time())
        keys = list(self._pending_touches)
        self._pending_touches.clear()
        
        try:
            # Chunks of 900: SQLite bound-variable limit is 999.
            for i in range(0, len(keys), 900):
                chunk = keys[i:i+900]
                placeholders = ",".join("?" * len(chunk))
                c.execute(f"UPDATE thumbs SET last_access = ? WHERE key IN ({placeholders})", [now] + chunk)
            c.commit()
        except Exception as e:
            logging.error(f"[thumb_cache] L2 touch flush error: {e}")

    def close(self) -> None:
        if self._conn:
            try:
                self._flush_touches(self._conn)
                self._conn.close()
            except Exception:
                pass
            self._conn = None


_l1_lock = threading.Lock()   # in-memory dict only
_l2_lock = threading.Lock()   # SQLite disk I/O
_l1: _L1 | None = None
_l2: _L2 | None = None


def _init() -> tuple[_L1, _L2]:
    global _l1, _l2

    if _l1 is not None and _l2 is not None:
        return _l1, _l2

    cache_dir = Path(settings._SETTINGS_DIR) / "thumb_cache"
    db_path = cache_dir / "cache.db"

    _l1 = _L1(max_bytes=_L1_MAX_BYTES)
    _l2 = _L2(db_path=db_path, max_bytes=_L2_MAX_BYTES)

    return _l1, _l2


def get(key) -> bytes | None:
    key = str(key)

    # L1 has its own lock so a hit never waits on disk I/O.
    with _l1_lock:
        l1, _ = _init()
        data = l1.get(key)
        if data is not None:
            return data

    with _l2_lock:
        _, l2 = _init()
        data = l2.get(key)

    if data is not None:
        with _l1_lock:
            l1, _ = _init()
            l1.put(key, data)
        return data

    return None


def put(key, data: bytes) -> None:
    key = str(key)

    with _l1_lock:
        l1, _ = _init()
        l1.put(key, data)

    with _l2_lock:
        _, l2 = _init()
        l2.put(key, data)


def clear() -> None:
    with _l1_lock:
        l1, _ = _init()
        l1.clear()
    with _l2_lock:
        _, l2 = _init()
        l2.clear()


def stats() -> dict:
    with _l1_lock:
        l1, _ = _init()
        l1_entries = l1.entry_count
        l1_bytes = l1.byte_count
    with _l2_lock:
        _, l2 = _init()
        l2_stats = l2.stats()
    return {
        "l1_entries": l1_entries,
        "l1_bytes":   l1_bytes,
        "l2_entries": l2_stats["entries"],
        "l2_bytes":   l2_stats["bytes"],
    }


def shutdown() -> None:
    global _l1, _l2
    with _l1_lock:
        _l1 = None
    with _l2_lock:
        if _l2 is not None:
            _l2.close()
        _l2 = None
