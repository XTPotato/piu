"""Panel colors and geometry.

Two different layouts live here, and confusing them is an easy mistake:

* **The physical pad** is an X - the two up-panels on top, the two down-panels
  below, the center between them. `panel_rect` draws that arrangement, for pad
  diagrams in options and binding screens.
* **The screen** is a row. Notes scroll upward in vertical lanes and the step
  zone is a horizontal strip of receptors, one per column, left to right.
  `lane_rects` computes that.

Corner panels are colored by axis - the down pair red, the up pair blue, the
center yellow - which is how a player reads the field at speed.
"""

from __future__ import annotations

import pygame

from piu.formats.chart import Panel

#: Panel fill colors, keyed by panel.
PANEL_COLORS: dict[Panel, tuple[int, int, int]] = {
    Panel.DOWN_LEFT: (214, 44, 62),
    Panel.UP_LEFT: (58, 118, 232),
    Panel.CENTER: (240, 198, 52),
    Panel.UP_RIGHT: (58, 118, 232),
    Panel.DOWN_RIGHT: (214, 44, 62),
}

#: Where each panel sits inside one pad, as (column, row) in a 3x3 grid.
#: The X shape leaves the grid's edge midpoints empty.
PANEL_GRID: dict[Panel, tuple[int, int]] = {
    Panel.UP_LEFT: (0, 0),
    Panel.UP_RIGHT: (2, 0),
    Panel.CENTER: (1, 1),
    Panel.DOWN_LEFT: (0, 2),
    Panel.DOWN_RIGHT: (2, 2),
}


def panel_rect(
    panel: Panel, origin: tuple[int, int], cell: int, gap: int = 0
) -> pygame.Rect:
    """Rect for one panel of a pad whose top-left corner is ``origin``."""
    column, row = PANEL_GRID[panel]
    return pygame.Rect(
        origin[0] + column * (cell + gap),
        origin[1] + row * (cell + gap),
        cell,
        cell,
    )


def pad_size(cell: int, gap: int = 0) -> int:
    """Edge length of one three-by-three pad diagram."""
    return cell * 3 + gap * 2


def lane_rects(
    columns: int,
    *,
    width: int,
    top: int,
    cell: int,
    gap: int = 6,
) -> list[pygame.Rect]:
    """Receptor rects for a step zone, one per column, centered in ``width``.

    This is the on-screen layout: a horizontal row, not the pad's X.
    """
    stride = cell + gap
    total = stride * columns - gap
    left = (width - total) // 2
    return [
        pygame.Rect(left + index * stride, top, cell, cell)
        for index in range(columns)
    ]


def draw_panel(
    surface: pygame.Surface,
    panel: Panel,
    rect: pygame.Rect,
    *,
    lit: bool = False,
) -> None:
    """Draw one panel. ``lit`` brightens it, as a step zone does on a hit."""
    color = PANEL_COLORS[panel]
    if lit:
        color = tuple(min(255, channel + 90) for channel in color)
        pygame.draw.rect(surface, color, rect, border_radius=6)
    else:
        # Unlit panels are outlines, so notes stay readable over them.
        pygame.draw.rect(surface, color, rect, width=3, border_radius=6)
