"""
settings/manager.py — Unified configuration and settings management.

SettingsManager singleton + static constants.
User preferences persisted to %APPDATA%/BooruBrowser.
Credentials stored securely using system keyring.
"""
import json
import os
from pathlib import Path

# --- STATIC CONSTANTS ---
BASE_DIR = Path(__file__).parent.parent
VERSION = "1.0.0"
SEARCH_LIMIT = 50
TIMEOUT = 30.0
DOWNLOAD_DIR = BASE_DIR / "files"
DOWNLOAD_DIR.mkdir(exist_ok=True)
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json"
}

# --- INTERNAL STATE ---
_SETTINGS_DIR  = Path(os.environ.get("APPDATA", ".")) / "BooruBrowser"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"
_BOOKMARKS_FILE = _SETTINGS_DIR / "bookmarks.json"


class SettingsManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SettingsManager, cls).__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        # Default state
        self.active_booru: str = "safebooru"
        self.blacklist: str = ""
        self.favorites: str = ""
        self.booru_order: list = []
        self.thumbnail_size: int = 250
        self.thumbnail_res: int = 720
        self.masonry_mode: bool = False
        self.infinite_scroll: bool = False
        self.reduced_motion: bool = False
        self.use_arrows_for_sorting: bool = False
        self.use_legacy_viewer: bool = False
        self.video_engine: str = "qt"
        self.use_http2: bool = False
        self.proxy_url: str = ""
        self.custom_download_path: str = ""
        self.concurrent_downloads: int = 50
        self.use_network_semaphore: bool = True
        self.download_folder_use_artist_folder: bool = False
        self.use_smart_folders: bool = False
        self.bypass_data: dict = {}
        self.session_keys: dict = {}
        self.auth_tokens: dict  = {}
        self.bookmarks: list = []

    def load(self):
        """Load settings from disk and update singleton attributes."""
        if not _SETTINGS_FILE.exists():
            return
        try:
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[settings] Could not read settings file, using defaults: {e}")
            return

        # --- Migration: thumbnail_size > 500 means it was actually a resolution ---
        if "thumbnail_size" in data and "thumbnail_res" not in data:
            if data["thumbnail_size"] >= 500:
                data["thumbnail_res"] = data["thumbnail_size"]
                data["thumbnail_size"] = 250
            else:
                data.setdefault("thumbnail_res", 720)

        # --- Migration: plaintext credentials → secure keyring storage ---
        if "credentials" in data:
            print("[settings] Migrating plaintext credentials to secure storage...")
            try:
                from credentials import migrate_from_settings
                migrate_from_settings(data["credentials"])
            except Exception as e:
                print(f"[settings] Credential migration failed: {e}")
            del data["credentials"]
            # Re-save without plaintext credentials
            self._raw_save(data)

        # Apply all known keys
        for k, v in data.items():
            if hasattr(self, k):
                setattr(self, k, v)

        self.validate()

    def validate(self):
        """Enforce sane bounds on numeric settings."""
        if self.thumbnail_size < 100:
            self.thumbnail_size = 100
        elif self.thumbnail_size > 600:
            self.thumbnail_size = 600

        if self.thumbnail_res < 100:
            self.thumbnail_res = 100
        elif self.thumbnail_res > 1200:
            self.thumbnail_res = 1200

        if self.concurrent_downloads < 1:
            self.concurrent_downloads = 1
        elif self.concurrent_downloads > 200:
            self.concurrent_downloads = 200

    def save(self):
        """Persist current settings to disk."""
        self.validate()
        data = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        return self._raw_save(data)

    def _raw_save(self, data):
        """Low-level save — writes a dict to the settings JSON file."""
        try:
            _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            tmp = _SETTINGS_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(_SETTINGS_FILE)
            return True
        except Exception as e:
            print(f"[settings] Could not save settings: {e}")
            return False

    # --- Bookmark Helpers ---

    def load_bookmarks(self):
        if not _BOOKMARKS_FILE.exists():
            return
        try:
            with open(_BOOKMARKS_FILE, "r", encoding="utf-8") as f:
                self.bookmarks = json.load(f)
        except Exception as e:
            print(f"[settings] Could not read bookmarks: {e}")

    def save_bookmarks(self):
        try:
            _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            with open(_BOOKMARKS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.bookmarks, f, indent=2)
        except Exception as e:
            print(f"[settings] Could not save bookmarks: {e}")

    def is_post_bookmarked(self, post_id):
        """Check if a post is in the bookmarks list."""
        pid = str(post_id)
        return any(str(p.get("id")) == pid for p in self.bookmarks)

    def add_bookmark(self, post):
        if not self.is_post_bookmarked(post.get("id")):
            if "_booru" not in post:
                post["_booru"] = self.active_booru
            self.bookmarks.append(post)
            self.save_bookmarks()

    def remove_bookmark(self, post_id):
        pid = str(post_id)
        self.bookmarks = [p for p in self.bookmarks if str(p.get("id")) != pid]
        self.save_bookmarks()

    # --- Credentials helpers ---

    def get_credential(self, booru):
        """Retrieve API credentials from secure storage."""
        from credentials import get_credential
        return get_credential(booru)

    def set_credential(self, booru, user_id, api_key):
        """Store API credentials securely using encrypted local storage."""
        from credentials import set_credential
        set_credential(booru, user_id, api_key)

    # --- Bypass helpers ---

    def save_bypass(self, name, cookies, user_agent):
        self.bypass_data[name] = {"cookies": cookies, "user_agent": user_agent}
        self.save()

    # --- Path helpers ---
    
    def get_download_dir(self):
        """Returns the user's custom download path, or the default files/ dir."""
        if self.custom_download_path:
            p = Path(self.custom_download_path)
            if p.exists() and p.is_dir():
                return p
        return DOWNLOAD_DIR

manager = SettingsManager()
