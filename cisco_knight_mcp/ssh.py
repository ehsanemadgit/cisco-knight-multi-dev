"""Per-device SSH policy, pinned host keys, and network CLI sessions."""
import base64
import hashlib
import re
import socket
import threading

import paramiko
from netmiko import ConnectHandler

from .inventory import atomic_write

MODERN_DISABLED = {
    "kex": ["diffie-hellman-group1-sha1", "diffie-hellman-group14-sha1", "diffie-hellman-group-exchange-sha1"],
    "keys": ["ssh-rsa", "ssh-dss"],
    "ciphers": ["aes128-cbc", "aes192-cbc", "aes256-cbc", "3des-cbc", "blowfish-cbc"],
    "macs": ["hmac-md5", "hmac-md5-96", "hmac-sha1", "hmac-sha1-96"],
}
CLI_ERROR = re.compile(r"(?im)^\s*(?:%\s*(?:Invalid|Error|Incomplete|Ambiguous|Unrecognized|Authorization|Access denied)|(?:ERROR|Invalid command):)")


def disabled(profile):
    # Legacy enables only algorithms still implemented by the installed SSH library.
    # It never changes a process-global Paramiko setting.
    return MODERN_DISABLED if profile == "modern" else {}


def host_id(device):
    return device.host if device.port == 22 else f"[{device.host}]:{device.port}"


def fingerprint(key):
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def verify_known(device, key, path):
    keys = paramiko.HostKeys()
    if path.exists():
        keys.load(str(path))
    entry = keys.lookup(host_id(device))
    if entry and not any(existing.asbytes() == key.asbytes() for existing in entry.values()):
        raise ValueError("SSH host key changed. Verify the device identity before updating known_hosts.")
    return bool(entry)


def pin_key(device, key, path):
    verify_known(device, key, path)
    keys = paramiko.HostKeys()
    if path.exists():
        keys.load(str(path))
    keys.add(host_id(device), key.get_name(), key)
    lines = []
    for host in keys:
        for algorithm, item in keys[host].items():
            lines.append(f"{host} {algorithm} {item.get_base64()}\n")
    atomic_write(path, "".join(lines))


def probe(device):
    """Negotiate SSH without sending any credentials."""
    sock = socket.create_connection((device.host, device.port), timeout=12)
    transport = None
    try:
        transport = paramiko.Transport(sock, disabled_algorithms=disabled(device.ssh_profile))
        transport.start_client(timeout=12)
        if not transport.is_active():
            raise ValueError("SSH negotiation did not complete.")
        key = transport.get_remote_server_key()
        return key, {"host_key": transport.host_key_type, "fingerprint": fingerprint(key), "cipher_to_device": transport.local_cipher, "cipher_from_device": transport.remote_cipher, "mac_to_device": transport.local_mac, "mac_from_device": transport.remote_mac, "profile": device.ssh_profile, "key_exchange": "negotiated successfully"}
    finally:
        if transport:
            transport.close()
        sock.close()


def connect(device, secrets, known_hosts):
    if not known_hosts.exists():
        raise ValueError("Device host key has not been trusted. Run setup first.")
    try:
        return _connect(device, secrets, known_hosts)
    except Exception as exc:
        raise RuntimeError(f"SSH login or enable validation failed ({type(exc).__name__}).") from None


def _connect(device, secrets, known_hosts):
    conn = ConnectHandler(
        device_type=device.platform, host=device.host, port=device.port,
        username=device.username, password=secrets["password"], secret=secrets.get("enable", ""),
        ssh_strict=True, system_host_keys=False, alt_host_keys=True, alt_key_file=str(known_hosts),
        disabled_algorithms=disabled(device.ssh_profile), use_keys=False, allow_agent=False,
        conn_timeout=12, auth_timeout=15, banner_timeout=15, read_timeout_override=30,
    )
    try:
        if device.enable_required:
            conn.enable()
            if not conn.check_enable_mode():
                raise ValueError("Enable-mode verification failed.")
        return conn
    except Exception:
        conn.disconnect()
        raise


def check_cli(output):
    if CLI_ERROR.search(output):
        raise ValueError("The device rejected the command. Check syntax, platform and account privileges.")
    return output


class Sessions:
    def __init__(self, inventory, credentials):
        self.inventory = inventory
        self.credentials = credentials
        self.connections = {}
        self.locks = {}
        self.guard = threading.Lock()

    def lock(self, name):
        with self.guard:
            return self.locks.setdefault(name, threading.RLock())

    def get(self, name):
        device = self.inventory.get(name)
        old = self.connections.get(name)
        if old and old[0] == device and old[1].is_alive():
            return old[1]
        if old:
            old[1].disconnect()
        conn = connect(device, self.credentials.get(device), self.inventory.known_hosts)
        self.connections[name] = (device, conn)
        return conn

    def drop(self, name):
        old = self.connections.pop(name, None)
        if old:
            try:
                old[1].disconnect()
            except Exception:
                pass

    def close(self):
        for name in list(self.connections):
            self.drop(name)
