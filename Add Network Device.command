#!/bin/sh
set -eu

MCP_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON="$MCP_ROOT/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo "The MCP environment is not installed yet. Starting the installer…"
  exec /usr/bin/env python3 "$MCP_ROOT/setup_wizard.py" setup
fi

exec "$PYTHON" -m ehsan_mcp --data-dir "$MCP_ROOT/runtime" setup
