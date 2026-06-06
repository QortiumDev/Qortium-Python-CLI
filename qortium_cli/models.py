from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class EndpointSettings:
    base_url: str
    timeout_seconds: int


@dataclass
class AccountSettings:
    name: str = "x"
    account_address: str = "x"
    public_key: str = "x"
    private_key: str = "x"
    api_key: str = "x"


@dataclass
class ChatSettings:
    tx_group_id: int = 0
    fee: str = "0"


@dataclass
class AppContext:
    settings_dir: Path
    endpoint: EndpointSettings
    account: AccountSettings
    chat: ChatSettings
    debug: bool = True


@dataclass
class ToolPlugin:
    key: str
    label: str
    description: str
    handler: Callable[[AppContext], None]
