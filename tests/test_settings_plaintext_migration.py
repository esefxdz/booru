"""Upgrading from a settings.json that still holds plaintext secrets.

Builds before 2026-05-19 saved the whole SettingsManager ``__dict__`` to
settings.json, so ``bypass_data``, ``session_keys`` and ``auth_tokens`` sat
there in plaintext. Later builds read secrets only from the credentials store
and dropped those keys on the next save, so the cookies/logins were lost.
All values below are fake.
"""
import json
import sys

import pytest

FAKE_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Same keys, order and indent=2 layout the old SettingsManager.save() produced.
OLD_SETTINGS = {
    "active_booru": "safebooru",
    "blacklist": "",
    "favorites": "",
    "booru_order": ["safebooru", "gelbooru"],
    "thumbnail_size": 250,
    "thumbnail_res": 720,
    "masonry_mode": False,
    "infinite_scroll": False,
    "reduced_motion": False,
    "use_arrows_for_sorting": False,
    "use_legacy_viewer": False,
    "video_engine": "qt",
    "use_http2": False,
    "proxy_url": "",
    "custom_download_path": "",
    "concurrent_downloads": 50,
    "use_network_semaphore": True,
    "download_folder_use_artist_folder": False,
    "use_smart_folders": False,
    "bypass_data": {
        "gelbooru": {"cookies": {"cf_clearance": "FAKE-PLAIN-CF-GEL"}, "user_agent": FAKE_UA},
        # oldest shape (settings.py era): cf_clearance stored directly
        "rule34": {"cf_clearance": "FAKE-PLAIN-CF-R34", "user_agent": FAKE_UA},
    },
    "session_keys": {"safebooru": {"pass_hash": "FAKE-PLAIN-SESSION"}},
    "auth_tokens": {"e621": {"user": "fakeuser", "token": "FAKE-PLAIN-TOKEN"}},
    "bookmarks": [],
}
PLAIN_SECRETS = ("FAKE-PLAIN-CF-GEL", "FAKE-PLAIN-CF-R34", "FAKE-PLAIN-SESSION", "FAKE-PLAIN-TOKEN")


@pytest.fixture
def mgr(monkeypatch):
    import core.settings as mod
    m = mod.manager
    for k, v in (("blacklist", ""), ("bypass_data", {}), ("session_keys", {}),
                 ("auth_tokens", {}), ("_save_disabled", False), ("_initialized", True),
                 ("_secrets_unloaded", False), ("_legacy_plaintext", None)):
        monkeypatch.setattr(m, k, v, raising=False)
    return mod, m


def _write_old(mod, extra=None):
    data = dict(OLD_SETTINGS, **(extra or {}))
    mod._SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _store():
    from core import credentials
    return {k: credentials.get_sensitive(k) for k in ("_bypass_data", "_session_keys", "_auth_tokens")}


def test_upgrade_moves_plaintext_into_store_and_out_of_settings(mgr):
    from cloudflare_bypasser import store
    mod, m = mgr
    _write_old(mod)
    m.load()

    s = _store()
    assert s["_bypass_data"] == OLD_SETTINGS["bypass_data"]
    assert s["_session_keys"] == OLD_SETTINGS["session_keys"]
    assert s["_auth_tokens"] == OLD_SETTINGS["auth_tokens"]
    assert m.bypass_data == OLD_SETTINGS["bypass_data"]
    assert m.session_keys == OLD_SETTINGS["session_keys"]
    assert m.auth_tokens == OLD_SETTINGS["auth_tokens"]
    assert store.get_cookies("rule34") == {"cf_clearance": "FAKE-PLAIN-CF-R34"}

    assert m.save()
    raw = mod._SETTINGS_FILE.read_text(encoding="utf-8")
    saved = json.loads(raw)
    for k in ("bypass_data", "session_keys", "auth_tokens"):
        assert k not in saved
    for secret in PLAIN_SECRETS:
        assert secret not in raw
    assert saved["booru_order"] == ["safebooru", "gelbooru"]  # other settings kept
    # and the secrets survive a restart
    m.load()
    assert m.bypass_data == OLD_SETTINGS["bypass_data"]


def test_old_plaintext_credentials_block_does_not_drop_secrets_early(mgr):
    # The "credentials" migration re-saves settings.json during load(); the
    # plaintext cookies must still be there until they are in the store.
    from core import credentials
    mod, m = mgr
    _write_old(mod, {"credentials": {"danbooru": {"user_id": "u", "api_key": "FAKE-KEY"}}})
    m.load()
    assert credentials.get_credential("danbooru") == {"user_id": "u", "api_key": "FAKE-KEY"}
    assert _store()["_auth_tokens"] == OLD_SETTINGS["auth_tokens"]


def test_existing_store_entries_win_over_plaintext(mgr):
    from core import credentials
    mod, m = mgr
    stored = {"gelbooru": {"cookies": {"cf_clearance": "FAKE-STORED-NEWER"}, "user_agent": "UA2"}}
    credentials.set_sensitive_many({"_bypass_data": stored,
                                    "_auth_tokens": {"e621": {"user": "x", "token": "FAKE-STORED-TOKEN"}}})
    _write_old(mod)
    m.load()
    s = _store()
    assert s["_bypass_data"]["gelbooru"] == stored["gelbooru"]          # not overwritten
    assert s["_bypass_data"]["rule34"] == OLD_SETTINGS["bypass_data"]["rule34"]  # filled in
    assert s["_auth_tokens"] == {"e621": {"user": "x", "token": "FAKE-STORED-TOKEN"}}
    assert s["_session_keys"] == OLD_SETTINGS["session_keys"]
    assert m.bypass_data["gelbooru"] == stored["gelbooru"]


def test_locked_store_migrates_nothing_and_loses_nothing(mgr, monkeypatch):
    from core import credentials
    mod, m = mgr
    credentials.set_sensitive("_bypass_data", {"danbooru": {"cookies": {"a": "FAKE-STORED"}}})
    cred_file = credentials.CredentialManager._get_credentials_file()
    before = cred_file.read_bytes()
    _write_old(mod)

    real = credentials.CredentialManager._load_credentials
    locked = {"on": True}

    def flaky(self):
        if locked["on"]:
            raise PermissionError(32, "being used by another process")
        return real(self)

    monkeypatch.setattr(credentials.CredentialManager, "_load_credentials", flaky)
    m.load()
    assert m._secrets_unloaded is True
    m.blacklist = "changed"
    assert m.save()
    assert cred_file.read_bytes() == before                      # store untouched
    saved = json.loads(mod._SETTINGS_FILE.read_text(encoding="utf-8"))
    assert saved["blacklist"] == "changed"
    for k in ("bypass_data", "session_keys", "auth_tokens"):
        assert saved[k] == OLD_SETTINGS[k]                       # plaintext kept

    locked["on"] = False                                         # next start: store readable
    m.load()
    s = _store()
    assert s["_bypass_data"]["danbooru"] == {"cookies": {"a": "FAKE-STORED"}}
    assert s["_bypass_data"]["gelbooru"] == OLD_SETTINGS["bypass_data"]["gelbooru"]
    assert s["_auth_tokens"] == OLD_SETTINGS["auth_tokens"]
    assert m.save()
    assert "FAKE-PLAIN-TOKEN" not in mod._SETTINGS_FILE.read_text(encoding="utf-8")


def test_failed_store_write_keeps_plaintext_in_settings(mgr, monkeypatch):
    mod, m = mgr
    _write_old(mod)
    monkeypatch.setattr(mod, "set_sensitive_many", lambda items: False)
    m.load()
    assert m.bypass_data == OLD_SETTINGS["bypass_data"]          # usable this session
    assert m.save()
    saved = json.loads(mod._SETTINGS_FILE.read_text(encoding="utf-8"))
    for k in ("bypass_data", "session_keys", "auth_tokens"):
        assert saved[k] == OLD_SETTINGS[k]


def test_read_back_mismatch_keeps_plaintext_in_settings(mgr, monkeypatch):
    mod, m = mgr
    _write_old(mod)
    real_get = mod.get_sensitive
    calls = {"n": 0}

    def get(key, **kw):
        calls["n"] += 1
        if calls["n"] > 3:          # the read-back after the migration write
            return {}
        return real_get(key, **kw)

    monkeypatch.setattr(mod, "get_sensitive", get)
    m.load()
    monkeypatch.setattr(mod, "set_sensitive_many", lambda items: True)  # save() itself "succeeds"
    assert m.save()
    saved = json.loads(mod._SETTINGS_FILE.read_text(encoding="utf-8"))
    assert saved["auth_tokens"] == OLD_SETTINGS["auth_tokens"]


def test_save_disabled_never_touches_old_settings(mgr, monkeypatch):
    mod, m = mgr
    _write_old(mod)
    before = mod._SETTINGS_FILE.read_bytes()
    m.load()
    monkeypatch.setattr(m, "_save_disabled", True)
    assert m.save() is False
    assert mod._SETTINGS_FILE.read_bytes() == before


def test_settings_without_plaintext_does_not_write_store(mgr, monkeypatch):
    mod, m = mgr
    mod._SETTINGS_FILE.write_text('{"blacklist": "x", "bypass_data": {}}', encoding="utf-8")
    writes = []
    monkeypatch.setattr(mod, "set_sensitive_many", lambda items: writes.append(items) or True)
    m.load()
    assert writes == []
