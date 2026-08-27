"""The judgement ruleset: how far off a step may be, and what it costs.

Every number here is a design decision that gameplay elsewhere reads rather
than reimplements. Keeping them in one module means the windows, the combo
rule, the life cost and the score weight of a judgement cannot drift apart -
which they will if each screen decides for itself what a Bad is worth.

Why the windows are multiples of one twenty-fourth of a second
--------------------------------------------------------------
Pump It Up is a fixed-timestep arcade game and its judgement windows are
conventionally quoted as 42 / 83 / 125 / 167ms. Those are not arbitrary: they
are 1, 2, 3 and 4 times 1/24s to within a millisecond. Deriving them from a
single unit rather than hard-coding four rounded constants keeps the ratios
exact and makes the one number worth tuning obvious.

This is an informed reconstruction, not a specification. Andamiro publishes no
window table, so these values are an assumption in the same category as the
`.ucs` semantics: pinned by tests so a change is deliberate and visible, and
worth validating against real play before being trusted. `tests/test_judge.py`
is where that assumption lives.

Why the sign convention is input-minus-expected
-----------------------------------------------
Negative is early, positive is late, matching `piu.gameplay.offsets`. The two
modules measure the same quantity and disagreeing about its sign would be a
bug that reads as a calibration error.

This module must not import pygame.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: The unit every window is built from. 1/24s is where the conventional
#: 42/83/125/167ms table comes from; see the module docstring.
JUDGEMENT_UNIT = 1.0 / 24.0


class Judgement(Enum):
    """How well a note was hit, best to worst.

    The value is the multiple of `JUDGEMENT_UNIT` at which the window closes.
    `MISS` has no window: it is what happens when no input arrives at all, so
    its bound is the point past which a note can no longer be hit.
    """

    PERFECT = 1
    GREAT = 2
    GOOD = 3
    BAD = 4
    MISS = 0

    @property
    def window(self) -> float:
        """Half-width of this judgement's window, in seconds."""
        return self.value * JUDGEMENT_UNIT

    @property
    def breaks_combo(self) -> bool:
        """Whether receiving this judgement resets the combo to zero.

        Good keeps the combo. That is the arcade behaviour and it matters for
        feel: a run of slightly loose steps should cost score without erasing
        the evidence that the player was still on the chart.
        """
        return self in (Judgement.BAD, Judgement.MISS)

    @property
    def is_hit(self) -> bool:
        """Whether a note with this judgement was touched at all."""
        return self is not Judgement.MISS


#: Past this, a note is no longer hittable and becomes a Miss. It is exactly
#: the Bad window, so there is one boundary rather than two that must be kept
#: in step - a note is either inside some judgement's window or it is gone.
MISS_WINDOW = Judgement.BAD.window

#: Ordered best-first. `judge_offset` walks this, so the order is load-bearing
#: rather than cosmetic: the first window a step fits inside is the one it gets.
JUDGEMENT_ORDER: tuple[Judgement, ...] = (
    Judgement.PERFECT,
    Judgement.GREAT,
    Judgement.GOOD,
    Judgement.BAD,
)


def judge_offset(offset: float) -> Judgement:
    """Grade a step whose timing error is ``offset`` seconds.

    Negative is early, positive is late. Returns `MISS` for anything outside
    the Bad window, which is the same thing as saying the step did not belong
    to this note.
    """
    distance = abs(offset)
    for judgement in JUDGEMENT_ORDER:
        if distance <= judgement.window:
            return judgement
    return Judgement.MISS


#: Life change per judgement, as a fraction of a full bar.
#:
#: Asymmetric on purpose, and the asymmetry is the whole design: recovery is
#: slower than loss, so a bar that has been drained stays a real problem for
#: several bars afterwards rather than refilling during the next easy run. A
#: Good neither helps nor hurts - it is the "you are still on the chart"
#: judgement, and it should not be a way to heal.
LIFE_DELTA: dict[Judgement, float] = {
    Judgement.PERFECT: 0.008,
    Judgement.GREAT: 0.004,
    Judgement.GOOD: 0.0,
    Judgement.BAD: -0.030,
    Judgement.MISS: -0.060,
}

#: Score weight per judgement, as a fraction of a note's maximum value. Used to
#: compute the percentage the grade is read from, so these are ratios rather
#: than point values and do not need to be scaled to a chart's length.
SCORE_WEIGHT: dict[Judgement, float] = {
    Judgement.PERFECT: 1.0,
    Judgement.GREAT: 0.6,
    Judgement.GOOD: 0.2,
    Judgement.BAD: 0.0,
    Judgement.MISS: 0.0,
}

#: What stepping on a mine costs. Mines are not notes: they never appear in the
#: judgement counts, never touch the combo, and cannot be "hit" well or badly.
#: The only thing they do is drain, which is why the cost sits here alone.
MINE_LIFE_PENALTY = -0.050

#: Life a stage begins with, and the level below which it fails. Starting at
#: half rather than full means the bar reads as a two-sided gauge from the
#: first note instead of a resource that only ever depletes.
STARTING_LIFE = 0.5
FAILURE_LIFE = 0.0
MAXIMUM_LIFE = 1.0


@dataclass(frozen=True, slots=True)
class HitResult:
    """One judged note. Produced by the session, consumed by UI and results."""

    note_index: int
    column: int
    judgement: Judgement
    #: Seconds early (negative) or late (positive). Zero for a Miss, which had
    #: no input to measure - check `judgement` before reading this.
    offset: float
    #: Song position at which the judgement was decided, for hit animations.
    time: float

    def describe(self) -> str:
        if self.judgement is Judgement.MISS:
            return "{} miss".format(self.column)
        return "{} {} {:+.0f}ms".format(
            self.column, self.judgement.name.lower(), self.offset * 1000.0
        )
