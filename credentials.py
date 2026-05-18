"""
credentials.py — Simple credential storage.

Stores API credentials in plain text for simplicity and reliability.
Not encrypted, but acceptable risk for local desktop app.
"""
import os
import json
import uuid
import hashlib
import base64
from pathlib import Path
from typing import Optional, Dict, Any

def _get_machine_key() -> bytes:
    mac = str(uuid.getnode())
    user = os.environ.get("USERNAME", os.environ.get("USER", "unknown"))
    salt = f"{mac}_{user}".encode()
    return hashlib.sha256(salt).digest()

def _encrypt(data: str) -> str:
    key = _get_machine_key()
    encrypted = bytearray()
    for i, b in enumerate(data.encode('utf-8')):
        encrypted.append(b ^ key[i % len(key)])
    return base64.b64encode(encrypted).decode('utf-8')

def _decrypt(data: str) -> str:
    try:
        if not data: return "{}"
        # Try to parse as JSON directly first (in case it's legacy plaintext)
        try:
            json.loads(data)
            return data
        except json.JSONDecodeError:
            pass
            
        key = _get_machine_key()
        encrypted_bytes = base64.b64decode(data.encode('utf-8'))
        decrypted = bytearray()
        for i, b in enumerate(encrypted_bytes):
            decrypted.append(b ^ key[i % len(key)])
        return decrypted.decode('utf-8')
    except Exception:
        return "{}"


class CredentialManager:
    """Simple credential storage using encrypted local JSON file."""

    @staticmethod
    def _get_credentials_file() -> Path:
        """Get the path to the credentials file."""
        appdata = os.environ.get("APPDATA", ".")
        return Path(appdata) / "BooruBrowser" / "credentials.bin"

    def _ensure_file_exists(self):
        """Ensure the credentials file and directory exist."""
        cred_file = self._get_credentials_file()
        cred_file.parent.mkdir(parents=True, exist_ok=True)
        if not cred_file.exists():
            cred_file.write_text(_encrypt("{}"))

    def _load_credentials(self) -> Dict[str, Any]:
        """Load credentials from file."""
        try:
            cred_file = self._get_credentials_file()
            # Support legacy plaintext file if exists and bin doesn't
            legacy_file = cred_file.with_name("credentials.json")
            
            if cred_file.exists():
                return json.loads(_decrypt(cred_file.read_text()))
            elif legacy_file.exists():
                data = json.loads(legacy_file.read_text())
                # Migrate to encrypted format
                self._save_credentials(data)
                legacy_file.unlink()
                return data
            return {}
        except Exception as e:
            print(f"[credentials] Failed to load credentials: {e}")
            return {}

    def _save_credentials(self, credentials: Dict[str, Any]):
        """Save credentials to file."""
        try:
            cred_file = self._get_credentials_file()
            cred_file.parent.mkdir(parents=True, exist_ok=True)
            encrypted = _encrypt(json.dumps(credentials))
            cred_file.write_text(encrypted)
        except Exception as e:
            print(f"[credentials] Failed to save credentials: {e}")
            raise

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
            print(f"[credentials] Failed to store credentials for {booru}: {e}")
            return False

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
            print(f"[credentials] Failed to retrieve credentials for {booru}: {e}")
            return None

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
            print(f"[credentials] Failed to delete credentials for {booru}: {e}")
            return False

    def list_boorus_with_credentials(self) -> list[str]:
        """
        Get list of booru sites that have stored credentials.

        Returns:
            List of booru names that have credentials stored
        """
        try:
            credentials = self._load_credentials()
            return list(credentials.keys())
        except Exception:
            return []

    def migrate_from_settings(self, settings_credentials: Dict[str, Any]) -> None:
        """
        Migrate credentials from settings.json to separate credentials file.

        Args:
            settings_credentials: Dict of credentials from old settings format
        """
        if not settings_credentials:
            return

        print(f"[credentials] Migrating {len(settings_credentials)} credential(s) to separate file...")
        migrated_count = 0

        for booru, cred_data in settings_credentials.items():
            if isinstance(cred_data, dict) and "user_id" in cred_data and "api_key" in cred_data:
                if self.set_credential(booru, cred_data["user_id"], cred_data["api_key"]):
                    migrated_count += 1
                    print(f"[credentials] Migrated {booru}")

        if migrated_count > 0:
            print(f"[credentials] Successfully migrated {migrated_count} credential(s)")


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