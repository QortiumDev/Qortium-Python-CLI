"""Unified chat data model and Core-backed operations for the terminal UI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from qortium_cli.chat_format import build_chat_message_text, decode_chat_message
from qortium_cli.crypto import b58encode
from qortium_cli.models import AppContext
from qortium_cli.services import (
    get_active_chats,
    get_chat_messages,
    get_direct_private_active_chats,
    get_direct_private_chat_messages,
    get_member_groups,
    get_name_info,
    get_private_group_active_chats,
    get_private_group_chat_messages,
    get_unconfirmed_chat_messages,
    make_session,
    send_direct_private_chat,
    send_private_group_chat,
)
from qortium_cli.validators import is_placeholder

CHAT_HISTORY_LIMIT = 80
CHAT_STATE_FILENAME = "chat-workspace-state.json"


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _preview(message: Mapping[str, Any] | None) -> str:
    if not message:
        return ""
    decoded = decode_chat_message(message)
    text = " ".join(decoded.body.split())
    if decoded.kind == "encrypted":
        status = str(message.get("status") or message.get("decryptionStatus") or "")
        if status.upper() == "MISSING_KEY":
            return "Private key required"
    return text


@dataclass(frozen=True)
class ChatConversation:
    key: str
    kind: str
    title: str
    timestamp: int = 0
    preview: str = ""
    group_id: int | None = None
    address: str = ""
    member_count: int = 0
    status: str = ""

    @property
    def is_direct(self) -> bool:
        return self.kind == "direct"

    @property
    def is_private(self) -> bool:
        return self.kind in {"direct", "private_group"}

    @property
    def category(self) -> str:
        return "DIRECT" if self.is_direct else "GROUPS"


@dataclass(frozen=True)
class ConversationInbox:
    conversations: tuple[ChatConversation, ...]
    warnings: tuple[str, ...] = ()

    def by_key(self, key: str) -> ChatConversation | None:
        return next((item for item in self.conversations if item.key == key), None)


@dataclass
class ChatReadState:
    active_key: str = ""
    seen_timestamps: dict[str, int] | None = None
    help_seen: bool = False

    def __post_init__(self) -> None:
        if self.seen_timestamps is None:
            self.seen_timestamps = {}

    def unread(self, conversation: ChatConversation) -> bool:
        assert self.seen_timestamps is not None
        return conversation.timestamp > self.seen_timestamps.get(conversation.key, 0)

    def mark_seen(self, conversation: ChatConversation) -> None:
        assert self.seen_timestamps is not None
        self.active_key = conversation.key
        self.seen_timestamps[conversation.key] = max(
            conversation.timestamp,
            self.seen_timestamps.get(conversation.key, 0),
        )


def chat_state_path(settings_dir: Path) -> Path:
    return settings_dir / CHAT_STATE_FILENAME


def load_chat_read_state(settings_dir: Path) -> ChatReadState:
    try:
        data = json.loads(chat_state_path(settings_dir).read_text(encoding="utf-8"))
        seen = {
            str(key): max(0, _integer(value))
            for key, value in dict(data.get("seen_timestamps") or {}).items()
        }
        return ChatReadState(
            active_key=str(data.get("active_key") or ""),
            seen_timestamps=seen,
            help_seen=bool(data.get("help_seen", False)),
        )
    except Exception:
        return ChatReadState()


def save_chat_read_state(settings_dir: Path, state: ChatReadState) -> None:
    settings_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "active_key": state.active_key,
        "seen_timestamps": dict(state.seen_timestamps or {}),
        "help_seen": state.help_seen,
    }
    chat_state_path(settings_dir).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _private_access_available(ctx: AppContext) -> bool:
    private_key = str(ctx.account.private_key or "").strip()
    api_key = str(ctx.account.api_key or "").strip()
    return bool(
        private_key
        and api_key
        and not is_placeholder(private_key)
        and not is_placeholder(api_key)
    )


def _latest_by_group(rows: Iterable[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    latest: dict[int, Mapping[str, Any]] = {}
    for row in rows:
        group_id = _integer(row.get("groupId"), -1)
        if group_id < 0:
            continue
        if _integer(row.get("timestamp")) >= _integer(latest.get(group_id, {}).get("timestamp")):
            latest[group_id] = row
    return latest


class ChatGateway:
    """Translate user-facing conversation intents into Qortium Core calls."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def list_conversations(self) -> ConversationInbox:
        warnings: list[str] = []
        memberships: list[dict[str, Any]] = []
        ordinary_active: dict[str, list[dict[str, Any]]] = {"groups": [], "direct": []}
        direct_active: list[dict[str, Any]] = []
        private_group_active: list[dict[str, Any]] = []

        with make_session(self.ctx, include_api_key=True) as session:
            try:
                memberships = get_member_groups(
                    self.ctx,
                    self.ctx.account.account_address,
                    session,
                )
            except Exception as exc:
                warnings.append(f"Group list: {exc}")

            try:
                ordinary_active = get_active_chats(
                    self.ctx,
                    session,
                    self.ctx.account.account_address,
                )
            except Exception as exc:
                warnings.append(f"Conversation previews: {exc}")

            if _private_access_available(self.ctx):
                try:
                    direct_active = get_direct_private_active_chats(
                        self.ctx,
                        session,
                        self.ctx.account.private_key,
                    )
                except Exception as exc:
                    warnings.append(f"Direct chats: {exc}")
                try:
                    private_group_active = get_private_group_active_chats(
                        self.ctx,
                        session,
                        self.ctx.account.private_key,
                    )
                except Exception as exc:
                    warnings.append(f"Private groups: {exc}")

        direct: list[ChatConversation] = []
        for row in direct_active:
            address = str(row.get("address") or "").strip()
            if not address:
                continue
            title = str(row.get("name") or "").strip() or address
            direct.append(
                ChatConversation(
                    key=f"direct:{address}",
                    kind="direct",
                    title=title,
                    address=address,
                    timestamp=_integer(row.get("timestamp")),
                    preview=_preview(row),
                    status=str(row.get("decryptionStatus") or ""),
                )
            )

        open_latest = _latest_by_group(ordinary_active.get("groups", []))
        private_latest = {
            _integer(row.get("groupId"), -1): row
            for row in private_group_active
            if _integer(row.get("groupId"), -1) > 0
        }

        public_row = open_latest.get(0, {})
        groups: list[ChatConversation] = [
            ChatConversation(
                key="group:0",
                kind="public",
                title="General Chat",
                group_id=0,
                timestamp=_integer(public_row.get("timestamp")),
                preview=_preview(public_row),
            )
        ]

        seen_group_ids: set[int] = {0}
        for group in memberships:
            group_id = _integer(group.get("groupId"), -1)
            if group_id <= 0 or group_id in seen_group_ids:
                continue
            seen_group_ids.add(group_id)
            is_open = _boolean(group.get("isOpen"))
            latest = open_latest.get(group_id, {}) if is_open else private_latest.get(group_id, {})
            status = str(latest.get("status") or "")
            preview = _preview(latest)
            if not is_open and not _private_access_available(self.ctx):
                status = "LOCKED"
                preview = "Unlock the account to read private chat"
            groups.append(
                ChatConversation(
                    key=f"group:{group_id}",
                    kind="group" if is_open else "private_group",
                    title=str(group.get("groupName") or "").strip() or f"Group {group_id}",
                    group_id=group_id,
                    member_count=max(0, _integer(group.get("memberCount"))),
                    timestamp=_integer(latest.get("timestamp")),
                    preview=preview,
                    status=status,
                )
            )

        direct.sort(key=lambda item: (-item.timestamp, item.title.casefold()))
        groups.sort(key=lambda item: (-item.timestamp, item.title.casefold()))
        return ConversationInbox(tuple((*direct, *groups)), tuple(warnings))

    def load_messages(
        self,
        conversation: ChatConversation,
        *,
        limit: int = CHAT_HISTORY_LIMIT,
        before: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        with make_session(self.ctx, include_api_key=True) as session:
            if conversation.kind == "direct":
                rows = get_direct_private_chat_messages(
                    self.ctx,
                    session,
                    self.ctx.account.private_key,
                    conversation.address,
                    limit=limit,
                    before=before,
                )
            elif conversation.kind == "private_group":
                rows = get_private_group_chat_messages(
                    self.ctx,
                    session,
                    self.ctx.account.private_key,
                    int(conversation.group_id or 0),
                    limit=limit,
                    before=before,
                )
            else:
                group_id = int(conversation.group_id or 0)
                rows = get_chat_messages(
                    self.ctx,
                    session,
                    tx_group_id=group_id,
                    limit=limit,
                    reverse=True,
                    before=before,
                )
                if before is None:
                    unconfirmed = get_unconfirmed_chat_messages(
                        self.ctx,
                        session,
                        tx_group_id=group_id,
                        limit=limit,
                    )
                    signatures = {
                        str(row.get("signature") or "")
                        for row in rows
                        if row.get("signature")
                    }
                    rows.extend(
                        row
                        for row in unconfirmed
                        if not row.get("signature") or row.get("signature") not in signatures
                    )

        rows.sort(key=lambda row: _integer(row.get("timestamp")))
        return tuple(rows[-max(1, int(limit)):])

    def resolve_direct_recipient(self, name_or_address: str) -> ChatConversation:
        value = str(name_or_address or "").strip()
        if not value:
            raise ValueError("Enter a Qortium name or address.")
        if not _private_access_available(self.ctx):
            raise RuntimeError(
                "Direct chat requires an unlocked account private key and local API key."
            )

        if value.startswith("Q") and len(value) >= 20:
            address = value
            title = value
        else:
            with make_session(self.ctx, include_api_key=False) as session:
                name_info = get_name_info(self.ctx, value, session)
            address = str(name_info.get("owner") or "").strip()
            if not address:
                raise ValueError(f"No Qortium address was found for {value}.")
            title = str(name_info.get("name") or value).strip()

        return ChatConversation(
            key=f"direct:{address}",
            kind="direct",
            title=title,
            address=address,
        )

    def send_text(
        self,
        conversation: ChatConversation,
        text: str,
        *,
        replied_to: str = "",
        chat_reference: str = "",
    ) -> Any:
        message = build_chat_message_text(text, replied_to or None)
        if conversation.kind in {"direct", "private_group"}:
            encoded = b58encode(message.encode("utf-8"))
            with make_session(self.ctx, include_api_key=True) as session:
                if conversation.kind == "direct":
                    return send_direct_private_chat(
                        self.ctx,
                        session,
                        self.ctx.account.private_key,
                        conversation.address,
                        encoded,
                        chat_reference=chat_reference,
                    )
                return send_private_group_chat(
                    self.ctx,
                    session,
                    self.ctx.account.private_key,
                    int(conversation.group_id or 0),
                    encoded,
                    chat_reference=chat_reference,
                )

        from qortium_cli.tools import _send_chat_message

        self.ctx.chat.tx_group_id = int(conversation.group_id or 0)
        return _send_chat_message(
            self.ctx,
            message,
            chat_reference=chat_reference,
            quiet=True,
        )

    def send_payload(
        self,
        conversation: ChatConversation,
        payload: str,
        *,
        chat_reference: str,
    ) -> Any:
        """Send an already-encoded reaction/edit envelope."""

        if conversation.kind in {"direct", "private_group"}:
            encoded = b58encode(payload.encode("utf-8"))
            with make_session(self.ctx, include_api_key=True) as session:
                if conversation.kind == "direct":
                    return send_direct_private_chat(
                        self.ctx,
                        session,
                        self.ctx.account.private_key,
                        conversation.address,
                        encoded,
                        chat_reference=chat_reference,
                    )
                return send_private_group_chat(
                    self.ctx,
                    session,
                    self.ctx.account.private_key,
                    int(conversation.group_id or 0),
                    encoded,
                    chat_reference=chat_reference,
                )

        from qortium_cli.tools import _send_chat_message

        self.ctx.chat.tx_group_id = int(conversation.group_id or 0)
        return _send_chat_message(
            self.ctx,
            payload,
            chat_reference=chat_reference,
            quiet=True,
        )
