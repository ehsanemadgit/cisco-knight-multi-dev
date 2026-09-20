"""Passwords stay outside the inventory and MCP arguments."""
import base64
import getpass
import json
import os
import sys
import warnings

import keyring
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .inventory import atomic_write

def hidden(prompt):
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt, stream=sys.stderr)


SERVICE = "ehsan-multi-r-and-s-mcp"
TRUSTED_BACKENDS = {"keyring.backends.macOS", "keyring.backends.Windows", "keyring.backends.SecretService", "keyring.backends.kwallet"}


def native_keyring():
    backend = keyring.get_keyring()
    candidates = getattr(backend, "backends", [backend])
    for candidate in candidates:
        if type(candidate).__module__ in TRUSTED_BACKENDS and candidate.priority > 0:
            return candidate
    raise ValueError("No supported OS credential store is available. Choose encrypted storage or session-only credentials.")


class Credentials:
    def __init__(self, root, interactive=False):
        self.root = root
        self.interactive = interactive
        self.session = {}
        self.master = os.environ.get("EHSAN_MCP_MASTER_PASSWORD")

    def _master(self, new=False):
        if not self.master:
            if not self.interactive:
                raise ValueError("Encrypted vault is locked. Launch with --unlock-vault in a terminal or provide EHSAN_MCP_MASTER_PASSWORD via your secret manager.")
            master = hidden("Vault master password: ")
            if len(master) < 12:
                raise ValueError("Use a master password of at least 12 characters.")
            if new and master != hidden("Confirm master password: "):
                raise ValueError("Master passwords do not match.")
            self.master = master
        return self.master

    def _vault(self):
        path = self.root / "credentials.enc.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            salt = base64.b64decode(payload["salt"], validate=True)
        else:
            payload = None
            salt = os.urandom(16)
        key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(self._master(new=payload is None).encode())
        cipher = Fernet(base64.urlsafe_b64encode(key))
        try:
            values = json.loads(cipher.decrypt(payload["ciphertext"].encode())) if payload else {}
        except InvalidToken:
            self.master = None
            raise ValueError("Wrong master password or damaged credential vault.") from None
        return path, salt, cipher, values

    def put(self, device, password, enable=""):
        value = {"password": password, "enable": enable}
        if not password or (device.enable_required and not enable):
            raise ValueError("Required password is empty.")
        if device.credential_store == "keyring":
            native_keyring().set_password(SERVICE, device.credential_id, json.dumps(value))
        elif device.credential_store == "encrypted":
            path, salt, cipher, values = self._vault()
            values[device.credential_id] = value
            atomic_write(path, json.dumps({"salt": base64.b64encode(salt).decode(), "ciphertext": cipher.encrypt(json.dumps(values).encode()).decode()}))
        elif device.credential_store == "session":
            self.session[device.credential_id] = value
        else:
            raise ValueError("Environment credentials must be supplied by the launcher.")

    def get(self, device):
        if device.credential_store == "keyring":
            raw = native_keyring().get_password(SERVICE, device.credential_id)
            if not raw:
                raise ValueError("No credentials found in the OS credential store.")
            value = json.loads(raw)
        elif device.credential_store == "encrypted":
            value = self._vault()[3].get(device.credential_id, {})
        elif device.credential_store == "environment":
            value = {"password": os.environ.get(device.credential_id + "_PASSWORD", ""), "enable": os.environ.get(device.credential_id + "_ENABLE", "")}
        else:
            value = self.session.get(device.credential_id, {})
            if not value and self.interactive:
                self.put(device, hidden(f"SSH password for {device.name}: "), hidden(f"Enable password for {device.name}: ") if device.enable_required else "")
                value = self.session[device.credential_id]
        if not value.get("password") or (device.enable_required and not value.get("enable")):
            raise ValueError("Credentials unavailable. Run setup, or launch serve --prompt-secrets for session-only devices.")
        return value

    def delete(self, device):
        if device.credential_store == "keyring":
            native_keyring().delete_password(SERVICE, device.credential_id)
        elif device.credential_store == "encrypted":
            path, salt, cipher, values = self._vault()
            values.pop(device.credential_id, None)
            atomic_write(path, json.dumps({"salt": base64.b64encode(salt).decode(), "ciphertext": cipher.encrypt(json.dumps(values).encode()).decode()}))
        self.session.pop(device.credential_id, None)
