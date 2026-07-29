from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.services import make_session
from qortium_cli.storage import write_config_file
from qortium_cli.ui import prompts
from qortium_cli.validators import normalize_api_key


def make_context(api_key: str) -> AppContext:
    return AppContext(
        settings_dir=Path("."),
        endpoint=EndpointSettings("http://127.0.0.1:24891", 5),
        account=AccountSettings(api_key=api_key),
        chat=ChatSettings(),
        debug=False,
    )


class ApiKeySafetyTests(TestCase):
    def test_control_character_is_rejected_before_it_becomes_a_header(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid control"):
            make_session(make_context("\x16"), include_api_key=True)

    def test_validation_message_does_not_echo_the_key(self) -> None:
        malformed = "secret\x16value"
        with self.assertRaises(ValueError) as raised:
            normalize_api_key(malformed)

        self.assertNotIn("secret", str(raised.exception))
        self.assertIn("Settings", str(raised.exception))

    def test_config_writer_refuses_to_persist_control_characters(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            with self.assertRaisesRegex(ValueError, "invalid control"):
                write_config_file(settings_dir, make_context("\x16").account)

            self.assertFalse((settings_dir / "config.py").exists())

    def test_windows_hidden_prompt_pastes_clipboard_on_ctrl_v(self) -> None:
        getwch = MagicMock(side_effect=["\x16", "\r"])
        fake_msvcrt = SimpleNamespace(getwch=getwch)
        with (
            patch.dict(sys.modules, {"msvcrt": fake_msvcrt}),
            patch.object(prompts, "_windows_clipboard_text", return_value="pasted-api-key"),
            patch.object(prompts, "_p"),
        ):
            value = prompts._windows_secret_input("API key: ")

        self.assertEqual(value, "pasted-api-key")
        self.assertNotIn("\x16", value)
