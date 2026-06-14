"""Backward-compatibility shim — re-exports everything from qortium_cli.ui.*"""
from __future__ import annotations

from qortium_cli.ui.banner import (
    print_banner,
    print_logo,
    print_option,
    print_section,
    print_stat,
    print_setup_banner,
    tool_header,
)
from qortium_cli.ui.console import clear_screen, init_console
from qortium_cli.ui.prompts import (
    error,
    ok,
    pause,
    prompt_decimal,
    prompt_int,
    prompt_multiline_message,
    prompt_secret,
    prompt_str,
    prompt_yes_no,
    read_menu_choice,
    warn,
)
from qortium_cli.ui.widgets import (
    TxPipeline,
    addr_short,
    balance_str,
    bool_str,
    data_table,
    error_panel,
    height_str,
    json_panel,
    ok_panel,
    spinner,
    stat_table,
    warn_panel,
)

__all__ = [
    # banner
    "print_banner",
    "print_logo",
    "print_option",
    "print_section",
    "print_stat",
    "print_setup_banner",
    "tool_header",
    # console
    "clear_screen",
    "init_console",
    # prompts
    "error",
    "ok",
    "pause",
    "prompt_decimal",
    "prompt_int",
    "prompt_multiline_message",
    "prompt_secret",
    "prompt_str",
    "prompt_yes_no",
    "read_menu_choice",
    "warn",
    # widgets
    "TxPipeline",
    "addr_short",
    "balance_str",
    "bool_str",
    "data_table",
    "error_panel",
    "height_str",
    "json_panel",
    "ok_panel",
    "spinner",
    "stat_table",
    "warn_panel",
    # startup_splash kept for backward compat — defined below
    "startup_splash",
]


def startup_splash() -> None:
    """Legacy splash — replaced by ANSI animation in app.py, kept for compat."""
    import os
    import sys
    import time
    import textwrap
    from qortium_cli.constants import APP_TITLE, LOGO_GRADIENT, QORTIUM_ASCII, RESET

    if str(os.environ.get("QORTIUM_NO_ANIM", "") or "").strip() == "1":
        return
    if not getattr(sys.stdout, "isatty", lambda: False)():
        return

    clear_screen()
    lines = textwrap.dedent(QORTIUM_ASCII).strip("\n").splitlines()
    total = max(len(lines), 1)
    tail = max(total - 1, 1)
    time.sleep(0.09)
    for index, line in enumerate(lines):
        ratio = index / tail
        idx = min(int(ratio * (len(LOGO_GRADIENT) - 1)), len(LOGO_GRADIENT) - 1)
        sys.stdout.write(LOGO_GRADIENT[idx] + line + RESET + "\n")
        sys.stdout.flush()
        time.sleep(0.03 + (0.03 * ratio))
    sys.stdout.write(APP_TITLE + "\n")
    sys.stdout.flush()
    time.sleep(0.18)
