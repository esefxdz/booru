"""
credentials.py — Local storage for API keys, tokens and bypass/session cookies.

Format
------
``credentials.bin`` (next to settings.json) holds one JSON object.

* On Windows it is encrypted with DPAPI (``CryptProtectData``), the same
  mechanism browsers use: only the same Windows user account can decrypt
  it, and another program running as you still can. The file starts with
  ``DPAPI1:``.
* Files written by older versions are XOR-obfuscated with a key derived
  from the MAC address + username (reversible by anyone who reads this
  code) or plain JSON. They are read once and rewritten as DPAPI.

Because DPAPI is tied to the Windows account, copying the app folder to
another PC/account means saved logins have to be entered again. The old
XOR scheme had the same limitation (its key included the MAC address).

If the file cannot be decrypted it is renamed to
``credentials.bin.unreadable-<timestamp>`` and an error is logged, instead
of being silently overwritten with an empty store.
"""
import base64
import ctypes
import hashlib
import json
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

_DPAPI_PREFIX = "DPAPI1:"
_ENTROPY = b"BooruBrowser credentials v1"


# One lock for every read-modify-write of credentials.bin. Saves happen on the
# GUI thread and on the asyncio thread (e.g. clearing a Cloudflare bypass);
# without this, concurrent saves silently dropped each other's changes.
_LOCK = threading.RLock()


def _locked(fn):
    def wrapper(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


class CredentialReadError(Exception):
    """credentials.bin exists but could not be decrypted/parsed."""


# ---------------------------------------------------------------------------
# DPAPI (Windows) via ctypes — no pywin32 dependency
# ---------------------------------------------------------------------------

class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> "_DataBlob":
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob._buf = buf  # keep the buffer alive as long as the blob
    return blob


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    src, entropy, out = _blob(data), _blob(_ENTROPY), _DataBlob()
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(src), None, ctypes.byref(entropy), None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        raise OSError(f"DPAPI {'protect' if protect else 'unprotect'} failed (error {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def _have_dpapi() -> bool:
    return sys.platform == "win32"


# ---------------------------------------------------------------------------
# Legacy XOR obfuscation (read-only migration; also the non-Windows fallback)
# ---------------------------------------------------------------------------

def _get_machine_key() -> bytes:
    mac = str(uuid.getnode())
    user = os.environ.get("USERNAME", os.environ.get("USER", "unknown"))
    return hashlib.sha256(f"{mac}_{user}".encode()).digest()


def _xor(data: bytes) -> bytes:
    key = _get_machine_key()
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


# ---------------------------------------------------------------------------
# Encode / decode
# ---------------------------------------------------------------------------

def _encrypt(data: str) -> str:
    raw = data.encode("utf-8")
    if _have_dpapi():
        return _DPAPI_PREFIX + base64.b64encode(_dpapi(raw, protect=True)).decode("ascii")
    # Non-Windows: obfuscation only. The app targets Windows.
    return base64.b64encode(_xor(raw)).decode("ascii")


def _decrypt(data: str) -> str:
    """Return the JSON text stored in *data*. Raises CredentialReadError."""
    data = (data or "").strip()
    if not data:
        return "{}"
    try:
        if data.startswith(_DPAPI_PREFIX):
            if not _have_dpapi():
                raise CredentialReadError("DPAPI-encrypted file cannot be read on this OS")
            text = _dpapi(base64.b64decode(data[len(_DPAPI_PREFIX):]), protect=False).decode("utf-8")
        else:
            try:                     # legacy plaintext JSON
                json.loads(data)
                return data
            except json.JSONDecodeError:
                pass
            text = _xor(base64.b64decode(data)).decode("utf-8")   # legacy XOR
        json.loads(text)
        return text
    except CredentialReadError:
        raise
    except Exception as e:
        raise CredentialReadError(str(e)) from e


class CredentialManager:
    """Credential storage in a DPAPI-encrypted local JSON file."""

    @staticmethod
    def _get_credentials_file() -> Path:
        """Get the path to the credentials file.

        Stored next to settings.json in the app directory so the whole
        folder is portable (copy to USB, another machine, etc.).
        Falls back to the legacy %APPDATA% location for migration.
        """
        from ui.settings_view.manager import BASE_DIR
        return BASE_DIR / "credentials.bin"

    @staticmethod
    def _get_legacy_credentials_file() -> Path:
        """Legacy %APPDATA% path — only used for one-time migration."""
        appdata = os.environ.get("APPDATA", ".")
        return Path(appdata) / "BooruBrowser" / "credentials.bin"

    def _ensure_file_exists(self):
        """Ensure the credentials file and directory exist."""
        cred_file = self._get_credentials_file()
        cred_file.parent.mkdir(parents=True, exist_ok=True)
        if not cred_file.exists():
            cred_file.write_text(_encrypt("{}"))

    @_locked
    def _load_credentials(self) -> Dict[str, Any]:
        """Load credentials, migrating legacy locations/formats if needed.

        Never returns {} for a file that exists but is unreadable: that file
        is moved aside first so the next save cannot destroy it.
        """
        cred_file = self._get_credentials_file()

        # One-time migration from the legacy %APPDATA% location / JSON file.
        if not cred_file.exists():
            legacy_bin = self._get_legacy_credentials_file()
            legacy_json = cred_file.with_name("credentials.json")
            if legacy_bin.exists():
                try:
                    cred_file.parent.mkdir(parents=True, exist_ok=True)
                    import shutil
                    shutil.copy2(legacy_bin, cred_file)
                    legacy_bin.unlink(missing_ok=True)
                    logging.info("[credentials] Migrated credentials.bin from %APPDATA%")
                except Exception as me:
                    logging.warning("[credentials] Could not migrate legacy credentials.bin: %s", me)
            elif legacy_json.exists():
                try:
                    data = json.loads(legacy_json.read_text(encoding="utf-8"))
                    self._save_credentials(data)
                    legacy_json.unlink()
                    return data
                except Exception as e:
                    logging.warning("[credentials] Could not migrate credentials.json: %s", e)

        if not cred_file.exists():
            return {}

        raw = cred_file.read_text(encoding="utf-8")
        try:
            data = json.loads(_decrypt(raw))
            if not isinstance(data, dict):
                raise CredentialReadError("credentials file is not a JSON object")
        except CredentialReadError as e:
            aside = cred_file.with_name(f"{cred_file.name}.unreadable-{int(time.time())}")
            try:
                cred_file.replace(aside)
                logging.error(
                    "[credentials] Could not decrypt %s (%s). Moved it to %s; "
                    "saved logins must be entered again.", cred_file.name, e, aside.name)
            except OSError:
                logging.exception("[credentials] Could not decrypt or move aside %s", cred_file)
                raise
            return {}

        # Upgrade legacy XOR/plaintext files to DPAPI in place.
        if _have_dpapi() and not raw.lstrip().startswith(_DPAPI_PREFIX):
            try:
                self._save_credentials(data)
                logging.info("[credentials] Upgraded credentials.bin to DPAPI encryption")
            except Exception:
                logging.exception("[credentials] Could not upgrade credentials.bin to DPAPI")
        return data

    def _save_credentials(self, credentials: Dict[str, Any]):
        """Encrypt and atomically write credentials to disk."""
        from fileutil import atomic_write_text
        atomic_write_text(self._get_credentials_file(), _encrypt(json.dumps(credentials)))

    @_locked
    def set_credential(self, booru: str, user_id: str, api_key: str) -> bool:
        """
        Store API credentials.

        Args:
            booru: Name of the booru site (e.g., 'danbooru', 'e621')
            user_id: Username or user ID
            api_key: API key or password

        Returns:
            bool: True if stored successfully, False otherwise
        """
        try:
            self._ensure_file_exists()
            credentials = self._load_credentials()
            credentials[booru] = {
                "user_id": user_id,
                "api_key": api_key
            }
            self._save_credentials(credentials)
            return True
        except Exception as e:
            logging.error(f"[credentials] Failed to store credentials for {booru}: {e}")
            return False

    @_locked
    def get_credential(self, booru: str) -> Optional[Dict[str, str]]:
        """
        Retrieve API credentials.

        Args:
            booru: Name of the booru site

        Returns:
            Dict with 'user_id' and 'api_key' keys, or None if not found
        """
        try:
            credentials = self._load_credentials()
            return credentials.get(booru)
        except Exception as e:
            logging.error(f"[credentials] Failed to retrieve credentials for {booru}: {e}")
            return None

    @_locked
    def delete_credential(self, booru: str) -> bool:
        """
        Delete stored credentials for a booru site.

        Args:
            booru: Name of the booru site

        Returns:
            bool: True if deleted successfully, False otherwise
        """
        try:
            credentials = self._load_credentials()
            if booru in credentials:
                del credentials[booru]
                self._save_credentials(credentials)
            return True
        except Exception as e:
            logging.error(f"[credentials] Failed to delete credentials for {booru}: {e}")
            return False

    @_locked
    def list_boorus_with_credentials(self) -> list[str]:
        """
        Get list of booru sites that have stored credentials.

        Returns:
            List of booru names that have credentials stored
        """
        try:
            credentials = self._load_credentials()
            return [k for k in credentials.keys() if not k.startswith("_")]
        except Exception:
            logging.exception("[credentials] Failed to list credentials")
            return []

    @_locked
    def get_sensitive(self, key: str) -> dict:
        try:
            return self._load_credentials().get(key, {})
        except Exception:
            logging.exception("[credentials] Failed to read sensitive data %s", key)
            return {}

    @_locked
    def set_sensitive(self, key: str, data: dict) -> bool:
        try:
            self._ensure_file_exists()
            credentials = self._load_credentials()
            credentials[key] = data
            self._save_credentials(credentials)
            return True
        except Exception as e:
            logging.error(f"[credentials] Failed to save sensitive data {key}: {e}")
            return False

    @_locked
    def set_sensitive_many(self, items: Dict[str, dict]) -> bool:
        """Store several sensitive blobs in one read-modify-write."""
        try:
            self._ensure_file_exists()
            credentials = self._load_credentials()
            credentials.update(items)
            self._save_credentials(credentials)
            return True
        except Exception as e:
            logging.error(f"[credentials] Failed to save sensitive data {sorted(items)}: {e}")
            return False

    @_locked
    def migrate_from_settings(self, settings_credentials: Dict[str, Any]) -> None:
        """
        Migrate credentials from settings.json to separate credentials file.

        Args:
            settings_credentials: Dict of credentials from old settings format
        """
        if not settings_credentials:
            return

        logging.info(f"[credentials] Migrating {len(settings_credentials)} credential(s) to separate file...")
        migrated_count = 0

        for booru, cred_data in settings_credentials.items():
            if isinstance(cred_data, dict) and "user_id" in cred_data and "api_key" in cred_data:
                if self.set_credential(booru, cred_data["user_id"], cred_data["api_key"]):
                    migrated_count += 1
                    logging.info(f"[credentials] Migrated {booru}")

        if migrated_count > 0:
            logging.info(f"[credentials] Successfully migrated {migrated_count} credential(s)")


# Global instance for easy access
_credential_manager = CredentialManager()


# --- Module-level functions for backward compatibility ---
def set_credential(booru: str, user_id: str, api_key: str) -> bool:
    """Store API credentials."""
    return _credential_manager.set_credential(booru, user_id, api_key)

def get_credential(booru: str) -> Optional[Dict[str, str]]:
    """Retrieve API credentials."""
    return _credential_manager.get_credential(booru)

def delete_credential(booru: str) -> bool:
    """Delete stored credentials."""
    return _credential_manager.delete_credential(booru)

def list_boorus_with_credentials() -> list[str]:
    """Get list of booru sites with stored credentials."""
    return _credential_manager.list_boorus_with_credentials()

def migrate_from_settings(settings_credentials: Dict[str, Any]) -> None:
    """Migrate credentials from settings.json."""
    _credential_manager.migrate_from_settings(settings_credentials)

def get_sensitive(key: str) -> dict:
    """Retrieve sensitive data dict (e.g. bypass_data)."""
    return _credential_manager.get_sensitive(key)

def set_sensitive(key: str, data: dict) -> bool:
    """Store sensitive data dict securely."""
    return _credential_manager.set_sensitive(key, data)


def set_sensitive_many(items: Dict[str, dict]) -> bool:
    """Store several sensitive data dicts in a single write."""
    return _credential_manager.set_sensitive_many(items)
