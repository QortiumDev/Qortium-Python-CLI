from __future__ import annotations

from unittest import TestCase
from unittest.mock import MagicMock, patch

from qortium_cli import market_prices


class MarketPriceTests(TestCase):
    def setUp(self) -> None:
        market_prices._market_cache.clear()

    def test_fetches_supported_coins_in_one_batched_keyless_request(self) -> None:
        response = MagicMock()
        response.json.return_value = {
            "bitcoin": {
                "usd": 70000,
                "usd_24h_change": 1.25,
                "last_updated_at": 123,
            },
            "litecoin": {
                "usd": 90.5,
                "usd_24h_change": -2,
                "last_updated_at": 124,
            },
        }
        session = MagicMock()
        session.get.return_value = response

        snapshot = market_prices.fetch_market_prices(
            ("QORT", "LTC", "BTC", "UNKNOWN"),
            session=session,
        )

        self.assertEqual(set(snapshot.quotes), {"BTC", "LTC"})
        self.assertEqual(str(snapshot.quotes["BTC"].price), "70000")
        self.assertEqual(str(snapshot.quotes["LTC"].change_24h), "-2")
        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["params"]["ids"], "bitcoin,litecoin")
        self.assertNotIn("x-cg-demo-api-key", kwargs["headers"])

    def test_optional_demo_key_is_sent_only_when_configured(self) -> None:
        response = MagicMock()
        response.json.return_value = {"bitcoin": {"eur": 60000}}
        session = MagicMock()
        session.get.return_value = response

        with patch.dict(
            "os.environ",
            {"QORTIUM_CLI_COINGECKO_API_KEY": "demo-secret"},
            clear=False,
        ):
            market_prices.fetch_market_prices(
                ("BTC",),
                "eur",
                session=session,
            )

        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["headers"]["x-cg-demo-api-key"], "demo-secret")

    def test_failed_refresh_returns_stale_cached_prices(self) -> None:
        good_response = MagicMock()
        good_response.json.return_value = {"bitcoin": {"usd": 70000}}
        session = MagicMock()
        session.get.return_value = good_response
        first = market_prices.fetch_market_prices(("BTC",), session=session)

        session.get.side_effect = market_prices.requests.ConnectionError("offline")
        stale = market_prices.fetch_market_prices(
            ("BTC",),
            force=True,
            session=session,
        )

        self.assertTrue(stale.stale)
        self.assertEqual(stale.quotes, first.quotes)
        self.assertIn("offline", stale.error)
