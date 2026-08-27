"""Tests for the StepMania ``.sm`` / ``.ssc`` parser."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from piu.formats import stepmania
from piu.formats.chart import NoteKind, PlayMode

FIXTURES = Path(__file__).parent / "fixtures"


def parse(text: str):
    return stepmania.parse(dedent(text).lstrip())


def single(notes: str, extra: str = "") -> str:
    """A minimal one-chart simfile wrapping ``notes``."""
    return (
        "#TITLE:T;\n#BPMS:0.000=120.000;\n"
        + extra
        + "#NOTES:\npump-single:\nC:\nHard:\n10:\n0,0,0,0,0:\n"
        + notes
        + ";\n"
    )


class TestSmFixture:
    def test_song_metadata(self) -> None:
        song = stepmania.parse(FIXTURES / "simple.sm")
        assert song.title == "Test Song"
        assert song.artist == "Test Artist"
        assert song.audio_path == "song.ogg"
        assert song.banner_path == "banner.png"
        assert song.sample_start == pytest.approx(32.0)

    def test_only_pump_charts_are_kept(self) -> None:
        song = stepmania.parse(FIXTURES / "simple.sm")
        assert len(song.charts) == 1
        assert song.charts[0].mode is PlayMode.SINGLE

    def test_chart_metadata(self) -> None:
        chart = stepmania.parse(FIXTURES / "simple.sm").charts[0]
        assert chart.level == 17
        assert chart.charter == "Test Charter"
        assert chart.difficulty_name == "Hard"

    def test_measures_subdivide_into_beats(self) -> None:
        chart = stepmania.parse(FIXTURES / "simple.sm").charts[0]
        # Four rows per measure means one row per beat.
        assert [n.beat for n in chart.notes] == [0.0, 2.0, 4.0, 8.0]

    def test_offset_and_bpm_change_apply(self) -> None:
        chart = stepmania.parse(FIXTURES / "simple.sm").charts[0]
        times = [n.time for n in chart.notes]
        # #OFFSET:-0.5 puts beat 0 at 0.5 s; the tempo doubles at beat 4.
        assert times == pytest.approx([0.5, 1.5, 2.5, 3.5])

    def test_hold_spans_from_head_to_tail(self) -> None:
        chart = stepmania.parse(FIXTURES / "simple.sm").charts[0]
        hold = next(n for n in chart.notes if n.kind is NoteKind.HOLD)
        assert hold.beat == 4.0
        assert hold.end_beat == 6.0

    def test_mines_do_not_count_toward_combo(self) -> None:
        chart = stepmania.parse(FIXTURES / "simple.sm").charts[0]
        assert len(chart.notes) == 4
        assert chart.tap_count == 3


class TestSscFixture:
    def test_both_charts_load(self) -> None:
        song = stepmania.parse(FIXTURES / "simple.ssc")
        assert song.title == "SSC Song"
        assert [c.mode for c in song.charts] == [PlayMode.DOUBLE, PlayMode.SINGLE]

    def test_chart_metadata_comes_from_the_notedata_section(self) -> None:
        double = stepmania.parse(FIXTURES / "simple.ssc").charts[0]
        assert double.level == 21
        assert double.charter == "Doubles Charter"
        assert double.difficulty_name == "Crazy"
        assert double.columns == 10

    def test_chart_level_bpms_override_the_song(self) -> None:
        double = stepmania.parse(FIXTURES / "simple.ssc").charts[0]
        assert double.timing.bpm_at(0.0) == 120.0
        # Beat 2 at 120 BPM is one second in.
        assert double.notes[-1].time == pytest.approx(1.0)

    def test_chart_without_timing_inherits_the_song(self) -> None:
        single_chart = stepmania.parse(FIXTURES / "simple.ssc").charts[1]
        assert single_chart.timing.bpm_at(0.0) == 100.0

    def test_notes_land_in_the_right_columns(self) -> None:
        double = stepmania.parse(FIXTURES / "simple.ssc").charts[0]
        assert [n.column for n in double.notes] == [0, 9]


class TestNoteData:
    def test_row_count_sets_the_subdivision(self) -> None:
        song = parse(single("10000\n10000\n10000\n10000\n10000\n10000\n10000\n10000\n"))
        # Eight rows in a four-beat measure are eighth notes.
        assert [n.beat for n in song.charts[0].notes] == [
            0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5
        ]

    def test_measures_are_four_beats_apart(self) -> None:
        song = parse(single("10000\n,\n10000\n"))
        assert [n.beat for n in song.charts[0].notes] == [0.0, 4.0]

    def test_rolls_are_played_as_holds(self) -> None:
        song = parse(single("40000\n00000\n30000\n00000\n"))
        note = song.charts[0].notes[0]
        assert note.kind is NoteKind.HOLD
        assert note.end_beat == 2.0

    def test_fakes_are_dropped(self) -> None:
        song = parse(single("F0000\n10000\n00000\n00000\n"))
        assert len(song.charts[0].notes) == 1

    def test_lifts_are_played_as_taps(self) -> None:
        song = parse(single("L0000\n00000\n00000\n00000\n"))
        assert song.charts[0].notes[0].kind is NoteKind.TAP

    def test_unterminated_hold_ends_at_its_head(self) -> None:
        # Hand-edited files do this; loading the chart beats refusing it.
        song = parse(single("20000\n00000\n00000\n00000\n"))
        hold = song.charts[0].notes[0]
        assert hold.end_beat == hold.beat

    def test_short_row_is_rejected(self) -> None:
        with pytest.raises(stepmania.StepManiaParseError, match="expected 5 columns"):
            parse(single("100\n"))

    def test_comments_are_stripped(self) -> None:
        song = parse(single("10000// trailing note comment\n00000\n00000\n00000\n"))
        assert len(song.charts[0].notes) == 1


class TestTimingTags:
    def test_stops_delay_later_notes(self) -> None:
        song = parse(
            single(
                "10000\n00000\n00000\n00000\n,\n10000\n00000\n00000\n00000\n",
                extra="#STOPS:0.000=1.000;\n",
            )
        )
        times = [n.time for n in song.charts[0].notes]
        # The note on the stop beat is hit as the stop begins; the next
        # measure is pushed back by the stop's full second.
        assert times == pytest.approx([0.0, 3.0])

    def test_delays_push_their_own_note_back(self) -> None:
        song = parse(single("10000\n", extra="#DELAYS:0.000=1.000;\n"))
        assert song.charts[0].notes[0].time == pytest.approx(1.0)

    def test_freezes_is_accepted_as_stops(self) -> None:
        song = parse(
            single(
                "10000\n00000\n00000\n00000\n,\n10000\n00000\n00000\n00000\n",
                extra="#FREEZES:0.000=1.000;\n",
            )
        )
        assert song.charts[0].notes[-1].time == pytest.approx(3.0)

    def test_bpms_may_wrap_across_lines(self) -> None:
        chart = stepmania.parse(FIXTURES / "simple.sm").charts[0]
        assert chart.timing.bpm_at(4.0) == 240.0


class TestWarps:
    def test_notes_inside_a_warp_are_dropped(self) -> None:
        # Beats 0-2 are warped, so only the note on beat 2 survives.
        song = parse(
            single(
                "10000\n10000\n10000\n10000\n",
                extra="#WARPS:0.000=2.000;\n",
            )
        )
        assert [n.beat for n in song.charts[0].notes] == [2.0, 3.0]

    def test_negative_bpm_becomes_a_warp(self) -> None:
        song = parse(
            single(
                "10000\n10000\n10000\n10000\n",
                extra="#BPMS:0.000=120.000,1.000=-9999.000,2.000=120.000;\n",
            )
        )
        chart = song.charts[0]
        assert chart.timing.is_warped(1.0)
        assert not chart.timing.is_warped(2.0)
        # The warped beat is unreachable, so its note is gone.
        assert [n.beat for n in chart.notes] == [0.0, 2.0, 3.0]

    def test_all_negative_bpms_is_an_error(self) -> None:
        with pytest.raises(stepmania.StepManiaParseError, match="no positive BPM"):
            parse(single("10000\n", extra="#BPMS:0.000=-120.000;\n"))


class TestRobustness:
    def test_unknown_steps_type_is_skipped(self) -> None:
        song = parse(
            "#TITLE:T;\n#BPMS:0.000=120.000;\n"
            "#NOTES:\nkaraoke-solo:\nC:\nHard:\n10:\n0,0,0,0,0:\n0000\n;\n"
        )
        assert song.charts == []

    def test_missing_bpms_falls_back_to_a_default(self) -> None:
        song = parse(
            "#TITLE:T;\n"
            "#NOTES:\npump-single:\nC:\nHard:\n10:\n0,0,0,0,0:\n10000\n;\n"
        )
        assert song.charts[0].timing.bpm_at(0.0) == 120.0

    def test_malformed_timing_entries_are_skipped(self) -> None:
        song = parse(single("10000\n", extra="#STOPS:garbage,4.000=0.500;\n"))
        assert len(song.charts[0].timing.stops) == 1
