"""Tests for the JSON-backed booru registry (boorus/__init__.py)."""
import json

import pytest

import boorus


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the store at a temp file and isolate the legacy-.py migration dir."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    monkeypatch.setattr(boorus, "STORE_FILE", tmp_path / "custom_boorus.json")
    monkeypatch.setattr(boorus, "_PACKAGE_DIR", pkg)
    saved = dict(boorus.REGISTRY)
    boorus.load()
    yield tmp_path
    boorus.REGISTRY.clear()
    boorus.REGISTRY.update(saved)


GOOD = {"url": "https://example.com", "api_path": "/index.php", "post_key": None, "api_type": "gelbooru"}


def test_builtins_present(store):
    assert "gelbooru" in boorus.REGISTRY and "safebooru" in boorus.REGISTRY


def test_add_persists_and_reloads(store):
    boorus.add_booru("mybooru", GOOD)
    boorus.REGISTRY.clear()
    boorus.load()
    assert boorus.REGISTRY["mybooru"]["url"] == "https://example.com"


@pytest.mark.parametrize("url", [
    'https://example.com/";__import__("os").system("calc");x="',   # audit exploit
    "javascript:alert(1)",
    "file:///C:/Windows",
    "https://user:pass@example.com",
    "https://exa mple.com",
    "https://example.com/?a=1",
    "example.com",
])
def test_rejects_bad_urls(store, url):
    with pytest.raises(boorus.BooruValidationError):
        boorus.add_booru("bad", {**GOOD, "url": url})
    assert "bad" not in boorus.REGISTRY


@pytest.mark.parametrize("api_path", ['"; import os', "index.php", "/../etc", "/a b"])
def test_rejects_bad_api_path(store, api_path):
    with pytest.raises(boorus.BooruValidationError):
        boorus.add_booru("bad", {**GOOD, "api_path": api_path})


@pytest.mark.parametrize("name", ["", "../x", "Upper", "a" * 65, "a.b", 'x"'])
def test_rejects_bad_names(store, name):
    with pytest.raises(boorus.BooruValidationError):
        boorus.add_booru(name, GOOD)


def test_rejects_unknown_api_type(store):
    with pytest.raises(boorus.BooruValidationError):
        boorus.add_booru("bad", {**GOOD, "api_type": "os.system"})


def test_engine_override_on_builtin_persists(store):
    boorus.REGISTRY["gelbooru"]["api_type"] = "danbooru"
    assert boorus.write_booru_file("gelbooru")
    boorus.load()
    assert boorus.REGISTRY["gelbooru"]["api_type"] == "danbooru"


def test_remove_builtin_persists(store):
    boorus.remove_booru("gelbooru")
    boorus.load()
    assert "gelbooru" not in boorus.REGISTRY


def test_tampered_store_entry_is_skipped(store):
    (store / "custom_boorus.json").write_text(json.dumps(
        {"boorus": {"evil": {**GOOD, "url": 'https://x";import os;"'}, "ok": GOOD}}))
    boorus.load()
    assert "evil" not in boorus.REGISTRY and "ok" in boorus.REGISTRY


def test_corrupt_store_does_not_crash(store):
    (store / "custom_boorus.json").write_text("{not json")
    boorus.load()
    assert "safebooru" in boorus.REGISTRY


def test_legacy_py_migrated_without_executing(store, tmp_path):
    marker = tmp_path / "pwned"
    pkg = tmp_path / "pkg"
    (pkg / "oldone.py").write_text(
        'NAME = "oldone"\nURL = "https://old.example"\nAPI_PATH = "/index.php"\n'
        'POST_KEY = None\nAPI_TYPE = "moebooru"\n'
        f'open({str(marker)!r}, "w").write("x")\n'
    )
    boorus.load()
    assert not marker.exists(), "legacy file must be parsed, never executed"
    assert boorus.REGISTRY["oldone"]["api_type"] == "moebooru"
    assert not (pkg / "oldone.py").exists()
    assert "oldone" in json.loads((tmp_path / "custom_boorus.json").read_text())["boorus"]


def test_malicious_legacy_py_rejected(store, tmp_path):
    pkg = tmp_path / "pkg"
    (pkg / "evil.py").write_text('NAME = "evil"\nURL = "https://x\\";import os;\\""\n')
    boorus.load()
    assert "evil" not in boorus.REGISTRY
