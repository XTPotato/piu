"""Beat/time conversion tests.

These run headless: no display, no audio device, no pygame.
"""

from __future__ import annotations

import pytest

from piu.core.timing import (
    BpmSegment,
    StopSegment,
    TimingData,
    WarpSegment,
)


class TestConstantBpm:
    def test_beats_convert_to_seconds(self) -> None:
        timing = TimingData.constant(120.0)
        assert timing.beat_to_time(0.0) == pytest.approx(0.0)
        assert timing.beat_to_time(1.0) == pytest.approx(0.5)
        assert timing.beat_to_time(4.0) == pytest.approx(2.0)

    def test_inverse_recovers_the_beat(self) -> None:
        timing = TimingData.constant(120.0)
        assert timing.time_to_beat(2.0) == pytest.approx(4.0)
        assert timing.time_to_beat(0.5) == pytest.approx(1.0)

    def test_offset_shifts_beat_zero(self) -> None:
        # StepMania convention: beat 0 lands at -offset seconds.
        timing = TimingData.constant(120.0, offset=-1.5)
        assert timing.beat_to_time(0.0) == pytest.approx(1.5)
        assert timing.beat_to_time(4.0) == pytest.approx(3.5)
        assert timing.time_to_beat(1.5) == pytest.approx(0.0)

    def test_lead_in_before_beat_zero_is_negative(self) -> None:
        timing = TimingData.constant(120.0)
        assert timing.time_to_beat(-1.0) == pytest.approx(-2.0)


class TestBpmChanges:
    def test_time_accumulates_per_segment(self) -> None:
        timing = TimingData(
            bpms=[BpmSegment(0.0, 120.0), BpmSegment(4.0, 240.0)]
        )
        assert timing.beat_to_time(4.0) == pytest.approx(2.0)
        # Four beats at 240 BPM is one further second.
        assert timing.beat_to_time(8.0) == pytest.approx(3.0)
        assert timing.time_to_beat(3.0) == pytest.approx(8.0)

    def test_bpm_lookup(self) -> None:
        timing = TimingData(
            bpms=[BpmSegment(0.0, 120.0), BpmSegment(4.0, 240.0)]
        )
        assert timing.bpm_at(0.0) == 120.0
        assert timing.bpm_at(3.9) == 120.0
        assert timing.bpm_at(4.0) == 240.0

    def test_implicit_segment_at_beat_zero(self) -> None:
        # A chart whose first BPM is declared late still starts sensibly.
        timing = TimingData(bpms=[BpmSegment(8.0, 200.0)])
        assert timing.bpm_at(0.0) == 200.0

    def test_negative_bpm_is_rejected(self) -> None:
        # Parsers must translate negative BPMs into warps before this point.
        with pytest.raises(ValueError, match="non-positive BPM"):
            TimingData(bpms=[BpmSegment(0.0, -120.0)])


class TestStops:
    def test_note_on_the_stop_beat_is_hit_when_the_stop_begins(self) -> None:
        timing = TimingData(
            bpms=[BpmSegment(0.0, 120.0)], stops=[StopSegment(4.0, 1.0)]
        )
        assert timing.beat_to_time(4.0) == pytest.approx(2.0)

    def test_later_beats_are_pushed_back(self) -> None:
        timing = TimingData(
            bpms=[BpmSegment(0.0, 120.0)], stops=[StopSegment(4.0, 1.0)]
        )
        assert timing.beat_to_time(5.0) == pytest.approx(3.5)

    def test_beat_is_frozen_for_the_duration(self) -> None:
        timing = TimingData(
            bpms=[BpmSegment(0.0, 120.0)], stops=[StopSegment(4.0, 1.0)]
        )
        assert timing.time_to_beat(2.0) == pytest.approx(4.0)
        assert timing.time_to_beat(2.5) == pytest.approx(4.0)
        assert timing.time_to_beat(3.0) == pytest.approx(4.0)
        assert timing.time_to_beat(3.5) == pytest.approx(5.0)

    def test_zero_length_stops_are_discarded(self) -> None:
        timing = TimingData(
            bpms=[BpmSegment(0.0, 120.0)], stops=[StopSegment(4.0, 0.0)]
        )
        assert timing.stops == ()
        assert timing.beat_to_time(5.0) == pytest.approx(2.5)

    def test_multiple_stops_accumulate(self) -> None:
        timing = TimingData(
            bpms=[BpmSegment(0.0, 120.0)],
            stops=[StopSegment(2.0, 0.25), StopSegment(4.0, 0.5)],
        )
        assert timing.beat_to_time(6.0) == pytest.approx(3.0 + 0.75)


class TestDelays:
    def test_delay_elapses_before_its_beat(self) -> None:
        timing = TimingData(
            bpms=[BpmSegment(0.0, 120.0)],
            stops=[StopSegment(4.0, 1.0, is_delay=True)],
        )
        # Unlike a stop, the note on beat 4 waits out the delay first.
        assert timing.beat_to_time(4.0) == pytest.approx(3.0)
        assert timing.beat_to_time(5.0) == pytest.approx(3.5)

    def test_beat_is_frozen_during_the_delay(self) -> None:
        timing = TimingData(
            bpms=[BpmSegment(0.0, 120.0)],
            stops=[StopSegment(4.0, 1.0, is_delay=True)],
        )
        assert timing.time_to_beat(2.0) == pytest.approx(4.0)
        assert timing.time_to_beat(2.5) == pytest.approx(4.0)
        assert timing.time_to_beat(3.5) == pytest.approx(5.0)


class TestWarps:
    def test_warped_beats_consume_no_time(self) -> None:
        timing = TimingData(
            bpms=[BpmSegment(0.0, 120.0)], warps=[WarpSegment(4.0, 4.0)]
        )
        assert timing.beat_to_time(4.0) == pytest.approx(2.0)
        assert timing.beat_to_time(8.0) == pytest.approx(2.0)
        assert timing.beat_to_time(12.0) == pytest.approx(4.0)

    def test_warp_membership(self) -> None:
        timing = TimingData(
            bpms=[BpmSegment(0.0, 120.0)], warps=[WarpSegment(4.0, 4.0)]
        )
        assert not timing.is_warped(3.9)
        assert timing.is_warped(4.0)
        assert timing.is_warped(7.9)
        assert not timing.is_warped(8.0)

    def test_playback_lands_past_the_warp(self) -> None:
        timing = TimingData(
            bpms=[BpmSegment(0.0, 120.0)], warps=[WarpSegment(4.0, 4.0)]
        )
        assert timing.time_to_beat(2.0) == pytest.approx(8.0)

    def test_overlapping_warps_are_merged(self) -> None:
        timing = TimingData(
            bpms=[BpmSegment(0.0, 120.0)],
            warps=[WarpSegment(4.0, 4.0), WarpSegment(6.0, 4.0)],
        )
        assert len(timing.warps) == 1
        assert timing.warps[0].beat == 4.0
        assert timing.warps[0].length == 6.0


class TestInvariants:
    """Properties that must hold for any combination of timing features."""

    @staticmethod
    def _mixed() -> TimingData:
        return TimingData(
            offset=-0.75,
            bpms=[
                BpmSegment(0.0, 128.0),
                BpmSegment(16.0, 96.0),
                BpmSegment(32.0, 200.0),
            ],
            stops=[StopSegment(20.0, 0.4), StopSegment(24.0, 0.15)],
        )

    def test_beat_to_time_is_monotonic(self) -> None:
        timing = self._mixed()
        previous = float("-inf")
        beat = 0.0
        while beat <= 48.0:
            current = timing.beat_to_time(beat)
            assert current >= previous
            previous = current
            beat += 0.25

    def test_round_trip_through_seconds(self) -> None:
        timing = self._mixed()
        beat = 0.0
        while beat <= 48.0:
            seconds = timing.beat_to_time(beat)
            assert timing.time_to_beat(seconds) == pytest.approx(beat, abs=1e-9)
            beat += 0.25

    def test_round_trip_survives_a_warp(self) -> None:
        # Warped beats are unreachable by design, so only check outside them.
        timing = TimingData(
            bpms=[BpmSegment(0.0, 150.0)], warps=[WarpSegment(8.0, 4.0)]
        )
        for beat in (0.0, 4.0, 7.5, 12.0, 16.0, 32.0):
            seconds = timing.beat_to_time(beat)
            assert timing.time_to_beat(seconds) == pytest.approx(beat, abs=1e-9)
