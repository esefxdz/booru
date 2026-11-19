"""BOORUBROWSER_DATA_DIR must also sandbox the legacy %APPDATA% sources: with
the override set, migration code never reads or deletes the real APPDATA."""
import sys

import pytest

import app_paths
import credentials
from ui.autocomplete import tag_cache  # noqa: F401  (imports the module)


@pytest.fixture
def fake_appdata(tmp_path, monkeypatch):
    root = tmp_path / "Roaming"
    d = root / "BooruBrowser"
    d.mkdir(parents=True)
    for name in ("settings.json", "bookmarks.db", "tag_cache.db",
                 "tag_cache.json", "credentials.bin"):
        (d / name).write_bytes(b"{}")
    monkeypatch.setenv("APPDATA", str(root))
    return d


def _snapshot(d):
    return {p.name: p.read_bytes() for p in d.iterdir()}


def test_legacy_dir_is_inside_override(fake_appdata):
    d = app_paths.legacy_appdata_dir()
    assert fake_appdata not in (d, *d.parents)
    assert app_paths.data_dir() in d.parents


def test_legacy_dir_without_override_is_appdata(fake_appdata, monkeypatch):
    monkeypatch.delenv(app_paths.ENV_OVERRIDE)
    assert app_paths.legacy_appdata_dir() == fake_appdata


def test_migrations_ignore_appdata_under_override(fake_appdata, tmp_path, monkeypatch):
    before = _snapshot(fake_appdata)
    data = tmp_path / "data"
    data.mkdir()

    # credentials: would read AND delete the legacy file
    mgr = credentials.CredentialManager()
    monkeypatch.setattr(credentials.CredentialManager, "_get_credentials_file",
                        staticmethod(lambda: data / "credentials.v2.bin"))
    assert fake_appdata / "credentials.bin" not in mgr._legacy_sources()
    mgr._load_credentials()

    # settings
    sm = sys.modules["ui.settings_view.manager"]
    monkeypatch.setattr(sm, "_SETTINGS_FILE", data / "settings.json")
    sm.SettingsManager()._initialized = False
    sm.SettingsManager().initialize()
    assert not (data / "settings.json").exists() or \
        (data / "settings.json").read_bytes() != b"{}"

    # bookmarks db
    from ui.bookmarks_main import bookmarks_db as bdb
    monkeypatch.setattr(bdb, "_DB_FILE", data / "bookmarks.db")
    obj = bdb.BookmarksDB.__new__(bdb.BookmarksDB)
    obj.db_path = data / "bookmarks.db"
    obj._migrate_legacy_db()
    assert not obj.db_path.exists()

    # tag cache db
    monkeypatch.setattr(tag_cache, "_DB_PATH", data / "tag_cache.db")
    tag_cache._local.conn = None
    tag_cache._conn()
    assert (data / "tag_cache.db").stat().st_size != 2

    # tag categorizer json
    import tag_categorizer
    monkeypatch.setattr(tag_categorizer, "BASE_DIR", data)
    tag_categorizer.TagCategorizer()
    assert not (data / "tag_cache.json").exists()

    assert _snapshot(fake_appdata) == before
