"""Matching inputs to expected times, and judging whether timing is good enough.

This is the arithmetic behind the W1 timing gate. It is kept separate from the
screen that drives it so the verdict itself can be tested: a gate whose pass
condition has never been exercised is not a gate.

An *offset* is ``input_time - expected_time``. Negative means early, positive
means late. What matters for a rhythm game is less the mean - a consistent bias
is exactly what calibration removes - than the **spread**. A large standard
deviation cannot be calibrated away, and it is what makes a game feel
unreliable no matter how carefully the player times a step.

This module must not import pygame.
"""

from __future__ import annotations

from dataclasses import dataclass

# The three statistics used here are computed locally rather than imported from
# the stdlib's `statistics` module, which pygbag's trimmed CPython does not
# ship - importing it fails at runtime in the browser with ModuleNotFoundError.
# The arithmetic is four lines; the dependency was not worth the risk.
# `math` is avoided for the same reason, hence ** 0.5 rather than sqrt.


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _stdev(values: list[float]) -> float:
    """Sample standard deviation. Zero for fewer than two values."""
    if len(values) < 2:
        return 0.0
    average = _mean(values)
    variance = sum((v - average) ** 2 for v in values) / (len(values) - 1)
    return variance ** 0.5

#: Beyond this an input is assumed to belong to no click at all - a stray key
#: press rather than a late attempt - and is discarded instead of poisoning the
#: statistics with a half-second outlier.
MATCH_WINDOW = 0.25


@dataclass(frozen=True, slots=True)
class Verdict:
    """Whether measured timing is good enough to build on."""

    passed: bool
    reason: str


@dataclass(slots=True)
class OffsetStats:
    """Summary of a run of measured offsets, all values in seconds."""

    count: int
    mean: float
    median: float
    stdev: float
    minimum: float
    maximum: float
    unmatched_inputs: int
    missed_expected: int

    @property
    def spread(self) -> float:
        """Peak-to-peak spread."""
        return self.maximum - self.minimum

    def describe(self) -> str:
        return (
            "n={} mean={:+.1f}ms median={:+.1f}ms sd={:.1f}ms "
            "min={:+.1f}ms max={:+.1f}ms".format(
                self.count,
                self.mean * 1000.0,
                self.median * 1000.0,
                self.stdev * 1000.0,
                self.minimum * 1000.0,
                self.maximum * 1000.0,
            )
        )


def match_inputs(
    inputs: list[float],
    expected: list[float],
    window: float = MATCH_WINDOW,
) -> tuple[list[float], list[float], list[float]]:
    """Pair each input with its nearest expected time.

    Returns ``(offsets, unmatched_inputs, missed_expected)``.

    Each expected time can absorb at most one input, so a double-tap shows up
    as an unmatched input rather than silently improving the statistics.
    """
    if window <= 0.0:
        raise ValueError("window must be positive, got {!r}".format(window))

    ordered = sorted(expected)
    claimed: set[int] = set()
    offsets: list[float] = []
    unmatched: list[float] = []

    for moment in sorted(inputs):
        best_index = -1
        best_distance = window
        for index, target in enumerate(ordered):
            if index in claimed:
                continue
            distance = abs(moment - target)
            if distance <= best_distance:
                best_distance = distance
                best_index = index
            elif target > moment and distance > best_distance:
                # Sorted, so everything further right is worse still.
                break

        if best_index < 0:
            unmatched.append(moment)
        else:
            claimed.add(best_index)
            offsets.append(moment - ordered[best_index])

    missed = [t for index, t in enumerate(ordered) if index not in claimed]
    return offsets, unmatched, missed


#: Fraction of a half-beat beyond which a measurement is treated as ambiguous.
#: Well below 1.0, because confidence should degrade before the exact boundary
#: rather than at it.
AMBIGUITY_FRACTION = 0.6


def is_ambiguous(stats: OffsetStats, period: float) -> bool:
    """Whether the run sits too close to the half-beat boundary to be trusted.

    This is aliasing, and it is worth being precise about why it cannot simply
    be corrected. Nearest-neighbour matching always pairs a tap with the
    closest click, so it can never report an offset larger than half a beat. A
    player who is 300ms late on a 500ms beat produces *exactly the same* tap
    pattern as one who is 200ms early. Not similar - identical. No amount of
    analysis recovers which happened, because the information is not in the
    data.

    What makes that dangerous rather than merely imprecise is how it presents:
    a consistent late player is reported as a consistent early one, with near
    zero standard deviation. It looks like the best possible result, passes the
    gate, and yields a calibration offset of the wrong sign.

    So rather than guess a direction, the measurement is declared unusable when
    it lands near the boundary. An offset that large is implausible for someone
    genuinely trying to tap along, which makes "run it again with the count-in"
    both the safe answer and the likely correct one.
    """
    if stats.count == 0 or period <= 0.0:
        return False
    half_beat = period / 2.0
    return abs(stats.median) > half_beat * AMBIGUITY_FRACTION


def summarize(
    offsets: list[float],
    unmatched_inputs: int = 0,
    missed_expected: int = 0,
) -> OffsetStats:
    """Reduce a list of offsets to the numbers the gate is judged on."""
    if not offsets:
        return OffsetStats(0, 0.0, 0.0, 0.0, 0.0, 0.0, unmatched_inputs, missed_expected)

    return OffsetStats(
        count=len(offsets),
        mean=_mean(offsets),
        median=_median(offsets),
        stdev=_stdev(offsets),
        minimum=min(offsets),
        maximum=max(offsets),
        unmatched_inputs=unmatched_inputs,
        missed_expected=missed_expected,
    )


def evaluate(
    stats: OffsetStats,
    perfect_window: float,
    minimum_samples: int = 16,
    ambiguous: bool = False,
) -> Verdict:
    """Decide whether measured timing clears the W1 gate.

    The plan's condition is "mean judged offset near zero after calibration,
    standard deviation inside the Perfect window". Mean is the weaker half: a
    consistent bias is precisely what the calibration offset subtracts. The
    spread is the real test, because nothing downstream can remove it.
    """
    # Checked before anything else: an aliased run produces numbers that look
    # excellent, so trusting them would be the worst outcome available.
    if ambiguous:
        return Verdict(
            False,
            "offsets are near half a beat, where a late tap and an early one "
            "are indistinguishable - the sign here may be inverted. Use the "
            "count-in to lock onto the tempo and run it again.",
        )

    if stats.count < minimum_samples:
        return Verdict(
            False,
            "only {} samples; need at least {} for the spread to mean "
            "anything".format(stats.count, minimum_samples),
        )

    if stats.stdev > perfect_window:
        return Verdict(
            False,
            "standard deviation {:.1f}ms exceeds the Perfect window "
            "({:.1f}ms). A consistent bias could be calibrated out, but "
            "spread cannot.".format(stats.stdev * 1000.0, perfect_window * 1000.0),
        )

    # After calibration the residual mean should be small. Judged against the
    # same window, since a bias that size is what the player would feel.
    if abs(stats.mean - stats.median) > perfect_window:
        return Verdict(
            False,
            "mean and median differ by {:.1f}ms, which means the distribution "
            "is skewed by outliers rather than centred".format(
                abs(stats.mean - stats.median) * 1000.0
            ),
        )

    return Verdict(
        True,
        "spread {:.1f}ms is inside the {:.1f}ms Perfect window across {} "
        "samples".format(
            stats.stdev * 1000.0, perfect_window * 1000.0, stats.count
        ),
    )


def suggest_calibration(stats: OffsetStats) -> float:
    """The offset a player should apply, in seconds.

    The median is used rather than the mean because a handful of badly late
    taps should not drag the correction that everyone else's timing depends on.
    """
    return stats.median
