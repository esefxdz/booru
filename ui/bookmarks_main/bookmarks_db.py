import os
import shutil
import json
import sqlite3
import logging
import threading
from pathlib import Path

from ui.settings_view.manager import BASE_DIR
_DB_FILE = BASE_DIR / "bookmarks.db"
# Legacy path — only used for one-time migration
_LEGACY_DB = Path(os.environ.get("APPDATA", ".")) / "BooruBrowser" / "bookmarks.db"

class BookmarksDB:
    def __init__(self):
        self.db_path = _DB_FILE
        self._conn = None
        self._lock = threading.Lock()
        self._migrate_legacy_db()
        self._init_db()
        self._migrate_legacy_json()

    def _migrate_legacy_db(self):
        """One-time: copy bookmarks.db from %APPDATA% to the app folder."""
        if not self.db_path.exists() and _LEGACY_DB.exists():
            try:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(_LEGACY_DB, self.db_path)
                _LEGACY_DB.unlink(missing_ok=True)
                logging.info("[bookmarks] Migrated bookmarks.db from %%APPDATA%%")
            except Exception as e:
                logging.warning("[bookmarks] Could not migrate legacy bookmarks.db: %s", e)

    def _get_conn(self):
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _migrate_legacy_json(self):
        legacy_file = _DB_FILE.parent / "bookmarks.json"
        if not legacy_file.exists():
            return
        
        try:
            with open(legacy_file, "r", encoding="utf-8") as f:
                old_bookmarks = json.load(f)
            
            for post in old_bookmarks:
                self.add_bookmark(post)
                
            legacy_file.rename(legacy_file.parent / (legacy_file.name + ".migrated"))
            logging.info(f"[bookmarks_db] Migrated {len(old_bookmarks)} legacy bookmarks to SQLite.")
        except Exception as e:
            logging.error(f"[bookmarks_db] Failed to migrate legacy bookmarks.json: {e}")

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            conn.execute('''
                CREATE TABLE IF NOT EXISTS bookmarks (
                    id TEXT PRIMARY KEY,
                    booru TEXT,
                    post_data TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
    def is_post_bookmarked(self, post_id: str) -> bool:
        pid = str(post_id)
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute("SELECT 1 FROM bookmarks WHERE id = ?", (pid,))
            return cursor.fetchone() is not None

    def are_posts_bookmarked(self, post_ids: list[str]) -> set[str]:
        if not post_ids:
            return set()
        
        # SQLite maximum bound parameters is typically 999, so we chunk it just in case
        chunk_size = 900
        bookmarked = set()
        
        with self._lock:
            conn = self._get_conn()
            for i in range(0, len(post_ids), chunk_size):
                chunk = [str(pid) for pid in post_ids[i:i + chunk_size]]
                placeholders = ",".join("?" * len(chunk))
                cursor = conn.execute(f"SELECT id FROM bookmarks WHERE id IN ({placeholders})", chunk)
                bookmarked.update(row[0] for row in cursor.fetchall())
                
        return bookmarked

    def add_bookmark(self, post: dict):
        raw_id = post.get("id")
        if raw_id is None:
            return
        pid = str(raw_id)
        if not pid:
            return

        booru = post.get("_booru", "unknown")
        
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO bookmarks (id, booru, post_data) VALUES (?, ?, ?)",
                (pid, booru, json.dumps(post))
            )
            conn.commit()

    def remove_bookmark(self, post_id: str):
        pid = str(post_id)
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM bookmarks WHERE id = ?", (pid,))
            conn.commit()

    def get_all_bookmarks(self) -> list:
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute("SELECT post_data FROM bookmarks ORDER BY added_at DESC")
            results = []
            for row in cursor.fetchall():
                try:
                    results.append(json.loads(row[0]))
                except json.JSONDecodeError:
                    pass
            return results

    def load_bookmarks(self):
        """No-op compatibility method for code that previously forced a JSON reload."""
        pass

# Singleton instance
db = BookmarksDB()
