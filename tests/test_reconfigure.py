from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.setup_wizard import configure_api_key, run_reconfigure_menu
from qortium_cli.storage import load_account_settings, write_config_file


def make_context(settings_dir: Path) -> AppContext:
    return AppContext(
        settings_dir=settings_dir,
        endpoint=EndpointSettings(base_url="http://127.0.0.1:24891", timeout_seconds=15),
        account=AccountSettings(
            name="old-name",
            account_address="QgV4s3xnzLhVBEJxcYui4u4q11yhUHsd9v",
            public_key="old-public-key",
            private_key="old-private-key",
            api_key="old-api-key",
        ),
        chat=ChatSettings(),
        debug=False,
    )


class ReconfigureTests(TestCase):
    def test_configure_api_key_preserves_wallet_values(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            ctx = make_context(settings_dir)
            write_config_file(settings_dir, ctx.account)

            with patch("qortium_cli.setup_wizard.prompt_secret", return_value="new-api-key"):
                configure_api_key(ctx)

            saved = load_account_settings(settings_dir)

            self.assertEqual(ctx.account.api_key, "new-api-key")
            self.assertEqual(saved.api_key, "new-api-key")
            self.assertEqual(saved.private_key, "old-private-key")
            self.assertEqual(saved.public_key, "old-public-key")
            self.assertEqual(saved.account_address, "QgV4s3xnzLhVBEJxcYui4u4q11yhUHsd9v")
            self.assertEqual(saved.name, "old-name")

    def test_reconfigure_menu_can_update_only_api_key(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            ctx = make_context(settings_dir)
            write_config_file(settings_dir, ctx.account)

            with (
                patch("qortium_cli.setup_wizard.read_menu_choice", side_effect=["3", "0"]),
                patch("qortium_cli.setup_wizard.prompt_secret", return_value="new-api-key"),
                patch("qortium_cli.setup_wizard.print_setup_banner"),
                patch("qortium_cli.setup_wizard.print_stat"),
                patch("qortium_cli.setup_wizard.print_option"),
                patch("qortium_cli.setup_wizard.pause"),
            ):
                run_reconfigure_menu(ctx)

            saved = load_account_settings(settings_dir)

            self.assertEqual(saved.api_key, "new-api-key")
            self.assertEqual(saved.private_key, "old-private-key")
