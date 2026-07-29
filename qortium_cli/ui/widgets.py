from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Generator, Iterator

from rich.columns import Columns
from rich.live import Live
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from qortium_cli.ui.motion import MotionLevel, loading_effect, motion_level
from qortium_cli.ui.theme import console

_POW_SPINNER = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
_STEP_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

STEP_LABELS = ["Building", "PoW Nonce", "Signing", "Broadcasting"]
_STEP_NUMS = ["①", "②", "③", "④"]


# ---------------------------------------------------------------------------
# Generic spinner context manager
# ---------------------------------------------------------------------------


_LOADING_FRAME_LIMIT = 36
_LOADING_FRAME_SECONDS = 0.055
_LOADING_FRAME_STRIDES = {
    "highlight": 3,
    "decrypt": 8,
    "wipe": 3,
    "slide": 5,
    "rain": 8,
    "errorcorrect": 8,
}


def _current_screen_snapshot() -> str:
    """Return the Rich-rendered content currently visible in the terminal."""

    if not console.record:
        return ""
    try:
        rendered = console.export_text(clear=False, styles=True)
    except (AssertionError, OSError, RuntimeError):
        return ""
    lines = rendered.rstrip("\n").splitlines()
    if not lines:
        return ""
    return "\n".join(lines[-max(6, console.height) :])


def _screen_with_loading_footer(screen: str, width: int, height: int) -> str:
    canvas_width = max(12, int(width))
    canvas_height = max(6, int(height))
    content = screen.rstrip("\n").splitlines()[: canvas_height - 1]
    content.extend("" for _ in range((canvas_height - 1) - len(content)))
    return "\n".join((*content, "LOADING...".center(canvas_width)))


def _new_loading_effect(effect_name: str, text: str) -> object:
    if effect_name == "decrypt":
        from terminaltexteffects.effects.effect_decrypt import Decrypt

        return Decrypt(text)
    if effect_name == "wipe":
        from terminaltexteffects.effects.effect_wipe import Wipe

        return Wipe(text)
    if effect_name == "slide":
        from terminaltexteffects.effects.effect_slide import Slide

        return Slide(text)
    if effect_name == "rain":
        from terminaltexteffects.effects.effect_rain import Rain

        return Rain(text)
    if effect_name == "errorcorrect":
        from terminaltexteffects.effects.effect_errorcorrect import ErrorCorrect

        return ErrorCorrect(text)

    from terminaltexteffects.effects.effect_highlight import Highlight

    return Highlight(text)


def _iter_loading_frames(
    screen: str,
    width: int,
    height: int,
    effect_name: str,
) -> Iterator[Text]:
    """Yield TTE frames as they are generated to minimize first-frame latency."""

    from terminaltexteffects.utils.graphics import Color, Gradient

    effect = _new_loading_effect(
        effect_name,
        _screen_with_loading_footer(screen, width, height),
    )
    terminal_config = getattr(effect, "terminal_config")
    terminal_config.canvas_width = max(12, int(width))
    terminal_config.canvas_height = max(6, int(height))
    terminal_config.anchor_canvas = "sw"
    terminal_config.anchor_text = "nw"
    terminal_config.frame_rate = 0

    effect_config = getattr(effect, "effect_config")
    gradient = (
        Color("#29d3ff"),
        Color("#8d6bff"),
        Color("#f1a7ff"),
    )
    if hasattr(effect_config, "final_gradient_stops"):
        effect_config.final_gradient_stops = gradient
    if hasattr(effect_config, "final_gradient_steps"):
        effect_config.final_gradient_steps = 10
    if hasattr(effect_config, "final_gradient_direction"):
        effect_config.final_gradient_direction = Gradient.Direction.HORIZONTAL
    if hasattr(effect_config, "ciphertext_colors"):
        effect_config.ciphertext_colors = gradient
    if hasattr(effect_config, "typing_speed"):
        effect_config.typing_speed = 12
    if hasattr(effect_config, "highlight_brightness"):
        effect_config.highlight_brightness = 2.0
    if hasattr(effect_config, "highlight_width"):
        effect_config.highlight_width = 5

    stride = _LOADING_FRAME_STRIDES.get(effect_name, 4)
    emitted = 0
    for index, frame in enumerate(effect):
        if index % stride == 0:
            yield Text.from_ansi(frame.rstrip("\n"))
            emitted += 1
        if emitted >= _LOADING_FRAME_LIMIT:
            return


def _build_loading_frames(
    screen: str,
    width: int,
    height: int,
    effect_name: str,
) -> tuple[Text, ...]:
    """Collect one bounded loop for tests and non-live consumers."""

    sampled = tuple(
        _iter_loading_frames(screen, width, height, effect_name)
    )
    loop = (*sampled, *sampled[-2:0:-1]) if len(sampled) > 2 else sampled
    return tuple(loop)


class _TteLoadingIndicator:
    def __init__(self, message: str, effect_name: str | None = None) -> None:
        self.message = message
        self.effect_name = effect_name or loading_effect()
        self.screen = _current_screen_snapshot()
        if not self.screen.strip():
            raise RuntimeError("No current screen is available to animate.")
        self._dimensions = (max(12, console.width), max(6, console.height))
        self._initial_frame = Text.from_ansi(
            _screen_with_loading_footer(self.screen, *self._dimensions)
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._live: Live | None = None
        self._record_was_enabled = console.record

    def start(self) -> None:
        console.record = False
        self._live = Live(
            self._initial_frame,
            console=console,
            refresh_per_second=20,
            transient=True,
            screen=True,
            vertical_overflow="crop",
        )
        self._live.__enter__()

        def _animate() -> None:
            while not self._stop.is_set():
                try:
                    dimensions = (
                        max(12, console.width),
                        max(6, console.height),
                    )
                    self._dimensions = dimensions
                    forward_frames: list[Text] = []
                    resized = False
                    for frame in _iter_loading_frames(
                        self.screen,
                        *dimensions,
                        self.effect_name,
                    ):
                        if self._stop.is_set():
                            return
                        current_dimensions = (
                            max(12, console.width),
                            max(6, console.height),
                        )
                        if current_dimensions != dimensions:
                            resized = True
                            break
                        forward_frames.append(frame)
                        if self._live is not None:
                            self._live.update(frame, refresh=True)
                        self._stop.wait(_LOADING_FRAME_SECONDS)
                    if resized:
                        continue
                    if not forward_frames:
                        self._stop.set()
                        return
                    for frame in reversed(forward_frames[1:-1]):
                        if self._stop.is_set():
                            return
                        current_dimensions = (
                            max(12, console.width),
                            max(6, console.height),
                        )
                        if current_dimensions != dimensions:
                            resized = True
                            break
                        if self._live is not None:
                            self._live.update(frame, refresh=True)
                        self._stop.wait(_LOADING_FRAME_SECONDS)
                    if resized:
                        continue
                except (
                    AttributeError,
                    ImportError,
                    IndexError,
                    OSError,
                    RuntimeError,
                    TypeError,
                    UnicodeError,
                    ValueError,
                ):
                    self._stop.set()
                    return

        self._thread = threading.Thread(
            target=_animate,
            name="qortium-tte-loading",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            try:
                self._thread.join(timeout=0.5)
            except RuntimeError:
                pass
        if self._live is not None:
            try:
                self._live.__exit__(None, None, None)
            except (OSError, RuntimeError, UnicodeError, ValueError):
                pass
            self._live = None
        console.record = self._record_was_enabled


@contextmanager
def spinner(message: str) -> Generator[None, None, None]:
    loader: _TteLoadingIndicator | None = None
    if motion_level(console.file) is MotionLevel.FULL:
        try:
            loader = _TteLoadingIndicator(message)
            loader.start()
        except (
            AttributeError,
            ImportError,
            OSError,
            RuntimeError,
            TypeError,
            UnicodeError,
            ValueError,
        ):
            if loader is not None:
                loader.stop()
            loader = None

    if loader is not None:
        try:
            yield
        finally:
            loader.stop()
        return

    yield


# ---------------------------------------------------------------------------
# TX Pipeline — 4-step live progress display
# ---------------------------------------------------------------------------

class TxPipeline:
    """Live 4-step transaction progress panel."""

    def __init__(self, tx_type: str) -> None:
        self.tx_type = tx_type
        self._states: list[str] = ["pending"] * 4  # pending | running | done | error
        self._elapsed: list[float] = [0.0] * 4
        self._start: list[float | None] = [None] * 4
        self._frame = 0
        self._pow_thread: threading.Thread | None = None
        self._pow_stop = threading.Event()

    # --- rendering ----------------------------------------------------------

    def _render(self) -> Panel:
        self._frame += 1
        sp_pow = _POW_SPINNER[self._frame % len(_POW_SPINNER)]
        sp_gen = _STEP_SPINNER[self._frame % len(_STEP_SPINNER)]

        t = Text()
        t.append("\n")
        for i, (num, label, state) in enumerate(
            zip(_STEP_NUMS, STEP_LABELS, self._states)
        ):
            pad = f"{label:<16}"
            if state == "pending":
                t.append(f"  {num} {pad}", style="dim")
                t.append("[ waiting...  ]\n", style="dim")
            elif state == "running":
                spinner_char = sp_pow if i == 1 else sp_gen
                elapsed = self._elapsed[i]
                t.append(f"  {num} {pad}", style="bold #dca8ff")
                if i == 1:
                    t.append(f"{spinner_char} Computing...  ", style="bold #b27cff")
                    t.append(f"{elapsed:5.1f}s\n", style="bold #9458e5")
                else:
                    t.append(f"{spinner_char} Working...\n", style="bold #b27cff")
            elif state == "done":
                elapsed = self._elapsed[i]
                t.append(f"  {num} {pad}", style="bold white")
                t.append("✓", style="bold green")
                t.append(f"  {elapsed:.1f}s\n", style="dim")
            elif state == "error":
                t.append(f"  {num} {pad}", style="bold red")
                t.append("✗  Failed\n", style="bold red")
        t.append("\n")

        # footer
        done_count = self._states.count("done")
        has_error = "error" in self._states
        if has_error:
            footer = Text("  Transaction failed", style="bold red")
        elif done_count == 4:
            footer = Text("  ✓ Transaction sent", style="bold green")
        else:
            footer = Text(f"  Step {done_count + 1} of 4...", style="dim")

        group = Text.assemble(t, footer, "\n")
        return Panel(
            group,
            title=f"[bold #b27cff]⬡  {self.tx_type}[/]",
            border_style="#7848cc",
            padding=(0, 1),
        )

    # --- step control -------------------------------------------------------

    def start(self, step: int) -> None:
        self._states[step] = "running"
        self._start[step] = time.monotonic()
        if step == 1:
            self._pow_stop.clear()

            def _tick() -> None:
                while not self._pow_stop.wait(0.05):
                    if self._start[1] is not None:
                        self._elapsed[1] = time.monotonic() - self._start[1]

            self._pow_thread = threading.Thread(target=_tick, daemon=True)
            self._pow_thread.start()

    def finish(self, step: int, ok: bool = True) -> None:
        if step == 1:
            self._pow_stop.set()
            if self._pow_thread:
                self._pow_thread.join(timeout=0.5)
        self._states[step] = "done" if ok else "error"
        if self._start[step] is not None:
            self._elapsed[step] = time.monotonic() - self._start[step]

    # --- context manager usage ----------------------------------------------

    def run(self) -> "_PipelineRunner":
        return _PipelineRunner(self)


class _PipelineRunner:
    def __init__(self, pipeline: TxPipeline) -> None:
        self._p = pipeline
        self._live: Live | None = None

    def __enter__(self) -> "TxPipeline":
        self._live = Live(
            self._p._render(),
            console=console,
            refresh_per_second=10,
            transient=False,
        )
        self._live.__enter__()
        self._live.update(self._p._render())
        self._p._live_ref = self._live
        return self._p

    def __exit__(self, *args: object) -> None:
        if self._live:
            self._live.update(self._p._render())
            self._live.__exit__(*args)


# Patch TxPipeline to update live on every state change
_orig_start = TxPipeline.start
_orig_finish = TxPipeline.finish


def _patched_start(self: TxPipeline, step: int) -> None:
    _orig_start(self, step)
    if hasattr(self, "_live_ref") and self._live_ref is not None:
        self._live_ref.update(self._render())


def _patched_finish(self: TxPipeline, step: int, ok: bool = True) -> None:
    _orig_finish(self, step, ok)
    if hasattr(self, "_live_ref") and self._live_ref is not None:
        self._live_ref.update(self._render())


TxPipeline.start = _patched_start  # type: ignore[method-assign]
TxPipeline.finish = _patched_finish  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Result panels
# ---------------------------------------------------------------------------

def ok_panel(message: str, title: str = "Success") -> None:
    console.print(
        Panel(
            f"[bold green]✓[/]  {message}",
            title=f"[bold green]{title}[/]",
            border_style="green",
        )
    )


def warn_panel(message: str, title: str = "Warning") -> None:
    console.print(
        Panel(
            f"[bold yellow]⚠[/]  {message}",
            title=f"[bold yellow]{title}[/]",
            border_style="yellow",
        )
    )


def error_panel(message: str, title: str = "Error", hint: str = "") -> None:
    body = f"[bold red]✗[/]  {message}"
    if hint:
        body += f"\n\n[dim]{hint}[/]"
    console.print(
        Panel(body, title=f"[bold red]{title}[/]", border_style="red")
    )


# ---------------------------------------------------------------------------
# Data display helpers
# ---------------------------------------------------------------------------

def stat_table(rows: list[tuple[str, str]]) -> Table:
    t = Table.grid(padding=(0, 2))
    t.add_column(justify="right", style="dim")
    t.add_column(style="white")
    for label, value in rows:
        t.add_row(label + ":", value)
    return t


def data_table(
    headers: list[str],
    rows: list[list[str]],
    *,
    border_style: str = "#5a3cb0",
    header_style: str = "bold #b27cff",
) -> Table:
    t = Table(border_style=border_style, header_style=header_style, show_lines=False)
    for h in headers:
        t.add_column(h)
    for row in rows:
        # Alternate row shading
        style = "dim" if rows.index(row) % 2 == 0 else ""
        t.add_row(*row, style=style)
    return t


def json_panel(data: str | dict, title: str = "Response") -> None:
    import json as _json
    if isinstance(data, dict):
        data = _json.dumps(data, indent=2)
    console.print(
        Panel(
            Syntax(data, "json", theme="monokai", word_wrap=True),
            title=f"[qort.heading]{title}[/]",
            border_style="#5a3cb0",
        )
    )


def bool_str(value: bool) -> str:
    return "[green]● Yes[/]" if value else "[red]● No[/]"


def balance_str(value: str) -> str:
    try:
        f = float(value)
        if f > 0:
            return f"[bold green]{value}[/]"
        return f"[dim]{value}[/]"
    except (ValueError, TypeError):
        return str(value)


def addr_short(address: str, keep: int = 12) -> str:
    if len(address) <= keep * 2 + 3:
        return address
    return address[:keep] + "…" + address[-keep:]


def height_str(height: int | str) -> str:
    try:
        return f"[bold #b27cff]{int(height):,}[/]"
    except (ValueError, TypeError):
        return str(height)
