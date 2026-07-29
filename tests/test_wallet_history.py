from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from qortium_cli.foreign_wallets import ForeignWallet
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.qortal_bridge import QortalJsonResult
from qortium_cli.wallet_history import (
    load_combined_history,
    load_wallet_history,
    load_wallet_public_info,
    WalletTransaction,
)
from qortium_cli.wallet_portfolio import WalletBalance


class WalletHistoryTests(TestCase):
    @staticmethod
    def _context(settings_dir: Path) -> AppContext:
        return AppContext(
            settings_dir=settings_dir,
            endpoint=EndpointSettings("http://127.0.0.1:24891", 5),
            account=AccountSettings(
                name="alice",
                account_address="Qalice",
                private_key="private-key",
            ),
            chat=ChatSettings(),
        )

    @staticmethod
    def _btc() -> WalletBalance:
        return WalletBalance("BTC", "Bitcoin", "MAIN", 8, address="bc1primary")

    def test_qort_history_normalizes_incoming_and_outgoing_payments(self) -> None:
        payload = [
            {
                "timestamp": 2000,
                "signature": "incoming",
                "amount": "2.5",
                "fee": "0.01",
                "creatorAddress": "Qsender",
                "recipient": "Qalice",
            },
            {
                "timestamp": 1000,
                "signature": "outgoing",
                "amount": "1",
                "fee": "0.01",
                "recipient": "Qrecipient",
            },
        ]
        with TemporaryDirectory() as tmp:
            with patch(
                "qortium_cli.wallet_history.fetch_qortal_json",
                return_value=QortalJsonResult(payload, "https://node", "public"),
            ):
                rows = load_wallet_history(
                    self._context(Path(tmp)),
                    WalletBalance("QORT", "Qortal", "QORTAL", 8),
                )

        self.assertEqual(rows[0].amount, Decimal("2.5"))
        self.assertEqual(rows[0].sender, "Qsender")
        self.assertEqual(rows[1].amount, Decimal("-1"))
        self.assertEqual(rows[1].recipient, "Qrecipient")

    def test_foreign_history_uses_xpub_and_preserves_signed_atomic_amount(self) -> None:
        response = MagicMock()
        response.json.return_value = [
            {
                "txHash": "hash",
                "timestamp": 3000,
                "totalAmount": -125000000,
                "feeAmount": 1000,
                "inputs": [
                    {
                        "address": "bc1mine",
                        "amount": 200000000,
                        "addressInWallet": True,
                    }
                ],
                "outputs": [
                    {
                        "address": "bc1theirs",
                        "amount": 125000000,
                        "addressInWallet": False,
                    }
                ],
            }
        ]
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.return_value = response
        derived = ForeignWallet(
            coin="BTC",
            xpub58="xpub-public",
            address="bc1primary",
        )
        with TemporaryDirectory() as tmp:
            with (
                patch(
                    "qortium_cli.wallet_history.derive_foreign_wallet",
                    return_value=derived,
                ),
                patch("qortium_cli.services.make_session", return_value=session),
            ):
                rows = load_wallet_history(self._context(Path(tmp)), self._btc())

        self.assertEqual(rows[0].amount, Decimal("-1.25"))
        self.assertEqual(rows[0].fee, Decimal("0.00001"))
        self.assertEqual(rows[0].recipient, "bc1theirs")
        self.assertEqual(session.post.call_args.kwargs["data"], "xpub-public")

    def test_public_info_uses_addressinfos_endpoint(self) -> None:
        response = MagicMock()
        response.json.return_value = [
            {
                "address": "bc1child",
                "pathAsString": "M/0/0",
                "value": 50000000,
                "transactionCount": 3,
                "isSpendable": True,
            }
        ]
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.return_value = response
        derived = ForeignWallet("BTC", "bc1primary", "xpub-public")
        with TemporaryDirectory() as tmp:
            with (
                patch(
                    "qortium_cli.wallet_history.derive_foreign_wallet",
                    return_value=derived,
                ),
                patch("qortium_cli.services.make_session", return_value=session),
            ):
                info = load_wallet_public_info(
                    self._context(Path(tmp)),
                    self._btc(),
                )

        self.assertEqual(info.primary_address, "bc1primary")
        self.assertEqual(info.addresses[0].balance, Decimal("0.5"))
        self.assertEqual(info.addresses[0].transaction_count, 3)
        self.assertEqual(session.post.call_args.kwargs["json"], {"xpub58": "xpub-public"})

    def test_combined_history_sorts_and_isolates_wallet_errors(self) -> None:
        qort = WalletBalance("QORT", "Qortal", "QORTAL", 8)
        btc = self._btc()
        with TemporaryDirectory() as tmp:
            ctx = self._context(Path(tmp))

            def fake_load(_ctx, wallet, *, limit):
                if wallet.ticker == "BTC":
                    raise RuntimeError("foreign server offline")
                return WalletTransaction(
                    "QORT",
                    1000,
                    "qort-hash",
                    Decimal("1"),
                ),

            with patch(
                "qortium_cli.wallet_history.load_wallet_history",
                side_effect=fake_load,
            ):
                result = load_combined_history(ctx, (qort, btc))

        self.assertEqual(result.transactions[0].tx_hash, "qort-hash")
        self.assertIn("BTC", result.errors)
