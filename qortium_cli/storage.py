from __future__ import annotations

import importlib.util
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict

from qortium_cli.constants import DEFAULT_BASE_URL, DEFAULT_TIMEOUT_SECONDS
from qortium_cli.models import AccountSettings, ChatSettings, EndpointSettings
from qortium_cli.validators import normalize_node_url


def endpoint_file_path(settings_dir: Path) -> Path:
    return settings_dir / "endpoint.py"


def config_file_path(settings_dir: Path) -> Path:
    return settings_dir / "config.py"


def chat_settings_file_path(settings_dir: Path) -> Path:
    return settings_dir / "chat_settings.json"


def _load_module_values(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    module_name = f"_qortium_runtime_{path.stem}_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return {}

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return {}
    return module.__dict__


def load_endpoint_settings(settings_dir: Path) -> EndpointSettings:
    values = _load_module_values(endpoint_file_path(settings_dir))
    raw_url = str(values.get("QORTAL_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).strip()
    raw_timeout = values.get("TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)

    try:
        base_url = normalize_node_url(raw_url)
    except Exception:
        base_url = DEFAULT_BASE_URL

    try:
        timeout_seconds = int(raw_timeout)
        if timeout_seconds <= 0:
            raise ValueError
    except Exception:
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    return EndpointSettings(base_url=base_url, timeout_seconds=timeout_seconds)


def load_account_settings(settings_dir: Path) -> AccountSettings:
    values = _load_module_values(config_file_path(settings_dir))
    return AccountSettings(
        name=str(values.get("NAME", "x") or "x").strip(),
        account_address=str(values.get("ACCOUNT_ADDRESS", "x") or "x").strip(),
        public_key=str(values.get("PUBLIC_KEY", "x") or "x").strip(),
        private_key=str(values.get("PRIVATE_KEY", "x") or "x").strip(),
        api_key=str(values.get("API_KEY", "x") or "x").strip(),
    )


def load_chat_settings(settings_dir: Path) -> ChatSettings:
    path = chat_settings_file_path(settings_dir)
    if not path.exists():
        return ChatSettings()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ChatSettings()

    if not isinstance(data, dict):
        return ChatSettings()

    try:
        tx_group_id = int(data.get("tx_group_id", 0))
        if tx_group_id < 0:
            tx_group_id = 0
    except Exception:
        tx_group_id = 0

    raw_fee = str(data.get("fee", "0") or "0").strip()
    try:
        parsed_fee = Decimal(raw_fee)
        if parsed_fee < 0:
            parsed_fee = Decimal("0")
        fee = parsed_fee.to_eng_string()
    except (InvalidOperation, ValueError):
        fee = "0"

    return ChatSettings(tx_group_id=tx_group_id, fee=fee)


def write_endpoint_file(settings_dir: Path, settings: EndpointSettings) -> None:
    url_literal = json.dumps(settings.base_url)
    timeout_value = int(max(1, settings.timeout_seconds))
    content = (
        "# Qortal node configuration\n"
        f"QORTAL_BASE_URL = {url_literal}\n\n"
        "# Request timeout in seconds\n"
        f"TIMEOUT_SECONDS = {timeout_value}\n"
    )
    settings_dir.mkdir(parents=True, exist_ok=True)
    endpoint_file_path(settings_dir).write_text(content, encoding="utf-8")


def write_config_file(settings_dir: Path, account: AccountSettings) -> None:
    content = (
        f"NAME = {json.dumps(account.name)}\n"
        f"ACCOUNT_ADDRESS = {json.dumps(account.account_address)}\n"
        f"PUBLIC_KEY = {json.dumps(account.public_key)}\n"
        f"PRIVATE_KEY = {json.dumps(account.private_key)}\n"
        f"API_KEY = {json.dumps(account.api_key)}\n"
    )
    settings_dir.mkdir(parents=True, exist_ok=True)
    config_file_path(settings_dir).write_text(content, encoding="utf-8")


def write_chat_settings(settings_dir: Path, settings: ChatSettings) -> None:
    payload = {
        "tx_group_id": int(max(0, settings.tx_group_id)),
        "fee": str(settings.fee),
    }
    settings_dir.mkdir(parents=True, exist_ok=True)
    chat_settings_file_path(settings_dir).write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
