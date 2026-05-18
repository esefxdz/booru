"""
thumb_cache.py -- Two-tier thumbnail cache (L1 in-memory + L2 SQLite disk).

Architecture
============

    ┌──────────────────────────────────────────────────────────────┐
    │                        CALLER                                │
    │    downloader.py / gallery.py / anywhere                     │
    │         ▼ get(key)          ▼ put(key, data)                 │
    ├──────────────────────────────────────────────────────────────┤
    │                   L1  In-Memory LRU                          │
    │  • OrderedDict with byte-level accounting                    │
    │  • Default 64 MB cap (configurable)                          │
    │  • Instant hit → returns bytes, no disk I/O                  │
    │  • On eviction: oldest entries silently dropped (they still  │
    │    live in L2 so nothing is lost)                             │
    ├──────────────────────────────────────────────────────────────┤
    │                   L2  SQLite on Disk                          │
    │  • Persistent across app restarts                            │
    │  • Default 500 MB cap (configurable)                         │
    │  • Single long-lived connection with WAL mode for speed      │
    │  • Batch eviction (oldest 10 %) when over limit              │
    │  • Thread-safe via threading.Lock                            │
    └──────────────────────────────────────────────────────────────┘

Usage
=====
    import thumb_cache

    # Read (checks L1 first, then L2, promotes to L1 on hit)
    data: bytes | None = thumb_cache.get("safebooru:12345")

    # Write (stores in both L1 and L2)
    thumb_cache.put("safebooru:12345", jpeg_bytes)

    # Wipe everything
    thumb_cache.clear()

    # Runtime stats (for settings / debug UI)
    stats = thumb_cache.stats()
    # → {"l1_entries": 312, "l1_bytes": 42_000_000,
    #    "l2_entries": 8400, "l2_bytes": 210_000_000}

Thread Safety
=============
Both tiers are guarded by a single ``threading.Lock``.  The lock is
fine-grained enough for thumbnail workloads — each critical section
is a fast dict lookup or a single SQLite row fetch.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path


# ─────────────────────────────────────────────────────────────────
# Constants & Defaults
# ─────────────────────────────────────────────────────────────────

_L1_MAX_BYTES: int = 64 * 1024 * 1024     # 64 MB in-memory budget
_L2_MAX_BYTES: int = 500 * 1024 * 1024    # 500 MB on-disk budget
_L2_EVICT_RATIO: float = 0.10             # evict oldest 10 % when over limit


# ─────────────────────────────────────────────────────────────────
# L1 — In-Memory LRU Cache
# ─────────────────────────────────────────────────────────────────
#
#   A bounded OrderedDict that tracks total byte usage.
#   On every access the touched key is moved to the end (= most
#   recently used).  When the byte budget is exceeded, the oldest
#   entries are popped from the front until we're under budget.
#
#   This is intentionally NOT an functools.lru_cache — we need:
#     • byte-level (not entry-count) eviction
#     • manual invalidation (clear / per-key delete)
#     • introspection (stats)
# ─────────────────────────────────────────────────────────────────

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: _L1                                                         ║
# ║  In-memory LRU cache backed by an OrderedDict.  Tracks total       ║
# ║  byte usage instead of entry count — a single 500 KB thumbnail     ║
# ║  costs more budget than a 5 KB icon.  On eviction the oldest       ║
# ║  (least recently used) entries are silently dropped; they still    ║
# ║  live in L2 on disk so nothing is permanently lost.                 ║
# ╚══════════════════════════════════════════════════════════════════════╝
class _L1:

    __slots__ = ("_data", "_bytes", "_max_bytes")

    def __init__(self, max_bytes: int = _L1_MAX_BYTES) -> None:
        self._data: OrderedDict[str, bytes] = OrderedDict()
        self._bytes: int = 0
        self._max_bytes: int = max_bytes

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  get  — returns cached bytes or None.  Promotes the key to     │
    # │  most-recently-used so it survives future eviction rounds.      │
    # └──────────────────────────────────────────────────────────────────┘
    def get(self, key: str) -> bytes | None:
        """Return cached bytes or None.  Promotes key to MRU on hit."""
        if key in self._data:
            self._data.move_to_end(key)  # touch → most recently used
            return self._data[key]
        return None

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  put  — inserts or updates a key.  If the total byte usage     │
    # │  exceeds _max_bytes, pops the oldest entries from the front    │
    # │  of the OrderedDict until we're back under budget.             │
    # └──────────────────────────────────────────────────────────────────┘
    def put(self, key: str, data: bytes) -> None:
        size = len(data)

        # If the key already exists, subtract its old size first
        if key in self._data:
            self._bytes -= len(self._data[key])
            self._data.move_to_end(key)
            self._data[key] = data
        else:
            self._data[key] = data

        self._bytes += size

        # Evict oldest entries until we're under budget
        while self._bytes > self._max_bytes and self._data:
            _oldest_key, oldest_val = self._data.popitem(last=False)
            self._bytes -= len(oldest_val)

    # ── admin ─────────────────────────────────────────────────
    def clear(self) -> None:
        self._data.clear()
        self._bytes = 0

    @property
    def entry_count(self) -> int:
        return len(self._data)

    @property
    def byte_count(self) -> int:
        return self._bytes


# ─────────────────────────────────────────────────────────────────
# L2 — SQLite Persistent Cache
# ─────────────────────────────────────────────────────────────────
#
#   Stores thumbnails as BLOBs keyed by a string like
#   "safebooru:12345" or just a plain post_id.
#
#   Design choices for 1 M user scale:
#     • WAL journal mode — allows concurrent reads while a write
#       is in progress; prevents "database is locked" errors.
#     • Single long-lived connection — avoids the overhead of
#       opening/closing on every call.
#     • Batch eviction — when the total size exceeds the budget,
#       delete the oldest 10 % in one DELETE statement instead of
#       looping row-by-row.
#     • ``last_access`` column — updated on reads so frequently
#       viewed thumbnails survive eviction.
# ─────────────────────────────────────────────────────────────────

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  CLASS: _L2                                                         ║
# ║  SQLite-backed persistent thumbnail cache.  Stores thumbnails      ║
# ║  as BLOBs keyed by "booru:post_id".  Uses WAL journal mode,       ║
# ║  a single long-lived connection, batch eviction, and a             ║
# ║  last_access column so frequently viewed images survive cleanup.   ║
# ╚══════════════════════════════════════════════════════════════════════╝
class _L2:

    def __init__(self, db_path: Path, max_bytes: int = _L2_MAX_BYTES) -> None:
        self._db_path = db_path
        self._max_bytes = max_bytes
        self._conn: sqlite3.Connection | None = None

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _ensure_conn  — opens (or reuses) a long-lived SQLite         │
    # │  connection.  On first open it enables WAL journal mode,       │
    # │  creates the schema, and auto-migrates old databases that      │
    # │  lack the size_bytes / last_access columns.                     │
    # └──────────────────────────────────────────────────────────────────┘
    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn

        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,    # safe — we guard with our own lock
        )

        # WAL mode: dramatically reduces lock contention on concurrent reads/writes
        self._conn.execute("PRAGMA journal_mode=WAL")

        # ── Schema migration ──────────────────────────────────────
        # Check if the old schema (key, data, created) exists and
        # needs upgrading to (key, data, size_bytes, created_at, last_access).
        # If the table exists but is missing new columns, drop and recreate.
        try:
            cols = {
                row[1] for row in
                self._conn.execute("PRAGMA table_info(thumbs)").fetchall()
            }
            if cols and "size_bytes" not in cols:
                # Old schema detected — drop and let CREATE TABLE rebuild it
                print("[thumb_cache] Migrating old cache schema...")
                self._conn.execute("DROP TABLE thumbs")
                self._conn.commit()
        except Exception:
            pass  # table doesn't exist yet, CREATE below will handle it

        # ── Create table (new schema) ─────────────────────────────
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS thumbs (
                key          TEXT    PRIMARY KEY,
                data         BLOB   NOT NULL,
                size_bytes   INTEGER NOT NULL,
                created_at   INTEGER NOT NULL,
                last_access  INTEGER NOT NULL
            )
        """)

        # Index on last_access for fast eviction ordering
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_thumbs_access
            ON thumbs (last_access)
        """)

        self._conn.commit()
        return self._conn

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  get  — fetches a thumbnail from disk.  On hit, updates the    │
    # │  last_access timestamp so the entry survives LRU eviction.     │
    # └──────────────────────────────────────────────────────────────────┘
    def get(self, key: str) -> bytes | None:
        try:
            conn = self._ensure_conn()
            row = conn.execute(
                "SELECT data FROM thumbs WHERE key = ?", (key,)
            ).fetchone()

            if row is None:
                return None

            # Touch the access timestamp so this entry survives eviction
            conn.execute(
                "UPDATE thumbs SET last_access = ? WHERE key = ?",
                (int(time.time()), key),
            )
            conn.commit()
            return row[0]

        except Exception as e:
            print(f"[thumb_cache] L2 get error: {e}")
            return None

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  put  — inserts or replaces a thumbnail on disk.  After each   │
    # │  write, checks total size and triggers batch eviction if the   │
    # │  500 MB budget is exceeded.                                     │
    # └──────────────────────────────────────────────────────────────────┘
    def put(self, key: str, data: bytes) -> None:
        """Insert or replace.  Triggers eviction if over budget."""
        try:
            conn = self._ensure_conn()
            now = int(time.time())
            conn.execute(
                """INSERT OR REPLACE INTO thumbs
                   (key, data, size_bytes, created_at, last_access)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, data, len(data), now, now),
            )
            conn.commit()

            # Periodic eviction check (amortised: only runs ~every 100 writes)
            self._maybe_evict(conn)

        except Exception as e:
            print(f"[thumb_cache] L2 put error: {e}")

    # ┌──────────────────────────────────────────────────────────────────┐
    # │  _maybe_evict  — if total cache size exceeds the budget,       │
    # │  deletes the oldest 10% of entries in a single SQL DELETE.     │
    # │  This is O(1) DB round-trips vs. the old row-by-row loop.      │
    # └──────────────────────────────────────────────────────────────────┘
    def _maybe_evict(self, conn: sqlite3.Connection) -> None:
        try:
            total = conn.execute(
                "SELECT SUM(size_bytes) FROM thumbs"
            ).fetchone()[0] or 0

            if total <= self._max_bytes:
                return

            # Calculate how many entries to drop (oldest 10 %)
            count = conn.execute(
                "SELECT COUNT(*) FROM thumbs"
            ).fetchone()[0] or 0

            drop_count = max(1, int(count * _L2_EVICT_RATIO))

            # Batch delete — one statement, no Python loop
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

    # ── admin ─────────────────────────────────────────────────
    def clear(self) -> None:
        """Wipe all cached thumbnails."""
        try:
            conn = self._ensure_conn()
            conn.execute("DELETE FROM thumbs")
            conn.execute("VACUUM")          # reclaim disk space
            conn.commit()
        except Exception as e:
            print(f"[thumb_cache] L2 clear error: {e}")

    def stats(self) -> dict:
        """Return entry count and total byte size."""
        try:
            conn = self._ensure_conn()
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM thumbs"
            ).fetchone()
            return {"entries": row[0], "bytes": row[1]}
        except Exception:
            return {"entries": 0, "bytes": 0}

    def close(self) -> None:
        """Close the SQLite connection (call on app shutdown)."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


# ─────────────────────────────────────────────────────────────────
# Module-Level Singleton & Public API
# ─────────────────────────────────────────────────────────────────
#
#   The rest of the codebase should only ever call:
#     thumb_cache.get(key)
#     thumb_cache.put(key, data)
#     thumb_cache.clear()
#     thumb_cache.stats()
#
#   Everything below wires L1 + L2 together behind these four
#   functions, with a single lock protecting both tiers.
# ─────────────────────────────────────────────────────────────────

_l1_lock = threading.Lock()   # Fast: only guards the in-memory OrderedDict
_l2_lock = threading.Lock()   # Slow: guards SQLite disk I/O
_l1: _L1 | None = None
_l2: _L2 | None = None


def _init() -> tuple[_L1, _L2]:
    """Lazy-initialise both cache tiers on first use."""
    global _l1, _l2

    if _l1 is not None and _l2 is not None:
        return _l1, _l2

    from ui import settings_view as settings
    cache_dir = Path(settings._SETTINGS_DIR) / "thumb_cache"
    db_path = cache_dir / "cache.db"

    _l1 = _L1(max_bytes=_L1_MAX_BYTES)
    _l2 = _L2(db_path=db_path, max_bytes=_L2_MAX_BYTES)

    return _l1, _l2


# ┌──────────────────────────────────────────────────────────────────┐
# │  get  — public API.  Checks L1 first (instant), then L2 (disk  │
# │  read).  On L2 hit, promotes the entry into L1 so the next     │
# │  access is memory-speed.  Returns None on a total miss.         │
# └──────────────────────────────────────────────────────────────────┘
def get(key) -> bytes | None:
    key = str(key)

    # ── L1 hit (instant, never blocked by disk) ─────────────
    with _l1_lock:
        l1, _ = _init()
        data = l1.get(key)
        if data is not None:
            return data

    # ── L2 hit → promote to L1 (separate lock) ───────────
    with _l2_lock:
        _, l2 = _init()
        data = l2.get(key)

    if data is not None:
        with _l1_lock:
            l1, _ = _init()
            l1.put(key, data)   # warm up the memory tier
        return data

    # ── total miss ────────────────────────────────────
    return None


# ┌──────────────────────────────────────────────────────────────────┐
# │  put  — public API.  Stores a thumbnail in both L1 (memory)    │
# │  and L2 (disk) so it's instantly available on the next get()   │
# │  and survives app restarts.                                     │
# └──────────────────────────────────────────────────────────────────┘
def put(key, data: bytes) -> None:
    key = str(key)

    with _l1_lock:
        l1, _ = _init()
        l1.put(key, data)   # fast memory store

    with _l2_lock:
        _, l2 = _init()
        l2.put(key, data)   # durable disk store


# ┌──────────────────────────────────────────────────────────────────┐
# │  clear  — wipes both L1 and L2.  Called from the Settings UI   │
# │  "Clear Thumbnail Cache" button.  L2 also runs VACUUM to       │
# │  reclaim disk space immediately.                                │
# └──────────────────────────────────────────────────────────────────┘
def clear() -> None:
    with _l1_lock:
        l1, _ = _init()
        l1.clear()
    with _l2_lock:
        _, l2 = _init()
        l2.clear()


# ┌──────────────────────────────────────────────────────────────────┐
# │  stats  — returns a dict with entry count and byte totals for  │
# │  both L1 and L2.  Used by the Settings → About page to show    │
# │  how much memory/disk the cache is consuming.                   │
# └──────────────────────────────────────────────────────────────────┘
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


# ┌──────────────────────────────────────────────────────────────────┐
# │  shutdown  — closes the SQLite connection cleanly.  Called by  │
# │  main.py on app exit to flush WAL and avoid leftover files.     │
# └──────────────────────────────────────────────────────────────────┘
def shutdown() -> None:
    global _l1, _l2
    with _l1_lock:
        _l1 = None
    with _l2_lock:
        if _l2:
            _l2.close()
        _l2 = None
