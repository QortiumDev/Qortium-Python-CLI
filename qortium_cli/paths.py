from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "QortiumCLI"


def project_root_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _configured_home() -> Path | None:
    raw = str(
        os.environ.get("QORTIUM_CLI_HOME", "")
        or os.environ.get("QOTIUM_CLI_HOME", "")
        or ""
    ).strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _ensure_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def _default_settings_dir() -> Path:
    if os.name == "nt":
        appdata = str(os.environ.get("APPDATA", "") or "").strip()
        if appdata:
            return Path(appdata).resolve() / APP_DIR_NAME
    return (Path.home() / ".qortium-cli").resolve()


def resolve_settings_dir(project_root: Path) -> Path:
    project_root = project_root.resolve()

    configured = _configured_home()
    if configured is not None and _ensure_dir(configured):
        return configured

    legacy_files = ("endpoint.py", "config.py", "chat_settings.json")
    if any((project_root / name).exists() for name in legacy_files):
        return project_root

    settings_dir = _default_settings_dir()
    if _ensure_dir(settings_dir):
        return settings_dir

    # Final fallback for restricted sandboxes or locked home folders.
    portable_dir = project_root / ".qortium-cli-data"
    if _ensure_dir(portable_dir):
        return portable_dir

    return project_root
