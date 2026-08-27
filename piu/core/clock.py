"""The song clock: the single source of truth for "where are we in the song".

Every note position, every judgement, and every scroll offset is derived from
`SongClock.position`. If it drifts against what the player hears, the game is
wrong no matter how good everything above it is.

In the browser the clock is ``AudioContext.currentTime``, reached through the
JS bridge in ``tools/web_audio.js``. That clock is driven by the same hardware
that produces the sound, so it cannot drift against the audio the way a
wall-clock timer does. Output latency is subtracted so that `position` means
"what is reaching the speakers now" rather than "what has been submitted to
the audio graph".

This module must not import pygame, and it does no I/O of its own - the bridge
owns anything asynchronous. That keeps `ManualClock` a complete, honest stand-in
for tests, which is where all the arithmetic below is actually verified.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from piu import runtime


class ClockError(RuntimeError):
    """Raised when a clock cannot be prepared or started."""


class SongClock(ABC):
    """Contract shared by every clock implementation."""

    @abstractmethod
    def position(self) -> float:
        """Seconds into the song. Negative during a lead-in."""

    @abstractmethod
    def start(self, at: float = 0.0) -> None:
        """Begin playback from ``at`` seconds."""

    @abstractmethod
    def stop(self) -> None:
        """Stop playback and release the source."""

    @property
    @abstractmethod
    def playing(self) -> bool:
        """Whether audio is currently advancing."""

    @property
    @abstractmethod
    def duration(self) -> float:
        """Length of the loaded audio in seconds, or 0.0 if nothing is loaded."""


class ManualClock(SongClock):
    """A clock driven by explicit `advance` calls.

    Not a mock of the real thing so much as the same arithmetic with a
    hand-cranked time source. Every property the gameplay code relies on -
    monotonic advance, negative lead-in, offset correction, pause and resume -
    is exercised against this in the test suite, with no audio device and no
    browser involved.
    """

    def __init__(self, duration: float = 0.0, offset: float = 0.0) -> None:
        self._duration = float(duration)
        self._offset = float(offset)
        self._elapsed = 0.0
        self._start_at = 0.0
        self._playing = False

    def advance(self, seconds: float) -> None:
        """Move the clock forward. Only advances while playing."""
        if seconds < 0.0:
            raise ValueError("time cannot run backwards: {!r}".format(seconds))
        if self._playing:
            self._elapsed += seconds

    def position(self) -> float:
        return self._start_at + self._elapsed - self._offset

    def start(self, at: float = 0.0) -> None:
        self._start_at = float(at)
        self._elapsed = 0.0
        self._playing = True

    def stop(self) -> None:
        self._playing = False

    def pause(self) -> None:
        self._playing = False

    def resume(self) -> None:
        self._playing = True

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def offset(self) -> float:
        """Calibration offset in seconds, subtracted from every reading."""
        return self._offset

    @offset.setter
    def offset(self, value: float) -> None:
        self._offset = float(value)


class WebAudioClock(SongClock):
    """Clock backed by ``AudioContext.currentTime`` via the JS bridge.

    All asynchronous work - fetching, decoding, resuming a suspended context -
    happens in JavaScript. This class only issues commands and reads back a
    status string and a number, so nothing here depends on bridging a JS
    promise into Python, which is the least dependable part of the interop.

    Usage is therefore poll-shaped::

        clock = WebAudioClock()
        clock.load_click_track(bpm=120, beats=32)
        while clock.state == "loading":
            await asyncio.sleep(0)
        if clock.state == "ready":
            clock.start()
    """

    def __init__(self, offset: float = 0.0) -> None:
        if not runtime.IS_WEB:
            raise ClockError(
                "WebAudioClock requires the browser build; guard construction "
                "with runtime.IS_WEB"
            )
        self._offset = float(offset)
        self._bridge = self._resolve_bridge()

    @staticmethod
    def _resolve_bridge():
        bridge = getattr(runtime.window(), "piuAudio", None)
        if bridge is None:
            raise ClockError(
                "window.piuAudio is missing - the page was built without "
                "tools/web_audio.js. Rebuild with --template tools/piu.tmpl"
            )
        return bridge

    # ------------------------------------------------------------- loading

    def init_context(self) -> bool:
        """Create the AudioContext. Only valid after a user gesture."""
        return bool(self._bridge.init())

    def load_click_track(
        self, bpm: float, beats: int, lead_in: float = 1.0, accent_every: int = 4
    ) -> bool:
        """Synthesize a metronome track with clicks at exact beat positions.

        Used by the timing rig: the reference is arithmetic rather than decoded
        material, so any measured offset belongs to the pipeline rather than to
        the audio file.
        """
        return bool(
            self._bridge.makeClickTrack(float(bpm), int(beats), float(lead_in),
                                        int(accent_every))
        )

    def load_url(self, url: str) -> bool:
        """Begin fetching and decoding ``url``. Poll `state` until it settles."""
        return bool(self._bridge.loadUrl(str(url)))

    # ------------------------------------------------------------- playback

    def start(self, at: float = 0.0) -> None:
        if not self._bridge.play(float(at), 0.12):
            raise ClockError(
                "playback failed to start: {}".format(self.last_error or "unknown")
            )

    def stop(self) -> None:
        self._bridge.stop()

    def pause(self) -> None:
        self._bridge.pause()

    def resume(self) -> None:
        self._bridge.resume()

    def position(self) -> float:
        return float(self._bridge.position()) - self._offset

    def context_time(self) -> float:
        """Raw ``AudioContext.currentTime``.

        Input events are stamped against this so that an input timestamp and a
        song position share one time base, with the latency correction applied
        exactly once.
        """
        return float(self._bridge.contextTime())

    # ------------------------------------------------------------ reporting

    @property
    def playing(self) -> bool:
        return self.state == "playing"

    @property
    def duration(self) -> float:
        return float(self._bridge.duration())

    @property
    def state(self) -> str:
        """One of idle, loading, ready, playing, paused, stopped, error."""
        return str(self._bridge.state())

    @property
    def last_error(self) -> str:
        return str(self._bridge.lastError())

    @property
    def context_state(self) -> str:
        """The AudioContext's own state: running, suspended, closed, or none."""
        return str(self._bridge.contextState())

    @property
    def sample_rate(self) -> float:
        return float(self._bridge.sampleRate())

    @property
    def latency(self) -> float:
        """Output latency in seconds, as the browser reports it.

        Browsers report this inconsistently and some omit it, which is why
        calibration exists regardless of what this returns.
        """
        return float(self._bridge.latency())

    @property
    def offset(self) -> float:
        """Calibration offset in seconds, subtracted from every reading."""
        return self._offset

    @offset.setter
    def offset(self, value: float) -> None:
        self._offset = float(value)
