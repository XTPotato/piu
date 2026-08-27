"""Smoke tests for the async app shell.

These import pygame, so they live outside the headless engine core. They run
under SDL's dummy video driver, which means they work in CI and on a machine
with no display attached.

The point is to catch the failure modes that a WASM build turns into a hung
browser tab: a loop that never yields, a screen stack that empties without
stopping, or a boot screen that never passes the gesture gate.
"""

from __future__ import annotations

import asyncio
import os

import pytest

# Must be set before pygame initialises its video backend.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from piu.app import App, Screen  # noqa: E402
from piu.formats.chart import PlayMode  # noqa: E402
from piu.screens.boot import KEY_CODES, BootScreen, PanelTestScreen  # noqa: E402
from piu.input import layouts  # noqa: E402


@pytest.fixture
def app() -> App:
    instance = App((320, 240))
    instance.init_display()
    yield instance
    pygame.quit()


class CountingScreen(Screen):
    """Quits after a fixed number of frames, so the loop is guaranteed to end."""

    def __init__(self, app: App, frames: int) -> None:
        super().__init__(app)
        self.frames = frames
        self.updates = 0
        self.draws = 0

    async def update(self, dt: float) -> None:
        self.updates += 1
        if self.updates >= self.frames:
            self.app.quit()

    async def draw(self, surface: pygame.Surface) -> None:
        self.draws += 1


class TestMainLoop:
    def test_loop_runs_and_stops(self, app: App) -> None:
        screen = CountingScreen(app, frames=5)
        asyncio.run(app.run(screen))
        assert screen.updates == 5
        assert screen.draws == 5

    def test_loop_stops_when_the_stack_empties(self, app: App) -> None:
        class PoppingScreen(Screen):
            async def update(self, dt: float) -> None:
                self.app.pop()

        asyncio.run(app.run(PoppingScreen(app)))
        assert not app.running

    def test_delta_time_is_seconds(self, app: App) -> None:
        seen: list[float] = []

        class RecordingScreen(Screen):
            async def update(self, dt: float) -> None:
                seen.append(dt)
                if len(seen) >= 3:
                    self.app.quit()

        asyncio.run(app.run(RecordingScreen(app)))
        # Frame deltas are small but never negative, and never milliseconds.
        assert all(0.0 <= dt < 1.0 for dt in seen)

    def test_screens_draw_bottom_up(self, app: App) -> None:
        order: list[str] = []

        class Marker(Screen):
            def __init__(self, app: App, name: str) -> None:
                super().__init__(app)
                self.name = name

            async def update(self, dt: float) -> None:
                self.app.quit()

            async def draw(self, surface: pygame.Surface) -> None:
                order.append(self.name)

        bottom = Marker(app, "bottom")
        app.push(bottom)
        app.push(Marker(app, "top"))
        asyncio.run(app.run())
        assert order == ["bottom", "top"]


class TestGestureGate:
    """Browsers refuse to start audio before a real interaction."""

    def test_no_gesture_recorded_at_startup(self, app: App) -> None:
        assert app.user_gesture is False

    def test_keypress_counts_as_a_gesture(self, app: App) -> None:
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a))
        app._pump_events()
        assert app.user_gesture is True

    def test_click_counts_as_a_gesture(self, app: App) -> None:
        pygame.event.post(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(0, 0))
        )
        app._pump_events()
        assert app.user_gesture is True

    def test_boot_screen_advances_only_after_a_gesture(self, app: App) -> None:
        boot = BootScreen(app)
        app.push(boot)

        asyncio.run(boot.update(0.016))
        assert app.top is boot, "advanced without a user gesture"

        app.user_gesture = True
        asyncio.run(boot.update(0.016))
        assert isinstance(app.top, PanelTestScreen)


class TestPanelTestScreen:
    def test_every_layout_key_resolves_to_a_pygame_code(self) -> None:
        # A key name in a layout with no entry here would be silently
        # unbindable, which is the kind of bug that only shows up in play.
        for layout in layouts.LAYOUTS.values():
            for name in layout.all_keys:
                assert name in KEY_CODES, "no pygame key code for {!r}".format(name)

    def test_holding_a_key_lights_its_column(self, app: App) -> None:
        screen = PanelTestScreen(app)
        screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w))
        # 'w' is Up-Left, which is column 1 in the WASDX layout.
        assert screen._held == {1}

        screen.handle_event(pygame.event.Event(pygame.KEYUP, key=pygame.K_w))
        assert screen._held == set()

    def test_unbound_keys_are_ignored(self, app: App) -> None:
        screen = PanelTestScreen(app)
        screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q))
        assert screen._held == set()

    def test_tab_cycles_mode_and_rebinds(self, app: App) -> None:
        screen = PanelTestScreen(app)
        assert screen.mode is PlayMode.SINGLE

        screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB))
        assert screen.mode is PlayMode.HALF_DOUBLE
        # Half-double starts at the left pad's centre, so 's' is now column 0.
        screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s))
        assert screen._held == {0}

    def test_escape_quits(self, app: App) -> None:
        screen = PanelTestScreen(app)
        app.running = True
        screen.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        assert app.running is False

    def test_draws_without_error_in_every_mode(self, app: App) -> None:
        screen = PanelTestScreen(app)
        surface = pygame.Surface((320, 240))
        for _ in range(3):
            asyncio.run(screen.draw(surface))
            screen._cycle_mode()
