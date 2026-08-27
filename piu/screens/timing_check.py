"""The W1 timing gate, run in the browser.

The plan makes this the gate on everything downstream: if the browser cannot
hold timing, that has to be known now rather than after five more milestones
have been built on the assumption that it can.

How it measures
---------------
A click track is synthesized directly in Web Audio, so the reference is
arithmetic - clicks land on exact sample indices - rather than something
decoded from a file. Whatever offset comes out belongs to the pipeline, not to
the material.

The player taps along. Each keydown is stamped by the JS bridge with the audio
clock at the instant the DOM event fires, so the measurement is not polluted by
frame quantisation. Offsets are then input-minus-expected, and the verdict comes
from `piu.gameplay.offsets`, which is unit-tested.

Native results are deliberately not accepted as evidence: the browser is the
only runtime that ships.
"""

from __future__ import annotations

import pygame

from piu import runtime
from piu.app import App, Screen
from piu.core.clock import ClockError, WebAudioClock
from piu.gameplay import offsets
from piu.input.web_input import WebKeyboard

BACKGROUND = (12, 12, 18)
TEXT = (236, 236, 240)
MUTED = (128, 128, 140)
GOOD = (96, 210, 130)
BAD = (232, 96, 108)
ACCENT = (58, 118, 232)

BPM = 120.0
BEATS = 32
LEAD_IN = 2.0
ACCENT_EVERY = 4

#: Matches the default ruleset's Perfect half-window.
PERFECT_WINDOW = 0.042

#: Keys that count as a tap. Any of them, so the player can use whatever is
#: comfortable - this measures the pipeline, not a specific binding.
TAP_CODES = {
    "Space", "KeyA", "KeyW", "KeyS", "KeyD", "KeyX",
    "Numpad1", "Numpad7", "Numpad5", "Numpad9", "Numpad3",
}


def _font(size: int) -> pygame.font.Font:
    return pygame.font.Font(None, size)


class TimingCheckScreen(Screen):
    """Plays a click track and measures how accurately taps land on it."""

    def __init__(self, app: App) -> None:
        super().__init__(app)
        self._title = _font(44)
        self._body = _font(28)
        self._small = _font(22)
        self._mono = _font(24)

        self.clock: WebAudioClock | None = None
        self.keyboard = WebKeyboard()
        self.status = "starting"
        self.detail = ""

        self.expected = [LEAD_IN + i * (60.0 / BPM) for i in range(BEATS)]
        self.taps: list[float] = []
        self.stats = offsets.summarize([])
        self.verdict: offsets.Verdict | None = None
        self._reported = False

    # ------------------------------------------------------------ lifecycle

    async def enter(self) -> None:
        if not runtime.IS_WEB:
            self.status = "unavailable"
            self.detail = (
                "The timing gate only runs in the browser. The desktop build "
                "has no audio path, and its numbers would not be evidence "
                "about the runtime that ships."
            )
            runtime.log("WARN", "timing check skipped: not the web build")
            return

        try:
            self.clock = WebAudioClock()
        except ClockError as error:
            self.status = "error"
            self.detail = str(error)
            runtime.log("FAIL", "timing check: {}".format(error))
            return

        # The gesture that got us here already unlocked audio.
        if not self.clock.init_context():
            self.status = "error"
            self.detail = self.clock.last_error or "could not create AudioContext"
            return

        runtime.log(
            "BOOT",
            "timing check: building {} beats at {:g} BPM, context {} @ {:g}Hz, "
            "reported latency {:.1f}ms".format(
                BEATS, BPM, self.clock.context_state,
                self.clock.sample_rate, self.clock.latency * 1000.0,
            ),
        )

        if not self.clock.load_click_track(BPM, BEATS, LEAD_IN, ACCENT_EVERY):
            self.status = "error"
            self.detail = self.clock.last_error or "click track generation failed"
            return

        self.keyboard.enable()
        self.status = "ready"

    async def exit(self) -> None:
        self.keyboard.disable()
        if self.clock is not None:
            self.clock.stop()

    # --------------------------------------------------------------- input

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_ESCAPE:
            self.app.pop()
            return
        if event.key == pygame.K_r:
            self._restart()
            return
        if event.key == pygame.K_RETURN and self.status == "ready":
            self._begin()

        # Taps themselves are read from the timestamped JS queue, not from
        # pygame events, so nothing is measured off a frame boundary. The
        # fallback below only applies where the bridge is unavailable.
        if self.status == "running" and not self.keyboard.available:
            if event.key in (pygame.K_SPACE, pygame.K_a, pygame.K_w,
                             pygame.K_s, pygame.K_d, pygame.K_x):
                assert self.clock is not None
                self.taps.append(self.clock.position())

    def _begin(self) -> None:
        assert self.clock is not None
        self.taps.clear()
        self.verdict = None
        self._reported = False
        self.keyboard.drain()  # discard anything queued before the start
        self.clock.start()
        self.status = "running"
        runtime.log("BOOT", "timing check: playing")

    def _restart(self) -> None:
        if self.clock is None:
            return
        self.clock.stop()
        self.status = "ready"
        self.taps.clear()
        self.verdict = None
        self._reported = False

    # -------------------------------------------------------------- update

    async def update(self, dt: float) -> None:
        if self.clock is None or self.status not in ("running", "ready"):
            return

        for event in self.keyboard.drain():
            if event.down and event.code in TAP_CODES and self.status == "running":
                self.taps.append(event.time)

        if self.status != "running":
            return

        self._recompute()

        # The track has played out, plus a moment for the last tap to land.
        if self.clock.position() > self.expected[-1] + 0.75:
            self._finish()

    def _recompute(self) -> None:
        matched, unmatched, missed = offsets.match_inputs(self.taps, self.expected)
        self.stats = offsets.summarize(matched, len(unmatched), len(missed))

    def _finish(self) -> None:
        assert self.clock is not None
        self.clock.stop()
        self.status = "done"
        self._recompute()
        self.verdict = offsets.evaluate(self.stats, PERFECT_WINDOW)

        if self._reported:
            return
        self._reported = True

        runtime.log(
            "OK" if self.verdict.passed else "WARN",
            "timing gate {}: {}".format(
                "PASSED" if self.verdict.passed else "NOT PASSED", self.stats.describe()
            ),
        )
        runtime.log("BOOT", "timing gate reason: {}".format(self.verdict.reason))
        runtime.log(
            "BOOT",
            "suggested calibration offset: {:+.1f}ms  "
            "(unmatched taps {}, missed clicks {})".format(
                offsets.suggest_calibration(self.stats) * 1000.0,
                self.stats.unmatched_inputs,
                self.stats.missed_expected,
            ),
        )

    # ---------------------------------------------------------------- draw

    async def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BACKGROUND)
        width, height = surface.get_size()
        centre = width // 2

        def line(text: str, font: pygame.font.Font, color, y: int) -> None:
            rendered = font.render(text, True, color)
            surface.blit(rendered, rendered.get_rect(center=(centre, y)))

        line("Timing check", self._title, TEXT, 56)

        if self.status == "unavailable":
            line("Not available on the desktop build", self._body, MUTED, 140)
            self._wrap(surface, self.detail, 180)
            line("ESC to go back", self._small, MUTED, height - 40)
            return

        if self.status == "error":
            line("Audio could not start", self._body, BAD, 140)
            self._wrap(surface, self.detail, 180)
            line("ESC to go back", self._small, MUTED, height - 40)
            return

        if self.status in ("starting", "ready"):
            line("Tap along with the click on every beat.", self._body, TEXT, 130)
            line(
                "Any of space, WASDX, or the numpad counts.",
                self._small, MUTED, 168,
            )
            line("ENTER to start      ESC to go back", self._body, ACCENT, 220)
            return

        # Running or done.
        position = self.clock.position() if self.clock else 0.0
        if self.status == "running" and position < 0:
            line("Get ready...", self._body, TEXT, 130)
        else:
            beat = max(0, int((position - LEAD_IN) / (60.0 / BPM)) + 1)
            line(
                "Beat {} of {}".format(min(beat, BEATS), BEATS),
                self._body, TEXT, 130,
            )

        self._draw_scatter(surface, centre, 250)

        line(self.stats.describe(), self._mono, TEXT, 350)
        line(
            "taps {}   unmatched {}   missed clicks {}".format(
                len(self.taps), self.stats.unmatched_inputs, self.stats.missed_expected
            ),
            self._small, MUTED, 384,
        )

        if self.verdict is not None:
            color = GOOD if self.verdict.passed else BAD
            line(
                "GATE PASSED" if self.verdict.passed else "GATE NOT PASSED",
                self._title, color, 440,
            )
            self._wrap(surface, self.verdict.reason, 486)
            line(
                "Suggested calibration: {:+.1f}ms".format(
                    offsets.suggest_calibration(self.stats) * 1000.0
                ),
                self._body, TEXT, 566,
            )

        line("R to run again      ESC to go back", self._small, MUTED, height - 40)

    def _draw_scatter(self, surface: pygame.Surface, centre: int, y: int) -> None:
        """Each tap as a mark, so the shape of the error is visible at a glance.

        A tight cluster and a wide smear can share a mean; only one of them is
        playable, and the picture separates them instantly.
        """
        half_width = 300
        scale = half_width / 0.120  # +/-120ms across the bar

        pygame.draw.rect(
            surface, (30, 30, 44),
            pygame.Rect(centre - half_width, y - 26, half_width * 2, 52),
            border_radius=6,
        )
        # The Perfect window, for scale.
        window_px = int(PERFECT_WINDOW * scale)
        pygame.draw.rect(
            surface, (32, 58, 40),
            pygame.Rect(centre - window_px, y - 26, window_px * 2, 52),
            border_radius=6,
        )
        pygame.draw.line(surface, MUTED, (centre, y - 26), (centre, y + 26), 2)

        matched, _, _ = offsets.match_inputs(self.taps, self.expected)
        for offset in matched:
            x = centre + int(max(-0.120, min(0.120, offset)) * scale)
            colour = GOOD if abs(offset) <= PERFECT_WINDOW else BAD
            pygame.draw.line(surface, colour, (x, y - 20), (x, y + 20), 2)

        for label, dx in (("early", -half_width + 34), ("late", half_width - 30)):
            rendered = self._small.render(label, True, MUTED)
            surface.blit(rendered, rendered.get_rect(center=(centre + dx, y + 40)))

    def _wrap(self, surface: pygame.Surface, text: str, y: int) -> None:
        """Word-wrap ``text`` centred on the surface."""
        words = text.split()
        limit = surface.get_width() - 160
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = (current + " " + word).strip()
            if self._small.size(candidate)[0] > limit and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)

        for index, text_line in enumerate(lines[:4]):
            rendered = self._small.render(text_line, True, MUTED)
            surface.blit(
                rendered,
                rendered.get_rect(center=(surface.get_width() // 2, y + index * 26)),
            )
