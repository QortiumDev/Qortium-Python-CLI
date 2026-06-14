from __future__ import annotations

import traceback
from pathlib import Path

from qortium_cli.models import AppContext
from qortium_cli.paths import project_root_dir, resolve_settings_dir
from qortium_cli.setup_wizard import configure_first_run_files
from qortium_cli.storage import load_account_settings, load_chat_settings, load_endpoint_settings
from qortium_cli.ui import (
    error,
    init_console,
    ok,
    pause,
    print_banner,
    print_option,
    print_section,
    read_menu_choice,
    startup_splash,
    warn,
)
from qortium_cli.update_checker import maybe_notify_available_updates
from qortium_cli.utils import pretty_exception


class _ForceStream:
    """Stdout wrapper that always reports isatty=True so the animation plays from .bat launchers."""
    def write(self, s: str) -> int:
        import sys
        return sys.stdout.write(s)
    def flush(self) -> None:
        import sys
        sys.stdout.flush()
    def isatty(self) -> bool:
        return True


def _play_startup_animation() -> bool:
    """Play the ANSI startup animation. Returns True if it played."""
    try:
        from importlib.resources import as_file, files
        from qortium_cli.ui.animation import play_ansi_animation

        resource = files("qortium_cli.assets").joinpath("startup-animation.txt")
        with as_file(resource) as path:
            if not path.is_file():
                return False
            return play_ansi_animation(
                path,
                stream=_ForceStream(),
                disable_env="QORTIUM_CLI_NO_ANIM",
            )
    except Exception:
        return False


def create_context(settings_dir: Path) -> AppContext:
    endpoint = load_endpoint_settings(settings_dir)
    account = load_account_settings(settings_dir)
    chat = load_chat_settings(settings_dir)
    return AppContext(settings_dir=settings_dir, endpoint=endpoint, account=account, chat=chat, debug=True)


def run_main_menu(ctx: AppContext) -> None:
    from qortium_cli.tools import build_tool_plugins
    tools = build_tool_plugins()
    tool_map = {tool.key: tool for tool in tools}

    while True:
        _render_main_menu(ctx, tools)
        choice = read_menu_choice("").upper()

        if choice == "0":
            ok("Bye.")
            return

        if choice == "9":
            configure_first_run_files(ctx, force=True)
            continue

        if choice == "/":
            _fuzzy_search_menu(ctx, tools)
            continue

        tool = tool_map.get(choice)
        if not tool:
            warn("Unknown option.")
            pause()
            continue

        try:
            tool.handler(ctx)
        except KeyboardInterrupt:
            warn("Cancelled.")
            pause()
        except Exception as exc:
            error("Tool failed:")
            from qortium_cli.ui.widgets import error_panel
            error_panel(pretty_exception(exc), hint="Check node connection and try again.")
            if ctx.debug:
                traceback.print_exc()
            pause()


def _render_main_menu(ctx: AppContext, tools: list) -> None:
    from rich import box as rich_box
    from rich.table import Table
    from rich.text import Text
    from qortium_cli.ui.theme import console
    from qortium_cli.ui.console import clear_screen
    from qortium_cli.constants import APP_VERSION

    clear_screen()
    from qortium_cli.ui.banner import print_logo
    print_logo()

    # Quick non-blocking stats fetch
    stats: dict = {}
    try:
        from qortium_cli.services import fetch_node_snapshot
        stats = fetch_node_snapshot(ctx)
    except Exception:
        pass

    def kv(t: Text, key: str, label: str) -> None:
        t.append(f" [{key}] ", style="bold yellow")
        t.append(label + "\n", style="white")

    # ── Left column (row 1): title + quick status ────────────────────────────
    left1 = Text()
    left1.append(f"\n Qortium CLI\n", style="bold #e8d0ff")
    left1.append(f" v{APP_VERSION}\n", style="dim #b27cff")
    if stats:
        status = stats.get("status") or {}
        info = stats.get("info") or {}
        synced = status.get("isSynchronizing") is False
        minting = bool(status.get("isMintingPossible", False))
        height = status.get("height", "?")
        from qortium_cli.utils import format_uptime
        uptime_ms = info.get("uptime", 0)
        left1.append("\n", style="")
        left1.append(" ● Synced\n" if synced else " ⟳ Syncing\n",
                     style="bold green" if synced else "bold yellow")
        left1.append(" ● Minting\n" if minting else " ○ Not Minting\n",
                     style="bold green" if minting else "bold red")
        left1.append(f" ▪ {int(height):,} blocks\n" if str(height).isdigit() else "",
                     style="dim #b27cff")
        left1.append(f" ▪ up {format_uptime(uptime_ms)}\n", style="dim")
    else:
        left1.append("\n [dim]offline[/dim]\n", style="dim")
    left1.append("\n", style="")

    # ── Left column (row 2): SOCIAL ──────────────────────────────────────────
    left2 = Text()
    left2.append("\n SOCIAL\n", style="bold #b27cff")
    kv(left2, "2", "Chat")
    kv(left2, "3", "Groups")
    left2.append("\n", style="")

    # ── Left column (row 3): TOOLS label ────────────────────────────────────
    left3 = Text()
    left3.append("\n TOOLS\n", style="bold #b27cff")
    left3.append("\n", style="")

    # ── Right column (row 1): ACCOUNT ────────────────────────────────────────
    right1 = Text()
    right1.append("\n ACCOUNT\n", style="bold #b27cff")
    kv(right1, "5", "Wallet")
    kv(right1, "B", "Backup Wallet")
    kv(right1, "4", "Names")
    kv(right1, "7", "Minting")
    right1.append("\n", style="")

    # ── Right column (row 2): NETWORK ────────────────────────────────────────
    right2 = Text()
    right2.append("\n NETWORK\n", style="bold #b27cff")
    kv(right2, "1", "Node")
    kv(right2, "A", "API Explorer")
    right2.append("\n", style="")

    # ── Right column (row 3): TOOLS items ────────────────────────────────────
    right3 = Text()
    right3.append("\n", style="")
    kv(right3, "6", "QDN")
    kv(right3, "8", "TX Hub")
    right3.append("\n", style="")

    # ── Assemble 3-row, 2-col grid ───────────────────────────────────────────
    grid = Table(
        box=rich_box.DOUBLE,
        show_header=False,
        expand=True,
        padding=(0, 0),
        border_style="#7848cc",
    )
    grid.add_column(ratio=2)
    grid.add_column(ratio=3)
    grid.add_row(left1, right1)
    grid.add_row(left2, right2)
    grid.add_row(left3, right3)

    console.print(grid)

    # ── Footer ────────────────────────────────────────────────────────────────
    footer = Text()
    for key, label in [("9","Reconfig"), ("/","Search"), ("H","Help"), ("U","Update"), ("0","Exit")]:
        footer.append(f"  [{key}] ", style="bold yellow")
        footer.append(label, style="dim")
    console.print(footer)
    console.print()


def _fuzzy_search_menu(ctx: AppContext, tools: list) -> None:
    from qortium_cli.ui.theme import console
    from qortium_cli.ui.prompts import prompt_str, warn

    # Build a flat list of all menu items across all tools
    all_items: list[tuple[str, str, object]] = []
    for tool in tools:
        all_items.append((tool.key, tool.label, tool))
        # Include sub-items if tool exposes them
        if hasattr(tool, "sub_items"):
            for sub_key, sub_label, sub_fn in tool.sub_items:
                all_items.append((sub_key, f"{tool.label} › {sub_label}", sub_fn))

    console.print("\n[qort.heading]Search commands (type to filter, Enter to select):[/]")
    query = prompt_str("[qort.accent]/ [/]", "")
    if not query:
        return

    query_lower = query.lower()
    matches = [
        (key, label, fn)
        for key, label, fn in all_items
        if query_lower in label.lower() or query_lower in key
    ]

    if not matches:
        warn("No matching commands.")
        pause()
        return

    console.print()
    for i, (key, label, _) in enumerate(matches[:9], start=1):
        console.print(f"[qort.key]{i})[/] [white]{label}[/]")

    console.print()
    choice_raw = prompt_str("Select: ", "")
    try:
        idx = int(choice_raw) - 1
        if 0 <= idx < len(matches):
            _, _, fn = matches[idx]
            if hasattr(fn, "handler"):
                fn.handler(ctx)
            elif callable(fn):
                fn(ctx)
    except (ValueError, IndexError):
        pass


def run() -> None:
    init_console()

    # Try ANSI animation first, fall back to text splash
    if not _play_startup_animation():
        startup_splash()

    project_root = project_root_dir()
    settings_dir = resolve_settings_dir(project_root)
    ctx = create_context(settings_dir)
    configure_first_run_files(ctx)
    maybe_notify_available_updates(settings_dir)
    run_main_menu(ctx)
