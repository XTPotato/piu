"""The application shell: window, screen stack, and the async main loop.

The loop is a coroutine because pygbag requires it: the browser drives frames
via vsync, and the Python side must yield control back with
``await asyncio.sleep(0)`` once per frame or the page locks up. The same loop
runs unchanged on the desktop, so there is exactly one implementation.

Screens are an explicit stack rather than a single current-screen slot, so a
pause menu or an options overlay can sit on top of gameplay without the
screen underneath losing its state.
"""

from __future__ import annotations

import asyncio

import pygame

from piu import runtime

WINDOW_SIZE = (1280, 720)
WINDOW_TITLE = "piu"

#: Frame cap for the desktop dev build. In the browser this is ignored -
#: pygbag fires the loop on vsync and the cap would only add latency.
DESKTOP_FPS = 240


class Screen:
    """Base class for a screen on the stack.

    ``update`` and ``draw`` are async so a screen can await asset loads or
    audio decoding without blocking the frame.
    """

    def __init__(self, app: App) -> None:
        self.app = app

    async def enter(self) -> None:
        """Called when this screen becomes the top of the stack."""

    async def exit(self) -> None:
        """Called when this screen is popped."""

    def handle_event(self, event: pygame.event.Event) -> None:
        """Handle one input event. Called before `update` each frame."""

    async def update(self, dt: float) -> None:
        """Advance by ``dt`` seconds."""

    async def draw(self, surface: pygame.Surface) -> None:
        """Draw this screen. The stack draws bottom-up."""


class App:
    """Owns the window, the screen stack, and the frame loop."""

    def __init__(self, size: tuple[int, int] = WINDOW_SIZE) -> None:
        self.size = size
        self.screen_stack: list[Screen] = []
        self.running = False
        self.surface: pygame.Surface | None = None
        self.clock: pygame.time.Clock | None = None
        #: Set once the player has interacted. Browsers refuse to start an
        #: AudioContext before a real user gesture, so nothing audible may be
        #: attempted until this is True.
        self.user_gesture = False

    # ------------------------------------------------------------- lifecycle

    def init_display(self) -> None:
        pygame.init()
        # vsync=1 keeps scrolling tear-free. The browser composites on its own
        # schedule, so this is a desktop-only hint and may be ignored.
        self.surface = pygame.display.set_mode(self.size)
        pygame.display.set_caption(WINDOW_TITLE)
        self.clock = pygame.time.Clock()

    def push(self, screen: Screen) -> None:
        self.screen_stack.append(screen)

    def pop(self) -> Screen | None:
        return self.screen_stack.pop() if self.screen_stack else None

    @property
    def top(self) -> Screen | None:
        return self.screen_stack[-1] if self.screen_stack else None

    def quit(self) -> None:
        self.running = False

    # ------------------------------------------------------------- main loop

    async def run(self, initial: Screen | None = None) -> None:
        """Run until the app quits.

        Must be awaited from an ``async def main()`` - see ``main.py``.
        """
        if self.surface is None:
            self.init_display()

        if initial is not None:
            self.push(initial)
            await initial.enter()

        self.running = True
        frames = 0
        while self.running:
            dt = self._tick()
            self._pump_events()

            top = self.top
            if top is None:
                self.running = False
                break

            await top.update(dt)
            await self._draw()

            pygame.display.flip()

            frames += 1
            if frames == 1:
                # The single most useful signal in a browser: if this never
                # appears, the loop never completed a frame, and the problem
                # is upstream of rendering.
                runtime.log("OK", "first frame presented")

            # The yield that makes this work in the browser. Without it the
            # page never regains control and the tab hangs.
            await asyncio.sleep(0)

        pygame.quit()

    def _tick(self) -> float:
        """Advance the frame clock and return delta seconds."""
        assert self.clock is not None
        if runtime.IS_WEB:
            # Frames already arrive on vsync; capping again only adds latency.
            return self.clock.tick() / 1000.0
        return self.clock.tick(DESKTOP_FPS) / 1000.0

    def _pump_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return

            # Any real interaction unlocks audio. Tracked here rather than in
            # a screen so it survives screen changes.
            if event.type in (
                pygame.KEYDOWN,
                pygame.MOUSEBUTTONDOWN,
                pygame.FINGERDOWN,
            ):
                self.user_gesture = True

            top = self.top
            if top is not None:
                top.handle_event(event)

    async def _draw(self) -> None:
        assert self.surface is not None
        self.surface.fill((0, 0, 0))
        # Bottom-up, so an overlay screen draws over what it covers.
        for screen in self.screen_stack:
            await screen.draw(self.surface)
