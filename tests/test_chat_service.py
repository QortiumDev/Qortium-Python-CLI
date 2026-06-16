from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock

from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.services import build_chat


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
