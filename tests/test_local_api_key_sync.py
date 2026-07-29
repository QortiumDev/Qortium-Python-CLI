from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from qortium_cli.app import sync_local_core_api_key
from qortium_cli.core_detection import LocalCoreApiKey
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.services import test_api_key_via_node
from qortium_cli.storage import load_account_settings


def make_context(settings_dir: Path, api_key: str = "old-key") -> AppContext:
    return AppContext(
        settings_dir=settings_dir,
        endpoint=EndpointSettings("http://127.0.0.1:24891", 15),
        account=AccountSettings(
            name="alice",
            account_address="Qalice",
            public_key="public-key",
            private_key="private-key",
            api_key=api_key,
        ),
        chat=ChatSettings(),
        debug=False,
    )


def candidate(root: Path, api_key: str = "installed-key") -> LocalCoreApiKey:
    return LocalCoreApiKey(
        api_key=api_key,
        api_key_path=root / "apikey.txt",
        api_key_directory=root,
        cwd=root,
        jar_path=root / "qortium.jar",
        pid=0,
        settings_path=root / "settings.json",
    )


class ApiKeyVerificationTests(TestCase):
    def test_core_test_endpoint_must_explicitly_return_true(self) -> None:
        response = MagicMock(status_code=200, text="true")
        with patch("qortium_cli.services.requests.get", return_value=response) as get:
            accepted = test_api_key_via_node(
                "http://127.0.0.1:24891/",
                "candidate-key",
                15,
            )

        self.assertTrue(accepted)
        get.assert_called_once_with(
            "http://127.0.0.1:24891/admin/apikey/test",
            headers={"X-API-KEY": "candidate-key", "Accept": "text/plain"},
            timeout=5,
        )

    def test_core_rejection_does_not_accept_candidate(self) -> None:
        response = MagicMock(status_code=401, text="false")
        with patch("qortium_cli.services.requests.get", return_value=response):
            self.assertFalse(
                test_api_key_via_node(
                    "http://127.0.0.1:24891",
                    "candidate-key",
                    15,
                )
            )


class LocalApiKeySyncTests(TestCase):
    def test_verified_install_key_replaces_only_api_key(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = make_context(root)
            with (
                patch(
                    "qortium_cli.app.detect_local_core_api_key",
                    return_value=candidate(root),
                ),
                patch("qortium_cli.app.test_api_key_via_node", return_value=True),
            ):
                changed = sync_local_core_api_key(ctx)

            saved = load_account_settings(root)

        self.assertTrue(changed)
        self.assertEqual(ctx.account.api_key, "installed-key")
        self.assertEqual(saved.api_key, "installed-key")
        self.assertEqual(saved.private_key, "private-key")
        self.assertEqual(saved.account_address, "Qalice")

    def test_unverified_install_key_is_not_saved(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = make_context(root)
            with (
                patch(
                    "qortium_cli.app.detect_local_core_api_key",
                    return_value=candidate(root),
                ),
                patch("qortium_cli.app.test_api_key_via_node", return_value=False),
            ):
                changed = sync_local_core_api_key(ctx)

            self.assertFalse((root / "config.py").exists())

        self.assertFalse(changed)
        self.assertEqual(ctx.account.api_key, "old-key")

    def test_matching_verified_key_does_not_rewrite_settings(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = make_context(root, api_key="installed-key")
            with (
                patch(
                    "qortium_cli.app.detect_local_core_api_key",
                    return_value=candidate(root),
                ),
                patch("qortium_cli.app.test_api_key_via_node", return_value=True),
                patch("qortium_cli.app.write_config_file") as write_config,
            ):
                changed = sync_local_core_api_key(ctx)

        self.assertFalse(changed)
        write_config.assert_not_called()
