"""
credentials.py — Local storage for API keys, tokens and bypass/session cookies.

Format
------
``credentials.v2.bin`` (next to settings.json) holds one JSON object.

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
``credentials.v2.bin.unreadable-<timestamp>`` and an error is logged, instead
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

    #: Current store. A new name (not credentials.bin) so an older exe, which
    #: cannot read DPAPI and would overwrite the file with an empty store,
    #: never sees it. Downgrading just starts logged out instead of wiping.
    FILE_NAME = "credentials.v2.bin"
    #: Written by <= 1.1.x next to the exe: XOR-obfuscated or plain JSON.
    LEGACY_NAME = "credentials.bin"

    @staticmethod
    def _get_credentials_file() -> Path:
        """Path of the DPAPI store (in the data folder, see app_paths)."""
        from ui.settings_view.manager import BASE_DIR
        return BASE_DIR / CredentialManager.FILE_NAME

    @staticmethod
    def _get_legacy_credentials_file() -> Path:
        """Pre-portable %APPDATA% location — only read for one-time migration."""
        appdata = os.environ.get("APPDATA", ".")
        return Path(appdata) / "BooruBrowser" / CredentialManager.LEGACY_NAME

    def _legacy_sources(self) -> list[Path]:
        cred_file = self._get_credentials_file()
        return [
            cred_file.with_name(self.LEGACY_NAME),      # next to the exe (<= 1.1.x)
            self._get_legacy_credentials_file(),         # %APPDATA% (older)
            cred_file.with_name("credentials.json"),     # plaintext (oldest)
        ]

    def _ensure_file_exists(self):
        """Kept for callers; migration happens in _load_credentials, and
        _save_credentials creates the file, so nothing to pre-create here."""
        self._get_credentials_file().parent.mkdir(parents=True, exist_ok=True)

    def _migrate_legacy(self) -> Optional[Dict[str, Any]]:
        """If there is no v2 store yet, import the first readable legacy file.

        The legacy file is deleted only after the v2 store has been written
        and read back successfully (it holds reversible-XOR or plaintext
        secrets, so leaving it around would defeat the encryption).
        """
        for src in self._legacy_sources():
            if not src.exists():
                continue
            try:
                data = json.loads(_decrypt(src.read_text(encoding="utf-8")))
                if not isinstance(data, dict):
                    raise CredentialReadError("not a JSON object")
            except (CredentialReadError, OSError, ValueError) as e:
                logging.warning("[credentials] Could not read legacy %s (%s); left in place", src, e)
                continue
            try:
                self._save_credentials(data)
                check = json.loads(_decrypt(self._get_credentials_file().read_text(encoding="utf-8")))
                if check != data:
                    raise CredentialReadError("read-back mismatch")
            except Exception:
                logging.exception("[credentials] Migration from %s failed; legacy file kept", src)
                return data
            try:
                src.unlink()
            except OSError:
                logging.warning("[credentials] Migrated %s but could not delete it", src)
            logging.info("[credentials] Migrated %s to %s (DPAPI)", src.name,
                         self._get_credentials_file().name)
            return data
        return None

    @staticmethod
    def _read_with_retry(path: Path) -> str:
        """read_text, retrying briefly on PermissionError: an AV scanner or
        sync client often holds the file for a few hundred ms at startup."""
        for delay in (0.1, 0.2, 0.4):
            try:
                return path.read_text(encoding="utf-8")
            except PermissionError:
                time.sleep(delay)
        return path.read_text(encoding="utf-8")

    @_locked
    def _load_credentials(self) -> Dict[str, Any]:
        """Load credentials, migrating legacy files on first use.

        Never returns {} for a file that exists but is unreadable: that file
        is moved aside first so the next save cannot destroy it.
        """
        cred_file = self._get_credentials_file()
        if not cred_file.exists():
            migrated = self._migrate_legacy()
            if migrated is not None:
                return migrated
            return {}

        raw = self._read_with_retry(cred_file)
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

        # A v2 file is always DPAPI on Windows; re-encrypt if it somehow isn't.
        if _have_dpapi() and not raw.lstrip().startswith(_DPAPI_PREFIX):
            try:
                self._save_credentials(data)
            except Exception:
                logging.exception("[credentials] Could not re-encrypt %s", cred_file.name)
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
    def get_sensitive(self, key: str, *, raise_on_error: bool = False) -> dict:
        """Return the stored blob, or {} if absent.

        A failed read also returns {} by default; pass raise_on_error=True
        to tell "unreadable" apart from "no secrets" (the exception propagates).
        """
        try:
            return self._load_credentials().get(key, {})
        except Exception:
            logging.exception("[credentials] Failed to read sensitive data %s", key)
            if raise_on_error:
                raise
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

def get_sensitive(key: str, *, raise_on_error: bool = False) -> dict:
    """Retrieve sensitive data dict (e.g. bypass_data)."""
    return _credential_manager.get_sensitive(key, raise_on_error=raise_on_error)

def set_sensitive(key: str, data: dict) -> bool:
    """Store sensitive data dict securely."""
    return _credential_manager.set_sensitive(key, data)


def set_sensitive_many(items: Dict[str, dict]) -> bool:
    """Store several sensitive data dicts in a single write."""
    return _credential_manager.set_sensitive_many(items)
