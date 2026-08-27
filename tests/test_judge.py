"""Tests for the judgement ruleset.

These pin an *assumption*, not a specification. Andamiro publishes no window
table, so the 42/83/125/167ms figures are an informed reconstruction in the
same category as the `.ucs` semantics. The point of testing them is that
changing them should be a deliberate act with a visible diff, rather than
something that drifts while nobody is looking.
"""

from __future__ import annotations

import pytest

from piu.gameplay.judge import (
    JUDGEMENT_UNIT,
    LIFE_DELTA,
    MISS_WINDOW,
    SCORE_WEIGHT,
    Judgement,
    judge_offset,
)


class TestWindows:
    def test_windows_match_the_conventional_table(self) -> None:
        # The published-by-community figures, in milliseconds. If these ever
        # disagree with real play, this is the line to change.
        assert Judgement.PERFECT.window * 1000.0 == pytest.approx(41.67, abs=0.01)
        assert Judgement.GREAT.window * 1000.0 == pytest.approx(83.33, abs=0.01)
        assert Judgement.GOOD.window * 1000.0 == pytest.approx(125.0, abs=0.01)
        assert Judgement.BAD.window * 1000.0 == pytest.approx(166.67, abs=0.01)

    def test_windows_are_exact_multiples_of_one_unit(self) -> None:
        # Derived rather than hard-coded, so the ratios stay exact. A rounded
        # constant table would drift from these by up to a third of a millisecond.
        for judgement in (
            Judgement.PERFECT,
            Judgement.GREAT,
            Judgement.GOOD,
            Judgement.BAD,
        ):
            assert judgement.window == judgement.value * JUDGEMENT_UNIT

    def test_miss_window_is_exactly_the_bad_window(self) -> None:
        # `PlaySession.press` depends on this. It bounds its search for a
        # candidate note by MISS_WINDOW and then judges whatever it finds,
        # assuming the result cannot be a MISS. If these two ever diverge, a
        # press could be matched to a note it is not actually able to hit, and
        # the note would be recorded with a judgement no window admits.
        assert MISS_WINDOW == Judgement.BAD.window


class TestJudgingAnOffset:
    def test_a_dead_on_step_is_perfect(self) -> None:
        assert judge_offset(0.0) is Judgement.PERFECT

    def test_grading_degrades_with_distance(self) -> None:
        assert judge_offset(0.030) is Judgement.PERFECT
        assert judge_offset(0.060) is Judgement.GREAT
        assert judge_offset(0.100) is Judgement.GOOD
        assert judge_offset(0.150) is Judgement.BAD
        assert judge_offset(0.200) is Judgement.MISS

    def test_early_and_late_grade_identically(self) -> None:
        # The ruleset is symmetric; only calibration has an opinion about sign.
        for magnitude in (0.010, 0.050, 0.100, 0.150, 0.300):
            assert judge_offset(-magnitude) is judge_offset(magnitude)

    def test_window_boundaries_are_inclusive(self) -> None:
        # A step exactly on the boundary gets the better grade. Stated as a
        # test because the alternative is equally defensible and the choice
        # would otherwise be invisible.
        assert judge_offset(Judgement.PERFECT.window) is Judgement.PERFECT
        assert judge_offset(Judgement.GREAT.window) is Judgement.GREAT
        assert judge_offset(Judgement.BAD.window) is Judgement.BAD

    def test_just_past_the_bad_window_is_a_miss(self) -> None:
        assert judge_offset(Judgement.BAD.window + 0.001) is Judgement.MISS


class TestConsequences:
    def test_good_keeps_the_combo_and_bad_does_not(self) -> None:
        # The arcade behaviour, and the reason it matters: a run of loose steps
        # should cost score without erasing the evidence the player was on the
        # chart at all.
        assert not Judgement.PERFECT.breaks_combo
        assert not Judgement.GREAT.breaks_combo
        assert not Judgement.GOOD.breaks_combo
        assert Judgement.BAD.breaks_combo
        assert Judgement.MISS.breaks_combo

    def test_recovery_is_slower_than_loss(self) -> None:
        # The asymmetry is the design: a drained bar should stay a problem for
        # several bars rather than refilling over one easy run.
        assert LIFE_DELTA[Judgement.PERFECT] < abs(LIFE_DELTA[Judgement.MISS])
        assert abs(LIFE_DELTA[Judgement.MISS]) > abs(LIFE_DELTA[Judgement.BAD])

    def test_a_good_neither_heals_nor_hurts(self) -> None:
        assert LIFE_DELTA[Judgement.GOOD] == 0.0

    def test_every_judgement_has_a_life_and_score_entry(self) -> None:
        # A missing key here is a KeyError in the middle of a stage, which is
        # the worst possible time to discover it.
        for judgement in Judgement:
            assert judgement in LIFE_DELTA
            assert judgement in SCORE_WEIGHT

    def test_score_weight_falls_monotonically(self) -> None:
        order = [
            Judgement.PERFECT,
            Judgement.GREAT,
            Judgement.GOOD,
            Judgement.BAD,
            Judgement.MISS,
        ]
        weights = [SCORE_WEIGHT[j] for j in order]
        assert weights == sorted(weights, reverse=True)
        assert weights[0] == 1.0

    def test_only_a_miss_counts_as_untouched(self) -> None:
        assert Judgement.BAD.is_hit
        assert not Judgement.MISS.is_hit
