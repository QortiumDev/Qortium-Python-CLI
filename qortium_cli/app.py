from __future__ import annotations

import traceback
from pathlib import Path

from qortium_cli.models import AppContext
from qortium_cli.paths import project_root_dir, resolve_settings_dir
from qortium_cli.setup_wizard import configure_first_run_files
from qortium_cli.storage import load_account_settings, load_chat_settings, load_endpoint_settings
from qortium_cli.tools import build_tool_plugins
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


def create_context(settings_dir: Path) -> AppContext:
    endpoint = load_endpoint_settings(settings_dir)
    account = load_account_settings(settings_dir)
    chat = load_chat_settings(settings_dir)
    return AppContext(settings_dir=settings_dir, endpoint=endpoint, account=account, chat=chat, debug=True)


def run_main_menu(ctx: AppContext) -> None:
    tools = build_tool_plugins()
    tool_map = {tool.key: tool for tool in tools}

    while True:
        print_banner(ctx.endpoint.base_url, "Main Menu")
        print_section("Toolbox")
        for tool in tools:
            print_option(tool.key, f"{tool.label} - {tool.description}")
        print_option("9", "Reconfigure endpoint/config")
        print_option("0", "Exit")
        choice = read_menu_choice("Choose an option: ").lower()

        if choice == "0":
            ok("Bye.")
            return

        if choice == "9":
            configure_first_run_files(ctx, force=True)
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
            print(pretty_exception(exc))
            if ctx.debug:
                traceback.print_exc()
            pause()


def run() -> None:
    init_console()
    startup_splash()
    project_root = project_root_dir()
    settings_dir = resolve_settings_dir(project_root)
    ctx = create_context(settings_dir)
    configure_first_run_files(ctx)
    maybe_notify_available_updates(settings_dir)
    run_main_menu(ctx)
