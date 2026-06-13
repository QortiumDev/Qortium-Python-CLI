import base64
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from qortium_cli.chat_format import build_chat_message_text
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.tools import (
    _editable_chat_threads,
    _normalize_chat_message_input,
    _run_chat_edit_command,
    _send_chat_message,
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


class ChatCommandTests(TestCase):
    def test_build_chat_message_text_preserves_reply_target(self) -> None:
        payload = build_chat_message_text("updated", "sig-parent")

        self.assertEqual(json.loads(payload), {"message": "updated", "repliedTo": "sig-parent"})
        self.assertEqual(build_chat_message_text("plain"), "plain")

    def test_normalize_chat_message_input_escapes_leading_slash(self) -> None:
        self.assertEqual(_normalize_chat_message_input("//help"), "/help")
        self.assertEqual(_normalize_chat_message_input("/help"), "/help")
        self.assertEqual(_normalize_chat_message_input("hello"), "hello")

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
