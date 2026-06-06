from __future__ import annotations

import os
import sys
import textwrap
import time
from decimal import Decimal, InvalidOperation
from typing import Any, List

from qortium_cli.constants import (
    APP_TITLE,
    BOLD,
    C_ACCENT,
    C_BAD,
    C_CORE,
    C_GOOD,
    C_KEY,
    C_TEXT,
    C_WARN,
    DIM,
    LOGO_GRADIENT,
    QORTIUM_ASCII,
    RESET,
    SETUP_TITLE,
)

try:
    from colorama import init as colorama_init, just_fix_windows_console
except ImportError:
    print("Missing dependency: colorama")
    print("Install with: python -m pip install colorama")
    raise SystemExit(1)


def init_console() -> None:
    colorama_init(autoreset=True)
    just_fix_windows_console()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def rule(width: int = 78) -> None:
    print(DIM + ("-" * width) + RESET)


def pick_vertical_gradient_color(index: int, total: int, palette: List[str]) -> str:
    if not palette:
        return ""
    if total <= 1:
        return palette[0]
    ratio = index / (total - 1)
    palette_index = int(ratio * (len(palette) - 1))
    return palette[palette_index]


def print_logo() -> None:
    lines = textwrap.dedent(QORTIUM_ASCII).strip("\n").splitlines()
    total = max(len(lines), 1)
    for index, line in enumerate(lines):
        color = pick_vertical_gradient_color(index, total, LOGO_GRADIENT)
        print(color + line + RESET)


def startup_splash() -> None:
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
        color = pick_vertical_gradient_color(index, total, LOGO_GRADIENT)
        print(color + line + RESET)
        ratio = index / tail
        time.sleep(0.03 + (0.03 * ratio))

    print(C_ACCENT + BOLD + APP_TITLE + RESET)
    time.sleep(0.18)


def print_banner(base_url: str, title: str) -> None:
    clear_screen()
    print_logo()
    print(C_ACCENT + BOLD + APP_TITLE + RESET)
    print(DIM + f"Node: {base_url}" + RESET)
    print(C_CORE + BOLD + f"[ {title} ]" + RESET)
    rule()


def print_setup_banner(title: str) -> None:
    clear_screen()
    print_logo()
    print(C_ACCENT + BOLD + SETUP_TITLE + RESET)
    print(C_CORE + BOLD + f"[ {title} ]" + RESET)
    rule()


def print_section(title: str) -> None:
    print(C_CORE + BOLD + title + RESET)


def print_stat(label: str, value: Any) -> None:
    print(f"{DIM}- {label}:{RESET} {C_TEXT}{value}{RESET}")


def print_option(key: str, label: str) -> None:
    print(f"{C_KEY}{key}){RESET} {C_TEXT}{label}{RESET}")


def ok(message: str) -> None:
    print(C_GOOD + message + RESET)


def warn(message: str) -> None:
    print(C_WARN + message + RESET)


def error(message: str) -> None:
    print(C_BAD + message + RESET)


def pause() -> None:
    try:
        input(DIM + "\nPress Enter to continue..." + RESET)
    except (EOFError, KeyboardInterrupt):
        pass


def read_menu_choice(prompt: str = "Choose an option: ") -> str:
    try:
        return input(C_TEXT + prompt + RESET).strip()
    except EOFError:
        return "0"


def prompt_str(prompt: str, default: str = "") -> str:
    try:
        value = input(C_TEXT + prompt + RESET).strip()
    except EOFError:
        return default
    return value if value else default


def prompt_secret(prompt: str) -> str:
    return prompt_str(prompt, "").strip()


def prompt_int(prompt: str, default: int, minimum: int = 0) -> int:
    while True:
        raw = prompt_str(prompt, "")
        if raw == "":
            return default
        try:
            value = int(raw)
            if value < minimum:
                warn(f"Value must be >= {minimum}.")
                continue
            return value
        except ValueError:
            warn("Please enter a whole number.")


def prompt_decimal(prompt: str, default: Decimal) -> Decimal:
    while True:
        raw = prompt_str(prompt, "")
        if raw == "":
            return default
        try:
            value = Decimal(raw)
            if value < 0:
                warn("Value must be >= 0.")
                continue
            return value
        except InvalidOperation:
            warn("Please enter a valid number.")


def prompt_yes_no(prompt: str, default_yes: bool = False) -> bool:
    suffix = " [Y/n]: " if default_yes else " [y/N]: "
    while True:
        raw = prompt_str(prompt + suffix, "").lower()
        if raw == "":
            return default_yes
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        warn("Please enter y or n.")


def prompt_multiline_message() -> str:
    print(DIM + "Type your chat message. Type /done on its own line to finish." + RESET)
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "/done":
            break
        lines.append(line)
    return "\n".join(lines).strip()
