"""
ui/autocomplete/tag_cache.py

Local SQLite tag cache for instant, offline-capable autocomplete.
Stores tags per-booru and supports fuzzy/substring matching so
queries like "girl" can match "1girl" without a network round-trip.

Populated automatically from network autocomplete results.
"""
import sqlite3
import os
import threading
import shutil
import logging
from pathlib import Path

from ui.settings_view.manager import BASE_DIR
_DB_PATH = BASE_DIR / "tag_cache.db"
# Legacy path — only used for one-time migration
_LEGACY_DB = Path(os.environ.get("APPDATA", ".")) / "BooruBrowser" / "tag_cache.db"

_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Return a thread-local SQLite connection (one per thread)."""
    if not hasattr(_local, "conn") or _local.conn is None:
        if not _DB_PATH.exists() and _LEGACY_DB.exists():
            try:
                _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(_LEGACY_DB, _DB_PATH)
                _LEGACY_DB.unlink(missing_ok=True)
                logging.info("[autocomplete] Migrated tag_cache.db from %%APPDATA%%")
            except Exception as e:
                logging.warning("[autocomplete] Could not migrate legacy tag_cache.db: %s", e)

        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(_DB_PATH), timeout=2.0)
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                booru   TEXT    NOT NULL,
                name    TEXT    NOT NULL,
                type    TEXT    NOT NULL DEFAULT 'general',
                count   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (booru, name)
            )
        """)
        _local.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tags_lookup
            ON tags (booru, name COLLATE NOCASE)
        """)
        _local.conn.commit()
    return _local.conn


def store_tags(booru: str, tags: list[dict]) -> None:
    """Upsert a batch of tags into the cache.

    Each tag dict must have keys: name, type, count.
    """
    if not tags:
        return
    conn = _conn()
    conn.executemany(
        """INSERT INTO tags (booru, name, type, count)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(booru, name) DO UPDATE SET
               type  = excluded.type,
               count = excluded.count""",
        [(booru, t["name"], t.get("type", "general"), t.get("count", 0)) for t in tags if t.get("name")]
    )
    conn.commit()


def search_tags(booru: str, prefix: str, limit: int = 15) -> list[dict]:
    """Fuzzy-search the local cache.

    Matches any tag whose name *contains* the prefix as a substring,
    ordered by post count descending.  e.g. "girl" → "1girl", "girl", …
    """
    conn = _conn()
    rows = conn.execute(
        """SELECT name, type, count FROM tags
           WHERE booru = ? AND name LIKE ?
           ORDER BY count DESC
           LIMIT ?""",
        (booru, f"%{prefix}%", limit)
    ).fetchall()
    return [{"name": r[0], "type": r[1], "count": r[2]} for r in rows]
