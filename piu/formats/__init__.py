"""Chart parsers and the canonical chart model.

Every format compiles into `piu.formats.chart.Song` / `Chart`, so nothing
downstream needs to know where a chart came from. `load` dispatches on file
extension; `scan` walks a song library directory.

This package must not import pygame.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from piu.formats import native, stepmania, ucs
from piu.formats.chart import (
    Chart,
    Note,
    NoteKind,
    Panel,
    PlayMode,
    Song,
    panel_for_column,
)

__all__ = [
    "Chart",
    "Note",
    "NoteKind",
    "Panel",
    "PlayMode",
    "Song",
    "UnknownFormatError",
    "load",
    "panel_for_column",
    "scan",
    "supported_extensions",
]

#: Extensions we know how to open. ``.ucs`` yields a bare chart, so it is
#: wrapped into a single-chart song for a uniform return type.
LOADERS: dict[str, Callable[[Path], Song]] = {
    ".sm": stepmania.parse,
    ".ssc": stepmania.parse,
    ".ucs": lambda path: Song(charts=[ucs.parse(path)]),
    ".json": native.load_song,
}

#: When a folder holds several formats of the same song, prefer the richest.
#: SSC carries per-chart timing that SM cannot express, so it wins over SM.
PREFERENCE: tuple[str, ...] = (".json", ".ssc", ".sm", ".ucs")


class UnknownFormatError(ValueError):
    """Raised when a file's extension has no registered parser."""


def supported_extensions() -> tuple[str, ...]:
    return tuple(LOADERS)


def load(path: str | Path) -> Song:
    """Load any supported chart file into a `Song`."""
    path = Path(path)
    loader = LOADERS.get(path.suffix.lower())
    if loader is None:
        raise UnknownFormatError(
            "no parser for {!r} (supported: {})".format(
                path.suffix, ", ".join(sorted(LOADERS))
            )
        )
    return loader(path)


def find_chart_files(folder: Path) -> list[Path]:
    """Chart files in one song folder, best format first.

    A folder commonly ships the same song as both ``.sm`` and ``.ssc``; the
    preference order decides which one is authoritative.
    """
    found: list[Path] = []
    for suffix in PREFERENCE:
        found.extend(sorted(p for p in folder.glob("*" + suffix) if p.is_file()))
    return found


def load_folder(folder: Path) -> Song | None:
    """Load the best chart file in ``folder``, merging any loose ``.ucs`` charts.

    UCS files hold no song metadata, so when they sit beside a simfile their
    charts are folded into it rather than becoming separate songs.
    """
    files = find_chart_files(folder)
    if not files:
        return None

    primary = next((p for p in files if p.suffix.lower() != ".ucs"), None)
    if primary is None:
        # A UCS-only folder: the folder name is the only title available.
        song = Song(title=folder.name)
    else:
        song = load(primary)
        if not song.title:
            song.title = folder.name

    for path in files:
        if path.suffix.lower() == ".ucs":
            song.charts.append(ucs.parse(path))

    return song if song.charts else None


def scan(library: str | Path) -> list[Song]:
    """Load every song folder under ``library``.

    A song library is a directory of song folders, optionally grouped one
    level deep into packs, which is how StepMania libraries are laid out.
    """
    root = Path(library)
    if not root.is_dir():
        return []

    songs: list[Song] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        song = load_folder(folder)
        if song is not None:
            songs.append(song)
            continue
        # Not a song folder itself - treat it as a pack of song folders.
        for nested in sorted(p for p in folder.iterdir() if p.is_dir()):
            nested_song = load_folder(nested)
            if nested_song is not None:
                songs.append(nested_song)

    return songs
