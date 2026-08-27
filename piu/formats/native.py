"""The native JSON chart format.

This is the canonical model written straight to disk. It exists so that:

* the bundled demo songs have a format we own outright,
* tests have fixtures that are readable and hand-editable, and
* any imported chart can be dumped for debugging and diffed against another.

Note *times* are deliberately not stored. They are derived from the timing
data on load, so a file can never disagree with itself about when a note
falls.

Schema (``format: piu-song``)::

    {
      "format": "piu-song",
      "version": 1,
      "title": "...", "artist": "...", "audio": "track.ogg",
      "charts": [
        {
          "mode": "single", "level": 17, "difficulty": "Hard",
          "charter": "...",
          "timing": {
            "offset": -0.5,
            "bpms":   [[0.0, 120.0]],
            "stops":  [[8.0, 0.5]],
            "delays": [], "warps": []
          },
          "notes": [
            {"beat": 0.0, "column": 0, "kind": "tap"},
            {"beat": 4.0, "column": 0, "kind": "hold", "end_beat": 6.0}
          ]
        }
      ]
    }

This module must not import pygame.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from piu.core.timing import BpmSegment, StopSegment, TimingData, WarpSegment
from piu.formats.chart import Chart, Note, NoteKind, PlayMode, Song

SONG_FORMAT = "piu-song"
CHART_FORMAT = "piu-chart"
VERSION = 1


class NativeParseError(ValueError):
    """Raised when a native chart document is malformed."""


# ---------------------------------------------------------------- loading


def load_song(source: str | Path | dict[str, Any]) -> Song:
    """Load a `Song` from a native document, file path, or JSON text."""
    data = _as_dict(source)
    _check_format(data, (SONG_FORMAT, CHART_FORMAT))

    # A bare chart document is treated as a song with exactly one chart, so
    # callers never have to care which of the two they were handed.
    if data.get("format") == CHART_FORMAT:
        return Song(charts=[_load_chart(data)])

    song = Song(
        title=str(data.get("title", "")),
        artist=str(data.get("artist", "")),
        audio_path=str(data.get("audio", "")),
        banner_path=str(data.get("banner", "")),
        sample_start=float(data.get("sample_start", 0.0)),
        sample_length=float(data.get("sample_length", 15.0)),
    )
    song.charts = [_load_chart(c) for c in data.get("charts", [])]
    return song


def load_chart(source: str | Path | dict[str, Any]) -> Chart:
    """Load a single `Chart`, from either document shape."""
    data = _as_dict(source)
    if data.get("format") == SONG_FORMAT:
        song = load_song(data)
        if not song.charts:
            raise NativeParseError("song document contains no charts")
        return song.charts[0]
    _check_format(data, (CHART_FORMAT,))
    return _load_chart(data)


def _as_dict(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    text = (
        source.read_text(encoding="utf-8-sig")
        if isinstance(source, Path)
        else source
    )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NativeParseError("not valid JSON: {}".format(exc)) from exc
    if not isinstance(data, dict):
        raise NativeParseError("expected a JSON object at the top level")
    return data


def _check_format(data: dict[str, Any], allowed: tuple[str, ...]) -> None:
    kind = data.get("format")
    if kind not in allowed:
        raise NativeParseError(
            "expected format {}, got {!r}".format(" or ".join(allowed), kind)
        )
    version = data.get("version", VERSION)
    if version != VERSION:
        raise NativeParseError(
            "unsupported version {!r}; this build reads version {}".format(
                version, VERSION
            )
        )


def _load_chart(data: dict[str, Any]) -> Chart:
    if not isinstance(data, dict):
        raise NativeParseError("chart entry is not an object")

    mode = _load_mode(data.get("mode", "single"))
    timing = _load_timing(data.get("timing", {}))
    notes = [_load_note(n, mode, timing) for n in data.get("notes", [])]

    chart = Chart(
        mode=mode,
        timing=timing,
        notes=notes,
        level=int(data.get("level", 1)),
        difficulty_name=str(data.get("difficulty", "")),
        charter=str(data.get("charter", "")),
    )
    chart.sort()
    return chart


def _load_mode(value: Any) -> PlayMode:
    try:
        return PlayMode(str(value).strip().lower())
    except ValueError:
        raise NativeParseError(
            "unknown mode {!r} (expected one of {})".format(
                value, ", ".join(m.value for m in PlayMode)
            )
        ) from None


def _load_timing(data: dict[str, Any]) -> TimingData:
    # Stops and delays are separate arrays in the file but one list in the
    # model, distinguished by the is_delay flag.
    stops = [StopSegment(float(b), float(d)) for b, d in data.get("stops", [])]
    stops += [
        StopSegment(float(b), float(d), is_delay=True)
        for b, d in data.get("delays", [])
    ]
    return TimingData(
        offset=float(data.get("offset", 0.0)),
        bpms=[BpmSegment(float(b), float(v)) for b, v in data.get("bpms", [])],
        stops=stops,
        warps=[WarpSegment(float(b), float(n)) for b, n in data.get("warps", [])],
    )


def _load_note(data: dict[str, Any], mode: PlayMode, timing: TimingData) -> Note:
    try:
        beat = float(data["beat"])
        column = int(data["column"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NativeParseError(
            "note {!r} needs numeric 'beat' and 'column'".format(data)
        ) from exc

    if not 0 <= column < mode.columns:
        raise NativeParseError(
            "column {} is out of range for mode {} ({} columns)".format(
                column, mode.value, mode.columns
            )
        )

    try:
        kind = NoteKind(str(data.get("kind", "tap")).lower())
    except ValueError:
        raise NativeParseError(
            "unknown note kind {!r}".format(data.get("kind"))
        ) from None

    end_beat = data.get("end_beat")
    if kind is NoteKind.HOLD and end_beat is None:
        raise NativeParseError(
            "hold at beat {:g} column {} has no 'end_beat'".format(beat, column)
        )

    return Note(
        beat=beat,
        time=timing.beat_to_time(beat),
        column=column,
        kind=kind,
        end_beat=float(end_beat) if end_beat is not None else None,
        end_time=timing.beat_to_time(float(end_beat)) if end_beat is not None else None,
    )


# ---------------------------------------------------------------- writing


def dump_song(song: Song) -> dict[str, Any]:
    """Serialize a `Song` to a native document."""
    return {
        "format": SONG_FORMAT,
        "version": VERSION,
        "title": song.title,
        "artist": song.artist,
        "audio": song.audio_path,
        "banner": song.banner_path,
        "sample_start": song.sample_start,
        "sample_length": song.sample_length,
        "charts": [_dump_chart(c) for c in song.charts],
    }


def dump_chart(chart: Chart) -> dict[str, Any]:
    """Serialize a single `Chart` to a standalone native document."""
    return {"format": CHART_FORMAT, "version": VERSION, **_dump_chart(chart)}


def _dump_chart(chart: Chart) -> dict[str, Any]:
    return {
        "mode": chart.mode.value,
        "level": chart.level,
        "difficulty": chart.difficulty_name,
        "charter": chart.charter,
        "timing": _dump_timing(chart.timing),
        "notes": [_dump_note(n) for n in chart.notes],
    }


def _dump_timing(timing: TimingData) -> dict[str, Any]:
    return {
        "offset": timing.offset,
        "bpms": [[s.beat, s.bpm] for s in timing.bpms],
        "stops": [[s.beat, s.duration] for s in timing.stops if not s.is_delay],
        "delays": [[s.beat, s.duration] for s in timing.stops if s.is_delay],
        "warps": [[w.beat, w.length] for w in timing.warps],
    }


def _dump_note(note: Note) -> dict[str, Any]:
    data: dict[str, Any] = {
        "beat": note.beat,
        "column": note.column,
        "kind": note.kind.value,
    }
    if note.end_beat is not None:
        data["end_beat"] = note.end_beat
    return data


def write(song: Song, path: Path, *, indent: int = 2) -> None:
    """Write a `Song` to ``path`` as formatted JSON."""
    path.write_text(
        json.dumps(dump_song(song), indent=indent) + "\n", encoding="utf-8"
    )
