"""Tests for the generated demo content.

The demo chart is the only chart the game can currently play, so it is also the
only end-to-end fixture there is. The playthrough at the bottom is the real
value here: it drives the whole session over a chart with jumps, overlapping
holds and mines, and asserts the result is perfect. Anything that breaks
holds, column mapping, or the note cursor fails it.
"""

from __future__ import annotations

import pytest

from piu.content import (
    DEMO_BPM,
    DEMO_LEAD_IN,
    _time_of,
    demo_chart,
    demo_length_beats,
    demo_notes,
    demo_song,
    demo_timing,
)
from piu.formats.chart import NoteKind, PlayMode
from piu.gameplay.judge import Judgement
from piu.gameplay.scoring import Grade
from piu.gameplay.session import PlaySession


class TestTheChartIsWellFormed:
    def test_beat_to_time_agrees_with_the_times_baked_into_the_notes(self) -> None:
        # The bug this guards: the notes carry absolute times that include the
        # lead-in, so the chart's TimingData must carry the matching offset. If
        # it does not, the two agree at no beat at all, and nothing notices
        # until something recomputes a time from a beat.
        timing = demo_timing()
        for note in demo_notes():
            assert timing.beat_to_time(note.beat) == pytest.approx(note.time)
            if note.end_beat is not None:
                assert timing.beat_to_time(note.end_beat) == pytest.approx(
                    note.end_time
                )

    def test_beat_zero_lands_after_the_lead_in(self) -> None:
        assert demo_timing().beat_to_time(0.0) == pytest.approx(DEMO_LEAD_IN)

    def test_the_tempo_is_what_the_constant_says(self) -> None:
        timing = demo_timing()
        one_beat = timing.beat_to_time(1.0) - timing.beat_to_time(0.0)
        assert one_beat == pytest.approx(60.0 / DEMO_BPM)

    def test_the_chart_is_sorted_by_time(self) -> None:
        # The session's cursor and the field's bisect both assume this.
        times = [note.time for note in demo_chart().notes]
        assert times == sorted(times)

    def test_every_column_is_on_the_pad(self) -> None:
        for note in demo_notes():
            assert 0 <= note.column < PlayMode.SINGLE.columns

    def test_holds_end_after_they_start(self) -> None:
        holds = [n for n in demo_notes() if n.kind is NoteKind.HOLD]
        assert holds, "the demo is supposed to exercise holds"
        for note in holds:
            assert note.end_time is not None
            assert note.end_time > note.time
            assert note.duration > 0.0

    def test_the_chart_contains_the_cases_it_claims_to(self) -> None:
        # The chart's whole purpose is coverage, so an edit that quietly drops
        # a case should fail rather than just lower the difficulty.
        notes = demo_notes()
        assert any(n.kind is NoteKind.HOLD for n in notes), "no holds"
        assert any(n.kind is NoteKind.MINE for n in notes), "no mines"

        times = [n.time for n in notes]
        assert len(times) != len(set(times)), "no jumps - no two notes share a time"

        overlapping = [
            (a, b)
            for a in notes
            if a.kind is NoteKind.HOLD and a.end_time is not None
            for b in notes
            if b is not a
            and b.kind is NoteKind.HOLD
            and b.time < a.end_time
            and b.time > a.time
        ]
        assert overlapping, "no overlapping holds - concurrent hold state untested"

    def test_mines_do_not_count_towards_the_combo(self) -> None:
        chart = demo_chart()
        mines = sum(1 for n in chart.notes if n.kind is NoteKind.MINE)
        assert mines > 0
        assert chart.tap_count == len(chart.notes) - mines

    def test_the_click_track_outlasts_the_last_note(self) -> None:
        # A track that stops early leaves the final notes with no audio to be
        # judged against, which reads as a broken chart rather than a short one.
        last = max(
            (n.end_beat if n.end_beat is not None else n.beat) for n in demo_notes()
        )
        assert demo_length_beats() > last

    def test_the_song_wrapper_carries_the_chart(self) -> None:
        song = demo_song()
        assert song.title
        assert len(song.charts) == 1
        assert song.charts[0].mode is PlayMode.SINGLE


class TestAPerfectPlaythrough:
    """Play the real demo chart end to end, dead on every note.

    This is the closest thing to an integration test the engine has: a chart
    with jumps, overlapping holds and mines, driven through the session exactly
    as the gameplay screen drives it. The expected result is unambiguous, which
    is what makes it a useful failure when it breaks.
    """

    @staticmethod
    def _play(chart) -> PlaySession:
        session = PlaySession(chart)

        # Taps are released shortly after being pressed - which matters,
        # because a foot left on a panel is how mines are stepped on.
        events: list[tuple[float, int, str, int]] = []
        for note in chart.notes:
            if note.kind is NoteKind.MINE:
                continue
            events.append((note.time, 0, "down", note.column))
            if note.is_hold and note.end_time is not None:
                events.append((note.end_time, 1, "up", note.column))
            else:
                events.append((note.time + 0.05, 1, "up", note.column))
        events.sort()

        for moment, _, kind, column in events:
            # Input before time, per the session's frame contract.
            if kind == "down":
                session.press(column, moment)
            else:
                session.release(column, moment)
            session.update(moment)

        session.update(events[-1][0] + 5.0)
        return session

    def test_it_scores_a_full_combo(self) -> None:
        session = self._play(demo_chart())

        assert session.board.counts[Judgement.MISS] == 0
        assert session.board.counts[Judgement.BAD] == 0
        assert session.board.full_combo
        assert session.board.max_combo == demo_chart().tap_count

    def test_it_scores_perfectly(self) -> None:
        session = self._play(demo_chart())

        assert session.board.accuracy == pytest.approx(1.0)
        assert session.board.grade is Grade.SSS
        assert not session.failed

    def test_it_steps_on_no_mines_and_makes_no_stray_presses(self) -> None:
        # Both would be silent in the grade - accuracy is computed from notes,
        # not from what else the player did - so they are asserted separately.
        session = self._play(demo_chart())

        assert session.board.mines_hit == 0
        assert session.board.stray_presses == 0

    def test_every_note_is_resolved(self) -> None:
        session = self._play(demo_chart())

        assert session.finished
        assert session.board.judged == demo_chart().tap_count

    def test_doing_nothing_at_all_fails_the_stage(self) -> None:
        # The precondition that gives the tests above their meaning: this chart
        # is not one that passes itself.
        chart = demo_chart()
        session = PlaySession(chart)
        session.update(chart.notes[-1].time + 5.0)

        assert session.failed
        assert session.board.counts[Judgement.MISS] == chart.tap_count
        assert session.board.grade is Grade.F
