"""credentials.py: DPAPI encryption, legacy migration, no silent data loss."""
import base64
import json
import sys

import pytest

import credentials as c

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    f = tmp_path / "credentials.v2.bin"
    monkeypatch.setattr(c.CredentialManager, "_get_credentials_file", staticmethod(lambda: f))
    monkeypatch.setattr(c.CredentialManager, "_get_legacy_credentials_file",
                        staticmethod(lambda: tmp_path / "legacy" / "credentials.bin"))
    return c.CredentialManager(), f


def test_roundtrip_is_dpapi_not_plaintext(mgr):
    m, f = mgr
    assert m.set_credential("danbooru", "alice", "SECRET-KEY-123")
    raw = f.read_text()
    assert raw.startswith("DPAPI1:")
    assert "SECRET" not in raw and "SECRET" not in base64.b64decode(raw[7:]).decode("latin-1")
    assert m.get_credential("danbooru") == {"user_id": "alice", "api_key": "SECRET-KEY-123"}


def _write_legacy_xor(path, data):
    path.write_text(base64.b64encode(c._xor(json.dumps(data).encode())).decode())


LEGACY = {"gelbooru": {"user_id": "1", "api_key": "k"}, "_bypass_data": {"x": {"cookies": {}}}}


def test_legacy_xor_file_migrated_to_v2_and_removed(mgr, tmp_path):
    m, f = mgr
    old = tmp_path / "credentials.bin"
    _write_legacy_xor(old, LEGACY)
    assert m._load_credentials() == LEGACY
    assert f.read_text().startswith("DPAPI1:")
    assert not old.exists(), "weak XOR copy must not stay on disk"
    assert m._load_credentials() == LEGACY


def test_first_call_being_a_save_still_migrates(mgr, tmp_path):
    """set_credential before any read used to pre-create an empty store,
    which made the migration think it was already done."""
    m, f = mgr
    _write_legacy_xor(tmp_path / "credentials.bin", LEGACY)
    assert m.set_credential("danbooru", "a", "b")
    data = m._load_credentials()
    assert data["gelbooru"] == LEGACY["gelbooru"] and data["danbooru"]["user_id"] == "a"


def test_appdata_legacy_is_migrated(mgr, tmp_path):
    m, f = mgr
    appdata = tmp_path / "legacy" / "credentials.bin"
    appdata.parent.mkdir()
    _write_legacy_xor(appdata, LEGACY)
    assert m._load_credentials() == LEGACY and f.exists() and not appdata.exists()


def test_legacy_plaintext_json_is_upgraded(mgr, tmp_path):
    m, f = mgr
    (tmp_path / "credentials.json").write_text(json.dumps({"e621": {"user_id": "u", "api_key": "k"}}))
    assert m.get_credential("e621") == {"user_id": "u", "api_key": "k"}
    assert f.read_text().startswith("DPAPI1:")


def test_downgrade_cannot_destroy_v2_store(mgr, tmp_path):
    """An old exe only knows credentials.bin. After migration that file is
    gone, so the old exe starts empty and whatever it writes there is
    ignored by the new version: the v2 store is untouched."""
    m, f = mgr
    _write_legacy_xor(tmp_path / "credentials.bin", LEGACY)
    m._load_credentials()
    v2_before = f.read_text()
    _write_legacy_xor(tmp_path / "credentials.bin", {})   # what the old exe would save
    assert m._load_credentials() == LEGACY
    assert f.read_text() == v2_before


def test_failed_migration_keeps_legacy_file(mgr, tmp_path, monkeypatch):
    m, f = mgr
    old = tmp_path / "credentials.bin"
    _write_legacy_xor(old, LEGACY)

    def broken_save(self, data):
        raise OSError("disk full")

    monkeypatch.setattr(c.CredentialManager, "_save_credentials", broken_save)
    assert m._load_credentials() == LEGACY      # still usable this session
    assert old.exists()


def test_unreadable_file_is_moved_aside_not_wiped(mgr, tmp_path):
    m, f = mgr
    f.write_text("DPAPI1:" + base64.b64encode(b"garbage from another account").decode())
    original = f.read_text()
    assert m.get_credential("danbooru") is None
    aside = list(tmp_path.glob("credentials.v2.bin.unreadable-*"))
    assert len(aside) == 1 and aside[0].read_text() == original
    # and a later save does not touch the moved-aside copy
    assert m.set_credential("danbooru", "a", "b")
    assert aside[0].read_text() == original


def test_sensitive_blobs_roundtrip(mgr):
    m, _ = mgr
    blob = {"danbooru": {"cookies": {"cf_clearance": "v" * 3000}, "user_agent": "UA"}}
    assert m.set_sensitive("_bypass_data", blob)
    assert m.get_sensitive("_bypass_data") == blob


def test_concurrent_saves_lose_nothing(mgr, caplog):
    """3 threads x 60 read-modify-write saves of different keys: every
    thread's last value must survive and no save may fail."""
    import threading
    m, _ = mgr
    errors = []

    def worker(i):
        for n in range(60):
            if not m.set_sensitive(f"k{i}", {"n": n}):
                errors.append((i, n))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert all(m.get_sensitive(f"k{i}") == {"n": 59} for i in range(3))
    assert "Failed to save" not in caplog.text


def test_set_sensitive_many_single_write(mgr):
    m, f = mgr
    assert c.set_sensitive_many is not None
    assert m.set_sensitive_many({"_a": {"x": 1}, "_b": {"y": 2}})
    assert m.get_sensitive("_a") == {"x": 1} and m.get_sensitive("_b") == {"y": 2}
    assert not list(f.parent.glob("*.tmp")), "temp files left behind"
