from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from qortium_cli.core_detection import LocalCoreApiKey
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.setup_wizard import (
    configure_api_key,
    configure_endpoint_url,
    configure_wallet_identity,
    run_initial_setup,
    run_reconfigure_menu,
)
from qortium_cli.storage import (
    load_account_settings,
    load_endpoint_settings,
    write_config_file,
    write_endpoint_file,
)


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

            with (
                patch("qortium_cli.setup_wizard.detect_local_core_api_key", return_value=None),
                patch("qortium_cli.setup_wizard.prompt_secret", return_value="new-api-key"),
            ):
                configure_api_key(ctx)

            saved = load_account_settings(settings_dir)

            self.assertEqual(ctx.account.api_key, "new-api-key")
            self.assertEqual(saved.api_key, "new-api-key")
            self.assertEqual(saved.private_key, "old-private-key")
            self.assertEqual(saved.public_key, "old-public-key")
            self.assertEqual(saved.account_address, "QgV4s3xnzLhVBEJxcYui4u4q11yhUHsd9v")
            self.assertEqual(saved.name, "old-name")

    def test_configure_api_key_uses_detected_local_core_key_by_default(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            ctx = make_context(settings_dir)
            write_config_file(settings_dir, ctx.account)
            detected = LocalCoreApiKey(
                api_key="detected-api-key",
                api_key_path=settings_dir / "apikey.txt",
                api_key_directory=settings_dir,
                cwd=settings_dir,
                jar_path=settings_dir / "qortium.jar",
                pid=123,
                settings_path=settings_dir / "settings.json",
            )

            with (
                patch("qortium_cli.setup_wizard.detect_local_core_api_key", return_value=detected),
                patch("qortium_cli.setup_wizard.prompt_secret", return_value=""),
                patch("qortium_cli.setup_wizard.ok"),
            ):
                configure_api_key(ctx)

            saved = load_account_settings(settings_dir)

            self.assertEqual(ctx.account.api_key, "detected-api-key")
            self.assertEqual(saved.api_key, "detected-api-key")
            self.assertEqual(saved.private_key, "old-private-key")

    def test_initial_setup_prefers_detected_api_key_over_existing_key(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            ctx = make_context(settings_dir)
            detected = LocalCoreApiKey(
                api_key="detected-api-key",
                api_key_path=settings_dir / "apikey.txt",
                api_key_directory=settings_dir,
                cwd=settings_dir,
                jar_path=settings_dir / "qortium.jar",
                pid=123,
                settings_path=settings_dir / "settings.json",
            )
            next_account = AccountSettings(
                name="detected-account",
                account_address="Qdetected",
                public_key="detected-public-key",
                private_key="detected-private-key",
                api_key="detected-api-key",
            )

            with (
                patch(
                    "qortium_cli.setup_wizard._prompt_endpoint_url_with_connection_check",
                    return_value="http://127.0.0.1:24891",
                ),
                patch("qortium_cli.setup_wizard.prompt_int", return_value=15),
                patch("qortium_cli.setup_wizard.detect_local_core_api_key", return_value=detected),
                patch("qortium_cli.setup_wizard.prompt_secret", return_value=""),
                patch("qortium_cli.setup_wizard._prompt_private_key", return_value="detected-private-key"),
                patch(
                    "qortium_cli.setup_wizard._account_from_private_key",
                    return_value=next_account,
                ) as account_from_private_key,
                patch("qortium_cli.setup_wizard.print_setup_banner"),
                patch("qortium_cli.setup_wizard.pause"),
                patch("qortium_cli.setup_wizard.ok"),
            ):
                run_initial_setup(ctx)

            saved = load_account_settings(settings_dir)

            account_from_private_key.assert_called_once_with(
                ctx,
                "detected-private-key",
                "detected-api-key",
            )
            self.assertEqual(saved.api_key, "detected-api-key")

    def test_reconfigure_menu_can_update_only_api_key(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            ctx = make_context(settings_dir)
            write_config_file(settings_dir, ctx.account)

            with (
                patch("qortium_cli.setup_wizard.read_menu_choice", side_effect=["3", "0"]),
                patch("qortium_cli.setup_wizard.detect_local_core_api_key", return_value=None),
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

    def test_reconfigure_menu_runs_initial_setup_then_returns(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            ctx = make_context(settings_dir)

            with (
                patch("qortium_cli.setup_wizard.read_menu_choice", return_value="9") as read_menu_choice,
                patch("qortium_cli.setup_wizard.run_initial_setup") as run_initial_setup,
                patch("qortium_cli.setup_wizard.print_setup_banner"),
                patch("qortium_cli.setup_wizard.print_stat"),
                patch("qortium_cli.setup_wizard.print_option") as print_option,
            ):
                run_reconfigure_menu(ctx)

            print_option.assert_any_call("9", "Run initial setup")
            read_menu_choice.assert_called_once()
            run_initial_setup.assert_called_once_with(ctx)

    def test_configure_wallet_identity_accepts_wallet_file(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            ctx = make_context(settings_dir)
            wallet_path = settings_dir / "wallet.json"
            next_account = AccountSettings(
                name="wallet-account",
                account_address="Qwallet",
                public_key="wallet-public-key",
                private_key="wallet-private-key",
                api_key="old-api-key",
            )

            with (
                patch("qortium_cli.setup_wizard.read_menu_choice", return_value="3"),
                patch("qortium_cli.setup_wizard.prompt_str", return_value=f"'{wallet_path}' "),
                patch("qortium_cli.setup_wizard.prompt_secret", return_value="wallet-password"),
                patch(
                    "qortium_cli.setup_wizard.private_key_from_wallet_file",
                    return_value="wallet-private-key",
                ) as private_key_from_wallet_file,
                patch(
                    "qortium_cli.setup_wizard._account_from_private_key",
                    return_value=next_account,
                ) as account_from_private_key,
                patch("qortium_cli.setup_wizard.ok"),
            ):
                configure_wallet_identity(ctx)

            saved = load_account_settings(settings_dir)

            private_key_from_wallet_file.assert_called_once_with(wallet_path.resolve(), "wallet-password")
            account_from_private_key.assert_called_once_with(ctx, "wallet-private-key", "old-api-key")
            self.assertEqual(ctx.account.private_key, "wallet-private-key")
            self.assertEqual(saved.private_key, "wallet-private-key")

    def test_configure_endpoint_url_retries_after_failed_connection(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            ctx = make_context(settings_dir)
            write_endpoint_file(settings_dir, ctx.endpoint)

            with (
                patch(
                    "qortium_cli.setup_wizard.prompt_str",
                    side_effect=["http://bad-node:24891", "http://good-node:24891"],
                ),
                patch(
                    "qortium_cli.setup_wizard.check_node_connection",
                    side_effect=[
                        (False, "connection refused"),
                        (True, "Node API responded."),
                    ],
                ) as check_node_connection,
                patch("qortium_cli.setup_wizard.read_menu_choice", return_value="1"),
                patch("qortium_cli.setup_wizard.print_option"),
                patch("qortium_cli.setup_wizard.warn"),
                patch("qortium_cli.setup_wizard.ok"),
            ):
                configure_endpoint_url(ctx)

            saved = load_endpoint_settings(settings_dir)

            self.assertEqual(ctx.endpoint.base_url, "http://good-node:24891")
            self.assertEqual(saved.base_url, "http://good-node:24891")
            self.assertEqual(check_node_connection.call_count, 2)

    def test_configure_endpoint_url_can_continue_after_failed_connection(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            ctx = make_context(settings_dir)
            write_endpoint_file(settings_dir, ctx.endpoint)

            with (
                patch("qortium_cli.setup_wizard.prompt_str", return_value="http://bad-node:24891"),
                patch(
                    "qortium_cli.setup_wizard.check_node_connection",
                    return_value=(False, "connection refused"),
                ) as check_node_connection,
                patch("qortium_cli.setup_wizard.read_menu_choice", return_value="2"),
                patch("qortium_cli.setup_wizard.print_option"),
                patch("qortium_cli.setup_wizard.warn"),
            ):
                configure_endpoint_url(ctx)

            saved = load_endpoint_settings(settings_dir)

            self.assertEqual(ctx.endpoint.base_url, "http://bad-node:24891")
            self.assertEqual(saved.base_url, "http://bad-node:24891")
            check_node_connection.assert_called_once_with("http://bad-node:24891", 15)
