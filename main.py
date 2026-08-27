"""pygbag entry point.

pygbag packages the folder containing ``main.py`` and calls it as the program
entry, so this file must sit at the repository root and must drive the game
through ``asyncio.run`` on an ``async def main()``.

Every startup stage is logged. In the browser those lines land in the on-page
diagnostics panel, so a failure names the stage that broke instead of leaving
a blank canvas. That matters more here than on the desktop: there is no
console in front of a player, and a WASM stall looks identical to a hang.

Keep this file thin. Everything real lives in the ``piu`` package so it stays
importable by the test suite, which never touches this module.
"""

# /// script
# dependencies = ["pygame-ce"]
# ///

import asyncio
import sys

# This import looks unused, and it is not. pygbag decides which packages to
# install by statically parsing THIS file's imports (aio.pep0723.check_list ->
# parse_code, given main.py's source). An import of pygame nested inside
# piu/app.py is invisible to that scan, so pygame is never installed and the
# module resolves to an empty stub - which surfaces much later and very
# confusingly as "module 'pygame' has no attribute 'init'".
#
# Any third-party package the game needs at runtime must be imported here, at
# top level, for the same reason. tests/test_entrypoint.py enforces it.
import pygame  # noqa: F401


def _bootstrap_failure(context: str, error: BaseException) -> None:
    """Report a failure that happened before piu.runtime was usable."""
    import traceback

    detail = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    ).rstrip()
    print("[piu] FAIL  {}: {}: {}".format(context, type(error).__name__, error))
    print(detail)

    # The diagnostics panel is installed by the page itself, so it is
    # reachable even when the Python side failed to import.
    try:
        import platform

        bridge = getattr(platform.window, "piuBootLog", None)
        if bridge is not None:
            bridge("FAIL", "{}: {}".format(context, error), detail)
    except Exception:
        pass


try:
    from piu import runtime
    from piu.app import App
    from piu.screens.boot import BootScreen
except BaseException as error:  # noqa: BLE001 - last chance to say anything
    _bootstrap_failure("importing the game package", error)
    raise


async def main() -> None:
    runtime.log("BOOT", "python entry reached: {}".format(runtime.describe()))
    runtime.log("BOOT", "python {}".format(sys.version.replace("\n", " ")))

    app = App()

    try:
        runtime.log("BOOT", "opening the display")
        app.init_display()
        runtime.log(
            "OK", "display ready at {}x{}".format(*app.size)
        )
    except BaseException as error:  # noqa: BLE001
        runtime.report_exception("opening the display", error)
        raise

    try:
        runtime.log("BOOT", "entering the main loop")
        await app.run(BootScreen(app))
        runtime.log("BOOT", "main loop exited cleanly")
    except BaseException as error:  # noqa: BLE001
        runtime.report_exception("running the main loop", error)
        raise


asyncio.run(main())
