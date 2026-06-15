"""
boorus/__init__.py

Auto-discovers all built-in booru definitions (*.py files in this package)
and exposes them as the REGISTRY dict. Custom/user-added boorus are merged
into REGISTRY at app startup from settings.json.

Provides helpers for writing booru files and invalidating importlib caches
so that add/remove/engine-change operations are atomic and durable.
"""
from pathlib import Path
import importlib
import sys
import logging

REGISTRY: dict = {}

BOORU_TEMPLATE = """\
NAME     = "{name}"
URL      = "{url}"
API_PATH = "{api_path}"
POST_KEY = {post_key}
API_TYPE = "{api_type}"
"""


def _discover():
    """Import every .py file in this directory and register its metadata."""
    booru_dir = Path(__file__).resolve().parent
    for f in sorted(booru_dir.glob("*.py")):
        if f.name.startswith("_"):
            continue
        mod = importlib.import_module(f"boorus.{f.stem}")
        name = getattr(mod, "NAME", f.stem)
        REGISTRY[name] = {
            "url":      getattr(mod, "URL",      ""),
            "api_path": getattr(mod, "API_PATH", "/index.php"),
            "post_key": getattr(mod, "POST_KEY", None),
            "api_type": getattr(mod, "API_TYPE", "gelbooru"),
        }


def write_booru_file(name: str) -> bool:
    """Overwrite the .py file for *name* using data from REGISTRY.

    This ensures the file on disk always matches the in-memory state,
    avoiding the old ``readlines()`` / line-replacement approach that
    could corrupt files when the format changed.

    Returns True on success, False if the booru is not in REGISTRY.
    """
    data = REGISTRY.get(name)
    if not data:
        logging.warning("[boorus] write_booru_file: '%s' not in REGISTRY", name)
        return False

    booru_dir = Path(__file__).resolve().parent
    booru_file = booru_dir / f"{name}.py"

    post_key = data.get("post_key")
    post_key_repr = f'"{post_key}"' if isinstance(post_key, str) else str(post_key)

    content = BOORU_TEMPLATE.format(
        name=name,
        url=data.get("url", ""),
        api_path=data.get("api_path", ""),
        post_key=post_key_repr,
        api_type=data.get("api_type", "gelbooru"),
    )

    try:
        with open(booru_file, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            # Ensure the write hits disk before we try to import from it
            import os as _os
            _os.fsync(f.fileno())
        return True
    except Exception:
        logging.exception("[boorus] Failed to write %s", booru_file)
        return False


def invalidate_cache(name: str) -> None:
    """Remove a booru module from ``sys.modules`` and delete its ``.pyc``.

    Call this after writing a booru file so that the next
    ``importlib.import_module`` picks up the fresh content instead of
    a stale cached bytecode file.
    """
    mod_key = f"boorus.{name}"
    if mod_key in sys.modules:
        del sys.modules[mod_key]

    # Nuke any cached bytecode so an old .pyc doesn't shadow the new .py
    booru_dir = Path(__file__).resolve().parent
    pycache = booru_dir / "__pycache__"
    if pycache.exists():
        for pyc in pycache.glob(f"{name}.cpython-*.pyc"):
            try:
                pyc.unlink()
            except OSError:
                pass
        # Also nuke the variant without cpython tag (older Python)
        for pyc in pycache.glob(f"{name}.*.pyc"):
            try:
                pyc.unlink()
            except OSError:
                pass


def reregister(name: str) -> bool:
    """Re-read a booru .py file and update REGISTRY in-place.

    Used after writing a booru file to ensure the in-memory REGISTRY
    reflects exactly what was written (catches any write errors).
    Returns True if the booru was re-registered successfully.
    """
    invalidate_cache(name)
    try:
        mod = importlib.import_module(f"boorus.{name}")
        REGISTRY[name] = {
            "url":      getattr(mod, "URL",      ""),
            "api_path": getattr(mod, "API_PATH", "/index.php"),
            "post_key": getattr(mod, "POST_KEY", None),
            "api_type": getattr(mod, "API_TYPE", "gelbooru"),
        }
        return True
    except ModuleNotFoundError:
        # The file was deleted — remove from REGISTRY
        REGISTRY.pop(name, None)
        return False
    except Exception:
        logging.exception("[boorus] Failed to re-register '%s'", name)
        return False


_discover()
