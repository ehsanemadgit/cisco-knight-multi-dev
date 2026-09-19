"""Structured MCP tools with explicit targets and device-bound change previews."""
import asyncio
from dataclasses import asdict
import hashlib
import json
import re
import secrets
import time

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from jsonschema import validate, ValidationError

from . import __version__
from .inventory import Inventory
from .credentials import Credentials
from .ssh import Sessions, probe, verify_known, check_cli

# Preserve the existing tool names, but replace the old hard-coded example
# configurations with explicit, complete command batches.
CONFIG_TOOLS = {
    "cisco_config_batch": "General configuration",
    "cisco_interface": "Interfaces",
    "cisco_vlan": "VLANs",
    "cisco_vtp": "VTP",
    "cisco_stp": "Spanning Tree",
    "cisco_portchannel": "EtherChannel",
    "cisco_route_static": "Static routing",
    "cisco_ospf": "OSPF",
    "cisco_eigrp": "EIGRP",
    "cisco_bgp": "BGP",
    "cisco_acl": "Access control lists",
    "cisco_nat": "NAT",
    "cisco_dhcp": "DHCP",
    "cisco_first_hop_redundancy": "HSRP / VRRP / GLBP",
    "cisco_qos": "QoS",
    "cisco_snmp": "SNMP",
    "cisco_ntp": "NTP",
    "cisco_security": "SSH / AAA / users",
    "cisco_monitor": "IP SLA / SPAN / logging",
}
NAME = {"type": "string", "minLength": 1, "description": "Exact enrolled device name; use list_devices."}
COMMANDS = {"type": "array", "minItems": 1, "maxItems": 100, "items": {"type": "string", "minLength": 1}, "description": "Complete config-mode command sequence, including interface/router context where needed. Omit configure terminal/end."}
CONFIRM = {"confirmed": {"type": "boolean", "default": False}, "confirmation_token": {"type": "string"}, "dry_run": {"type": "boolean", "default": False}}


def tool(name, description, properties, required):
    return types.Tool(name=name, description=description, inputSchema={"type": "object", "properties": properties, "required": required, "additionalProperties": False})


def tools():
    result = [
        tool("list_devices", "List enrolled devices and cached SSH session status, without fetching passwords or opening connections.", {}, []),
        tool("add_device", "Get the local setup wizard command. Enter passwords locally, never in chat or tool arguments.", {}, []),
        tool("test_device", "Check SSH compatibility, pinned host identity, login and configured enable access.", {"device": NAME}, ["device"]),
        tool("cisco_show", "Run one read-only show command on a named device.", {"device": NAME, "command": {"type": "string"}, "dry_run": {"type": "boolean"}}, ["device", "command"]),
        tool("show_many", "Run the same read-only show command across selected devices; failures are reported per device.", {"devices": {"type": "array", "minItems": 1, "maxItems": 100, "uniqueItems": True, "items": NAME}, "command": {"type": "string"}}, ["devices", "command"]),
        tool("neighbors", "Read CDP and LLDP neighbor tables from selected devices.", {"devices": {"type": "array", "minItems": 1, "maxItems": 100, "uniqueItems": True, "items": NAME}}, ["devices"]),
        tool("cisco_ping", "Ping a destination from a named device.", {"device": NAME, "destination": {"type": "string"}}, ["device", "destination"]),
        tool("cisco_traceroute", "Trace a route from a named device.", {"device": NAME, "destination": {"type": "string"}}, ["device", "destination"]),
        tool("cisco_health", "Read CPU, memory and interface status from a named device.", {"device": NAME}, ["device"]),
        tool("cisco_stats", "Read server statistics and cached connection status.", {}, []),
        tool("cisco_backup", "Read running configuration, or explicitly save running to startup configuration. Returned configuration can contain device secrets.", {"device": NAME, "action": {"type": "string", "enum": ["read_running", "save_startup"]}, **CONFIRM}, ["device", "action"]),
        tool("cisco_rollback", "Preview and run IOS/IOS-XE configure replace using an existing local .cfg snapshot. Other platforms are not supported for this tool.", {"device": NAME, "snapshot": {"type": "string"}, **CONFIRM}, ["device", "snapshot"]),
    ]
    for name, topic in CONFIG_TOOLS.items():
        result.append(tool(name, topic + ": preview explicit configuration commands, then apply using the returned device-bound token. Include required CLI context. No implicit defaults or example addresses.", {"device": NAME, "commands": COMMANDS, "save": {"type": "boolean", "default": False}, **CONFIRM}, ["device", "commands"]))
    return result


def single_line(command):
    if not command.strip() or any(ord(c) < 32 or ord(c) == 127 for c in command):
        raise ValueError("Commands must be one non-empty line without control characters.")
    return command.strip()


def show_command(command):
    command = single_line(command)
    if not re.match(r"(?i)^show\s+", command):
        raise ValueError("cisco_show accepts full 'show ...' commands only.")
    if any(c in command for c in (";", ">", "<")) or re.search(r"(?i)\|\s*(?:redirect|append|tee)\b", command):
        raise ValueError("Show output redirection and command chaining are not allowed.")
    return command


def config_commands(commands):
    commands = [single_line(c) for c in commands]
    # These operations need dedicated workflows; abbreviations are also rejected.
    forbidden = ("reload", "erase", "delete", "format", "boot", "confreg", "copy", "write", "configure", "do", "end", "exit")
    for command in commands:
        first = command.split()[0].lower()
        if any(word.startswith(first) for word in forbidden) and first != "exit":
            raise ValueError(f"Use a dedicated workflow for '{first}'; it is not allowed inside a configuration batch.")
        if any(c in command for c in (";", "|", ">", "<")):
            raise ValueError("Command chaining and shell operators are not allowed.")
    return commands


class Engine:
    def __init__(self, inventory, credentials):
        self.inventory = inventory
        self.credentials = credentials
        self.sessions = Sessions(inventory, credentials)
        self.pending = {}
        self.schemas = {t.name: t.inputSchema for t in tools()}

    def read(self, name, command):
        with self.sessions.lock(name):
            try:
                return {"success": True, "device": name, "command": command, "output": check_cli(self.sessions.get(name).send_command(command))}
            except Exception as exc:
                self.sessions.drop(name)
                raise RuntimeError(f"Read failed ({type(exc).__name__}); run the connection test.") from None

    def changes(self, name, operation, payload, args):
        device = self.inventory.get(name)
        binding = {"device": asdict(device), "operation": operation, "payload": payload}
        digest = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
        preview = {"device": name, "host": device.host, "operation": operation, **payload}
        if args.get("dry_run"):
            return {"success": True, "simulation": True, "preview": preview}
        now = time.monotonic()
        self.pending = {k: v for k, v in self.pending.items() if v[1] > now}
        if not args.get("confirmed"):
            if len(self.pending) >= 500:
                raise ValueError("Too many pending changes. Wait for existing confirmation tokens to expire.")
            token = secrets.token_urlsafe(24)
            self.pending[token] = (digest, now + 300)
            return {"success": False, "confirmation_required": True, "confirmation_token": token, "expires_in_seconds": 300, "preview": preview}
        token = args.get("confirmation_token")
        pending = self.pending.get(token)
        if not pending or pending[0] != digest:
            raise ValueError("Confirmation token is expired or does not match this device and exact operation.")
        del self.pending[token]
        with self.sessions.lock(name):
            started = False
            try:
                conn = self.sessions.get(name)
                if not conn.check_enable_mode():
                    raise ValueError("Privileged access is required. Re-enroll with an enable password if necessary.")
                started = True
                if operation == "config":
                    output = check_cli(conn.send_config_set(payload["commands"], error_pattern=r"(?im)^\s*%\s*(?:Invalid|Error|Incomplete|Ambiguous|Authorization)"))
                    if payload["save"]:
                        output += "\n" + check_cli(conn.save_config())
                elif operation == "save_startup":
                    output = check_cli(conn.save_config())
                else:
                    output = check_cli(conn.send_command("configure replace " + payload["snapshot"] + " force", read_timeout=60))
                return {"success": True, "device": name, "output": output}
            except Exception as exc:
                self.sessions.drop(name)
                if started:
                    return {"success": False, "device": name, "error": f"Change did not complete cleanly ({type(exc).__name__}). Inspect the device before retrying; some commands may already have applied.", "may_have_applied": True}
                raise

    def call(self, name, args):
        try:
            if name not in self.schemas:
                raise ValueError("Unknown tool.")
            validate(args, self.schemas[name])
            return self._call(name, args)
        except ValidationError:
            return {"success": False, "error": "Arguments do not match the tool schema. Check required fields and types."}
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            return {"success": False, "error": f"Operation failed ({type(exc).__name__}). Check connectivity, credentials, platform, host key and SSH profile using setup. Raw SSH errors are suppressed to avoid exposing secrets."}

    def _call(self, name, args):
        if name == "list_devices":
            return {"devices": [{"name": d.name, "host": d.host, "port": d.port, "platform": d.platform, "ssh_profile": d.ssh_profile, "session_cached": d.name in self.sessions.connections} for d in self.inventory.devices().values()]}
        if name == "add_device":
            import sys
            return {"message": "Run the setup wizard in a local terminal. Choose 1 to add a device. Passwords are entered there with hidden input.", "executable": sys.executable, "arguments": ["-m", "cisco_knight_mcp", "--data-dir", str(self.inventory.root.resolve()), "setup"]}
        if name == "cisco_stats":
            return {"server": "Cisco Knight Multi-Device MCP", "version": __version__, "tools_count": len(self.schemas), "devices_count": len(self.inventory.devices()), "cached_sessions": list(self.sessions.connections)}
        if name in {"show_many", "neighbors"}:
            # Sequential calls avoid flooding a small lab or overwhelming its AAA server.
            commands = [show_command(args["command"])] if name == "show_many" else ["show cdp neighbors", "show lldp neighbors"]
            results = {d: [self.call("cisco_show", {"device": d, "command": c}) for c in commands] for d in args["devices"]}
            return {"success": all(r.get("success", False) for rs in results.values() for r in rs), "results": results}
        device = args["device"]
        enrolled = self.inventory.get(device)
        if name == "test_device":
            key, report = probe(enrolled)
            if not verify_known(enrolled, key, self.inventory.known_hosts):
                raise ValueError("Untrusted SSH host key. Run setup first.")
            result = self.read(device, "show version")
            result.pop("output", None)
            result["ssh"] = report
            return result
        if name == "cisco_show":
            command = show_command(args["command"])
            if args.get("dry_run"):
                return {"success": True, "simulation": True, "device": device, "command": command}
            return self.read(device, command)
        if name in {"cisco_ping", "cisco_traceroute"}:
            target = args["destination"]
            if not re.fullmatch(r"[A-Za-z0-9_.:-]+", target):
                raise ValueError("Destination must be a single IP address or hostname.")
            return self.read(device, ("ping " if name == "cisco_ping" else "traceroute ") + target)
        if name == "cisco_health":
            commands = {"cisco_ios": ["show processes cpu", "show processes memory", "show ip interface brief"], "cisco_nxos": ["show system resources", "show interface brief"], "cisco_xr": ["show processes cpu", "show memory summary", "show ipv4 interface brief"]}[enrolled.platform]
            results = [self.call("cisco_show", {"device": device, "command": c}) for c in commands]
            return {"success": all(r.get("success") for r in results), "device": device, "results": results}
        if name in CONFIG_TOOLS:
            if enrolled.platform == "cisco_xr":
                raise ValueError("IOS-XR configuration commits are not supported in this release; read-only tools are available.")
            return self.changes(device, "config", {"commands": config_commands(args["commands"]), "save": args.get("save", False)}, args)
        if name == "cisco_backup":
            if args["action"] == "read_running":
                return self.read(device, "show running-config")
            if enrolled.platform == "cisco_xr":
                raise ValueError("IOS-XR save/commit workflows are not supported in this release.")
            return self.changes(device, "save_startup", {}, args)
        if name == "cisco_rollback":
            if enrolled.platform != "cisco_ios":
                raise ValueError("Rollback is currently supported only on IOS/IOS-XE.")
            snapshot = args["snapshot"]
            if not re.fullmatch(r"(?:flash|bootflash):[A-Za-z0-9_/-]+\.cfg", snapshot):
                raise ValueError("Snapshot must be a local flash: or bootflash: .cfg path.")
            return self.changes(device, "rollback", {"snapshot": snapshot}, args)
        raise ValueError("Unknown tool.")


async def serve(root, prompt_secrets=False, unlock_vault=False):
    inventory = Inventory(root)
    credentials = Credentials(root, interactive=prompt_secrets or unlock_vault)
    # Interactive secrets are collected before the MCP transport starts.
    for d in inventory.devices().values():
        if (d.credential_store == "session" and prompt_secrets) or (d.credential_store == "encrypted" and unlock_vault):
            credentials.get(d)
    credentials.interactive = False
    engine = Engine(inventory, credentials)
    server = Server("cisco-knight-multi-dev", version=__version__)

    @server.list_tools()
    async def list_tools():
        return tools()

    request_lock = asyncio.Lock()

    @server.call_tool()
    async def call_tool(name, arguments):
        # Serialize changes so a single-use token cannot be raced by concurrent calls.
        async with request_lock:
            result = await asyncio.to_thread(engine.call, name, arguments or {})
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result, indent=2))], isError=result.get("success") is False and not result.get("confirmation_required", False))

    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        engine.sessions.close()
