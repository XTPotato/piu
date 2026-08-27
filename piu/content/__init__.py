"""Originally-authored demo content, generated rather than shipped as files.

Everything here is written in code and built at load. That is a content-policy
decision before it is a technical one: this repository is public, no Andamiro
sprites, songs or step charts may appear in it, and third-party audio brings a
licence question every time it is added. A chart that is a function returning
`Note` objects, played against the click track the W1 rig already synthesizes,
has no such question to answer.

It is also the reason the vertical slice is playable today. The alternative -
wait for a licensed track before anything can be judged - would have left the
gameplay code untested against a real timeline for another milestone.

Why the demo is a metronome rather than a song
-----------------------------------------------
`WebAudioClock.load_click_track` puts clicks on exact sample indices, so the
reference is arithmetic. When a note is charted on beat 12 and the click for
beat 12 is a sample index, any offset the player sees belongs to the pipeline
or to them - never to a decoded file's own alignment. W4 swaps real audio in
behind the same `Chart`, and nothing downstream changes.

This module must not import pygame.
"""

from __future__ import annotations

from piu.core.timing import BpmSegment, TimingData
from piu.formats.chart import Chart, Note, NoteKind, PlayMode, Song

#: The demo runs at a tempo where eighth notes are comfortable and the beat is
#: unambiguous, so a player can tell a mistimed step from a misread one.
DEMO_BPM = 120.0

#: Seconds of silence before beat zero. Long enough to read the field and find
#: the tempo; the click track's own count-in sits inside it.
DEMO_LEAD_IN = 3.0

#: Unmeasured count-in clicks, pitched lower. Four is one bar - the shortest
#: count-in a player can actually lock onto, established during W1.
DEMO_PICKUP_BEATS = 4

_BEAT = 60.0 / DEMO_BPM

# Columns, in `Panel` order: Down-Left, Up-Left, Centre, Up-Right, Down-Right.
DL, UL, C, UR, DR = 0, 1, 2, 3, 4


def demo_timing() -> TimingData:
    """The demo's beat/time map.

    The negative offset is what puts beat zero at `DEMO_LEAD_IN` rather than at
    zero, so `beat_to_time` agrees with the times baked into the notes. Without
    it the two disagree by the whole lead-in, and nothing complains until
    something recomputes a note's time from its beat - a speed mod, an editor,
    a re-export - and the chart silently slides three seconds off its audio.
    `tests/test_content.py` pins the agreement.
    """
    return TimingData(offset=-DEMO_LEAD_IN, bpms=[BpmSegment(0.0, DEMO_BPM)])


def _time_of(beat: float) -> float:
    return DEMO_LEAD_IN + beat * _BEAT


def _tap(beat: float, column: int) -> Note:
    return Note(beat=beat, time=_time_of(beat), column=column)


def _hold(beat: float, length: float, column: int) -> Note:
    return Note(
        beat=beat,
        time=_time_of(beat),
        column=column,
        kind=NoteKind.HOLD,
        end_beat=beat + length,
        end_time=_time_of(beat + length),
    )


def _mine(beat: float, column: int) -> Note:
    return Note(
        beat=beat, time=_time_of(beat), column=column, kind=NoteKind.MINE
    )


def demo_notes() -> list[Note]:
    """The demo chart's notes.

    Written as five phrases that each exercise something the engine has to get
    right, in increasing order of demand, so a failure says which part broke:

    1. Quarter notes on the outer panels - the plain case.
    2. Quarters moving inward, then centre accents - column mapping.
    3. Holds, including two overlapping - hold state and the release grace.
    4. An eighth-note stream - the visible-window slice under load.
    5. Jumps and two mines - simultaneous columns, and a hazard to step around.
    """
    notes: list[Note] = []

    # 1. Eight bars of quarters, alternating feet.
    for i in range(16):
        notes.append(_tap(float(i), DL if i % 2 == 0 else DR))

    # 2. Inward, with the centre on every fourth beat.
    for i in range(16):
        beat = 16.0 + i
        if i % 4 == 3:
            notes.append(_tap(beat, C))
        else:
            notes.append(_tap(beat, UL if i % 2 == 0 else UR))

    # 3. Holds. The last pair overlaps, which is the case that catches a
    #    session tracking only one hold at a time.
    notes.append(_hold(32.0, 2.0, DL))
    notes.append(_hold(34.0, 2.0, DR))
    notes.append(_hold(36.0, 4.0, UL))
    notes.append(_hold(38.0, 2.0, UR))

    # 4. Sixteen eighth notes climbing across the pad and back.
    ladder = [DL, UL, C, UR, DR, UR, C, UL]
    for i in range(16):
        notes.append(_tap(40.0 + i * 0.5, ladder[i % len(ladder)]))

    # 5. Jumps on the beat, with mines on the off-beats between them.
    for i in range(4):
        beat = 48.0 + i * 2.0
        notes.append(_tap(beat, DL))
        notes.append(_tap(beat, DR))
        notes.append(_mine(beat + 1.0, C))

    notes.append(_tap(56.0, C))
    return notes


def demo_chart() -> Chart:
    """A short single-pad chart, sorted and ready to play."""
    chart = Chart(
        mode=PlayMode.SINGLE,
        timing=demo_timing(),
        notes=demo_notes(),
        level=3,
        difficulty_name="Demo",
        charter="piu",
    )
    chart.sort()
    return chart


def demo_song() -> Song:
    """The demo chart wrapped in the metadata a song select will want."""
    return Song(
        title="Metronome Demo",
        artist="piu",
        charts=[demo_chart()],
    )


def demo_length_beats() -> float:
    """Beats the click track must cover for the whole chart to be playable."""
    notes = demo_notes()
    last = max(
        (n.end_beat if n.end_beat is not None else n.beat) for n in notes
    )
    # A little tail so the final note is not also the last sound.
    return last + 4.0
