from dataclasses import dataclass, asdict
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile

from platformdirs import user_config_path

PLATFORMS = {"cisco_ios": "Cisco IOS / IOS-XE", "cisco_nxos": "Cisco NX-OS", "cisco_xr": "Cisco IOS-XR"}


def data_dir(value=None):
    return Path(value or os.environ.get("CISCO_KNIGHT_MCP_DATA_DIR") or user_config_path("cisco-knight-multi-dev", appauthor=False))


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@dataclass(frozen=True)
class Device:
    name: str
    host: str
    username: str
    port: int = 22
    platform: str = "cisco_ios"
    enable_required: bool = False
    ssh_profile: str = "modern"
    credential_store: str = "keyring"
    credential_id: str = ""

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", self.name):
            raise ValueError("Device name must contain 1–64 letters, digits, dots, dashes or underscores.")
        try:
            ipaddress.ip_address(self.host)
        except ValueError:
            if not re.fullmatch(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", self.host):
                raise ValueError("Enter a valid IP address or hostname (without a URL or port).")
        if not self.username or any(ord(c) < 32 for c in self.username):
            raise ValueError("SSH username is required and cannot contain control characters.")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("SSH port must be between 1 and 65535.")
        if self.platform not in PLATFORMS:
            raise ValueError("Supported platforms: Cisco IOS/IOS-XE, NX-OS and IOS-XR.")
        if self.ssh_profile not in {"modern", "legacy"}:
            raise ValueError("Unknown SSH compatibility profile.")
        if self.credential_store not in {"keyring", "encrypted", "session", "environment"}:
            raise ValueError("Unknown credential store.")


class Inventory:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "devices.json"
        self.known_hosts = self.root / "known_hosts"

    def devices(self):
        if not self.path.exists():
            return {}
        content = json.loads(self.path.read_text(encoding="utf-8"))
        if content.get("version") != 1:
            raise ValueError("Unsupported inventory format.")
        result = {}
        for item in content["devices"]:
            device = Device(**item)
            if device.name in result:
                raise ValueError("Duplicate device name in inventory.")
            result[device.name] = device
        return result

    def get(self, name):
        devices = self.devices()
        if name not in devices:
            raise ValueError(f"Unknown device '{name}'. Use list_devices or the setup wizard.")
        return devices[name]

    def add(self, device):
        devices = self.devices()
        if device.name in devices:
            raise ValueError("That device name already exists. Remove it before enrolling again.")
        devices[device.name] = device
        self._save(devices)

    def remove(self, name):
        devices = self.devices()
        if name not in devices:
            raise ValueError("Device not found.")
        del devices[name]
        self._save(devices)

    def _save(self, devices):
        atomic_write(self.path, json.dumps({"version": 1, "devices": [asdict(d) for d in devices.values()]}, indent=2) + "\n")
