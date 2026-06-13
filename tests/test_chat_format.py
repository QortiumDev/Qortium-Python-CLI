import base64
import io
import json
from contextlib import redirect_stdout
from unittest import TestCase

from qortium_cli.chat_format import (
    ChatReaction,
    build_reaction_message_text,
    build_message_reaction_index,
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


def reaction_message(
    *,
    sender: str,
    timestamp: int,
    chat_reference: str = "sig-a",
    content: str = "\U0001f44d",
    content_state: bool = True,
):
    return message(
        chatReference=chat_reference,
        data=base64_text(
            json.dumps(
                {
                    "message": "",
                    "type": "reaction",
                    "content": content,
                    "contentState": content_state,
                }
            )
        ),
        sender=sender,
        signature=f"reaction-{sender}-{timestamp}",
        timestamp=timestamp,
    )


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

    def test_build_reaction_message_text_rejects_empty_reaction(self) -> None:
        with self.assertRaises(ValueError):
            build_reaction_message_text("", True)

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
        reaction = reaction_message(sender="Qb", timestamp=30)

        threads = build_message_threads([original, reply, reaction])

        self.assertEqual(len(threads), 2)
        self.assertEqual(threads[0].latest, original)
        self.assertEqual(threads[1].latest, reply)

    def test_build_message_reaction_index_uses_latest_sender_state(self) -> None:
        reactions = build_message_reaction_index(
            [
                reaction_message(sender="Qa", timestamp=20),
                reaction_message(sender="Qb", timestamp=30),
                reaction_message(
                    sender="Qc",
                    timestamp=40,
                    content="\u2764\ufe0f",
                ),
                reaction_message(sender="Qa", timestamp=50, content_state=False),
            ],
            self_address="Qb",
        )

        self.assertEqual(len(reactions["sig-a"]), 2)
        self.assertEqual(reactions["sig-a"][0].content, "\U0001f44d")
        self.assertEqual(reactions["sig-a"][0].count, 1)
        self.assertTrue(reactions["sig-a"][0].reacted_by_self)
        self.assertEqual([reactor.sender for reactor in reactions["sig-a"][0].reactors], ["Qb"])
        self.assertEqual(reactions["sig-a"][1].content, "\u2764\ufe0f")
        self.assertEqual(reactions["sig-a"][1].count, 1)

    def test_print_chat_timeline_folds_edits_and_shows_reactions(self) -> None:
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
        reaction = reaction_message(sender="Qb", timestamp=1700000130000)

        output = io.StringIO()
        with redirect_stdout(output):
            _print_chat_timeline([original, edit, reply, reaction])

        text = output.getvalue()
        self.assertIn("Chat Timeline (2 messages)", text)
        self.assertIn("[edited]", text)
        self.assertIn("edited body", text)
        self.assertIn("reply to Alice: edited body", text)
        self.assertIn("Reactions: \U0001f44d 1", text)
        self.assertIn("reply body", text)
        self.assertNotIn("original body", text)
        self.assertNotIn("sig-reaction", text)

    def test_print_chat_timeline_shows_unavailable_for_missing_reply(self) -> None:
        reply = message(
            data=base64_text(
                json.dumps({"message": "orphan reply", "repliedTo": "missing-signature"})
            ),
            sender="Qb",
            senderName="Bob",
            signature="sig-reply",
            timestamp=1700000120000,
        )

        output = io.StringIO()
        with redirect_stdout(output):
            _print_chat_timeline([reply])

        text = output.getvalue()
        self.assertIn("reply to: unavailable", text)
        self.assertIn("orphan reply", text)
        self.assertNotIn("missing-signature", text)
