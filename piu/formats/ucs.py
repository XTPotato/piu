"""Parser for Andamiro ``.ucs`` user charts.

Format
------
A UCS file is a header followed by one or more blocks. Each block restates the
timing that applies to the rows beneath it::

    :Format=1
    :Mode=Single
    :BPM=145
    :Delay=0
    :Beat=4
    :Split=2
    ..X..
    .....
    M....
    H....
    W....

Every row is one tick. ``Split`` is the number of ticks per beat, so a row
lasts ``60 / BPM / Split`` seconds. ``Beat`` is the measure length in beats
and affects only how an editor draws measure lines - it does not affect
timing. ``Delay`` is a pause in milliseconds before the block starts.

Panel characters, one per column:

===========  ==========================
``.``        empty
``X``        tap
``M``        hold start
``H``        hold body
``W``        hold end
===========  ==========================

.. warning::
   No authoritative public specification of this format exists, so the
   semantics above - in particular that ``Split`` is ticks-per-beat and that
   ``Beat`` is cosmetic - are reconstructed from community documentation and
   should be confirmed against real ``.ucs`` files before this parser is
   trusted for arbitrary charts. If they turn out to differ, the canonical
   chart model means only this module has to change.

This module must not import pygame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from piu.core.timing import BpmSegment, StopSegment, TimingData
from piu.formats.chart import Chart, Note, NoteKind, PlayMode

EMPTY = "."
TAP = "X"
HOLD_START = "M"
HOLD_BODY = "H"
HOLD_END = "W"

#: Mode names as they appear in the header, mapped to the canonical play mode.
#: Performance modes use the same panel count as their base mode; they differ
#: only in scoring, which is not the parser's concern.
MODE_NAMES: dict[str, PlayMode] = {
    "single": PlayMode.SINGLE,
    "s-performance": PlayMode.SINGLE,
    "single performance": PlayMode.SINGLE,
    "double": PlayMode.DOUBLE,
    "d-performance": PlayMode.DOUBLE,
    "double performance": PlayMode.DOUBLE,
    "halfdouble": PlayMode.HALF_DOUBLE,
    "half-double": PlayMode.HALF_DOUBLE,
    "couple": PlayMode.ROUTINE,
    "routine": PlayMode.ROUTINE,
}


class UcsParseError(ValueError):
    """Raised when a ``.ucs`` file cannot be understood."""


@dataclass(slots=True)
class _Block:
    """One timing block: a header plus the rows it governs."""

    bpm: float
    delay_ms: float
    beat: int
    split: int
    start_beat: float
    rows: list[str] = field(default_factory=list)

    @property
    def beats_per_row(self) -> float:
        return 1.0 / self.split


def parse(source: str | Path) -> Chart:
    """Parse UCS text, or the contents of a ``.ucs`` file, into a `Chart`."""
    text = _read(source)
    mode, blocks = _split_blocks(text)
    timing = _build_timing(blocks)
    notes = _build_notes(blocks, mode, timing)

    chart = Chart(mode=mode, timing=timing, notes=notes)
    chart.sort()
    return chart


def _read(source: str | Path) -> str:
    if isinstance(source, Path):
        # UCS files in the wild are inconsistently encoded and often carry a
        # BOM. utf-8-sig strips it; the replacement fallback keeps a stray
        # byte from failing the whole load.
        return source.read_text(encoding="utf-8-sig", errors="replace")
    return source.lstrip("﻿")


def _split_blocks(text: str) -> tuple[PlayMode, list[_Block]]:
    """Walk the file, collecting timing blocks and the rows under each."""
    mode: PlayMode | None = None
    blocks: list[_Block] = []
    pending: dict[str, str] = {}
    current: _Block | None = None
    current_beat = 0.0

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue

        if line.startswith(":"):
            key, _, value = line[1:].partition("=")
            key = key.strip().lower()
            value = value.strip()

            if key == "mode":
                mode = _parse_mode(value, lineno)
            elif key == "format":
                pass  # Only version 1 exists; nothing varies on it yet.
            elif key in ("bpm", "delay", "beat", "split"):
                # A repeated key means a new block is starting.
                if key in pending:
                    current = None
                    pending.clear()
                pending[key] = value
                if len(pending) == 4:
                    current_beat = _advance(current, current_beat)
                    current = _make_block(pending, current_beat, lineno)
                    blocks.append(current)
                    pending = {}
            continue

        if current is None:
            raise UcsParseError(
                "line {}: step row {!r} appears before any timing block".format(
                    lineno, line
                )
            )
        current.rows.append(line)

    if mode is None:
        raise UcsParseError("file has no :Mode= header")
    if not blocks:
        raise UcsParseError("file has no timing blocks")
    return mode, blocks


def _advance(block: _Block | None, current_beat: float) -> float:
    """Beat position after ``block`` finishes playing."""
    if block is None:
        return current_beat
    return current_beat + len(block.rows) * block.beats_per_row


def _make_block(values: dict[str, str], start_beat: float, lineno: int) -> _Block:
    try:
        bpm = float(values["bpm"])
        delay_ms = float(values["delay"])
        beat = int(float(values["beat"]))
        split = int(float(values["split"]))
    except ValueError as exc:
        raise UcsParseError(
            "line {}: malformed block header {!r}".format(lineno, values)
        ) from exc

    if bpm <= 0.0:
        raise UcsParseError("line {}: BPM must be positive, got {}".format(lineno, bpm))
    if split <= 0:
        raise UcsParseError(
            "line {}: Split must be positive, got {}".format(lineno, split)
        )
    return _Block(bpm=bpm, delay_ms=delay_ms, beat=beat, split=split, start_beat=start_beat)


def _parse_mode(value: str, lineno: int) -> PlayMode:
    try:
        return MODE_NAMES[value.strip().lower()]
    except KeyError:
        raise UcsParseError(
            "line {}: unknown mode {!r} (expected one of {})".format(
                lineno, value, ", ".join(sorted(MODE_NAMES))
            )
        ) from None


def _build_timing(blocks: list[_Block]) -> TimingData:
    """Each block contributes a BPM segment, and its delay a pause."""
    bpms: list[BpmSegment] = []
    stops: list[StopSegment] = []

    for block in blocks:
        # Consecutive blocks often repeat the same BPM just to change Split;
        # collapsing those keeps the timing tables small.
        if not bpms or bpms[-1].bpm != block.bpm:
            bpms.append(BpmSegment(block.start_beat, block.bpm))
        if block.delay_ms > 0.0:
            stops.append(
                StopSegment(block.start_beat, block.delay_ms / 1000.0, is_delay=True)
            )

    return TimingData(offset=0.0, bpms=bpms, stops=stops)


def _build_notes(
    blocks: list[_Block], mode: PlayMode, timing: TimingData
) -> list[Note]:
    """Turn step rows into notes, stitching hold runs into single notes."""
    columns = mode.columns
    notes: list[Note] = []
    # Column index -> the hold note still waiting for its 'W' row.
    open_holds: dict[int, Note] = {}

    for block in blocks:
        for row_index, row in enumerate(block.rows):
            if len(row) != columns:
                raise UcsParseError(
                    "expected {} columns for mode {}, got {} in row {!r}".format(
                        columns, mode.value, len(row), row
                    )
                )
            beat = block.start_beat + row_index * block.beats_per_row
            time = timing.beat_to_time(beat)

            for column, symbol in enumerate(row):
                _apply(symbol, column, beat, time, notes, open_holds)

    if open_holds:
        raise UcsParseError(
            "hold started but never ended in column(s) {}".format(
                ", ".join(str(c) for c in sorted(open_holds))
            )
        )
    return notes


def _apply(
    symbol: str,
    column: int,
    beat: float,
    time: float,
    notes: list[Note],
    open_holds: dict[int, Note],
) -> None:
    if symbol == EMPTY:
        return

    if symbol == TAP:
        notes.append(Note(beat=beat, time=time, column=column, kind=NoteKind.TAP))
        return

    if symbol == HOLD_START:
        note = Note(beat=beat, time=time, column=column, kind=NoteKind.HOLD)
        notes.append(note)
        open_holds[column] = note
        return

    if symbol in (HOLD_BODY, HOLD_END):
        held = open_holds.get(column)
        if held is None:
            raise UcsParseError(
                "hold {} in column {} at beat {:g} has no matching start".format(
                    symbol, column, beat
                )
            )
        # The tail extends to whichever row proves to be last.
        held.end_beat = beat
        held.end_time = time
        if symbol == HOLD_END:
            del open_holds[column]
        return

    raise UcsParseError(
        "unknown step character {!r} in column {} at beat {:g}".format(
            symbol, column, beat
        )
    )
