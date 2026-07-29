"""Combined node health, minting, and maintenance workspace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich import box
from rich.panel import Panel
from rich.table import Table

from qortium_cli.models import AppContext
from qortium_cli.ui import json_panel, pause, read_menu_choice, warn
from qortium_cli.ui.menu import MenuOption, render_header, render_options
from qortium_cli.ui.theme import console
from qortium_cli.ui.widgets import error_panel, spinner
from qortium_cli.utils import format_uptime, pretty_exception
from qortium_cli.validators import is_placeholder


@dataclass(frozen=True)
class NodeMintingState:
    """Data displayed immediately when the workspace opens."""

    snapshot: dict[str, Any] | None
    loaded_minting_accounts: int | None
    node_error: str = ""
    minting_error: str = ""


def _refresh(_: AppContext) -> None:
    """Return to the workspace loop, which reloads all live state."""


def _view_minting_accounts(ctx: AppContext) -> None:
    from qortium_cli.tools.minting import view_minting_accounts

    view_minting_accounts(ctx)


def _setup_self_share(ctx: AppContext) -> None:
    from qortium_cli.tools.minting import setup_self_share

    setup_self_share(ctx)


def _add_minting_key(ctx: AppContext) -> None:
    from qortium_cli.tools.minting import add_minting_key

    add_minting_key(ctx)


def _view_node_settings(ctx: AppContext) -> None:
    from qortium_cli.services import make_session, request_json

    with spinner("Loading node settings..."):
        with make_session(ctx, include_api_key=True) as session:
            settings = request_json(ctx, session, "GET", "/admin/settings")
    json_panel(settings, "Effective node settings")
    pause()


def _admin_action(path: str, label: str):
    def action(ctx: AppContext) -> None:
        from qortium_cli.tools import run_admin_action

        run_admin_action(ctx, path, label)
        pause()

    return action


def node_actions() -> tuple[MenuOption, ...]:
    """One workflow-ordered action list for the whole workspace."""

    return (
        MenuOption("1", "Refresh status", "Reload node and minting information", _refresh),
        MenuOption(
            "2",
            "View loaded minting accounts",
            "Inspect reward-share keys currently loaded by Core",
            _view_minting_accounts,
        ),
        MenuOption(
            "3",
            "Set up self-share",
            "Create a self reward-share and load its minting key",
            _setup_self_share,
        ),
        MenuOption(
            "4",
            "Add existing minting key",
            "Load an existing reward-share private key into Core",
            _add_minting_key,
        ),
        MenuOption(
            "5",
            "View node settings",
            "Inspect the Core settings currently in effect",
            _view_node_settings,
        ),
        MenuOption(
            "6",
            "Bootstrap node",
            "Replace local chain data from a trusted bootstrap",
            _admin_action("/admin/bootstrap", "Bootstrap node"),
            destructive=True,
        ),
        MenuOption(
            "7",
            "Restart node",
            "Request a controlled Core restart",
            _admin_action("/admin/restart", "Restart node"),
            destructive=True,
        ),
        MenuOption(
            "8",
            "Stop node",
            "Shut down the connected Core process",
            _admin_action("/admin/stop", "Stop node"),
            destructive=True,
        ),
    )


def _load_state(ctx: AppContext) -> NodeMintingState:
    from qortium_cli.services import fetch_node_snapshot, make_session, request_text_or_json

    snapshot: dict[str, Any] | None = None
    account_count: int | None = None
    node_error = ""
    minting_error = ""

    with spinner("Loading node and minting status..."):
        try:
            snapshot = fetch_node_snapshot(ctx)
        except Exception as exc:
            node_error = pretty_exception(exc)

        if is_placeholder(ctx.account.api_key):
            minting_error = "API key required to inspect loaded minting accounts."
        else:
            try:
                with make_session(ctx, include_api_key=True) as session:
                    accounts = request_text_or_json(
                        ctx,
                        session,
                        "GET",
                        "/admin/mintingaccounts",
                    )
                if isinstance(accounts, list):
                    account_count = len(accounts)
                elif not accounts:
                    account_count = 0
                else:
                    minting_error = "Core returned an unexpected minting-account response."
            except Exception as exc:
                minting_error = pretty_exception(exc)

    return NodeMintingState(
        snapshot=snapshot,
        loaded_minting_accounts=account_count,
        node_error=node_error,
        minting_error=minting_error,
    )


def _value(value: Any) -> str:
    if value in (None, ""):
        return "—"
    return f"{value:,}" if isinstance(value, int) and not isinstance(value, bool) else str(value)


def _node_panel(state: NodeMintingState) -> Panel:
    if state.snapshot is None:
        detail = state.node_error or "The connected Core API did not respond."
        return Panel(
            f"[bold red]OFFLINE[/]\n[#a9a0bc]{detail}[/]",
            title="[bold red] NODE STATUS [/]",
            box=box.SQUARE,
            border_style="#7a3e4c",
        )

    info = state.snapshot.get("info") or {}
    status = state.snapshot.get("status") or {}
    syncing = bool(status.get("isSynchronizing", False))
    sync_percent = status.get("syncPercent")
    sync_text = "SYNCING" if syncing else "READY"
    sync_style = "bold amber1" if syncing else "bold green"
    if sync_percent not in (None, ""):
        sync_text = f"{sync_text}  {_value(sync_percent)}%"

    grid = Table.grid(padding=(0, 2), expand=True)
    grid.add_column(style="#8f86a4", no_wrap=True)
    grid.add_column(style="white", overflow="fold")
    grid.add_row("LINK", "[bold green]ONLINE[/]")
    grid.add_row("SYNC", f"[{sync_style}]{sync_text}[/]")
    grid.add_row("HEIGHT", _value(status.get("height")))
    grid.add_row("PEERS", _value(status.get("numberOfConnections")))
    grid.add_row("DATA PEERS", _value(status.get("numberOfDataConnections")))
    grid.add_row("UPTIME", format_uptime(info.get("uptime")))
    grid.add_row("BUILD", _value(info.get("buildVersion")))
    return Panel(
        grid,
        title="[bold #5ee7ff] NODE STATUS [/]",
        box=box.SQUARE,
        border_style="#376c78",
    )


def _minting_panel(state: NodeMintingState) -> Panel:
    status = (state.snapshot or {}).get("status") or {}
    possible = status.get("isMintingPossible")
    if possible is True:
        capability = "[bold green]MINTING[/]"
    elif possible is False:
        capability = "[bold amber1]NOT READY[/]"
    else:
        capability = "[bold red]UNAVAILABLE[/]"

    if state.loaded_minting_accounts is None:
        loaded = "[bold amber1]UNKNOWN[/]"
    elif state.loaded_minting_accounts == 0:
        loaded = "[bold amber1]NONE LOADED[/]"
    else:
        noun = "KEY" if state.loaded_minting_accounts == 1 else "KEYS"
        loaded = f"[bold green]{state.loaded_minting_accounts} {noun}[/]"

    grid = Table.grid(padding=(0, 2), expand=True)
    grid.add_column(style="#8f86a4", no_wrap=True)
    grid.add_column(style="white", overflow="fold")
    grid.add_row("CORE", capability)
    grid.add_row("LOADED", loaded)
    grid.add_row(
        "MEANING",
        "Core capability and loaded keys are shown separately; this does not estimate rewards.",
    )
    if state.minting_error:
        grid.add_row("NOTE", f"[amber1]{state.minting_error}[/]")

    return Panel(
        grid,
        title="[bold #c9a7ff] MINTING STATUS [/]",
        box=box.SQUARE,
        border_style="#604b82",
    )


def render_node_hub(
    ctx: AppContext,
    state: NodeMintingState,
    options: tuple[MenuOption, ...] | None = None,
) -> None:
    """Render status cards and the combined action menu responsively."""

    render_header(ctx, "Node & Minting", "Home  >  Node & Minting")
    node = _node_panel(state)
    minting = _minting_panel(state)

    if console.width >= 94:
        status_grid = Table.grid(expand=True, padding=(0, 1))
        status_grid.add_column(ratio=1)
        status_grid.add_column(ratio=1)
        status_grid.add_row(node, minting)
        console.print(status_grid)
    else:
        console.print(node)
        console.print(minting)

    console.print("[bold #8d6bff] NODE & MINTING ACTIONS [/]\n")
    render_options(options or node_actions())


def open_node_hub(ctx: AppContext) -> None:
    options = node_actions()
    option_map = {option.key: option for option in options}

    while True:
        state = _load_state(ctx)
        render_node_hub(ctx, state, options)
        choice = read_menu_choice("\nChoose: ").strip()
        if choice == "0":
            return

        option = option_map.get(choice)
        if option is None:
            warn("That number is not available here.")
            pause()
            continue
        try:
            option.action(ctx)
        except KeyboardInterrupt:
            warn("Cancelled.")
            pause()
        except Exception as exc:
            error_panel(
                pretty_exception(exc),
                hint="Check the node connection and try again.",
            )
            pause()
