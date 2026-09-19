from dataclasses import replace
import json
import os
import sys
from unittest.mock import MagicMock, patch

import paramiko
import pytest

from cisco_knight_mcp.inventory import Device, Inventory
from cisco_knight_mcp.credentials import Credentials, native_keyring
from cisco_knight_mcp.server import Engine, tools
from cisco_knight_mcp.ssh import pin_key, verify_known, disabled
from cisco_knight_mcp.wizard import add_device


def device(name="sw1", **kwargs):
    return Device(name=name, host="192.0.2.1", username="admin", credential_store="session", credential_id=name, **kwargs)


@pytest.fixture
def engine(tmp_path):
    inventory = Inventory(tmp_path)
    inventory.add(device())
    inventory.add(device("r1"))
    result = Engine(inventory, Credentials(tmp_path))
    result.sessions = MagicMock()
    result.sessions.connections = {}
    result.sessions.get.return_value.check_enable_mode.return_value = True
    result.sessions.get.return_value.send_command.return_value = "OK"
    result.sessions.get.return_value.send_config_set.return_value = "OK"
    result.sessions.get.return_value.save_config.return_value = "SAVED"
    return result


def test_inventory_roundtrip_and_no_passwords(tmp_path):
    inv = Inventory(tmp_path)
    d = device()
    inv.add(d)
    assert inv.get(d.name) == d
    assert "password" not in inv.path.read_text()
    with pytest.raises(ValueError):
        inv.add(d)
    inv.remove(d.name)
    assert not inv.devices()


@pytest.mark.parametrize("kwargs", [{"port": 0}, {"port": True}, {"host": "bad host"}, {"name": "../x"}, {"platform": "linux"}, {"ssh_profile": "auto"}])
def test_invalid_device(kwargs):
    values = {"name": "sw1", "host": "192.0.2.1", "username": "admin", **kwargs}
    with pytest.raises(ValueError):
        Device(**values)


def test_encrypted_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("CISCO_KNIGHT_MCP_MASTER_PASSWORD", "long-test-master-password")
    store = Credentials(tmp_path)
    d = replace(device(), credential_store="encrypted", enable_required=True)
    store.put(d, "secret-ssh-password", "secret-enable-password")
    assert "secret-ssh-password" not in (tmp_path / "credentials.enc.json").read_text()
    assert Credentials(tmp_path).get(d)["enable"] == "secret-enable-password"
    monkeypatch.setenv("CISCO_KNIGHT_MCP_MASTER_PASSWORD", "wrong-master-password")
    with pytest.raises(ValueError, match="Wrong master"):
        Credentials(tmp_path).get(d)
    store.delete(d)
    with pytest.raises(ValueError, match="Credentials unavailable"):
        store.get(d)


def test_reject_plaintext_keyring():
    with patch("cisco_knight_mcp.credentials.keyring.get_keyring", return_value=MagicMock()):
        with pytest.raises(ValueError, match="No supported"):
            native_keyring()


def test_session_credentials_are_not_persisted(tmp_path):
    store = Credentials(tmp_path)
    store.put(device(), "hidden")
    assert store.get(device())["password"] == "hidden"
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError):
        Credentials(tmp_path).get(device())


def test_host_key_pinning(tmp_path):
    known = tmp_path / "known_hosts"
    d = device(port=2222)
    first = paramiko.RSAKey.generate(2048)
    assert not verify_known(d, first, known)
    pin_key(d, first, known)
    assert verify_known(d, first, known)
    assert "[192.0.2.1]:2222" in known.read_text()
    with pytest.raises(ValueError, match="changed"):
        verify_known(d, paramiko.RSAKey.generate(2048), known)


def test_legacy_is_per_device():
    assert disabled("modern")["keys"] == ["ssh-rsa", "ssh-dss"]
    assert disabled("legacy") == {}
    assert disabled("modern")["keys"] == ["ssh-rsa", "ssh-dss"]


def test_explicit_device_required(engine):
    assert not engine.call("cisco_show", {"command": "show version"})["success"]
    assert not engine.call("cisco_show", {"device": "missing", "command": "show version"})["success"]
    engine.sessions.get.assert_not_called()


@pytest.mark.parametrize("command", ["configure terminal", "sh version", "show version\nreload", "show version | redirect flash:x", "show version; reload", "show version > flash:x"])
def test_show_rejects_writes(engine, command):
    assert not engine.call("cisco_show", {"device": "sw1", "command": command})["success"]
    engine.sessions.get.assert_not_called()


def test_selects_correct_device(engine):
    result = engine.call("cisco_show", {"device": "r1", "command": "show ip route"})
    assert result["success"]
    engine.sessions.get.assert_called_once_with("r1")


def test_preview_and_confirmation_bound_to_device_and_commands(engine):
    args = {"device": "sw1", "commands": ["interface Gi0/2", "description test"], "save": True}
    preview = engine.call("cisco_config_batch", args)
    assert preview["confirmation_required"]
    engine.sessions.get.assert_not_called()
    confirmed = {**args, "confirmed": True, "confirmation_token": preview["confirmation_token"]}
    assert not engine.call("cisco_config_batch", {**confirmed, "device": "r1"})["success"]
    assert not engine.call("cisco_config_batch", {**confirmed, "commands": ["hostname altered"]})["success"]
    assert engine.call("cisco_config_batch", confirmed)["success"]
    engine.sessions.get.return_value.send_config_set.assert_called_once()
    engine.sessions.get.return_value.save_config.assert_called_once()
    assert not engine.call("cisco_config_batch", confirmed)["success"]


def test_token_expires(engine):
    args = {"device": "sw1", "commands": ["hostname test"]}
    with patch("cisco_knight_mcp.server.time.monotonic", return_value=0):
        token = engine.call("cisco_config_batch", args)["confirmation_token"]
    with patch("cisco_knight_mcp.server.time.monotonic", return_value=301):
        assert not engine.call("cisco_config_batch", {**args, "confirmed": True, "confirmation_token": token})["success"]
    engine.sessions.get.assert_not_called()


def test_dry_run_never_connects(engine):
    result = engine.call("cisco_vlan", {"device": "sw1", "commands": ["vlan 999"], "dry_run": True})
    assert result["simulation"]
    engine.sessions.get.assert_not_called()


def test_write_failure_not_retried(engine):
    args = {"device": "sw1", "commands": ["hostname lab"]}
    token = engine.call("cisco_config_batch", args)["confirmation_token"]
    conn = engine.sessions.get.return_value
    conn.send_config_set.side_effect = RuntimeError("private-device-output")
    result = engine.call("cisco_config_batch", {**args, "confirmed": True, "confirmation_token": token})
    assert result["may_have_applied"]
    assert "private-device-output" not in json.dumps(result)
    conn.send_config_set.assert_called_once()


def test_many_isolates_failures(engine):
    result = engine.call("show_many", {"devices": ["sw1", "missing", "r1"], "command": "show version"})
    assert not result["success"]
    assert result["results"]["sw1"][0]["success"]
    assert result["results"]["r1"][0]["success"]
    assert not result["results"]["missing"][0]["success"]


def test_schemas_preserve_names_and_add_five():
    catalog = tools()
    assert len(catalog) == 31
    assert len({t.name for t in catalog}) == 31
    assert all("password" not in json.dumps(t.inputSchema) for t in catalog)


def test_enrollment_success(tmp_path):
    inv = Inventory(tmp_path)
    store = Credentials(tmp_path)
    conn = MagicMock()
    conn.send_command.return_value = "Cisco IOS Software, version test"
    key = paramiko.RSAKey.generate(2048)
    answers = iter(["sw1", "192.0.2.1", "22", "admin", "1", "3"])
    with patch("cisco_knight_mcp.wizard.ask", side_effect=lambda *a: next(answers)), patch("cisco_knight_mcp.wizard.yes", side_effect=[True, True, True]), patch("cisco_knight_mcp.wizard.private_password", side_effect=["ssh-secret", "enable-secret"]), patch("cisco_knight_mcp.wizard.probe", return_value=(key, {"profile": "modern"})), patch("cisco_knight_mcp.wizard.connect", return_value=conn), patch("cisco_knight_mcp.wizard.native_keyring", side_effect=ValueError()):
        add_device(inv, store)
    assert inv.get("sw1").enable_required
    assert store.get(inv.get("sw1"))["enable"] == "enable-secret"
    assert "ssh-secret" not in inv.path.read_text()
    conn.disconnect.assert_called_once()


def test_enrollment_failed_login_does_not_save(tmp_path):
    inv = Inventory(tmp_path)
    answers = iter(["sw1", "192.0.2.1", "22", "admin", "1"])
    key = paramiko.RSAKey.generate(2048)
    with patch("cisco_knight_mcp.wizard.ask", side_effect=lambda *a: next(answers)), patch("cisco_knight_mcp.wizard.yes", side_effect=[False, True]), patch("cisco_knight_mcp.wizard.private_password", return_value="hidden"), patch("cisco_knight_mcp.wizard.probe", return_value=(key, {})), patch("cisco_knight_mcp.wizard.connect", side_effect=RuntimeError("login failed")):
        with pytest.raises(RuntimeError):
            add_device(inv, Credentials(tmp_path))
    assert not inv.devices()
    assert not inv.known_hosts.exists()


def test_legacy_retry_requires_opt_in(tmp_path):
    inv = Inventory(tmp_path)
    answers = iter(["sw1", "192.0.2.1", "22", "admin", "1"])
    with patch("cisco_knight_mcp.wizard.ask", side_effect=lambda *a: next(answers)), patch("cisco_knight_mcp.wizard.yes", side_effect=[False, False]), patch("cisco_knight_mcp.wizard.private_password", return_value="hidden"), patch("cisco_knight_mcp.wizard.probe", side_effect=paramiko.ssh_exception.IncompatiblePeer("no acceptable kex")) as probe_mock:
        add_device(inv, Credentials(tmp_path))
    assert probe_mock.call_count == 1
    assert not inv.devices()


def test_enable_failure_closes_session(tmp_path):
    from cisco_knight_mcp.ssh import connect
    known = tmp_path / "known_hosts"
    known.write_text("")
    d = device(enable_required=True)
    conn = MagicMock()
    conn.check_enable_mode.return_value = False
    with patch("cisco_knight_mcp.ssh.ConnectHandler", return_value=conn) as factory:
        with pytest.raises(RuntimeError, match="enable validation failed"):
            connect(d, {"password": "ssh-secret", "enable": "enable-secret"}, known)
    conn.enable.assert_called_once()
    conn.disconnect.assert_called_once()
    assert factory.call_args.kwargs["secret"] == "enable-secret"
    assert factory.call_args.kwargs["ssh_strict"] is True
    assert factory.call_args.kwargs["alt_key_file"] == str(known)


def test_read_exception_does_not_expose_remote_output(engine):
    engine.sessions.get.return_value.send_command.side_effect = ValueError("password=private-output")
    result = engine.call("cisco_show", {"device": "sw1", "command": "show version"})
    assert not result["success"]
    assert "private-output" not in json.dumps(result)


def test_inventory_change_invalidates_confirmation(engine):
    args = {"device": "sw1", "commands": ["hostname test"]}
    token = engine.call("cisco_config_batch", args)["confirmation_token"]
    old = engine.inventory.get("sw1")
    engine.inventory.remove("sw1")
    engine.inventory.add(replace(old, host="192.0.2.2"))
    assert not engine.call("cisco_config_batch", {**args, "confirmed": True, "confirmation_token": token})["success"]
    engine.sessions.get.assert_not_called()


def test_wizard_declined_host_key_does_not_save(tmp_path):
    inv = Inventory(tmp_path)
    answers = iter(["sw1", "192.0.2.1", "22", "admin", "1"])
    with patch("cisco_knight_mcp.wizard.ask", side_effect=lambda *a: next(answers)), patch("cisco_knight_mcp.wizard.yes", side_effect=[False, False]), patch("cisco_knight_mcp.wizard.private_password", return_value="hidden"), patch("cisco_knight_mcp.wizard.probe", return_value=(paramiko.RSAKey.generate(2048), {})), patch("cisco_knight_mcp.wizard.connect") as connect_mock:
        add_device(inv, Credentials(tmp_path))
    connect_mock.assert_not_called()
    assert not inv.devices()
