from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from qortium_cli.wallet_preferences import (
    WalletPreferences,
    load_wallet_preferences,
    wallet_preferences_path,
    write_wallet_preferences,
)


class WalletPreferenceTests(TestCase):
    def test_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            expected = WalletPreferences("eur", "value-desc", True)

            write_wallet_preferences(settings_dir, expected)

            self.assertEqual(load_wallet_preferences(settings_dir), expected)

    def test_invalid_values_fall_back_to_defaults(self) -> None:
        with TemporaryDirectory() as tmp:
            settings_dir = Path(tmp)
            wallet_preferences_path(settings_dir).write_text(
                json.dumps(
                    {
                        "currency": "not-money",
                        "sort_mode": "random",
                        "hide_zero": "yes",
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(load_wallet_preferences(settings_dir), WalletPreferences())
