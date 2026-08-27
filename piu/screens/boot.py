"""Boot and panel-test screens.

`BootScreen` exists for a hard browser constraint, not for decoration:
browsers refuse to start an AudioContext without a genuine user gesture, so
the game must not attempt anything audible before the player clicks or presses
a key. Every later audio path depends on this gate having been passed.

`PanelTestScreen` is the W0 deliverable. It proves, in the real target, that
the async loop runs, input reaches the screen stack, the WASDX mapping
resolves to the right panels, and rendering works - end to end, before any
gameplay exists.
"""

from __future__ import annotations

import pygame

from piu import runtime
from piu.app import App, Screen
from piu.formats.chart import PlayMode, panel_for_column
from piu.input import layouts
from piu.render import panels

BACKGROUND = (12, 12, 18)
TEXT = (236, 236, 240)
MUTED = (128, 128, 140)

#: Layout key names mapped to the *name* of the pygame constant that carries
#: them. The layout tables in piu.input.layouts stay pygame-free so they can be
#: tested headlessly; this is where those names become real key codes.
#:
#: These are stored as strings and resolved lazily on purpose. Under pygbag the
#: pygame module is not fully populated when this module is imported, so
#: evaluating pygame.K_a at module scope raises AttributeError and takes the
#: whole game down before the first frame. Nothing here may touch a pygame
#: attribute at import time.
KEY_CONSTANT_NAMES: dict[str, str] = {
    "a": "K_a",
    "w": "K_w",
    "s": "K_s",
    "d": "K_d",
    "x": "K_x",
    "kp1": "K_KP1",
    "kp7": "K_KP7",
    "kp5": "K_KP5",
    "kp9": "K_KP9",
    "kp3": "K_KP3",
    "n": "K_n",
    "y": "K_y",
    "h": "K_h",
    "i": "K_i",
    "comma": "K_COMMA",
}

_key_codes: dict[str, int] | None = None


def key_codes() -> dict[str, int]:
    """Resolve layout key names to pygame key codes, once, on first use.

    Looks in ``pygame.locals`` first, which is where the constants actually
    live, and falls back to the top-level ``pygame`` namespace that normally
    re-exports them. A name that resolves nowhere is reported and skipped
    rather than raising, so one missing constant cannot cost the whole game.
    """
    global _key_codes
    if _key_codes is not None:
        return _key_codes

    from pygame import locals as pygame_locals

    resolved: dict[str, int] = {}
    missing: list[str] = []
    for name, constant in KEY_CONSTANT_NAMES.items():
        code = getattr(pygame_locals, constant, None)
        if code is None:
            code = getattr(pygame, constant, None)
        if code is None:
            missing.append(constant)
        else:
            resolved[name] = code

    if missing:
        runtime.log(
            "WARN",
            "pygame is missing key constants: {}".format(", ".join(missing)),
            "Those keys will be unbindable. This usually means the pygame "
            "build differs from the desktop one.",
        )

    _key_codes = resolved
    return _key_codes


def _font(size: int) -> pygame.font.Font:
    return pygame.font.Font(None, size)


def _centered(surface: pygame.Surface, text: str, font: pygame.font.Font,
              color: tuple[int, int, int], y: int) -> None:
    rendered = font.render(text, True, color)
    rect = rendered.get_rect(center=(surface.get_width() // 2, y))
    surface.blit(rendered, rect)


class BootScreen(Screen):
    """Waits for the user gesture that unlocks browser audio."""

    def __init__(self, app: App) -> None:
        super().__init__(app)
        self._title = _font(96)
        self._body = _font(32)
        self._small = _font(24)
        self._elapsed = 0.0

    async def update(self, dt: float) -> None:
        self._elapsed += dt
        # App tracks the gesture globally, so any key, click, or tap counts.
        if self.app.user_gesture:
            # The app loop runs the exit/enter hooks once this frame settles.
            self.app.pop()
            self.app.push(PanelTestScreen(self.app))

    async def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BACKGROUND)
        height = surface.get_height()
        _centered(surface, "piu", self._title, TEXT, height // 2 - 90)
        _centered(
            surface,
            "Press any key or click to start",
            self._body,
            TEXT,
            height // 2 + 10,
        )
        _centered(
            surface,
            "Browsers require a gesture before audio can start",
            self._small,
            MUTED,
            height // 2 + 50,
        )
        _centered(surface, runtime.describe(), self._small, MUTED, height - 40)


class PanelTestScreen(Screen):
    """Lights panels as their bound keys are held.

    This is deliberately the first thing built: it exercises the layout
    tables, the panel geometry, and the input path in the browser, so a
    mapping bug is caught before any gameplay is layered on top.
    """

    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.layout = layouts.DEFAULT_LAYOUT
        self.mode = PlayMode.SINGLE
        self._held: set[int] = set()
        self._title = _font(40)
        self._small = _font(24)
        self._rebuild_bindings()

    def _rebuild_bindings(self) -> None:
        """Map pygame key codes to chart columns for the current mode."""
        codes = key_codes()
        self._bindings: dict[int, int] = {}
        for key_name, column in self.layout.key_to_column(self.mode).items():
            code = codes.get(key_name)
            if code is not None:
                self._bindings[code] = column

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.app.quit()
                return
            if event.key == pygame.K_TAB:
                self._cycle_mode()
                return
            if event.key == pygame.K_t:
                self._open_timing_check()
                return
            if event.key == pygame.K_p:
                self._open_gameplay()
                return
            column = self._bindings.get(event.key)
            if column is not None:
                self._held.add(column)
        elif event.type == pygame.KEYUP:
            column = self._bindings.get(event.key)
            if column is not None:
                self._held.discard(column)

    def _open_gameplay(self) -> None:
        # Same reasoning as the timing screen below: gameplay drags in the
        # audio clock and the note field, and neither should load until asked.
        from piu.screens.gameplay import GameplayScreen

        self._held.clear()
        self.app.push(GameplayScreen(self.app))

    def _open_timing_check(self) -> None:
        # Imported here rather than at module scope: the timing screen pulls in
        # the audio clock, and nothing should be loaded until it is asked for.
        from piu.screens.timing_check import TimingCheckScreen

        self._held.clear()
        self.app.push(TimingCheckScreen(self.app))

    def _cycle_mode(self) -> None:
        order = [PlayMode.SINGLE, PlayMode.HALF_DOUBLE, PlayMode.DOUBLE]
        self.mode = order[(order.index(self.mode) + 1) % len(order)]
        self._held.clear()
        self._rebuild_bindings()

    async def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BACKGROUND)
        width, height = surface.get_size()

        _centered(surface, "Panel test - {}".format(self.mode.value),
                  self._title, TEXT, 60)
        _centered(
            surface,
            "Hold the bound keys to light panels   |   TAB changes mode"
            "   |   P play demo   |   T timing check   |   ESC quits",
            self._small,
            MUTED,
            110,
        )

        cell = 110 if self.mode is PlayMode.SINGLE else 72
        columns = self.mode.columns
        keys = self.layout.keys_for(self.mode)

        # The step zone is a row of receptors, one per column - the on-screen
        # layout, not the pad's X.
        rects = panels.lane_rects(
            columns, width=width, top=height // 2 - cell // 2, cell=cell
        )

        for column, rect in enumerate(rects):
            panel = panel_for_column(column, self.mode)
            panels.draw_panel(surface, panel, rect, lit=column in self._held)

            label = self._small.render(keys[column], True, MUTED)
            surface.blit(
                label, label.get_rect(center=(rect.centerx, rect.bottom + 20))
            )

        _centered(surface, runtime.describe(), self._small, MUTED, height - 40)
