from __future__ import annotations

import os
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from rich.console import Console

from qortium_cli.navigation import main_options
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.ui import dashboard
from qortium_cli.ui import menu
from qortium_cli.ui.motion import (
    LOADING_EFFECT_ENV,
    MotionLevel,
    apply_saved_motion,
    load_saved_loading_effect,
    load_saved_motion,
    motion_level,
    save_loading_effect,
    save_motion,
)


class _InteractiveStream(StringIO):
    def isatty(self) -> bool:
        return True


class NavigationTests(TestCase):
    @staticmethod
    def _context(settings_dir: Path) -> AppContext:
        return AppContext(
            settings_dir=settings_dir,
            endpoint=EndpointSettings("http://127.0.0.1:24891", 5),
            account=AccountSettings(name="alice", account_address="Qexample"),
            chat=ChatSettings(tx_group_id=7),
        )

    def test_top_level_numbers_follow_daily_workflow_order(self) -> None:
        self.assertEqual(
            [(option.key, option.label) for option in main_options()],
            [
                ("1", "Node & Minting"),
                ("2", "Chat & Groups"),
                ("3", "Wallets & Payments"),
                ("4", "QDN Files & Apps"),
                ("5", "Identity & Names"),
                ("6", "Advanced Tools"),
                ("7", "Help"),
                ("8", "Updates"),
                ("9", "Settings"),
            ],
        )

    def test_compact_menu_wraps_without_exceeding_terminal_width(self) -> None:
        output = StringIO()
        compact_console = Console(
            file=output,
            width=56,
            color_system=None,
            highlight=False,
        )
        with patch.object(menu, "console", compact_console):
            menu.render_options(main_options(), zero_label="Exit")

        rendered = output.getvalue()
        self.assertIn("Node & Minting", rendered)
        self.assertIn("Status, sync, settings", rendered)
        self.assertIn("Exit", rendered)
        self.assertTrue(all(len(line) <= 56 for line in rendered.splitlines()))

    def test_motion_is_disabled_for_noninteractive_output(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(motion_level(StringIO()), MotionLevel.OFF)

    def test_reduced_motion_preference_is_respected(self) -> None:
        with patch.dict(os.environ, {"QORTIUM_CLI_MOTION": "reduced"}, clear=True):
            self.assertEqual(motion_level(_InteractiveStream()), MotionLevel.REDUCED)

    def test_dashboard_stacks_cleanly_at_sixty_columns(self) -> None:
        output = StringIO()
        narrow_console = Console(
            file=output,
            width=60,
            color_system=None,
            highlight=False,
        )
        snapshot = {
            "info": {"uptime": 90_000},
            "status": {
                "height": 123456,
                "isSynchronizing": False,
                "isMintingPossible": True,
                "numberOfConnections": 8,
            },
        }
        with TemporaryDirectory() as tmp:
            with (
                patch.object(dashboard, "console", narrow_console),
                patch.object(menu, "console", narrow_console),
                patch.object(dashboard, "clear_screen"),
                patch.object(dashboard, "_snapshot", return_value=snapshot),
            ):
                dashboard.render_dashboard(self._context(Path(tmp)), main_options())

        rendered = output.getvalue()
        self.assertIn("NODE STATUS", rendered)
        self.assertIn("ACTIVE IDENTITY", rendered)
        self.assertIn("MINTING", rendered)
        self.assertNotIn("AVAILABLE", rendered)
        self.assertIn("QDN Files & Apps", rendered)
        self.assertTrue(all(len(line) <= 60 for line in rendered.splitlines()))

    def test_motion_preference_round_trips_in_runtime_settings(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            save_loading_effect(settings_dir, "rain")
            save_motion(settings_dir, MotionLevel.REDUCED)
            self.assertEqual(load_saved_motion(settings_dir), MotionLevel.REDUCED)
            self.assertEqual(load_saved_loading_effect(settings_dir), "rain")
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(apply_saved_motion(settings_dir), MotionLevel.REDUCED)
                self.assertEqual(os.environ["QORTIUM_CLI_MOTION"], "reduced")
                self.assertEqual(os.environ[LOADING_EFFECT_ENV], "rain")

    def test_loading_effect_update_preserves_motion_preference(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            save_motion(settings_dir, MotionLevel.OFF)

            save_loading_effect(settings_dir, "decrypt")

            self.assertEqual(load_saved_motion(settings_dir), MotionLevel.OFF)
            self.assertEqual(load_saved_loading_effect(settings_dir), "decrypt")

    def test_existing_motion_only_settings_gain_default_loading_effect(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            (settings_dir / "appearance.json").write_text(
                json.dumps({"motion": "reduced"}),
                encoding="utf-8",
            )

            self.assertEqual(load_saved_motion(settings_dir), MotionLevel.REDUCED)
            self.assertEqual(load_saved_loading_effect(settings_dir), "highlight")
