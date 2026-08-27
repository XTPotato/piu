"""Keyboard layout tests.

These pin the WASDX mapping, which is the default binding shipped in V1.
Layouts are pure data, so this runs with no pygame and no display.
"""

from __future__ import annotations

import pytest

from piu.formats.chart import Panel, PlayMode, panel_for_column
from piu.input import layouts


class TestWasdx:
    """The default layout: a 45 degree rotation of the key plus onto the panel X."""

    @pytest.mark.parametrize(
        ("key", "panel"),
        [
            ("w", Panel.UP_LEFT),
            ("d", Panel.UP_RIGHT),
            ("s", Panel.CENTER),
            ("a", Panel.DOWN_LEFT),
            ("x", Panel.DOWN_RIGHT),
        ],
    )
    def test_each_key_reaches_its_panel(self, key: str, panel: Panel) -> None:
        column = layouts.WASDX.column_for_key(key, PlayMode.SINGLE)
        assert column is not None
        assert panel_for_column(column, PlayMode.SINGLE) is panel

    def test_single_mode_uses_only_the_left_pad(self) -> None:
        assert layouts.WASDX.keys_for(PlayMode.SINGLE) == ("a", "w", "s", "d", "x")

    def test_unbound_key_returns_none(self) -> None:
        assert layouts.WASDX.column_for_key("q", PlayMode.SINGLE) is None

    def test_right_pad_keys_are_unbound_in_single(self) -> None:
        assert layouts.WASDX.column_for_key("kp7", PlayMode.SINGLE) is None

    def test_is_the_default(self) -> None:
        assert layouts.DEFAULT_LAYOUT is layouts.WASDX


class TestNumpadPad:
    """The numpad already sits in an X, so it needs no rotation."""

    @pytest.mark.parametrize(
        ("key", "panel"),
        [
            ("kp7", Panel.UP_LEFT),
            ("kp9", Panel.UP_RIGHT),
            ("kp5", Panel.CENTER),
            ("kp1", Panel.DOWN_LEFT),
            ("kp3", Panel.DOWN_RIGHT),
        ],
    )
    def test_numpad_matches_panel_geometry(self, key: str, panel: Panel) -> None:
        column = layouts.NUMPAD.column_for_key(key, PlayMode.SINGLE)
        assert column is not None
        assert panel_for_column(column, PlayMode.SINGLE) is panel


class TestDouble:
    def test_ten_columns_are_bound(self) -> None:
        keys = layouts.WASDX.keys_for(PlayMode.DOUBLE)
        assert len(keys) == 10
        assert len(set(keys)) == 10

    def test_left_pad_is_wasdx_and_right_pad_is_numpad(self) -> None:
        keys = layouts.WASDX.keys_for(PlayMode.DOUBLE)
        assert keys[:5] == ("a", "w", "s", "d", "x")
        assert keys[5:] == ("kp1", "kp7", "kp5", "kp9", "kp3")

    def test_both_pads_repeat_the_panel_pattern(self) -> None:
        for column in range(10):
            assert panel_for_column(column, PlayMode.DOUBLE) is Panel(column % 5)


class TestHalfDouble:
    def test_uses_the_middle_six_panels(self) -> None:
        keys = layouts.WASDX.keys_for(PlayMode.HALF_DOUBLE)
        assert len(keys) == 6
        # Physical indices 2 through 7 of the ten-panel setup.
        assert keys == ("s", "d", "x", "kp1", "kp7", "kp5")

    def test_first_column_is_the_left_pad_centre(self) -> None:
        assert panel_for_column(0, PlayMode.HALF_DOUBLE) is Panel.CENTER

    def test_panels_run_contiguously_across_the_gap(self) -> None:
        expected = [
            Panel.CENTER,
            Panel.UP_RIGHT,
            Panel.DOWN_RIGHT,
            Panel.DOWN_LEFT,
            Panel.UP_LEFT,
            Panel.CENTER,
        ]
        actual = [panel_for_column(c, PlayMode.HALF_DOUBLE) for c in range(6)]
        assert actual == expected

    def test_keys_agree_with_panels(self) -> None:
        # The half-double slice must line up with the panel offset; if one is
        # changed without the other, this catches it.
        keys = layouts.WASDX.keys_for(PlayMode.HALF_DOUBLE)
        double_keys = layouts.WASDX.keys_for(PlayMode.DOUBLE)
        for column, key in enumerate(keys):
            physical = double_keys.index(key)
            assert panel_for_column(column, PlayMode.HALF_DOUBLE) is Panel(
                physical % 5
            )


class TestLayoutRegistry:
    def test_lookup_by_name(self) -> None:
        assert layouts.get("wasdx") is layouts.WASDX
        assert layouts.get("NUMPAD") is layouts.NUMPAD

    def test_unknown_name_falls_back_to_the_default(self) -> None:
        assert layouts.get("dance-pad") is layouts.DEFAULT_LAYOUT

    def test_key_to_column_covers_every_column(self) -> None:
        lookup = layouts.WASDX.key_to_column(PlayMode.DOUBLE)
        assert sorted(lookup.values()) == list(range(10))

    def test_duplicate_bindings_are_rejected(self) -> None:
        with pytest.raises(layouts.LayoutError, match="more than one panel"):
            layouts.KeyboardLayout(
                name="broken",
                description="binds w twice",
                left=("a", "w", "s", "d", "x"),
                right=("w", "kp7", "kp5", "kp9", "kp3"),
            )

    def test_shipped_layouts_are_internally_consistent(self) -> None:
        for layout in layouts.LAYOUTS.values():
            assert len(set(layout.all_keys)) == 10
