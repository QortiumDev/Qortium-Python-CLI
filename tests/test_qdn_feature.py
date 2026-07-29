from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from qortium_cli.features.qdn import download_qdn_file
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings


class QdnDownloadFeatureTests(TestCase):
    @staticmethod
    def _context(settings_dir: Path) -> AppContext:
        return AppContext(
            settings_dir=settings_dir,
            endpoint=EndpointSettings("http://127.0.0.1:24891", 10),
            account=AccountSettings(api_key="key"),
            chat=ChatSettings(),
        )

    def test_download_streams_default_resource_to_selected_path(self) -> None:
        response = MagicMock()
        response.iter_content.return_value = [b"hello ", b"qdn"]
        session = MagicMock()
        session.get.return_value = response
        session_context = MagicMock()
        session_context.__enter__.return_value = session

        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / "report.txt"
            with (
                patch(
                    "qortium_cli.features.qdn.prompt_str",
                    side_effect=[
                        "FILE",
                        "alice",
                        "default",
                        "report.txt",
                        str(destination),
                    ],
                ),
                patch("qortium_cli.features.qdn.spinner", side_effect=lambda _: nullcontext()),
                patch("qortium_cli.features.qdn.pause"),
                patch("qortium_cli.features.qdn.ok"),
                patch("qortium_cli.services.make_session", return_value=session_context),
            ):
                download_qdn_file(self._context(Path(tmp)))

            self.assertEqual(destination.read_bytes(), b"hello qdn")

        session.get.assert_called_once()
        args, kwargs = session.get.call_args
        self.assertEqual(args[0], "http://127.0.0.1:24891/arbitrary/FILE/alice")
        self.assertEqual(kwargs["params"]["filepath"], "report.txt")
        self.assertEqual(kwargs["params"]["attachment"], "true")
        self.assertTrue(kwargs["stream"])
