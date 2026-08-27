"""The results screen: what the stage actually came to.

Deliberately more detailed than an arcade would be. This is a development
build, and the numbers a player never sees - stray presses, mines stepped on,
the spread of judgements rather than just the total - are the ones that say
whether the engine did the right thing. When the grade looks wrong, this screen
is where the reason should already be visible.
"""

from __future__ import annotations

import pygame

from piu.app import App, Screen
from piu.formats.chart import Chart
from piu.gameplay.judge import Judgement
from piu.gameplay.session import PlaySession

#: Order judgements are listed in: best first, which is also the order a player
#: reads them in and the order that makes a lopsided run obvious at a glance.
ROWS: tuple[Judgement, ...] = (
    Judgement.PERFECT,
    Judgement.GREAT,
    Judgement.GOOD,
    Judgement.BAD,
    Judgement.MISS,
)

ROW_COLORS: dict[Judgement, tuple[int, int, int]] = {
    Judgement.PERFECT: (255, 232, 120),
    Judgement.GREAT: (120, 240, 150),
    Judgement.GOOD: (120, 190, 245),
    Judgement.BAD: (240, 140, 110),
    Judgement.MISS: (225, 90, 90),
}


def _font(size: int) -> pygame.font.Font:
    return pygame.font.Font(None, size)


class ResultsScreen(Screen):
    """Shows the tally for a finished stage."""

    def __init__(self, app: App, session: PlaySession, chart: Chart) -> None:
        super().__init__(app)
        self.session = session
        self.chart = chart

        self._grade = _font(150)
        self._title = _font(40)
        self._body = _font(28)
        self._small = _font(22)
        self._replay = False

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
            self._replay = True

    async def update(self, dt: float) -> None:
        if not self._replay:
            return
        self._replay = False

        # Imported here rather than at module scope: the two screens reference
        # each other, and a play-again button is not worth an import cycle.
        from piu.screens.gameplay import GameplayScreen

        self.app.pop()
        self.app.push(GameplayScreen(self.app, self.chart))

    async def draw(self, surface: pygame.Surface) -> None:
        surface.fill((14, 14, 20))
        width, _ = surface.get_size()
        board = self.session.board

        heading = "Stage failed" if self.session.failed else "Stage clear"
        color = (230, 110, 100) if self.session.failed else (235, 235, 245)
        title = self._title.render(heading, True, color)
        surface.blit(title, title.get_rect(center=(width // 2, 62)))

        grade = self._grade.render(board.grade.name, True, (250, 240, 190))
        surface.blit(grade, grade.get_rect(center=(width // 2, 178)))

        accuracy = self._title.render(
            "{:.2f}%".format(board.accuracy * 100.0), True, (200, 200, 215)
        )
        surface.blit(accuracy, accuracy.get_rect(center=(width // 2, 262)))

        left = width // 2 - 210
        y = 320
        for judgement in ROWS:
            label = self._body.render(
                judgement.name.title(), True, ROW_COLORS[judgement]
            )
            count = self._body.render(
                str(board.counts[judgement]), True, (225, 225, 235)
            )
            surface.blit(label, (left, y))
            surface.blit(count, count.get_rect(topright=(left + 300, y)))
            y += 36

        combo_text = "Max combo {} / {}".format(board.max_combo, board.total_notes)
        if board.full_combo:
            combo_text += "   FULL COMBO"
        combo = self._body.render(combo_text, True, (235, 235, 245))
        surface.blit(combo, combo.get_rect(center=(width // 2, y + 24)))

        # The diagnostic half: not scored, but the first thing worth reading
        # when a result is surprising.
        diagnostics = "stray presses {}   mines {}   notes {}".format(
            board.stray_presses, board.mines_hit, len(self.chart.notes)
        )
        detail = self._small.render(diagnostics, True, (140, 140, 160))
        surface.blit(detail, detail.get_rect(center=(width // 2, y + 62)))

        hint = self._small.render("Enter to play again", True, (150, 150, 170))
        surface.blit(hint, hint.get_rect(center=(width // 2, y + 100)))
