from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Mapping

from qortium_cli.crypto import b58decode, is_base58

MAX_REACTION_CONTENT_LENGTH = 32


@dataclass(frozen=True)
class ChatReaction:
    content: str
    content_state: bool


@dataclass(frozen=True)
class DecodedChatMessage:
    body: str
    kind: str
    reaction: ChatReaction | None = None
    replied_to: str | None = None


@dataclass(frozen=True)
class MessageThread:
    latest: Mapping[str, Any]
    original: Mapping[str, Any]
    revisions: tuple[Mapping[str, Any], ...]


def _extract_doc_text(node: Any) -> str:
    if isinstance(node, dict):
        node_type = str(node.get("type", ""))
        if node_type == "text":
            return str(node.get("text", ""))

        parts = [_extract_doc_text(child) for child in node.get("content", [])]
        if node_type == "paragraph":
            return "".join(parts) + "\n"
        return "".join(parts)

    if isinstance(node, list):
        return "".join(_extract_doc_text(child) for child in node)

    return ""


def _truthy_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return default


def _has_readable_encrypted_payload(message: Mapping[str, Any]) -> bool:
    return (
        str(message.get("decryptionStatus", "") or "").upper() == "DECRYPTED"
        or str(message.get("status", "") or "").upper() == "DECRYPTED"
    )


def _decode_text_payload(data: Any, encoding: Any) -> str | None:
    if not isinstance(data, str) or not data:
        return ""

    enc = str(encoding or "").upper()
    decoded_bytes: bytes | None = None

    if enc == "BASE64":
        try:
            decoded_bytes = base64.b64decode(data)
        except Exception:
            return data
    elif enc == "BASE58" or is_base58(data):
        try:
            decoded_bytes = b58decode(data)
        except Exception:
            return data

    if decoded_bytes is None:
        return data

    return decoded_bytes.decode("utf-8", errors="replace")


def _normalize_reaction_content(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    content = value.strip()
    if 0 < len(content) <= MAX_REACTION_CONTENT_LENGTH:
        return content
    return None


def _get_envelope_reaction(envelope: Mapping[str, Any]) -> ChatReaction | None:
    if envelope.get("type") != "reaction":
        return None

    content = _normalize_reaction_content(envelope.get("content"))
    if not content:
        return None

    return ChatReaction(
        content=content,
        content_state=envelope.get("contentState") is not False,
    )


def _unwrap_chat_text_envelope(value: str) -> DecodedChatMessage:
    body = value
    reaction: ChatReaction | None = None
    replied_to: str | None = None

    for _ in range(3):
        try:
            parsed = json.loads(body)
        except Exception:
            break

        if not isinstance(parsed, dict):
            break

        message_doc = parsed.get("messageText")
        if isinstance(message_doc, dict):
            doc_text = _extract_doc_text(message_doc).strip()
            if doc_text:
                return DecodedChatMessage(body=doc_text, kind="text")

        envelope = parsed
        if not isinstance(envelope.get("message"), str):
            break

        reaction = _get_envelope_reaction(envelope)
        body = str(envelope["message"])
        if reaction:
            return DecodedChatMessage(body=body, kind="reaction", reaction=reaction)

        if replied_to is None:
            envelope_reply = envelope.get("repliedTo")
            if isinstance(envelope_reply, str) and envelope_reply:
                replied_to = envelope_reply

    return DecodedChatMessage(body=body, kind="text", replied_to=replied_to)


def decode_chat_message(message: Mapping[str, Any]) -> DecodedChatMessage:
    is_encrypted = _truthy_bool(message.get("isEncrypted"), default=False)
    is_text = _truthy_bool(message.get("isText"), default=True)

    if is_encrypted and (not _has_readable_encrypted_payload(message) or not message.get("data")):
        return DecodedChatMessage(body="Encrypted message", kind="encrypted")

    if not is_text:
        return DecodedChatMessage(body="Binary message", kind="binary")

    data = message.get("data")
    if not data:
        return DecodedChatMessage(body="", kind="empty")

    encoding = str(message.get("encoding") or "").upper()
    if encoding and encoding not in {"BASE58", "BASE64"}:
        return DecodedChatMessage(body="Unsupported message encoding", kind="unsupported")

    text = _decode_text_payload(data, encoding)
    if text is None:
        return DecodedChatMessage(body="Unable to decode message", kind="unsupported")

    try:
        return _unwrap_chat_text_envelope(text)
    except Exception:
        return DecodedChatMessage(body="Unable to decode message", kind="unsupported")


def is_reaction_chat_message(message: Mapping[str, Any]) -> bool:
    return decode_chat_message(message).kind == "reaction"


def _message_signature(message: Mapping[str, Any]) -> str:
    return str(message.get("signature") or "").strip()


def _message_chat_reference(message: Mapping[str, Any]) -> str:
    return str(message.get("chatReference") or "").strip()


def _message_sender(message: Mapping[str, Any]) -> str:
    return str(message.get("sender") or "").strip()


def sort_messages_by_timestamp(messages: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(messages, key=lambda item: int(item.get("timestamp") or 0))


def build_message_threads(messages: list[Mapping[str, Any]]) -> list[MessageThread]:
    originals_by_signature: dict[str, Mapping[str, Any]] = {}
    revisions_by_reference: dict[str, list[Mapping[str, Any]]] = {}

    for message in messages:
        if is_reaction_chat_message(message):
            continue

        signature = _message_signature(message)
        if signature and not _message_chat_reference(message):
            originals_by_signature[signature] = message

    for message in messages:
        if is_reaction_chat_message(message):
            continue

        reference = _message_chat_reference(message)
        if not reference:
            continue

        revisions_by_reference.setdefault(reference, []).append(message)

    threads: list[MessageThread] = []
    for message in messages:
        if is_reaction_chat_message(message):
            continue

        reference = _message_chat_reference(message)
        referenced_original = originals_by_signature.get(reference) if reference else None
        if referenced_original and _message_sender(referenced_original) == _message_sender(message):
            continue

        signature = _message_signature(message)
        revisions = sort_messages_by_timestamp(
            [
                revision
                for revision in revisions_by_reference.get(signature, [])
                if _message_sender(revision) == _message_sender(message)
            ]
        )
        threads.append(
            MessageThread(
                latest=revisions[-1] if revisions else message,
                original=message,
                revisions=tuple(revisions),
            )
        )

    return threads
