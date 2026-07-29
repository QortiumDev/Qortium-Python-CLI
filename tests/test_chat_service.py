from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock

from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.services import (
    build_chat,
    get_direct_private_active_chats,
    get_private_group_chat_messages,
    send_direct_private_chat,
)


def make_context() -> AppContext:
    return AppContext(
        settings_dir=Path("."),
        endpoint=EndpointSettings(base_url="http://127.0.0.1:24891", timeout_seconds=15),
        account=AccountSettings(),
        chat=ChatSettings(),
        debug=False,
    )


class ChatServiceTests(TestCase):
    def test_build_chat_sends_selected_group_as_request_param(self) -> None:
        ctx = make_context()
        session = MagicMock()
        response = MagicMock()
        response.text = "unsigned"
        session.post.return_value = response

        result = build_chat(ctx, {"txGroupId": 2, "data": "encoded"}, session, tx_group_id=2)

        self.assertEqual(result, "unsigned")
        session.post.assert_called_once_with(
            "http://127.0.0.1:24891/chat",
            params={"txGroupId": 2},
            json={"txGroupId": 2, "data": "encoded"},
            timeout=15,
        )
        response.raise_for_status.assert_called_once_with()

    def test_direct_private_active_chat_uses_key_and_base64_encoding(self) -> None:
        ctx = make_context()
        session = MagicMock()
        response = MagicMock()
        response.json.return_value = [{"address": "Qbob", "name": "Bob"}]
        session.post.return_value = response

        result = get_direct_private_active_chats(ctx, session, "private-key-58")

        self.assertEqual(result, [{"address": "Qbob", "name": "Bob"}])
        session.post.assert_called_once_with(
            "http://127.0.0.1:24891/chat/private/direct/active",
            json={"accountPrivateKey": "private-key-58", "encoding": "BASE64"},
            timeout=15,
        )

    def test_private_group_history_is_requested_newest_first(self) -> None:
        ctx = make_context()
        session = MagicMock()
        response = MagicMock()
        response.json.return_value = []
        session.post.return_value = response

        get_private_group_chat_messages(
            ctx,
            session,
            "private-key-58",
            7,
            limit=25,
            before=1234,
        )

        session.post.assert_called_once_with(
            "http://127.0.0.1:24891/chat/private/group/messages",
            json={
                "recipientPrivateKey": "private-key-58",
                "groupId": 7,
                "encoding": "BASE64",
                "limit": 25,
                "reverse": True,
                "before": 1234,
            },
            timeout=15,
        )

    def test_direct_private_send_uses_core_managed_encryption_endpoint(self) -> None:
        ctx = make_context()
        session = MagicMock()
        response = MagicMock()
        response.json.return_value = {"signature": "sent"}
        session.request.return_value = response

        result = send_direct_private_chat(
            ctx,
            session,
            "private-key-58",
            "Qbob",
            "base58-message",
            chat_reference="reply-signature",
        )

        self.assertEqual(result, {"signature": "sent"})
        session.request.assert_called_once_with(
            method="POST",
            url="http://127.0.0.1:24891/chat/private/direct/send",
            timeout=15,
            json={
                "senderPrivateKey": "private-key-58",
                "recipient": "Qbob",
                "data": "base58-message",
                "isText": True,
                "chatReference": "reply-signature",
            },
        )
