"""Stable top-level workflow catalog."""

from __future__ import annotations

from qortium_cli.models import AppContext
from qortium_cli.ui.menu import MenuOption


def _settings(ctx: AppContext) -> None:
    from qortium_cli.features.settings import open_settings

    open_settings(ctx)


def _help(ctx: AppContext) -> None:
    from qortium_cli.tools import tool_help_info

    tool_help_info(ctx)


def _update(ctx: AppContext) -> None:
    from qortium_cli.tools.update import tool_check_for_updates

    tool_check_for_updates(ctx)


def main_options() -> tuple[MenuOption, ...]:
    from qortium_cli.features.advanced import open_advanced
    from qortium_cli.features.identity import open_identity
    from qortium_cli.features.node import open_node_hub
    from qortium_cli.features.qdn import open_qdn_hub
    from qortium_cli.features.social import open_social_hub
    from qortium_cli.features.wallets import open_wallet_hub

    return (
        MenuOption("1", "Node & Minting", "Status, sync, settings, minting accounts", open_node_hub),
        MenuOption("2", "Chat & Groups", "Active room, quick switching, and group management", open_social_hub),
        MenuOption(
            "3",
            "Wallets & Payments",
            "Qortal QORT, Qortium assets, and external crypto wallets",
            open_wallet_hub,
        ),
        MenuOption("4", "QDN Files & Apps", "Browse, download, publish, and manage", open_qdn_hub),
        MenuOption("5", "Identity & Names", "Registered names used across Qortium", open_identity),
        MenuOption("6", "Advanced Tools", "Transactions and raw Core API access", open_advanced),
        MenuOption("7", "Help", "Guidance, version notes, and diagnostics", _help),
        MenuOption("8", "Updates", "Check for a newer Qortium CLI release", _update),
        MenuOption("9", "Settings", "Node connection, API key, and active account", _settings),
    )
