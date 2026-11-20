"""pytest config for the test suite.

The scripts listed in collect_ignore are manual debugging scripts, not tests:
they hit live sites or open Qt windows at import time. They are not part of
the repository and are skipped so a plain ``pytest`` is safe and offline.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Before ANY app module is imported: every data file (settings, credentials,
# bookmarks, caches) goes to a throwaway folder, never the real one.
os.environ["BOORUBROWSER_DATA_DIR"] = tempfile.mkdtemp(prefix="booru-test-data-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

collect_ignore = [
    "test_api.py",
    "test_bypasser.py",
    "test_cdns.py",
    "test_dialog.py",
    "test_domains.py",
    "test_gelbooru_videos.py",
    "test_get.py",
]


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_user_data(tmp_path_factory, monkeypatch):
    """Never let a test read or write the real settings/credentials/booru
    files that live next to the app (they are the developer's own data)."""
    data = tmp_path_factory.mktemp("userdata")
    import boorus
    import credentials
    monkeypatch.setattr(boorus, "STORE_FILE", data / "custom_boorus.json")
    monkeypatch.setattr(credentials.CredentialManager, "_get_credentials_file",
                        staticmethod(lambda: data / "credentials.v2.bin"))
    import ui.settings_view  # noqa: F401  (the package re-exports an instance named 'manager')
    settings_manager = sys.modules["ui.settings_view.manager"]
    monkeypatch.setattr(settings_manager, "_SETTINGS_FILE", data / "settings.json")
    # The Cloudflare circuit breaker is module-level and keyed by host; every
    # test server is 127.0.0.1, so one test's block must not leak into the next.
    from cloudflare_bypasser import circuit_breaker as _cf_breaker
    _cf_breaker.reset_all_circuits()
    yield
    _cf_breaker.reset_all_circuits()
