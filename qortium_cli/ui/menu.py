"""Reusable, workflow-oriented menu components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from qortium_cli.models import AppContext
from qortium_cli.ui.console import clear_screen
from qortium_cli.ui.prompts import pause, read_menu_choice, warn
from qortium_cli.ui.theme import console
from qortium_cli.ui.widgets import error_panel
from qortium_cli.utils import pretty_exception


@dataclass(frozen=True)
class MenuOption:
    key: str
    label: str
    description: str
    action: Callable[[AppContext], None]
    destructive: bool = False


def render_header(ctx: AppContext, title: str, breadcrumb: str = "Home") -> None:
    clear_screen()
    heading = Text()
    heading.append(" QORTIUM ", style="bold #071015 on #5ee7ff")
    heading.append(" // ", style="dim #81759c")
    heading.append(title.upper(), style="bold #f1eaff")
    heading.append("\n")
    heading.append(f" {breadcrumb}", style="dim #b9afd4")
    if console.width >= 58:
        heading.append("  •  ", style="dim")
        heading.append(ctx.endpoint.base_url, style="#55d7ff")
    console.print(
        Panel(heading, border_style="#5b4c7a", padding=(0, 1), box=box.SQUARE)
    )


def render_options(
    options: Sequence[MenuOption],
    *,
    zero_label: str = "Back",
    zero_description: str = "Return to the previous screen",
) -> None:
    compact = console.width < 82
    table = Table(
        box=box.SQUARE,
        show_header=False,
        expand=True,
        padding=(0, 1 if not compact else 0),
        border_style="#4f426e",
    )
    table.add_column("Key", width=6, no_wrap=True)
    table.add_column("Action", ratio=2 if not compact else 1)
    if not compact:
        table.add_column("Purpose", ratio=3, style="#a9a0bc")

    for option in options:
        key_style = "bold red" if option.destructive else "bold #5ee7ff"
        label_style = "bold #ff8f9c" if option.destructive else "bold white"
        if compact:
            label = (
                f"[{label_style}]{option.label}[/]\n"
                f"[#a9a0bc]{option.description}[/]"
            )
            table.add_row(f"[{key_style}][{option.key}][/]", label)
        else:
            table.add_row(
                f"[{key_style}][{option.key}][/]",
                f"[{label_style}]{option.label}[/]",
                option.description,
            )

    if compact:
        table.add_row("[dim][0][/]", f"[dim]{zero_label}[/]")
    else:
        table.add_row(
            "[dim][0][/]",
            f"[dim]{zero_label}[/]",
            f"[dim]{zero_description}[/]",
        )
    console.print(table)


def run_menu(
    ctx: AppContext,
    *,
    title: str,
    subtitle: str,
    options: Sequence[MenuOption],
) -> None:
    option_map = {option.key.upper(): option for option in options}

    while True:
        render_header(ctx, title, f"Home  ›  {title}")
        console.print(f"[#b9afd4]{subtitle}[/]\n")
        render_options(options)
        choice = read_menu_choice("\nChoose: ").upper()
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
