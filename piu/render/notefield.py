"""Drawing the scrolling note field.

Notes travel upward to a step zone near the top of the screen, which is the
arrangement Pump It Up uses and the reason the receptor row sits high rather
than low. A note's vertical position is a pure function of how far away in time
it is, so nothing here accumulates state that could drift from the song clock:
if the clock is right, the field is right.

Why everything is pre-rendered
------------------------------
WASM CPython is meaningfully slower than native and the browser is the only
target, so the per-frame budget is spent as if it were scarce. Every note
surface is drawn once at construction and blitted thereafter - no per-frame
surface creation, no per-frame allocation in the note loop, and one batched
`fblits` call for the taps instead of one `blit` each.

Why the visible slice is found by bisect
----------------------------------------
Per-frame work must be proportional to notes on screen, not notes in the chart.
The chart is time-sorted, so the visible window is two binary searches. The low
bound is pushed back by the longest hold in the chart, because a hold whose
head has already scrolled past the top of the screen can still have a body
crossing it.
"""

from __future__ import annotations

import bisect

import pygame

from piu.formats.chart import Chart, Note, NoteKind, panel_for_column
from piu.gameplay.session import NoteState, PlaySession
from piu.render.panels import PANEL_COLORS, draw_panel, lane_rects

#: Seconds a note is visible before it reaches the step zone. This is the
#: readable form of "scroll speed": it says how much warning the player gets,
#: which is the thing that actually matters, and it stays meaningful when the
#: window is resized. Speed mods in W5 scale this.
DEFAULT_LEAD_TIME = 1.1

#: Height of a note, as a fraction of the lane's width. Slightly less than
#: square so a stream of sixteenths reads as separate notes rather than a bar.
NOTE_ASPECT = 0.55


def _shade(color: tuple[int, int, int], amount: int) -> tuple[int, int, int]:
    """Lighten (positive) or darken (negative) a colour, clamped."""
    return (
        max(0, min(255, color[0] + amount)),
        max(0, min(255, color[1] + amount)),
        max(0, min(255, color[2] + amount)),
    )


class NoteField:
    """Renders one chart's notes against a step zone.

    Constructed after the display exists, so touching pygame here is safe -
    unlike module scope, where pygbag has not finished populating the module.
    """

    def __init__(
        self,
        chart: Chart,
        *,
        width: int,
        height: int,
        receptor_y: int = 96,
        cell: int = 108,
        gap: int = 8,
        lead_time: float = DEFAULT_LEAD_TIME,
    ) -> None:
        self.chart = chart
        self.width = width
        self.height = height
        self.receptor_y = receptor_y
        self.cell = cell
        self.lead_time = lead_time

        self.lanes = lane_rects(
            chart.columns, width=width, top=receptor_y, cell=cell, gap=gap
        )
        self.panels = [panel_for_column(c, chart.mode) for c in range(chart.columns)]

        #: Pixels a note travels per second. Derived so that a note entering at
        #: the bottom of the screen reaches the step zone exactly `lead_time`
        #: later, which is what makes the constant above readable.
        self.pixels_per_second = (height - receptor_y) / lead_time

        self.note_height = int(cell * NOTE_ASPECT)
        self._taps = [self._render_tap(column) for column in range(chart.columns)]
        self._heads = [self._render_head(column) for column in range(chart.columns)]

        self._times = [note.time for note in chart.notes]
        self._longest_hold = max(
            (note.duration for note in chart.notes if note.is_hold), default=0.0
        )

        # Resolved once. `fblits` is a pygame-ce addition and batching matters
        # far more under WASM than it does natively, but a missing method must
        # not be a crash on some other build.
        self._fblits = getattr(pygame.Surface, "fblits", None)

    # ------------------------------------------------------------ pre-render

    def _render_tap(self, column: int) -> pygame.Surface:
        """One note, drawn once and reused for every note in this column."""
        color = PANEL_COLORS[self.panels[column]]
        surface = pygame.Surface((self.cell, self.note_height), pygame.SRCALPHA)
        rect = surface.get_rect()

        pygame.draw.rect(surface, _shade(color, -70), rect, border_radius=8)
        pygame.draw.rect(surface, color, rect.inflate(-6, -6), border_radius=6)
        # A lighter band across the middle gives the note a readable centre at
        # speed, which a flat rectangle does not.
        band = rect.inflate(-18, -int(self.note_height * 0.55))
        pygame.draw.rect(surface, _shade(color, 70), band, border_radius=4)
        return surface

    def _render_head(self, column: int) -> pygame.Surface:
        """A hold head: the same note, marked so it reads as the start of one."""
        surface = self._render_tap(column).copy()
        color = PANEL_COLORS[self.panels[column]]
        rect = surface.get_rect()
        pygame.draw.rect(surface, _shade(color, 110), rect, width=3, border_radius=8)
        return surface

    # ----------------------------------------------------------------- draw

    def y_for(self, time: float, now: float) -> float:
        """Centre of the note for a note at ``time``, given song position ``now``."""
        return self.receptor_y + (time - now) * self.pixels_per_second

    def visible_range(self, now: float) -> tuple[int, int]:
        """Index range of notes that could touch the screen at ``now``."""
        span_below = (self.height - self.receptor_y) / self.pixels_per_second
        span_above = (self.receptor_y + self.cell) / self.pixels_per_second
        first = bisect.bisect_left(
            self._times, now - span_above - self._longest_hold
        )
        last = bisect.bisect_right(self._times, now + span_below)
        return first, last

    def draw_receptors(
        self, surface: pygame.Surface, lit: set[int] | None = None
    ) -> None:
        """Draw the step zone. Columns in ``lit`` are drawn pressed."""
        held = lit or set()
        for column, rect in enumerate(self.lanes):
            draw_panel(surface, self.panels[column], rect, lit=column in held)

    def draw_notes(
        self, surface: pygame.Surface, session: PlaySession, now: float
    ) -> None:
        """Draw every visible note that has not yet been resolved."""
        first, last = self.visible_range(now)
        batch: list[tuple[pygame.Surface, tuple[float, float]]] = []

        for index in range(first, last):
            note = self.chart.notes[index]
            if note.kind is NoteKind.MINE:
                continue
            state = session.state[index]
            if state is NoteState.DONE:
                continue

            lane = self.lanes[note.column]
            held = state is NoteState.HELD
            # A held note stays pinned to the step zone while the body drains
            # into it, which is what tells the player they are still holding.
            head_y = self.receptor_y if held else self.y_for(note.time, now)

            if note.is_hold and note.end_time is not None:
                self._draw_hold_body(surface, note, lane, head_y, now, held)

            sprite = self._heads[note.column] if note.is_hold else self._taps[note.column]
            batch.append((sprite, (lane.x, head_y)))

        if not batch:
            return
        if self._fblits is not None:
            surface.fblits(batch)
        else:
            for sprite, position in batch:
                surface.blit(sprite, position)

    def _draw_hold_body(
        self,
        surface: pygame.Surface,
        note: Note,
        lane: pygame.Rect,
        head_y: float,
        now: float,
        held: bool,
    ) -> None:
        """The bar joining a hold's head to its tail.

        Drawn before the head so the head caps it. While the hold is being
        held the head is pinned to the step zone and the tail keeps rising, so
        the body visibly drains away - which is the only feedback the player
        gets that the hold is still theirs.
        """
        assert note.end_time is not None
        centre = self.note_height / 2.0
        top = self.y_for(note.end_time, now) + centre
        bottom = head_y + centre
        if bottom <= top:
            return

        # Clipped to the screen rather than handed to pygame at full length: a
        # hold lasting a whole song is otherwise a rect thousands of pixels tall.
        top = max(top, -self.cell)
        bottom = min(bottom, self.height + self.cell)
        if bottom <= top:
            return

        color = PANEL_COLORS[self.panels[note.column]]
        body = pygame.Rect(
            lane.x + self.cell // 4,
            int(top),
            self.cell // 2,
            max(1, int(bottom - top)),
        )
        pygame.draw.rect(surface, _shade(color, 40 if held else -60), body)

    def draw_mines(
        self, surface: pygame.Surface, session: PlaySession, now: float
    ) -> None:
        """Mines, drawn as rings so they never read as something to step on."""
        first, last = self.visible_range(now)
        for index in range(first, last):
            note = self.chart.notes[index]
            if note.kind is not NoteKind.MINE:
                continue
            if session.state[index] is NoteState.DONE:
                continue
            lane = self.lanes[note.column]
            centre = (lane.centerx, int(self.y_for(note.time, now) + self.note_height / 2))
            pygame.draw.circle(surface, (210, 210, 210), centre, self.cell // 3, width=4)
            pygame.draw.circle(surface, (150, 150, 150), centre, self.cell // 6, width=3)
