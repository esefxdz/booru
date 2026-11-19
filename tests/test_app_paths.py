"""Data-folder choice for the portable exe."""
import tempfile
from pathlib import Path

import app_paths


def test_writable_permanent_folder_is_portable(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "_is_temporary", lambda p: False)
    app = tmp_path / "app"
    app.mkdir()
    d, reason = app_paths.choose_data_dir(app, tmp_path / "fallback")
    assert d == app and "portable" in reason
    assert not (tmp_path / "fallback").exists()


def test_read_only_folder_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "_is_temporary", lambda p: False)
    monkeypatch.setattr(app_paths, "_is_writable", lambda p: False)
    d, reason = app_paths.choose_data_dir(tmp_path / "ProgramFiles", tmp_path / "LocalAppData")
    assert d == tmp_path / "LocalAppData" and d.is_dir() and "not writable" in reason


def test_temp_folder_falls_back(tmp_path):
    inside_temp = Path(tempfile.gettempdir()) / "Temp1_BooruBrowser.zip"
    d, reason = app_paths.choose_data_dir(inside_temp, tmp_path / "LocalAppData")
    assert d == tmp_path / "LocalAppData" and "temporary" in reason


def test_write_probe_leaves_nothing(tmp_path):
    assert app_paths._is_writable(tmp_path)
    assert list(tmp_path.iterdir()) == []
