"""SettingsManager singleton; preferences in settings.json, secrets in credentials.bin."""
import logging
import json
import shutil
from pathlib import Path
from core.credentials import migrate_from_settings, get_sensitive, set_sensitive_many, get_credential, set_credential
from updater.version import __version__ as VERSION

import threading
import time
from core.app_paths import data_dir, legacy_appdata_dir
BASE_DIR = data_dir()
SEARCH_LIMIT = 50
TIMEOUT = 30.0
DOWNLOAD_DIR = BASE_DIR / "files"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json"
}

_SETTINGS_DIR  = BASE_DIR
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"

# Serialises saves from the GUI thread and the asyncio thread.
_SAVE_LOCK = threading.RLock()

# Secret fields -> their key in the credentials store. Never written to
# settings.json (except unmigrated plaintext from old builds, see load()).
_SECRET_STORE_KEYS = {
    "bypass_data": "_bypass_data",
    "session_keys": "_session_keys",
    "auth_tokens": "_auth_tokens",
}


class SettingsManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SettingsManager, cls).__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.active_booru: str = "safebooru"
        self.blacklist: str = ""
        self.favorites: str = ""
        self.booru_order: list = ["safebooru"]  # fresh-profile default; load() overrides
        self.thumbnail_size: int = 250
        self.thumbnail_res: int = 720
        self.masonry_mode: bool = False
        self.infinite_scroll: bool = False
        self.reduced_motion: bool = False
        self.use_arrows_for_sorting: bool = False
        self.use_legacy_viewer: bool = False
        self.video_engine: str = "qt"
        self.use_http2: bool = False
        self.cf_bypass_method: str = "auto"
        self.proxy_url: str = ""
        self.custom_download_path: str = ""
        self.concurrent_downloads: int = 50
        self.use_network_semaphore: bool = True
        self.use_rate_limit: bool = True
        self.rate_limit_delay: float = 0.25
        self.custom_user_agent: str = ""
        self.download_folder_use_artist_folder: bool = False
        self.use_smart_folders: bool = False
        self.download_engine: str = "urllib"
        self.bypass_data: dict = {}
        self.session_keys: dict = {}
        self.auth_tokens: dict  = {}
        self._initialized = False
        self._save_disabled = False
        # True when the secrets store could not be read at load(); save() then
        # leaves it alone so it can't overwrite real cookies with empty dicts.
        self._secrets_unloaded = False
        # Plaintext secrets found in an old settings.json that are not yet
        # verified in the credentials store; save() keeps them in the file.
        self._legacy_plaintext = None

    def initialize(self):
        """Create folders, migrate legacy settings, load. Call at startup."""
        if self._initialized:
            return
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        legacy = legacy_appdata_dir() / "settings.json"
        if not _SETTINGS_FILE.exists() and legacy.exists():
            try:
                shutil.copy2(legacy, _SETTINGS_FILE)
                logging.info(
                    "[settings] Migrated settings from %s → %s",
                    legacy, _SETTINGS_FILE,
                )
            except Exception as e:
                logging.warning("[settings] Could not migrate legacy settings: %s", e)
        self.load()
        self._initialized = True

    def load(self):
        data = {}
        if _SETTINGS_FILE.exists():
            try:
                with open(_SETTINGS_FILE, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("settings.json is not a JSON object")
            except (ValueError, UnicodeDecodeError) as e:
                # Corrupt file: keep a copy instead of letting the next save
                # overwrite it, then continue with defaults.
                aside = _SETTINGS_FILE.with_name(f"settings.json.unreadable-{int(time.time())}")
                try:
                    _SETTINGS_FILE.replace(aside)
                    logging.error("[settings] settings.json is corrupt (%s); moved it to %s "
                                  "and started from defaults", e, aside.name)
                except OSError:
                    logging.exception("[settings] settings.json is corrupt and could not be moved aside")
                    self._save_disabled = True
                data = {}
            except OSError as e:
                # Locked / permission problem: don't overwrite what we couldn't read.
                logging.error("[settings] Could not read settings.json (%s); "
                              "changes this session will not be saved", e)
                self._save_disabled = True
                data = {}

        # Old builds stored the resolution in thumbnail_size.
        if "thumbnail_size" in data and "thumbnail_res" not in data:
            if data["thumbnail_size"] >= 500:
                data["thumbnail_res"] = data["thumbnail_size"]
                data["thumbnail_size"] = 250
            else:
                data.setdefault("thumbnail_res", 720)

        if "credentials" in data:
            logging.info("[settings] Migrating plaintext credentials to secure storage...")
            try:
                migrate_from_settings(data["credentials"])
            except Exception as e:
                logging.error(f"[settings] Credential migration failed: {e}")
            del data["credentials"]
            self._raw_save(data)

        for k, v in data.items():
            if hasattr(self, k):
                setattr(self, k, v)

        # Builds before 2026-05-19 saved these in plaintext in settings.json.
        # Read, never removed from `data`: the file keeps them until they are
        # verified in the credentials store.
        plaintext = {k: data[k] for k in _SECRET_STORE_KEYS
                     if isinstance(data.get(k), dict) and data[k]}

        try:
            stored = {k: get_sensitive(sk, raise_on_error=True) or {}
                      for k, sk in _SECRET_STORE_KEYS.items()}
        except Exception as e:
            self._secrets_unloaded = True
            self._legacy_plaintext = plaintext or None  # nothing migrated, keep it
            logging.error(f"[settings] Failed to load sensitive data ({e}); "
                          "saved logins/cookies will not be written this session")
        else:
            self._secrets_unloaded = False
            self._legacy_plaintext = None
            if plaintext:
                stored = self._migrate_plaintext_secrets(plaintext, stored)
            for k, v in stored.items():
                setattr(self, k, v)

        self.validate()
        self._reconcile_active_booru()

    def _migrate_plaintext_secrets(self, plaintext, stored):
        """Merge old plaintext secrets into the store (store entries win); returns the merged values.

        If the write can't be read back, the plaintext stays pending and save() keeps it.
        """
        if not all(isinstance(stored[k], dict) for k in plaintext):
            logging.error("[settings] Credentials store has an unexpected format; "
                          "keeping old cookies/logins in settings.json")
            self._legacy_plaintext = plaintext
            return stored
        merged = dict(stored)
        for k, plain in plaintext.items():
            merged[k] = {**plain, **stored[k]}
        if merged == stored:
            return stored  # already in the store; the next save drops the plaintext
        with _SAVE_LOCK:
            try:
                ok = set_sensitive_many({_SECRET_STORE_KEYS[k]: merged[k] for k in plaintext})
                check = {k: get_sensitive(sk, raise_on_error=True) or {}
                         for k, sk in _SECRET_STORE_KEYS.items()} if ok else None
            except Exception:
                logging.exception("[settings] Reading back migrated cookies/logins failed")
                check = None
        if check != merged:
            self._legacy_plaintext = plaintext
            logging.error("[settings] Could not move cookies/logins from settings.json to "
                          "the credentials store; keeping them in settings.json for now")
        else:
            logging.info("[settings] Moved cookies/logins from settings.json to the "
                         "credentials store (%s)", ", ".join(sorted(plaintext)))
        return merged

    def _reconcile_active_booru(self):
        """Switch to an existing booru if the saved one was deleted."""
        import boorus
        if self.active_booru in boorus.REGISTRY:
            return
        fallback = next((b for b in self.booru_order if b in boorus.REGISTRY), None)             or next(iter(boorus.REGISTRY), "safebooru")
        logging.warning("[settings] Active booru %r no longer exists; using %r",
                        self.active_booru, fallback)
        self.active_booru = fallback

    def validate(self):
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

        if not self.booru_order:
            self.booru_order = ["safebooru"]

    def save(self):
        # Never save fresh-init defaults before load() has run.
        if not self._initialized:
            logging.debug("[settings] save() called before initialize() — skipped.")
            return False
        if self._save_disabled:
            logging.warning("[settings] save() skipped: settings.json could not be read this session")
            return False
        self.validate()
        # Secrets must never reach the plaintext settings.json.
        _SENSITIVE_KEYS = set(_SECRET_STORE_KEYS)
        
        with _SAVE_LOCK:
            # One credentials.bin write for all three so cycles can't interleave.
            if self._secrets_unloaded:
                logging.warning("[settings] save(): secrets store was unreadable at "
                                "startup; not writing cookies/tokens (would erase them)")
            elif not set_sensitive_many({
                "_bypass_data": self.bypass_data,
                "_session_keys": self.session_keys,
                "_auth_tokens": self.auth_tokens,
            }):
                logging.error("[settings] save(): could not write cookies/tokens to "
                              "the credentials store; they were not saved")
            data = {
                k: v for k, v in self.__dict__.items()
                if not k.startswith("_") and k not in _SENSITIVE_KEYS
            }
            if self._legacy_plaintext:
                # Old plaintext not yet verified in the store: keep it in
                # settings.json rather than lose it (load() retries).
                data.update(self._legacy_plaintext)
            return self._raw_save(data)

    def _raw_save(self, data):
        from core.fileutil import atomic_write_text
        try:
            with _SAVE_LOCK:
                atomic_write_text(_SETTINGS_FILE, json.dumps(data, indent=2))
            return True
        except Exception as e:
            logging.error(f"[settings] Could not save settings: {e}")
            return False

    def get_credential(self, booru):
        return get_credential(booru)

    def set_credential(self, booru, user_id, api_key):
        set_credential(booru, user_id, api_key)

    def save_bypass(self, name, cookies, user_agent):
        self.bypass_data[name] = {"cookies": cookies, "user_agent": user_agent}
        self.save()

    def get_download_dir(self):
        if self.custom_download_path:
            p = Path(self.custom_download_path)
            if p.exists() and p.is_dir():
                return p
        return DOWNLOAD_DIR

    def get_user_agent(self) -> str:
        if self.custom_user_agent.strip():
            return self.custom_user_agent.strip()
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

manager = SettingsManager()
