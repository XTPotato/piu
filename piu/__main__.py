"""Native development entry point: ``python -m piu``.

The browser is the only shipped target. This exists so iteration on parsing,
layout, and chart loading does not require a WASM rebuild each time - a
native start is seconds faster.

Timing is never evaluated here. The desktop audio path is a convenience
fallback, not a shipping one, so any judgement about whether the game feels
right has to be made in the browser.
"""

from __future__ import annotations

import argparse
import asyncio

from piu.app import App
from piu.screens.boot import BootScreen


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="piu",
        description="Development runner. The shipped build is the web build.",
    )
    parser.add_argument(
        "--size",
        metavar="WxH",
        default=None,
        help="window size, e.g. 1600x900 (default 1280x720)",
    )
    return parser.parse_args(argv)


def _size(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    try:
        width, _, height = text.lower().partition("x")
        return int(width), int(height)
    except ValueError:
        raise SystemExit("--size expects WxH, e.g. 1600x900") from None


async def _run(size: tuple[int, int] | None) -> None:
    app = App(size) if size else App()
    app.init_display()
    await app.run(BootScreen(app))


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(_run(_size(args.size)))


if __name__ == "__main__":
    main()
