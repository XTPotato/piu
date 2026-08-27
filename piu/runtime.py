"""Platform detection and the browser bridge.

The game ships as WebAssembly and runs natively only as a development
convenience. This module is the one place that knows the difference, so the
rest of the codebase can stay platform-agnostic.

Under pygbag, ``sys.platform`` is ``"emscripten"`` and a ``platform`` module is
injected into the runtime exposing ``window`` - the browser's global object.
That is how `piu.core.clock` reaches the Web Audio API and how
`piu.core.storage` reaches localStorage.

Keeping the JS-facing surface confined to this module matters: pygbag is
pre-1.0, so when its API shifts, the blast radius is one file.
"""

from __future__ import annotations

import sys
from typing import Any

#: True when running as WebAssembly under pygbag. This is the documented
#: check - pygbag sets sys.platform to "emscripten".
IS_WEB: bool = sys.platform == "emscripten"


class BrowserUnavailableError(RuntimeError):
    """Raised when browser-only functionality is reached on the desktop."""


def window() -> Any:
    """The browser's ``window`` object.

    Raises `BrowserUnavailableError` on desktop, so a missing platform guard
    fails loudly at the call site instead of silently degrading.
    """
    if not IS_WEB:
        raise BrowserUnavailableError(
            "window() is only available in the browser build; "
            "guard the call site with runtime.IS_WEB"
        )
    # Imported lazily and by name: on desktop this would resolve to the
    # standard library's platform module, which has no window attribute.
    import platform  # noqa: PLC0415 - pygbag injects its own module here

    return platform.window


def describe() -> str:
    """A short human-readable runtime description, for logs and the title screen."""
    if IS_WEB:
        return "web (pygbag/WASM, CPython {}.{})".format(*sys.version_info[:2])
    return "desktop dev build (CPython {}.{}, {})".format(
        *sys.version_info[:2], sys.platform
    )


def log(kind: str, message: str, detail: str = "") -> None:
    """Report a boot or runtime event.

    In the browser this forwards to the on-page diagnostics panel installed by
    ``tools/boot_diagnostics.js``, so a Python-side failure is visible to
    whoever is looking at the page rather than only in the developer console.
    On the desktop it prints.

    Never raises: diagnostics must not be able to break the thing they are
    diagnosing.
    """
    text = message if not detail else "{}\n{}".format(message, detail)
    if IS_WEB:
        try:
            bridge = getattr(window(), "piuBootLog", None)
            if bridge is not None:
                bridge(kind, message, detail)
                return
        except Exception:  # noqa: BLE001 - see docstring
            pass
    print("[piu] {:<5} {}".format(kind, text), flush=True)


def report_exception(context: str, error: BaseException) -> None:
    """Log a formatted traceback for ``error``, tagged with what was happening.

    A bare exception message rarely says which stage failed, so the context
    string carries that - "importing the game package", "opening the display",
    and so on.
    """
    import traceback  # noqa: PLC0415 - only needed on the failure path

    detail = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    ).rstrip()
    log("FAIL", "{}: {}: {}".format(context, type(error).__name__, error), detail)
