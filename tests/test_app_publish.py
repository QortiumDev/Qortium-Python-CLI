from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.tx_builder import _parse_args, _run_app_publish


def make_context() -> AppContext:
    return AppContext(
        settings_dir=Path("."),
        endpoint=EndpointSettings(base_url="http://127.0.0.1:24891", timeout_seconds=15),
        account=AccountSettings(
            name="My Name",
            account_address="QgV4s3xnzLhVBEJxcYui4u4q11yhUHsd9v",
            public_key="public-key",
            private_key="private-key",
            api_key="api-key",
        ),
        chat=ChatSettings(),
        debug=False,
    )


class AppPublishCommandTests(TestCase):
    def test_parser_accepts_app_publish_arguments(self) -> None:
        args = _parse_args(
            [
                "--build-only",
                "app-publish",
                "--name",
                "My Name",
                "--identifier",
                "default",
                "--path",
                "my-app.zip",
                "--tags",
                "app,qortal",
            ]
        )

        self.assertEqual(args.command, "app-publish")
        self.assertEqual(args.name, "My Name")
        self.assertEqual(args.identifier, "default")
        self.assertEqual(args.tags, "app,qortal")
        self.assertTrue(args.build_only)

    def test_run_app_publish_builds_signs_and_processes(self) -> None:
        ctx = make_context()
        session = MagicMock()

        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            (app_dir / "index.html").write_text("<h1>APP</h1>", encoding="utf-8")
            args = SimpleNamespace(
                name="My Name",
                identifier="default",
                path=str(app_dir),
                title="My App",
                description="Description",
                tags="app,qortal",
                category="software",
                preview=False,
                fee="0",
                out_payload=None,
                out_unsigned=None,
                out_signed=None,
                build_only=False,
                skip_process=False,
                auto_nonce=True,
            )

            with (
                patch(
                    "qortium_cli.tx_builder.get_name_info",
                    return_value={"name": "My Name", "owner": ctx.account.account_address},
                ),
                patch(
                    "qortium_cli.tx_builder.build_arbitrary_from_path",
                    return_value="unsigned-transaction",
                ) as build_publish,
                patch(
                    "qortium_cli.tx_builder.sign_tx",
                    return_value="signed-transaction",
                ) as sign_tx,
                patch(
                    "qortium_cli.tx_builder.process_tx",
                    return_value={"signature": "publish-signature"},
                ) as process_tx,
            ):
                result = _run_app_publish(args, ctx, session)

        self.assertEqual(result, 0)
        build_publish.assert_called_once_with(
            ctx,
            session,
            service="APP",
            name="My Name",
            identifier="default",
            local_path=str(app_dir.resolve()),
            title="My App",
            description="Description",
            tags=["app", "qortal"],
            category="SOFTWARE",
            fee_atomic=None,
            preview=False,
        )
        sign_tx.assert_called_once_with(ctx, "unsigned-transaction", session)
        process_tx.assert_called_once_with(ctx, "signed-transaction", session)

    def test_run_app_publish_build_only_skips_signing(self) -> None:
        ctx = make_context()
        session = MagicMock()

        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            (app_dir / "index.html").write_text("<h1>APP</h1>", encoding="utf-8")
            args = SimpleNamespace(
                name="My Name",
                identifier="default",
                path=str(app_dir),
                title="",
                description="",
                tags="",
                category="UNCATEGORIZED",
                preview=False,
                fee="0",
                out_payload=None,
                out_unsigned=None,
                out_signed=None,
                build_only=True,
                skip_process=False,
                auto_nonce=True,
            )

            with (
                patch(
                    "qortium_cli.tx_builder.get_name_info",
                    return_value={"name": "My Name", "owner": ctx.account.account_address},
                ),
                patch(
                    "qortium_cli.tx_builder.build_arbitrary_from_path",
                    return_value="unsigned-transaction",
                ),
                patch("qortium_cli.tx_builder.sign_tx") as sign_tx,
                patch("qortium_cli.tx_builder.process_tx") as process_tx,
            ):
                result = _run_app_publish(args, ctx, session)

        self.assertEqual(result, 0)
        sign_tx.assert_not_called()
        process_tx.assert_not_called()
