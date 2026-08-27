"""Parser for StepMania ``.sm`` and ``.ssc`` simfiles.

Both formats are MSD: a flat sequence of ``#TAG:value:value;`` entries with
``//`` line comments. They differ in how charts are delimited.

``.sm``
    One ``#NOTES;`` tag per chart, carrying six colon-separated fields:
    steps type, description, difficulty, meter, groove radar, and the note
    data itself.

``.ssc``
    A ``#NOTEDATA:;`` marker opens a chart section; the tags that follow
    describe it until its ``#NOTES;`` closes it. A chart may restate
    ``#BPMS``, ``#STOPS``, ``#DELAYS``, ``#WARPS``, or ``#OFFSET``, which then
    override the song-level values for that chart alone.

Only ``pump-*`` steps types are kept; dance and other game modes are skipped.

Note data is measure-based: measures are separated by commas, and a measure's
row count sets its subdivision, so a measure of 8 rows is eighth notes. One
measure is four beats.

This module must not import pygame.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from piu.core.timing import BpmSegment, StopSegment, TimingData, WarpSegment
from piu.formats.chart import Chart, Note, NoteKind, PlayMode, Song

BEATS_PER_MEASURE = 4.0

#: Steps types we play. Anything else in the file is another game's charts.
STEPS_TYPES: dict[str, PlayMode] = {
    "pump-single": PlayMode.SINGLE,
    "pump-halfdouble": PlayMode.HALF_DOUBLE,
    "pump-double": PlayMode.DOUBLE,
    "pump-couple": PlayMode.ROUTINE,
    "pump-routine": PlayMode.ROUTINE,
}

EMPTY = "0"
TAP = "1"
HOLD_HEAD = "2"
TAIL = "3"
ROLL_HEAD = "4"
MINE = "M"
FAKE = "F"
LIFT = "L"

_COMMENT = re.compile(r"//[^\n]*")


class StepManiaParseError(ValueError):
    """Raised when a simfile cannot be understood."""


@dataclass(slots=True)
class _Timing:
    """Raw timing values, before they become a `TimingData`."""

    offset: float | None = None
    bpms: list[tuple[float, float]] = field(default_factory=list)
    stops: list[tuple[float, float]] = field(default_factory=list)
    delays: list[tuple[float, float]] = field(default_factory=list)
    warps: list[tuple[float, float]] = field(default_factory=list)

    def merged_with(self, base: _Timing) -> _Timing:
        """Overlay this chart's timing on the song's, field by field.

        A chart that restates only ``#BPMS`` still inherits the song's stops.
        """
        return _Timing(
            offset=self.offset if self.offset is not None else base.offset,
            bpms=self.bpms or base.bpms,
            stops=self.stops or base.stops,
            delays=self.delays or base.delays,
            warps=self.warps or base.warps,
        )

    def build(self) -> TimingData:
        bpms, implied_warps = _split_negative_bpms(self.bpms)
        stops = [StopSegment(b, d) for b, d in self.stops if d > 0.0]
        stops += [StopSegment(b, d, is_delay=True) for b, d in self.delays if d > 0.0]
        warps = [WarpSegment(b, length) for b, length in self.warps]
        warps += implied_warps
        return TimingData(
            offset=self.offset or 0.0,
            bpms=[BpmSegment(b, v) for b, v in bpms],
            stops=stops,
            warps=warps,
        )


def parse(source: str | Path) -> Song:
    """Parse a ``.sm`` or ``.ssc`` file into a `Song` with all pump charts."""
    text = _read(source)
    song = Song()
    song_timing = _Timing()

    chart_tags: dict[str, str] | None = None
    chart_timing = _Timing()

    for tag, parts in _tokenize(text):
        value = parts[0] if parts else ""
        target = chart_timing if chart_tags is not None else song_timing

        if _read_timing(tag, value, target):
            continue

        if tag == "NOTEDATA":
            chart_tags = {}
            chart_timing = _Timing()
        elif tag == "NOTES" or tag == "NOTES2":
            chart = _build_chart(parts, chart_tags, chart_timing, song_timing)
            if chart is not None:
                song.charts.append(chart)
            chart_tags = None
            chart_timing = _Timing()
        elif chart_tags is not None:
            chart_tags[tag] = value
        else:
            _read_song_tag(song, tag, value)

    return song


def _read(source: str | Path) -> str:
    if isinstance(source, Path):
        # Simfiles are frequently latin-1 or shift-jis mislabelled as UTF-8;
        # replacing undecodable bytes keeps metadata imperfect but loadable.
        return source.read_text(encoding="utf-8-sig", errors="replace")
    return source.lstrip("﻿")


def _tokenize(text: str) -> list[tuple[str, list[str]]]:
    """Split MSD text into ``(TAG, [fields])`` pairs.

    Note data contains commas and newlines but never a semicolon or colon, so
    naive splitting on those is safe here.
    """
    text = _COMMENT.sub("", text)
    tokens: list[tuple[str, list[str]]] = []
    position = 0

    while True:
        start = text.find("#", position)
        if start < 0:
            break
        end = text.find(";", start)
        if end < 0:
            chunk, position = text[start + 1 :], len(text)
        else:
            chunk, position = text[start + 1 : end], end + 1

        fields = chunk.split(":")
        tag = fields[0].strip().upper()
        if tag:
            tokens.append((tag, [f.strip() for f in fields[1:]]))

    return tokens


def _read_song_tag(song: Song, tag: str, value: str) -> None:
    if tag == "TITLE":
        song.title = value
    elif tag == "ARTIST":
        song.artist = value
    elif tag == "MUSIC":
        song.audio_path = value
    elif tag == "BANNER":
        song.banner_path = value
    elif tag == "SAMPLESTART":
        song.sample_start = _float(value, 0.0)
    elif tag == "SAMPLELENGTH":
        song.sample_length = _float(value, 15.0)


def _read_timing(tag: str, value: str, target: _Timing) -> bool:
    """Consume a timing tag into ``target``. Returns whether it was one."""
    if tag == "OFFSET":
        target.offset = _float(value, 0.0)
    elif tag == "BPMS":
        target.bpms = _pairs(value)
    elif tag == "STOPS" or tag == "FREEZES":
        target.stops = _pairs(value)
    elif tag == "DELAYS":
        target.delays = _pairs(value)
    elif tag == "WARPS":
        target.warps = _pairs(value)
    else:
        return False
    return True


def _pairs(value: str) -> list[tuple[float, float]]:
    """Parse ``beat=value,beat=value`` lists, skipping malformed entries."""
    result: list[tuple[float, float]] = []
    for entry in value.replace("\n", "").replace("\r", "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        beat_text, sep, val_text = entry.partition("=")
        if not sep:
            continue
        try:
            result.append((float(beat_text), float(val_text)))
        except ValueError:
            continue
    return sorted(result)


def _float(value: str, default: float) -> float:
    try:
        return float(value)
    except ValueError:
        return default


def _split_negative_bpms(
    pairs: list[tuple[float, float]],
) -> tuple[list[tuple[float, float]], list[WarpSegment]]:
    """Convert negative BPM segments into warps.

    A negative BPM is a StepMania gimmick meaning "skip ahead instantly". The
    engine's timing model requires positive tempos, so each negative span
    becomes a warp over the same beat range and the previous positive tempo
    carries through it. This is an approximation of StepMania's exact
    time-debt behaviour, and is accurate for the usual case of a brief
    negative span used purely to skip.
    """
    if not pairs:
        return [], []

    positive: list[tuple[float, float]] = []
    warps: list[WarpSegment] = []

    for index, (beat, bpm) in enumerate(pairs):
        if bpm > 0.0:
            positive.append((beat, bpm))
            continue
        # The span runs until the next segment, or is a point warp if last.
        end = pairs[index + 1][0] if index + 1 < len(pairs) else beat
        if end > beat:
            warps.append(WarpSegment(beat, end - beat))

    if not positive:
        # A chart whose every tempo is negative has no usable timing.
        raise StepManiaParseError("no positive BPM segment found in #BPMS")
    return positive, warps


def _build_chart(
    parts: list[str],
    chart_tags: dict[str, str] | None,
    chart_timing: _Timing,
    song_timing: _Timing,
) -> Chart | None:
    """Build one chart from a ``#NOTES`` tag, or None if it is not a pump chart."""
    if len(parts) >= 6:
        # .sm form: type : description : difficulty : meter : radar : notes
        steps_type, description, difficulty, meter = parts[:4]
        note_text = parts[5]
        timing = song_timing
    else:
        # .ssc form: the surrounding #NOTEDATA section describes the chart.
        tags = chart_tags or {}
        steps_type = tags.get("STEPSTYPE", "")
        description = tags.get("DESCRIPTION", "") or tags.get("CHARTNAME", "")
        difficulty = tags.get("DIFFICULTY", "")
        meter = tags.get("METER", "")
        note_text = parts[0] if parts else ""
        timing = chart_timing.merged_with(song_timing)

    mode = STEPS_TYPES.get(steps_type.strip().lower())
    if mode is None:
        return None

    timing_data = timing.build()
    notes = _parse_notes(note_text, mode, timing_data)

    chart = Chart(
        mode=mode,
        timing=timing_data,
        notes=notes,
        level=int(_float(meter, 1.0)),
        difficulty_name=difficulty,
        charter=description,
    )
    chart.sort()
    return chart


def _parse_notes(text: str, mode: PlayMode, timing: TimingData) -> list[Note]:
    columns = mode.columns
    notes: list[Note] = []
    open_holds: dict[int, Note] = {}

    for measure_index, measure in enumerate(text.split(",")):
        rows = [line.strip() for line in measure.splitlines() if line.strip()]
        if not rows:
            continue
        step = BEATS_PER_MEASURE / len(rows)

        for row_index, row in enumerate(rows):
            if len(row) < columns:
                raise StepManiaParseError(
                    "expected {} columns for {}, got {} in row {!r}".format(
                        columns, mode.value, len(row), row
                    )
                )
            beat = measure_index * BEATS_PER_MEASURE + row_index * step
            time = timing.beat_to_time(beat)
            warped = timing.is_warped(beat)

            for column, symbol in enumerate(row[:columns]):
                _apply(symbol, column, beat, time, warped, notes, open_holds)

    # An unterminated hold is common in hand-edited files; ending it at its
    # head is more useful than refusing to load the chart.
    for held in open_holds.values():
        held.end_beat = held.beat
        held.end_time = held.time

    return notes


def _apply(
    symbol: str,
    column: int,
    beat: float,
    time: float,
    warped: bool,
    notes: list[Note],
    open_holds: dict[int, Note],
) -> None:
    if symbol in (EMPTY, FAKE):
        return

    if symbol == TAIL:
        held = open_holds.pop(column, None)
        if held is not None:
            held.end_beat = beat
            held.end_time = time
        return

    # Notes inside a warp can never be reached, so they are dropped rather
    # than left in the chart as guaranteed misses.
    if warped:
        return

    if symbol in (TAP, LIFT):
        notes.append(Note(beat=beat, time=time, column=column, kind=NoteKind.TAP))
    elif symbol == MINE:
        notes.append(Note(beat=beat, time=time, column=column, kind=NoteKind.MINE))
    elif symbol in (HOLD_HEAD, ROLL_HEAD):
        # Rolls are played as holds; re-tapping is not modelled in v1.
        note = Note(beat=beat, time=time, column=column, kind=NoteKind.HOLD)
        notes.append(note)
        open_holds[column] = note
