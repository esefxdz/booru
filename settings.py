"""
settings.py — Unified configuration and settings management.

Static constants and user preferences persisted to %APPDATA%/BooruBrowser.
"""
import json
import os
from pathlib import Path

# --- STATIC CONSTANTS ---
SEARCH_LIMIT = 50
TIMEOUT = 30.0

DOWNLOAD_DIR = Path("files")
DOWNLOAD_DIR.mkdir(exist_ok=True)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json"
}

# --- DYNAMIC USER PREFERENCES (DEFAULTS) ---
ACTIVE_BOORU = "safebooru"
BLACKLIST = ""
THUMBNAIL_SIZE = 250
CREDENTIALS = {}
BYPASS_DATA = {}
BOORU_ORDER = []
USE_ARROWS_FOR_SORTING = False
BOOKMARKS = []

# --- INTERNAL STATE ---
_SETTINGS_DIR  = Path(os.environ.get("APPDATA", ".")) / "BooruBrowser"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"
_BOOKMARKS_FILE = _SETTINGS_DIR / "bookmarks.json"

_data: dict = {}

def load():
    """Load settings from disk and update module globals."""
    global ACTIVE_BOORU, BLACKLIST, THUMBNAIL_SIZE, CREDENTIALS, BYPASS_DATA, BOORU_ORDER, USE_ARROWS_FOR_SORTING, _data
    if _SETTINGS_FILE.exists():
        try:
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                _data.update(json.load(f))
        except Exception as e:
            print(f"[settings] Could not read settings file, using defaults: {e}")
            
    ACTIVE_BOORU = _data.get("active_booru", ACTIVE_BOORU)
    BLACKLIST = _data.get("blacklist", BLACKLIST)
    THUMBNAIL_SIZE = _data.get("thumbnail_size", THUMBNAIL_SIZE)
    CREDENTIALS.update(_data.get("credentials", {}))
    BYPASS_DATA.update(_data.get("bypass_data", {}))
    BOORU_ORDER = _data.get("booru_order", [])
    USE_ARROWS_FOR_SORTING = _data.get("use_arrows_for_sorting", False)

def save():
    """Persist current settings to disk."""
    global _data
    _data["active_booru"] = ACTIVE_BOORU
    _data["blacklist"] = BLACKLIST
    _data["thumbnail_size"] = THUMBNAIL_SIZE
    _data["credentials"] = CREDENTIALS
    _data["bypass_data"] = BYPASS_DATA
    _data["booru_order"] = BOORU_ORDER
    _data["use_arrows_for_sorting"] = USE_ARROWS_FOR_SORTING
    try:
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(_data, f, indent=2)
        return True
    except Exception as e:
        print(f"[settings] Could not save settings: {e}")
        return False

# --- Bookmark Helpers ---
def load_bookmarks():
    global BOOKMARKS
    if _BOOKMARKS_FILE.exists():
        try:
            with open(_BOOKMARKS_FILE, "r", encoding="utf-8") as f:
                BOOKMARKS = json.load(f)
        except Exception as e:
            print(f"[settings] Could not read bookmarks: {e}")

def save_bookmarks():
    try:
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(_BOOKMARKS_FILE, "w", encoding="utf-8") as f:
            json.dump(BOOKMARKS, f, indent=2)
    except Exception as e:
        print(f"[settings] Could not save bookmarks: {e}")

# --- Credentials helpers ---
def set_credential(booru: str, user_id: str, api_key: str) -> None:
    CREDENTIALS[booru] = {"user_id": user_id, "api_key": api_key}

# --- Bypass helpers ---
def save_bypass(name: str, cf_clearance: str, user_agent: str) -> None:
    BYPASS_DATA[name] = {"cf_clearance": cf_clearance, "user_agent": user_agent}
    save()
