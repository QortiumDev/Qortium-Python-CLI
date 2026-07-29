from __future__ import annotations

from contextlib import contextmanager
from unittest import TestCase

from qortium_cli.ui.motion import STARTUP_FRAME_STEP, _center_on_terminal, _play


class _Terminal:
    def __init__(self) -> None:
        self.frames: list[str] = []

    def print(self, frame: str) -> None:
        self.frames.append(frame)


class _Effect:
    def __init__(self, frames: list[str]) -> None:
        self.frames = frames
        self.terminal = _Terminal()
        self.terminal_config = type(
            "TerminalConfig",
            (),
            {
                "canvas_width": -1,
                "canvas_height": -1,
                "anchor_canvas": "sw",
                "anchor_text": "sw",
            },
        )()

    def __iter__(self):
        return iter(self.frames)

    @contextmanager
    def terminal_output(self):
        yield self.terminal


class MotionPlaybackTests(TestCase):
    def test_startup_uses_six_frame_step(self) -> None:
        self.assertEqual(STARTUP_FRAME_STEP, 6)

    def test_fast_playback_renders_every_sixth_frame_and_final_state(self) -> None:
        effect = _Effect(
            [
                "frame-0",
                "frame-1",
                "frame-2",
                "frame-3",
                "frame-4",
                "frame-5",
                "frame-6",
                "frame-7",
            ]
        )

        self.assertTrue(_play(effect, frame_step=6))

        self.assertEqual(
            effect.terminal.frames,
            ["frame-0", "frame-6", "frame-7"],
        )

    def test_normal_playback_keeps_every_frame(self) -> None:
        effect = _Effect(["frame-0", "frame-1", "frame-2"])

        self.assertTrue(_play(effect))

        self.assertEqual(effect.terminal.frames, effect.frames)

    def test_startup_centers_text_on_terminal_sized_canvas(self) -> None:
        effect = _Effect(["frame"])

        _center_on_terminal(effect)

        self.assertEqual(effect.terminal_config.canvas_width, 0)
        self.assertEqual(effect.terminal_config.canvas_height, 0)
        self.assertEqual(effect.terminal_config.anchor_canvas, "c")
        self.assertEqual(effect.terminal_config.anchor_text, "c")
