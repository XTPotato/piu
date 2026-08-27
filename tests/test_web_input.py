"""Browser key-code mapping.

The JS side reports ``KeyboardEvent.code`` - the physical key - so bindings
follow position rather than moving under a different keyboard layout. This
translates those codes into the names piu.input.layouts uses.

Pure string handling, so it runs headlessly even though the surrounding
machinery is browser-only.
"""

from __future__ import annotations

import pytest

from piu.input import layouts
from piu.input.web_input import KeyEvent, WebKeyboard


def name_for(code: str) -> str:
    return KeyEvent(code=code, down=True, time=0.0).key_name


class TestKeyNames:
    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("KeyA", "a"),
            ("KeyW", "w"),
            ("KeyS", "s"),
            ("KeyD", "d"),
            ("KeyX", "x"),
            ("Numpad1", "kp1"),
            ("Numpad7", "kp7"),
            ("Numpad5", "kp5"),
            ("Numpad9", "kp9"),
            ("Numpad3", "kp3"),
            ("Comma", "comma"),
        ],
    )
    def test_maps_browser_codes_to_layout_names(self, code: str, expected: str) -> None:
        assert name_for(code) == expected

    def test_every_shipped_binding_is_reachable_from_a_browser_code(self) -> None:
        # A layout key with no browser code that produces it would be
        # unbindable in the only runtime that ships.
        codes = [
            "KeyA", "KeyW", "KeyS", "KeyD", "KeyX",
            "Numpad1", "Numpad7", "Numpad5", "Numpad9", "Numpad3",
            "KeyN", "KeyY", "KeyH", "KeyI", "Comma",
        ]
        produced = {name_for(code) for code in codes}
        for layout in layouts.LAYOUTS.values():
            for key in layout.all_keys:
                assert key in produced, (
                    "layout {!r} binds {!r}, which no browser code maps to"
                    .format(layout.name, key)
                )

    def test_unknown_codes_degrade_to_lowercase(self) -> None:
        assert name_for("F13") == "f13"


class TestDrainOffWeb:
    def test_is_unavailable_and_drains_empty(self) -> None:
        # On the desktop there is no bridge; callers must not need a guard.
        keyboard = WebKeyboard()
        assert not keyboard.available
        assert keyboard.drain() == []
        keyboard.enable()
        keyboard.disable()
