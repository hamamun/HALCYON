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
from engine import hw_decode
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

# How long a hardware-decoded media may play without producing a single
# decoded picture before the engine concludes the GPU path is broken and
# re-opens the same media with CPU decode (engine/hw_decode.py). Long enough
# for a slow disk and a cold decoder to deliver the first frame; short enough
# that a black screen never settles in as the outcome.
_HW_DECODE_GRACE_S = 3.0

# How long a Soft (vmem) media may play with video tracks but without a
# single published frame before we conclude Soft failed to generate video
# (shader missing, format negotiation failed, Nuitka callback race) and
# rescue it by switching to Turbo. Same grace as HW watchdog — 3s is
# enough for a slow disk, short enough that audio-only with a black stage
# never settles as the outcome. See task 1: Soft failed detection -> Turbo.
_SOFT_DECODE_GRACE_S = 3.0

# libVLC's public time and position values are samples from the demuxer, not a
# continuously advancing presentation clock. Some files update them sparsely;
# malformed files can leave one value at zero or -1 until the first seek. The
# UI clock therefore advances between trustworthy samples. A fresh sample may
# lead the current UI value by the time since the previous poll plus this small
# allowance; anything farther away is treated as a broken/stale sample rather
# than making every clock and seek bar jump.
_TIMELINE_SAMPLE_SLOP_MS = 2_000
# A normal poll gap is 200 ms. If the process wakes after system sleep, libVLC
# can still say Playing while its unchanged samples correctly show that no media
# time elapsed. Never turn that ambiguous wall-clock gap into a jump to the end;
# backend samples may account for the full gap, but interpolation does not guess
# across an unexplained delay longer than five seconds.
_TIMELINE_MAX_FALLBACK_GAP_MS = 5_000


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

#: Where libVLC's binauralizer looks for its head-related transfer function.
#:
#: ``spatialaudio.cpp`` builds the default path as
#: ``config_GetDataDir() + "/hrtfs/dodeca_and_7channel_3DSL_HRTF.sofa"``, and on
#: Windows ``config_GetDataDir()`` is ``VLC_DATA_PATH`` when set, otherwise the
#: directory containing ``libvlccore.dll`` (``src/win32/dirs.c``). Our bundled
#: layout puts ``libvlccore.dll`` in ``vendor/vlc``, so a file at
#: ``vendor/vlc/hrtfs/<name>.sofa`` is found with no configuration at all.
#:
#: Without it, playing a 5.1 track through a stereo device prints
#: "Could not load the SOFA HRTF" straight to stderr — bypassing our logging,
#: because it happens inside libVLC — and binaural spatialisation silently
#: degrades to a plain downmix. Audio still plays, which is why it is easy to
#: miss.
HRTF_DIR_NAME = "hrtfs"
DEFAULT_HRTF_NAME = "dodeca_and_7channel_3DSL_HRTF.sofa"


def find_bundled_hrtf(base: Path | None) -> tuple[Path | None, bool]:
    """Locate a bundled ``.sofa`` HRTF under ``base``.

    Returns ``(path, needs_option)``. ``needs_option`` is True when the file is
    present but somewhere libVLC will not look by itself, so the caller has to
    pass ``--hrtf-file`` explicitly.

    Both layouts are accepted deliberately. ``hrtfs/`` is the canonical one —
    it mirrors how VLC ships and costs no libVLC options — but a ``.sofa``
    dropped straight into ``vendor/vlc/`` is the obvious mistake to make, and
    rescuing it is one line here versus a silent loss of spatial audio.
    """
    if base is None:
        return None, False
    canonical = base / HRTF_DIR_NAME / DEFAULT_HRTF_NAME
    if canonical.is_file():
        return canonical, False
    # A differently named .sofa still has to be pointed at explicitly: libVLC
    # only auto-loads the one canonical filename. Then the loose-in-vendor/vlc
    # case, which libVLC cannot find at all without being told.
    search_dirs = [base / HRTF_DIR_NAME, base]
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        for candidate in sorted(directory.glob("*.sofa")):
            return candidate, True
    return None, False


def _resolve_bundled_vlc() -> Path | None:
    """Point ctypes at ``vendor/vlc`` if it is populated.

    Must happen *before* ``import vlc``. In a packaged build the same directory
    sits under the application root (§9, the Nuitka row).

    Two things here are deliberately not left to python-vlc's own finder:

    * python-vlc's ``find_lib()`` calls ``sys.exit(1)`` when
      ``PYTHON_VLC_LIB_PATH`` points at a DLL that fails to load (e.g. a
      missing VC++/MinGW dependency). That is a silent, uncatchable exit in a
      GUI subsystem build. We preload ``libvlccore.dll`` then ``libvlc.dll``
      ourselves *first*; if a dependency is missing the OSError names it, and
      once the DLLs are mapped into the process python-vlc's subsequent
      ``ctypes.CDLL`` just increments the refcount.
    * python-vlc derives ``VLC_PLUGIN_PATH`` from ``PYTHON_VLC_MODULE_PATH``
      (not from the lib path), so set both.
    """
    candidates = [paths.VENDOR_VLC]
    if paths.is_packaged_build():
        # Nuitka does not set sys.frozen, so the old check skipped the bundled
        # copy entirely. Check next to the executable as well so a layout where
        # the runtime lives directly beside Halcyon.exe is also accepted. The
        # Inno Setup build uses vendor/vlc (the first candidate); a bare
        # "vlc/" folder is kept for manual/sideload deployments.
        candidates.insert(0, Path(sys.executable).resolve().parent / "vendor" / "vlc")
        candidates.append(Path(sys.executable).resolve().parent / "vlc")

    for base in candidates:
        if not base.is_dir():
            continue
        if sys.platform == "win32":
            lib = base / "libvlc.dll"
            core = base / "libvlccore.dll"
        else:
            core = base / "libvlccore.so"
            lib = next(iter(base.glob("libvlc.so*")), None)
        if not lib or not lib.exists():
            continue

        plugins = base / "plugins"
        if plugins.is_dir():
            os.environ["VLC_PLUGIN_PATH"] = str(plugins)
            # python-vlc reads this and sets VLC_PLUGIN_PATH itself; setting
            # both means it works regardless of which code path reaches libVLC.
            os.environ["PYTHON_VLC_MODULE_PATH"] = str(plugins)

        if sys.platform == "win32":
            # Do not discard this handle: discarding it immediately removes
            # ``base`` from the DLL search path, which can make libvlc.dll
            # load while libvlccore.dll or a codec plugin fails later.
            try:
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(base)))
            except (AttributeError, OSError):
                # Older Python/Windows combinations may not expose the API;
                # ctypes can still use the explicit library paths below.
                log.debug("could not register VLC DLL directory", exc_info=True)
            # Put the VLC dir on PATH too — some VLC plugin dependencies are
            # resolved via the loader's normal search, not add_dll_directory.
            os.environ["PATH"] = str(base) + os.pathsep + os.environ.get("PATH", "")

            # Preload core then main library so a missing dependency is a
            # catchable OSError (naming the missing DLL) rather than python-vlc's
            # sys.exit(1). Hold references for the process lifetime.
            import ctypes

            try:
                if not core.exists():
                    raise FileNotFoundError(f"missing {core.name} in {base}")
                _DLL_DIRECTORY_HANDLES.append(ctypes.CDLL(str(core)))
                _DLL_DIRECTORY_HANDLES.append(ctypes.CDLL(str(lib)))
            except OSError as exc:
                raise OSError(
                    f"could not load libVLC from {base}: {exc}. "
                    "The Microsoft Visual C++ 2015-2022 x64 Redistributable may "
                    "be missing."
                ) from exc

        os.environ["PYTHON_VLC_LIB_PATH"] = str(lib)
        log.info("using bundled libVLC at %s", base)
        return base

    log.info("vendor/vlc not populated — falling back to system libVLC")
    return None


def _instance_args(vlc_base: Path | None) -> list[str]:
    """:data:`BASE_VLC_ARGS` plus an explicit ``--hrtf-file`` when needed.

    Kept separate from the constructor so the argument list stays testable
    without a native libVLC instance.
    """
    args = list(BASE_VLC_ARGS)
    try:
        hrtf, needs_option = find_bundled_hrtf(vlc_base)
    except Exception:  # never let a missing optional file stop playback
        log.debug("HRTF lookup failed", exc_info=True)
        return args
    if hrtf is None:
        # Not an error: VLC downmixes multichannel audio perfectly well
        # without it. Logged at debug so the absence is diagnosable when
        # somebody asks why binaural mode is quiet.
        log.debug(
            "no bundled HRTF under %s — binaural spatialisation unavailable",
            vlc_base,
        )
        return args
    if needs_option:
        args.append(f"--hrtf-file={hrtf}")
        log.info("using bundled HRTF at %s (explicit --hrtf-file)", hrtf)
    else:
        log.info("using bundled HRTF at %s", hrtf)
    return args


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
    # Hardware-decode watchdog state (§V.2, engine/hw_decode.py). ``pending``
    # is True only while the *current* media was opened with the GPU-decode
    # option and its health has not been confirmed yet; ``override`` names the
    # one MRL that must be re-opened with CPU decode after a runtime failure.
    _hw_decode_pending = False
    _hw_watch_started = None
    _cpu_decode_override = ""
    # Soft failure watchdog: Soft has video tracks but no frames published.
    _soft_decode_pending = False
    _soft_watch_started = None
    _soft_failed_mrls: set = set()
    # Defaults keep the timeline helpers safe in focused tests that construct
    # VlcEngine with __new__ instead of starting a native libVLC instance.
    _timeline_tick = None
    _last_vlc_time = None
    _last_vlc_position = None

    def __init__(self, backend: str = "auto", parent: QObject | None = None) -> None:
        super().__init__(parent)
        vlc_base = _resolve_bundled_vlc()
        try:
            import vlc  # noqa: PLC0415 - deliberately after the path fix-up
        except ImportError as exc:
            raise RuntimeError(
                "The python-vlc module is missing from this build "
                f"({exc}). Rebuild with --include-module=vlc."
            ) from exc

        self._vlc = vlc
        self._instance = vlc.Instance(_instance_args(vlc_base))
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
        # Soft failure watchdog (task 1)
        self._soft_decode_pending = False
        self._soft_watch_started = None
        self._soft_failed_mrls = set()

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
    # delivery to the GUI thread for us. Varargs-tolerant for Nuitka 1.3.1
    # installed build: event callbacks can be invoked with different argcounts
    # in compiled exe vs CPython dev.
    def _on_end_reached(self, *_args) -> None:
        try:
            self.endReached.emit()
        except Exception:
            pass

    def _on_error(self, *_args) -> None:
        try:
            self.errorOccurred.emit(f"Could not play {self._current_mrl or 'media'}")
        except Exception:
            pass

    def _on_state_event(self, *_args) -> None:
        pass  # the poll timer publishes state on the GUI thread

    def _on_buffering(self, *args) -> None:
        try:
            event = args[0] if args else None
            new_cache = float(event.u.new_cache) if event is not None else 0.0
        except Exception:
            return
        # libVLC reports the cache as a percentage (0..100). Both consumers
        # want a fraction: M3U's hairline (via `buffering`) and the seek
        # bars' buffer fill (via `buffered`), which multiply it by a width.
        try:
            buffered = max(0.0, min(1.0, new_cache / 100.0))
            if abs(buffered - self._buffered) > 1e-4:
                self._buffered = buffered
                self.bufferedChanged.emit(buffered)
            self.buffering.emit(new_cache)
        except Exception:
            pass

    def _on_length(self, *_args) -> None:
        pass  # picked up by the poll

    def _on_tracks(self, *_args) -> None:
        try:
            self.tracksChanged.emit()
        except Exception:
            pass

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
        playing_interval = state == State.Playing and previous_state == State.Playing
        rate = max(0.0, float(self._rate))
        # Full elapsed time validates a backend sample after a delayed GUI tick.
        # The self-generated fallback is capped separately so suspend/resume
        # cannot manufacture minutes of media time from an unchanged VLC clock.
        expected_advance_ms = elapsed_ms * rate if playing_interval else 0.0
        fallback_advance_ms = (
            elapsed_ms * rate
            if playing_interval and elapsed_ms <= _TIMELINE_MAX_FALLBACK_GAP_MS
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
            fallback_advance_ms = 0.0

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
                candidate = self._time + int(round(fallback_advance_ms))
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
        # Turbo's decode watchdog (§V.2): confirm a media opened with the
        # GPU-decode request is actually producing pictures, and quietly
        # re-open it with CPU decode when it is not. No-op on Soft and for
        # media that never asked for hardware decode.
        try:
            self._check_hw_decode_health(state)
        except Exception:
            log.debug("hardware-decode health check failed", exc_info=True)
            self._hw_decode_pending = False
        # Soft failure watchdog (task 1): Soft has video tracks but no frames.
        try:
            self._check_soft_decode_health(state)
        except Exception:
            log.debug("soft-decode health check failed", exc_info=True)
            self._soft_decode_pending = False

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
        # Disarm the decode watchdogs with the media it was watching; the new
        # media re-arms them below only if needed.
        self._hw_decode_pending = False
        self._hw_watch_started = None
        self._soft_decode_pending = False
        self._soft_watch_started = None
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
        #
        # The GPU request is a *route-level* wish, not a per-media certainty:
        # legacy codecs (WMV3/VC-1, DivX-era MPEG-4) black-screen on the
        # d3d11va path because drivers advertise decoders they no longer
        # honour. _effective_media_options() replaces the request for known-bad
        # containers and for a media the runtime watchdog already caught with
        # an explicit ``:avcodec-hw=none``.  Omitting the D3D11VA option is not
        # sufficient: libVLC 3's ``set_hwnd`` resets the player-level decoder
        # choice to automatic, which overrides the instance's
        # ``--avcodec-hw=none``.  The native Turbo window stays; only decode
        # moves to the CPU, exactly as it does in VLC's desktop player (§V.2).
        options = self._effective_media_options(mrl)
        for option in options:
            try:
                media.add_option(option)
            except Exception:
                log.debug("media option %s rejected", option, exc_info=True)
        # Arm the decode watchdog only when the GPU was actually requested.
        self._hw_decode_pending = hw_decode.HW_DECODE_OPTION in options
        self._hw_watch_started = None
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
        # A stopped player has no media to watch.
        self._hw_decode_pending = False
        self._hw_watch_started = None
        self._soft_decode_pending = False
        self._soft_watch_started = None
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
            # Hardware decode is what Turbo is for.  set_hwnd resets libVLC
            # 3's player-level decoder value to automatic; record the narrower
            # per-media D3D11VA request here.  _effective_media_options() swaps
            # that request for an equally narrow explicit ``none`` when this
            # particular media must use the CPU.
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

    # ------------------------------------------------- hardware decoding ---
    #
    # Turbo is two separable things: the *output route* (libVLC renders into
    # the native child window — works for every file) and the *decode method*
    # (":avcodec-hw=d3d11va" — great for H.264/HEVC/VP9/AV1, a black screen
    # for WMV3/VC-1 and DivX-era MPEG-4, whose hardware decoders modern
    # drivers advertise but reject at execute time, one 0x80070057 per frame).
    # The helpers below keep the two apart, the way VLC's own desktop player
    # does: the Turbo window always stays; only the decoder quietly moves to
    # the CPU when the GPU is a known or proven bad bet. See engine/hw_decode.py.

    def _effective_media_options(self, mrl: str) -> list[str]:
        """Return the recorded options with an explicit decoder for this media.

        Two reasons force CPU decode, checked in order of certainty:

        * the runtime watchdog already proved hardware decode broken for this
          exact MRL (``_cpu_decode_override``) — never hand the driver the
          same media twice;
        * the container is on the legacy list (``hw_decode.path_gpu_safe``),
          where the codec is not knowable synchronously but the extension is
          right in practice for every family that produced the black screens.

        Forced CPU decode must be represented by ``:avcodec-hw=none``, not by
        simply removing ``:avcodec-hw=d3d11va``.  In libVLC 3,
        ``libvlc_media_player_set_hwnd()`` sets the player's ``avcodec-hw``
        variable to an empty string (automatic).  That player-level value
        overrides the instance's ``--avcodec-hw=none``, so an option-less
        WMV/AVI still enters D3D11VA and produces exactly the
        ``Failed to execute: 0x80070057`` log this gate is meant to prevent.
        A media option is closer than both values, so an explicit ``none``
        reliably wins without replacing the player or giving up Turbo's native
        output window.
        """
        options = list(self._media_options)
        if hw_decode.HW_DECODE_OPTION not in options:
            return options
        if self._cpu_decode_override and self._cpu_decode_override == mrl:
            reason = "hardware decode already failed for this media"
        else:
            if hw_decode.path_gpu_safe(mrl) is not False:
                return options
            reason = "legacy container — GPU drivers mishandle this codec family"
        log.info(
            "Turbo output kept, forcing CPU decode with "
            ":avcodec-hw=none: %s (%s)",
            mrl,
            reason,
        )
        return [
            option
            for option in options
            if not option.startswith(":avcodec-hw=")
        ] + [hw_decode.CPU_DECODE_OPTION]

    def _check_hw_decode_health(self, state: State) -> None:
        """Watchdog for a media opened with the GPU-decode request (§V.4).

        The extension gate in :meth:`_effective_media_options` catches the
        known-bad containers before the driver sees them; this catches the
        rest — a legacy codec inside a modern container, or a driver that
        fails a codec the safe-list trusts. Two triggers:

        * the parsed track list names a codec on the unsafe list — fall back
          immediately, no need to wait for pictures that will never come;
        * the media has been Playing for :data:`_HW_DECODE_GRACE_S` seconds,
          has a video track, and libVLC's own statistics show **zero decoded
          pictures** — the black-screen signature, regardless of codec.

        The fallback re-opens the same MRL at the same position with CPU
        decode, exactly like the route-switch reopen: same media, same Turbo
        window, no announcement. Runs on the GUI thread from the poll.
        """
        if not self._hw_decode_pending:
            return
        if self._video_route != video_policy.TURBO:
            # Soft never carries the request; a stale flag must not linger.
            self._hw_decode_pending = False
            return
        if state != State.Playing:
            return
        now = time.monotonic()
        if self._hw_watch_started is None:
            self._hw_watch_started = now
            return

        if self._current_media_gpu_safe() is False:
            self._hw_decode_pending = False
            self._fallback_to_cpu_decode("codec is on the GPU-unsafe list")
            return

        if now - self._hw_watch_started < _HW_DECODE_GRACE_S:
            return

        decoded = self._decoded_video_pictures()
        if decoded is None:
            # No statistics on this build — nothing to measure, stop watching.
            self._hw_decode_pending = False
            return
        if decoded > 0:
            # Pictures are flowing: the hardware path is healthy.
            self._hw_decode_pending = False
            return
        if not self.video_tracks():
            # Audio-only media decodes zero pictures forever, correctly.
            self._hw_decode_pending = False
            return
        self._hw_decode_pending = False
        self._fallback_to_cpu_decode(
            f"no decoded pictures after {_HW_DECODE_GRACE_S:.0f} s"
        )

    def _current_media_gpu_safe(self) -> bool | None:
        """Codec verdict for the media the player holds now, or ``None``.

        ``None`` until the asynchronous parse lands (tracks_get is empty
        before then) — the watchdog just keeps waiting.
        """
        player = self._player
        getter = getattr(player, "get_media", None) if player is not None else None
        if not callable(getter):
            return None
        media = None
        try:
            media = getter()
            return hw_decode.media_gpu_safe(media)
        except Exception:
            log.debug("could not classify the current media's codecs", exc_info=True)
            return None
        finally:
            # get_media returns a new reference; never leak it.
            if media is not None:
                try:
                    media.release()
                except Exception:
                    pass

    def _decoded_video_pictures(self) -> int | None:
        """``decoded_video`` from libVLC's media statistics, or ``None``.

        ``None`` means "cannot know" (no media, no stats API), never zero —
        the watchdog treats the two very differently.
        """
        vlc = self._vlc
        player = self._player
        if vlc is None or player is None:
            return None
        getter = getattr(player, "get_media", None)
        if not callable(getter):
            return None
        media = None
        try:
            media = getter()
            if media is None:
                return None
            stats = vlc.MediaStats()
            if not media.get_stats(stats):
                return None
            return int(stats.decoded_video)
        except Exception:
            log.debug("could not read media statistics", exc_info=True)
            return None
        finally:
            if media is not None:
                try:
                    media.release()
                except Exception:
                    pass

    def _fallback_to_cpu_decode(self, reason: str) -> None:
        """Re-open the current media with CPU decode, keeping the Turbo window.

        §V.4's promise, applied to the decoder: the user must not lose
        playback because the *driver* could not be made to work. The MRL is
        remembered in ``_cpu_decode_override`` so replaying the same file
        later never repeats the failed attempt.
        """
        mrl = self._current_mrl
        if not mrl:
            return
        log.warning(
            "hardware decode failed (%s) — re-opening with CPU decode, "
            "Turbo output kept: %s",
            reason,
            mrl,
        )
        self._cpu_decode_override = mrl
        resume_ms, was_paused = self._capture_playback()
        self._reopen_current(resume_ms, was_paused)

    def _check_soft_decode_health(self, state: State) -> None:
        """Watchdog for Soft: video track exists but no frame ever published.

        Task 1: Auto stays Soft because file is not demanding, but Soft fails
        to generate video (shader missing, format negotiation failed, Nuitka
        callback race in 1.3.1). User sees audio only + black stage / Now
        Playing card. Detect and rescue by switching to Turbo, which uses a
        native HWND and D3D11 and can succeed where Soft's vmem path failed.

        Only arms when:
        * route is Soft
        * state is Playing
        * video_tracks() non-empty (has video, not audio-only)
        * MRL not already tried Soft->Turbo (avoid loop)
        * Turbo is available on this platform
        After _SOFT_DECODE_GRACE_S seconds with 0 frames_seen and 0 serial,
        switch to Turbo via set_video_route.
        """
        if self._video_route != video_policy.SOFT:
            self._soft_decode_pending = False
            self._soft_watch_started = None
            return
        if state != State.Playing:
            # Not playing yet — don't start timer, but keep pending if we
            # have video tracks so first Playing tick arms it.
            if state in (State.Opening, State.Buffering):
                return
            self._soft_decode_pending = False
            self._soft_watch_started = None
            return
        # Has video tracks?
        try:
            has_video_tracks = bool(self.video_tracks())
        except Exception:
            has_video_tracks = False
        if not has_video_tracks:
            # Audio-only file — never rescue to Turbo.
            self._soft_decode_pending = False
            self._soft_watch_started = None
            return
        # Avoid loop: if we already tried Soft->Turbo for this MRL, don't retry.
        mrl = self._current_mrl
        if mrl and mrl in self._soft_failed_mrls:
            self._soft_decode_pending = False
            self._soft_watch_started = None
            return
        # Turbo available?
        try:
            if not self.turbo_available():
                self._soft_decode_pending = False
                self._soft_watch_started = None
                return
        except Exception:
            pass

        now = time.monotonic()
        if not self._soft_decode_pending:
            self._soft_decode_pending = True
            self._soft_watch_started = now
            return
        if self._soft_watch_started is None:
            self._soft_watch_started = now
            return
        if now - self._soft_watch_started < _SOFT_DECODE_GRACE_S:
            return

        # Grace elapsed — did Soft produce any frame?
        try:
            vout = self.video_output
            ring = vout.ring if vout else None
            frames_seen = 0
            serial = 0
            fmt = None
            if ring is not None:
                frames_seen = ring.stats()[0]
                serial = ring.serial
                fmt = ring.format
        except Exception:
            frames_seen = 0
            serial = 0
            fmt = None

        if frames_seen > 0 or serial > 0 or fmt is not None:
            # Soft is producing — healthy.
            self._soft_decode_pending = False
            self._soft_watch_started = None
            return

        # Soft failed: video track exists but no frame published after grace.
        self._soft_decode_pending = False
        self._soft_watch_started = None
        if mrl:
            self._soft_failed_mrls.add(mrl)
            # Keep set bounded — only remember last 20 failures.
            if len(self._soft_failed_mrls) > 20:
                # pop arbitrary
                self._soft_failed_mrls.pop()
        log.warning(
            "Soft video failed to generate any frame after %.1fs "
            "(has video tracks but no picture) — switching to Turbo rescue: %s",
            _SOFT_DECODE_GRACE_S,
            mrl,
        )
        try:
            self.set_video_route(video_policy.TURBO)
        except Exception:
            log.debug("Soft->Turbo rescue failed", exc_info=True)

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
        self._timeline_tick = time.monotonic()
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
        return _describe_tracks(getattr(self._player, "video_get_track_description", lambda *args, **kwargs: None)())

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
        self._hw_decode_pending = False
        self._hw_watch_started = None
        self._soft_decode_pending = False
        self._soft_watch_started = None
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
