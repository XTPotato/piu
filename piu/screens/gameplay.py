"""The play screen: a chart, a clock, and everything the player sees.

This screen owns no rules. It reads the song clock, hands input and time to
`PlaySession`, and draws what comes back. Every question about whether a step
was good, what it cost, or whether the stage is over is answered in
`piu.gameplay`, which has no display and is tested without one. If a scoring
bug can be reproduced here but not there, the logic is in the wrong module.

Why calibration is applied to input rather than to the clock
-------------------------------------------------------------
Rhythm games have two offsets - one that moves the audio against the visuals,
and one that moves the player's input against both. The W1 rig measures the
*combined* judged offset, which is a single number, so it is applied in a
single place: the timestamp of each press. Visuals stay locked to the audio,
which is the relationship the player is actually reading. Shifting the clock
instead would move the notes away from their own clicks, which is a different
correction that happens to produce the same judgement and a worse picture.

Why the demo plays a metronome
------------------------------
The click track `WebAudioClock` synthesizes puts clicks on exact sample
indices, so the chart's beats and the audio's beats are the same arithmetic.
There is no decoded file whose own alignment could be the thing under
suspicion, and no licence question - see `piu.content`. W4 substitutes real
audio behind the same interface.
"""

from __future__ import annotations

import pygame

from piu import runtime
from piu.app import App, Screen
from piu.content import (
    DEMO_BPM,
    DEMO_LEAD_IN,
    DEMO_PICKUP_BEATS,
    demo_chart,
    demo_length_beats,
)
from piu.core.clock import ClockError, ManualClock, WebAudioClock
from piu.formats.chart import Chart, PlayMode
from piu.gameplay.judge import HitResult, Judgement
from piu.gameplay.session import PlaySession
from piu.input import layouts
from piu.input.web_input import WebKeyboard
from piu.render.notefield import NoteField

#: How long a judgement stays on screen after the step that earned it.
JUDGEMENT_HOLD = 0.55

#: Seconds after the last note before the results screen takes over. Long
#: enough that the final judgement is readable rather than snatched away.
OUTRO = 1.6

JUDGEMENT_COLORS: dict[Judgement, tuple[int, int, int]] = {
    Judgement.PERFECT: (255, 232, 120),
    Judgement.GREAT: (120, 240, 150),
    Judgement.GOOD: (120, 190, 245),
    Judgement.BAD: (240, 140, 110),
    Judgement.MISS: (225, 90, 90),
}


def _font(size: int) -> pygame.font.Font:
    return pygame.font.Font(None, size)


class GameplayScreen(Screen):
    """Plays one chart."""

    def __init__(
        self,
        app: App,
        chart: Chart | None = None,
        *,
        calibration: float = 0.0,
    ) -> None:
        super().__init__(app)
        self.chart = chart if chart is not None else demo_chart()
        self.calibration = calibration

        self._big = _font(84)
        self._title = _font(38)
        self._body = _font(26)
        self._small = _font(21)

        self.session = PlaySession(self.chart)
        self.field: NoteField | None = None
        self.clock: WebAudioClock | ManualClock | None = None
        self.keyboard = WebKeyboard()

        self.status = "loading"
        self.detail = ""
        self.position = 0.0
        self.started = False

        #: Columns whose panel is down, for lighting the step zone. Kept here
        #: rather than read from the session because it is presentation only.
        self._down: set[int] = set()
        self._last: HitResult | None = None
        self._last_at = -99.0
        self._finished_at: float | None = None

        self._key_columns = layouts.WASDX.key_to_column(PlayMode.SINGLE)
        self._last_note = max(
            (n.end_time if n.end_time is not None else n.time)
            for n in self.chart.notes
        ) if self.chart.notes else 0.0

    # ------------------------------------------------------------- lifecycle

    async def enter(self) -> None:
        surface = self.app.surface
        width, height = self.app.size if surface is None else surface.get_size()
        self.field = NoteField(self.chart, width=width, height=height)

        if not runtime.IS_WEB:
            # Desktop is for iterating on what the screen looks like. It has no
            # audio path, so nothing measured here is evidence about timing -
            # that rule is why the clock is a hand-cranked one rather than a
            # wall clock dressed up as a song position.
            self.clock = ManualClock()
            self.clock.start(0.0)
            self.status = "playing"
            self.detail = "desktop preview - no audio, timing is not evidence"
            self.started = True
            return

        try:
            self.clock = WebAudioClock()
        except ClockError as error:
            self.status = "error"
            self.detail = str(error)
            runtime.log("FAIL", "gameplay: {}".format(error))
            return

        if not self.clock.init_context():
            self.status = "error"
            self.detail = self.clock.last_error or "could not create AudioContext"
            runtime.log("FAIL", "gameplay: {}".format(self.detail))
            return

        # The click track's first *measured* beat must land on the chart's beat
        # zero. The track counts in before that, so its own lead-in is shorter
        # than the chart's by exactly the count-in.
        beat_period = 60.0 / DEMO_BPM
        track_lead_in = DEMO_LEAD_IN - DEMO_PICKUP_BEATS * beat_period
        if track_lead_in < 0.0:
            self.status = "error"
            self.detail = (
                "the count-in is longer than the chart's lead-in, so beat zero "
                "would fall before the song starts"
            )
            runtime.log("FAIL", "gameplay: {}".format(self.detail))
            return

        beats = int(demo_length_beats()) if self.chart.notes else 8
        if not self.clock.load_click_track(
            DEMO_BPM, beats, track_lead_in, 4, DEMO_PICKUP_BEATS
        ):
            self.status = "error"
            self.detail = self.clock.last_error or "could not build the click track"
            return

        self.keyboard.enable()
        runtime.log(
            "BOOT",
            "gameplay: {} notes, {} beats at {:g} BPM, calibration {:+.0f}ms".format(
                len(self.chart.notes), beats, DEMO_BPM, self.calibration * 1000.0
            ),
        )

    async def exit(self) -> None:
        self.keyboard.disable()
        if self.clock is not None:
            self.clock.stop()

    # ----------------------------------------------------------------- input

    def handle_event(self, event: pygame.event.Event) -> None:
        # Desktop only. In the browser, input arrives stamped through the JS
        # bridge and this path would quantise it to the frame - the 5ms the
        # whole input design exists to avoid.
        if runtime.IS_WEB and self.keyboard.available:
            return
        if event.type not in (pygame.KEYDOWN, pygame.KEYUP):
            return

        column = self._key_columns.get(pygame.key.name(event.key))
        if column is None:
            return
        if event.type == pygame.KEYDOWN:
            self._on_press(column, self.position)
        else:
            self._on_release(column, self.position)

    def _drain_stamped_input(self) -> None:
        for event in self.keyboard.drain():
            column = self._key_columns.get(event.key_name)
            if column is None:
                continue
            if event.down:
                self._on_press(column, event.time)
            else:
                self._on_release(column, event.time)

    def _on_press(self, column: int, at: float) -> None:
        self._down.add(column)
        # Calibration moves the player's timestamp, not the song. A player who
        # is consistently early has a negative measured offset, so subtracting
        # it moves the press later, towards the note.
        result = self.session.press(column, at - self.calibration)
        if result is not None:
            self._remember(result)

    def _on_release(self, column: int, at: float) -> None:
        self._down.discard(column)
        result = self.session.release(column, at - self.calibration)
        if result is not None:
            self._remember(result)

    def _remember(self, result: HitResult) -> None:
        self._last = result
        self._last_at = self.position

    # ---------------------------------------------------------------- update

    async def update(self, dt: float) -> None:
        if self.status == "error" or self.clock is None:
            return

        if isinstance(self.clock, ManualClock):
            self.clock.advance(dt)
        elif not self.started:
            state = self.clock.state
            if state == "ready":
                self.clock.start()
                self.started = True
                self.status = "playing"
                runtime.log("BOOT", "gameplay: playing")
            elif state == "error":
                self.status = "error"
                self.detail = self.clock.last_error
            return

        self.position = self.clock.position()

        # Input first, then time. A press is stamped when the key went down,
        # which is always before this frame - expiring notes first would turn
        # an on-time step into a miss because the frame was late. See the
        # frame contract in `piu.gameplay.session`.
        self._drain_stamped_input()
        for result in self.session.update(self.position):
            self._remember(result)

        if self.session.finished or self.position > self._last_note + OUTRO:
            if self._finished_at is None:
                self._finished_at = self.position
            elif self.position - self._finished_at >= OUTRO:
                await self._finish()

    async def _finish(self) -> None:
        from piu.screens.results import ResultsScreen

        runtime.log("OK", "stage complete: {}".format(self.session.board.describe()))
        self.app.pop()
        self.app.push(ResultsScreen(self.app, self.session, self.chart))

    # ------------------------------------------------------------------ draw

    async def draw(self, surface: pygame.Surface) -> None:
        surface.fill((14, 14, 20))
        if self.status == "error":
            self._draw_error(surface)
            return
        if self.field is None:
            return

        self.field.draw_receptors(surface, self._down)
        self.field.draw_notes(surface, self.session, self.position)
        self.field.draw_mines(surface, self.session, self.position)
        self._draw_hud(surface)

    def _draw_error(self, surface: pygame.Surface) -> None:
        text = self._title.render("Cannot play", True, (240, 120, 120))
        surface.blit(text, (60, 260))
        detail = self._body.render(self.detail, True, (200, 200, 200))
        surface.blit(detail, (60, 310))

    def _draw_hud(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        board = self.session.board

        # Life. Drawn as a bar that empties towards the left, with the failure
        # end marked, so "how close am I" is readable without a number.
        bar = pygame.Rect(40, height - 54, width - 80, 22)
        pygame.draw.rect(surface, (40, 40, 52), bar, border_radius=6)
        filled = bar.copy()
        filled.width = max(0, int(bar.width * self.session.life))
        color = (90, 210, 130) if self.session.life > 0.25 else (225, 100, 90)
        pygame.draw.rect(surface, color, filled, border_radius=6)
        pygame.draw.rect(surface, (90, 90, 110), bar, width=2, border_radius=6)

        if board.combo >= 4:
            combo = self._big.render(str(board.combo), True, (250, 250, 235))
            surface.blit(combo, combo.get_rect(center=(width // 2, 330)))

        if self._last is not None and self.position - self._last_at < JUDGEMENT_HOLD:
            name = self._last.judgement.name
            text = self._title.render(name, True, JUDGEMENT_COLORS[self._last.judgement])
            surface.blit(text, text.get_rect(center=(width // 2, 262)))

        stats = "{}  {:.1f}%  max {}".format(
            board.grade.name, board.accuracy * 100.0, board.max_combo
        )
        surface.blit(self._small.render(stats, True, (185, 185, 200)), (40, height - 86))

        if self.detail:
            note = self._small.render(self.detail, True, (150, 150, 165))
            surface.blit(note, (40, 18))
