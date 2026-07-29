from __future__ import annotations

from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from rich.console import Console

from qortium_cli.features import wallets
from qortium_cli.models import AccountSettings, AppContext, ChatSettings, EndpointSettings
from qortium_cli.ui import menu
from qortium_cli.wallet_portfolio import (
    WalletBalance,
    WalletPortfolio,
    _qortal_qort_balance,
    load_wallet_portfolio,
    parse_wallet_networks,
    sort_wallet_balances,
)
from qortium_cli.market_prices import MarketQuote, MarketSnapshot
from qortium_cli.qortal_bridge import QortBalance
from qortium_cli.wallet_history import WalletAddressInfo, WalletTransaction


class WalletPortfolioTests(TestCase):
    @staticmethod
    def _context(settings_dir: Path) -> AppContext:
        return AppContext(
            settings_dir=settings_dir,
            endpoint=EndpointSettings("http://127.0.0.1:24891", 5),
            account=AccountSettings(
                name="alice",
                account_address="Qexample",
                private_key="private-key",
            ),
            chat=ChatSettings(),
        )

    def test_discovery_matches_wallet_app_enabled_known_chain_rules(self) -> None:
        payload = [
            {
                "currencyCode": "LTC",
                "displayName": "Litecoin",
                "walletEnabled": True,
                "activeNetwork": "MAIN",
                "decimalPlaces": 8,
            },
            {
                "currencyCode": "BTC",
                "displayName": "Bitcoin",
                "walletEnabled": True,
                "activeNetwork": "TEST3",
                "decimalPlaces": 8,
            },
            {"currencyCode": "BCH", "walletEnabled": True},
            {"currencyCode": "DOGE", "walletEnabled": False},
        ]

        networks = parse_wallet_networks(payload)

        self.assertEqual([network.code for network in networks], ["BTC", "LTC"])
        self.assertEqual(networks[0].active_network, "TEST3")

    def test_portfolio_always_starts_with_qort_and_keeps_chain_order(self) -> None:
        qort = WalletBalance(
            ticker="QORT",
            display_name="Qortal",
            active_network="QORTAL PUBLIC",
            decimal_places=8,
            balance=Decimal("2"),
        )
        payload = [
            {
                "currencyCode": "LTC",
                "displayName": "Litecoin",
                "walletEnabled": True,
                "activeNetwork": "MAIN",
                "decimalPlaces": 8,
            },
            {
                "currencyCode": "BTC",
                "displayName": "Bitcoin",
                "walletEnabled": True,
                "activeNetwork": "MAIN",
                "decimalPlaces": 8,
            },
        ]
        session = MagicMock()
        session.__enter__.return_value = session

        with TemporaryDirectory() as tmp:
            with (
                patch(
                    "qortium_cli.wallet_portfolio._qortal_qort_balance",
                    return_value=qort,
                ),
                patch("qortium_cli.services.make_session", return_value=session),
                patch("qortium_cli.services.request_json", return_value=payload),
                patch(
                    "qortium_cli.wallet_portfolio._foreign_balance",
                    side_effect=lambda _ctx, network: WalletBalance(
                        ticker=network.code,
                        display_name=network.display_name,
                        active_network=network.active_network,
                        decimal_places=network.decimal_places,
                        balance=Decimal("1"),
                    ),
                ),
                patch(
                    "qortium_cli.market_prices.fetch_market_prices",
                    return_value=MarketSnapshot(
                        quotes={},
                        currency="usd",
                        fetched_at=0,
                    ),
                ),
            ):
                portfolio = load_wallet_portfolio(self._context(Path(tmp)))

        self.assertEqual(
            [wallet.ticker for wallet in portfolio.balances],
            ["QORT", "BTC", "LTC"],
        )
        self.assertEqual(
            [wallet.ticker for wallet in portfolio.all_balances],
            ["QORT", "BTC", "LTC"],
        )

    def test_value_sort_leaves_unpriced_wallets_after_priced_wallets(self) -> None:
        qort = WalletBalance("QORT", "Qortal", "QORTAL", 8)
        btc = WalletBalance(
            "BTC",
            "Bitcoin",
            "MAIN",
            8,
            fiat_value=Decimal("10"),
        )
        ltc = WalletBalance(
            "LTC",
            "Litecoin",
            "MAIN",
            8,
            fiat_value=Decimal("25"),
        )

        result = sort_wallet_balances((qort, btc, ltc), "value-desc")

        self.assertEqual([wallet.ticker for wallet in result], ["LTC", "BTC", "QORT"])

    def test_qort_balance_uses_qortal_bridge_instead_of_qortium_core(self) -> None:
        with TemporaryDirectory() as tmp:
            with patch(
                "qortium_cli.qortal_bridge.fetch_qort_balance",
                return_value=QortBalance(
                    amount=Decimal("7.25"),
                    node_url="https://api.qortal.org",
                    node_source="public",
                ),
            ) as fetch:
                wallet = _qortal_qort_balance(self._context(Path(tmp)))

        fetch.assert_called_once_with("Qexample", 5)
        self.assertEqual(wallet.ticker, "QORT")
        self.assertEqual(wallet.display_name, "Qortal")
        self.assertEqual(wallet.active_network, "QORTAL PUBLIC")
        self.assertEqual(wallet.balance, Decimal("7.25"))

    def test_wallet_workspace_renders_balances_at_sixty_columns(self) -> None:
        output = StringIO()
        narrow_console = Console(
            file=output,
            width=60,
            color_system=None,
            highlight=False,
        )
        portfolio = WalletPortfolio(
            balances=(
                WalletBalance(
                    ticker="QORT",
                    display_name="Qortal",
                    active_network="QORTAL PUBLIC",
                    decimal_places=8,
                    balance=Decimal("12.5"),
                ),
                WalletBalance(
                    ticker="BTC",
                    display_name="Bitcoin",
                    active_network="MAIN",
                    decimal_places=8,
                    balance=Decimal("0.01"),
                    unit_price=Decimal("70000"),
                    fiat_value=Decimal("700"),
                    change_24h=Decimal("2.5"),
                ),
            ),
            currency="usd",
            total_fiat=Decimal("700"),
        )

        with TemporaryDirectory() as tmp:
            with (
                patch.object(wallets, "console", narrow_console),
                patch.object(menu, "console", narrow_console),
                patch.object(menu, "clear_screen"),
            ):
                wallets.render_wallet_hub(
                    self._context(Path(tmp)),
                    portfolio,
                )

        rendered = output.getvalue()
        self.assertIn("WALLET BALANCES", rendered)
        self.assertIn("QORT", rendered)
        self.assertIn("12.50000000", rendered)
        self.assertIn("BTC", rendered)
        self.assertIn("0.01000000", rendered)
        self.assertIn("Refresh everything", rendered)
        self.assertIn("$700.00", rendered)
        self.assertNotIn("MARKET TAPE", rendered)
        self.assertTrue(all(len(line) <= 60 for line in rendered.splitlines()))

    def test_transaction_detail_stays_within_sixty_columns(self) -> None:
        output = StringIO()
        narrow_console = Console(
            file=output,
            width=60,
            color_system=None,
            highlight=False,
        )
        transaction = WalletTransaction(
            ticker="BTC",
            timestamp=1_700_000_000_000,
            tx_hash="a" * 64,
            amount=Decimal("-1.25"),
            fee=Decimal("0.00001"),
            sender="bc1-wallet-address-that-is-deliberately-long",
            recipient="bc1-external-address-that-is-deliberately-long",
            inputs=(
                WalletAddressInfo(
                    address="bc1-wallet-address-that-is-deliberately-long",
                    balance=Decimal("2"),
                    spendable=True,
                ),
            ),
            outputs=(
                WalletAddressInfo(
                    address="bc1-external-address-that-is-deliberately-long",
                    balance=Decimal("1.25"),
                ),
            ),
        )

        with TemporaryDirectory() as tmp:
            with (
                patch.object(wallets, "console", narrow_console),
                patch.object(menu, "console", narrow_console),
                patch.object(menu, "clear_screen"),
                patch.object(wallets, "read_menu_choice", return_value="0"),
            ):
                wallets._transaction_detail(
                    self._context(Path(tmp)),
                    transaction,
                )

        rendered = output.getvalue()
        self.assertIn("INPUTS", rendered)
        self.assertIn("OUTPUTS", rendered)
        self.assertIn("THIS WALLET", rendered)
        self.assertTrue(all(len(line) <= 60 for line in rendered.splitlines()))
