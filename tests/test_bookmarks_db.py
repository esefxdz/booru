"""Bookmarks are keyed on (booru, id): ids are only unique per booru."""
import json
import sqlite3
import threading

import pytest

from ui.bookmarks_main import bookmarks_db as m


def _db(path):
    db = m.BookmarksDB.__new__(m.BookmarksDB)
    db.db_path = path
    db._conn = None
    db._lock = threading.RLock()
    db._init_db()
    return db


@pytest.fixture
def db(tmp_path):
    return _db(tmp_path / "bookmarks.db")


def P(booru, pid, **extra):
    return {"id": pid, "_booru": booru, **extra}


def test_same_id_on_two_boorus_does_not_collide(db):
    db.add_bookmark(P("gelbooru", 1234567, tags="a"))
    db.add_bookmark(P("danbooru", 1234567, tags="b"))
    assert len(db.get_all_bookmarks()) == 2
    assert db.is_post_bookmarked("1234567", "gelbooru")
    assert db.is_post_bookmarked("1234567", "danbooru")
    assert not db.is_post_bookmarked("1234567", "safebooru")


def test_remove_only_affects_that_booru(db):
    db.add_bookmark(P("gelbooru", 5))
    db.add_bookmark(P("danbooru", 5))
    db.remove_bookmark("5", "gelbooru")
    assert not db.is_post_bookmarked("5", "gelbooru")
    assert db.is_post_bookmarked("5", "danbooru")


def test_bookmarked_keys_for_mixed_list(db):
    db.add_bookmark(P("gelbooru", 1))
    db.add_bookmark(P("danbooru", 2))
    posts = [P("gelbooru", 1), P("danbooru", 1), P("danbooru", 2), P("safebooru", 3)]
    assert db.bookmarked_keys(posts) == {("gelbooru", "1"), ("danbooru", "2")}


def test_v1_table_migrated_without_losing_rows(tmp_path):
    path = tmp_path / "bookmarks.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE bookmarks (id TEXT PRIMARY KEY, booru TEXT, post_data TEXT, "
              "added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    c.execute("INSERT INTO bookmarks VALUES ('1','gelbooru',?, '2026-01-01 10:00:00')", (json.dumps(P("gelbooru", 1)),))
    c.execute("INSERT INTO bookmarks VALUES ('2',NULL,?, '2026-01-02 10:00:00')", (json.dumps({"id": 2}),))
    c.commit()
    c.close()

    db = _db(path)
    pk = [r[1] for r in db._get_conn().execute("PRAGMA table_info(bookmarks)") if r[5]]
    assert pk == ["booru", "id"]
    assert len(db.get_all_bookmarks()) == 2
    # a v1 row without a booru ("unknown") still shows as bookmarked anywhere
    assert db.is_post_bookmarked("2", "danbooru")
    assert db.bookmarked_keys([P("danbooru", 2)]) == {("danbooru", "2")}
    backup = db._get_conn().execute("SELECT count(*) FROM bookmarks_v1_backup").fetchone()[0]
    assert backup == 2
    _db(path)   # second start: no-op
    assert len(db.get_all_bookmarks()) == 2


def test_old_exe_can_still_use_migrated_table(db):
    """A downgraded exe runs v1 SQL against the new table; it must work."""
    c = db._get_conn()
    c.execute("INSERT OR REPLACE INTO bookmarks (id, booru, post_data) VALUES (?, ?, ?)",
              ("9", "gelbooru", json.dumps(P("gelbooru", 9))))
    assert c.execute("SELECT 1 FROM bookmarks WHERE id = ?", ("9",)).fetchone()
