"""Tests for the note field's geometry, and a smoke test that it draws.

The geometry is arithmetic and is checked exactly. The drawing is checked only
for "does it run" - asserting pixels would pin down decisions that are supposed
to stay free - but running it matters more than it sounds: every bug this
module has had so far has been an exception on a code path no test entered,
and in the browser those surface as a blank canvas with a traceback in a log
nobody is reading yet.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402 - must follow the driver selection above

from piu.content import demo_chart  # noqa: E402
from piu.gameplay.session import PlaySession  # noqa: E402
from piu.render.notefield import NoteField  # noqa: E402

WIDTH, HEIGHT = 1280, 720


@pytest.fixture(scope="module")
def display() -> pygame.Surface:
    pygame.init()
    surface = pygame.display.set_mode((WIDTH, HEIGHT))
    yield surface
    pygame.quit()


@pytest.fixture()
def field(display: pygame.Surface) -> NoteField:
    return NoteField(demo_chart(), width=WIDTH, height=HEIGHT)


class TestGeometry:
    def test_a_note_due_now_sits_on_the_step_zone(self, field: NoteField) -> None:
        assert field.y_for(10.0, 10.0) == pytest.approx(field.receptor_y)

    def test_a_note_one_lead_time_away_is_at_the_bottom(self, field: NoteField) -> None:
        # This is what makes `lead_time` the readable form of scroll speed: a
        # note entering at the bottom edge takes exactly that long to arrive.
        y = field.y_for(10.0 + field.lead_time, 10.0)
        assert y == pytest.approx(HEIGHT)

    def test_notes_approach_from_below(self, field: NoteField) -> None:
        # Upward scrolling, which is the whole visual convention. A sign error
        # here would send notes off the top and look like nothing rendering.
        near = field.y_for(10.5, 10.0)
        far = field.y_for(11.0, 10.0)
        assert far > near > field.receptor_y

    def test_a_passed_note_is_above_the_step_zone(self, field: NoteField) -> None:
        assert field.y_for(9.5, 10.0) < field.receptor_y


class TestTheVisibleWindow:
    def test_it_excludes_notes_that_are_still_far_off(self, field: NoteField) -> None:
        chart = field.chart
        first, last = field.visible_range(0.0)
        # The demo's last note is half a minute in; nothing should be drawn for
        # it on the first frame.
        assert last < len(chart.notes)

    def test_it_grows_to_cover_notes_as_they_arrive(self, field: NoteField) -> None:
        early = field.visible_range(5.0)
        later = field.visible_range(20.0)
        assert later[0] >= early[0]
        assert later[1] > early[1]

    def test_it_reaches_back_far_enough_for_a_long_hold(self, field: NoteField) -> None:
        # A hold whose head has scrolled off the top can still have a body
        # crossing the screen, so the low bound is pushed back by the longest
        # hold in the chart. Without that the body vanishes with the head.
        chart = field.chart
        longest = max(n.duration for n in chart.notes if n.is_hold)
        assert longest > 0.0

        hold_index, hold = next(
            (i, n) for i, n in enumerate(chart.notes) if n.duration == longest
        )
        # Stand just after the head has left the top of the screen.
        moment = hold.time + longest * 0.5
        first, last = field.visible_range(moment)
        assert first <= hold_index < last

    def test_the_window_is_a_small_slice_of_a_long_chart(
        self, field: NoteField
    ) -> None:
        # The budget rule: per-frame work is proportional to notes on screen,
        # not notes in the chart. If this ever fails the bisect has stopped
        # doing its job and dense charts will be the first thing to suffer.
        first, last = field.visible_range(12.0)
        assert last - first < len(field.chart.notes)


class TestDrawing:
    def test_a_whole_playthrough_renders_without_raising(
        self, display: pygame.Surface, field: NoteField
    ) -> None:
        chart = field.chart
        session = PlaySession(chart)
        end = chart.notes[-1].time + 2.0

        moment = 0.0
        while moment < end:
            session.update(moment)
            display.fill((0, 0, 0))
            field.draw_receptors(display, {0, 2})
            field.draw_notes(display, session, moment)
            field.draw_mines(display, session, moment)
            moment += 1.0 / 60.0

    def test_it_draws_held_notes(self, display: pygame.Surface, field: NoteField) -> None:
        # The hold path pins the head to the step zone and drains the body,
        # which is a different branch from every other note.
        chart = field.chart
        session = PlaySession(chart)
        hold = next(n for n in chart.notes if n.is_hold)

        session.press(hold.column, hold.time)
        assert session.is_held(chart.notes.index(hold))

        field.draw_notes(display, session, hold.time + 0.5)

    def test_it_draws_with_an_empty_field(self, display: pygame.Surface) -> None:
        from piu.formats.chart import Chart, PlayMode
        from piu.content import demo_timing

        chart = Chart(mode=PlayMode.SINGLE, timing=demo_timing(), notes=[])
        empty = NoteField(chart, width=WIDTH, height=HEIGHT)
        session = PlaySession(chart)

        empty.draw_receptors(display)
        empty.draw_notes(display, session, 0.0)
        empty.draw_mines(display, session, 0.0)
