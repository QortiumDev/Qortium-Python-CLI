from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlparse


API_KEY_FILE = "apikey.txt"
MAINNET_API_PORT = 14891
TESTNET_API_PORT = 24891


@dataclass(frozen=True)
class LocalCoreApiKey:
    api_key: str
    api_key_path: Path
    api_key_directory: Path
    cwd: Path
    jar_path: Path
    pid: int
    settings_path: Path


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False

    normalized = host.strip().lower()
    if normalized == "localhost":
        return True

    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _endpoint_port(base_url: str) -> int | None:
    parsed = urlparse(base_url)
    if not _is_loopback_host(parsed.hostname):
        return None

    if parsed.port is not None:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    if parsed.scheme == "http":
        return 80
    return None


def _resolve_process_path(raw_path: str, cwd: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve()
    return (cwd / path).resolve()


def _read_json_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _effective_settings_path(settings_path: Path, cwd: Path) -> Path:
    settings = _read_json_file(settings_path)
    user_path = settings.get("userPath")
    if not isinstance(user_path, str) or not user_path.strip():
        return settings_path

    user_dir = Path(user_path.strip())
    if not user_dir.is_absolute():
        user_dir = cwd / user_dir
    redirected = (user_dir / settings_path.name).resolve()
    return redirected if redirected.exists() else settings_path


def _settings_api_port(settings: dict) -> int | None:
    raw_api_port = settings.get("apiPort")
    try:
        if raw_api_port is not None:
            return int(raw_api_port)
    except (TypeError, ValueError):
        pass

    if "isTestNet" in settings:
        return TESTNET_API_PORT if bool(settings.get("isTestNet", False)) else MAINNET_API_PORT
    return None


def _settings_api_key_directory(settings_path: Path, cwd: Path) -> Path:
    settings = _read_json_file(settings_path)
    raw_api_key_path = settings.get("apiKeyPath")
    if isinstance(raw_api_key_path, str) and raw_api_key_path.strip():
        return _resolve_process_path(raw_api_key_path.strip(), cwd)
    return cwd.resolve()


def _read_api_key(api_key_directory: Path) -> tuple[str, Path] | None:
    api_key_path = api_key_directory / API_KEY_FILE
    try:
        api_key = api_key_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not api_key:
        return None

    return api_key, api_key_path.resolve()


def _core_process_paths(args: list[str], cwd: Path) -> tuple[Path, Path] | None:
    try:
        jar_index = args.index("-jar")
    except ValueError:
        return None

    if len(args) <= jar_index + 2:
        return None

    jar_path = _resolve_process_path(args[jar_index + 1], cwd)
    jar_name = jar_path.name.lower()
    if not (
        jar_name.endswith(".jar")
        and (jar_name.startswith("qortium") or jar_name.startswith("qortal"))
    ):
        return None

    settings_path = _resolve_process_path(args[jar_index + 2], cwd)
    return jar_path, settings_path


def _iter_proc_dirs(proc_root: Path) -> list[Path]:
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return []
    return [entry for entry in entries if entry.is_dir() and entry.name.isdigit()]


def _read_process_args(proc_dir: Path) -> list[str]:
    raw = proc_dir.joinpath("cmdline").read_bytes()
    return [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]


def _read_process_cwd(proc_dir: Path) -> Path:
    return Path(os.readlink(proc_dir / "cwd")).resolve()


def _dedupe_candidates(candidates: list[LocalCoreApiKey]) -> list[LocalCoreApiKey]:
    deduped: dict[Path, LocalCoreApiKey] = {}
    for candidate in candidates:
        deduped[candidate.api_key_path] = candidate
    return list(deduped.values())


def detect_local_core_api_key(
    base_url: str,
    proc_root: Path = Path("/proc"),
) -> LocalCoreApiKey | None:
    target_port = _endpoint_port(base_url)
    if target_port is None:
        return None

    matched_candidates: list[LocalCoreApiKey] = []
    fallback_candidates: list[LocalCoreApiKey] = []

    for proc_dir in _iter_proc_dirs(proc_root):
        try:
            pid = int(proc_dir.name)
            args = _read_process_args(proc_dir)
            cwd = _read_process_cwd(proc_dir)
            process_paths = _core_process_paths(args, cwd)
            if process_paths is None:
                continue

            jar_path, raw_settings_path = process_paths
            settings_path = _effective_settings_path(raw_settings_path, cwd)
            settings = _read_json_file(settings_path)
            api_key_directory = _settings_api_key_directory(settings_path, cwd)
            api_key = _read_api_key(api_key_directory)
            if api_key is None:
                continue

            candidate = LocalCoreApiKey(
                api_key=api_key[0],
                api_key_path=api_key[1],
                api_key_directory=api_key_directory.resolve(),
                cwd=cwd,
                jar_path=jar_path,
                pid=pid,
                settings_path=settings_path,
            )

            api_port = _settings_api_port(settings)
            if api_port == target_port:
                matched_candidates.append(candidate)
            elif api_port is None:
                fallback_candidates.append(candidate)
        except Exception:
            continue

    matched_candidates = _dedupe_candidates(matched_candidates)
    if len(matched_candidates) == 1:
        return matched_candidates[0]
    if matched_candidates:
        return None

    fallback_candidates = _dedupe_candidates(fallback_candidates)
    return fallback_candidates[0] if len(fallback_candidates) == 1 else None
