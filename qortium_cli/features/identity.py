"""Identity and registered-name workflows."""

from __future__ import annotations

from qortium_cli.models import AppContext


def open_identity(ctx: AppContext) -> None:
    from qortium_cli.tools import tool_register_name

    tool_register_name(ctx)
