"""One stage in progress: notes, presses, and everything that follows.

This is the whole of gameplay, and it is deliberately free of pygame, of
rendering, and of any clock of its own. It is a function of "what the chart
says" and "what the player did, and when" - nothing else. That is what makes it
testable: `tests/test_session.py` plays entire charts through it with scripted
input and no display, no audio and no browser, and the results are exact rather
than approximate.

The frame contract
------------------
A caller must, once per frame, in this order:

1. Drain input events and call `press` / `release` with the timestamp the
   *input* carried, not the current song position.
2. Call `update(now)` with the current song position.

The order matters. Input is stamped at the DOM keydown (see
``tools/web_audio.js``), so a press always arrives with a timestamp slightly in
the past. Expiring notes first would let a step that was made in time be
recorded as a miss because the frame it arrived on was late. Processing input
first cannot have the opposite problem: a note expired on an earlier frame was
already out of reach of any input stamped since.

Why misses are found by expiry rather than by scanning
------------------------------------------------------
A note becomes a miss when the song passes it, which means something has to
notice the absence of an event. `update` walks forward from a cursor rather
than scanning the chart, so per-frame work is proportional to notes going by
rather than notes in the chart - the same budget rule the renderer follows.

This module must not import pygame.
"""

from __future__ import annotations

from enum import Enum

from piu.formats.chart import Chart, Note, NoteKind
from piu.gameplay.judge import (
    FAILURE_LIFE,
    LIFE_DELTA,
    MAXIMUM_LIFE,
    MINE_LIFE_PENALTY,
    MISS_WINDOW,
    STARTING_LIFE,
    HitResult,
    Judgement,
    judge_offset,
)
from piu.gameplay.scoring import Scoreboard

#: How early a hold may be released and still count as completed. Without a
#: grace the tail is a second, invisible timing window that the player gets no
#: feedback on, which punishes a step nobody asked them to make precisely.
HOLD_RELEASE_GRACE = Judgement.GREAT.window


class NoteState(Enum):
    """Where a note is in its life. Every note ends at DONE."""

    PENDING = "pending"
    #: A hold whose head was judged and whose panel is still down.
    HELD = "held"
    DONE = "done"


class PlaySession:
    """Mutable state of one stage being played."""

    def __init__(self, chart: Chart) -> None:
        self.chart = chart
        self.notes: list[Note] = chart.notes
        self.state: list[NoteState] = [NoteState.PENDING] * len(self.notes)
        self.board = Scoreboard(total_notes=chart.tap_count)
        self.life = STARTING_LIFE
        self.failed = False

        #: Judgement the head of each active hold received, so a broken hold
        #: can correct the tally it already wrote.
        self._head: dict[int, Judgement] = {}
        #: Column -> index of the hold currently being held in it.
        self._holding: dict[int, int] = {}
        #: When each column was last pressed and last released. Mines are
        #: judged against these rather than against a set of currently-down
        #: columns, because "is the panel down now" answers the wrong question:
        #: a mine is stepped on by being under a foot *as it passes*, and the
        #: frame that notices it passed arrives afterwards. Timestamps make the
        #: rule independent of frame rate, which is the same reason input is
        #: stamped at the DOM event rather than polled.
        self._press_at: dict[int, float] = {}
        self._release_at: dict[int, float] = {}
        #: First note not yet finalised. Everything before it is DONE.
        self._cursor = 0

    # ----------------------------------------------------------------- input

    def press(self, column: int, time: float) -> HitResult | None:
        """Register a panel going down. Returns the note it judged, if any."""
        self._press_at[column] = time

        index = self._nearest_pending(column, time)
        if index is None:
            self.board.stray_presses += 1
            return None

        note = self.notes[index]
        offset = time - note.time
        # Never a MISS: `_nearest_pending` bounds the distance by MISS_WINDOW,
        # which *is* the Bad window, so anything it returns grades to Bad at
        # worst. `tests/test_judge.py` pins that invariant, because if the two
        # bounds ever drift apart this silently starts judging unhittable notes.
        judgement = judge_offset(offset)

        self.board.record(judgement)
        self._apply_life(LIFE_DELTA[judgement])

        if note.is_hold:
            self.state[index] = NoteState.HELD
            self._head[index] = judgement
            self._holding[column] = index
        else:
            self._finish(index)

        return HitResult(index, column, judgement, offset, time)

    def release(self, column: int, time: float) -> HitResult | None:
        """Register a panel coming up. Returns a result only if a hold broke."""
        self._release_at[column] = time

        index = self._holding.pop(column, None)
        if index is None:
            return None

        note = self.notes[index]
        end = note.end_time if note.end_time is not None else note.time
        if time >= end - HOLD_RELEASE_GRACE:
            # Close enough to the tail to count as seeing it through.
            self._finish(index)
            return None

        return self._break_hold(index, column, time)

    # ----------------------------------------------------------------- clock

    def update(self, now: float) -> list[HitResult]:
        """Advance to song position ``now``. Returns misses and broken holds."""
        results: list[HitResult] = []

        for index in range(self._cursor, len(self.notes)):
            note = self.notes[index]
            state = self.state[index]

            if state is NoteState.DONE:
                continue

            if state is NoteState.HELD:
                end = note.end_time if note.end_time is not None else note.time
                if now >= end:
                    self._holding.pop(note.column, None)
                    self._finish(index)
                continue

            if note.time > now + MISS_WINDOW:
                # Time-sorted, so nothing beyond here is reachable either.
                break

            if note.kind is NoteKind.MINE:
                if now >= note.time:
                    if self._was_down_at(note.column, note.time):
                        self.board.mines_hit += 1
                        self._apply_life(MINE_LIFE_PENALTY)
                    self._finish(index)
                continue

            if now > note.time + MISS_WINDOW:
                self.board.record(Judgement.MISS)
                self._apply_life(LIFE_DELTA[Judgement.MISS])
                self._finish(index)
                results.append(HitResult(index, note.column, Judgement.MISS, 0.0, now))

        self._advance_cursor()
        return results

    # ------------------------------------------------------------- reporting

    @property
    def finished(self) -> bool:
        """Whether every note has been resolved one way or another."""
        return self._cursor >= len(self.notes)

    @property
    def combo(self) -> int:
        return self.board.combo

    def is_held(self, index: int) -> bool:
        return self.state[index] is NoteState.HELD

    # --------------------------------------------------------------- private

    def _nearest_pending(self, column: int, time: float) -> int | None:
        """Index of the closest unjudged note in ``column``, or None.

        Only notes within the miss window are considered, so a press in a lane
        whose next note is seconds away is a stray rather than a very early hit.
        """
        best_index: int | None = None
        best_distance = MISS_WINDOW

        for index in range(self._cursor, len(self.notes)):
            note = self.notes[index]
            if note.time > time + MISS_WINDOW:
                break
            if note.column != column or note.kind is NoteKind.MINE:
                continue
            if self.state[index] is not NoteState.PENDING:
                continue
            distance = abs(time - note.time)
            if distance <= best_distance:
                best_distance = distance
                best_index = index

        return best_index

    def _break_hold(self, index: int, column: int, time: float) -> HitResult:
        """Fail a hold that was let go early.

        The head's judgement is corrected in the tally but *not* refunded from
        the life bar. The tally is read once, at the end, and should describe
        what actually happened. The bar is read continuously, and rewinding a
        gain the player already saw would make it unreadable - so the miss
        simply costs what a miss costs, on top of what the head earned.
        """
        was = self._head.pop(index, Judgement.PERFECT)
        self.board.reclassify(was, Judgement.MISS)
        if not was.breaks_combo:
            self.board.combo = 0
        self._apply_life(LIFE_DELTA[Judgement.MISS])
        self._finish(index)
        return HitResult(index, column, Judgement.MISS, 0.0, time)

    def _was_down_at(self, column: int, when: float) -> bool:
        """Whether ``column``'s panel was held at song position ``when``.

        Only the most recent press and release are kept, which is enough: a
        mine is resolved on the first frame after it passes, so a column cannot
        have been pressed and released more than once in between at any
        plausible frame rate.
        """
        pressed = self._press_at.get(column)
        if pressed is None or pressed > when:
            return False
        released = self._release_at.get(column)
        if released is None or released < pressed:
            # Never released, or released before this press - still down.
            return True
        return released >= when

    def _finish(self, index: int) -> None:
        self.state[index] = NoteState.DONE
        self._head.pop(index, None)

    def _advance_cursor(self) -> None:
        while (
            self._cursor < len(self.notes)
            and self.state[self._cursor] is NoteState.DONE
        ):
            self._cursor += 1

    def _apply_life(self, delta: float) -> None:
        self.life = max(0.0, min(MAXIMUM_LIFE, self.life + delta))
        if self.life <= FAILURE_LIFE:
            self.failed = True
