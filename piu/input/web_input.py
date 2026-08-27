"""Audio-clock-stamped keyboard input, for the browser build.

Reading input once per frame quantises it by up to a frame - roughly 5ms of
standard deviation at 60Hz before any real jitter is counted. That is a large
fraction of a Perfect window to spend on nothing.

The JS side captures each DOM keydown as it happens and stamps it with the
audio clock, so an input timestamp and a song position share one time base and
subtract cleanly. This module drains that queue.

Falls back to an empty drain off the web, so callers need no platform branch
beyond choosing whether to use it at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from piu import runtime

#: The JS side hands back a flat sequence - code, down flag, timestamp,
#: repeating - because a flat list of primitives crosses the pygbag bridge far
#: more predictably than an array of objects.
FIELDS_PER_EVENT = 3


@dataclass(frozen=True, slots=True)
class KeyEvent:
    """A key transition stamped against the audio clock."""

    code: str
    down: bool
    time: float

    @property
    def key_name(self) -> str:
        """``KeyboardEvent.code`` reduced to the names used by piu.input.layouts.

        ``KeyA`` -> ``a``, ``Numpad7`` -> ``kp7``, ``Comma`` -> ``comma``.
        Physical codes are used rather than ``key`` so the binding follows the
        key's position and does not move under a different keyboard layout.
        """
        code = self.code
        if code.startswith("Key") and len(code) == 4:
            return code[3].lower()
        if code.startswith("Numpad"):
            return "kp" + code[len("Numpad"):].lower()
        if code.startswith("Digit") and len(code) == 6:
            return code[5]
        return code.lower()


class WebKeyboard:
    """Drains timestamped key events from the JS bridge."""

    def __init__(self) -> None:
        self._bridge = None
        if runtime.IS_WEB:
            self._bridge = getattr(runtime.window(), "piuInput", None)
            if self._bridge is None:
                runtime.log(
                    "WARN",
                    "window.piuInput is missing - falling back to frame-polled "
                    "input, which costs about 5ms of timing precision",
                )

    @property
    def available(self) -> bool:
        return self._bridge is not None

    def enable(self) -> None:
        if self._bridge is not None:
            self._bridge.enable()

    def disable(self) -> None:
        if self._bridge is not None:
            self._bridge.disable()

    def drain(self) -> list[KeyEvent]:
        """Every key transition since the last call, oldest first."""
        if self._bridge is None:
            return []

        try:
            flat = list(self._bridge.drain())
        except Exception as error:  # noqa: BLE001 - input must never crash a frame
            runtime.log("WARN", "input drain failed: {}".format(error))
            return []

        events: list[KeyEvent] = []
        for index in range(0, len(flat) - FIELDS_PER_EVENT + 1, FIELDS_PER_EVENT):
            code, down, moment = flat[index : index + FIELDS_PER_EVENT]
            events.append(
                KeyEvent(code=str(code), down=bool(down), time=float(moment))
            )
        return events
