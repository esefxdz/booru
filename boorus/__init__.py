"""
boorus/__init__.py

Auto-discovers all built-in booru definitions (*.py files in this package)
and exposes them as the REGISTRY dict. Custom/user-added boorus are merged
into REGISTRY at app startup from settings.json.
"""
from pathlib import Path
import importlib

REGISTRY: dict = {}


def _discover():
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


_discover()
