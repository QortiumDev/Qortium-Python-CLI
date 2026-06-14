from __future__ import annotations

from decimal import Decimal, InvalidOperation

import sys

from qortium_cli.constants import C_ACCENT, C_BAD, C_GOOD, C_TEXT, C_WARN, DIM, RESET


def _p(text: str) -> None:
    """Write text to sys.stdout, safely handling narrow console encodings."""
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", "ascii") or "ascii"
        safe = text.encode(enc, errors="replace").decode(enc)
        sys.stdout.write(safe)
        sys.stdout.flush()


def _prompt(text: str) -> str:
    _p(C_TEXT + text + RESET)
    try:
        return input().strip()
    except EOFError:
        return ""


def ok(message: str) -> None:
    _p(C_GOOD + "✓ " + message + RESET + "\n")


def warn(message: str) -> None:
    _p(C_WARN + "⚠ " + message + RESET + "\n")


def error(message: str) -> None:
    _p(C_BAD + "✗ " + message + RESET + "\n")


def pause() -> None:
    try:
        _p("\n" + DIM + "Press Enter to continue..." + RESET)
        input()
    except (EOFError, KeyboardInterrupt):
        pass


def read_menu_choice(prompt: str = "Choose an option: ") -> str:
    try:
        _p(C_ACCENT + (prompt or "Choose: ") + RESET)
        return input().strip()
    except EOFError:
        return "0"


def prompt_str(prompt: str, default: str = "") -> str:
    value = _prompt(prompt)
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
    console.print("[qort.dim]Type your message. Type /done on its own line to finish.[/]")
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
