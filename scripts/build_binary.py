"""Build the current platform's standalone Qortium CLI executable."""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path


def artifact_name() -> str:
    system = platform.system().lower()
    names = {
        "windows": "qortium-cli-windows",
        "darwin": "qortium-cli-macos",
        "linux": "qortium-cli-linux",
    }
    try:
        return names[system]
    except KeyError as exc:
        raise SystemExit(f"Unsupported build platform: {platform.system()}") from exc


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        artifact_name(),
        str(root / "main.py"),
    ]
    subprocess.run(command, cwd=root, check=True)
    suffix = ".exe" if platform.system() == "Windows" else ""
    print(f"Built {root / 'dist' / (artifact_name() + suffix)}")


if __name__ == "__main__":
    main()
