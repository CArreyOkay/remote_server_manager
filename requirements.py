"""Module dependencies for the Windows Remote Automation & Orchestration Platform.

Summary:
  - Server: Requires FastAPI, Uvicorn, and Pydantic.
  - Client: Zero external pip dependencies (runs purely on Python Standard Library:
            tkinter, ctypes, urllib, threading, sqlite3, json, base64).
  - Target Remote Venvs: ipykernel and wheel/setuptools (installed on demand by the script).
"""

import subprocess
import sys

SERVER_DEPENDENCIES: list[str] = [
    "fastapi>=0.100.0",
    "uvicorn[standard]>=0.23.0",
    "pydantic>=2.0.0",
]

CLIENT_DEPENDENCIES: list[str] = [
    # Zero third-party pip dependencies required.
    # The client runs entirely on native standard library modules:
    #   - tkinter / ttk (Desktop UI)
    #   - ctypes / wintypes (Windows SSPI Negotiate Auth, Advapi32, Kernel32)
    #   - urllib.request / urllib.parse (Streaming HTTP client)
    #   - sqlite3, threading, json, base64, fnmatch, argparse
]

TARGET_VENV_DEPENDENCIES: list[str] = [
    # Packages installed dynamically on the remote server into managed venvs:
    "ipykernel>=6.25.0",
    "wheel",
    "setuptools",
]


def generate_requirements_files() -> None:
    """Writes requirements-server.txt and requirements-client.txt to disk."""
    with open("requirements-server.txt", "w", encoding="utf-8") as s_file:
        s_file.write("\n".join(SERVER_DEPENDENCIES) + "\n")

    with open("requirements-client.txt", "w", encoding="utf-8") as c_file:
        c_file.write(
            "# Client runs 100% on standard library modules (tkinter, ctypes, urllib).\n"
            "# No pip packages required.\n"
        )

    print("[OK] requirements-server.txt and requirements-client.txt created.")


def install_server_dependencies() -> None:
    """Installs server dependencies into the active Python environment."""
    print("[INFO] Installing server dependencies via pip...")
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade"] + SERVER_DEPENDENCIES
    subprocess.check_call(cmd)
    print("[SUCCESS] All server dependencies successfully installed.")


if __name__ == "__main__":
    generate_requirements_files()
    # Uncomment the following line to install server dependencies immediately:
    install_server_dependencies()