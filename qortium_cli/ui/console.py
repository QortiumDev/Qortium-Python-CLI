from __future__ import annotations

import os
import sys


def init_console() -> None:
    """Enable UTF-8 and ANSI without changing terminal dimensions."""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            stdout_handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_int()
            if kernel32.GetConsoleMode(stdout_handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(stdout_handle, mode.value | 0x0004)
        except Exception:
            pass


def clear_screen() -> None:
    try:
        from qortium_cli.ui.theme import console

        if console.record:
            console.export_text(clear=True)
    except (AssertionError, OSError, RuntimeError):
        pass
    os.system("cls" if os.name == "nt" else "clear")
