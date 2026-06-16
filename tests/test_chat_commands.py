import base64
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from qortium_cli.chat_format import build_chat_message_text, build_reaction_message_text
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.tools import (
    _editable_chat_threads,
    _normalize_chat_message_input,
    _replyable_chat_threads,
    _replyable_chat_user_groups,
    _run_chat_edit_command,
    _run_chat_reaction_command,
    _run_chat_reply_command,
    _send_chat_message,
    run_chat_room,
)


def make_context() -> AppContext:
    return AppContext(
        settings_dir=Path("."),
        endpoint=EndpointSettings(base_url="http://127.0.0.1:24891", timeout_seconds=15),
        account=AccountSettings(
            name="tester",
            account_address="QgV4s3xnzLhVBEJxcYui4u4q11yhUHsd9v",
            public_key="public-key",
            private_key="private-key",
            api_key="api-key",
        ),
        chat=ChatSettings(),
        debug=False,
    )


def base64_text(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def message(**overrides):
    row = {
        "data": base64_text("hello"),
        "encoding": "BASE64",
        "isEncrypted": False,
        "isText": True,
        "sender": "QgV4s3xnzLhVBEJxcYui4u4q11yhUHsd9v",
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
    chat_reference: str = "sig-target",
    content: str = "\U0001f44d",
    content_state: bool = True,
):
    return message(
        chatReference=chat_reference,
        data=base64_text(build_reaction_message_text(content, content_state)),
        sender=sender,
        signature=f"reaction-{sender}-{timestamp}",
        timestamp=timestamp,
    )


class ChatCommandTests(TestCase):
    def test_build_chat_message_text_preserves_reply_target(self) -> None:
        payload = build_chat_message_text("updated", "sig-parent")

        self.assertEqual(json.loads(payload), {"message": "updated", "repliedTo": "sig-parent"})
        self.assertEqual(build_chat_message_text("plain"), "plain")

    def test_build_reaction_message_text_builds_reaction_envelope(self) -> None:
        payload = build_reaction_message_text("\U0001f44d", False)

        self.assertEqual(
            json.loads(payload),
            {
                "message": "",
                "type": "reaction",
                "content": "\U0001f44d",
                "contentState": False,
            },
        )

    def test_normalize_chat_message_input_escapes_leading_slash(self) -> None:
        self.assertEqual(_normalize_chat_message_input("//help"), "/help")
        self.assertEqual(_normalize_chat_message_input("/help"), "/help")
        self.assertEqual(_normalize_chat_message_input("hello"), "hello")

    def test_run_chat_room_prints_help_hint_after_timeline(self) -> None:
        ctx = make_context()

        with (
            patch("qortium_cli.tools.ensure_wallet_config_ready"),
            patch("qortium_cli.tools.print_banner"),
            patch("qortium_cli.tools._fetch_chat_timeline", return_value=[]),
            patch("qortium_cli.tools._print_chat_timeline", side_effect=lambda messages: print("timeline\n")),
            patch("qortium_cli.tools.prompt_str", return_value="/quit") as prompt,
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                run_chat_room(ctx)

        text = output.getvalue()
        self.assertIn("timeline\n\n/? for help\n", text)
        self.assertNotIn("Use /help for commands", text)
        prompt.assert_called_once_with("message > ", "")

    def test_editable_chat_threads_only_include_own_confirmed_text_messages(self) -> None:
        ctx = make_context()
        own = message(signature="sig-own", data=base64_text("own"))
        own_edit = message(
            chatReference="sig-own",
            signature="sig-own-edit",
            data=base64_text("own edited"),
        )
        other = message(
            sender="QotherAddress111111111111111111111111",
            signature="sig-other",
            data=base64_text("other"),
        )
        encrypted = message(
            signature="sig-encrypted",
            data=base64_text("secret"),
            isEncrypted=True,
        )
        pending = message(signature="sig-pending", _unconfirmed=True)

        editable = _editable_chat_threads(ctx, [own, other, encrypted, pending, own_edit])

        self.assertEqual(len(editable), 1)
        self.assertEqual(editable[0].original["signature"], "sig-own")
        self.assertEqual(editable[0].latest["signature"], "sig-own-edit")

    def test_replyable_chat_threads_include_confirmed_messages_with_signatures(self) -> None:
        own = message(signature="sig-own", data=base64_text("own"))
        other = message(
            sender="QotherAddress111111111111111111111111",
            senderName="Other",
            signature="sig-other",
            data=base64_text("other"),
        )
        unsigned = message(signature="", data=base64_text("unsigned"))
        pending = message(signature="sig-pending", _unconfirmed=True)

        replyable = _replyable_chat_threads([own, other, unsigned, pending])

        self.assertEqual([thread.original["signature"] for thread in replyable], ["sig-own", "sig-other"])

    def test_replyable_chat_user_groups_sort_by_latest_sender_message(self) -> None:
        old_own = message(
            signature="sig-own-old",
            data=base64_text("old own"),
            timestamp=10,
        )
        recent_own = message(
            signature="sig-own-recent",
            data=base64_text("recent own"),
            timestamp=30,
        )
        other = message(
            sender="QotherAddress111111111111111111111111",
            senderName="Other",
            signature="sig-other",
            data=base64_text("other"),
            timestamp=20,
        )

        groups = _replyable_chat_user_groups([old_own, other, recent_own])

        self.assertEqual([label for _, label, _ in groups], [make_context().account.account_address, "Other"])
        self.assertEqual(
            [thread.original["signature"] for thread in groups[0][2]],
            ["sig-own-recent", "sig-own-old"],
        )

    def test_run_chat_reply_command_submits_reply_envelope(self) -> None:
        ctx = make_context()
        target = message(
            sender="QotherAddress111111111111111111111111",
            senderName="Other",
            data=base64_text("target text"),
            signature="sig-target",
        )

        with (
            patch("qortium_cli.tools.read_menu_choice", side_effect=["1", "1"]),
            patch("qortium_cli.tools.prompt_str", return_value="reply body"),
            patch("qortium_cli.tools._send_chat_message", return_value={"signature": "sig-reply"}) as send,
        ):
            with redirect_stdout(io.StringIO()):
                result = _run_chat_reply_command(ctx, [target])

        self.assertEqual(result, {"signature": "sig-reply"})
        send.assert_called_once()
        _, message_text = send.call_args.args
        self.assertEqual(send.call_args.kwargs, {})
        self.assertEqual(json.loads(message_text), {"message": "reply body", "repliedTo": "sig-target"})

    def test_run_chat_reply_command_blank_input_cancels(self) -> None:
        ctx = make_context()
        target = message(signature="sig-target", data=base64_text("target text"))

        with (
            patch("qortium_cli.tools.read_menu_choice", side_effect=["1", "1"]),
            patch("qortium_cli.tools.prompt_str", return_value=""),
            patch("qortium_cli.tools._send_chat_message") as send,
        ):
            with redirect_stdout(io.StringIO()):
                result = _run_chat_reply_command(ctx, [target])

        self.assertIsNone(result)
        send.assert_not_called()

    def test_run_chat_reaction_command_adds_new_reaction(self) -> None:
        ctx = make_context()
        target = message(
            sender="QotherAddress111111111111111111111111",
            senderName="Other",
            data=base64_text("target text"),
            signature="sig-target",
        )

        with (
            patch("qortium_cli.tools.read_menu_choice", side_effect=["1", "1", "2", "1"]),
            patch("qortium_cli.tools._send_chat_message", return_value={"signature": "sig-reaction"}) as send,
        ):
            with redirect_stdout(io.StringIO()):
                result = _run_chat_reaction_command(ctx, [target])

        self.assertEqual(result, {"signature": "sig-reaction"})
        send.assert_called_once()
        _, message_text = send.call_args.args
        self.assertEqual(send.call_args.kwargs["chat_reference"], "sig-target")
        self.assertEqual(
            json.loads(message_text),
            {
                "message": "",
                "type": "reaction",
                "content": "\U0001f600",
                "contentState": True,
            },
        )

    def test_run_chat_reaction_command_removes_existing_self_reaction(self) -> None:
        ctx = make_context()
        target = message(
            sender="QotherAddress111111111111111111111111",
            senderName="Other",
            data=base64_text("target text"),
            signature="sig-target",
        )
        existing_reaction = reaction_message(
            sender=ctx.account.account_address,
            timestamp=20,
            chat_reference="sig-target",
        )

        with (
            patch("qortium_cli.tools.read_menu_choice", side_effect=["1", "1", "2", "1"]),
            patch("qortium_cli.tools._send_chat_message", return_value={"signature": "sig-reaction"}) as send,
        ):
            with redirect_stdout(io.StringIO()):
                result = _run_chat_reaction_command(ctx, [target, existing_reaction])

        self.assertEqual(result, {"signature": "sig-reaction"})
        _, message_text = send.call_args.args
        self.assertEqual(send.call_args.kwargs["chat_reference"], "sig-target")
        self.assertEqual(json.loads(message_text)["contentState"], False)

    def test_run_chat_reaction_command_can_add_when_self_reaction_exists(self) -> None:
        ctx = make_context()
        target = message(
            sender="QotherAddress111111111111111111111111",
            senderName="Other",
            data=base64_text("target text"),
            signature="sig-target",
        )
        existing_reaction = reaction_message(
            sender=ctx.account.account_address,
            timestamp=20,
            chat_reference="sig-target",
        )

        with (
            patch("qortium_cli.tools.read_menu_choice", side_effect=["1", "1", "1", "1", "1"]),
            patch("qortium_cli.tools._send_chat_message", return_value={"signature": "sig-reaction"}) as send,
        ):
            with redirect_stdout(io.StringIO()):
                result = _run_chat_reaction_command(ctx, [target, existing_reaction])

        self.assertEqual(result, {"signature": "sig-reaction"})
        _, message_text = send.call_args.args
        self.assertEqual(send.call_args.kwargs["chat_reference"], "sig-target")
        self.assertEqual(
            json.loads(message_text),
            {
                "message": "",
                "type": "reaction",
                "content": "\u2764\ufe0f",
                "contentState": True,
            },
        )

    def test_run_chat_reaction_command_cancel_does_not_send(self) -> None:
        ctx = make_context()
        target = message(signature="sig-target", data=base64_text("target text"))

        with (
            patch("qortium_cli.tools.read_menu_choice", side_effect=["1", "1", "0"]),
            patch("qortium_cli.tools._send_chat_message") as send,
        ):
            with redirect_stdout(io.StringIO()):
                result = _run_chat_reaction_command(ctx, [target])

        self.assertIsNone(result)
        send.assert_not_called()

    def test_run_chat_edit_command_submits_reference_and_preserves_reply(self) -> None:
        ctx = make_context()
        original = message(
            data=base64_text(json.dumps({"message": "old reply", "repliedTo": "sig-parent"})),
            signature="sig-own",
        )

        with (
            patch("qortium_cli.tools.read_menu_choice", return_value="1"),
            patch("qortium_cli.tools.prompt_str", return_value="updated reply"),
            patch("qortium_cli.tools._send_chat_message", return_value={"signature": "sig-edit"}) as send,
        ):
            with redirect_stdout(io.StringIO()):
                result = _run_chat_edit_command(ctx, [original])

        self.assertEqual(result, {"signature": "sig-edit"})
        send.assert_called_once()
        _, message_text = send.call_args.args
        self.assertEqual(send.call_args.kwargs["chat_reference"], "sig-own")
        self.assertEqual(json.loads(message_text), {"message": "updated reply", "repliedTo": "sig-parent"})

    def test_run_chat_edit_command_blank_input_cancels(self) -> None:
        ctx = make_context()
        original = message(signature="sig-own", data=base64_text("old"))

        with (
            patch("qortium_cli.tools.read_menu_choice", return_value="1"),
            patch("qortium_cli.tools.prompt_str", return_value=""),
            patch("qortium_cli.tools._send_chat_message") as send,
        ):
            with redirect_stdout(io.StringIO()):
                result = _run_chat_edit_command(ctx, [original])

        self.assertIsNone(result)
        send.assert_not_called()

    def test_send_chat_message_includes_chat_reference_when_present(self) -> None:
        ctx = make_context()
        ctx.chat.tx_group_id = 2
        session = MagicMock()
        manager = MagicMock()
        manager.__enter__.return_value = session
        manager.__exit__.return_value = None

        with (
            patch("qortium_cli.tools.make_session", return_value=manager),
            patch("qortium_cli.tools.to_base58_pubkey", return_value="sender-public-key"),
            patch("qortium_cli.tools.b58encode", return_value="encoded-message") as b58encode,
            patch("qortium_cli.tools.get_timestamp", return_value=123),
            patch("qortium_cli.tools.build_chat", return_value="unsigned") as build_chat,
            patch("qortium_cli.tools.compute_chat_nonce", return_value="unsigned-with-nonce"),
            patch("qortium_cli.tools.sign_tx", return_value="signed"),
            patch("qortium_cli.tools.process_tx", return_value={"signature": "sig-result"}),
        ):
            with redirect_stdout(io.StringIO()):
                result = _send_chat_message(ctx, "edited", chat_reference="sig-own")

        self.assertEqual(result, {"signature": "sig-result"})
        b58encode.assert_called_once_with(b"edited")
        payload = build_chat.call_args.args[1]
        self.assertEqual(payload["chatReference"], "sig-own")
        self.assertEqual(payload["data"], "encoded-message")
        self.assertEqual(payload["txGroupId"], 2)
        self.assertEqual(build_chat.call_args.kwargs["tx_group_id"], 2)
