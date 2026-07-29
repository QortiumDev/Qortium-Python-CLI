import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from qortium_cli.features.chat_backend import (
    ChatConversation,
    ChatGateway,
    ChatReadState,
    load_chat_read_state,
    save_chat_read_state,
)
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings


def context(settings_dir: Path) -> AppContext:
    return AppContext(
        settings_dir=settings_dir,
        endpoint=EndpointSettings("http://127.0.0.1:24891", 5),
        account=AccountSettings(
            name="Alice",
            account_address="Qalice",
            public_key="public-key",
            private_key="private-key-58",
            api_key="api-key",
        ),
        chat=ChatSettings(),
        debug=False,
    )


def encoded_message(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class ChatGatewayTests(TestCase):
    def test_inbox_unifies_direct_open_and_private_group_conversations(self) -> None:
        with TemporaryDirectory() as tmp:
            gateway = ChatGateway(context(Path(tmp)))
            with (
                patch(
                    "qortium_cli.features.chat_backend.make_session"
                ) as make_session,
                patch(
                    "qortium_cli.features.chat_backend.get_member_groups",
                    return_value=[
                        {
                            "groupId": 7,
                            "groupName": "Development",
                            "isOpen": True,
                            "memberCount": 35,
                        },
                        {
                            "groupId": 9,
                            "groupName": "Private Team",
                            "isOpen": False,
                            "memberCount": 4,
                        },
                    ],
                ),
                patch(
                    "qortium_cli.features.chat_backend.get_active_chats",
                    return_value={
                        "groups": [
                            {
                                "groupId": 7,
                                "timestamp": 200,
                                "data": encoded_message("Latest development update"),
                                "encoding": "BASE64",
                                "isText": True,
                                "isEncrypted": False,
                            }
                        ],
                        "direct": [],
                    },
                ),
                patch(
                    "qortium_cli.features.chat_backend.get_direct_private_active_chats",
                    return_value=[
                        {
                            "address": "Qbob",
                            "name": "Bob",
                            "timestamp": 300,
                            "data": encoded_message("Hello Alice"),
                            "encoding": "BASE64",
                            "isText": True,
                            "isEncrypted": True,
                            "decryptionStatus": "DECRYPTED",
                        }
                    ],
                ),
                patch(
                    "qortium_cli.features.chat_backend.get_private_group_active_chats",
                    return_value=[
                        {
                            "groupId": 9,
                            "groupName": "Private Team",
                            "timestamp": 100,
                            "data": encoded_message("Secret update"),
                            "encoding": "BASE64",
                            "isText": True,
                            "isEncrypted": True,
                            "status": "DECRYPTED",
                        }
                    ],
                ),
            ):
                make_session.return_value.__enter__.return_value = MagicMock()
                inbox = gateway.list_conversations()

        self.assertEqual(
            [(item.kind, item.title) for item in inbox.conversations],
            [
                ("direct", "Bob"),
                ("group", "Development"),
                ("private_group", "Private Team"),
                ("public", "General Chat"),
            ],
        )
        self.assertEqual(inbox.conversations[0].preview, "Hello Alice")
        self.assertEqual(inbox.conversations[1].member_count, 35)

    def test_read_state_persists_last_conversation_and_seen_timestamp(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            conversation = ChatConversation(
                key="group:7",
                kind="group",
                title="Development",
                timestamp=1234,
                group_id=7,
            )
            state = ChatReadState()
            self.assertTrue(state.unread(conversation))
            state.mark_seen(conversation)
            state.help_seen = True
            save_chat_read_state(settings_dir, state)

            restored = load_chat_read_state(settings_dir)

        self.assertEqual(restored.active_key, "group:7")
        self.assertFalse(restored.unread(conversation))
        self.assertTrue(restored.help_seen)
