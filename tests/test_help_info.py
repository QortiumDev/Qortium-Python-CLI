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
    def test_app_title_uses_v100(self) -> None:
        self.assertEqual(APP_TITLE, "Qortium CLI 1.0.0")

    def test_help_info_shows_whats_new_entries(self) -> None:
        ctx = make_context()

        # Navigate: Help menu → What's New → select v0.3.0 (now at index 3) → back → back
        with (
            patch("qortium_cli.tools.print_banner"),
            patch("qortium_cli.tools.read_menu_choice", side_effect=["1", "3", "0", "0"]),
            patch("qortium_cli.tools.pause"),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                tool_help_info(ctx)

        text = output.getvalue()
        self.assertIn("What's New?", text)
        self.assertIn("v0.3.0", text)
        self.assertIn("v0.4.0", text)
        self.assertIn("v1.0.0", text)
        self.assertIn("Chat commands added: /reply, /edit, /react, /help, and /?.", text)
