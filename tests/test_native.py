"""Tests for the native JSON format and the loader registry.

The round-trip tests are the important ones: they assert that a chart imported
from any format survives a trip through native JSON unchanged, which is what
makes the canonical model trustworthy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import piu.formats as formats
from piu.formats import native, stepmania, ucs
from piu.formats.chart import NoteKind, PlayMode

FIXTURES = Path(__file__).parent / "fixtures"


def minimal(**overrides) -> dict:
    data = {
        "format": "piu-song",
        "version": 1,
        "title": "Demo",
        "artist": "Nobody",
        "audio": "track.ogg",
        "charts": [
            {
                "mode": "single",
                "level": 4,
                "difficulty": "Easy",
                "timing": {"offset": 0.0, "bpms": [[0.0, 120.0]]},
                "notes": [
                    {"beat": 0.0, "column": 0, "kind": "tap"},
                    {"beat": 2.0, "column": 2, "kind": "hold", "end_beat": 4.0},
                ],
            }
        ],
    }
    data.update(overrides)
    return data


class TestLoading:
    def test_song_metadata(self) -> None:
        song = native.load_song(minimal())
        assert song.title == "Demo"
        assert song.audio_path == "track.ogg"
        assert len(song.charts) == 1

    def test_times_are_derived_not_stored(self) -> None:
        song = native.load_song(minimal())
        notes = song.charts[0].notes
        assert notes[0].time == pytest.approx(0.0)
        assert notes[1].time == pytest.approx(1.0)
        assert notes[1].end_time == pytest.approx(2.0)

    def test_loads_from_json_text(self) -> None:
        song = native.load_song(json.dumps(minimal()))
        assert song.title == "Demo"

    def test_bare_chart_document_becomes_a_one_chart_song(self) -> None:
        chart_doc = native.dump_chart(native.load_song(minimal()).charts[0])
        song = native.load_song(chart_doc)
        assert len(song.charts) == 1
        assert song.charts[0].level == 4

    def test_load_chart_accepts_a_song_document(self) -> None:
        chart = native.load_chart(minimal())
        assert chart.mode is PlayMode.SINGLE


class TestValidation:
    def test_wrong_format_is_rejected(self) -> None:
        with pytest.raises(native.NativeParseError, match="expected format"):
            native.load_song({"format": "something-else"})

    def test_future_version_is_rejected(self) -> None:
        with pytest.raises(native.NativeParseError, match="unsupported version"):
            native.load_song(minimal(version=99))

    def test_invalid_json_is_rejected(self) -> None:
        with pytest.raises(native.NativeParseError, match="not valid JSON"):
            native.load_song("{not json")

    def test_unknown_mode_is_rejected(self) -> None:
        data = minimal()
        data["charts"][0]["mode"] = "quintuple"
        with pytest.raises(native.NativeParseError, match="unknown mode"):
            native.load_song(data)

    def test_column_out_of_range_is_rejected(self) -> None:
        data = minimal()
        data["charts"][0]["notes"] = [{"beat": 0.0, "column": 7, "kind": "tap"}]
        with pytest.raises(native.NativeParseError, match="out of range"):
            native.load_song(data)

    def test_hold_without_an_end_is_rejected(self) -> None:
        data = minimal()
        data["charts"][0]["notes"] = [{"beat": 0.0, "column": 0, "kind": "hold"}]
        with pytest.raises(native.NativeParseError, match="no 'end_beat'"):
            native.load_song(data)

    def test_note_missing_a_beat_is_rejected(self) -> None:
        data = minimal()
        data["charts"][0]["notes"] = [{"column": 0}]
        with pytest.raises(native.NativeParseError, match="numeric"):
            native.load_song(data)


class TestRoundTrip:
    """A chart must survive dump -> load unchanged, whatever format it began as."""

    @staticmethod
    def assert_same(first, second) -> None:
        assert first.mode is second.mode
        assert first.level == second.level
        assert len(first.notes) == len(second.notes)
        for a, b in zip(first.notes, second.notes):
            assert a.column == b.column
            assert a.kind is b.kind
            assert a.beat == pytest.approx(b.beat)
            assert a.time == pytest.approx(b.time)
            if a.end_beat is None:
                assert b.end_beat is None
            else:
                assert a.end_beat == pytest.approx(b.end_beat)
                assert a.end_time == pytest.approx(b.end_time)

    def test_native_round_trip(self) -> None:
        original = native.load_song(minimal())
        reloaded = native.load_song(native.dump_song(original))
        self.assert_same(original.charts[0], reloaded.charts[0])

    def test_sm_survives_a_trip_through_native(self) -> None:
        original = stepmania.parse(FIXTURES / "simple.sm").charts[0]
        reloaded = native.load_chart(native.dump_chart(original))
        self.assert_same(original, reloaded)

    def test_ssc_survives_a_trip_through_native(self) -> None:
        for original in stepmania.parse(FIXTURES / "simple.ssc").charts:
            reloaded = native.load_chart(native.dump_chart(original))
            self.assert_same(original, reloaded)

    def test_ucs_survives_a_trip_through_native(self) -> None:
        original = ucs.parse(FIXTURES / "simple.ucs")
        reloaded = native.load_chart(native.dump_chart(original))
        self.assert_same(original, reloaded)

    def test_timing_features_survive(self) -> None:
        # Stops, delays, and warps must all come back distinguishable.
        data = minimal()
        data["charts"][0]["timing"] = {
            "offset": -0.25,
            "bpms": [[0.0, 120.0], [8.0, 90.0]],
            "stops": [[4.0, 0.5]],
            "delays": [[6.0, 0.25]],
            "warps": [[10.0, 2.0]],
        }
        original = native.load_song(data).charts[0]
        reloaded = native.load_chart(native.dump_chart(original))

        assert reloaded.timing.offset == pytest.approx(-0.25)
        assert len(reloaded.timing.bpms) == 2
        assert len(reloaded.timing.warps) == 1
        assert sum(1 for s in reloaded.timing.stops if s.is_delay) == 1
        assert sum(1 for s in reloaded.timing.stops if not s.is_delay) == 1
        assert reloaded.timing.beat_to_time(9.0) == pytest.approx(
            original.timing.beat_to_time(9.0)
        )

    def test_writes_to_disk(self, tmp_path: Path) -> None:
        song = native.load_song(minimal())
        target = tmp_path / "song.json"
        native.write(song, target)
        assert native.load_song(target).title == "Demo"


class TestRegistry:
    @pytest.mark.parametrize(
        ("filename", "expected_charts"),
        [("simple.sm", 1), ("simple.ssc", 2), ("simple.ucs", 1)],
    )
    def test_dispatches_on_extension(self, filename: str, expected_charts: int) -> None:
        song = formats.load(FIXTURES / filename)
        assert len(song.charts) == expected_charts

    def test_unknown_extension_is_rejected(self) -> None:
        with pytest.raises(formats.UnknownFormatError, match="no parser"):
            formats.load(FIXTURES / "simple.txt")

    def test_supported_extensions_are_advertised(self) -> None:
        assert set(formats.supported_extensions()) == {".sm", ".ssc", ".ucs", ".json"}


class TestLibraryScanning:
    def make_song_folder(self, root: Path, name: str, filename: str) -> Path:
        folder = root / name
        folder.mkdir(parents=True)
        (folder / filename).write_bytes((FIXTURES / filename).read_bytes())
        return folder

    def test_scans_song_folders(self, tmp_path: Path) -> None:
        self.make_song_folder(tmp_path, "Song A", "simple.sm")
        self.make_song_folder(tmp_path, "Song B", "simple.ssc")
        songs = formats.scan(tmp_path)
        assert {s.title for s in songs} == {"Test Song", "SSC Song"}

    def test_scans_one_level_of_packs(self, tmp_path: Path) -> None:
        self.make_song_folder(tmp_path / "Pack", "Song A", "simple.sm")
        songs = formats.scan(tmp_path)
        assert [s.title for s in songs] == ["Test Song"]

    def test_ssc_wins_over_sm_in_the_same_folder(self, tmp_path: Path) -> None:
        folder = self.make_song_folder(tmp_path, "Both", "simple.sm")
        (folder / "simple.ssc").write_bytes((FIXTURES / "simple.ssc").read_bytes())
        songs = formats.scan(tmp_path)
        assert len(songs) == 1
        assert songs[0].title == "SSC Song"

    def test_loose_ucs_charts_join_the_simfile(self, tmp_path: Path) -> None:
        folder = self.make_song_folder(tmp_path, "Song", "simple.sm")
        (folder / "extra.ucs").write_bytes((FIXTURES / "simple.ucs").read_bytes())
        songs = formats.scan(tmp_path)
        assert len(songs) == 1
        # One pump chart from the .sm, plus the .ucs chart.
        assert len(songs[0].charts) == 2

    def test_ucs_only_folder_uses_its_name_as_the_title(self, tmp_path: Path) -> None:
        self.make_song_folder(tmp_path, "Custom Steps", "simple.ucs")
        songs = formats.scan(tmp_path)
        assert [s.title for s in songs] == ["Custom Steps"]

    def test_missing_library_is_not_an_error(self, tmp_path: Path) -> None:
        assert formats.scan(tmp_path / "nope") == []

    def test_empty_folders_are_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "Empty").mkdir()
        assert formats.scan(tmp_path) == []
