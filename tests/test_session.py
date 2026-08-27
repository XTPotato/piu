"""Tests for the play session: whole stages, scripted, with no display.

The session is the only place where "what the chart says" meets "what the
player did", so these are the tests that would catch a game that looks right
and scores wrong. Every case below is driven by explicit timestamps rather than
a real clock, which is what makes the expected values exact.
"""

from __future__ import annotations

import pytest

from piu.core.timing import BpmSegment, TimingData
from piu.formats.chart import Chart, Note, NoteKind, PlayMode
from piu.gameplay.judge import (
    LIFE_DELTA,
    MISS_WINDOW,
    STARTING_LIFE,
    Judgement,
)
from piu.gameplay.scoring import Grade
from piu.gameplay.session import HOLD_RELEASE_GRACE, NoteState, PlaySession

# 120 BPM throughout, so one beat is half a second and beat == time * 2. The
# beat values are cosmetic here - the session reads `time` only - but they are
# filled in honestly so a failure never looks like a beat/time confusion.
BPM = 120.0


def tap(time: float, column: int) -> Note:
    return Note(beat=time * 2.0, time=time, column=column)


def hold(time: float, end: float, column: int) -> Note:
    return Note(
        beat=time * 2.0,
        time=time,
        column=column,
        kind=NoteKind.HOLD,
        end_beat=end * 2.0,
        end_time=end,
    )


def mine(time: float, column: int) -> Note:
    return Note(beat=time * 2.0, time=time, column=column, kind=NoteKind.MINE)


def session_for(*notes: Note) -> PlaySession:
    chart = Chart(
        mode=PlayMode.SINGLE,
        timing=TimingData(bpms=[BpmSegment(0.0, BPM)]),
        notes=list(notes),
    )
    chart.sort()
    return PlaySession(chart)


class TestTaps:
    def test_a_dead_on_step_is_perfect_and_starts_a_combo(self) -> None:
        session = session_for(tap(1.0, 2))
        result = session.press(2, 1.0)

        assert result is not None
        assert result.judgement is Judgement.PERFECT
        assert session.combo == 1

    def test_a_result_reports_the_signed_offset(self) -> None:
        # Late is positive, matching `piu.gameplay.offsets`. A sign flip here
        # would read as a calibration error rather than as a bug.
        session = session_for(tap(1.0, 0))
        result = session.press(0, 1.060)

        assert result is not None
        assert result.judgement is Judgement.GREAT
        assert result.offset == pytest.approx(0.060)

    def test_a_press_with_no_note_nearby_is_a_stray(self) -> None:
        session = session_for(tap(5.0, 0))
        assert session.press(0, 1.0) is None
        assert session.board.stray_presses == 1
        assert session.board.judged == 0

    def test_a_press_in_the_wrong_column_does_not_steal_a_note(self) -> None:
        session = session_for(tap(1.0, 2))
        assert session.press(3, 1.0) is None
        assert session.state[0] is NoteState.PENDING

    def test_one_note_absorbs_only_one_press(self) -> None:
        # A double-tap should show up as a stray rather than quietly improving
        # the tally, which is the same rule `offsets.match_inputs` follows.
        session = session_for(tap(1.0, 1))
        assert session.press(1, 1.0) is not None
        assert session.press(1, 1.010) is None
        assert session.board.counts[Judgement.PERFECT] == 1
        assert session.board.stray_presses == 1

    def test_the_nearer_of_two_candidates_wins(self) -> None:
        session = session_for(tap(1.0, 0), tap(1.10, 0))
        result = session.press(0, 1.09)

        assert result is not None
        assert result.note_index == 1


class TestMisses:
    def test_a_note_expires_once_the_window_closes(self) -> None:
        session = session_for(tap(1.0, 2))

        # Still hittable at the far edge of the Bad window.
        assert session.update(1.0 + MISS_WINDOW) == []
        assert session.state[0] is NoteState.PENDING

        results = session.update(1.0 + MISS_WINDOW + 0.001)
        assert [r.judgement for r in results] == [Judgement.MISS]
        assert session.state[0] is NoteState.DONE

    def test_a_miss_breaks_the_combo(self) -> None:
        session = session_for(tap(1.0, 0), tap(2.0, 0), tap(3.0, 0))
        session.press(0, 1.0)
        assert session.combo == 1

        session.update(2.0 + MISS_WINDOW + 0.001)
        assert session.combo == 0

    def test_a_missed_note_is_not_hittable_afterwards(self) -> None:
        session = session_for(tap(1.0, 0))
        session.update(2.0)
        assert session.press(0, 2.0) is None
        assert session.board.counts[Judgement.MISS] == 1


class TestTheFrameContract:
    """Input is stamped in the past; the frame it lands on may be late.

    `web_audio.js` timestamps a keydown as the DOM event fires, so a press
    always reaches Python with a timestamp behind the current song position.
    The session's contract is that a caller drains input *before* calling
    `update`, and these two tests are why that ordering is not a style choice.
    """

    def test_a_press_stamped_in_the_past_is_still_judged(self) -> None:
        session = session_for(tap(1.0, 0))

        # A frame arrives late - the song is already well past the note - but
        # the press it carries was made exactly on time.
        result = session.press(0, 1.0)
        session.update(1.0 + MISS_WINDOW + 0.05)

        assert result is not None
        assert result.judgement is Judgement.PERFECT
        assert session.board.counts[Judgement.MISS] == 0

    def test_updating_first_would_have_lost_that_step(self) -> None:
        # The precondition that makes the test above meaningful: with the
        # order reversed, the very same on-time press is recorded as a miss
        # plus a stray. If this ever stops failing, the guard above is inert.
        session = session_for(tap(1.0, 0))

        session.update(1.0 + MISS_WINDOW + 0.05)
        result = session.press(0, 1.0)

        assert result is None
        assert session.board.counts[Judgement.MISS] == 1
        assert session.board.stray_presses == 1


class TestHolds:
    def test_a_hold_held_to_its_tail_keeps_the_head_judgement(self) -> None:
        session = session_for(hold(1.0, 2.0, 2))
        result = session.press(2, 1.0)

        assert result is not None
        assert result.judgement is Judgement.PERFECT
        assert session.is_held(0)

        assert session.update(2.0) == []
        assert session.state[0] is NoteState.DONE
        assert session.board.counts[Judgement.PERFECT] == 1
        assert session.board.counts[Judgement.MISS] == 0

    def test_releasing_early_turns_the_hold_into_a_miss(self) -> None:
        session = session_for(hold(1.0, 3.0, 2))
        session.press(2, 1.0)
        # Precondition: the head really was banked as a Perfect, so the
        # reclassification below is doing work rather than describing a no-op.
        assert session.board.counts[Judgement.PERFECT] == 1

        result = session.release(2, 1.5)

        assert result is not None
        assert result.judgement is Judgement.MISS
        assert session.board.counts[Judgement.PERFECT] == 0
        assert session.board.counts[Judgement.MISS] == 1
        assert session.combo == 0

    def test_releasing_inside_the_grace_still_completes(self) -> None:
        session = session_for(hold(1.0, 3.0, 2))
        session.press(2, 1.0)

        assert session.release(2, 3.0 - HOLD_RELEASE_GRACE + 0.001) is None
        assert session.state[0] is NoteState.DONE
        assert session.board.counts[Judgement.MISS] == 0

    def test_a_hold_whose_head_is_never_hit_expires_like_a_tap(self) -> None:
        session = session_for(hold(1.0, 3.0, 2))
        results = session.update(1.0 + MISS_WINDOW + 0.001)

        assert [r.judgement for r in results] == [Judgement.MISS]

    def test_a_broken_hold_costs_life_on_top_of_what_the_head_earned(self) -> None:
        # Deliberate: the tally is corrected but the life bar is not rewound,
        # because the bar is read continuously and a backwards jump would be
        # unreadable. Pinned so the asymmetry is a decision, not a bug.
        session = session_for(hold(1.0, 3.0, 2))
        session.press(2, 1.0)
        session.release(2, 1.5)

        expected = STARTING_LIFE + LIFE_DELTA[Judgement.PERFECT] + LIFE_DELTA[Judgement.MISS]
        assert session.life == pytest.approx(expected)

    def test_releasing_a_column_holding_nothing_is_harmless(self) -> None:
        session = session_for(tap(1.0, 0))
        assert session.release(4, 1.0) is None


class TestMines:
    def test_a_mine_passed_with_the_panel_down_drains_life(self) -> None:
        session = session_for(mine(1.0, 3))
        session.press(3, 0.5)  # a stray press that leaves the panel down
        session.update(1.0)

        assert session.board.mines_hit == 1
        assert session.life < STARTING_LIFE

    def test_a_mine_passed_with_the_panel_up_is_harmless(self) -> None:
        session = session_for(mine(1.0, 3))
        session.update(1.0)

        assert session.board.mines_hit == 0
        assert session.life == STARTING_LIFE

    def test_lifting_off_before_a_mine_avoids_it(self) -> None:
        session = session_for(mine(1.0, 3))
        session.press(3, 0.5)
        session.release(3, 0.9)
        session.update(1.0)

        assert session.board.mines_hit == 0

    def test_mines_never_enter_the_judgement_counts(self) -> None:
        session = session_for(mine(1.0, 3), tap(2.0, 0))
        session.press(3, 0.5)
        session.update(1.0)

        assert session.board.judged == 0
        assert session.combo == 0
        # And they are not part of what a full combo has to cover.
        assert session.board.total_notes == 1

    def test_a_mine_is_hit_even_when_the_frame_notices_late(self) -> None:
        # Regression. The check used to be "is the panel down at this instant",
        # evaluated on whichever frame happened to notice the mine had passed.
        # Here the foot was squarely on the panel as the mine went by and was
        # lifted before the frame arrived, so the old rule scored it as clean.
        session = session_for(mine(1.0, 3))
        session.press(3, 0.8)
        session.release(3, 1.2)
        session.update(1.5)

        assert session.board.mines_hit == 1

    def test_a_step_taken_after_a_mine_passed_does_not_hit_it(self) -> None:
        # The other half of the same bug: a press made well after the mine was
        # gone used to count, because the frame that noticed the mine saw the
        # panel down. Frame rate must not decide either way.
        session = session_for(mine(1.0, 3))
        session.press(3, 1.4)
        session.update(1.5)

        assert session.board.mines_hit == 0

    def test_a_press_cannot_be_matched_to_a_mine(self) -> None:
        session = session_for(mine(1.0, 3))
        assert session.press(3, 1.0) is None
        assert session.board.stray_presses == 1


class TestLife:
    def test_life_cannot_exceed_the_maximum(self) -> None:
        session = session_for(*[tap(1.0 + i * 0.5, 0) for i in range(200)])
        for i in range(200):
            session.press(0, 1.0 + i * 0.5)
        assert session.life <= 1.0

    def test_enough_misses_fail_the_stage(self) -> None:
        session = session_for(*[tap(1.0 + i, 0) for i in range(20)])
        assert not session.failed

        session.update(30.0)
        assert session.failed
        assert session.life == 0.0

    def test_a_stage_does_not_fail_on_a_single_slip(self) -> None:
        # A bar that fails instantly is not a bar. Guards against someone
        # scaling LIFE_DELTA without noticing what it does to the floor.
        session = session_for(*[tap(1.0 + i, 0) for i in range(20)])
        session.update(1.0 + MISS_WINDOW + 0.001)
        assert not session.failed


class TestScoring:
    def test_a_clean_run_is_a_full_combo(self) -> None:
        session = session_for(*[tap(1.0 + i * 0.5, i % 5) for i in range(10)])
        for i in range(10):
            session.press(i % 5, 1.0 + i * 0.5)

        assert session.board.full_combo
        assert session.board.max_combo == 10
        assert session.board.accuracy == pytest.approx(1.0)
        assert session.board.grade is Grade.SSS

    def test_accuracy_is_measured_against_the_whole_chart(self) -> None:
        # An abandoned stage must not read as perfect on the notes it did see.
        session = session_for(*[tap(1.0 + i, 0) for i in range(4)])
        session.press(0, 1.0)

        assert session.board.accuracy == pytest.approx(0.25)
        assert session.board.grade is Grade.F

    def test_a_bad_scores_nothing_but_is_still_a_judged_note(self) -> None:
        # Comfortably inside the Bad window rather than exactly on it: adding
        # the window to a note time and subtracting it back does not round-trip
        # in binary floating point, so an on-the-boundary press here lands a
        # fraction outside and is rejected. The boundary itself is exact in
        # `test_judge.py`, where no arithmetic intervenes.
        session = session_for(tap(1.0, 0))
        result = session.press(0, 1.150)

        assert result is not None
        assert result.judgement is Judgement.BAD
        assert session.board.accuracy == pytest.approx(0.0)
        assert session.board.judged == 1
        assert not session.board.full_combo

    def test_max_combo_survives_a_later_break(self) -> None:
        session = session_for(tap(1.0, 0), tap(2.0, 0), tap(3.0, 0))
        session.press(0, 1.0)
        session.press(0, 2.0)
        assert session.board.max_combo == 2

        session.update(3.0 + MISS_WINDOW + 0.001)
        assert session.combo == 0
        assert session.board.max_combo == 2


class TestProgress:
    def test_a_session_finishes_once_every_note_is_resolved(self) -> None:
        session = session_for(tap(1.0, 0), tap(2.0, 1))
        assert not session.finished

        session.press(0, 1.0)
        session.update(1.0)
        assert not session.finished

        session.update(5.0)
        assert session.finished

    def test_an_empty_chart_is_finished_immediately(self) -> None:
        session = session_for()
        assert session.finished
        assert session.board.accuracy == 0.0
        # Nothing was played, so nothing was full-comboed.
        assert not session.board.full_combo
