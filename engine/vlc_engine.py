"""libVLC lifecycle and playback — Milestone 1.1.

The only place in Halcyon that talks to libVLC. Everything above it sees Qt
signals and plain properties; nothing above it imports ``vlc``.

Two things in here are load-bearing and easy to get wrong:

**Callback lifetime (§9, High).** libVLC event callbacks are C function pointers.
If Python garbage-collects the trampoline while VLC still holds the address, the
process dies with no traceback. Every callback is stored on ``self``.

**Shutdown order (§9, Med).** ``stop()`` → wait for the player to actually stop →
*then* ``release()``. Releasing from inside a Qt slot that is itself running on a
VLC event callback deadlocks or crashes. Event callbacks here therefore never do
work; they emit a queued Qt signal and return immediately.
"""

from __future__ import annotations

import logging
import math
import os
import sys
import time
from enum import IntEnum
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QObject,
    QTimer,
    QUrl,
    Signal,
    Slot,
)

from core import paths
from core import video_mode as video_policy
from engine.video_out import Chroma, VideoOutput

log = logging.getLogger(__name__)

# Keep Windows DLL-directory handles alive for the lifetime of the process.
# ``os.add_dll_directory`` removes the search path when its returned handle is
# garbage-collected; retaining only the path is not sufficient for libvlccore
# and the plugin DLLs on Python 3.8+.
_DLL_DIRECTORY_HANDLES = []


class State(IntEnum):
    """Mirrors ``libvlc_state_t`` but decoupled from it, so UI code never
    imports ``vlc``."""

    Idle = 0
    Opening = 1
    Buffering = 2
    Playing = 3
    Paused = 4
    Stopped = 5
    Ended = 6
    Error = 7


_VLC_STATE_MAP = {
    0: State.Idle,      # NothingSpecial
    1: State.Opening,
    2: State.Buffering,
    3: State.Playing,
    4: State.Paused,
    5: State.Stopped,
    6: State.Ended,
    7: State.Error,
}

#: States in which the player is not holding the decoder open any more.
_SETTLED_STATES = (0, 5, 6, 7)

# Qt's ``int`` properties and Signal(int) use a signed 32-bit C++ int.  VLC
# uses a signed 64-bit millisecond time, but some Matroska demuxers surface an
# unknown timestamp as an unsigned -1 (or another corrupt, enormous value).
# Never let such a value cross the Python/Qt boundary: shiboken raises an
# OverflowError and QML retains its previous (often end-of-file) seek state.
_QT_INT_MAX = 2_147_483_647

# libVLC's public time and position values are samples from the demuxer, not a
# continuously advancing presentation clock. Some files update them sparsely;
# malformed files can leave one value at zero or -1 until the first seek. The
# UI clock therefore advances between trustworthy samples. A fresh sample may
# lead the current UI value by the time since the previous poll plus this small
# allowance; anything farther away is treated as a broken/stale sample rather
# than making every clock and seek bar jump.
_TIMELINE_SAMPLE_SLOP_MS = 2_000


def _qt_milliseconds(value) -> int | None:
    """Return a Qt-safe non-negative millisecond value, or ``None``.

    ``None`` is deliberately distinct from zero: zero is a valid playback
    timestamp, whereas an unknown VLC timestamp must leave the last trustworthy
    value untouched.
    """
    try:
        milliseconds = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if 0 <= milliseconds <= _QT_INT_MAX:
        return milliseconds
    return None


def _enum_int(value, default: int = 0) -> int:
    """Read a libVLC enum as a plain ``int``.

    **This is load-bearing.** ``python-vlc`` returns ``libvlc_state_t`` as a
    :class:`vlc.State`, which derives from ``ctypes.c_uint`` — *not* from
    ``int``. Calling ``int()`` on it does not unwrap it; ctypes falls back to
    parsing its raw 4-byte buffer as a decimal string and raises::

        ValueError: invalid literal for int() with base 10: b'\\x03\\x00\\x00\\x00'

    The old ``int(self._player.get_state())`` sat inside a bare ``except:
    return`` in the poll, so **every poll tick aborted on its first line**.
    Nothing downstream ever updated: no time, no duration, no position, and
    ``isPlaying`` was permanently ``False`` — which is why the seek bar stayed
    grey, the clocks stayed at zero and Pause did nothing (``toggle()`` saw a
    non-Playing state and called ``play()`` again).

    The value lives in ``.value``; only fall back to ``int()`` for a genuine
    Python int.
    """
    if value is None:
        return default
    inner = getattr(value, "value", None)
    if inner is not None:
        try:
            return int(inner)
        except (TypeError, ValueError):
            return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

#: Base options. ``--avcodec-threads=0`` = use every core, which is what makes
#: software decode viable at 1080p/1440p (§0.5).
BASE_VLC_ARGS = [
    "--no-xlib",
    "--quiet",
    "--intf=dummy",
    "--no-video-title-show",
    "--avcodec-threads=0",
    "--no-snapshot-preview",
    "--no-stats",
    "--no-osd",  # Halcyon draws its own OSD in the scene graph (§6.2)
    # ------------------------------------------------------------------
    # Hardware decoding is INCOMPATIBLE with the vmem video callbacks.
    #
    # With --avcodec-hw=auto (the default) libVLC decodes into GPU surfaces in
    # an opaque, driver-specific tiled layout. vmem then has to read those back
    # into our buffers; when the copy is not supported for the negotiated
    # chroma the planes arrive partially written or not at all, which is
    # exactly the "no video / green garbage" symptom on 10-bit HEVC .mkv files.
    # Upstream's position is explicit: "If you want hardware acceleration, do
    # not use the video callbacks."
    #
    # ``libvlc_video_set_callbacks()`` already does ``var_SetString(mp,
    # "avcodec-hw", "none")`` on the *player* object, so in the normal flow
    # this is belt-and-braces. It is kept deliberately because that inheritance
    # only applies to objects created after the call: setting it on the
    # instance makes the guarantee independent of whether anything ever calls
    # attach() late, and it also covers the short-lived probe instances in
    # modes/local/playlist.py. Explicit beats implicit for a setting whose
    # failure mode is a green picture.
    "--avcodec-hw=none",
]


def _resolve_bundled_vlc() -> Path | None:
    """Point ctypes at ``vendor/vlc`` if it is populated.

    Must happen *before* ``import vlc``. In a frozen build the same directory
    sits next to the executable (§9, the Nuitka row).
    """
    candidates = [paths.VENDOR_VLC]
    if getattr(sys, "frozen", False):
        candidates.insert(0, Path(sys.executable).parent / "vlc")
    for base in candidates:
        if not base.is_dir():
            continue
        lib = base / ("libvlc.dll" if sys.platform == "win32" else "libvlc.so")
        if not lib.exists() and sys.platform != "win32":
            lib = next(iter(base.glob("libvlc.so*")), None)
        if lib and lib.exists():
            plugins = base / "plugins"
            if plugins.is_dir():
                os.environ["VLC_PLUGIN_PATH"] = str(plugins)
            if sys.platform == "win32":
                # Do not discard this handle: discarding it immediately removes
                # ``base`` from the DLL search path, which can make libvlc.dll
                # load while libvlccore.dll or a codec plugin fails later.
                try:
                    _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(base)))
                except (AttributeError, OSError):
                    # Older Python/Windows combinations may not expose the API;
                    # python-vlc can still use the explicit library path below.
                    log.debug("could not register VLC DLL directory", exc_info=True)
                os.environ["PYTHON_VLC_LIB_PATH"] = str(lib)
            else:
                os.environ["PYTHON_VLC_LIB_PATH"] = str(lib)
            log.info("using bundled libVLC at %s", base)
            return base
    log.info("vendor/vlc not populated — falling back to system libVLC")
    return None


class VlcEngine(QObject):
    """The player. One instance, shared by every mode that plays media."""

    stateChanged = Signal(int)
    positionChanged = Signal(float)     # 0.0 - 1.0
    timeChanged = Signal(int)           # ms
    durationChanged = Signal(int)       # ms
    volumeChanged = Signal(int)
    mutedChanged = Signal(bool)
    rateChanged = Signal(float)
    mediaChanged = Signal(str)          # mrl
    endReached = Signal()
    errorOccurred = Signal(str)
    buffering = Signal(float)           # 0 - 100
    #: Fraction (0..1) of the current media buffered, for the seek bar's
    #: buffer fill. Kept as a Q_PROPERTY too: MiniBar binds ``player.buffered``
    #: and an undefined property is a dead QML binding (§M.4).
    bufferedChanged = Signal(float)
    tracksChanged = Signal()
    #: The effective video route actually in force — "soft" or "turbo" (§V.2).
    #: Emitted after every successful switch *and* after a Turbo failure has
    #: fallen back, so the UI never has to guess which route it is looking at.
    videoRouteChanged = Signal(str)
    #: Decoded width × height of video track 0. Turbo's WindowContainer
    #: sizes itself to this so the letterbox is QML black, not a hole.
    videoSizeChanged = Signal()

    # Class-level defaults for the video-route state. ``__init__`` gives every
    # real engine its own values; these exist because the teardown tests build
    # an engine with ``VlcEngine.__new__`` to exercise ``open()``/``stop()``
    # without libVLC, and a route that only exists after ``__init__`` would
    # turn those into AttributeErrors. Immutable defaults on purpose — nothing
    # can mutate shared class state by accident.
    _video_route = video_policy.SOFT
    _turbo_surface = None
    _media_options: tuple = ()
    _buffered = 0.0
    _user_paused = False
    _pending_turbo_play = False
    _video_width = 0
    _video_height = 0
    # Defaults keep the timeline helpers safe in focused tests that construct
    # VlcEngine with __new__ instead of starting a native libVLC instance.
    _timeline_tick = None
    _last_vlc_time = None
    _last_vlc_position = None

    def __init__(self, backend: str = "auto", parent: QObject | None = None) -> None:
        super().__init__(parent)
        _resolve_bundled_vlc()
        import vlc  # noqa: PLC0415 - deliberately after the path fix-up

        self._vlc = vlc
        self._instance = vlc.Instance(BASE_VLC_ARGS)
        if self._instance is None:
            raise RuntimeError(
                "libVLC failed to initialise — check vendor/vlc/ (see README)"
            )
        self._player = self._instance.media_player_new()
        self._media = None

        chroma = Chroma.RV32 if backend == "rv32" else Chroma.I420
        self.video_output = VideoOutput(chroma)
        self.video_output.attach(self._player)

        # --- Local video modes (§V) ---------------------------------------
        # Soft is the route the player boots on and the route it returns to on
        # any Turbo problem. `turbo_surface` is created lazily by
        # set_video_route() so a session that never asks for Turbo never
        # imports QtGui here.
        self._video_route = video_policy.SOFT
        self._turbo_surface = None
        #: Per-playback libVLC options (":avcodec-hw=d3d11va" for Turbo).
        #: Applied to each media in open(); empty on the Soft path.
        self._media_options: list[str] = []

        self._state = State.Idle
        self._duration = 0
        self._position = 0.0
        self._time = 0
        self._buffered = 0.0
        # Wall-clock anchor used only to keep the *displayed* timeline moving
        # between libVLC samples. It never drives decoding or A/V sync.
        self._timeline_tick = time.monotonic()
        self._last_vlc_time: int | None = None
        self._last_vlc_position: float | None = None
        self._volume = 80
        self._muted = False
        self._rate = 1.0
        self._current_mrl = ""
        self._releasing = False
        self._scrubbing = False
        #: Set by open() when the media should start somewhere other than 0;
        #: consumed by the poll on the first Playing tick. Zero means "nothing
        #: pending", which is also what cancelling one leaves behind.
        self._pending_resume_ms = 0
        #: True only after an explicit user pause, not Opening/Buffering.
        self._user_paused = False
        #: Play again once WindowContainer has adopted the Turbo HWND.
        self._pending_turbo_play = False
        self._video_width = 0
        self._video_height = 0

        # Hard references — see the module docstring. Never let these be locals.
        self._event_callbacks: list = []
        self._attach_events()

        # libVLC's position events are irregular; a steady 200 ms poll keeps the
        # seek bar smooth without hammering the UI thread.
        self._poll = QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self._poll_state)
        self._poll.start()

        self.set_volume(self._volume)

    # -------------------------------------------------------------- events ---
    def _attach_events(self) -> None:
        vlc = self._vlc
        em = self._player.event_manager()
        self._event_manager = em
        self._event_wiring: list = []
        wiring = [
            (vlc.EventType.MediaPlayerEndReached, self._on_end_reached),
            (vlc.EventType.MediaPlayerEncounteredError, self._on_error),
            (vlc.EventType.MediaPlayerPlaying, self._on_state_event),
            (vlc.EventType.MediaPlayerPaused, self._on_state_event),
            (vlc.EventType.MediaPlayerStopped, self._on_state_event),
            (vlc.EventType.MediaPlayerOpening, self._on_state_event),
            (vlc.EventType.MediaPlayerBuffering, self._on_buffering),
            (vlc.EventType.MediaPlayerLengthChanged, self._on_length),
            (vlc.EventType.MediaPlayerESAdded, self._on_tracks),
            (vlc.EventType.MediaPlayerESDeleted, self._on_tracks),
        ]
        for event_type, handler in wiring:
            em.event_attach(event_type, handler)
            self._event_callbacks.append(handler)
            self._event_wiring.append((event_type, handler))

    def _detach_events(self) -> None:
        """Unhook every VLC event before the player is released.

        Leaving them attached is what produced ``QObject::disconnect:
        Unexpected nullptr parameter`` on exit: VLC could still fire into a
        Python callback whose Qt receiver was already being torn down.
        """
        em = getattr(self, "_event_manager", None)
        if em is None:
            return
        for event_type, _handler in getattr(self, "_event_wiring", []):
            try:
                # python-vlc's EventManager.event_detach takes ONLY the event
                # type — it drops every callback registered under it on that
                # manager. Passing the handler as a second argument raises
                # TypeError, which this except swallowed at DEBUG, so all ten
                # callbacks stayed live right through player teardown: the
                # exit-time QObject::disconnect warning this method exists to
                # prevent. One handler per type is attached, so dropping by
                # type detaches exactly what _attach_events registered.
                em.event_detach(event_type)
            except Exception:
                log.debug("event_detach failed for %s", event_type, exc_info=True)
        self._event_wiring = []
        self._event_manager = None

    # Every one of these runs on a *VLC* thread. Emit and get out — Qt queues the
    # delivery to the GUI thread for us.
    def _on_end_reached(self, _event) -> None:
        self.endReached.emit()

    def _on_error(self, _event) -> None:
        self.errorOccurred.emit(f"Could not play {self._current_mrl or 'media'}")

    def _on_state_event(self, _event) -> None:
        pass  # the poll timer publishes state on the GUI thread

    def _on_buffering(self, event) -> None:
        try:
            new_cache = float(event.u.new_cache)
        except Exception:
            return
        # libVLC reports the cache as a percentage (0..100). Both consumers
        # want a fraction: M3U's hairline (via `buffering`) and the seek
        # bars' buffer fill (via `buffered`), which multiply it by a width.
        buffered = max(0.0, min(1.0, new_cache / 100.0))
        if abs(buffered - self._buffered) > 1e-4:
            self._buffered = buffered
            self.bufferedChanged.emit(buffered)
        self.buffering.emit(new_cache)

    def _on_length(self, _event) -> None:
        pass  # picked up by the poll

    def _on_tracks(self, _event) -> None:
        self.tracksChanged.emit()

    # ---------------------------------------------------------------- poll ---
    def _plausible_timeline_sample(
        self, candidate_ms: int, expected_advance_ms: float, state: State
    ) -> int | None:
        """Validate one libVLC timeline sample against the displayed clock.

        During ordinary playback the timeline is monotonic. User seeks already
        update ``self._time`` before the next poll, so a stale pre-seek sample
        is either behind that value or implausibly far ahead and is rejected.
        This is also what keeps a malformed ``get_position() == 1.0`` from
        throwing a newly opened file straight to its end.
        """
        candidate = max(0, int(candidate_ms))
        if self._duration > 0:
            candidate = min(candidate, self._duration)
        if state != State.Playing:
            return candidate
        if candidate <= self._time:
            # A stale/equal sample must not both move the clock backwards *or*
            # consume this poll tick. Returning None lets the monotonic fallback
            # advance normally; explicit backward seeks have already moved
            # _time before polling resumes.
            return None
        allowed_lead = max(0.0, expected_advance_ms) + _TIMELINE_SAMPLE_SLOP_MS
        if candidate - self._time > allowed_lead:
            return None
        return candidate

    def _poll_state(self) -> None:
        """Publish engine state and a resilient UI timeline, 5x a second.

        libVLC's time/position properties are demuxer samples. Their update
        frequency is not guaranteed, and a damaged timestamp can leave one at
        zero or -1 until a seek. We still prefer every sane libVLC sample, then
        its separately reported position sample, and finally advance the *displayed*
        clock from ``time.monotonic`` while the player says it is Playing.
        Decoding and A/V sync remain entirely owned by libVLC.

        Every backend reading is fetched independently, so one unlucky call can
        never prevent state, duration, timeline, or video-size updates.
        """
        if self._releasing or self._player is None:
            return

        player = self._player
        previous_state = self._state

        try:
            state = _VLC_STATE_MAP.get(_enum_int(player.get_state()), State.Idle)
        except Exception:
            state = self._state
        if state != self._state:
            self._state = state
            self.stateChanged.emit(int(state))

        now = time.monotonic()
        last_tick = getattr(self, "_timeline_tick", None)
        self._timeline_tick = now
        elapsed_ms = max(0.0, (now - last_tick) * 1000.0) if last_tick is not None else 0.0
        # Do not charge Opening/Buffering/Paused time to playback merely because
        # the transition to Playing happened between two 200 ms poll ticks.
        expected_advance_ms = (
            elapsed_ms * max(0.0, float(self._rate))
            if state == State.Playing and previous_state == State.Playing
            else 0.0
        )

        # Apply a queued resume as soon as the media is genuinely playing.
        # Cleared before the seek, not after: if seek() raises we must not
        # retry on every one of the next five ticks a second.
        if self._pending_resume_ms and state == State.Playing:
            resume_ms = self._pending_resume_ms
            self._pending_resume_ms = 0
            log.debug("applying resume seek to %d ms", resume_ms)
            self.seek(resume_ms)
            # seek() anchors the clock at the instant of the request.
            expected_advance_ms = 0.0

        try:
            duration = _qt_milliseconds(player.get_length())
        except Exception:
            duration = None
        # -1 means that VLC has not discovered the length yet. Do not turn an
        # unsigned sentinel into a huge duration or emit it through Signal(int).
        if duration is not None and duration != self._duration:
            self._duration = duration
            self.durationChanged.emit(duration)

        # While the user is dragging the seek bar the UI is authoritative:
        # publishing VLC's pre-seek time here would yank the knob backwards
        # between the drag and the seek landing. The monotonic anchor above is
        # still refreshed, so releasing a long drag never creates a time jump.
        if not self._scrubbing:
            try:
                raw_time = _qt_milliseconds(player.get_time())
            except Exception:
                raw_time = None
            previous_raw_time = getattr(self, "_last_vlc_time", None)
            raw_time_changed = raw_time is not None and raw_time != previous_raw_time
            if raw_time is not None:
                self._last_vlc_time = raw_time

            # Position is a fallback, never an unchecked source of truth. It is
            # particularly valuable when get_time() is -1 or stuck, but old MKV
            # demuxers can report a false 1.0 for malformed timestamps.
            raw_position = None
            getter = getattr(player, "get_position", None)
            if callable(getter):
                try:
                    value = float(getter())
                    if math.isfinite(value) and 0.0 <= value <= 1.0:
                        raw_position = value
                except (TypeError, ValueError, OverflowError):
                    pass
                except Exception:
                    pass
            previous_raw_position = getattr(self, "_last_vlc_position", None)
            raw_position_changed = (
                raw_position is not None
                and (
                    previous_raw_position is None
                    or abs(raw_position - previous_raw_position) > 1e-7
                )
            )
            if raw_position is not None:
                self._last_vlc_position = raw_position

            candidate = None
            if raw_time_changed:
                candidate = self._plausible_timeline_sample(
                    raw_time, expected_advance_ms, state
                )

            if candidate is None and raw_position_changed and self._duration > 0:
                # A lone 100% sample near the beginning is the known malformed
                # MKV failure. A genuinely ending file has already brought the
                # effective clock close to its duration, or reached Ended.
                false_end = (
                    raw_position >= 0.999
                    and state != State.Ended
                    and self._time < int(self._duration * 0.95)
                )
                if not false_end:
                    position_time = int(round(raw_position * self._duration))
                    candidate = self._plausible_timeline_sample(
                        position_time, expected_advance_ms, state
                    )

            if candidate is None and state == State.Playing:
                # Last resort for sparse, frozen, or invalid backend samples.
                # This changes presentation only; no seek or decoder operation
                # is performed, so ordinary playback cannot be disturbed.
                candidate = self._time + int(round(expected_advance_ms))
                if self._duration > 0:
                    candidate = min(candidate, self._duration)

            if candidate is not None and candidate != self._time:
                self._time = candidate
                self.timeChanged.emit(candidate)

            # Publish one coherent timeline. Remaining time in QML is duration
            # minus this value, so elapsed, remaining, and the seek knob can no
            # longer disagree when one libVLC property is temporarily bad.
            position = self._time / self._duration if self._duration > 0 else 0.0
            position = max(0.0, min(1.0, position))
            if abs(position - self._position) > 1e-5:
                self._position = position
                self.positionChanged.emit(position)

        self._refresh_video_size()

    # ------------------------------------------------------------ playback ---
    @Slot(str)
    def open(self, path_or_url: str, start_ms: int = 0, announce: bool = True) -> None:
        """Load media and start playing. Accepts a path, a file:// URL or a
        network URL (Phase 2's HLS streams come through here unchanged).

        ``announce`` is an internal flag, always true for every real caller.
        :meth:`set_video_route` re-opens the *same* media on the other video
        route and passes ``False`` so the switch does not masquerade as a new
        media: no Now Playing toast, no metadata reload, no recent-files entry
        for something that never stopped playing (§V.4).

        **Self-safe transition.** This is the one place a new media is handed
        to libVLC, so it is the one place that has to guarantee the previous
        media is fully detached before the new one is set. Every caller —
        ``AppController.openPath`` for local Next/Previous and end-of-track,
        ``M3UContext._open_url`` for stream-switching, the remote bridge,
        ``startOver`` for resume overrides — funnels through here, and not
        one of them reliably calls ``stop()`` first when the user changes
        track while a previous file is still playing. Without the teardown
        below, ``self._media.release()`` on the still-playing media races
        the decoder thread and terminates the process inside ``libvlc.dll``
        with no Python traceback (the asymmetric Video 1 → Next → crash,
        Video 2 → Previous → fine symptom). ``stop()`` is the libVLC-safe
        order: stop the player, ``set_media(None)`` so libVLC releases its
        internal reference, then drop our Python-side refcount.
        """
        if not path_or_url:
            return

        # ------------------------------------------------------------------
        # 1. Tear the previous media down in the libVLC-safe order.  Done
        # unconditionally: a fresh player has nothing to release, the call
        # short-circuits on ``self._media is None`` and ``self._current_mrl``
        # is empty, so the no-op case costs essentially nothing.
        # ------------------------------------------------------------------
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                log.debug("player.stop failed during open() teardown", exc_info=True)
            try:
                self._player.set_media(None)
            except Exception:
                log.debug("set_media(None) failed during open() teardown", exc_info=True)
        if self._media is not None:
            try:
                self._media.release()
            except Exception:
                log.debug("media.release failed during open() teardown", exc_info=True)
            self._media = None
        self._current_mrl = ""
        self._scrubbing = False
        self._pending_resume_ms = 0
        self._reset_timeline()

        # Retire whatever the previous media left on the video surface
        # *before* the new one starts. ``stop()`` already calls
        # ``notify_video_stopped()`` and we just reset the timeline above,
        # so the ring is empty. Calling it again here is harmless and keeps
        # the invariant visible at the call site: a new media always starts
        # against a clean video surface. (libVLC only fires its own video
        # cleanup callback when it genuinely tears a vout down, and going
        # from a video file straight to an audio file inside the same
        # player does not reliably produce one before the audio starts. The
        # explicit retire removes the race and is what kept
        # ``VideoSurface.hasVideo`` from latching true after a video ended.)
        try:
            self.video_output.notify_video_stopped()
        except Exception:
            log.debug("could not reset the video surface for new media", exc_info=True)

        # ------------------------------------------------------------------
        # 2. Set up the new media.  The python-vlc contract for
        # ``set_media`` is: "Afterwards the p_md can be safely destroyed."
        # The player holds its own reference, so the local handle is only
        # needed until the call returns; the old code kept a strong
        # reference on ``self._media`` for the lifetime of the play, which
        # is a slow leak across many Next clicks.  We now release
        # immediately and rely on the player to keep the media alive.
        # ------------------------------------------------------------------
        mrl = path_or_url
        if not _looks_like_url(mrl):
            mrl = Path(mrl).expanduser().resolve().as_uri()

        media = self._instance.media_new(mrl)
        if media is None:
            self.errorOccurred.emit(f"Could not open {path_or_url}")
            return
        # Per-playback options (§V.2): Turbo carries ":avcodec-hw=d3d11va" so
        # hardware decode applies to this media only, leaving the instance-wide
        # "none" that protects the Soft vmem path untouched. Never fatal — a
        # build that rejects the option still plays, just without HW decode.
        for option in self._media_options:
            try:
                media.add_option(option)
            except Exception:
                log.debug("media option %s rejected", option, exc_info=True)
        try:
            media.parse_with_options(self._vlc.MediaParseFlag.local, 3000)
        except Exception:
            log.debug("media.parse_with_options failed for %s", path_or_url, exc_info=True)
        if self._player is None:
            # shutdown() ran between our teardown and now; nothing to do.
            try:
                media.release()
            except Exception:
                pass
            try:
                self.errorOccurred.emit(f"Could not open {path_or_url}")
            except Exception:
                pass
            return
        try:
            self._player.set_media(media)
        except Exception:
            log.exception("set_media failed for %s", path_or_url)
            try:
                media.release()
            except Exception:
                pass
            self.errorOccurred.emit(f"Could not open {path_or_url}")
            return
        # Player now owns the media.  Drop our local refcount so we do not
        # leak it.  The previous-file teardown already cleared
        # ``self._media``, so we deliberately do NOT store the new media
        # there: ``self._media`` is now reserved for the "I need to call
        # release() myself" path (shutdown) and is not a duplicate ref.
        try:
            media.release()
        except Exception:
            log.debug("media.release after set_media failed for %s", path_or_url, exc_info=True)
        self._current_mrl = mrl
        if announce:
            # A new file: drop the previous picture size so Turbo does not
            # keep the old aspect for a frame. A silent route-switch reopen
            # (announce=False) keeps the size — same media, same picture.
            self._set_video_size(0, 0)
            self.mediaChanged.emit(mrl)
        self._player.play()

        # Resume is applied on the first Playing tick, not on a fixed delay.
        # A 300 ms singleShot is a race: a file that is still opening silently
        # drops the seek (VLC ignores set_time before playback starts), so the
        # UI announced "Resuming from 24:31" while playback sat at zero. The
        # poll already runs 5x a second and already knows when the state turns
        # Playing — hanging the seek off that makes it deterministic on a cold
        # cache and on a slow disk alike.
        self._pending_resume_ms = int(start_ms) if start_ms > 0 else 0

    @Slot()
    def play(self) -> None:
        # ``self._media`` is no longer the "is a media loaded" indicator:
        # ``open()`` releases its local handle as soon as the player takes
        # ownership (the python-vlc contract), so ``self._media`` is always
        # None mid-play. Use ``self._current_mrl`` instead.
        if self._player is None or not self._current_mrl:
            return
        self._user_paused = False
        self._player.play()
        self._publish_state_now()

    @Slot()
    def pause(self) -> None:
        """Pause, and reflect it immediately.

        ``can_pause()`` returns a ctypes bool that is falsy for some codecs
        even when pausing works, so a failed check must not silently swallow
        the request — we try to pause regardless and only guard the call.
        """
        if self._player is None:
            return
        self._user_paused = True
        try:
            self._player.set_pause(1)
        except Exception:
            log.exception("pause failed")
        self._publish_state_now()

    @Slot()
    def toggle(self) -> None:
        """Single implementation of play/pause — §4.1. Space, the transport
        button, the stage click and the OSD all route here.

        Reads the state straight from libVLC rather than trusting the cached
        ``self._state``: the cache is refreshed by a 200 ms poll, so a click
        arriving between ticks used to be judged against a stale value.
        """
        if self._player is None or not self._current_mrl:
            return
        try:
            live = _VLC_STATE_MAP.get(_enum_int(self._player.get_state()), self._state)
        except Exception:
            live = self._state
        if live == State.Playing:
            self.pause()
        else:
            self.play()

    def _reset_timeline(self) -> None:
        """Clear published timeline values without relying on VLC callbacks."""
        self._timeline_tick = time.monotonic()
        self._last_vlc_time = None
        self._last_vlc_position = None
        if self._time != 0:
            self._time = 0
            self.timeChanged.emit(0)
        if self._position != 0.0:
            self._position = 0.0
            self.positionChanged.emit(0.0)
        if self._duration != 0:
            self._duration = 0
            self.durationChanged.emit(0)
        if self._buffered != 0.0:
            self._buffered = 0.0
            self.bufferedChanged.emit(0.0)

    @Slot()
    def stop(self) -> None:
        """Stop playback and zero the clocks.

        libVLC stops reporting time once stopped, so the poll would leave the
        last-known time and position on screen forever. Reset them here and
        notify, so the seek bar empties and the clocks read 0:00.
        """
        if self._player is None:
            return
        try:
            self._player.stop()
            self._player.set_media(None)
        except Exception:
            log.exception("stop failed")
        if self._media is not None:
            try:
                self._media.release()
            except Exception:
                pass
            self._media = None
        self._scrubbing = False
        self._pending_resume_ms = 0   # nothing to resume into any more
        self._pending_turbo_play = False
        self._user_paused = False
        self._current_mrl = ""
        self._set_video_size(0, 0)
        # One-tuner rule (§V.4): a full stop — including the one
        # AppController performs when switching to a mode that does not use
        # the player — must not leave a native Turbo child alive. The next
        # media re-resolves its own route from scratch.
        if self._video_route == video_policy.TURBO:
            self._release_turbo_surface()
            self._restore_soft_output()
            self.videoRouteChanged.emit(self._video_route)
        try:
            self.video_output.notify_video_stopped()
        except Exception:
            log.debug("could not reset the video surface on stop", exc_info=True)
        self._reset_timeline()
        self._publish_state_now()

    # ------------------------------------------------------- video route ---
    #
    # Soft and Turbo are two ways of getting the *same* player's pictures onto
    # the screen, not two players (§V.2). Soft keeps libVLC writing into the
    # vmem callbacks (engine/video_out.py) that the QML scene graph samples;
    # Turbo takes those callbacks off and gives libVLC a native child window
    # instead, so a hardware decoder can keep the frame on the GPU.
    #
    # libVLC decides which output a media uses when the media starts, so a
    # live switch means re-opening the current MRL at the current position.
    # That is what makes "continue the same media without stopping playback"
    # (§V.4) achievable at all — and why the failure path below re-opens on
    # Soft rather than leaving the user with a dead picture.

    @Property(str, notify=videoRouteChanged)
    def videoRoute(self) -> str:  # noqa: N802 - QML-facing
        """"soft" or "turbo" — what the player is actually doing right now."""
        return self._video_route

    @property
    def turbo_window(self):
        """The native child ``QWindow`` for QML's ``WindowContainer``, or None.

        Read by the shell through :class:`core.app.AppController`; QML never
        touches the engine's private surface object.
        """
        surface = self._turbo_surface
        return surface.window if surface is not None else None

    def turbo_available(self) -> bool:
        """Can Turbo even be attempted on this build/platform (§V.3)?"""
        from engine.turbo_surface import is_supported  # local: QtGui-free import

        return bool(is_supported())

    @Slot(str, result=str)
    def set_video_route(self, route: str) -> str:
        """Put the player on ``route`` ("soft" or "turbo"). Returns what it got.

        The return value is the honest answer, not the request: a Turbo attempt
        that fails anywhere — unsupported platform, no native handle, set_hwnd
        refused, the re-open raised — cleans up whatever it created and returns
        ``"soft"`` with the same media still playing from the same position.
        """
        wanted = video_policy.SOFT if route != video_policy.TURBO else video_policy.TURBO
        if self._player is None:
            return self._video_route
        if wanted == self._video_route:
            return self._video_route

        if wanted == video_policy.TURBO:
            if not self._enter_turbo():
                # _enter_turbo already restored Soft and re-opened the media.
                return self._video_route
        else:
            self._leave_turbo()

        self.videoRouteChanged.emit(self._video_route)
        return self._video_route

    def _enter_turbo(self) -> bool:
        """Soft -> Turbo. Any failure ends with the player back on Soft."""
        from engine.turbo_surface import TurboSurface

        if not self.turbo_available():
            # Nothing to attempt: no platform support means no native child,
            # and the answer would be Soft anyway. Bail out *before* stopping
            # the player, so an impossible request costs the user nothing —
            # not even the re-open a real failure would have to pay for.
            log.info("Turbo is not available on this platform — staying on Soft")
            return False

        resume_ms, was_paused = self._capture_playback()
        surface = TurboSurface(parent=self)
        try:
            # Order matters. Detach the vmem callbacks *before* handing libVLC
            # a window: leaving both installed is the documented recipe for a
            # green/blank picture (see BASE_VLC_ARGS), and video_out.detach()
            # is only safe once the player is stopped, which it is here.
            self._player.stop()
            self.video_output.detach()
            self.video_output.notify_video_stopped()
            if not surface.start(self._player):
                raise RuntimeError("native Turbo surface unavailable")
            # Hardware decode is what Turbo is for; the instance-wide
            # --avcodec-hw=none exists for the vmem path, so override it on
            # this player only.
            self._set_player_option("avcodec-hw", "d3d11va")
            self._turbo_surface = surface
            self._video_route = video_policy.TURBO
            self._reopen_current(resume_ms, was_paused)
            if not was_paused:
                self._pending_turbo_play = True
                QTimer.singleShot(80, self, self._turbo_play_if_pending)
        except Exception:
            log.warning("Turbo could not be started — falling back to Soft", exc_info=True)
            self._pending_turbo_play = False
            try:
                surface.stop(self._player)
            except Exception:
                log.debug("Turbo cleanup after a failed start also failed", exc_info=True)
            self._turbo_surface = None
            self._video_route = video_policy.SOFT
            self._restore_soft_output()
            self._reopen_current(resume_ms, was_paused)
            self.videoRouteChanged.emit(self._video_route)
            return False
        return True

    def _leave_turbo(self) -> None:
        """Turbo -> Soft. Always succeeds: Soft is the resting state."""
        self._pending_turbo_play = False
        resume_ms, was_paused = self._capture_playback()
        try:
            self._player.stop()
        except Exception:
            log.debug("stop before leaving Turbo failed", exc_info=True)
        surface = self._turbo_surface
        self._turbo_surface = None
        if surface is not None:
            try:
                surface.stop(self._player)
            except Exception:
                log.debug("tearing down the Turbo surface failed", exc_info=True)
        self._video_route = video_policy.SOFT
        self._restore_soft_output()
        self._reopen_current(resume_ms, was_paused)

    def note_turbo_embedded(self) -> None:
        """WindowContainer adopted the child. Seal the hole and start play."""
        if self._video_route != video_policy.TURBO:
            return
        surface = self._turbo_surface
        if surface is not None:
            try:
                surface.reharden_now()
            except Exception:
                log.debug("Turbo reharden after embed failed", exc_info=True)
        self._turbo_play_if_pending()

    def _turbo_play_if_pending(self) -> None:
        if not self._pending_turbo_play:
            return
        if self._video_route != video_policy.TURBO:
            self._pending_turbo_play = False
            return
        if self._user_paused or self._state == State.Paused:
            self._pending_turbo_play = False
            return
        self._pending_turbo_play = False
        try:
            self.play()
        except Exception:
            log.debug("Turbo play-after-embed failed", exc_info=True)

    def turbo_failed(self, reason: str = "") -> None:
        """Called when Turbo broke *after* setup — embedding, resize, playback.

        §V.4: the user must not lose playback because Turbo could not be made
        to work. This is the one entry point for every late failure (the QML
        ``WindowContainer`` reporting it could not adopt the child, a native
        playback error), and it does exactly what a failed start does.
        """
        if self._video_route != video_policy.TURBO:
            return
        log.warning("Turbo failed after setup (%s) — falling back to Soft", reason or "?")
        self._leave_turbo()
        self.videoRouteChanged.emit(self._video_route)

    def _restore_soft_output(self) -> None:
        """Re-install the vmem callbacks and undo the Turbo player options."""
        try:
            self._set_player_option("avcodec-hw", "none")
        except Exception:
            log.debug("could not restore avcodec-hw=none", exc_info=True)
        try:
            self.video_output.attach(self._player)
        except Exception:
            log.exception("could not re-attach the Soft video callbacks")

    def _set_player_option(self, name: str, value: str) -> None:
        """Scope a libVLC option to *this* playback, not the whole instance.

        The instance-wide ``--avcodec-hw=none`` (see :data:`BASE_VLC_ARGS`) has
        to keep protecting the Soft vmem path and the short-lived probe
        instances, so Turbo cannot simply change it globally. libVLC's supported
        per-playback override is a media option (``:avcodec-hw=d3d11va``), which
        applies to the media object the player is given — and a new media object
        is created on every :meth:`open`, including the silent re-open that
        performs the switch. Recording it here is therefore enough; ``open()``
        applies it.
        """
        option = f":{name}={value}"
        prefix = f":{name}="
        self._media_options = [
            existing for existing in self._media_options if not existing.startswith(prefix)
        ]
        # "none" is the instance default; re-stating it as a media option is
        # harmless but noisy, so Soft simply carries no override at all.
        if not (name == "avcodec-hw" and value == "none"):
            self._media_options.append(option)

    def _capture_playback(self) -> tuple[int, bool]:
        """Where we are, and whether the user had paused (not merely Opening)."""
        position_ms = 0
        try:
            value = _qt_milliseconds(self._player.get_time())
            position_ms = int(value or 0)
        except Exception:
            position_ms = int(self._time or 0)
        if position_ms <= 0:
            position_ms = int(self._pending_resume_ms or 0)
        was_paused = bool(getattr(self, "_user_paused", False) or self._state == State.Paused)
        return position_ms, was_paused

    def _reopen_current(self, resume_ms: int, was_paused: bool) -> None:
        """Re-open the current MRL on the current route, at ``resume_ms``.

        Silent by design (``announce=False``): to everything above the engine
        this is the same media that never stopped, which is exactly what §V.4
        promises. Nothing to re-open (audio-only, stopped player) is a no-op.

        Only an explicit user pause is restored. Opening / Buffering still
        means the user wanted play.
        """
        mrl = self._current_mrl
        if not mrl:
            return
        self.open(mrl, max(0, int(resume_ms)), announce=False)
        if was_paused:
            QTimer.singleShot(0, self.pause)

    def _publish_state_now(self) -> None:
        """Push the current libVLC state out without waiting for the poll.

        Play/pause must feel instant: the button glyph and the auto-hide logic
        both key off ``isPlaying``, and a 200 ms lag there reads as a dropped
        click.
        """
        if self._releasing or self._player is None:
            return
        try:
            state = _VLC_STATE_MAP.get(_enum_int(self._player.get_state()), self._state)
        except Exception:
            return
        if state != self._state:
            self._state = state
            self.stateChanged.emit(int(state))

    @Slot(bool)
    def set_scrubbing(self, active: bool) -> None:
        """Tell the engine the user is dragging the seek bar.

        While true the poll stops publishing time/position, so the knob
        follows the pointer instead of fighting stale readings from VLC.
        """
        self._scrubbing = bool(active)
        if self._scrubbing:
            # The user has taken the timeline: a resume seek arriving mid-drag
            # would yank it out from under them.
            self.cancel_pending_resume()

    @Slot()
    def cancel_pending_resume(self) -> None:
        """Drop a queued resume seek that has not been applied yet.

        Called when the user overrides the resume — Start Over, or any manual
        seek before the media reaches Playing. Without this the queued seek
        lands afterwards and silently undoes what they asked for.
        """
        if self._pending_resume_ms:
            log.debug("cancelled pending resume seek")
        self._pending_resume_ms = 0

    @Slot(int)
    def seek(self, ms: int) -> None:
        """Seek to an absolute time, updating *both* readouts.

        Time and position are two views of one thing. Emitting only one left
        the seek bar and the clock disagreeing until the next poll tick.
        """
        if self._player is None:
            return
        ms = _qt_milliseconds(ms)
        # The slot is public to QML as well as Python callers.  Keep its
        # explicit emissions safe even when VLC has no usable duration yet.
        if ms is None:
            return
        if self._duration > 0:
            ms = min(ms, self._duration)
        try:
            self._player.set_time(int(ms))
        except Exception:
            log.exception("seek failed")
            return
        self._time = ms
        self._timeline_tick = time.monotonic()
        self.timeChanged.emit(self._time)
        if self._duration > 0:
            position = max(0.0, min(1.0, ms / self._duration))
            if abs(position - self._position) > 1e-5:
                self._position = position
                self.positionChanged.emit(position)

    @Slot(int)
    def seek_relative(self, delta_ms: int) -> None:
        self.seek(self._time + int(delta_ms))

    @Slot(float)
    def set_position(self, fraction: float) -> None:
        if self._player is None:
            return
        fraction = max(0.0, min(1.0, float(fraction)))
        try:
            self._player.set_position(fraction)
        except Exception:
            log.exception("set_position failed")
            return
        self._position = fraction
        self.positionChanged.emit(fraction)
        if self._duration > 0:
            time_ms = int(fraction * self._duration)
            if time_ms != self._time:
                self._time = time_ms
                self.timeChanged.emit(time_ms)

    # -------------------------------------------------------------- audio ---
    @Slot(int)
    def set_volume(self, volume: int) -> None:
        volume = max(0, min(200, int(volume)))
        self._player.audio_set_volume(volume)
        if volume != self._volume:
            self._volume = volume
            self.volumeChanged.emit(volume)

    @Slot(int)
    def adjust_volume(self, delta: int) -> None:
        self.set_volume(self._volume + int(delta))

    @Slot(bool)
    def set_muted(self, muted: bool) -> None:
        self._player.audio_set_mute(bool(muted))
        if bool(muted) != self._muted:
            self._muted = bool(muted)
            self.mutedChanged.emit(self._muted)

    @Slot()
    def toggle_mute(self) -> None:
        self.set_muted(not self._muted)

    @Slot(float)
    def set_rate(self, rate: float) -> None:
        rate = max(0.25, min(4.0, float(rate)))
        self._player.set_rate(rate)
        if abs(rate - self._rate) > 1e-6:
            self._rate = rate
            self.rateChanged.emit(rate)

    # ------------------------------------------------------------- tracks ---
    def audio_tracks(self) -> list[tuple[int, str]]:
        return _describe_tracks(self._player.audio_get_track_description())

    def video_tracks(self) -> list[tuple[int, str]]:
        """Video tracks of the current media, if any."""
        return _describe_tracks(getattr(self._player, "video_get_track_description", lambda: None)())

    def video_size(self) -> tuple[int, int]:
        """Decoded width × height of video track 0, or ``(0, 0)``.

        ``video_get_size`` only knows the answer once the decoder is up,
        which is later than the container parse. Auto uses this as the
        fallback when metadata has not produced a resolution yet (§V.2).
        """
        player = self._player
        if player is None:
            return (0, 0)
        getter = getattr(player, "video_get_size", None)
        if not callable(getter):
            return (0, 0)
        try:
            size = getter(0)
        except Exception:
            return (0, 0)
        if not size:
            return (0, 0)
        try:
            width, height = int(size[0] or 0), int(size[1] or 0)
        except (TypeError, ValueError, IndexError):
            return (0, 0)
        return (max(0, width), max(0, height))

    def _set_video_size(self, width: int, height: int) -> None:
        width = max(0, int(width or 0))
        height = max(0, int(height or 0))
        if width == self._video_width and height == self._video_height:
            return
        self._video_width = width
        self._video_height = height
        self.videoSizeChanged.emit()

    def _refresh_video_size(self) -> None:
        width, height = self.video_size()
        self._set_video_size(width, height)

    @Property(int, notify=videoSizeChanged)
    def videoWidth(self) -> int:  # noqa: N802 - QML-facing
        """Decoded width of video track 0, or 0 until the decoder knows."""
        return int(self._video_width or 0)

    @Property(int, notify=videoSizeChanged)
    def videoHeight(self) -> int:  # noqa: N802 - QML-facing
        """Decoded height of video track 0, or 0 until the decoder knows."""
        return int(self._video_height or 0)

    def video_fps(self) -> float:
        """Live frame rate from libVLC, or ``0.0`` if not yet known."""
        player = self._player
        if player is None:
            return 0.0
        getter = getattr(player, "get_fps", None)
        if not callable(getter):
            return 0.0
        try:
            rate = float(getter() or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return rate if rate > 0.0 else 0.0

    def subtitle_tracks(self) -> list[tuple[int, str]]:
        return _describe_tracks(self._player.video_get_spu_description())

    def current_audio_track(self) -> int:
        """Id of the audio track VLC actually has selected, as it is now.

        The popover paints its "current" marker from this, so it must be the
        engine's word — a UI-side guess goes stale the first time VLC picks a
        default track on its own (every new media does this)."""
        try:
            return int(self._player.audio_get_track())
        except Exception:
            return -1

    def current_subtitle_track(self) -> int:
        """Id of the spu VLC is showing right now; ``-1`` when disabled."""
        try:
            return int(self._player.video_get_spu())
        except Exception:
            return -1

    @Slot(int)
    def set_audio_track(self, track_id: int) -> None:
        self._player.audio_set_track(int(track_id))

    @Slot(int)
    def set_subtitle_track(self, track_id: int) -> None:
        self._player.video_set_spu(int(track_id))

    @Slot(str, result=bool)
    @Slot(str, bool, result=bool)
    def add_subtitle_file(self, path: str, select: bool = True) -> bool:
        """External subtitle via ``add_slave`` (§P1.5).

        ``select`` is libVLC's add_slave selection flag: True activates the
        track (manual pick/download), False only registers it as an available
        subtitle without showing it — used for the "subtitles start off"
        auto-load at media start.

        Guarded on every step. ``add_slave`` is a no-op unless a media is
        loaded, and handing it a path that does not exist makes libVLC spawn a
        demuxer that fails asynchronously on a VLC thread — which is a far more
        confusing failure than returning False here.
        """
        if self._player is None or self._releasing:
            return False
        if not self._current_mrl:
            log.info("no media loaded — cannot attach subtitle %s", path)
            return False
        try:
            resolved = Path(paths.normalise_path(path)).expanduser()
        except Exception:
            log.warning("unusable subtitle path %r", path)
            return False
        if not resolved.is_file():
            log.warning("subtitle not found on disk: %s", resolved)
            return False
        try:
            rc = self._player.add_slave(
                self._vlc.MediaSlaveType.subtitle, resolved.resolve().as_uri(), select
            )
        except Exception:
            log.exception("add_subtitle_file failed for %s", resolved)
            return False
        if rc != 0:
            log.warning("libVLC rejected subtitle %s (rc=%s)", resolved.name, rc)
            return False
        return True

    @Slot(int)
    def set_subtitle_delay(self, delay_ms: int) -> None:
        self._player.video_set_spu_delay(int(delay_ms) * 1000)  # API is microseconds

    # ------------------------------------------------------- video adjust ---
    @Slot(bool)
    def set_adjust_enabled(self, enabled: bool) -> None:
        self._player.video_set_adjust_int(self._vlc.VideoAdjustOption.Enable, int(enabled))

    @Slot(str, float)
    def set_adjust(self, option: str, value: float) -> None:
        opts = self._vlc.VideoAdjustOption
        mapping = {
            "contrast": opts.Contrast,
            "brightness": opts.Brightness,
            "hue": opts.Hue,
            "saturation": opts.Saturation,
            "gamma": opts.Gamma,
        }
        key = mapping.get(option)
        if key is None:
            return
        if option == "hue":
            self._player.video_set_adjust_int(key, int(value))
        else:
            self._player.video_set_adjust_float(key, float(value))

    # ------------------------------------------------------------ shutdown ---
    @Slot()
    def shutdown(self) -> None:
        """Stop → settle → release, in that order (§9).

        Called from ``aboutToQuit``, never from an event callback.
        """
        if self._releasing:
            return
        self._releasing = True
        self._poll.stop()
        try:
            if self._player is not None:
                # Stop first and wait for VLC's decoder/event threads. Detaching
                # while a stop event is still being dispatched leaves a narrow
                # race where libVLC can call an already-invalid callback; it was
                # also the source of the noisy QObject::disconnect warning seen
                # during application exit.
                self._player.stop()
                deadline = 2000
                waited = 0
                import time

                while waited < deadline:
                    try:
                        if _enum_int(self._player.get_state()) in _SETTLED_STATES:
                            break
                    except Exception:
                        break
                    time.sleep(0.02)
                    waited += 20

                # No VLC event can be in flight now. Remove event and video
                # callback registrations before releasing either object.
                self._detach_events()
                # A Turbo child window must never outlive the player that draws
                # into it (§V.4 — no background Turbo player, no orphan window).
                self._release_turbo_surface()
                self.video_output.detach()
                self._player.release()
                self._player = None
            if self._media is not None:
                self._media.release()
                self._media = None
            if self._instance is not None:
                self._instance.release()
                self._instance = None
        except Exception:
            # Best effort cleanup is still important if a backend reports an
            # error from stop/release. In particular, never leave Python
            # callback trampolines registered against a dying VLC instance.
            log.exception("shutdown was not clean")
            self._detach_events()
            self._release_turbo_surface()
            try:
                self.video_output.detach()
            except Exception:
                log.debug("video callback detach failed", exc_info=True)
        log.info("engine shut down")

    def _release_turbo_surface(self) -> None:
        """Destroy the native child, whatever state it is in. Never raises."""
        surface = self._turbo_surface
        self._turbo_surface = None
        self._video_route = video_policy.SOFT
        self._media_options = []
        if surface is None:
            return
        try:
            surface.stop(self._player)
        except Exception:
            log.debug("Turbo surface teardown failed", exc_info=True)

    # ---------------------------------------------------------- properties ---
    @Property(int, notify=stateChanged)
    def state(self) -> int:
        return int(self._state)

    @Property(bool, notify=stateChanged)
    def isPlaying(self) -> bool:  # noqa: N802 - QML-facing
        return self._state == State.Playing

    @Property(int, notify=durationChanged)
    def duration(self) -> int:
        return self._duration

    @Property(int, notify=timeChanged)
    def time(self) -> int:
        return self._time

    @Property(float, notify=positionChanged)
    def position(self) -> float:
        return self._position

    @Property(float, notify=bufferedChanged)
    def buffered(self) -> float:
        """Fraction (0..1) of the media buffered. 0.0 when not playing."""
        return self._buffered

    @Property(int, notify=volumeChanged)
    def volume(self) -> int:
        return self._volume

    @Property(bool, notify=mutedChanged)
    def muted(self) -> bool:
        return self._muted

    @Property(float, notify=rateChanged)
    def rate(self) -> float:
        return self._rate

    @Property(str, notify=mediaChanged)
    def currentMedia(self) -> str:  # noqa: N802 - QML-facing
        return self._current_mrl

    def set_taskbar_frame_capture_enabled(self, enabled: bool) -> None:
        """Toggle Soft decoded-frame caching for minimized taskbar previews."""
        output = getattr(self, "video_output", None)
        if output is not None:
            output.set_taskbar_frame_capture_enabled(enabled)

    def latest_taskbar_frame(self):
        """Latest independently-owned Soft decoded frame, if this route has one."""
        output = getattr(self, "video_output", None)
        return output.latest_taskbar_frame() if output is not None else None

    @property
    def raw_player(self):
        """Escape hatch for engine-internal helpers (equalizer, metadata).
        Nothing in ``ui/`` or ``modes/`` may touch this."""
        return self._player

    @property
    def raw_instance(self):
        return self._instance


def _looks_like_url(value: str) -> bool:
    url = QUrl(value)
    return url.isValid() and bool(url.scheme()) and len(url.scheme()) > 1


def _describe_tracks(raw) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    if not raw:
        return out
    for track_id, name in raw:
        label = name.decode("utf-8", "replace") if isinstance(name, bytes) else str(name)
        out.append((int(track_id), label))
    return out
