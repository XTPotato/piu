"""The canonical chart model.

Every parser (`.sm`, `.ssc`, `.ucs`, native JSON) compiles into these types, so
gameplay code never knows or cares which format a chart came from.

This module must stay free of pygame and of any I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from piu.core.timing import TimingData


class Panel(Enum):
    """The five physical panels of one Pump It Up pad, in column order."""

    DOWN_LEFT = 0
    UP_LEFT = 1
    CENTER = 2
    UP_RIGHT = 3
    DOWN_RIGHT = 4


class NoteKind(Enum):
    TAP = "tap"
    HOLD = "hold"
    MINE = "mine"


class PlayMode(Enum):
    """Play modes, distinguished by how many columns they occupy."""

    SINGLE = "single"
    HALF_DOUBLE = "halfdouble"
    DOUBLE = "double"
    ROUTINE = "routine"

    @property
    def columns(self) -> int:
        return _MODE_COLUMNS[self]

    @property
    def pads(self) -> int:
        """Number of physical pads the mode spans (1 for single, 2 otherwise)."""
        return 1 if self is PlayMode.SINGLE else 2


_MODE_COLUMNS: dict[PlayMode, int] = {
    PlayMode.SINGLE: 5,
    PlayMode.HALF_DOUBLE: 6,
    PlayMode.DOUBLE: 10,
    PlayMode.ROUTINE: 10,
}


def panel_for_column(column: int, mode: PlayMode) -> Panel:
    """Map a chart column onto the physical panel it lands on.

    Half-double occupies the middle six panels of a ten-panel setup, so its
    columns are offset by three relative to a plain double chart.
    """
    index = column + 3 if mode is PlayMode.HALF_DOUBLE else column
    return Panel(index % 5)


@dataclass(slots=True)
class Note:
    """A single note.

    `time` (and `end_time` for holds) are resolved once at load via `TimingData`,
    so the gameplay hot loop never does beat/time math.
    """

    beat: float
    time: float
    column: int
    kind: NoteKind = NoteKind.TAP
    end_beat: float | None = None
    end_time: float | None = None

    @property
    def is_hold(self) -> bool:
        return self.kind is NoteKind.HOLD

    @property
    def duration(self) -> float:
        if self.end_time is None:
            return 0.0
        return self.end_time - self.time


@dataclass(slots=True)
class Chart:
    """One playable difficulty of a song."""

    mode: PlayMode
    timing: TimingData
    notes: list[Note] = field(default_factory=list)
    level: int = 1
    difficulty_name: str = ""
    charter: str = ""

    @property
    def columns(self) -> int:
        return self.mode.columns

    @property
    def tap_count(self) -> int:
        """Notes that contribute to max combo (mines never do)."""
        return sum(1 for n in self.notes if n.kind is not NoteKind.MINE)

    def sort(self) -> None:
        """Order notes by time, then column - the order gameplay expects."""
        self.notes.sort(key=lambda n: (n.time, n.column))


@dataclass(slots=True)
class Song:
    """A song folder: shared metadata plus every chart found in it."""

    title: str = ""
    artist: str = ""
    audio_path: str = ""
    banner_path: str = ""
    sample_start: float = 0.0
    sample_length: float = 15.0
    charts: list[Chart] = field(default_factory=list)

    def chart_for(self, mode: PlayMode, level: int) -> Chart | None:
        for chart in self.charts:
            if chart.mode is mode and chart.level == level:
                return chart
        return None
