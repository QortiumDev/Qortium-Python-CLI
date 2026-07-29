"""Low-level and developer-facing workflows."""

from __future__ import annotations

from qortium_cli.models import AppContext
from qortium_cli.ui.menu import MenuOption, run_menu


def _transactions(ctx: AppContext) -> None:
    from qortium_cli.tools.tx_hub import tool_tx_hub

    tool_tx_hub(ctx)


def _api(ctx: AppContext) -> None:
    from qortium_cli.tools.api_raw import tool_api_explorer

    tool_api_explorer(ctx)


def open_advanced(ctx: AppContext) -> None:
    run_menu(
        ctx,
        title="Advanced Tools",
        subtitle="Powerful low-level interfaces for people who know the Core API.",
        options=(
            MenuOption(
                "1",
                "Guided transaction builder",
                "Review, sign, and submit supported advanced transactions",
                _transactions,
            ),
            MenuOption("2", "API explorer", "Browse and call raw Qortium Core endpoints", _api),
        ),
    )
