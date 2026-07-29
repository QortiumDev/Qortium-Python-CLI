"""Qortium CLI application shell."""

from __future__ import annotations

import traceback
from dataclasses import replace
from pathlib import Path

from qortium_cli.core_detection import detect_local_core_api_key
from qortium_cli.constants import QORTIUM_ASCII
from qortium_cli.models import AppContext
from qortium_cli.navigation import main_options
from qortium_cli.paths import project_root_dir, resolve_settings_dir
from qortium_cli.services import test_api_key_via_node
from qortium_cli.setup_wizard import configure_first_run_files
from qortium_cli.storage import (
    load_account_settings,
    load_chat_settings,
    load_endpoint_settings,
    write_config_file,
)
from qortium_cli.ui import init_console, ok, pause, read_menu_choice, warn
from qortium_cli.ui.dashboard import render_dashboard
from qortium_cli.ui.motion import apply_saved_motion, play_startup
from qortium_cli.ui.widgets import error_panel
from qortium_cli.update_checker import maybe_notify_available_updates
from qortium_cli.utils import pretty_exception


def create_context(settings_dir: Path) -> AppContext:
    return AppContext(
        settings_dir=settings_dir,
        endpoint=load_endpoint_settings(settings_dir),
        account=load_account_settings(settings_dir),
        chat=load_chat_settings(settings_dir),
        debug=False,
    )


def sync_local_core_api_key(ctx: AppContext) -> bool:
    """Scan the local Core install and persist a verified changed key."""

    try:
        candidate = detect_local_core_api_key(ctx.endpoint.base_url)
        if candidate is None:
            return False
        if not test_api_key_via_node(
            ctx.endpoint.base_url,
            candidate.api_key,
            ctx.endpoint.timeout_seconds,
        ):
            return False
        if candidate.api_key == ctx.account.api_key:
            return False

        ctx.account = replace(ctx.account, api_key=candidate.api_key)
        write_config_file(ctx.settings_dir, ctx.account)
        return True
    except Exception:
        # Discovery is a convenience. It must never prevent the CLI from opening.
        return False


def run_main_menu(ctx: AppContext) -> None:
    options = main_options()
    option_map = {option.key: option for option in options}

    while True:
        render_dashboard(ctx, options)
        choice = read_menu_choice("\nSELECT WORKFLOW > ").upper()
        if choice == "0":
            ok("Session closed.")
            return

        option = option_map.get(choice)
        if option is None:
            warn("That workflow number is not available.")
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
            if ctx.debug:
                traceback.print_exc()
            pause()


def run() -> None:
    init_console()
    settings_dir = resolve_settings_dir(project_root_dir())
    apply_saved_motion(settings_dir)
    play_startup(QORTIUM_ASCII)

    ctx = create_context(settings_dir)
    if sync_local_core_api_key(ctx):
        ok("API key synchronized from the local Qortium Core installation.")
    configure_first_run_files(ctx)
    maybe_notify_available_updates(settings_dir)
    run_main_menu(ctx)
