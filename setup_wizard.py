#!/usr/bin/env python3
"""Portable first-run launcher. Installs this project in its own virtual environment."""
from pathlib import Path
import subprocess
import sys
import venv


def main():
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 or newer is required.")
    root = Path(__file__).resolve().parent
    environment = root / ".venv"
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.exists():
        print("Creating a local Python environment…", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    ready = subprocess.run([str(python), "-c", "import ehsan_mcp, netmiko, keyring, mcp"], capture_output=True)
    if ready.returncode:
        print("Installing Ehsan Multi R-and-S MCP and dependencies…", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "-e", str(root)], check=True)
    subprocess.run([str(python), "-m", "ehsan_mcp", *sys.argv[1:]], check=True)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
    except subprocess.CalledProcessError:
        raise SystemExit("Setup did not complete. Review the error above and try again.")
