from __future__ import annotations

import textwrap

from rich.align import Align
from rich.panel import Panel
from rich.text import Text

from qortium_cli.constants import APP_VERSION, QORTIUM_ASCII
from qortium_cli.ui.console import clear_screen
from qortium_cli.ui.theme import GRADIENT_COLORS, console

TOOL_ICONS = {
    "node": "◉",
    "chat": "◎",
    "groups": "◆",
    "names": "✦",
    "wallet": "◉",
    "qdn": "⬡",
    "minting": "◈",
    "tx_hub": "✦",
    "api": "⬢",
    "setup": "⚙",
    "help": "?",
}


def _gradient_logo() -> Text:
    lines = textwrap.dedent(QORTIUM_ASCII).strip("\n").splitlines()
    total = max(len(lines), 1)
    text = Text(no_wrap=True)
    for i, line in enumerate(lines):
        ratio = i / max(total - 1, 1)
        idx = min(int(ratio * (len(GRADIENT_COLORS) - 1)), len(GRADIENT_COLORS) - 1)
        text.append(line + "\n", style=f"bold {GRADIENT_COLORS[idx]}")
    return text


def print_logo() -> None:
    console.print(_gradient_logo())


def print_banner(base_url: str, title: str) -> None:
    clear_screen()
    console.print(_gradient_logo())
    console.print(f"[qort.accent]Qortium CLI {APP_VERSION}[/]")
    console.print(f"[qort.dim]Node: {base_url}[/]")
    console.print(f"[qort.heading][ {title} ][/]")
    console.rule(style="qort.dim")


def print_setup_banner(title: str) -> None:
    clear_screen()
    console.print(_gradient_logo())
    console.print("[qort.accent]Qortium Setup[/]")
    console.print(f"[qort.heading][ {title} ][/]")
    console.rule(style="qort.dim")


def tool_header(label: str, icon: str = "◆") -> None:
    console.print()
    box = Panel(
        Align.center(f"[bold #e8d0ff]{icon}  {label.upper()}[/]"),
        border_style="#5a3cb0",
        padding=(0, 4),
    )
    console.print(box)
    console.print()


def print_section(title: str) -> None:
    from qortium_cli.constants import BOLD, C_CORE, RESET
    print(C_CORE + BOLD + title + RESET)


def print_stat(label: str, value: object) -> None:
    from qortium_cli.constants import C_TEXT, DIM, RESET
    print(f"{DIM}- {label}:{RESET} {C_TEXT}{value}{RESET}")


def print_option(key: str, label: str) -> None:
    from qortium_cli.constants import BOLD, C_KEY, C_TEXT, RESET
    print(f"{C_KEY}{key}){RESET} {C_TEXT}{label}{RESET}")
