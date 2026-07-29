from __future__ import annotations

from decimal import Decimal
from unittest import TestCase
from unittest.mock import MagicMock

from qortium_cli import qortal_bridge


def _response(
    *,
    status_code: int = 200,
    text: str = "",
    json_value: object = None,
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.json.return_value = json_value
    return response


class QortalBridgeTests(TestCase):
    def setUp(self) -> None:
        qortal_bridge._invalidate_cached_node()

    def tearDown(self) -> None:
        qortal_bridge._invalidate_cached_node()

    def test_prefers_synced_local_qortal_node_for_qort_balance(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(
                json_value={
                    "height": 2_000_000,
                    "syncPhase": "SYNCED",
                    "syncPercent": 100,
                    "syncBlocksRemaining": 0,
                    "isSynchronizing": False,
                }
            ),
            _response(json_value=[]),
            _response(text="12.50000000"),
        ]

        result = qortal_bridge.fetch_qort_balance(
            "Qexample",
            30,
            session=session,
        )

        self.assertEqual(result.amount, Decimal("12.50000000"))
        self.assertEqual(result.node_source, "local")
        self.assertEqual(result.node_url, "http://127.0.0.1:12391")
        self.assertIn(
            "http://127.0.0.1:12391/addresses/balance/Qexample",
            session.get.call_args_list[-1].args[0],
        )

    def test_unsynced_local_node_falls_back_to_public_qortal_node(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(
                json_value={
                    "height": 2_000_000,
                    "syncPhase": "SYNCING",
                    "syncPercent": 99,
                    "syncBlocksRemaining": 12,
                    "isSynchronizing": True,
                }
            ),
            _response(json_value={"height": 2_000_000}),
            _response(text="3.75"),
        ]

        result = qortal_bridge.fetch_qort_balance(
            "Qexample",
            30,
            session=session,
        )

        self.assertEqual(result.amount, Decimal("3.75"))
        self.assertEqual(result.node_source, "public")
        self.assertEqual(result.node_url, "https://ext-node.qortal.link")
        requested_urls = [call.args[0] for call in session.get.call_args_list]
        self.assertIn(
            "https://ext-node.qortal.link/addresses/balance/Qexample",
            requested_urls,
        )

    def test_accepts_version_two_value_object_balance_response(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(
                json_value={
                    "height": 2_000_000,
                    "syncPhase": "SYNCED",
                    "syncPercent": 100,
                    "syncBlocksRemaining": 0,
                    "isSynchronizing": False,
                }
            ),
            _response(json_value=[]),
            _response(
                text='{"value": 4.125}',
                json_value={"value": 4.125},
            ),
        ]

        result = qortal_bridge.fetch_qort_balance(
            "Qexample",
            30,
            session=session,
        )

        self.assertEqual(result.amount, Decimal("4.125"))

    def test_rejects_non_decimal_qortal_balance(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            _response(json_value={"height": 2_000_000}),
            _response(json_value={"height": 2_000_000}),
            _response(text="not-a-balance"),
            _response(json_value={"height": 2_000_000}),
            _response(json_value={"height": 2_000_000}),
            _response(text="also-invalid"),
            _response(json_value={"height": 2_000_000}),
        ]

        with self.assertRaisesRegex(RuntimeError, "QORT balance lookup failed"):
            qortal_bridge.fetch_qort_balance(
                "Qexample",
                30,
                session=session,
            )
