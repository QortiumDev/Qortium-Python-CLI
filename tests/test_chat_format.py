import base64
import io
import json
from contextlib import redirect_stdout
from unittest import TestCase

from qortium_cli.chat_format import (
    ChatReaction,
    build_message_threads,
    decode_chat_message,
)
from qortium_cli.tools import _print_chat_timeline


def base64_text(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def message(**overrides):
    row = {
        "data": base64_text("hello"),
        "encoding": "BASE64",
        "isEncrypted": False,
        "isText": True,
        "sender": "Qa",
        "signature": "sig-a",
        "timestamp": 10,
        "txGroupId": 0,
    }
    row.update(overrides)
    return row


class ChatFormatTests(TestCase):
    def test_decode_plain_base64_text(self) -> None:
        decoded = decode_chat_message(message(data=base64_text("plain text")))

        self.assertEqual(decoded.kind, "text")
        self.assertEqual(decoded.body, "plain text")
        self.assertIsNone(decoded.replied_to)

    def test_decode_reply_envelope(self) -> None:
        decoded = decode_chat_message(
            message(
                data=base64_text(
                    json.dumps({"message": "reply body", "repliedTo": "sig-parent"})
                )
            )
        )

        self.assertEqual(decoded.kind, "text")
        self.assertEqual(decoded.body, "reply body")
        self.assertEqual(decoded.replied_to, "sig-parent")

    def test_decode_nested_direct_reply_envelope(self) -> None:
        nested = json.dumps({"message": "nested reply", "repliedTo": "sig-parent"})
        direct = json.dumps({"message": nested, "version": 2})

        decoded = decode_chat_message(message(data=base64_text(direct)))

        self.assertEqual(decoded.kind, "text")
        self.assertEqual(decoded.body, "nested reply")
        self.assertEqual(decoded.replied_to, "sig-parent")

    def test_decode_reaction_envelope(self) -> None:
        reaction = json.dumps(
            {
                "message": "",
                "type": "reaction",
                "content": "\U0001f44d",
                "contentState": False,
            }
        )

        decoded = decode_chat_message(message(data=base64_text(reaction)))

        self.assertEqual(decoded.kind, "reaction")
        self.assertEqual(decoded.body, "")
        self.assertEqual(
            decoded.reaction,
            ChatReaction(content="\U0001f44d", content_state=False),
        )

    def test_decode_legacy_message_text_doc(self) -> None:
        doc = {
            "messageText": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "rich text"}],
                    }
                ],
            }
        }

        decoded = decode_chat_message(message(data=base64_text(json.dumps(doc))))

        self.assertEqual(decoded.kind, "text")
        self.assertEqual(decoded.body, "rich text")

    def test_decode_unreadable_encrypted_message_placeholder(self) -> None:
        decoded = decode_chat_message(
            message(
                data=base64_text("secret"),
                isEncrypted=True,
            )
        )

        self.assertEqual(decoded.kind, "encrypted")
        self.assertEqual(decoded.body, "Encrypted message")

    def test_decode_decrypted_direct_wrapper(self) -> None:
        decoded = decode_chat_message(
            message(
                data=base64_text(json.dumps({"message": "direct text", "version": 2})),
                decryptionStatus="DECRYPTED",
                isEncrypted=True,
            )
        )

        self.assertEqual(decoded.kind, "text")
        self.assertEqual(decoded.body, "direct text")

    def test_build_message_threads_folds_same_sender_edits(self) -> None:
        original = message(data=base64_text("original"), signature="sig-a", timestamp=10)
        other = message(sender="Qb", signature="sig-b", timestamp=20)
        first_edit = message(
            chatReference="sig-a",
            data=base64_text("edit one"),
            signature="sig-edit-1",
            timestamp=30,
        )
        second_edit = message(
            chatReference="sig-a",
            data=base64_text("edit two"),
            signature="sig-edit-2",
            timestamp=40,
        )

        threads = build_message_threads([original, other, second_edit, first_edit])

        self.assertEqual(len(threads), 2)
        self.assertEqual(threads[0].original, original)
        self.assertEqual(threads[0].latest, second_edit)
        self.assertEqual(threads[0].revisions, (first_edit, second_edit))
        self.assertEqual(threads[1].latest, other)

    def test_build_message_threads_keeps_replies_and_skips_reactions(self) -> None:
        original = message(data=base64_text("original"), signature="sig-a", timestamp=10)
        reply = message(
            chatReference="sig-a",
            data=base64_text("reply"),
            sender="Qb",
            signature="sig-reply",
            timestamp=20,
        )
        reaction = message(
            chatReference="sig-a",
            data=base64_text(
                json.dumps(
                    {
                        "message": "",
                        "type": "reaction",
                        "content": "\U0001f44d",
                        "contentState": True,
                    }
                )
            ),
            sender="Qb",
            signature="sig-reaction",
            timestamp=30,
        )

        threads = build_message_threads([original, reply, reaction])

        self.assertEqual(len(threads), 2)
        self.assertEqual(threads[0].latest, original)
        self.assertEqual(threads[1].latest, reply)

    def test_print_chat_timeline_folds_edits_and_hides_reactions(self) -> None:
        original = message(
            data=base64_text("original body"),
            senderName="Alice",
            signature="sig-a",
            timestamp=1700000000000,
        )
        edit = message(
            chatReference="sig-a",
            data=base64_text("edited body"),
            senderName="Alice",
            signature="sig-edit",
            timestamp=1700000060000,
        )
        reply = message(
            data=base64_text(
                json.dumps({"message": "reply body", "repliedTo": "sig-a"})
            ),
            sender="Qb",
            senderName="Bob",
            signature="sig-reply",
            timestamp=1700000120000,
        )
        reaction = message(
            chatReference="sig-a",
            data=base64_text(
                json.dumps(
                    {
                        "message": "",
                        "type": "reaction",
                        "content": "\U0001f44d",
                        "contentState": True,
                    }
                )
            ),
            sender="Qb",
            senderName="Bob",
            signature="sig-reaction",
            timestamp=1700000130000,
        )

        output = io.StringIO()
        with redirect_stdout(output):
            _print_chat_timeline([original, edit, reply, reaction])

        text = output.getvalue()
        self.assertIn("Chat Timeline (2 messages)", text)
        self.assertIn("[edited]", text)
        self.assertIn("edited body", text)
        self.assertIn("reply to Alice: edited body", text)
        self.assertIn("reply body", text)
        self.assertNotIn("original body", text)
        self.assertNotIn("sig-reaction", text)
        self.assertNotIn("\U0001f44d", text)
