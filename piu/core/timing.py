"""Beat/time conversion: the foundation everything else is built on.

A chart is authored in beats; audio plays in seconds. TimingData converts
between the two in the presence of BPM changes, stops, delays, and warps.

Conventions
-----------
* ``offset`` follows the StepMania sign convention: beat 0 occurs at
  ``-offset`` seconds. So ``#OFFSET:-1.5`` means beat 0 lands 1.5 s into
  the audio.
* A **stop** at beat *b* pauses scrolling *after* beat *b* is reached, so a
  note on the stop beat is hit at the moment the stop begins.
* A **delay** at beat *b* pauses *before* beat *b* is reached, so a note on
  the delay beat is hit only once the delay has elapsed.
* A **warp** skips a span of beats in zero time. Notes inside a warp are
  unreachable and are dropped by the parsers.

Times are resolved once at chart load, so the gameplay hot loop never calls
into this module for note positions.

This module must not import pygame, and performs no I/O.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

DEFAULT_BPM = 120.0


@dataclass(frozen=True, slots=True)
class BpmSegment:
    """A BPM that takes effect at ``beat`` and holds until the next segment."""

    beat: float
    bpm: float


@dataclass(frozen=True, slots=True)
class StopSegment:
    """A pause of ``duration`` seconds at ``beat``.

    ``is_delay`` selects the before/after semantics described in the module
    docstring.
    """

    beat: float
    duration: float
    is_delay: bool = False


@dataclass(frozen=True, slots=True)
class WarpSegment:
    """A skip of ``length`` beats, starting at ``beat``, taking zero time."""

    beat: float
    length: float


class TimingData:
    """Converts between beats and seconds for one chart.

    Construction precomputes piecewise-linear tables in both directions, so
    each conversion is a binary search plus one multiply.
    """

    __slots__ = (
        "offset",
        "bpms",
        "stops",
        "warps",
        "_ibeats",
        "_itimes",
        "_irates",
        "_bpm_beats",
        "_stop_beats",
        "_stop_cum",
        "_delay_beats",
        "_delay_cum",
        "_ph_t",
        "_ph_beat",
        "_ph_bps",
    )

    def __init__(
        self,
        offset: float = 0.0,
        bpms: list[BpmSegment] | None = None,
        stops: list[StopSegment] | None = None,
        warps: list[WarpSegment] | None = None,
    ) -> None:
        self.offset = float(offset)
        self.bpms = self._normalize_bpms(bpms)
        self.stops = tuple(
            sorted(
                (s for s in (stops or []) if s.duration > 0.0),
                key=lambda s: s.beat,
            )
        )
        self.warps = self._merge_warps(warps)
        self._bpm_beats = [seg.beat for seg in self.bpms]
        self._build_beat_to_time()
        self._build_time_to_beat()

    # ------------------------------------------------------------------ setup

    @staticmethod
    def _normalize_bpms(bpms: list[BpmSegment] | None) -> tuple[BpmSegment, ...]:
        """Sort BPM segments and guarantee one starting at beat 0."""
        segments = sorted(bpms or [], key=lambda b: b.beat)
        for seg in segments:
            if seg.bpm <= 0.0:
                raise ValueError(
                    "non-positive BPM {} at beat {}; parsers must convert "
                    "negative BPMs into warps".format(seg.bpm, seg.beat)
                )
        if not segments:
            return (BpmSegment(0.0, DEFAULT_BPM),)
        if segments[0].beat > 0.0:
            segments.insert(0, BpmSegment(0.0, segments[0].bpm))
        return tuple(segments)

    @staticmethod
    def _merge_warps(warps: list[WarpSegment] | None) -> tuple[WarpSegment, ...]:
        """Sort warps and coalesce any that overlap, so lookups stay simple."""
        pending = sorted(
            (w for w in (warps or []) if w.length > 0.0), key=lambda w: w.beat
        )
        merged: list[WarpSegment] = []
        for warp in pending:
            if merged and warp.beat <= merged[-1].beat + merged[-1].length:
                prev = merged[-1]
                end = max(prev.beat + prev.length, warp.beat + warp.length)
                merged[-1] = WarpSegment(prev.beat, end - prev.beat)
            else:
                merged.append(warp)
        return tuple(merged)

    def _build_beat_to_time(self) -> None:
        """Build elementary intervals of constant scroll rate.

        Boundaries come from BPM changes and from warp start/end points. Inside
        a warp the rate is zero seconds per beat, which is what makes warped
        beats consume no time.
        """
        bounds = {0.0}
        bounds.update(seg.beat for seg in self.bpms)
        for warp in self.warps:
            bounds.add(warp.beat)
            bounds.add(warp.beat + warp.length)
        starts = sorted(b for b in bounds if b >= 0.0)

        ibeats: list[float] = []
        itimes: list[float] = []
        irates: list[float] = []
        elapsed = 0.0
        for index, start in enumerate(starts):
            if index > 0:
                span = start - starts[index - 1]
                elapsed += span * irates[index - 1]
            rate = 0.0 if self._in_warp(start) else 60.0 / self._bpm_at(start)
            ibeats.append(start)
            itimes.append(elapsed)
            irates.append(rate)

        self._ibeats = ibeats
        self._itimes = itimes
        self._irates = irates

        # Prefix sums let stop and delay contributions resolve in one bisect.
        self._stop_beats, self._stop_cum = self._prefix(
            [s for s in self.stops if not s.is_delay]
        )
        self._delay_beats, self._delay_cum = self._prefix(
            [s for s in self.stops if s.is_delay]
        )

    @staticmethod
    def _prefix(segments: list[StopSegment]) -> tuple[list[float], list[float]]:
        beats = [s.beat for s in segments]
        cumulative = [0.0]
        for seg in segments:
            cumulative.append(cumulative[-1] + seg.duration)
        return beats, cumulative

    def _build_time_to_beat(self) -> None:
        """Build the inverse table as phases of constant beats-per-second.

        Stops and delays appear as plateaus holding the beat constant while
        time advances. A warp spans zero time, so its phase has zero width and
        a bisect naturally lands past it.
        """
        boundaries = sorted(set(self._ibeats) | {s.beat for s in self.stops})
        times: list[float] = []
        beats: list[float] = []
        rates: list[float] = []

        for beat in boundaries:
            delay = self._duration_at(self._delay_beats, self._delay_cum, beat)
            stop = self._duration_at(self._stop_beats, self._stop_cum, beat)
            hit_time = self.beat_to_time(beat)

            if delay > 0.0:
                times.append(hit_time - delay)
                beats.append(beat)
                rates.append(0.0)
            if stop > 0.0:
                times.append(hit_time)
                beats.append(beat)
                rates.append(0.0)

            spb = self._irates[self._interval_index(beat)]
            times.append(hit_time + stop)
            beats.append(beat)
            rates.append(0.0 if spb == 0.0 else 1.0 / spb)

        self._ph_t = times
        self._ph_beat = beats
        self._ph_bps = rates

    # -------------------------------------------------------------- internals

    def _in_warp(self, beat: float) -> bool:
        for warp in self.warps:
            if warp.beat <= beat < warp.beat + warp.length:
                return True
        return False

    def _interval_index(self, beat: float) -> int:
        return max(0, bisect.bisect_right(self._ibeats, beat) - 1)

    @staticmethod
    def _duration_at(
        beats: list[float], cumulative: list[float], beat: float
    ) -> float:
        """Total duration of segments landing exactly on ``beat``."""
        lo = bisect.bisect_left(beats, beat)
        hi = bisect.bisect_right(beats, beat)
        return cumulative[hi] - cumulative[lo]

    def _bpm_at(self, beat: float) -> float:
        index = max(0, bisect.bisect_right(self._bpm_beats, beat) - 1)
        return self.bpms[index].bpm

    # ----------------------------------------------------------------- public

    def bpm_at(self, beat: float) -> float:
        """The BPM in effect at ``beat``."""
        return self._bpm_at(beat)

    def beat_to_time(self, beat: float) -> float:
        """Seconds at which ``beat`` is reached.

        For a note on a stop beat this is the moment the note must be hit,
        which is when the stop begins.
        """
        index = self._interval_index(beat)
        pure = self._itimes[index] + (beat - self._ibeats[index]) * self._irates[index]

        # A stop strictly before this beat has already elapsed; one *on* this
        # beat has not. A delay on this beat has.
        stops = self._stop_cum[bisect.bisect_left(self._stop_beats, beat)]
        delays = self._delay_cum[bisect.bisect_right(self._delay_beats, beat)]
        return -self.offset + pure + stops + delays

    def time_to_beat(self, time: float) -> float:
        """The beat being displayed at ``time`` seconds.

        This holds steady through a stop or delay, and jumps across a warp.
        """
        index = bisect.bisect_right(self._ph_t, time) - 1
        if index < 0:
            index = 0
        return self._ph_beat[index] + (time - self._ph_t[index]) * self._ph_bps[index]

    def is_warped(self, beat: float) -> bool:
        """Whether ``beat`` falls inside a warp, and so can never be played."""
        return self._in_warp(beat)

    @classmethod
    def constant(cls, bpm: float, offset: float = 0.0) -> TimingData:
        """Timing for a chart with a single, unchanging BPM."""
        return cls(offset=offset, bpms=[BpmSegment(0.0, bpm)])

    def __repr__(self) -> str:
        return (
            "TimingData(offset={:g}, bpms={}, stops={}, warps={})".format(
                self.offset, len(self.bpms), len(self.stops), len(self.warps)
            )
        )
