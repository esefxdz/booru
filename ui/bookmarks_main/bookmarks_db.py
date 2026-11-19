import shutil
import json
import sqlite3
import logging
import threading

from app_paths import legacy_appdata_dir
from ui.settings_view.manager import BASE_DIR
_DB_FILE = BASE_DIR / "bookmarks.db"

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
        legacy = legacy_appdata_dir() / "bookmarks.db"
        if not self.db_path.exists() and legacy.exists():
            try:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                # Copy (never move) so the original survives, and bring the
                # WAL/SHM sidecars so recent writes are not lost.
                for suffix in ("-wal", "-shm"):
                    side = legacy.with_name(legacy.name + suffix)
                    if side.exists():
                        shutil.copy2(side, self.db_path.with_name(self.db_path.name + suffix))
                shutil.copy2(legacy, self.db_path)
                logging.info("[bookmarks] Copied bookmarks.db from %APPDATA% (original kept)")
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
                    booru TEXT NOT NULL DEFAULT 'unknown',
                    id TEXT NOT NULL,
                    post_data TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (booru, id)
                )
            ''')
            try:
                self._migrate_to_composite_key(conn)
            except Exception:
                # Never let a failed migration stop the app from starting:
                # keep using the v1 table and retry on the next start.
                logging.exception("[bookmarks] Migration to a (booru, id) key failed; "
                                  "keeping the old table, will retry next start")

    @staticmethod
    def _migrate_to_composite_key(conn):
        """v1 keyed bookmarks on post id alone, so the same id on two boorus
        overwrote each other. Rebuild the table keyed on (booru, id) once,
        keeping the old table as bookmarks_v1_backup."""
        pk = [row[1] for row in sorted(
            (r for r in conn.execute("PRAGMA table_info(bookmarks)") if r[5]), key=lambda r: r[5])]
        if pk == ["booru", "id"]:
            return
        logging.info("[bookmarks] Migrating bookmarks table to a (booru, id) key")
        # sqlite3 does not BEGIN before DDL, so `with conn:` cannot roll back
        # CREATE TABLE. Manage the transaction explicitly instead.
        previous = conn.isolation_level
        conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                # leftover from an older failed run
                conn.execute("DROP TABLE IF EXISTS bookmarks_v2")
                conn.execute('''
                    CREATE TABLE bookmarks_v2 (
                        booru TEXT NOT NULL DEFAULT 'unknown',
                        id TEXT NOT NULL,
                        post_data TEXT,
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (booru, id)
                    )
                ''')
                conn.execute('''
                    INSERT OR IGNORE INTO bookmarks_v2 (booru, id, post_data, added_at)
                    SELECT COALESCE(NULLIF(booru, ''), 'unknown'), id, post_data, added_at
                    FROM bookmarks
                ''')
                conn.execute("DROP TABLE IF EXISTS bookmarks_v1_backup")
                conn.execute("ALTER TABLE bookmarks RENAME TO bookmarks_v1_backup")
                conn.execute("ALTER TABLE bookmarks_v2 RENAME TO bookmarks")
                conn.execute("COMMIT")
            except BaseException:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
        finally:
            conn.isolation_level = previous

    # Rows saved by very old versions have booru 'unknown'; they match any booru
    # so upgrading never makes an existing bookmark look un-bookmarked.

    def is_post_bookmarked(self, post_id: str, booru: str | None = None) -> bool:
        pid = str(post_id)
        with self._lock:
            conn = self._get_conn()
            if booru is None:
                cursor = conn.execute("SELECT 1 FROM bookmarks WHERE id = ?", (pid,))
            else:
                cursor = conn.execute(
                    "SELECT 1 FROM bookmarks WHERE id = ? AND booru IN (?, 'unknown')", (pid, booru))
            return cursor.fetchone() is not None

    def are_posts_bookmarked(self, post_ids: list[str], booru: str | None = None) -> set[str]:
        """Ids among *post_ids* that are bookmarked (on *booru*, if given)."""
        if not post_ids:
            return set()
        chunk_size = 900   # SQLite bound-parameter limit is 999
        bookmarked = set()
        with self._lock:
            conn = self._get_conn()
            for i in range(0, len(post_ids), chunk_size):
                chunk = [str(pid) for pid in post_ids[i:i + chunk_size]]
                placeholders = ",".join("?" * len(chunk))
                if booru is None:
                    cursor = conn.execute(
                        f"SELECT id FROM bookmarks WHERE id IN ({placeholders})", chunk)
                else:
                    cursor = conn.execute(
                        f"SELECT id FROM bookmarks WHERE id IN ({placeholders}) "
                        "AND booru IN (?, 'unknown')", chunk + [booru])
                bookmarked.update(row[0] for row in cursor.fetchall())
        return bookmarked

    def bookmarked_keys(self, posts: list[dict]) -> set[tuple[str, str]]:
        """``{(booru, id)}`` for the posts in *posts* that are bookmarked.

        Works for mixed lists (the bookmarks page shows several boorus).
        """
        ids = list({str(p.get("id")) for p in posts if p.get("id") is not None})
        if not ids:
            return set()
        rows: set[tuple[str, str]] = set()
        with self._lock:
            conn = self._get_conn()
            for i in range(0, len(ids), 900):
                chunk = ids[i:i + 900]
                placeholders = ",".join("?" * len(chunk))
                rows.update(conn.execute(
                    f"SELECT booru, id FROM bookmarks WHERE id IN ({placeholders})", chunk).fetchall())
        unknown_ids = {pid for b, pid in rows if b == "unknown"}
        keys = {(b, pid) for b, pid in rows if b != "unknown"}
        for p in posts:
            pid = str(p.get("id"))
            if pid in unknown_ids:
                keys.add((p.get("_booru") or "unknown", pid))
        return keys

    def add_bookmark(self, post: dict):
        raw_id = post.get("id")
        if raw_id is None:
            return
        pid = str(raw_id)
        if not pid:
            return
        booru = post.get("_booru") or "unknown"
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO bookmarks (booru, id, post_data) VALUES (?, ?, ?)",
                (booru, pid, json.dumps(post))
            )
            conn.commit()

    def remove_bookmark(self, post_id: str, booru: str | None = None):
        pid = str(post_id)
        with self._lock:
            conn = self._get_conn()
            if booru is None:
                conn.execute("DELETE FROM bookmarks WHERE id = ?", (pid,))
            else:
                conn.execute("DELETE FROM bookmarks WHERE id = ? AND booru IN (?, 'unknown')",
                             (pid, booru))
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
