"""Chat and group workflows."""

from __future__ import annotations

from qortium_cli.models import AppContext


def open_social_hub(ctx: AppContext) -> None:
    """Open the active conversation directly, without an intermediate menu."""

    from qortium_cli.features.chat import open_chat_workspace

    open_chat_workspace(ctx)
