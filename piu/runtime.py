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
