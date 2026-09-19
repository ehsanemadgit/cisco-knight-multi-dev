# cisco-knight-multi-dev

Manage multiple Cisco switches and routers through one MCP server. Enroll devices in a local terminal wizard, then select each device by name from your MCP client.

This is a new, separate implementation informed by the existing Cisco MCP installation. Your original server is not overwritten or automatically replaced. Version 0.1.0 retains its 26 tool names and adds five inventory and multi-device tools. Configuration tool arguments have changed: use explicit command batches instead of the original placeholder defaults.

## About the author

**[Ehsan Emad](https://www.linkedin.com/in/ehsanemad)**

Principal Architect | Strategic Advisory | Enterprise Network | Cybersecurity | Data Center | Agentic AI Enthusiast |  CCDE #20210029 | 4xCCIE #28551 | CISSP | 2x NSE 7 | OpenShift | Cisco Champion | Fire Jumper Elite185

Creator of **cisco-knight-multi-dev**, **Networking With Ehsan**, and the **TechLoungeCast** podcast. This project brings practical routing and switching lab work into a reusable, multi-device MCP workflow.

- **Networking With Ehsan:** [networkingwithehsan.com](https://www.networkingwithehsan.com/)
- **TechLoungeCast:** [techloungecast.com](https://techloungecast.com/)
- **Podcast:** [Listen on Apple Podcasts](https://podcasts.apple.com/ca/podcast/techloungecast/id1847186556)
- **LinkedIn:** [Ehsan Emad](https://www.linkedin.com/in/ehsanemad)

## Why we added the setup wizard

The original Cisco MCP connected to one device through a fixed set of environment variables. Expanding it to a lab with multiple switches and routers meant users needed a simple, repeatable way to register each device, manage its credentials and verify that it could connect.

The setup wizard guides users through enrollment in a local terminal. Instead of editing configuration files or placing passwords in chat, users answer prompts for the device name, management address, SSH username and password, and an optional enable password. The wizard tests the connection before adding the device to the inventory.

### Benefits

- **Easier onboarding:** Guided prompts replace manual inventory editing, making the first device and every additional device easier to set up.
- **One inventory for the lab:** Give each switch or router a meaningful name, then target it explicitly from MCP tools without changing the server's connection settings.
- **Hidden password entry and storage choices:** Enter passwords locally with hidden input and choose an OS credential store, an encrypted vault or session-only storage. SSH and enable passwords stay out of the inventory file.
- **Connection problems caught early:** Check SSH negotiation, login, the selected Cisco platform and enable access when requested before saving a device.
- **Compatibility with older lab equipment:** When modern SSH negotiation fails, the wizard offers a legacy compatibility retry for that device without changing other devices' SSH profiles.
- **Device identity verification:** Review and trust a new SSH host-key fingerprint during enrollment. Later connections reject a changed key instead of silently accepting it.
- **Consistent setup across operating systems:** The Python wizard and launchers are designed for Windows, Linux and macOS, with credential-storage options suited to each environment. Windows has been validated end-to-end with Codex, including device enrollment, connection testing, MCP discovery and a live `show version` call. Linux native validation is still pending.
- **Simpler maintenance and client setup:** List devices, test connections, remove devices and print the MCP client configuration from the same menu.

The wizard prepares and validates device access; it does not configure routing or switching features during enrollment. Once devices are enrolled, the MCP tools use their names for individual commands and multi-device read-only checks.

## Install for the first time

The installer is the folder you downloaded or extracted. You do not need to open Python files or edit JSON files by hand. You need Python 3.10 or newer and a terminal only for the first setup.

### macOS

1. Extract the ZIP file.
2. Open the extracted `cisco-knight-multi-dev` folder in Finder.
3. Double-click **`Add Network Device.command`**. If macOS asks for confirmation, choose **Open**. If you see a security warning, Control-click the file, choose **Open**, then choose **Open** again.
4. Wait while the launcher creates its private Python environment and installs dependencies.
5. When the menu appears, choose **1. Add device**.

If Python is not installed, install Python 3.10 or newer from [python.org](https://www.python.org/downloads/macos/) and double-click the launcher again.

### Windows

1. Extract the ZIP file; do not run the wizard from inside the ZIP preview.
2. Open the extracted `cisco-knight-multi-dev` folder.
3. Double-click **`setup.cmd`**.
4. If Windows says Python is missing, install Python 3.10 or newer from [python.org](https://www.python.org/downloads/windows/), select **Add Python to PATH** during installation, and double-click **`setup.cmd`** again.
5. When the menu appears, choose **1. Add device**.

The first run creates a private `.venv` folder and installs the required packages. By default, the wizard stores the device inventory in the operating system's per-user application-data directory. On Windows this is normally `%LOCALAPPDATA%\cisco-knight-multi-dev`. The setup window is a terminal window; keep it open while answering prompts.

### Windows + Codex: first-time checklist

Follow these steps if you are installing this MCP on a Windows computer for the first time:

1. Download the ZIP package to the Windows computer.
2. Right-click the ZIP, choose **Extract All**, and open the extracted `cisco-knight-multi-dev` folder. Do not run files from inside the ZIP preview.
3. Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/windows/). During installation, select **Add Python to PATH**.
4. Double-click **`setup.cmd`**. A Windows terminal window opens and installs the MCP's private Python environment and dependencies.
5. In the menu, choose **1. Add device**. Enter a friendly name such as `SW-MGMT-1`, the management IP or hostname, SSH port (normally `22`), SSH username, SSH password, and optional enable password.
6. Review the SSH fingerprint and compatibility report. Continue only when the fingerprint belongs to the device you intended to add.
7. Choose **OS credential store** when the wizard asks where to save credentials. On Windows this uses the Windows Credential Manager through Python Keyring.
8. Choose **3. Test device connection** and confirm that `show version` succeeds.
9. Repeat **1. Add device** for every switch or router, then test each device.
10. Choose **5. Show MCP client configuration**. Copy the generated Windows JSON or Codex TOML entry; it contains the correct Windows Python path and inventory directory for that installation.
11. In Codex, open the user MCP configuration. On Windows this is normally `%USERPROFILE%\.codex\config.toml`. Add the generated `[mcp_servers.cisco-knight-multi-dev]` entry and keep the path and arguments exactly as the wizard printed them.
12. In Codex, use **Ask for approval** as the recommended permission mode. Save `config.toml`, fully restart Codex, then ask: **“List my enrolled devices using cisco-knight-multi-dev.”**
13. Verify real device access with a read-only command such as: **“Using cisco-knight-multi-dev, run show version on <device-name>.”** Approve the action if Codex asks.

Do not replace Windows paths with macOS paths, do not type passwords into the Codex configuration, and do not edit `devices.json` or the credential files manually.

If Codex fails to start the MCP server with `WinError 5: Access is denied`, first confirm that the generated interpreter path and data directory are correct. If the same configuration works outside Codex but the restricted Codex sandbox still blocks MCP process creation, temporarily try **Full Access** as a troubleshooting fallback. Full Access is not required in the validated Windows setup: **Ask for approval** successfully listed enrolled devices and executed a live `show version` through Cisco Knight MCP.

## Start the wizard

After the first installation, use the same launcher whenever you want to add or test equipment.

**macOS / Linux:**

```sh
python3 setup_wizard.py
```

**Windows:**

```powershell
py -3 setup_wizard.py
```

Or launch `setup.command` on macOS / `setup.cmd` on Windows. The launcher creates `.venv`, installs the project and dependencies on first use, and opens this menu:

```text
Cisco Knight Multi-Device MCP — Device Setup

1. Add device
2. List devices
3. Test device connection
4. Remove device
5. Show MCP client configuration
0. Exit
```

Adding a device asks for its name, management IP/hostname, SSH port, username, hidden SSH password, whether it needs an enable password, and (if yes) its hidden enable password. Select IOS/IOS-XE, NX-OS or IOS-XR.

### Wizard help

You do not need to open or edit `devices.json`, `known_hosts`, or the credential vault to add equipment. Open a terminal and run the wizard launcher:

```sh
/Users/ehsan/Documents/MCP/cisco-knight-multi-dev/.venv/bin/python \
  -m cisco_knight_mcp \
  setup
```

The easiest option on macOS is to double-click **`Add Network Device.command`**. It opens the setup menu and uses the correct inventory automatically. On Windows, double-click **`setup.cmd`**. If you are working from the source folder, run `python3 setup_wizard.py`. These launchers open the same menu and write the enrolled device to the correct inventory automatically.

Use the wizard whenever you need to add another switch or router:

1. Start `setup_wizard.py` (or open `setup.command` on macOS / `setup.cmd` on Windows).
2. Choose **1. Add device**.
3. Enter a unique device name, management IP or hostname, SSH port, SSH username and hidden SSH password.
4. Answer whether the device needs an enable password; if yes, enter that password when prompted.
5. Select the platform and review the SSH compatibility report and host-key fingerprint.
6. Trust the fingerprint only after comparing it with the device you intended to enroll.
7. Choose credential storage, then confirm **Save**.
8. Choose **3. Test device connection** and enter the saved device name.

To add more devices, return to the menu and repeat **1. Add device**. Choose **2. List devices** to see exact names for MCP commands. Choose **4. Remove device** to remove a device and its saved credentials. Choose **5. Show MCP client configuration** to print the launcher configuration for the client you are setting up. The wizard does not change device configuration; it only validates SSH access, optional enable access and the selected platform before saving the device.

The wizard negotiates SSH before transmitting credentials, displays its host-key fingerprint and negotiated encryption/MAC algorithms, and asks you to trust a new host key. It tests login, enable access when requested, and the platform using `show version`. Failed validation does not add a device. It then asks where to store credentials and saves the device after confirmation.

If the modern SSH policy cannot negotiate, the wizard offers an explicit legacy retry for that device. Older SHA-1/CBC algorithms may then be used, but only those supported by the installed Paramiko version. Removed algorithms such as DSA on Paramiko 4 cannot be re-enabled by this setting. Changed host keys are rejected; there is no automatic key replacement.

## Password storage

- **OS credential store:** macOS Keychain, Windows Credential Manager, or a Linux Secret Service/KWallet backend. Recommended for desktop MCP clients. The implementation rejects unknown/plaintext keyring backends.
- **Encrypted vault:** Scrypt derives a key from your master password; Fernet encrypts and authenticates the credential data. The master password is not saved. A terminal-launched server can use `serve --unlock-vault`. Desktop launchers need `CISCO_KNIGHT_MCP_MASTER_PASSWORD` injected through their secret-management mechanism; do not put it in the inventory or commit it.
- **Session only:** saved only in memory. Start with `serve --prompt-secrets` in a terminal to enter passwords before MCP starts. A desktop client cannot answer those terminal prompts, so use OS storage for normal desktop launches.

`devices.json` contains hostnames, usernames and credential references, but no SSH/enable passwords. Credential and known-host files are created atomically; POSIX file permissions are restricted. Windows uses the current user's filesystem ACLs. This is a local, single-user inventory; run one enrollment wizard at a time.

Data defaults to the platform's per-user configuration directory. Use a separate location consistently if desired:

```sh
python3 setup_wizard.py --data-dir ./runtime setup
```

## Connect your MCP client

Choose **5. Show MCP client configuration** after enrolling devices. It prints both a JSON MCP client entry and a Codex TOML entry, using the exact interpreter and data directory from that installation. Merge the generated entry into your client's configuration and reload its MCP servers.

The server name is `cisco-knight-multi-dev`. No changes to your current Codex configuration are made by setup.

Installed CLI commands:

```text
cisco-knight-multi-dev setup
cisco-knight-multi-dev client-config
cisco-knight-multi-dev serve
cisco-knight-multi-dev serve --unlock-vault
cisco-knight-multi-dev serve --prompt-secrets
```

For launchers, run the full virtual-environment Python path with `-m cisco_knight_mcp --data-dir <absolute-directory> serve`. Keep wizard prompts off the MCP stdio connection.

## Examples

```json
{"name": "list_devices", "arguments": {}}
{"name": "cisco_show", "arguments": {"device": "SW-4500X", "command": "show interfaces status"}}
{"name": "neighbors", "arguments": {"devices": ["SW-4500X", "IPN_ISN-1"]}}
{"name": "show_many", "arguments": {"devices": ["SW-4500X", "IPN_ISN-1"], "command": "show version"}}
```

The `add_device` MCP tool returns the local wizard command. It deliberately does not collect passwords in chat or attempt interactive prompts over MCP.

Configuration example:

```json
{
  "name": "cisco_interface",
  "arguments": {
    "device": "SW-4500X",
    "commands": ["interface GigabitEthernet0/2", "description Lab uplink"],
    "save": false
  }
}
```

The first call returns a preview and a token without opening an SSH connection. Review it, then repeat the identical request with `confirmed: true` and `confirmation_token`. Tokens expire after five minutes, are single-use and bind to the exact device record, operation, commands and save flag. `dry_run: true` previews without creating a token or connecting.

Configuration uses one CLI session and proper config mode. A failed write is never automatically retried: partial changes may have applied and must be inspected. Writes do not fan out across multiple devices. No configuration tool supplies example IPs, public SNMP communities or other silent defaults.

## Tools (31)

New tools: `list_devices`, `add_device`, `test_device`, `show_many`, `neighbors`.

Read/diagnostic tools: `cisco_show`, `cisco_ping`, `cisco_traceroute`, `cisco_health`, `cisco_stats`.

Configuration tools: `cisco_config_batch`, `cisco_interface`, `cisco_vlan`, `cisco_vtp`, `cisco_stp`, `cisco_portchannel`, `cisco_route_static`, `cisco_ospf`, `cisco_eigrp`, `cisco_bgp`, `cisco_acl`, `cisco_nat`, `cisco_dhcp`, `cisco_first_hop_redundancy`, `cisco_qos`, `cisco_snmp`, `cisco_ntp`, `cisco_security`, `cisco_monitor`.

`cisco_backup` reads the running config or saves running to startup; it does not automatically create a local backup file. Running configuration can contain sensitive device data. `cisco_rollback` supports an existing local IOS/IOS-XE `.cfg` snapshot with `configure replace`.

## Current scope and validation

- IOS/IOS-XE and NX-OS have read and configuration paths. IOS-XR is read-only in this release; its commit workflow needs separate support.
- Device enrollment uses password-based SSH, with optional enable credentials. SSH key authentication is not yet exposed in the wizard.
- Multi-device reads are sequential and return per-device successes/failures.
- 34 automated tests pass locally, including a real MCP stdio client/server exchange. The setup menu also passed a terminal smoke test.
- Windows has been validated end-to-end with Python 3.13, the setup wizard, per-user application data, Codex MCP configuration, **Ask for approval** permission mode, enrolled-device discovery and a live `show version` call against a Cisco IOS switch.
- Live read-only validation against the existing lab switch required the legacy SSH profile and negotiated an RSA host key, AES128-CBC and HMAC-SHA1; version and CDP reads succeeded. Native macOS/Linux execution and NX-OS/IOS-XR hardware validation are still pending for this renamed release.
- A GitHub Actions matrix is included for Windows, Linux and macOS; it has not run remotely yet. It tests mocked networking/storage and the actual MCP stdio exchange, not platform credential-store integration.

Run tests after installing the project:

```sh
python -m pip install -e . pytest
python -m pytest -q
```

Implementation references: [Netmiko API](https://ktbyers.github.io/netmiko/docs/netmiko/) and [Python keyring documentation](https://keyring.readthedocs.io/en/stable/).
