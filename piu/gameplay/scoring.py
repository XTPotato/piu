"""Turning a pile of judgements into a percentage and a letter.

Split from `piu.gameplay.judge` because the two answer different questions and
change for different reasons. `judge` decides what one step was worth, and its
numbers are timing physics. This decides what a whole stage was worth, and its
numbers are a curve someone chose. Expect the curve below to be argued about;
expect the windows not to be.

Why accuracy rather than a point total
--------------------------------------
Pump It Up's real scoring is a point total with combo bonuses, and the exact
formula differs between releases. Reproducing a specific release's arithmetic
would be guessing at unpublished constants, and the guess would be invisible -
a wrong grade looks exactly like a right one. Weighted accuracy is chart-length
independent, is obvious to explain, and does not pretend to an authority it
does not have. A point total can be layered on later without moving the grade,
because the grade reads the ratio and not the points.

This module must not import pygame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from piu.gameplay.judge import SCORE_WEIGHT, Judgement


class Grade(Enum):
    """Stage letter, best to worst. Value is the accuracy floor to earn it."""

    SSS = 0.99
    SS = 0.97
    S = 0.94
    A = 0.90
    B = 0.80
    C = 0.70
    D = 0.60
    F = 0.0


#: Ordered best-first, so `grade_for` returns the first grade a run clears.
GRADE_ORDER: tuple[Grade, ...] = (
    Grade.SSS,
    Grade.SS,
    Grade.S,
    Grade.A,
    Grade.B,
    Grade.C,
    Grade.D,
    Grade.F,
)


def grade_for(accuracy: float) -> Grade:
    """The letter earned by ``accuracy``, a ratio in 0..1."""
    for grade in GRADE_ORDER:
        if accuracy >= grade.value:
            return grade
    return Grade.F


@dataclass(slots=True)
class Scoreboard:
    """Running tally for one stage.

    Mutable and updated in place, because it is read every frame by the HUD and
    allocating a new one per note would be the wrong trade in the hot loop.
    """

    total_notes: int = 0
    counts: dict[Judgement, int] = field(default_factory=dict)
    combo: int = 0
    max_combo: int = 0
    mines_hit: int = 0
    #: Presses that matched no note. Not a judgement and not a penalty - a
    #: diagnostic, the same quantity `offsets.unmatched_inputs` reports.
    stray_presses: int = 0

    def __post_init__(self) -> None:
        for judgement in Judgement:
            self.counts.setdefault(judgement, 0)

    def record(self, judgement: Judgement) -> None:
        self.counts[judgement] += 1
        if judgement.breaks_combo:
            self.combo = 0
        else:
            self.combo += 1
            if self.combo > self.max_combo:
                self.max_combo = self.combo

    def reclassify(self, was: Judgement, now: Judgement) -> None:
        """Move one note from one judgement to another after the fact.

        Only a broken hold does this: the head was judged when it was hit, and
        the note turned out to be worse than that judgement once the player let
        go. The tally is what the results screen reports, so it should describe
        what happened rather than what looked true at the time.
        """
        if self.counts[was] > 0:
            self.counts[was] -= 1
        self.counts[now] += 1

    @property
    def judged(self) -> int:
        return sum(self.counts.values())

    @property
    def accuracy(self) -> float:
        """Weighted accuracy over the whole chart, in 0..1.

        Divided by the chart's note count rather than by notes judged so far,
        so a stage abandoned early reads as a low score instead of a perfect
        one on three notes.
        """
        if self.total_notes <= 0:
            return 0.0
        earned = sum(
            SCORE_WEIGHT[judgement] * count for judgement, count in self.counts.items()
        )
        return earned / self.total_notes

    @property
    def grade(self) -> Grade:
        return grade_for(self.accuracy)

    @property
    def full_combo(self) -> bool:
        """Whether every note was hit without breaking combo."""
        return (
            self.judged == self.total_notes
            and self.total_notes > 0
            and self.counts[Judgement.BAD] == 0
            and self.counts[Judgement.MISS] == 0
        )

    def describe(self) -> str:
        return "{} {:.2f}% combo {} / {}".format(
            self.grade.name, self.accuracy * 100.0, self.max_combo, self.total_notes
        )
