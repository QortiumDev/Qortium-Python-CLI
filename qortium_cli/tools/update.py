"""Auto-update tool — check GitHub, install latest, restart."""
from __future__ import annotations

import os
import subprocess
import sys

from qortium_cli.constants import APP_VERSION
from qortium_cli.models import AppContext
from qortium_cli.ui import ok, pause, warn
from qortium_cli.ui.banner import tool_header
from qortium_cli.ui.theme import console
from qortium_cli.ui.widgets import error_panel, ok_panel, spinner, warn_panel
from qortium_cli.update_checker import (
    GITHUB_REPO_URL,
    fetch_github_releases,
    select_update_offers,
)


def _restart() -> None:
    """Replace the current process with a fresh one (in-place restart)."""
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except OSError:
        # Windows fallback: spawn a new process then exit
        subprocess.Popen([sys.executable] + sys.argv)
        sys.exit(0)


def tool_check_for_updates(ctx: AppContext) -> None:
    tool_header("Check for Updates", "↑")

    console.print(f"[qort.dim]Current version:[/] [bold white]{APP_VERSION}[/]\n")

    # 1. Fetch releases
    try:
        with spinner("Checking GitHub for new releases..."):
            releases = fetch_github_releases(timeout_seconds=10)
    except Exception as exc:
        error_panel(str(exc), title="Could not reach GitHub", hint="Check your internet connection.")
        pause()
        return

    offers = select_update_offers(APP_VERSION, releases)

    if not offers:
        ok_panel(f"You are on the latest version ({APP_VERSION}).", title="Up to Date")
        pause()
        return

    # 2. Show available versions
    newest = offers[-1]  # select_update_offers returns stable last
    console.print(f"[bold #b27cff]Available update:[/] [bold white]{newest.tag_name}[/]")
    if newest.is_prerelease:
        console.print("[qort.warn]  (pre-release)[/]")
    console.print(f"[qort.dim]  {newest.html_url}[/]\n")

    if len(offers) > 1:
        for r in offers[:-1]:
            console.print(f"[qort.dim]Also available:[/] [white]{r.tag_name}[/]")
        console.print()

    # 3. Confirm
    console.print("[qort.accent]Install this update? [Y/n]: [/]", end="")
    try:
        answer = input().strip().lower()
    except EOFError:
        answer = "n"

    if answer not in {"", "y", "yes"}:
        warn("Update cancelled.")
        pause()
        return

    # 4. Run pip install
    install_url = f"git+{GITHUB_REPO_URL}.git@{newest.tag_name}"
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", f'"{install_url}"']
    cmd_str = " ".join(cmd)

    console.print(f"\n[qort.dim]Running:[/] [white]{cmd_str}[/]\n")

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", install_url],
            capture_output=False,
            text=True,
        )
    except Exception as exc:
        error_panel(str(exc), title="Install Failed")
        pause()
        return

    if proc.returncode != 0:
        error_panel(
            f"pip exited with code {proc.returncode}.",
            title="Install Failed",
            hint="Try running the install command manually.",
        )
        pause()
        return

    ok_panel(f"Successfully installed {newest.tag_name}.", title="Update Complete")
    console.print()

    # 5. Offer restart
    console.print("[qort.accent]Restart now to apply the update? [Y/n]: [/]", end="")
    try:
        restart_answer = input().strip().lower()
    except EOFError:
        restart_answer = "n"

    if restart_answer in {"", "y", "yes"}:
        console.print("[qort.dim]Restarting...[/]")
        _restart()
    else:
        warn("Restart manually to apply the update.")
        pause()
