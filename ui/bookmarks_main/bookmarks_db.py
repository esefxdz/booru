import os
import json
import sqlite3
import logging
from pathlib import Path

_SETTINGS_DIR = Path(os.environ.get("APPDATA", ".")) / "BooruBrowser"
_DB_FILE = _SETTINGS_DIR / "bookmarks.db"

class BookmarksDB:
    def __init__(self):
        self.db_path = _DB_FILE
        self._init_db()
        self._migrate_legacy_json()

    def _migrate_legacy_json(self):
        legacy_file = _SETTINGS_DIR / "bookmarks.json"
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
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT 1 FROM bookmarks WHERE id = ?", (pid,))
            return cursor.fetchone() is not None

    def add_bookmark(self, post: dict):
        raw_id = post.get("id")
        if raw_id is None:
            return
        pid = str(raw_id)
        if not pid:
            return

        booru = post.get("_booru", "unknown")
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO bookmarks (id, booru, post_data) VALUES (?, ?, ?)",
                (pid, booru, json.dumps(post))
            )

    def remove_bookmark(self, post_id: str):
        pid = str(post_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM bookmarks WHERE id = ?", (pid,))

    def get_all_bookmarks(self) -> list:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT post_data FROM bookmarks ORDER BY added_at DESC")
            results = []
            for row in cursor:
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
