"""Tests for the Andamiro ``.ucs`` parser.

The format has no authoritative public spec, so these tests pin down the
semantics this parser assumes. If real files prove a different reading, these
are the assertions to change first.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from piu.formats import ucs
from piu.formats.chart import NoteKind, PlayMode

FIXTURES = Path(__file__).parent / "fixtures"


def parse(text: str):
    return ucs.parse(dedent(text).strip() + "\n")


HEADER = """
    :Format=1
    :Mode=Single
    :BPM=120
    :Delay=0
    :Beat=4
    :Split=2
"""


class TestHeader:
    def test_mode_sets_the_column_count(self) -> None:
        chart = parse(HEADER + "X....\n")
        assert chart.mode is PlayMode.SINGLE
        assert chart.columns == 5

    def test_double_mode_uses_ten_columns(self) -> None:
        chart = parse(
            """
            :Format=1
            :Mode=Double
            :BPM=120
            :Delay=0
            :Beat=4
            :Split=2
            X.........
            """
        )
        assert chart.mode is PlayMode.DOUBLE
        assert chart.columns == 10

    def test_performance_mode_keeps_its_base_panel_count(self) -> None:
        chart = parse(
            """
            :Format=1
            :Mode=S-Performance
            :BPM=120
            :Delay=0
            :Beat=4
            :Split=2
            X....
            """
        )
        assert chart.mode is PlayMode.SINGLE

    def test_unknown_mode_is_rejected(self) -> None:
        with pytest.raises(ucs.UcsParseError, match="unknown mode"):
            parse(
                """
                :Format=1
                :Mode=Quintuple
                :BPM=120
                :Delay=0
                :Beat=4
                :Split=2
                X....
                """
            )

    def test_missing_mode_is_rejected(self) -> None:
        with pytest.raises(ucs.UcsParseError, match="no :Mode="):
            parse(
                """
                :Format=1
                :BPM=120
                :Delay=0
                :Beat=4
                :Split=2
                X....
                """
            )

    def test_rows_before_any_block_are_rejected(self) -> None:
        with pytest.raises(ucs.UcsParseError, match="before any timing block"):
            parse(
                """
                :Format=1
                :Mode=Single
                X....
                """
            )


class TestRowTiming:
    def test_split_sets_ticks_per_beat(self) -> None:
        # Split=2 means each row is half a beat; at 120 BPM that is 0.25 s.
        chart = parse(HEADER + "X....\n.....\nX....\n")
        assert [n.beat for n in chart.notes] == [0.0, 1.0]
        assert [n.time for n in chart.notes] == pytest.approx([0.0, 0.5])

    def test_finer_split_subdivides_further(self) -> None:
        chart = parse(
            """
            :Format=1
            :Mode=Single
            :BPM=120
            :Delay=0
            :Beat=4
            :Split=4
            X....
            X....
            """
        )
        assert [n.beat for n in chart.notes] == [0.0, 0.25]
        assert [n.time for n in chart.notes] == pytest.approx([0.0, 0.125])

    def test_delay_pushes_the_block_back(self) -> None:
        # Delay is milliseconds, and applies before the block's first row.
        chart = parse(
            """
            :Format=1
            :Mode=Single
            :BPM=120
            :Delay=500
            :Beat=4
            :Split=2
            X....
            """
        )
        assert chart.notes[0].time == pytest.approx(0.5)

    def test_bad_split_is_rejected(self) -> None:
        with pytest.raises(ucs.UcsParseError, match="Split must be positive"):
            parse(
                """
                :Format=1
                :Mode=Single
                :BPM=120
                :Delay=0
                :Beat=4
                :Split=0
                X....
                """
            )


class TestSteps:
    def test_taps_land_in_the_right_columns(self) -> None:
        chart = parse(HEADER + "X...X\n..X..\n")
        assert [(n.column, n.kind) for n in chart.notes] == [
            (0, NoteKind.TAP),
            (4, NoteKind.TAP),
            (2, NoteKind.TAP),
        ]

    def test_hold_run_becomes_one_note(self) -> None:
        chart = parse(HEADER + "M....\nH....\nH....\nW....\n")
        assert len(chart.notes) == 1
        hold = chart.notes[0]
        assert hold.kind is NoteKind.HOLD
        assert hold.is_hold
        assert hold.beat == 0.0
        assert hold.end_beat == 1.5
        # Three further rows at half a beat each, 120 BPM -> 0.75 s.
        assert hold.duration == pytest.approx(0.75)

    def test_concurrent_holds_in_separate_columns(self) -> None:
        chart = parse(HEADER + "M...M\nH...H\nW...W\n")
        assert len(chart.notes) == 2
        assert {n.column for n in chart.notes} == {0, 4}
        assert all(n.kind is NoteKind.HOLD for n in chart.notes)

    def test_unterminated_hold_is_rejected(self) -> None:
        with pytest.raises(ucs.UcsParseError, match="never ended"):
            parse(HEADER + "M....\nH....\n")

    def test_hold_body_without_a_start_is_rejected(self) -> None:
        with pytest.raises(ucs.UcsParseError, match="no matching start"):
            parse(HEADER + "H....\n")

    def test_unknown_character_is_rejected(self) -> None:
        with pytest.raises(ucs.UcsParseError, match="unknown step character"):
            parse(HEADER + "Q....\n")

    def test_wrong_column_count_is_rejected(self) -> None:
        with pytest.raises(ucs.UcsParseError, match="expected 5 columns"):
            parse(HEADER + "X..\n")


class TestMultipleBlocks:
    def test_second_block_starts_where_the_first_ended(self) -> None:
        chart = parse(
            """
            :Format=1
            :Mode=Single
            :BPM=120
            :Delay=0
            :Beat=4
            :Split=2
            X....
            .....
            :BPM=240
            :Delay=0
            :Beat=4
            :Split=2
            X....
            """
        )
        # Two rows at half a beat each end the first block on beat 1.
        assert [n.beat for n in chart.notes] == [0.0, 1.0]
        # The second block plays at double tempo from that point.
        assert chart.timing.bpm_at(1.0) == 240.0
        assert [n.time for n in chart.notes] == pytest.approx([0.0, 0.5])

    def test_repeated_bpm_collapses_into_one_segment(self) -> None:
        # Blocks often restate the same BPM purely to change Split.
        chart = parse(
            """
            :Format=1
            :Mode=Single
            :BPM=120
            :Delay=0
            :Beat=4
            :Split=2
            X....
            :BPM=120
            :Delay=0
            :Beat=4
            :Split=4
            X....
            """
        )
        assert len(chart.timing.bpms) == 1


class TestFixtureFile:
    def test_parses_from_disk(self) -> None:
        chart = ucs.parse(FIXTURES / "simple.ucs")
        assert chart.mode is PlayMode.SINGLE

        taps = [n for n in chart.notes if n.kind is NoteKind.TAP]
        holds = [n for n in chart.notes if n.kind is NoteKind.HOLD]
        assert len(taps) == 5
        assert len(holds) == 1

        # Mines never exist in UCS, so every note counts toward combo.
        assert chart.tap_count == len(chart.notes)

    def test_notes_come_back_sorted_by_time(self) -> None:
        chart = ucs.parse(FIXTURES / "simple.ucs")
        times = [n.time for n in chart.notes]
        assert times == sorted(times)
