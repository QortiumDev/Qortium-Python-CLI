"""Best-effort native clipboard writes without a runtime dependency."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def copy_text(text: str) -> bool:
    value = str(text)
    if not value:
        return False

    if os.name == "nt":
        command = ["clip.exe"]
    elif sys.platform == "darwin":
        command = ["pbcopy"]
    else:
        command = []
        for candidate in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            if shutil.which(candidate[0]):
                command = candidate
                break
        if not command:
            return False

    try:
        subprocess.run(
            command,
            input=value,
            text=True,
            check=True,
            timeout=5,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt"
                else 0
            ),
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
