"""Song clock and offset-analysis tests.

The browser clock cannot be exercised headlessly, so the arithmetic every
implementation shares is verified against `ManualClock`, and the gate's verdict
logic is verified directly. A gate whose pass condition has never been tested
is not a gate.
"""

from __future__ import annotations

import pytest

from piu.core.clock import ClockError, ManualClock, WebAudioClock
from piu.gameplay import offsets


class TestManualClock:
    def test_starts_stopped_at_zero(self) -> None:
        clock = ManualClock(duration=10.0)
        assert clock.position() == pytest.approx(0.0)
        assert not clock.playing

    def test_advances_only_while_playing(self) -> None:
        clock = ManualClock()
        clock.advance(1.0)
        assert clock.position() == pytest.approx(0.0)

        clock.start()
        clock.advance(1.0)
        assert clock.position() == pytest.approx(1.0)

    def test_start_at_seeks(self) -> None:
        clock = ManualClock()
        clock.start(at=30.0)
        clock.advance(0.5)
        assert clock.position() == pytest.approx(30.5)

    def test_pause_freezes_and_resume_continues(self) -> None:
        clock = ManualClock()
        clock.start()
        clock.advance(1.0)
        clock.pause()
        clock.advance(5.0)
        assert clock.position() == pytest.approx(1.0)

        clock.resume()
        clock.advance(0.5)
        assert clock.position() == pytest.approx(1.5)

    def test_stop_halts(self) -> None:
        clock = ManualClock()
        clock.start()
        clock.advance(1.0)
        clock.stop()
        clock.advance(1.0)
        assert clock.position() == pytest.approx(1.0)
        assert not clock.playing

    def test_offset_is_subtracted(self) -> None:
        # A positive calibration offset means the player is consistently late,
        # so the reported position is pulled back.
        clock = ManualClock(offset=0.020)
        clock.start()
        clock.advance(1.0)
        assert clock.position() == pytest.approx(0.980)

    def test_offset_can_be_changed_mid_song(self) -> None:
        clock = ManualClock()
        clock.start()
        clock.advance(1.0)
        clock.offset = 0.050
        assert clock.position() == pytest.approx(0.950)

    def test_negative_lead_in(self) -> None:
        # Starting at a negative position is a count-in, not an error.
        clock = ManualClock()
        clock.start(at=-2.0)
        assert clock.position() == pytest.approx(-2.0)
        clock.advance(1.0)
        assert clock.position() == pytest.approx(-1.0)

    def test_time_cannot_run_backwards(self) -> None:
        clock = ManualClock()
        clock.start()
        with pytest.raises(ValueError, match="backwards"):
            clock.advance(-0.1)

    def test_position_is_monotonic(self) -> None:
        clock = ManualClock()
        clock.start()
        previous = clock.position()
        for _ in range(200):
            clock.advance(1.0 / 240.0)
            current = clock.position()
            assert current >= previous
            previous = current


class TestWebAudioClockGuard:
    def test_refuses_to_construct_off_web(self) -> None:
        # Constructing this on the desktop means a missing platform guard.
        # Failing loudly here beats a confusing AttributeError later.
        with pytest.raises(ClockError, match="browser build"):
            WebAudioClock()


class TestMatching:
    def test_exact_inputs_give_zero_offsets(self) -> None:
        expected = [0.0, 0.5, 1.0, 1.5]
        found, unmatched, missed = offsets.match_inputs(list(expected), expected)
        assert found == pytest.approx([0.0, 0.0, 0.0, 0.0])
        assert not unmatched
        assert not missed

    def test_late_inputs_are_positive(self) -> None:
        found, _, _ = offsets.match_inputs([0.030, 0.530], [0.0, 0.5])
        assert found == pytest.approx([0.030, 0.030])

    def test_early_inputs_are_negative(self) -> None:
        found, _, _ = offsets.match_inputs([-0.020, 0.480], [0.0, 0.5])
        assert found == pytest.approx([-0.020, -0.020])

    def test_stray_input_is_not_matched(self) -> None:
        found, unmatched, _ = offsets.match_inputs([0.0, 5.0], [0.0, 0.5])
        assert len(found) == 1
        assert unmatched == pytest.approx([5.0])

    def test_missed_beat_is_reported(self) -> None:
        found, _, missed = offsets.match_inputs([0.0], [0.0, 0.5, 1.0])
        assert len(found) == 1
        assert missed == pytest.approx([0.5, 1.0])

    def test_each_expected_time_absorbs_one_input(self) -> None:
        # A double tap must not quietly count twice and flatter the results.
        found, unmatched, _ = offsets.match_inputs([0.0, 0.005], [0.0])
        assert len(found) == 1
        assert len(unmatched) == 1

    def test_window_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="window must be positive"):
            offsets.match_inputs([0.0], [0.0], window=0.0)


class TestSummarize:
    def test_empty_input_is_not_an_error(self) -> None:
        stats = offsets.summarize([])
        assert stats.count == 0
        assert stats.stdev == 0.0

    def test_single_sample_has_no_spread(self) -> None:
        # statistics.stdev raises on one value; this must not propagate.
        stats = offsets.summarize([0.01])
        assert stats.count == 1
        assert stats.stdev == 0.0
        assert stats.mean == pytest.approx(0.01)

    def test_reports_the_distribution(self) -> None:
        stats = offsets.summarize([0.010, 0.020, 0.030])
        assert stats.mean == pytest.approx(0.020)
        assert stats.median == pytest.approx(0.020)
        assert stats.minimum == pytest.approx(0.010)
        assert stats.maximum == pytest.approx(0.030)
        assert stats.spread == pytest.approx(0.020)

    def test_describe_is_in_milliseconds(self) -> None:
        text = offsets.summarize([0.010, 0.020]).describe()
        assert "n=2" in text
        assert "ms" in text


class TestGate:
    PERFECT = 0.042  # seconds, matching the default ruleset

    def test_tight_timing_passes(self) -> None:
        samples = [0.001, -0.002, 0.003, -0.001] * 5
        verdict = offsets.evaluate(offsets.summarize(samples), self.PERFECT)
        assert verdict.passed, verdict.reason

    def test_wide_spread_fails(self) -> None:
        samples = [-0.090, 0.085, -0.070, 0.075] * 5
        verdict = offsets.evaluate(offsets.summarize(samples), self.PERFECT)
        assert not verdict.passed
        assert "standard deviation" in verdict.reason

    def test_consistent_bias_still_passes(self) -> None:
        # A steady 30ms lateness is exactly what calibration removes, so it
        # must not fail the gate on its own.
        samples = [0.030, 0.031, 0.029, 0.030] * 5
        stats = offsets.summarize(samples)
        assert offsets.evaluate(stats, self.PERFECT).passed
        assert offsets.suggest_calibration(stats) == pytest.approx(0.030, abs=1e-3)

    def test_too_few_samples_is_inconclusive(self) -> None:
        verdict = offsets.evaluate(offsets.summarize([0.0, 0.001]), self.PERFECT)
        assert not verdict.passed
        assert "samples" in verdict.reason

    def test_skewed_distribution_fails(self) -> None:
        # Mostly tight, with a few wild outliers dragging the mean away from
        # the median: calibrating to that mean would mis-serve every player.
        samples = [0.000] * 20 + [0.240] * 6
        verdict = offsets.evaluate(offsets.summarize(samples), self.PERFECT)
        assert not verdict.passed

    def test_calibration_uses_the_median(self) -> None:
        # One catastrophically late tap must not move the suggestion much.
        stats = offsets.summarize([0.020] * 10 + [0.500])
        assert offsets.suggest_calibration(stats) == pytest.approx(0.020)


class TestAmbiguity:
    """Guards against an aliased run reporting confident nonsense.

    Nearest-neighbour matching can never report more than half a beat, so a
    player 300ms late on a 500ms beat produces the same tap pattern as one
    200ms early. The information to tell them apart is not in the data, so the
    run is refused rather than guessed at.
    """

    PERIOD = 0.5  # 120 BPM
    GRID = [i * 0.5 for i in range(24)]

    def stats_for(self, delta: float) -> offsets.OffsetStats:
        taps = [t + delta for t in self.GRID]
        matched, unmatched, missed = offsets.match_inputs(taps, self.GRID)
        return offsets.summarize(matched, len(unmatched), len(missed))

    def test_tight_timing_is_not_ambiguous(self) -> None:
        assert not offsets.is_ambiguous(self.stats_for(0.012), self.PERIOD)

    def test_a_normal_calibration_bias_is_not_ambiguous(self) -> None:
        # 40ms late is a plausible, correctable bias and must stay usable.
        assert not offsets.is_ambiguous(self.stats_for(0.040), self.PERIOD)

    def test_near_half_a_beat_is_ambiguous(self) -> None:
        # The reported case: no count-in, player lags badly, every tap slips
        # onto the following click.
        assert offsets.is_ambiguous(self.stats_for(0.30), self.PERIOD)

    def test_ambiguity_is_symmetric(self) -> None:
        assert offsets.is_ambiguous(self.stats_for(-0.30), self.PERIOD)

    def test_empty_run_is_not_ambiguous(self) -> None:
        assert not offsets.is_ambiguous(offsets.summarize([]), self.PERIOD)

    def test_zero_period_is_handled(self) -> None:
        assert not offsets.is_ambiguous(self.stats_for(0.012), 0.0)

    def test_ambiguous_run_fails_the_gate_despite_looking_perfect(self) -> None:
        # The dangerous case. Without the check this passes with a tight
        # spread and hands back a calibration of the wrong sign.
        stats = self.stats_for(0.30)
        assert stats.stdev == pytest.approx(0.0, abs=1e-9)
        assert offsets.evaluate(stats, 0.042).passed, (
            "precondition: unchecked, an aliased run passes the gate"
        )

        verdict = offsets.evaluate(
            stats, 0.042, ambiguous=offsets.is_ambiguous(stats, self.PERIOD)
        )
        assert not verdict.passed
        assert "half a beat" in verdict.reason

    def test_scales_with_tempo(self) -> None:
        # At 240 BPM the beat is 250ms, so the same 100ms offset that is fine
        # at 120 BPM becomes ambiguous.
        fast_period = 0.25
        grid = [i * fast_period for i in range(24)]
        taps = [t + 0.100 for t in grid]
        matched, unmatched, missed = offsets.match_inputs(taps, grid)
        stats = offsets.summarize(matched, len(unmatched), len(missed))
        assert offsets.is_ambiguous(stats, fast_period)
        assert not offsets.is_ambiguous(self.stats_for(0.100), self.PERIOD)


class TestPickup:
    """The count-in clicks sound but are never measured."""

    BPM = 120.0
    LEAD_IN = 2.0
    PICKUP = 4
    BEATS = 8

    def expected(self) -> list[float]:
        period = 60.0 / self.BPM
        first = self.LEAD_IN + self.PICKUP * period
        return [first + i * period for i in range(self.BEATS)]

    def test_measurement_starts_after_the_pickup(self) -> None:
        expected = self.expected()
        assert expected[0] == pytest.approx(4.0)
        assert len(expected) == self.BEATS

    def test_tapping_the_pickup_does_not_corrupt_the_run(self) -> None:
        # A player who taps along with the count-in produces four extra taps
        # before the first measured beat. They must be reported as unmatched
        # rather than absorbed into the measured window.
        period = 60.0 / self.BPM
        expected = self.expected()
        pickup_taps = [self.LEAD_IN + i * period for i in range(self.PICKUP)]
        good_taps = [t + 0.008 for t in expected]

        matched, unmatched, missed = offsets.match_inputs(
            pickup_taps + good_taps, expected
        )
        assert len(matched) == self.BEATS
        assert len(unmatched) == self.PICKUP
        assert not missed

        stats = offsets.summarize(matched, len(unmatched), len(missed))
        assert stats.mean == pytest.approx(0.008)
