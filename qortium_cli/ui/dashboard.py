"""Responsive home dashboard."""

from __future__ import annotations

from typing import Sequence

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from qortium_cli.constants import APP_VERSION
from qortium_cli.models import AppContext
from qortium_cli.ui.console import clear_screen
from qortium_cli.ui.menu import MenuOption, render_options
from qortium_cli.ui.theme import console
from qortium_cli.utils import format_uptime


def _snapshot(ctx: AppContext) -> dict:
    """Fetch dashboard data quickly so an offline node cannot freeze navigation."""

    from qortium_cli.services import make_session

    timeout = min(max(ctx.endpoint.timeout_seconds, 1), 3)
    base_url = ctx.endpoint.base_url.rstrip("/")
    with make_session(ctx, include_api_key=False) as session:
        info_response = session.get(f"{base_url}/admin/info", timeout=timeout)
        info_response.raise_for_status()
        status_response = session.get(f"{base_url}/admin/status", timeout=timeout)
        status_response.raise_for_status()
        return {"info": info_response.json(), "status": status_response.json()}


def _brand_panel(ctx: AppContext) -> Panel:
    text = Text()
    text.append(" QORTIUM ", style="bold #071015 on #5ee7ff")
    text.append(" // COMMAND CONSOLE", style="bold #f1eaff")
    text.append(f"  v{APP_VERSION}", style="dim #a89fc0")
    text.append("\n")
    text.append(" NODE ", style="bold #071015 on #8d6bff")
    text.append(f" {ctx.endpoint.base_url}", style="#d7cced")
    return Panel(text, box=box.SQUARE, border_style="#5b4c7a", padding=(0, 1))


def _node_panel(snapshot: dict) -> Panel:
    status = snapshot.get("status") or {}
    info = snapshot.get("info") or {}
    syncing = bool(status.get("isSynchronizing", False))
    minting = status.get("isMintingPossible")
    if minting is True:
        minting_status = "[bold green]MINTING[/]"
    elif minting is False:
        minting_status = "[bold amber1]NOT READY[/]"
    else:
        minting_status = "[bold red]UNAVAILABLE[/]"
    height = status.get("height", "—")
    if isinstance(height, int):
        height = f"{height:,}"

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="#8f86a4", no_wrap=True)
    grid.add_column(style="white")
    grid.add_row("LINK", "[bold green]ONLINE[/]")
    grid.add_row("SYNC", "[bold amber1]SYNCING[/]" if syncing else "[bold green]READY[/]")
    grid.add_row("HEIGHT", str(height))
    grid.add_row("PEERS", str(status.get("numberOfConnections", "—")))
    grid.add_row("UPTIME", format_uptime(info.get("uptime")))
    grid.add_row("MINT", minting_status)
    return Panel(
        grid,
        title="[bold #5ee7ff] NODE STATUS [/]",
        box=box.SQUARE,
        border_style="#376c78",
    )


def _offline_panel() -> Panel:
    body = Text()
    body.append("LINK      ", style="#8f86a4")
    body.append("OFFLINE\n", style="bold red")
    body.append(
        "The CLI remains usable. Start Core or check Settings → node connection.",
        style="#a9a0bc",
    )
    return Panel(
        body,
        title="[bold red] NODE STATUS [/]",
        box=box.SQUARE,
        border_style="#7a3e4c",
    )


def _account_panel(ctx: AppContext) -> Panel:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="#8f86a4", no_wrap=True)
    grid.add_column(style="white", overflow="fold")
    grid.add_row("NAME", ctx.account.name or "—")
    grid.add_row("ADDRESS", ctx.account.account_address or "—")
    grid.add_row("CHAT", f"GROUP {ctx.chat.tx_group_id}")
    return Panel(
        grid,
        title="[bold #c9a7ff] ACTIVE IDENTITY [/]",
        box=box.SQUARE,
        border_style="#604b82",
    )


def render_dashboard(ctx: AppContext, options: Sequence[MenuOption]) -> None:
    clear_screen()
    console.print(_brand_panel(ctx))
    try:
        node = _node_panel(_snapshot(ctx))
    except Exception:
        node = _offline_panel()
    account = _account_panel(ctx)

    if console.width >= 94:
        status_grid = Table.grid(expand=True, padding=(0, 1))
        status_grid.add_column(ratio=1)
        status_grid.add_column(ratio=1)
        status_grid.add_row(node, account)
        console.print(status_grid)
    else:
        console.print(node)
        console.print(account)

    console.print("[bold #8d6bff] WORKFLOWS [/]\n")
    render_options(
        options,
        zero_label="Exit",
        zero_description="Close Qortium CLI",
    )
