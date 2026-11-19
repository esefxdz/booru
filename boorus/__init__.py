"""
boorus/__init__.py

Booru registry. Exposes ``REGISTRY``: ``{name: {url, api_path, post_key, api_type}}``.

Storage model
-------------
* Built-in boorus are plain data in ``BUILTIN_BOORUS`` below.
* Everything the user changes (custom boorus, engine overrides on a built-in,
  removed built-ins) lives in ``custom_boorus.json`` next to ``settings.json``.

Boorus used to be stored as generated ``.py`` files inside this package and
imported at startup. That let a crafted URL in "Add booru" execute code, and in
the packaged exe the package folder is a temp dir, so custom boorus were lost
on exit. Legacy ``.py`` files are migrated once by *parsing* them with ``ast``
(never importing them) and then deleted.

Every entry is validated before it is stored or loaded, so callers (the Qt UI
today, an HTTP API later) cannot put arbitrary data in the registry.
"""
from __future__ import annotations

import ast
import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("boorus")

REGISTRY: dict = {}

# Guards read-modify-write of custom_boorus.json and REGISTRY rebuilds.
_LOCK = threading.RLock()

BUILTIN_BOORUS: dict[str, dict] = {
    "gelbooru": {
        "url": "https://gelbooru.com",
        "api_path": "/index.php",
        "post_key": None,
        "api_type": "gelbooru",
    },
    "safebooru": {
        "url": "https://safebooru.org",
        "api_path": "/index.php",
        "post_key": None,
        "api_type": "gelbooru",
    },
}

_PACKAGE_DIR = Path(__file__).resolve().parent


def _app_dir() -> Path:
    """Directory that holds settings.json (next to the exe, or the repo root)."""
    if getattr(sys, "frozen", False):
        return Path(os.path.dirname(sys.executable)).resolve()
    return _PACKAGE_DIR.parent


# Module-level so tests can point it at a temp dir.
STORE_FILE: Path = _app_dir() / "custom_boorus.json"


class BooruValidationError(ValueError):
    """Raised when a booru entry fails validation."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")
_API_PATH_RE = re.compile(r"^/[A-Za-z0-9_\-./]*$")
_POST_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def _known_api_types() -> set[str]:
    from adapters import ADAPTERS
    return set(ADAPTERS)


def validate_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise BooruValidationError(
            "Name must be 1-64 chars of lowercase letters, digits, '_' or '-'"
        )
    return name


def validate_entry(name: str, data: dict) -> dict:
    """Return a clean copy of *data*, or raise BooruValidationError."""
    validate_name(name)
    if not isinstance(data, dict):
        raise BooruValidationError("Booru entry must be an object")

    url = data.get("url", "")
    if not isinstance(url, str):
        raise BooruValidationError("URL must be a string")
    url = url.strip().rstrip("/")
    if any(c.isspace() for c in url) or any(c in url for c in "\"'<>\\`"):
        raise BooruValidationError("URL contains invalid characters")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise BooruValidationError("URL must be http(s)://host")
    if parsed.username or parsed.password:
        raise BooruValidationError("URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise BooruValidationError("URL must not contain a query or fragment")
    if len(url) > 512:
        raise BooruValidationError("URL too long")

    api_path = data.get("api_path") or "/index.php"
    if not isinstance(api_path, str) or not _API_PATH_RE.match(api_path) or ".." in api_path:
        raise BooruValidationError("API path must start with '/' and contain only URL path characters")
    if len(api_path) > 256:
        raise BooruValidationError("API path too long")

    api_type = data.get("api_type") or "gelbooru"
    if api_type not in _known_api_types():
        raise BooruValidationError(f"Unknown API type '{api_type}'")

    post_key = data.get("post_key")
    if post_key is not None and (not isinstance(post_key, str) or not _POST_KEY_RE.match(post_key)):
        raise BooruValidationError("post_key must be a short identifier or null")

    return {"url": url, "api_path": api_path, "post_key": post_key, "api_type": api_type}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _locked_store(fn):
    def wrapper(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _read_store() -> dict:
    """Return ``{"boorus": {...}, "removed": [...]}``. Never raises."""
    empty = {"boorus": {}, "removed": []}
    if not STORE_FILE.exists():
        return empty
    try:
        raw = json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except Exception:
        # Move it aside so the next save cannot overwrite the user's boorus.
        aside = STORE_FILE.with_name(f"{STORE_FILE.name}.unreadable-{int(time.time())}")
        try:
            STORE_FILE.replace(aside)
            log.error("[boorus] %s is unreadable; moved it to %s", STORE_FILE.name, aside.name)
        except OSError:
            log.exception("[boorus] %s is unreadable and could not be moved aside", STORE_FILE)
        return empty
    if not isinstance(raw, dict):
        return empty
    entries = raw.get("boorus") if isinstance(raw.get("boorus"), dict) else {}
    removed = raw.get("removed") if isinstance(raw.get("removed"), list) else []
    return {"boorus": entries, "removed": [r for r in removed if isinstance(r, str)]}


def _write_store(store: dict) -> bool:
    from fileutil import atomic_write_text
    try:
        atomic_write_text(STORE_FILE, json.dumps(store, indent=2))
        return True
    except Exception:
        log.exception("[boorus] Failed to write %s", STORE_FILE)
        return False


def _parse_legacy_py(path: Path) -> tuple[str, dict] | None:
    """Read NAME/URL/... literals from an old generated booru .py file.

    Uses ``ast`` so a malicious file is never executed. Anything that is not a
    plain ``NAME = <literal>`` assignment is ignored.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    values: dict = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except Exception:
                continue
    name = values.get("NAME", path.stem)
    data = {
        "url": values.get("URL", ""),
        "api_path": values.get("API_PATH", "/index.php"),
        "post_key": values.get("POST_KEY"),
        "api_type": values.get("API_TYPE", "gelbooru"),
    }
    return (name, data) if isinstance(name, str) else None


def _migrate_legacy_py_files(store: dict) -> list[Path]:
    """Copy user-generated ``boorus/*.py`` entries into *store* (in memory).

    Returns the legacy files that were handled. The caller deletes them only
    after the store has been written successfully.
    """
    handled: list[Path] = []
    for f in sorted(_PACKAGE_DIR.glob("*.py")):
        if f.name.startswith("_"):
            continue
        parsed = _parse_legacy_py(f)
        if parsed is None:
            log.warning("[boorus] Could not parse legacy file %s; leaving it alone", f)
            continue
        name, data = parsed
        try:
            clean = validate_entry(name, data)
        except BooruValidationError as e:
            log.warning("[boorus] Legacy booru %s rejected (%s); file left in place", f.name, e)
            continue
        if BUILTIN_BOORUS.get(name) != clean and store["boorus"].get(name) is None:
            store["boorus"][name] = clean
        handled.append(f)
    return handled


@_locked_store
def load() -> None:
    """(Re)build REGISTRY from built-ins + the JSON store."""
    store = _read_store()
    if not getattr(sys, "frozen", False):
        legacy = _migrate_legacy_py_files(store)
        if legacy and _write_store(store):
            for f in legacy:
                try:
                    f.unlink()
                    log.info("[boorus] Migrated legacy booru file %s to %s", f.name, STORE_FILE.name)
                except OSError:
                    log.warning("[boorus] Could not delete migrated legacy file %s", f)

    REGISTRY.clear()
    removed = set(store["removed"])
    for name, data in BUILTIN_BOORUS.items():
        if name not in removed:
            REGISTRY[name] = dict(data)
    for name, data in store["boorus"].items():
        try:
            REGISTRY[name] = validate_entry(name, data)
        except BooruValidationError as e:
            log.warning("[boorus] Skipping invalid stored booru '%s': %s", name, e)


# ---------------------------------------------------------------------------
# Public API (kept compatible with the old .py-file based helpers)
# ---------------------------------------------------------------------------

def add_booru(name: str, data: dict) -> dict:
    """Validate, register and persist a booru. Returns the stored entry.

    Raises BooruValidationError on invalid input, OSError if it cannot be saved.
    """
    clean = validate_entry(name, data)
    REGISTRY[name] = clean
    if not write_booru_file(name):
        raise OSError(f"Could not save {STORE_FILE}")
    return clean


@_locked_store
def write_booru_file(name: str) -> bool:
    """Persist REGISTRY[name] to the JSON store.

    The name is historical (boorus used to be .py files); callers mutate
    REGISTRY and then call this. Invalid entries are refused and not written.
    """
    data = REGISTRY.get(name)
    if not data:
        log.warning("[boorus] write_booru_file: '%s' not in REGISTRY", name)
        return False
    try:
        clean = validate_entry(name, data)
    except BooruValidationError as e:
        log.error("[boorus] Refusing to save invalid booru '%s': %s", name, e)
        return False

    store = _read_store()
    if BUILTIN_BOORUS.get(name) == clean:
        store["boorus"].pop(name, None)   # back to the built-in default
    else:
        store["boorus"][name] = clean
    if name in store["removed"]:
        store["removed"].remove(name)
    REGISTRY[name] = clean
    return _write_store(store)


@_locked_store
def remove_booru(name: str) -> str | None:
    """Remove a booru and persist that. Returns a fallback booru name or None."""
    REGISTRY.pop(name, None)
    store = _read_store()
    store["boorus"].pop(name, None)
    if name in BUILTIN_BOORUS and name not in store["removed"]:
        store["removed"].append(name)
    _write_store(store)
    return next(iter(REGISTRY), None)


def invalidate_cache(name: str) -> None:
    """No-op. Kept for callers written for the old .py-file storage."""


def reregister(name: str) -> bool:
    """Reload *name* from storage into REGISTRY. Returns True if it exists."""
    load()
    return name in REGISTRY


load()
