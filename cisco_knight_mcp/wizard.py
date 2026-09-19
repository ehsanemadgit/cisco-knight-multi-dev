from dataclasses import asdict, replace
import getpass
import json
from pathlib import Path
import sys
import tempfile
import uuid

import paramiko

from .credentials import Credentials, native_keyring
from .inventory import Device, Inventory, PLATFORMS
from .ssh import probe, verify_known, pin_key, connect, check_cli


def ask(label, default=""):
    value = input(f"{label}" + (f" [{default}]" if default else "") + ": ").strip()
    return value or default


def yes(label, default=False):
    while True:
        value = ask(label + " (yes/no)", "yes" if default else "no").lower()
        if value in {"yes", "y"}:
            return True
        if value in {"no", "n"}:
            return False
        print("Please answer yes or no.")


def private_password(label):
    # Do not let getpass fall back to visibly echoing secrets in redirected terminals.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        value = getpass.getpass(label + ": ")
    if not value:
        raise ValueError("Password cannot be empty.")
    return value


def choose_platform():
    print("1. Cisco IOS / IOS-XE\n2. Cisco NX-OS\n3. Cisco IOS-XR")
    selection = ask("Device operating system", "1")
    if selection not in {"1", "2", "3"}:
        raise ValueError("Choose platform 1, 2 or 3.")
    return list(PLATFORMS)[int(selection) - 1]


def add_device(inventory, credentials):
    name = ask("Device name (e.g. SW-4500X)")
    if name in inventory.devices():
        raise ValueError("That device name already exists.")
    host = ask("Management IP or hostname")
    port = int(ask("SSH port", "22"))
    username = ask("SSH username")
    password = private_password("SSH password")
    enable_required = yes("Does this device require an enable password?")
    enable = private_password("Enable password") if enable_required else ""
    device = Device(name=name, host=host, username=username, port=port, platform=choose_platform(), enable_required=enable_required, credential_id=str(uuid.uuid4()))
    print("Checking SSH key exchange, host key, encryption and MAC compatibility…")
    try:
        key, report = probe(device)
    except paramiko.ssh_exception.IncompatiblePeer as exc:
        print(f"Modern SSH policy could not negotiate with this device: {exc}")
        print("Legacy compatibility permits older SHA-1/CBC algorithms for this device only.")
        if not yes("Retry this device using the legacy compatibility profile?"):
            return
        device = replace(device, ssh_profile="legacy")
        key, report = probe(device)
    print(json.dumps(report, indent=2))
    trusted = verify_known(device, key, inventory.known_hosts)
    if not trusted and not yes("Verify this fingerprint against your device. Trust this SSH host key?"):
        print("Enrollment cancelled.")
        return
    # Use a temporary pin until both authentication and device validation pass.
    with tempfile.TemporaryDirectory() as directory:
        known = Path(directory) / "known_hosts"
        pin_key(device, key, known)
        conn = connect(device, {"password": password, "enable": enable}, known)
        try:
            version = check_cli(conn.send_command("show version"))
            expected = {"cisco_ios": ("Cisco IOS", "IOS XE", "IOS-XE"), "cisco_nxos": ("NX-OS", "NXOS"), "cisco_xr": ("IOS XR", "IOS-XR")}[device.platform]
            if not any(marker.lower() in version.lower() for marker in expected):
                raise ValueError("show version does not match the selected Cisco platform. Check the device type.")
            print(f"SSH login successful. Device prompt: {conn.find_prompt()}")
            print("Enable access verified." if device.enable_required else "Enable password not requested.")
            print("Platform verified: " + PLATFORMS[device.platform])
        finally:
            conn.disconnect()
    try:
        backend = native_keyring()
        print(f"OS credential store available: {type(backend).__name__}")
        default = "1"
    except Exception:
        print("An OS credential store is not available in this session.")
        default = "2"
    print("1. OS credential store\n2. Encrypted vault (master password)\n3. Ask at each server startup (session only)")
    mode = ask("Credential storage", default)
    if mode not in {"1", "2", "3"}:
        raise ValueError("Choose storage 1, 2 or 3.")
    device = replace(device, credential_store={"1": "keyring", "2": "encrypted", "3": "session"}[mode])
    if not yes(f"Save {device.name} ({device.host}:{device.port})?", True):
        return
    credentials.put(device, password, enable)
    try:
        pin_key(device, key, inventory.known_hosts)
        inventory.add(device)
    except Exception:
        credentials.delete(device)
        raise
    print(f"Added {device.name}. Passwords are not stored in devices.json.")
    if mode == "3":
        print("Start the MCP server in a terminal with: cisco-knight-multi-dev serve --prompt-secrets")
    if mode == "2":
        print("Start in a terminal with: cisco-knight-multi-dev serve --unlock-vault")
        print("Desktop MCP launchers need CISCO_KNIGHT_MCP_MASTER_PASSWORD injected by a secret manager; prefer OS storage for unattended use.")


def list_devices(inventory):
    devices = inventory.devices()
    if not devices:
        print("No devices enrolled. Choose Add device to begin.")
    for d in devices.values():
        print(f"{d.name:24} {d.host}:{d.port}  {PLATFORMS[d.platform]}  SSH={d.ssh_profile}  credentials={d.credential_store}")


def test_device(inventory, credentials):
    list_devices(inventory)
    d = inventory.get(ask("Device name"))
    key, report = probe(d)
    if not verify_known(d, key, inventory.known_hosts):
        raise ValueError("Host key is not enrolled. Add this device through setup.")
    conn = connect(d, credentials.get(d), inventory.known_hosts)
    try:
        check_cli(conn.send_command("show version"))
        print(f"Connection successful: {conn.find_prompt()}")
        print(json.dumps(report, indent=2))
    finally:
        conn.disconnect()


def client_config(root):
    args = ["-m", "cisco_knight_mcp", "--data-dir", str(root.resolve()), "serve"]
    print(json.dumps({"mcpServers": {"cisco-knight-multi-dev": {"command": sys.executable, "args": args}}}, indent=2))
    print("\nCodex TOML configuration:")
    print('[mcp_servers.cisco-knight-multi-dev]')
    print("command = " + json.dumps(sys.executable))
    print("args = " + json.dumps(args))
    print("\nUse the same data directory when launching setup and serve.")


def run(root):
    inventory = Inventory(root)
    credentials = Credentials(root, interactive=True)
    print("\nCisco Knight Multi-Device MCP — Device Setup")
    print(f"Inventory: {inventory.path}")
    while True:
        print("\n1. Add device\n2. List devices\n3. Test device connection\n4. Remove device\n5. Show MCP client configuration\n0. Exit")
        try:
            choice = ask("Choose an option", "0")
            if choice == "0":
                return
            if choice == "1":
                add_device(inventory, credentials)
            elif choice == "2":
                list_devices(inventory)
            elif choice == "3":
                test_device(inventory, credentials)
            elif choice == "4":
                list_devices(inventory)
                device = inventory.get(ask("Device name to remove"))
                if yes(f"Remove {device.name} and its saved credentials?"):
                    credentials.delete(device)
                    inventory.remove(device.name)
                    print("Device removed. Its known host key is retained for future verification.")
            elif choice == "5":
                client_config(root)
            else:
                print("Choose an option from 0 through 5.")
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled.")
            return
        except Exception as exc:
            # Never print raw SSH exceptions: they may contain echoed credentials.
            if isinstance(exc, ValueError):
                print(f"Setup error: {exc}")
            else:
                print(f"Setup failed ({type(exc).__name__}). Check connectivity, credentials and SSH support; no device was added unless shown above.")
