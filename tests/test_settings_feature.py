from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from qortium_cli.features import settings
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.ui.motion import (
    LOADING_EFFECT_ENV,
    load_saved_loading_effect,
)


class AppearanceSettingsFeatureTests(TestCase):
    @staticmethod
    def _context(settings_dir: Path) -> AppContext:
        return AppContext(
            settings_dir=settings_dir,
            endpoint=EndpointSettings("http://127.0.0.1:24891", 5),
            account=AccountSettings(name="alice", account_address="Qexample"),
            chat=ChatSettings(),
        )

    def test_settings_menu_exposes_global_loading_effect(self) -> None:
        with TemporaryDirectory() as tmp:
            with patch.object(settings, "run_menu") as run_menu:
                settings.open_settings(self._context(Path(tmp)))

        options = run_menu.call_args.kwargs["options"]
        self.assertEqual(options[2].label, "Loading effect")
        self.assertIn("full-screen", options[2].description)

    def test_loading_effect_choice_persists_and_applies_immediately(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            with (
                patch.object(settings, "read_menu_choice", return_value="5"),
                patch.object(settings, "ok"),
                patch.object(settings, "pause"),
                patch("builtins.print"),
                patch.dict(os.environ, {}, clear=True),
            ):
                settings._loading_effect(self._context(settings_dir))

                self.assertEqual(load_saved_loading_effect(settings_dir), "rain")
                self.assertEqual(os.environ[LOADING_EFFECT_ENV], "rain")
