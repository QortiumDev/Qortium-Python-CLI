from __future__ import annotations

from io import StringIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from rich.console import Console

import qortium_cli.ui.console as console_module
import qortium_cli.ui.theme as theme
from qortium_cli.ui import widgets
from qortium_cli.ui.motion import LOADING_EFFECT_OPTIONS, MotionLevel


class LoadingIndicatorTests(TestCase):
    def test_effect_frames_stream_before_the_full_sequence_is_generated(self) -> None:
        consumed: list[int] = []

        class StreamingEffect:
            terminal_config = SimpleNamespace()
            effect_config = SimpleNamespace()

            def __iter__(self):
                for index in range(100):
                    consumed.append(index)
                    yield f"frame {index}"

        with patch.object(
            widgets,
            "_new_loading_effect",
            return_value=StreamingEffect(),
        ):
            frames = widgets._iter_loading_frames(
                "CURRENT SCREEN",
                60,
                20,
                "highlight",
            )
            first = next(frames)

        self.assertEqual(consumed, [0])
        self.assertIn("frame 0", first.plain)

    def test_tte_loading_frames_are_bounded_and_keep_the_current_screen(self) -> None:
        screen = "QORTIUM // COMMAND CONSOLE\nNODE STATUS\n[3] Wallets & Payments"
        frames = widgets._build_loading_frames(
            screen,
            60,
            20,
            "highlight",
        )

        self.assertGreater(len(frames), 1)
        self.assertLessEqual(len(frames), (widgets._LOADING_FRAME_LIMIT * 2) - 2)
        self.assertTrue(all("Wallets & Payments" in frame.plain for frame in frames))
        self.assertTrue(all("COMMAND CONSOLE" in frame.plain for frame in frames))
        self.assertTrue(all("LOADING..." in frame.plain for frame in frames))

    def test_loading_footer_is_centered_on_the_last_terminal_row(self) -> None:
        screen = widgets._screen_with_loading_footer(
            "DASHBOARD\n[3] Wallets & Payments",
            32,
            8,
        )

        lines = screen.splitlines()
        self.assertEqual(len(lines), 8)
        self.assertEqual(lines[-1].strip(), "LOADING...")
        self.assertEqual(len(lines[-1]), 32)

    def test_every_configured_effect_builds_a_full_narrow_screen(self) -> None:
        screen = "QORTIUM\nNODE STATUS\n[3] WALLETS"
        for effect, _, _ in LOADING_EFFECT_OPTIONS:
            with self.subTest(effect=effect):
                frames = widgets._build_loading_frames(
                    screen,
                    32,
                    12,
                    effect,
                )
                self.assertGreater(len(frames), 1)
                for frame in frames:
                    lines = frame.plain.splitlines()
                    self.assertEqual(len(lines), 12)
                    self.assertTrue(all(len(line) <= 32 for line in lines))

    def test_loader_uses_rich_alternate_screen(self) -> None:
        live = MagicMock()
        thread = MagicMock()
        with (
            patch.object(widgets, "Live", return_value=live) as live_type,
            patch.object(widgets.threading, "Thread", return_value=thread),
            patch.object(
                widgets,
                "_build_loading_frames",
                return_value=(MagicMock(),),
            ),
            patch.object(
                widgets,
                "_current_screen_snapshot",
                return_value="CURRENT DASHBOARD",
            ),
        ):
            loader = widgets._TteLoadingIndicator(
                "Loading wallets...",
                "wipe",
            )
            loader.start()
            loader.stop()

        self.assertTrue(live_type.call_args.kwargs["screen"])
        self.assertTrue(live_type.call_args.kwargs["transient"])
        thread.start.assert_called_once_with()
        live.__exit__.assert_called_once_with(None, None, None)

    def test_snapshot_comes_from_the_screen_already_rendered(self) -> None:
        output = StringIO()
        recorded_console = Console(
            file=output,
            width=60,
            height=20,
            color_system="truecolor",
            highlight=False,
            record=True,
        )
        with patch.object(widgets, "console", recorded_console):
            recorded_console.print("[bold cyan]QORTIUM // COMMAND CONSOLE[/]")
            recorded_console.print("[3] Wallets & Payments")

            snapshot = widgets._current_screen_snapshot()

        self.assertIn("QORTIUM // COMMAND CONSOLE", snapshot)
        self.assertIn("[3] Wallets & Payments", snapshot)
        self.assertNotIn("LOADING", snapshot)

    def test_clearing_screen_resets_the_recorded_snapshot(self) -> None:
        recorded_console = Console(
            file=StringIO(),
            width=60,
            height=20,
            color_system=None,
            highlight=False,
            record=True,
        )
        recorded_console.print("OLD SCREEN")

        with (
            patch.object(theme, "console", recorded_console),
            patch.object(console_module.os, "system"),
        ):
            console_module.clear_screen()

        self.assertEqual(recorded_console.export_text(clear=False), "")

    def test_spinner_uses_tte_loader_for_full_motion(self) -> None:
        loader = MagicMock()
        with (
            patch.object(widgets, "motion_level", return_value=MotionLevel.FULL),
            patch.object(
                widgets,
                "_TteLoadingIndicator",
                return_value=loader,
            ) as loader_type,
        ):
            with widgets.spinner("Loading wallets..."):
                pass

        loader_type.assert_called_once_with("Loading wallets...")
        loader.start.assert_called_once_with()
        loader.stop.assert_called_once_with()

    def test_reduced_motion_adds_no_separate_loading_screen(self) -> None:
        with (
            patch.object(
                widgets,
                "motion_level",
                return_value=MotionLevel.REDUCED,
            ),
            patch.object(widgets, "_TteLoadingIndicator") as loader_type,
        ):
            with widgets.spinner("Loading wallets..."):
                pass

        loader_type.assert_not_called()

    def test_spinner_adds_no_loading_ui_when_tte_cannot_start(self) -> None:
        loader = MagicMock()
        loader.start.side_effect = RuntimeError("terminal unavailable")
        with (
            patch.object(widgets, "motion_level", return_value=MotionLevel.FULL),
            patch.object(
                widgets,
                "_TteLoadingIndicator",
                return_value=loader,
            ),
        ):
            with widgets.spinner("Loading wallets..."):
                pass

        loader.stop.assert_called_once_with()

    def test_spinner_preserves_body_exceptions_and_stops_animation(self) -> None:
        loader = MagicMock()
        with (
            patch.object(widgets, "motion_level", return_value=MotionLevel.FULL),
            patch.object(
                widgets,
                "_TteLoadingIndicator",
                return_value=loader,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "request failed"):
                with widgets.spinner("Loading wallets..."):
                    raise RuntimeError("request failed")

        loader.stop.assert_called_once_with()
