from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from qortium_cli.clipboard import copy_text


class ClipboardTests(TestCase):
    def test_windows_uses_native_clip_command(self) -> None:
        with (
            patch("qortium_cli.clipboard.os.name", "nt"),
            patch("qortium_cli.clipboard.subprocess.run") as run,
        ):
            copied = copy_text("wallet-address")

        self.assertTrue(copied)
        self.assertEqual(run.call_args.args[0], ["clip.exe"])
        self.assertEqual(run.call_args.kwargs["input"], "wallet-address")

    def test_no_linux_clipboard_command_fails_safely(self) -> None:
        with (
            patch("qortium_cli.clipboard.os.name", "posix"),
            patch("qortium_cli.clipboard.sys.platform", "linux"),
            patch("qortium_cli.clipboard.shutil.which", return_value=None),
        ):
            self.assertFalse(copy_text("wallet-address"))
