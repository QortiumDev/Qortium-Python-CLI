"""CLI connection, account, and appearance settings."""

from __future__ import annotations

import os

from qortium_cli.models import AppContext
from qortium_cli.ui import ok, pause, read_menu_choice, warn
from qortium_cli.ui.menu import MenuOption, run_menu
from qortium_cli.ui.motion import (
    LOADING_EFFECT_ENV,
    LOADING_EFFECT_OPTIONS,
    MotionLevel,
    load_saved_loading_effect,
    save_loading_effect,
    save_motion,
)


def _connection_and_account(ctx: AppContext) -> None:
    from qortium_cli.setup_wizard import configure_first_run_files

    configure_first_run_files(ctx, force=True)


def _motion(ctx: AppContext) -> None:
    print()
    print("1) Full     — startup and feature transitions")
    print("2) Reduced  — startup animation only")
    print("3) Off      — static interface")
    print("0) Cancel")
    choice = read_menu_choice("Motion level: ")
    levels = {
        "1": MotionLevel.FULL,
        "2": MotionLevel.REDUCED,
        "3": MotionLevel.OFF,
    }
    if choice == "0":
        return
    level = levels.get(choice)
    if level is None:
        warn("Unknown motion level.")
        pause()
        return
    save_motion(ctx.settings_dir, level)
    os.environ["QORTIUM_CLI_MOTION"] = level.value
    ok(f"Motion set to {level.value}.")
    pause()


def _loading_effect(ctx: AppContext) -> None:
    current = load_saved_loading_effect(ctx.settings_dir)
    print()
    for index, (key, label, description) in enumerate(
        LOADING_EFFECT_OPTIONS,
        start=1,
    ):
        marker = "  < current" if key == current else ""
        print(f"{index}) {label}{marker}")
        print(f"   {description}")
    print("0) Cancel")
    choice = read_menu_choice("Loading effect: ")
    if choice == "0":
        return
    try:
        effect, label, _ = LOADING_EFFECT_OPTIONS[int(choice) - 1]
    except (ValueError, IndexError):
        warn("Unknown loading effect.")
        pause()
        return
    save_loading_effect(ctx.settings_dir, effect)
    os.environ[LOADING_EFFECT_ENV] = effect
    ok(f"Loading effect set to {label}.")
    pause()


def open_settings(ctx: AppContext) -> None:
    run_menu(
        ctx,
        title="Settings",
        subtitle="Connection and identity affect Core access; appearance affects only this CLI.",
        options=(
            MenuOption(
                "1",
                "Connection & account",
                "Endpoint, timeout, API key, and active account",
                _connection_and_account,
            ),
            MenuOption(
                "2",
                "Motion level",
                "Full, reduced, or static TerminalTextEffects presentation",
                _motion,
            ),
            MenuOption(
                "3",
                "Loading effect",
                "Choose the full-screen effect used while operations load",
                _loading_effect,
            ),
        ),
    )
