import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from qortium_cli.constants import APP_TITLE
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.tools import tool_help_info


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


class HelpInfoTests(TestCase):
    def test_app_title_uses_v030(self) -> None:
        self.assertEqual(APP_TITLE, "Qortium CLI 0.3.0")

    def test_help_info_shows_v030_whats_new_entry(self) -> None:
        ctx = make_context()

        with (
            patch("qortium_cli.tools.print_banner"),
            patch("qortium_cli.tools.read_menu_choice", side_effect=["1", "1", "0", "0"]),
            patch("qortium_cli.tools.pause"),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                tool_help_info(ctx)

        text = output.getvalue()
        self.assertIn("What's New?", text)
        self.assertIn("v0.3.0", text)
        self.assertIn("Chat commands added: /reply, /edit, /react, /help, and /?.", text)
        self.assertIn("Reaction picker supports add/remove flows and emoji categories.", text)
