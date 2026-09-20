import argparse
import asyncio
import logging
from .inventory import data_dir


def main():
    parser = argparse.ArgumentParser(description="Ehsan Multi R-and-S MCP")
    parser.add_argument("--data-dir", help="Inventory, encrypted vault and known_hosts directory")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("setup", help="Interactive device enrollment menu (default)")
    commands.add_parser("client-config", help="Print MCP client configuration")
    server = commands.add_parser("serve", help="Start the stdio MCP server")
    server.add_argument("--prompt-secrets", action="store_true", help="Prompt locally for session-only passwords before starting MCP")
    server.add_argument("--unlock-vault", action="store_true", help="Prompt locally to unlock the encrypted vault before starting MCP")
    args = parser.parse_args()
    root = data_dir(args.data_dir)
    # Third-party SSH log messages can contain raw exceptions. Keep them out of MCP logs.
    logging.getLogger("paramiko").setLevel(logging.CRITICAL)
    logging.getLogger("netmiko").setLevel(logging.CRITICAL)
    if args.command == "serve":
        from .server import serve
        asyncio.run(serve(root, args.prompt_secrets, args.unlock_vault))
    elif args.command == "client-config":
        from .wizard import client_config
        client_config(root)
    else:
        from .wizard import run
        run(root)
