from __future__ import annotations

import os
import sys


MIN_COLS = 130
MIN_LINES = 45


def init_console() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    if os.name == "nt":
        try:
            import ctypes
            import ctypes.wintypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            stdout_handle = kernel32.GetStdHandle(-11)

            # Enable ANSI escape processing
            mode = ctypes.c_int()
            if kernel32.GetConsoleMode(stdout_handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(stdout_handle, mode.value | 0x0004)

            # Ensure the window is at least MIN_COLS × MIN_LINES
            # Must set buffer size >= window size first to avoid errors
            class COORD(ctypes.Structure):
                _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

            class SMALL_RECT(ctypes.Structure):
                _fields_ = [
                    ("Left", ctypes.c_short), ("Top", ctypes.c_short),
                    ("Right", ctypes.c_short), ("Bottom", ctypes.c_short),
                ]

            class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
                _fields_ = [
                    ("dwSize", COORD),
                    ("dwCursorPosition", COORD),
                    ("wAttributes", ctypes.c_ushort),
                    ("srWindow", SMALL_RECT),
                    ("dwMaximumWindowSize", COORD),
                ]

            info = CONSOLE_SCREEN_BUFFER_INFO()
            if kernel32.GetConsoleScreenBufferInfo(stdout_handle, ctypes.byref(info)):
                cur_cols = info.dwSize.X
                cur_lines = info.srWindow.Bottom - info.srWindow.Top + 1
                max_cols = info.dwMaximumWindowSize.X
                max_lines = info.dwMaximumWindowSize.Y

                new_cols = min(max(cur_cols, MIN_COLS), max_cols)
                new_lines = min(max(cur_lines, MIN_LINES), max_lines)

                if new_cols > cur_cols or new_lines > cur_lines:
                    # Expand buffer first
                    buf = COORD(new_cols, max(info.dwSize.Y, new_lines + 100))
                    kernel32.SetConsoleScreenBufferSize(stdout_handle, buf)
                    # Then resize window
                    win = SMALL_RECT(0, 0, new_cols - 1, new_lines - 1)
                    kernel32.SetConsoleWindowInfo(stdout_handle, True, ctypes.byref(win))
        except Exception:
            pass


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")
