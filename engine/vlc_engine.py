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
import os
import re
import sys
import threading
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
from engine.video_out import Chroma, VideoOutput
from engine.vlc_tracks import media_tracks

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
    tracksChanged = Signal()

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

        self._state = State.Idle
        self._duration = 0
        self._position = 0.0
        self._time = 0
        self._volume = 80
        self._muted = False
        self._rate = 1.0
        self._current_mrl = ""
        self._releasing = False
        self._scrubbing = False
        # Probe media whose parser failed to acknowledge cancellation are kept
        # alive rather than released under a native parser thread. This should
        # stay empty; a bounded parse timeout normally always emits completion.
        self._deferred_probe_media: list = []
        self._deferred_probe_lock = threading.Lock()

        # Hard references — see the module docstring. Never let these be locals.
        self._event_callbacks: list = []
        self._attach_events()

        # External subtitle filenames: maps track IDs to actual filenames.
        # Populated when add_subtitle_file is called, used when describing tracks
        # to show real filenames instead of VLC's generic "Track 1", "Track 2".
        self._external_subtitle_names: dict[int, str] = {}
        self._pending_external_subtitles: list[str] = []
        #: SPU track ids that existed *before* the pending externals were
        #: attached. Anything outside this set is, by construction, a track
        #: add_slave just produced — which is a far stronger signal than
        #: guessing from the label. See ``subtitle_tracks``.
        self._known_spu_ids: set[int] = set()

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
        for event_type, handler in getattr(self, "_event_wiring", []):
            try:
                em.event_detach(event_type, handler)
            except Exception:
                log.debug("event_detach failed for %s", event_type, exc_info=True)
        self._event_wiring = []
        self._event_manager = None

    # Every one of these runs on a *VLC* thread. Emit and get out — Qt queues the
    # delivery to the GUI thread for us.
    def _on_end_reached(self, _event) -> None:
        if getattr(self, "_releasing", False):
            return
        try:
            self.endReached.emit()
        except RuntimeError:
            log.debug("end event arrived after Qt receiver teardown", exc_info=True)

    def _on_error(self, _event) -> None:
        if getattr(self, "_releasing", False):
            return
        try:
            self.errorOccurred.emit(f"Could not play {self._current_mrl or 'media'}")
        except RuntimeError:
            log.debug("error event arrived after Qt receiver teardown", exc_info=True)

    def _on_state_event(self, _event) -> None:
        pass  # the poll timer publishes state on the GUI thread

    def _on_buffering(self, event) -> None:
        if getattr(self, "_releasing", False):
            return
        try:
            self.buffering.emit(float(event.u.new_cache))
        except (AttributeError, TypeError, ValueError, RuntimeError):
            log.debug("could not publish buffering event", exc_info=True)

    def _on_length(self, _event) -> None:
        pass  # picked up by the poll

    def _on_tracks(self, _event) -> None:
        if getattr(self, "_releasing", False):
            return
        try:
            self.tracksChanged.emit()
        except RuntimeError:
            log.debug("track event arrived after Qt receiver teardown", exc_info=True)

    # ---------------------------------------------------------------- poll ---
    def _poll_state(self) -> None:
        """Publish engine state on the GUI thread, 5x a second.

        Every reading is fetched independently. A single ``try`` around the
        whole body meant one unlucky call — and ``get_state()`` was an
        unlucky call on *every* tick, see :func:`_enum_int` — silently killed
        the time, duration and position updates that follow it.
        """
        if self._releasing or self._player is None:
            return

        player = self._player

        try:
            state = _VLC_STATE_MAP.get(_enum_int(player.get_state()), State.Idle)
        except Exception:
            state = self._state
        if state != self._state:
            self._state = state
            self.stateChanged.emit(int(state))

        try:
            duration = _qt_milliseconds(player.get_length())
        except Exception:
            duration = None
        # -1 means that VLC has not discovered the length yet.  Do not turn an
        # unsigned sentinel into a huge duration or emit it through Signal(int).
        if duration is not None and duration != self._duration:
            self._duration = duration
            self.durationChanged.emit(duration)

        # While the user is dragging the seek bar the UI is authoritative:
        # publishing VLC's pre-seek time here would yank the knob backwards
        # between the drag and the seek landing.
        if not self._scrubbing:
            try:
                time_ms = _qt_milliseconds(player.get_time())
            except Exception:
                time_ms = None
            if time_ms is not None and time_ms != self._time:
                self._time = time_ms
                self.timeChanged.emit(time_ms)

            # VLC's native position is derived from the same timestamps, but
            # for malformed MKV timestamps it can be 1.0 while get_time()
            # returns an unsigned error sentinel.  Derive it only from values
            # that passed the Qt range check, keeping the clock and seek knob
            # coherent and preventing a false end-of-file position.
            position = self._time / self._duration if self._duration > 0 else 0.0
            position = max(0.0, min(1.0, position))
            if abs(position - self._position) > 1e-5:
                self._position = position
                self.positionChanged.emit(position)

    # ------------------------------------------------------------ playback ---
    @Slot(str)
    def open(self, path_or_url: str, start_ms: int = 0) -> None:
        """Load media and start playing. Accepts a path, a file:// URL or a
        network URL (Phase 2's HLS streams come through here unchanged)."""
        if not path_or_url:
            return
        mrl = path_or_url
        if not _looks_like_url(mrl):
            mrl = Path(mrl).expanduser().resolve().as_uri()

        # A newly selected item has no trustworthy timeline until its demuxer
        # reports one.  In particular, do not show the previous file's final
        # position during MKV discovery (which made a new video look seeked to
        # its end even while it was visibly playing from the beginning).
        self._scrubbing = False
        self._reset_timeline()

        # Clear external subtitle state from the previous media. Track IDs are
        # per-media, so old mappings would be meaningless — and worse, stale
        # pending names could incorrectly rename tracks in the new media.
        self._external_subtitle_names.clear()
        self._pending_external_subtitles.clear()
        self._known_spu_ids.clear()

        # Retire whatever the previous media left on the video surface *before*
        # the new one starts. libVLC only fires its video cleanup callback when
        # it genuinely tears a vout down, and going from a video file straight
        # to an audio file inside the same player does not reliably produce one
        # before the audio starts. Without this the stage kept showing (and
        # kept `hasVideo` true for) the final frame of the finished video, so
        # the audio-only Now Playing card — album art, title, artist, album —
        # never appeared. A fresh player has no previous frame, which is why
        # the same audio file looked fine when played first.
        try:
            self.video_output.notify_video_stopped()
        except Exception:
            log.debug("could not reset the video surface for new media", exc_info=True)

        if self._media is not None:
            try:
                self._media.release()
            except Exception:
                pass
            self._media = None

        media = self._instance.media_new(mrl)
        if media is None:
            self.errorOccurred.emit(f"Could not open {path_or_url}")
            return
        # Start exactly one parse for this media. Metadata retries only read
        # snapshots; starting another parse on each retry used to overlap
        # several native parser operations with decoder startup.
        parse_flags = self._vlc.MediaParseFlag.local.value
        fetch_local = getattr(self._vlc.MediaParseFlag, "fetch_local", None)
        if fetch_local is not None:
            parse_flags |= fetch_local.value
        try:
            media.parse_with_options(parse_flags, 3000)
        except Exception:
            # Playback does its own stream discovery, so a preparse failure may
            # cost tags/artwork but must never prevent the file from opening.
            log.debug("media preparse could not be started for %s", mrl, exc_info=True)
        self._media = media
        self._player.set_media(media)
        self._current_mrl = mrl
        self.mediaChanged.emit(mrl)
        self._player.play()
        if start_ms > 0:
            QTimer.singleShot(300, lambda: self.seek(start_ms))

    def probe_duration(self, path: str, cancellation=None) -> int:
        """Parse one queued file on the existing libVLC instance.

        Called only by Local's private one-thread probe pool. Keeping instance
        ownership here avoids constructing/releasing a whole native VLC runtime
        for every row while another instance is opening the file for playback.
        The first, auto-played row is not probed at all; its live duration fills
        the model through ``durationChanged``.
        """
        instance = self._instance
        if instance is None or self._releasing or not path:
            return 0

        media = event_manager = callback = None
        parsed = threading.Event()
        parse_event = None
        completed = False
        parse_started = False
        try:
            media = instance.media_new_path(str(Path(path).expanduser().resolve()))
            if media is None:
                return 0
            event_manager = media.event_manager()
            parse_event = self._vlc.EventType.MediaParsedChanged

            def _parsed(_event):
                parsed.set()

            callback = _parsed  # hard reference until detach below
            event_manager.event_attach(parse_event, callback)
            result = media.parse_with_options(self._vlc.MediaParseFlag.local, 1500)
            if result == -1:
                return 0
            parse_started = True
            try:
                completed = _enum_int(media.get_parsed_status()) > 0
            except Exception:
                pass

            # Poll cancellation so playlist shutdown does not need to wait for
            # the full parser timeout merely to discover it was cancelled.
            for _ in range(20):
                if completed or parsed.wait(0.1):
                    completed = True
                    break
                if cancellation is not None and getattr(cancellation, "cancelled", False):
                    break

            if not completed:
                stop_parse = getattr(media, "parse_stop", None)
                if callable(stop_parse):
                    stop_parse()
                # parse_stop promises a ParsedChanged(timeout) event. Do not
                # release until that acknowledgement, because the parser still
                # owns the Media pointer until then.
                completed = parsed.wait(1.0)
            if not completed:
                return 0
            return max(0, int(media.get_duration()))
        except Exception:
            log.debug("duration probe failed for %s", path, exc_info=True)
            return 0
        finally:
            if event_manager is not None and parse_event is not None and callback:
                try:
                    event_manager.event_detach(parse_event, callback)
                except Exception:
                    pass
            if media is not None:
                if completed or not parse_started:
                    try:
                        media.release()
                    except Exception:
                        pass
                else:
                    # Safety beats reclaiming one tiny descriptor. Releasing
                    # here is the exact parse-thread use-after-free fixed in the
                    # previous round. Keep it until process teardown instead.
                    with self._deferred_probe_lock:
                        self._deferred_probe_media.append(media)

    @Slot()
    def play(self) -> None:
        if self._player is None or self._media is None or not self._current_mrl:
            return
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
        if self._player is None or self._media is None or not self._current_mrl:
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
        if self._time != 0:
            self._time = 0
            self.timeChanged.emit(0)
        if self._position != 0.0:
            self._position = 0.0
            self.positionChanged.emit(0.0)
        if self._duration != 0:
            self._duration = 0
            self.durationChanged.emit(0)

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
        self._current_mrl = ""
        try:
            self.video_output.notify_video_stopped()
        except Exception:
            log.debug("could not reset the video surface on stop", exc_info=True)
        self._reset_timeline()
        self._publish_state_now()

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
    def has_video(self) -> bool:
        """Check if the current media has video tracks.
        
        Returns True if at least one video track exists (excluding the disable track).
        Used to determine if subtitle features should be enabled.
        """
        try:
            video_tracks = self._player.video_get_track_description()
            if not video_tracks:
                return False
            # Filter out the disable track (id=-1) and check if any real tracks exist
            real_tracks = [tid for tid, _ in video_tracks if tid != -1]
            return len(real_tracks) > 0
        except Exception:
            log.debug("video_get_track_description failed", exc_info=True)
            return False

    def audio_tracks(self) -> list[tuple[int, str]]:
        """Audio tracks, named by **language** wherever the file says one.

        ``audio_get_track_description()`` returns whatever string the muxer
        put in the track's *title* field, and most releases leave that empty —
        so libVLC synthesises ``Track 1``, ``Track 2``, ``Audio Track 3``. On a
        dual-audio file that is the whole problem: two rows, both meaningless,
        and no way to tell the English dub from the Hindi one without playing
        each in turn.

        The language is not missing, it is just in a different place. Every
        elementary stream carries an ISO language code, exposed on the *media*
        (``media.tracks_get()``) rather than on the player's description list.
        This joins the two by track id and prefers the language whenever the
        description is a placeholder:

            (1, "Track 1")  + language "eng"        ->  (1, "English")
            (2, "Track 2")  + language "hin"        ->  (2, "Hindi")
            (3, "Commentary") + language "eng"      ->  (3, "Commentary")

        A real title always wins — someone who labelled a track "Director's
        Commentary" said something the language code cannot. Two tracks that
        resolve to the *same* language keep a disambiguating suffix, because
        "English" twice is no better than "Track 1" twice.

        Everything here is best-effort: any failure falls back to libVLC's own
        description, which is exactly the previous behaviour.
        """
        raw = _describe_tracks(self._player.audio_get_track_description())
        languages = self._track_languages()
        if not languages:
            return raw

        named: list[tuple[int, str]] = []
        for track_id, label in raw:
            if track_id == -1:
                named.append((track_id, label))
                continue
            language = languages.get(track_id, "")
            if language and _is_generic_track_name(label):
                named.append((track_id, language))
            else:
                named.append((track_id, label))

        return _disambiguate(named)

    def _track_languages(self) -> dict[int, str]:
        """``{track id: "English"}`` for every stream the media declares.

        Read from the media rather than the player because that is the only
        place libVLC exposes the ISO language code. Returns ``{}`` on any
        problem — a missing language costs a nicer label, never a track.
        """
        media = self._media
        if media is None:
            return {}
        out: dict[int, str] = {}
        try:
            # python-vlc's Media.tracks_get() leaks its native allocation (the
            # generated release line is commented out). The context manager
            # uses the raw API and keeps nested pointers valid until release.
            with media_tracks(self._vlc, media) as tracks:
                for track in tracks:
                    code = getattr(track, "language", None)
                    if isinstance(code, bytes):
                        code = code.decode("utf-8", "replace")
                    if not code:
                        continue
                    name = _LANGUAGE_NAMES.get(str(code).strip().lower())
                    if name:
                        out[int(track.id)] = name
        except Exception:
            log.debug("could not read track languages", exc_info=True)
            return {}
        return out

    def subtitle_tracks(self) -> list[tuple[int, str]]:
        """Return subtitle tracks, with real names for external subtitles.

        libVLC names a track attached through ``add_slave`` after whatever the
        demuxer felt like — usually ``Track 1`` / ``Subtitle Track 2``, and on
        some builds simply ``Track 4`` with no relation to anything the user
        typed. "Track 4" tells you nothing about which of three .srt files you
        just loaded, so the stem of the file that produced the track is used
        instead.

        **A pending name is claimed by id, not by label.** The previous version
        matched on the label looking generic, and that is why downloaded and
        loaded subtitles kept showing up as "Track xx" anyway:

        * the generic-name list was a guess at libVLC's wording, and any build
          or locale that phrased it differently (``Track 4 - [Undetermined]``,
          ``Subtitle track #1``, a bare language code) failed the regex, so the
          real name was never applied;
        * worse, the *first* generic-looking row won — including an **embedded**
          track that happened to be unnamed — so the sidecar's name could be
          stapled to a completely different track while the new one kept its
          number.

        ``_known_spu_ids`` records which SPU ids existed when the file was
        opened, when each slave was attached, and after every refresh. A track
        whose id is not in that set has appeared since — which, given
        ``add_slave`` is the only thing that adds one mid-playback, is the
        track a pending name belongs to. Ids are compared, not prose, so this
        holds in every locale and on every libVLC build.

        **Names are claimed from the tail of the fresh ids**, and that detail
        is load-bearing. Auto-loading a sidecar happens on ``mediaChanged``,
        which can beat libVLC's discovery of the file's *embedded* subtitle
        streams — so a single refresh may surface two embedded tracks and the
        slave all at once, all of them "fresh". libVLC appends slaves after the
        embedded streams, so the last N fresh ids are the N tracks
        ``add_slave`` produced. Claiming from the front would have named an
        embedded track after the sidecar and left the sidecar as "Track 3",
        which is the reported bug wearing a different hat.

        Unclaimed pending names are kept: ESAdded is asynchronous, so the first
        refresh after ``add_subtitle_file`` frequently runs before libVLC has
        published the track at all.
        """
        raw = _describe_tracks(self._player.video_get_spu_description())

        result: list[tuple[int, str]] = []
        # Ids that are new since the last time we looked, in libVLC's order.
        # The off row (-1) is never a real track and can never be a slave.
        fresh = [tid for tid, _ in raw if tid != -1 and tid not in self._known_spu_ids]
        pending = self._pending_external_subtitles
        # Pair the trailing fresh ids with the pending names, in order.
        claimable = dict(zip(fresh[-len(pending):], list(pending))) if pending else {}
        claimed_count = len(claimable)

        for track_id, name in raw:
            stored = self._external_subtitle_names.get(track_id)
            if stored is not None:
                result.append((track_id, stored))
                continue
            if track_id in claimable:
                claimed = claimable[track_id]
                self._external_subtitle_names[track_id] = claimed
                result.append((track_id, claimed))
                continue
            # An embedded track, or an external one we have run out of names
            # for. Fall back to libVLC's label, tidied: a bare "Track 4" is
            # noise, but it is still better than an empty row.
            result.append((track_id, name.strip() or f"Track {track_id}"))

        # Drop only the names that actually found a track; the rest wait for
        # the refresh that follows libVLC's ESAdded.
        if claimed_count:
            del pending[:claimed_count]
        # Remember everything we have now seen, so the *next* add_slave is
        # measured against this state rather than against the file's original
        # track list.
        self._known_spu_ids.update(tid for tid, _ in raw if tid != -1)
        # Downloading English for a film that already carries an embedded
        # English track leaves two rows reading "English" — as impossible to
        # tell apart as the "Track 1"/"Track 2" this replaced. Same treatment
        # as the audio list: only duplicates are touched, and they keep a
        # stable ordinal so rows do not shuffle between refreshes.
        return _disambiguate(result)

    @staticmethod
    def _is_generic_subtitle_name(name: str) -> bool:
        """Whether a label is one of libVLC's placeholder track names.

        No longer used to *claim* a pending name — see ``subtitle_tracks``,
        which matches on track id because prose-matching is what let "Track xx"
        survive. Kept because it is still the honest answer to "is this label
        worth showing to a human", and callers (and tests) ask that.
        """
        generic_patterns = [
            r"^subtitle\s*track\s*#?\s*\d+$",
            r"^track\s*#?\s*\d+$",
            r"^subtitle\s*#?\s*\d+$",
            r"^spu\s*#?\s*\d+$",
            r"^\[\d+\]$",  # "[0]", "[1]", etc.
            r"^\d+$",  # Just a number
        ]
        cleaned = str(name or "").strip()
        return any(re.match(p, cleaned, re.IGNORECASE) for p in generic_patterns)

    def current_audio_track(self) -> int:
        """The track libVLC is *actually* playing, or ``-1`` for none.

        This is the missing half of track selection. Without it the popover had
        no way to tell which row is live, so it fell back to its default
        ``currentAudioId: -1`` — which is libVLC's id for **Disable** — and drew
        the highlight on "Disable" while sound was plainly coming out. The
        selected row and the audible track are the same fact; it has to be read
        from the player, not assumed.
        """
        try:
            return int(self._player.audio_get_track())
        except Exception:
            log.debug("audio_get_track failed", exc_info=True)
            return -1

    def current_subtitle_track(self) -> int:
        try:
            return int(self._player.video_get_spu())
        except Exception:
            log.debug("video_get_spu failed", exc_info=True)
            return -1

    @Slot(int)
    def set_audio_track(self, track_id: int) -> None:
        self._player.audio_set_track(int(track_id))
        # libVLC does not raise ESSelected for an application-driven switch, so
        # nothing else would tell the UI the selection moved.
        self.tracksChanged.emit()

    @Slot(int)
    def set_subtitle_track(self, track_id: int) -> None:
        self._player.video_set_spu(int(track_id))
        self.tracksChanged.emit()

    @Slot(str, result=bool)
    def add_subtitle_file(self, path: str) -> bool:
        """External subtitle via ``add_slave`` (§P1.5).

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
        # Snapshot the SPU ids that exist *before* the slave is attached, so
        # whatever appears afterwards is identifiable as new. Doing it here
        # rather than relying on the last refresh closes the window where a
        # track arrived between that refresh and this call.
        try:
            for tid, _ in _describe_tracks(self._player.video_get_spu_description()):
                if tid != -1:
                    self._known_spu_ids.add(tid)
        except Exception:
            log.debug("could not snapshot subtitle tracks before add_slave", exc_info=True)
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
                self._vlc.MediaSlaveType.subtitle, resolved.resolve().as_uri(), True
            )
        except Exception:
            log.exception("add_subtitle_file failed for %s", resolved)
            return False
        if rc != 0:
            log.warning("libVLC rejected subtitle %s (rc=%s)", resolved.name, rc)
            return False
        # Store the label for later use when describing tracks. The track id is
        # assigned asynchronously by VLC, so we queue the name and claim it in
        # subtitle_tracks() once the track appears.
        #
        # Guarded, and returning True regardless: the slave is *already
        # attached* by this point. Failing the call because we could not work
        # out a pretty label would report a working subtitle as broken — the
        # worst possible trade. A stream URL, for instance, has no local stem
        # to strip, and that must cost a nice name, not the subtitle.
        try:
            media_stem = Path(paths.normalise_path(self._current_mrl)).stem
        except Exception:
            media_stem = ""
        try:
            label = _subtitle_label(resolved, media_stem)
        except Exception:
            log.debug("could not label subtitle %s", resolved, exc_info=True)
            label = resolved.stem or "Subtitle"
        self._pending_external_subtitles.append(label)
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

                # Stop new work, but keep every ctypes video trampoline alive
                # until MediaPlayer.release() has destroyed the native vout.
                # A settled state is not proof that a callback stack has already
                # returned; clearing it before release leaves a dangling C
                # function pointer and causes an untraceable access violation.
                self._detach_events()
                self.video_output.detach()
                player = self._player
                player.release()
                self._player = None
                self.video_output.release_callbacks()
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
            try:
                self.video_output.detach()
            except Exception:
                log.debug("video callback detach failed", exc_info=True)
        log.info("engine shut down")

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

    @Property(bool, notify=tracksChanged)
    def hasVideo(self) -> bool:  # noqa: N802 - QML-facing
        """True if the current media has at least one video track."""
        return self.has_video()

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


#: ISO 639-1/2 codes (and the odd spelled-out name) mapped to what a person
#: would rather read. Used for two things, both purely cosmetic: naming an
#: *audio* track whose title field the muxer left empty, and reading the
#: language tag off a subtitle filename. Nothing routes or decides on these.
_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "eng": "English", "english": "English",
    "es": "Spanish", "spa": "Spanish", "spanish": "Spanish",
    "fr": "French", "fra": "French", "fre": "French", "french": "French",
    "de": "German", "ger": "German", "deu": "German", "german": "German",
    "it": "Italian", "ita": "Italian", "italian": "Italian",
    "pt": "Portuguese", "por": "Portuguese", "portuguese": "Portuguese",
    "pt-br": "Portuguese (BR)", "pob": "Portuguese (BR)",
    "nl": "Dutch", "dut": "Dutch", "nld": "Dutch", "dutch": "Dutch",
    "pl": "Polish", "pol": "Polish", "polish": "Polish",
    "ru": "Russian", "rus": "Russian", "russian": "Russian",
    "uk": "Ukrainian", "ukr": "Ukrainian",
    "tr": "Turkish", "tur": "Turkish", "turkish": "Turkish",
    "ar": "Arabic", "ara": "Arabic", "arabic": "Arabic",
    "fa": "Persian", "per": "Persian", "fas": "Persian",
    "he": "Hebrew", "heb": "Hebrew",
    "hi": "Hindi", "hin": "Hindi", "hindi": "Hindi",
    "bn": "Bengali", "ben": "Bengali", "bengali": "Bengali",
    "ta": "Tamil", "tam": "Tamil", "ur": "Urdu", "urd": "Urdu",
    "id": "Indonesian", "ind": "Indonesian", "ms": "Malay", "may": "Malay",
    "th": "Thai", "tha": "Thai", "vi": "Vietnamese", "vie": "Vietnamese",
    "zh": "Chinese", "chi": "Chinese", "zho": "Chinese",
    "zh-cn": "Chinese (simplified)", "zh-tw": "Chinese (traditional)",
    "ja": "Japanese", "jpn": "Japanese", "japanese": "Japanese",
    "ko": "Korean", "kor": "Korean", "korean": "Korean",
    "cs": "Czech", "cze": "Czech", "sk": "Slovak", "slo": "Slovak",
    "hu": "Hungarian", "hun": "Hungarian", "ro": "Romanian", "rum": "Romanian",
    "bg": "Bulgarian", "bul": "Bulgarian", "el": "Greek", "gre": "Greek",
    "sv": "Swedish", "swe": "Swedish", "da": "Danish", "dan": "Danish",
    "fi": "Finnish", "fin": "Finnish", "no": "Norwegian", "nor": "Norwegian",
    "hr": "Croatian", "hrv": "Croatian", "sr": "Serbian", "srp": "Serbian",
    "sl": "Slovenian", "slv": "Slovenian",
}

#: Suffixes that qualify a subtitle rather than name it.
_SUBTITLE_QUALIFIERS: dict[str, str] = {
    "sdh": "SDH",
    "cc": "CC",
    "hi": "SDH",          # only ever read *after* a language, see below
    "forced": "forced",
    "full": "full",
}


#: libVLC's synthesised names for a stream whose title field is empty. These are
#: the labels worth replacing with a language; anything else is a real title
#: somebody chose, and is left alone.
_GENERIC_TRACK_RE = re.compile(
    r"""^(
        (audio|subtitle|spu|video)?\s*track\s*\#?\s*\d+
      | (audio|subtitle|spu)\s*\#?\s*\d+
      | \[\s*\d+\s*\]
      | \d+
      | track
      | -
    )$""",
    re.IGNORECASE | re.VERBOSE,
)


def _is_generic_track_name(name: str) -> bool:
    """Whether a track label is a placeholder rather than a chosen title."""
    cleaned = str(name or "").strip()
    if not cleaned:
        return True
    return bool(_GENERIC_TRACK_RE.match(cleaned))


def _disambiguate(tracks: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Make repeated labels distinguishable again.

    A file with two English audio streams (a stereo mix and a 5.1 mix, say)
    resolves both to "English", which is exactly as useless as the "Track 1" /
    "Track 2" this replaced. Only duplicates are touched, and they keep a
    stable ordinal so the rows do not shuffle between refreshes.
    """
    seen: dict[str, int] = {}
    for _, label in tracks:
        seen[label] = seen.get(label, 0) + 1

    used: dict[str, int] = {}
    out: list[tuple[int, str]] = []
    for track_id, label in tracks:
        if seen.get(label, 0) > 1 and track_id != -1:
            used[label] = used.get(label, 0) + 1
            out.append((track_id, f"{label} {used[label]}"))
        else:
            out.append((track_id, label))
    return out


def _subtitle_label(subtitle: Path, media_stem: str) -> str:
    """A human label for an external subtitle file.

    The stem alone is what produced the second half of the "Track xx" report.
    A downloaded subtitle is saved as ``<media stem>.<lang><ext>`` and a sidecar
    is usually named after the release too, so the raw stem is a 60-character
    repeat of the filename already shown in the title bar —
    ``Andor.S02E01.1080p.WEB-DL.x265-GROUP.en``. In a 340px popover that elides
    to ``Andor.S02E01.1080p.WEB…``, which distinguishes nothing when there are
    two of them.

    So: strip the media's own name off the front, and read what is left.
    ``Movie.en`` becomes **English**, ``Movie.en.sdh`` becomes **English SDH**,
    ``Movie.forced`` becomes **forced**. Anything unrecognised is kept verbatim
    (it is the user's own naming, and they know what it means), and a subtitle
    whose name carries no extra information at all falls back to the file's own
    stem so the row is never blank.
    """
    stem = subtitle.stem
    remainder = stem
    # Only strip the media stem when the subtitle genuinely sits under it;
    # an unrelated .srt keeps its whole name.
    if media_stem and stem.lower().startswith(media_stem.lower()):
        remainder = stem[len(media_stem):]
    remainder = remainder.strip(" ._-")

    if not remainder:
        # `Movie.srt` next to `Movie.mkv` — nothing to add, so name it after
        # the file rather than after the video it duplicates.
        return subtitle.stem or "Subtitle"

    # A bare de-duplication counter is not a name. `_save` appends ".2", ".3"
    # when it refuses to clobber an existing subtitle, so a download whose
    # language tag the server omitted lands as `Movie.2.srt` — and the row then
    # read "2", which is the meaningless-number symptom this function exists to
    # remove, arriving by a different route. Name it after the file instead.
    if remainder.isdigit():
        return subtitle.stem or "Subtitle"

    # Whole-remainder match first, so a regional tag written with the hyphen
    # that also separates fields — `Movie.pt-BR.srt` — is read as one code
    # rather than split into "pt" and an unknown "BR".
    if remainder.lower() in _LANGUAGE_NAMES:
        return _LANGUAGE_NAMES[remainder.lower()]

    parts = [p for p in re.split(r"[ ._-]+", remainder) if p]
    language = ""
    qualifiers: list[str] = []
    unknown: list[str] = []
    for part in parts:
        key = part.lower()
        if not language and key in _LANGUAGE_NAMES:
            language = _LANGUAGE_NAMES[key]
        elif key in _SUBTITLE_QUALIFIERS and (key != "hi" or language):
            # "hi" is Hindi at the front of the remainder and hearing-impaired
            # after a language has already been read — `Movie.en.hi.srt`.
            tag = _SUBTITLE_QUALIFIERS[key]
            if tag not in qualifiers:
                qualifiers.append(tag)
        else:
            unknown.append(part)

    # Nothing was recognised: this is the user's own name for the file, so show
    # it exactly as they wrote it rather than a de-punctuated rewrite of it.
    if not language and not qualifiers:
        return remainder

    label = " ".join(filter(None, [language, *qualifiers, *unknown])).strip()
    return label or subtitle.stem or "Subtitle"


def _describe_tracks(raw) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    if not raw:
        return out
    for track_id, name in raw:
        label = name.decode("utf-8", "replace") if isinstance(name, bytes) else str(name)
        out.append((int(track_id), label))
    return out
