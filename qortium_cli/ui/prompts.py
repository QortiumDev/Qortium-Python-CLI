from __future__ import annotations

from decimal import Decimal, InvalidOperation
from getpass import getpass

import os
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


def _windows_clipboard_text() -> str:
    """Read Unicode clipboard text without adding a runtime dependency."""

    try:
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalLock.restype = ctypes.c_void_p

        if not user32.OpenClipboard(None):
            return ""
        try:
            handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
            if not handle:
                return ""
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return ""
            try:
                return ctypes.wstring_at(pointer)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except (AttributeError, OSError, TypeError, ValueError):
        return ""


def _windows_secret_input(prompt: str) -> str:
    """Hidden Windows input with explicit Ctrl+V clipboard support."""

    import msvcrt

    _p(prompt)
    characters: list[str] = []
    while True:
        char = msvcrt.getwch()
        if char in {"\r", "\n"}:
            _p("\n")
            return "".join(characters).strip()
        if char == "\x03":
            _p("\n")
            raise KeyboardInterrupt
        if char == "\b":
            if characters:
                characters.pop()
            continue
        if char == "\x16":
            pasted = _windows_clipboard_text().strip()
            characters.extend(
                value
                for value in pasted
                if ord(value) >= 32 and ord(value) != 127
            )
            continue
        if char in {"\x00", "\xe0"}:
            msvcrt.getwch()
            continue
        if ord(char) < 32 or ord(char) == 127:
            continue
        characters.append(char)


def prompt_secret(prompt: str) -> str:
    try:
        if os.name == "nt" and getattr(sys.stdin, "isatty", lambda: False)():
            return _windows_secret_input(prompt)
        return getpass(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


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
