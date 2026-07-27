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
        if self._releasing or self._player is None:
            return
        try:
            raw = int(self._player.get_state())
        except Exception:
            return
        state = _VLC_STATE_MAP.get(raw, State.Idle)
        if state != self._state:
            self._state = state
            self.stateChanged.emit(int(state))

        duration = max(0, int(self._player.get_length()))
        if duration != self._duration:
            self._duration = duration
            self.durationChanged.emit(duration)

        time_ms = max(0, int(self._player.get_time()))
        if time_ms != self._time:
            self._time = time_ms
            self.timeChanged.emit(time_ms)

        position = float(self._player.get_position() or 0.0)
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
        self._player.play()

    @Slot()
    def pause(self) -> None:
        if self._player.can_pause():
            self._player.set_pause(1)

    @Slot()
    def toggle(self) -> None:
        """Single implementation of play/pause — §4.1. Space, the transport
        button and the OSD all route here."""
        if self._state == State.Playing:
            self.pause()
        else:
            self.play()

    @Slot()
    def stop(self) -> None:
        try:
            self._player.stop()
        except Exception:
            log.exception("stop failed")

    @Slot(int)
    def seek(self, ms: int) -> None:
        if self._duration > 0:
            ms = max(0, min(ms, self._duration))
        self._player.set_time(int(ms))
        self._time = int(ms)
        self.timeChanged.emit(self._time)

    @Slot(int)
    def seek_relative(self, delta_ms: int) -> None:
        self.seek(self._time + int(delta_ms))

    @Slot(float)
    def set_position(self, fraction: float) -> None:
        fraction = max(0.0, min(1.0, float(fraction)))
        self._player.set_position(fraction)
        self._position = fraction
        self.positionChanged.emit(fraction)

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
        try:
            if self._player is not None:
                self._player.stop()
                # Give VLC's threads a moment to unwind before the memory they
                # are still touching disappears.
                deadline = 2000
                waited = 0
                while waited < deadline:
                    try:
                        if int(self._player.get_state()) in (0, 5, 6, 7):
                            break
                    except Exception:
                        break
                    QTimer.singleShot(0, lambda: None)
                    import time

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
