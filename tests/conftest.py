"""pytest config for the test suite.

The scripts listed in collect_ignore are manual debugging scripts, not tests:
they hit live sites or open Qt windows at import time. They are not part of
the repository and are skipped so a plain ``pytest`` is safe and offline.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
                        staticmethod(lambda: data / "credentials.bin"))
    monkeypatch.setattr(credentials.CredentialManager, "_get_legacy_credentials_file",
                        staticmethod(lambda: data / "legacy_credentials.bin"))
    import ui.settings_view  # noqa: F401  (the package re-exports an instance named 'manager')
    settings_manager = sys.modules["ui.settings_view.manager"]
    monkeypatch.setattr(settings_manager, "_SETTINGS_FILE", data / "settings.json")
    monkeypatch.setattr(settings_manager, "_LEGACY_SETTINGS_FILE", data / "legacy_settings.json")
    yield
