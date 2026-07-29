from __future__ import annotations

import io
import sys

from rich.console import Console
from rich.theme import Theme


def _utf8_stdout() -> object:
    """Return stdout wrapped in UTF-8 with error replacement, if possible."""
    if hasattr(sys.stdout, "buffer"):
        try:
            return io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass
    return sys.stdout


def _utf8_stderr() -> object:
    if hasattr(sys.stderr, "buffer"):
        try:
            return io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass
    return sys.stderr

GRADIENT_COLORS = [
    "#e8d0ff",
    "#d6b0ff",
    "#c490ff",
    "#ae70f7",
    "#9458e5",
    "#7848cc",
    "#5a3cb0",
]

CHAT_USER_HEX = [
    "#ff7a7a",
    "#ffa64d",
    "#ffd666",
    "#96e277",
    "#58dcb0",
    "#60d4ff",
    "#68aaff",
    "#8a84ff",
    "#b87eff",
    "#ec88ff",
    "#ff92ce",
    "#b6c0d0",
]

QORT_THEME = Theme(
    {
        "qort.heading": "bold #b27cff",
        "qort.accent": "bold #dca8ff",
        "qort.key": "bold yellow",
        "qort.good": "bold green",
        "qort.warn": "bold yellow",
        "qort.bad": "bold red",
        "qort.dim": "dim white",
        "qort.text": "white",
        "qort.muted": "dim #9090a0",
        "qort.grad0": "bold #e8d0ff",
        "qort.grad1": "bold #d6b0ff",
        "qort.grad2": "bold #c490ff",
        "qort.grad3": "bold #ae70f7",
        "qort.grad4": "bold #9458e5",
        "qort.grad5": "bold #7848cc",
        "qort.grad6": "bold #5a3cb0",
        "qort.panel": "#5a3cb0",
        "qort.border": "#7848cc",
    }
)

console = Console(
    file=_utf8_stdout(),  # type: ignore[arg-type]
    theme=QORT_THEME,
    highlight=False,
    legacy_windows=False,
    record=True,
)
err_console = Console(
    file=_utf8_stderr(),  # type: ignore[arg-type]
    stderr=True,
    theme=QORT_THEME,
    highlight=False,
    legacy_windows=False,
)
