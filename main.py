"""pygbag entry point.

pygbag packages the folder containing ``main.py`` and calls it as the program
entry, so this file must sit at the repository root and must drive the game
through ``asyncio.run`` on an ``async def main()``.

Keep this file thin. Everything real lives in the ``piu`` package so it stays
importable by the test suite, which never touches this module.
"""

import asyncio

from piu.app import App
from piu.screens.boot import BootScreen


async def main() -> None:
    app = App()
    app.init_display()
    await app.run(BootScreen(app))


asyncio.run(main())
