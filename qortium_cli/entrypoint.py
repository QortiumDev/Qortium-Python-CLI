from __future__ import annotations

import argparse
import os
import traceback
from collections.abc import Sequence

from qortium_cli.constants import APP_VERSION
from qortium_cli.ui import error, warn
from qortium_cli.utils import pretty_exception


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qortium-cli",
        description="A colorful command console for Qortium.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Qortium CLI {APP_VERSION}",
    )
    parser.add_argument(
        "--no-motion",
        action="store_true",
        help="disable TerminalTextEffects animations for this session",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="verify packaged runtime imports and exit",
    )
    return parser


def _self_check() -> None:
    from terminaltexteffects.effects.effect_decrypt import Decrypt
    from terminaltexteffects.effects.effect_errorcorrect import ErrorCorrect
    from terminaltexteffects.effects.effect_highlight import Highlight
    from terminaltexteffects.effects.effect_rain import Rain
    from terminaltexteffects.effects.effect_slide import Slide
    from terminaltexteffects.effects.effect_wipe import Wipe
    from textual.app import App as TextualApp

    from qortium_cli.crypto import b58encode
    from qortium_cli.clipboard import copy_text
    from qortium_cli.features.chat import chat_actions
    from qortium_cli.features.chat_tui import ChatWorkspaceApp
    from qortium_cli.features.node import node_actions
    from qortium_cli.features.wallets import wallet_actions
    from qortium_cli.foreign_wallets import derive_foreign_wallet
    from qortium_cli.market_prices import COINGECKO_IDS
    from qortium_cli.navigation import main_options
    from qortium_cli.qortal_bridge import qortal_node_candidates
    from qortium_cli.wallet_history import WalletTransaction
    from qortium_cli.wallet_preferences import FIAT_CURRENCY_CODES

    if len(main_options()) != 9:
        raise RuntimeError("navigation catalog is incomplete")
    if (
        len(node_actions()) != 8
        or len(chat_actions((), ())) != 8
        or len(wallet_actions()) != 7
    ):
        raise RuntimeError("feature action catalogs are incomplete")
    test_wallet = derive_foreign_wallet(b58encode(bytes(range(32))), "BTC")
    if test_wallet.address != "1A9G3q16XmzmVDF72DvSZEK37ZzZUrNmK1":
        raise RuntimeError("foreign-wallet derivation is incomplete")
    if qortal_node_candidates()[0].url != "http://127.0.0.1:12391":
        raise RuntimeError("Qortal wallet bridge is incomplete")
    if (
        COINGECKO_IDS.get("BTC") != "bitcoin"
        or "usd" not in FIAT_CURRENCY_CODES
        or WalletTransaction is None
        or copy_text is None
    ):
        raise RuntimeError("wallet workspace support is incomplete")
    if any(
        effect is None
        for effect in (Decrypt, ErrorCorrect, Highlight, Rain, Slide, Wipe)
    ):
        raise RuntimeError("TerminalTextEffects imports are incomplete")
    if not issubclass(ChatWorkspaceApp, TextualApp):
        raise RuntimeError("Textual chat workspace support is incomplete")
    print("Qortium CLI runtime check: OK")


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.self_check:
        _self_check()
        return
    if args.no_motion:
        os.environ["QORTIUM_CLI_MOTION"] = "off"

    from qortium_cli.app import run

    try:
        run()
    except KeyboardInterrupt:
        warn("\nCancelled.")
    except Exception as exc:
        error("ERROR: " + pretty_exception(exc))
        if os.environ.get("QORTIUM_CLI_DEBUG") == "1":
            traceback.print_exc()
        try:
            input("\nAn error occurred. Press Enter to exit...")
        except Exception:
            pass
