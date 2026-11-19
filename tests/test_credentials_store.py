"""credentials.py: DPAPI encryption, legacy migration, no silent data loss."""
import base64
import json
import sys

import pytest

import credentials as c

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    f = tmp_path / "credentials.bin"
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


def test_legacy_xor_file_is_read_and_upgraded(mgr):
    m, f = mgr
    data = {"gelbooru": {"user_id": "1", "api_key": "k"}, "_bypass_data": {"x": {"cookies": {}}}}
    f.write_text(base64.b64encode(c._xor(json.dumps(data).encode())).decode())
    assert m._load_credentials() == data
    assert f.read_text().startswith("DPAPI1:")
    assert m._load_credentials() == data


def test_legacy_plaintext_json_is_upgraded(mgr):
    m, f = mgr
    f.write_text(json.dumps({"e621": {"user_id": "u", "api_key": "k"}}))
    assert m.get_credential("e621") == {"user_id": "u", "api_key": "k"}
    assert f.read_text().startswith("DPAPI1:")


def test_unreadable_file_is_moved_aside_not_wiped(mgr, tmp_path):
    m, f = mgr
    f.write_text("DPAPI1:" + base64.b64encode(b"garbage from another account").decode())
    original = f.read_text()
    assert m.get_credential("danbooru") is None
    aside = list(tmp_path.glob("credentials.bin.unreadable-*"))
    assert len(aside) == 1 and aside[0].read_text() == original
    # and a later save does not touch the moved-aside copy
    assert m.set_credential("danbooru", "a", "b")
    assert aside[0].read_text() == original


def test_sensitive_blobs_roundtrip(mgr):
    m, _ = mgr
    blob = {"danbooru": {"cookies": {"cf_clearance": "v" * 3000}, "user_agent": "UA"}}
    assert m.set_sensitive("_bypass_data", blob)
    assert m.get_sensitive("_bypass_data") == blob
