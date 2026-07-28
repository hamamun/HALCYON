"""Keep the machine (and the screen) awake while media is playing.

The bug this exists for: watching a two-hour film, and having Windows blank the
monitor an hour in because the user has not touched the mouse. From the OS's
point of view the machine has been idle the whole time — Halcyon draws frames
through Qt Quick, and *nothing* about rendering resets the idle timer. Media
players have to say so explicitly.

The mechanism is ``SetThreadExecutionState``:

``ES_CONTINUOUS``
    Make the request stick until it is cleared, rather than nudging the idle
    timer once. Without it the call is a one-shot reset, which would mean
    polling forever and still losing the race.
``ES_DISPLAY_REQUIRED``
    Do not blank the monitor. Requested for **video** only.
``ES_SYSTEM_REQUIRED``
    Do not suspend the machine. Requested for audio as well, because sleeping
    mid-album is just as wrong — but the screen is allowed to switch off, which
    is what you want for an album that plays on for an hour.

Three properties of the API drive the design here:

* It is **per-thread.** The state belongs to whichever thread called it, so
  every call must come from the same thread — the GUI thread, since a QTimer /
  Qt signal is what drives this. Calling it from a VLC callback thread would set
  the flag on a thread that then exits, silently dropping the request.
* It is **not** reference counted. The last call on the thread wins, so the
  state is tracked here and only re-applied when it actually changes.
* It must be **released**, by calling with ``ES_CONTINUOUS`` alone. Leaving a
  display request behind after playback stops is the other half of this bug,
  and the visible symptom is a machine that never sleeps again.

Non-Windows platforms get a no-op object rather than an import error, so the
pure-Python parts of the app keep running anywhere (README: "the app targets
Windows; the pure-Python parts run anywhere").
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QObject, QTimer

log = logging.getLogger(__name__)

# winbase.h
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


class PowerGuard(QObject):
    """Holds a wake request for as long as something is playing.

    Wire it to the engine and forget about it::

        guard = PowerGuard(player, parent=app)

    It listens to state changes, works out whether the current media has a
    picture, and asks Windows for the weakest request that covers it.
    """

    def __init__(self, engine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._current = 0  # the flags currently asserted, 0 = nothing
        self._supported = sys.platform == "win32"

        if self._supported:
            try:
                import ctypes

                self._set_state = ctypes.windll.kernel32.SetThreadExecutionState
                # Returns the previous state as a DWORD; 0 means the call
                # failed. Declaring the types keeps ctypes from truncating the
                # 0x80000000 flag on the way in.
                self._set_state.argtypes = [ctypes.c_uint]
                self._set_state.restype = ctypes.c_uint
            except Exception:
                log.debug("SetThreadExecutionState unavailable", exc_info=True)
                self._supported = False

        engine.stateChanged.connect(self._refresh)
        engine.mediaChanged.connect(self._refresh)
        # A stream can gain or lose its video track after playback starts
        # (cover-art "video" tracks, or a video ES appearing late), and the
        # right answer changes with it.
        engine.tracksChanged.connect(self._refresh)

        # Belt and braces, and cheap: a periodic re-check.
        #
        # ES_CONTINUOUS is sticky, so this is not about re-asserting — _apply()
        # is a no-op when nothing changed. It is about re-*evaluating*: the only
        # input that can change without a signal is has_vout(). A video ES that
        # appears late, or a vout that goes away without an ES event, would
        # otherwise leave the wrong request standing for the rest of the track.
        #
        # has_vout() is a single cheap libVLC call, so a 5 s tick is free at
        # this scale — and 5 s after a film starts is still minutes inside the
        # shortest display timeout Windows offers.
        self._recheck = QTimer(self)
        self._recheck.setInterval(5_000)
        self._recheck.timeout.connect(self._refresh)
        self._recheck.start()
        # Stopped on release() so a quitting app is not still polling.

        self._refresh()

    # ----------------------------------------------------------- internals ---
    def _wanted(self) -> int:
        """The flags the current playback state calls for."""
        from engine.vlc_engine import State

        try:
            playing = int(self._engine.state) == int(State.Playing)
        except Exception:
            playing = False
        if not playing:
            return 0

        flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        if self._has_video():
            flags |= ES_DISPLAY_REQUIRED
        return flags

    def _has_video(self) -> bool:
        """Is a picture actually being displayed?

        ``has_vout()`` is libVLC's own answer and counts the video outputs the
        player currently drives, which is exactly the question — it goes to zero
        when a video ends and the next track is audio, so the display request is
        dropped at the right moment without any extra bookkeeping here.
        """
        player = getattr(self._engine, "raw_player", None)
        if player is None:
            return False
        try:
            return int(player.has_vout()) > 0
        except Exception:
            return False

    def _apply(self, flags: int) -> None:
        if flags == self._current or not self._supported:
            self._current = flags
            return
        # Releasing is ES_CONTINUOUS with no requirement bits — not a call with
        # zero, which is invalid and returns 0.
        try:
            result = self._set_state(flags if flags else ES_CONTINUOUS)
        except Exception:
            log.debug("SetThreadExecutionState raised", exc_info=True)
            return
        if result == 0:
            log.warning("SetThreadExecutionState(0x%08X) failed", flags)
            return
        self._current = flags
        log.debug("power request -> 0x%08X", flags)

    # -------------------------------------------------------------- slots ---
    def _refresh(self, *_args) -> None:
        self._apply(self._wanted())

    # ------------------------------------------------------------ lifecycle ---
    def release(self) -> None:
        """Drop any outstanding request. Called on shutdown.

        Skipping this leaves the display request set for as long as the process
        lives — and, on a crash, until the thread that made it goes away.
        """
        self._recheck.stop()
        self._apply(0)

    @property
    def active(self) -> bool:
        """True while a wake request is held — used by the tests."""
        return self._current != 0

    @property
    def keeping_display_on(self) -> bool:
        return bool(self._current & ES_DISPLAY_REQUIRED)
