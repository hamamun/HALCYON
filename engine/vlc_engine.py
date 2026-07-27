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
import sys
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

log = logging.getLogger(__name__)


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
                os.add_dll_directory(str(base))
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
        self.endReached.emit()

    def _on_error(self, _event) -> None:
        self.errorOccurred.emit(f"Could not play {self._current_mrl or 'media'}")

    def _on_state_event(self, _event) -> None:
        pass  # the poll timer publishes state on the GUI thread

    def _on_buffering(self, event) -> None:
        try:
            self.buffering.emit(float(event.u.new_cache))
        except Exception:
            pass

    def _on_length(self, _event) -> None:
        pass  # picked up by the poll

    def _on_tracks(self, _event) -> None:
        self.tracksChanged.emit()

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
            duration = max(0, int(player.get_length()))
        except Exception:
            duration = self._duration
        if duration != self._duration:
            self._duration = duration
            self.durationChanged.emit(duration)

        # While the user is dragging the seek bar the UI is authoritative:
        # publishing VLC's pre-seek time here would yank the knob backwards
        # between the drag and the seek landing.
        if not self._scrubbing:
            try:
                time_ms = max(0, int(player.get_time()))
            except Exception:
                time_ms = self._time
            if time_ms != self._time:
                self._time = time_ms
                self.timeChanged.emit(time_ms)

            try:
                position = float(player.get_position() or 0.0)
            except Exception:
                position = self._position
            # A stopped/ended player reports -1; clamp so the bar never renders
            # a negative fill.
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

        media = self._instance.media_new(mrl)
        if media is None:
            self.errorOccurred.emit(f"Could not open {path_or_url}")
            return
        media.parse_with_options(self._vlc.MediaParseFlag.local, 3000)
        self._media = media
        self._player.set_media(media)
        self._current_mrl = mrl
        self.mediaChanged.emit(mrl)
        self._player.play()
        if start_ms > 0:
            QTimer.singleShot(300, lambda: self.seek(start_ms))

    @Slot()
    def play(self) -> None:
        if self._player is None:
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
        if self._player is None:
            return
        try:
            live = _VLC_STATE_MAP.get(_enum_int(self._player.get_state()), self._state)
        except Exception:
            live = self._state
        if live == State.Playing:
            self.pause()
        else:
            self.play()

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
        except Exception:
            log.exception("stop failed")
        self._scrubbing = False
        self._current_mrl = ""
        if self._time != 0:
            self._time = 0
            self.timeChanged.emit(0)
        if self._position != 0.0:
            self._position = 0.0
            self.positionChanged.emit(0.0)
        if self._duration != 0:
            self._duration = 0
            self.durationChanged.emit(0)
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
        ms = max(0, int(ms))
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
    def audio_tracks(self) -> list[tuple[int, str]]:
        return _describe_tracks(self._player.audio_get_track_description())

    def subtitle_tracks(self) -> list[tuple[int, str]]:
        return _describe_tracks(self._player.video_get_spu_description())

    @Slot(int)
    def set_audio_track(self, track_id: int) -> None:
        self._player.audio_set_track(int(track_id))

    @Slot(int)
    def set_subtitle_track(self, track_id: int) -> None:
        self._player.video_set_spu(int(track_id))

    @Slot(str, result=bool)
    def add_subtitle_file(self, path: str) -> bool:
        """External subtitle via ``add_slave`` (§P1.5)."""
        try:
            uri = Path(path).expanduser().resolve().as_uri()
            rc = self._player.add_slave(self._vlc.MediaSlaveType.subtitle, uri, True)
            return rc == 0
        except Exception:
            log.exception("add_subtitle_file failed")
            return False

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
        # Detach first: no VLC event may reach Python once teardown starts.
        self._detach_events()
        try:
            if self._player is not None:
                self._player.stop()
                # Give VLC's threads a moment to unwind before the memory they
                # are still touching disappears.
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
            log.exception("shutdown was not clean")
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
