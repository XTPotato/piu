"""Built-in keyboard layouts, as pure data.

Keys are named as lowercase strings here rather than pygame constants, so the
mapping from key to panel can be tested with no display and no pygame import.
`piu.input.devices` resolves these names to SDL key codes.

Why WASDX maps the way it does
------------------------------
The panels form an X; ``W A S D X`` forms a plus. Rather than assign the five
keys arbitrarily, the default layout is a single 45 degree counter-clockwise
rotation of the plus onto the X, which makes it learnable::

     Panels                  Keys                Mapping
    UL     UR                  W            W -> Up-Left     (N -> NW)
        C          <-- 45 --  A  S  D       D -> Up-Right    (E -> NE)
    DL     DR                  X            S -> Center
                                            A -> Down-Left   (W -> SW)
                                            X -> Down-Right  (S -> SE)

The numpad needs no such trick - ``7 9 5 1 3`` already sit in an X - so it
ships as the second preset and as the right pad for Double.

This module must not import pygame.
"""

from __future__ import annotations

from dataclasses import dataclass

from piu.formats.chart import HALF_DOUBLE_OFFSET, Panel, PlayMode

#: Columns are ordered by `Panel`: Down-Left, Up-Left, Center, Up-Right,
#: Down-Right. Every layout tuple below follows that order.
PANEL_ORDER: tuple[Panel, ...] = (
    Panel.DOWN_LEFT,
    Panel.UP_LEFT,
    Panel.CENTER,
    Panel.UP_RIGHT,
    Panel.DOWN_RIGHT,
)

PadKeys = tuple[str, str, str, str, str]


class LayoutError(ValueError):
    """Raised when a layout is self-inconsistent."""


@dataclass(frozen=True, slots=True)
class KeyboardLayout:
    """Key names for both pads, in `PANEL_ORDER` per pad."""

    name: str
    description: str
    left: PadKeys
    right: PadKeys

    def __post_init__(self) -> None:
        keys = self.left + self.right
        duplicates = {k for k in keys if keys.count(k) > 1}
        if duplicates:
            raise LayoutError(
                "layout {!r} binds {} to more than one panel".format(
                    self.name, ", ".join(sorted(duplicates))
                )
            )

    @property
    def all_keys(self) -> tuple[str, ...]:
        return self.left + self.right

    def keys_for(self, mode: PlayMode) -> tuple[str, ...]:
        """Key names indexed by chart column, for ``mode``.

        Half-double occupies the middle six panels of a ten-panel setup, so it
        takes the middle six keys.
        """
        if mode is PlayMode.SINGLE:
            return self.left
        if mode is PlayMode.HALF_DOUBLE:
            start = HALF_DOUBLE_OFFSET
            return self.all_keys[start : start + mode.columns]
        return self.all_keys

    def column_for_key(self, key: str, mode: PlayMode) -> int | None:
        """Chart column a key drives, or None if it is unbound in ``mode``."""
        keys = self.keys_for(mode)
        try:
            return keys.index(key)
        except ValueError:
            return None

    def key_to_column(self, mode: PlayMode) -> dict[str, int]:
        """Full key-name to column lookup, for building an input dispatch."""
        return {key: column for column, key in enumerate(self.keys_for(mode))}


#: The default. Left pad on WASDX, right pad on the numpad, so Double mode is
#: one hand per pad.
WASDX = KeyboardLayout(
    name="wasdx",
    description="WASDX on the left pad, numpad on the right",
    left=("a", "w", "s", "d", "x"),
    right=("kp1", "kp7", "kp5", "kp9", "kp3"),
)

#: Numpad for the left pad too, for players who prefer a literal X shape on
#: both sides. The right pad moves to the ZXCVB row area.
NUMPAD = KeyboardLayout(
    name="numpad",
    description="Numpad on the left pad, YGHJN on the right",
    left=("kp1", "kp7", "kp5", "kp9", "kp3"),
    right=("n", "y", "h", "i", "comma"),
)

LAYOUTS: dict[str, KeyboardLayout] = {
    layout.name: layout for layout in (WASDX, NUMPAD)
}

DEFAULT_LAYOUT = WASDX


def get(name: str) -> KeyboardLayout:
    """Look up a layout by name, defaulting to WASDX if it is unknown."""
    return LAYOUTS.get(name.strip().lower(), DEFAULT_LAYOUT)
