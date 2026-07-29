"""Bounded TerminalTextEffects animations with accessibility fallbacks."""

from __future__ import annotations

import os
import sys
import json
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import TextIO


class MotionLevel(str, Enum):
    FULL = "full"
    REDUCED = "reduced"
    OFF = "off"


STARTUP_FRAME_STEP = 6
DEFAULT_LOADING_EFFECT = "highlight"
LOADING_EFFECT_ENV = "QORTIUM_CLI_LOADING_EFFECT"
LOADING_EFFECT_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("highlight", "Aurora Highlight", "A smooth light sweep across the loading text"),
    ("decrypt", "Cipher Decode", "Random characters resolve into the loading text"),
    ("wipe", "Gradient Wipe", "A clean directional color reveal"),
    ("slide", "Side Slide", "Characters glide into place from the edges"),
    ("rain", "Digital Rain", "Characters fall into their final positions"),
    ("errorcorrect", "Error Correct", "Glitched text repairs itself on screen"),
)
LOADING_EFFECT_KEYS = frozenset(key for key, _, _ in LOADING_EFFECT_OPTIONS)


@dataclass(frozen=True)
class AppearanceSettings:
    motion: MotionLevel = MotionLevel.FULL
    loading_effect: str = DEFAULT_LOADING_EFFECT


def _appearance_path(settings_dir: Path) -> Path:
    return settings_dir / "appearance.json"


def load_appearance(settings_dir: Path) -> AppearanceSettings:
    try:
        payload = json.loads(_appearance_path(settings_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return AppearanceSettings()
    if not isinstance(payload, dict):
        return AppearanceSettings()
    try:
        level = MotionLevel(str(payload.get("motion", "full")).strip().lower())
    except ValueError:
        level = MotionLevel.FULL
    effect = str(
        payload.get("loading_effect", DEFAULT_LOADING_EFFECT)
        or DEFAULT_LOADING_EFFECT
    ).strip().lower()
    if effect not in LOADING_EFFECT_KEYS:
        effect = DEFAULT_LOADING_EFFECT
    return AppearanceSettings(level, effect)


def save_appearance(settings_dir: Path, settings: AppearanceSettings) -> None:
    settings_dir.mkdir(parents=True, exist_ok=True)
    _appearance_path(settings_dir).write_text(
        json.dumps(
            {
                "motion": settings.motion.value,
                "loading_effect": settings.loading_effect,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def load_saved_motion(settings_dir: Path) -> MotionLevel:
    return load_appearance(settings_dir).motion


def load_saved_loading_effect(settings_dir: Path) -> str:
    return load_appearance(settings_dir).loading_effect


def save_motion(settings_dir: Path, level: MotionLevel) -> None:
    save_appearance(
        settings_dir,
        replace(load_appearance(settings_dir), motion=level),
    )


def save_loading_effect(settings_dir: Path, effect: str) -> None:
    normalized = str(effect or "").strip().lower()
    if normalized not in LOADING_EFFECT_KEYS:
        raise ValueError(f"Unknown loading effect: {effect}")
    save_appearance(
        settings_dir,
        replace(load_appearance(settings_dir), loading_effect=normalized),
    )


def apply_saved_motion(settings_dir: Path) -> MotionLevel:
    appearance = load_appearance(settings_dir)
    os.environ.setdefault("QORTIUM_CLI_MOTION", appearance.motion.value)
    os.environ.setdefault(LOADING_EFFECT_ENV, appearance.loading_effect)
    return appearance.motion


def loading_effect() -> str:
    requested = os.environ.get(
        LOADING_EFFECT_ENV,
        DEFAULT_LOADING_EFFECT,
    ).strip().lower()
    return requested if requested in LOADING_EFFECT_KEYS else DEFAULT_LOADING_EFFECT


def motion_level(stream: TextIO = sys.stdout) -> MotionLevel:
    """Return the effective motion level for the current terminal."""

    requested = os.environ.get("QORTIUM_CLI_MOTION", "full").strip().lower()
    if requested not in {level.value for level in MotionLevel}:
        requested = MotionLevel.FULL.value

    terminal = os.environ.get("TERM", "").strip().lower()
    disabled = (
        os.environ.get("QORTIUM_CLI_NO_ANIM") == "1"
        or os.environ.get("NO_COLOR") is not None
        or os.environ.get("CI") is not None
        or terminal == "dumb"
        or not getattr(stream, "isatty", lambda: False)()
    )
    if disabled:
        return MotionLevel.OFF
    return MotionLevel(requested)


def _play(effect: object, *, frame_step: int = 1) -> bool:
    try:
        terminal_output = getattr(effect, "terminal_output")
        with terminal_output() as terminal:
            step = max(1, int(frame_step))
            last_frame: str | None = None
            last_printed: str | None = None
            for index, frame in enumerate(effect):  # type: ignore[operator]
                last_frame = frame
                if index % step == 0:
                    terminal.print(frame)
                    last_printed = frame
            if last_frame is not None and last_frame != last_printed:
                terminal.print(last_frame)
        return True
    except (ImportError, OSError, RuntimeError, UnicodeError, ValueError):
        return False


def _center_on_terminal(effect: object) -> None:
    """Center an effect's text on the terminal-sized TTE canvas."""

    terminal_config = getattr(effect, "terminal_config")
    terminal_config.canvas_width = 0
    terminal_config.canvas_height = 0
    terminal_config.anchor_canvas = "c"
    terminal_config.anchor_text = "c"


def play_startup(text: str, *, stream: TextIO = sys.stdout) -> bool:
    """Reveal the brand with TTE's Decrypt effect."""

    if motion_level(stream) is MotionLevel.OFF:
        return False
    try:
        from terminaltexteffects.effects.effect_decrypt import Decrypt
        from terminaltexteffects.utils.graphics import Color, Gradient

        effect = Decrypt(text)
        _center_on_terminal(effect)
        effect.effect_config.typing_speed = 4
        effect.effect_config.ciphertext_colors = (
            Color("#29d3ff"),
            Color("#7c5cff"),
            Color("#d98cff"),
        )
        effect.effect_config.final_gradient_stops = (
            Color("#29d3ff"),
            Color("#8d6bff"),
            Color("#f1a7ff"),
        )
        effect.effect_config.final_gradient_steps = 10
        effect.effect_config.final_gradient_direction = Gradient.Direction.HORIZONTAL
        return _play(effect, frame_step=STARTUP_FRAME_STEP)
    except (ImportError, AttributeError, TypeError, ValueError):
        return False
