"""Multi-state spinner widget ΓÇö braille animation with stall detection and shimmer."""

from __future__ import annotations

import time
from enum import Enum

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class SpinnerMode(Enum):
    """Spinner animation modes with different speeds."""

    IDLE = "idle"
    THINKING = "thinking"
    REQUESTING = "requesting"
    RESPONDING = "responding"
    TOOL_USE = "tool_use"


# Braille spinner frames
_BRAILLE_FRAMES = ["Γáï", "ΓáÖ", "Γá╣", "Γá╕", "Γá╝", "Γá┤", "Γáª", "Γáº", "Γáç", "ΓáÅ"]

# Mode-specific speeds (seconds per frame)
_MODE_SPEEDS: dict[SpinnerMode, float] = {
    SpinnerMode.IDLE: 0.0,
    SpinnerMode.THINKING: 0.200,
    SpinnerMode.REQUESTING: 0.050,
    SpinnerMode.RESPONDING: 0.100,
    SpinnerMode.TOOL_USE: 0.150,
}

# Direction arrows for modes
_MODE_ARROWS: dict[SpinnerMode, str] = {
    SpinnerMode.IDLE: "",
    SpinnerMode.THINKING: "",
    SpinnerMode.REQUESTING: "Γåæ",
    SpinnerMode.RESPONDING: "Γåô",
    SpinnerMode.TOOL_USE: "ΓåÆ",
}


class Spinner(Widget):
    """Animated spinner with state-aware speed, stall detection, and shimmer.

    The spinner cycles through braille characters at a speed that depends
    on the current mode.  When no tokens arrive for >3 s the colour
    gradually shifts from orange to red (stall indication).  A shimmer
    effect sweeps left-to-right across the spinner text.
    """

    _mode: reactive[SpinnerMode] = reactive(SpinnerMode.IDLE)
    _stall_intensity: reactive[float] = reactive(0.0)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._frame_index = 0
        self._last_frame_time = 0.0
        self._last_token_time = time.monotonic()
        self._shimmer_pos = 0.0
        self._running = False
        self._tick_timer = None

    def compose(self) -> ComposeResult:
        yield Static(" ", id="spinner-char", classes="spinner-text spinner-idle")

    @property
    def spinner_widget(self) -> Static:
        return self.query_one("#spinner-char", Static)

    def set_mode(self, mode: SpinnerMode) -> None:
        """Set the spinner mode."""
        self._mode = mode
        if mode != SpinnerMode.IDLE:
            self._last_token_time = time.monotonic()
            self._stall_intensity = 0.0
        self._update_css_class()

    def token_received(self) -> None:
        """Call when a token is received to reset stall timer."""
        self._last_token_time = time.monotonic()
        self._stall_intensity = 0.0

    def start(self) -> None:
        """Start the spinner animation."""
        self._running = True
        self._last_frame_time = time.monotonic()
        self._tick_timer = self.set_interval(0.05, self._tick)

    def stop(self) -> None:
        """Stop the spinner animation."""
        self._running = False
        self._mode = SpinnerMode.IDLE
        self._stall_intensity = 0.0
        if self._tick_timer is not None:
            self._tick_timer.stop()
            self._tick_timer = None
        self._update_css_class()
        try:
            self.spinner_widget.update(" ")
        except Exception:
            pass

    def on_unmount(self) -> None:
        """Cancel timers when the widget is removed."""
        self.stop()

    def _tick(self) -> None:
        """Animation tick ΓÇö handles frame advance, shimmer, and stall detection."""
        if not self._running:
            return

        now = time.monotonic()
        speed = _MODE_SPEEDS[self._mode]

        # Update stall intensity (0ΓåÆ1 over 3 seconds of no tokens)
        stall_elapsed = now - self._last_token_time
        if stall_elapsed > 3.0 and self._mode != SpinnerMode.IDLE:
            self._stall_intensity = min(1.0, (stall_elapsed - 3.0) / 5.0)
        else:
            self._stall_intensity = 0.0

        # Advance frame if enough time has passed
        if speed > 0 and (now - self._last_frame_time) >= speed:
            self._frame_index = (self._frame_index + 1) % len(_BRAILLE_FRAMES)
            self._last_frame_time = now

        # Update shimmer position
        self._shimmer_pos = (self._shimmer_pos + 0.15) % 1.0

        # Render (merged frame + shimmer)
        self._render_frame()

    def _render_frame(self) -> None:
        """Render the current spinner frame with shimmer."""
        if self._mode == SpinnerMode.IDLE:
            self.spinner_widget.update(" ")
            return

        char = _BRAILLE_FRAMES[self._frame_index]
        arrow = _MODE_ARROWS[self._mode]
        text = f" {char}{arrow}" if arrow else f" {char}"

        # Apply shimmer: brighten one character at shimmer_pos
        shimmer_idx = int(self._shimmer_pos * len(text))
        if shimmer_idx < len(text) and self._stall_intensity < 0.5:
            shimmer_char = text[shimmer_idx]
            text = (
                text[:shimmer_idx]
                + f"[bold white]{shimmer_char}[/]"
                + text[shimmer_idx + 1 :]
            )

        try:
            self.spinner_widget.update(text, markup=True)
        except Exception:
            pass

        self._update_css_class()
        self.refresh(layout=False)

    def _update_css_class(self) -> None:
        """Update CSS class based on mode and stall intensity."""
        widget = self.spinner_widget
        for cls in (
            "spinner-idle",
            "spinner-thinking",
            "spinner-requesting",
            "spinner-responding",
            "spinner-tool-use",
            "spinner-stalled",
        ):
            widget.remove_class(cls)

        if self._stall_intensity > 0.5:
            widget.add_class("spinner-stalled")
        else:
            mode_class = {
                SpinnerMode.IDLE: "spinner-idle",
                SpinnerMode.THINKING: "spinner-thinking",
                SpinnerMode.REQUESTING: "spinner-requesting",
                SpinnerMode.RESPONDING: "spinner-responding",
                SpinnerMode.TOOL_USE: "spinner-tool-use",
            }
            widget.add_class(mode_class.get(self._mode, "spinner-idle"))
