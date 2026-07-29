from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.tools import tx_hub


class TransactionHubTests(unittest.TestCase):
    def context(self) -> AppContext:
        return AppContext(
            settings_dir=Path("."),
            endpoint=EndpointSettings("http://127.0.0.1:24891", 10),
            account=AccountSettings(
                name="alice",
                account_address="Q" + "a" * 33,
                public_key="public-key",
                private_key="private-key",
                api_key="api-key",
            ),
            chat=ChatSettings(),
            debug=False,
        )

    def test_catalog_uses_current_cancel_name_sale_endpoint(self) -> None:
        transaction = next(item for item in tx_hub.TX_CATALOG if item.code == "CANCEL_SELL_NAME")
        self.assertEqual(transaction.path, "/names/sell/cancel")

    def test_buy_name_collects_required_amount(self) -> None:
        transaction = next(item for item in tx_hub.TX_CATALOG if item.code == "BUY_NAME")
        self.assertIn("amount", {field.name for field in transaction.fields})

    def test_create_group_rejects_inverted_approval_delays(self) -> None:
        transaction = next(item for item in tx_hub.TX_CATALOG if item.code == "CREATE_GROUP")
        with self.assertRaisesRegex(ValueError, "Maximum approval delay"):
            tx_hub._validate_payload(
                transaction,
                {
                    "minimumBlockDelay": 20,
                    "maximumBlockDelay": 10,
                },
            )

    def test_update_name_requires_an_actual_change(self) -> None:
        transaction = next(item for item in tx_hub.TX_CATALOG if item.code == "UPDATE_NAME")
        with self.assertRaisesRegex(ValueError, "new name"):
            tx_hub._validate_payload(transaction, {"newName": "", "newData": ""})

    def test_account_readiness_requires_signing_and_api_values(self) -> None:
        ctx = self.context()
        self.assertTrue(tx_hub._account_is_ready(ctx))
        ctx.account.api_key = "x"
        self.assertFalse(tx_hub._account_is_ready(ctx))

    def test_public_key_is_filled_from_active_account(self) -> None:
        field = tx_hub.Field("creatorPublicKey", "Creator", auto="public_key")
        with patch("qortium_cli.crypto.to_base58_pubkey", return_value="encoded-key"):
            self.assertEqual(tx_hub._auto_value(field, self.context()), "encoded-key")


if __name__ == "__main__":
    unittest.main()
