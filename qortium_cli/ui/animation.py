"""Dependency-free player for Bash-style ANSI animation exports."""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import TextIO


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
FRAME_DEF_RE = re.compile(r"^(frame\d+)\(\)\s*\{$")
FRAME_CALL_RE = re.compile(r"^(frame\d+);$")
SLEEP_RE = re.compile(r"^sleep\s+([0-9.]+);$")
BLOCK_CHARS = ("\u2580", "\u2584", "\u2588", "\u2591", "\u2592", "\u2593")


def _repair_mojibake(text: str) -> str:
    original_score = sum(text.count(char) for char in BLOCK_CHARS)
    best = text
    best_score = original_score

    for encoding in ("cp1252", "latin1"):
        try:
            candidate = text.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        score = sum(candidate.count(char) for char in BLOCK_CHARS)
        if score > best_score:
            best = candidate
            best_score = score

    return best


def _decode_ansi(text: str) -> str:
    normalized = text.replace("\\e", "\x1b").replace("\\033", "\x1b")
    return _repair_mojibake(normalized)


def load_ansi_animation(path: Path) -> tuple[dict[str, str], list[tuple[str, float]]]:
    """Parse frame definitions and one loop schedule from an exported script."""

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    frames: dict[str, str] = {}
    schedule: list[tuple[str, float]] = []

    frame_name: str | None = None
    collecting = False
    frame_lines: list[str] = []
    in_loop = False
    pending_index = -1

    for raw in lines:
        line = raw.rstrip("\r\n")
        stripped = line.strip()

        frame_match = FRAME_DEF_RE.match(stripped)
        if frame_match:
            frame_name = frame_match.group(1)
            collecting = False
            frame_lines = []
            continue

        if frame_name and not collecting and stripped.startswith('printf "'):
            collecting = True
            frame_lines = [line.split('printf "', 1)[1]]
            continue

        if frame_name and collecting:
            if stripped == '";':
                frames[frame_name] = _decode_ansi("\n".join(frame_lines))
                frame_name = None
                collecting = False
                continue
            frame_lines.append(line)
            continue

        if stripped == "while true; do":
            in_loop = True
            continue

        if in_loop and stripped == "done":
            break

        if not in_loop:
            continue

        call_match = FRAME_CALL_RE.match(stripped)
        if call_match:
            schedule.append((call_match.group(1), 0.07))
            pending_index = len(schedule) - 1
            continue

        sleep_match = SLEEP_RE.match(stripped)
        if sleep_match and pending_index >= 0:
            frame, _ = schedule[pending_index]
            schedule[pending_index] = (frame, float(sleep_match.group(1)))

    if collecting:
        raise ValueError("Unterminated frame definition")
    if not frames:
        raise ValueError("No frame definitions found")
    if not schedule:
        raise ValueError("No playback schedule found")

    missing = sorted({name for name, _ in schedule if name not in frames})
    if missing:
        raise ValueError("Scheduled frames are missing definitions: " + ", ".join(missing))

    return frames, schedule


def _visible_size(frame: str) -> tuple[int, int]:
    lines = frame.splitlines()
    widths = [len(ANSI_ESCAPE_RE.sub("", line)) for line in lines]
    return (max(widths, default=0), len(lines))


def _trim_vertical_blank_rows(frame: str) -> str:
    lines = frame.splitlines()
    nonblank = [
        index
        for index, line in enumerate(lines)
        if ANSI_ESCAPE_RE.sub("", line).strip()
    ]
    if not nonblank:
        return frame
    return "\n".join(lines[nonblank[0] : nonblank[-1] + 1])


def _center_frame(frame: str, columns: int, rows: int) -> str:
    trimmed = _trim_vertical_blank_rows(frame)
    frame_lines = trimmed.splitlines()
    width, height = _visible_size(trimmed)
    left = " " * max(0, (columns - width) // 2)
    top = "\n" * min(2, max(0, (rows - height) // 2))
    return top + "\n".join(left + line for line in frame_lines)


def _enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        stdout_handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_int()
        if kernel32.GetConsoleMode(stdout_handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(stdout_handle, mode.value | 0x0004)
    except Exception:
        pass


def play_ansi_animation(
    path: Path,
    *,
    stream: TextIO = sys.stdout,
    disable_env: str | None = None,
    center: bool = True,
) -> bool:
    """Play one animation cycle, returning False when fallback should be used."""

    if disable_env and str(os.environ.get(disable_env, "") or "").strip() == "1":
        return False
    if not path.is_file() or not getattr(stream, "isatty", lambda: False)():
        return False

    try:
        frames, schedule = load_ansi_animation(path)
    except (OSError, UnicodeError, ValueError):
        return False

    _enable_windows_ansi()
    cursor_hidden = False
    try:
        stream.write("\x1b[2J\x1b[H\x1b[?25l")
        stream.flush()
        cursor_hidden = True

        for frame_name, delay in schedule:
            frame = frames[frame_name]
            if center:
                terminal = shutil.get_terminal_size(fallback=(80, 24))
                frame = _center_frame(frame, terminal.columns, terminal.lines)
            stream.write("\x1b[2J\x1b[H")
            stream.write(frame)
            stream.write("\x1b[0m")
            stream.flush()
            time.sleep(max(0.0, delay))

        return True
    except (OSError, UnicodeError, ValueError):
        return False
    finally:
        if cursor_hidden:
            try:
                stream.write("\x1b[0m\x1b[?25h")
                stream.flush()
            except Exception:
                pass
