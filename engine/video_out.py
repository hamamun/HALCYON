"""Zero-copy video output — §0.3 / §0.4.

This module is the reason Halcyon exists in the shape it does. Everything
visual — glass over video, OSD, blurred panels, PiP — is only possible because
frames land in **our** memory instead of a native child window.

The deal with libVLC
--------------------
``libvlc_video_set_callbacks`` hands us three callbacks:

``lock``     "I need somewhere to decode into" → we return a pointer into our
             own ring buffer. **No allocation, no copy, no Python object churn.**
``unlock``   "decoded" → we do nothing at all.
``display``  "this one is complete" → we publish an integer index. Eight bytes.

VLC's decoder thread writes directly into slot A while the Qt render thread
reads slot C and slot B holds the newest complete frame. Neither thread ever
waits on the other; a ``threading.Lock`` protects **only three integers**, held
for microseconds and never during pixel work (§9 GIL-contention mitigation).

Subtitles arrive already blended: VLC composites ASS/SSA/PGS into the picture
*before* ``lock`` returns, so styled subs come through the same path for free.

I420, not RV32
--------------
1.5 bytes/px instead of 4.0 — 2.67x less bus traffic — and it is what the decoder
natively produces, so nothing forces a CPU colour-space conversion before we even
see the frame. YUV→RGB happens in a fragment shader (§0.4). ``rv32`` remains a
one-line fallback for hardware that dislikes the shader path (§9).

The chroma callback, and why it needs its own prototype
-------------------------------------------------------
``python-vlc`` declares ``VideoFormatCb``'s ``chroma`` parameter as
``ctypes.c_char_p``. When ctypes marshals a ``c_char_p`` *into* a Python
callback it does not hand over the pointer — it builds an **immutable Python
``bytes`` object** from it. ``ctypes.memmove(chroma, b"I420", 4)`` therefore
writes four bytes into a throwaway Python object and VLC's real ``char
chroma[5]`` is never touched.

The consequence is not a crash, which is why it survived so long: VLC simply
keeps whatever chroma the decoder natively produces. For 8-bit H.264 that
happens to be I420 and everything looks fine. For 10-bit HEVC — which is what
most x265 ``.mkv`` rips are — it is ``I0AL``/``P010``, i.e. **two bytes per
sample**. We then allocate an 8-bit I420 ring, hand VLC 8-bit pitches, and
interpret the result as 8-bit planar: a sheared, green picture.

(The repeated "frame ring allocated" lines in the logs are a separate, normal
thing — libVLC builds and rebuilds the vout while it settles on a size. They
are worth watching but are not by themselves a fault.)

The fix is to declare the callback ourselves with ``chroma`` typed as a raw
``c_void_p``, so ``memmove`` lands in VLC's buffer, and then ``ctypes.cast`` the
result to the type ``python-vlc``'s binding expects. See :data:`_FormatCbProto`.

Lifetime rules (learned the hard way — §9, the High-severity row)
-----------------------------------------------------------------
* The ``ctypes`` trampolines are stored on ``self``. A callback that gets garbage
  collected mid-playback is an **instant segfault**, and it is the single most
  common ``python-vlc`` crash.
* The frame memory is allocated once per format and only freed when no reader
  holds it (``_readers`` refcount) — a Phase 2 PiP window binds to the same ring
  with no second decode (§P2.5).

One engine, many surfaces (§P2.5)
---------------------------------
The engine exists to be watched by **more than one** surface: the main Stage
(which never unbinds, §9) and Phase 2's PiP window, both bound to the same
``VideoOutput``. Frames are shared through the ring, and *notifications* are
shared through :meth:`VideoOutput.add_reader` — every reader registers its own
``frame``/``format``/``stop`` callbacks and every one of them is called when a
frame lands, the format changes, or the pipeline tears down.

The original single-slot attributes (``frame_ready`` / ``format_changed`` /
``video_stopped``) are kept for simple callers — they behave exactly as before
and are what the callback-robustness tests exercise. The two paths are
independent: a reader registered via :meth:`add_reader` is notified *in
addition to* the legacy slot, never instead of it, and removing a reader never
silences the legacy slot.

**Why the fan-out matters.** Before it, a second surface's ``bind()`` simply
overwrote ``frame_ready`` with its own handler — the main Stage stopped being
told that new pictures existed the moment the PiP opened (frozen picture while
audio kept playing), and if the PiP was destroyed without anything restoring
the callback, the notification was left pointing at a dead object and *nobody*
was told anything for the rest of the session. ``add_reader`` returning a token
is what makes :meth:`VideoOutput.remove_reader` able to drop exactly one
surface, leaving every other reader — and the legacy slot — untouched.

Two further guarantees, both learned the hard way in §P2.5:

* **A late-binding reader is told the current format.** libVLC fires the
  format callback once per stream, so a PiP surface that binds after the video
  started would never learn the format — its ``isPlanar`` flag stayed false
  and the YUV shader never loaded (a permanently black PiP until the next
  pause/play or media change re-fired the callback). :meth:`VideoOutput.add_reader`
  therefore replays the ring's current format to the new reader.
* **Dead readers are pruned at dispatch time.** Closing the PiP deletes its
  ``VideoSurface`` C++ object, and PySide6 does *not* relay ``QObject.destroyed``
  to Python slots for objects the QML engine destroys — so the surface's
  unregister-on-destroy hook never runs. Without the
  :meth:`VideoOutput._callback_alive` check, every frame after the close hit
  the deleted surface and logged ``RuntimeError: Signal source has been
  deleted`` for the rest of the session. The fan-out now drops such a reader
  the first time it would be notified.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from dataclasses import dataclass
from typing import Callable

#: Used by :meth:`VideoOutput._callback_alive` to detect surfaces whose C++
#: half has been deleted (a closed PiP window). Guarded so this module keeps
#: importing in pure-Python contexts (the Qt-free engine tests).
try:
    import shiboken6
except ImportError:  # pragma: no cover - PySide6 always ships shiboken6
    shiboken6 = None

log = logging.getLogger(__name__)

#: Ring depth. Three is the minimum that lets writer and reader never block:
#: one being written, one complete and newest, one being read.
SLOTS = 3

#: VLC recommends pitches and line counts be multiples of 32 so optimised
#: decoder/filter paths do not fall off a fast path.
ALIGN = 32


def _align_up(value: int, to: int = ALIGN) -> int:
    return (value + to - 1) // to * to


#: Our own prototype for ``libvlc_video_format_cb``.
#:
#: Identical to ``python-vlc``'s ``CallbackDecorators.VideoFormatCb`` except for
#: the second parameter: ``c_void_p`` instead of ``c_char_p``. That single
#: change is what makes the chroma request actually reach libVLC — see the
#: module docstring. ``ctypes.cast`` converts the resulting function pointer to
#: the declared type at registration time, and because a cast preserves the
#: address, libVLC calls exactly this trampoline.
_FormatCbProto = ctypes.CFUNCTYPE(
    ctypes.c_uint,                    # return: number of picture buffers
    ctypes.POINTER(ctypes.c_void_p),  # opaque
    ctypes.c_void_p,                  # chroma  -> writable char[5]
    ctypes.POINTER(ctypes.c_uint),    # width
    ctypes.POINTER(ctypes.c_uint),    # height
    ctypes.POINTER(ctypes.c_uint),    # pitches[]
    ctypes.POINTER(ctypes.c_uint),    # lines[]
)


class Chroma:
    I420 = "I420"
    RV32 = "RV32"


@dataclass(frozen=True, slots=True)
class _Reader:
    """One surface's notification callbacks (§P2.5).

    Created by :meth:`VideoOutput.add_reader` and handed back as the token for
    :meth:`VideoOutput.remove_reader`. All three callbacks run on VLC's
    decoder thread — the same thread rule as the legacy single-slot
    attributes: do nothing there but marshal.
    """

    frame: Callable[[], None] | None
    format: Callable[[FrameFormat], None] | None
    stop: Callable[[], None] | None


@dataclass(frozen=True, slots=True)
class FrameFormat:
    """Geometry of the frames currently in the ring.

    ``width``/``height`` are the *visible* picture size. ``y_pitch`` etc. are the
    padded strides VLC actually writes with; a consumer must respect them or the
    picture shears.
    """

    chroma: str
    width: int
    height: int
    y_pitch: int
    y_lines: int
    uv_pitch: int = 0
    uv_lines: int = 0

    @property
    def is_planar(self) -> bool:
        return self.chroma == Chroma.I420

    @property
    def y_size(self) -> int:
        return self.y_pitch * self.y_lines

    @property
    def uv_size(self) -> int:
        return self.uv_pitch * self.uv_lines

    @property
    def frame_size(self) -> int:
        if self.is_planar:
            return self.y_size + 2 * self.uv_size
        return self.y_size

    @property
    def aspect(self) -> float:
        return (self.width / self.height) if self.height else 1.0

    def describe(self) -> str:
        return (
            f"{self.chroma} {self.width}x{self.height} "
            f"(y pitch {self.y_pitch}x{self.y_lines}, "
            f"uv pitch {self.uv_pitch}x{self.uv_lines}, "
            f"{self.frame_size / 1024:.0f} KiB/frame)"
        )


@dataclass(slots=True)
class _BufferGeneration:
    """Backing storage for one negotiated video format.

    A format callback can run while Qt is copying a frame from the preceding
    format.  The old allocation must therefore outlive the current ring state;
    ``pins`` counts leases that still refer to this exact storage generation.
    """

    fmt: FrameFormat
    buffers: list[ctypes.Array]
    addresses: list[int]
    pins: int = 0


@dataclass(frozen=True, slots=True)
class ReadClaim:
    """A pinned frame and the storage generation that owns it.

    It deliberately iterates as the historic three-tuple, so simple consumers
    can still unpack ``serial, address, fmt``.  A consumer that may span a
    format change must pass the claim to :meth:`FrameRing.release_read`.
    """

    serial: int
    address: int
    format: FrameFormat
    _generation: _BufferGeneration

    def __iter__(self):
        yield self.serial
        yield self.address
        yield self.format

    def __getitem__(self, index: int):
        return (self.serial, self.address, self.format)[index]

    def __len__(self) -> int:
        return 3


class FrameRing:
    """Triple-buffered frame store, written by VLC, read by Qt.

    Thread-safety contract:

    * ``_lock`` guards **only** ``_write``, ``_ready``, ``_read`` and ``_serial``.
    * Pixel memory is never touched while the lock is held.
    * A slot handed out by :meth:`acquire_read` is not reused as a write target
      until the reader calls :meth:`release_read`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fmt: FrameFormat | None = None
        # The current generation is the only one VLC may decode into. Retired
        # generations stay strongly referenced until every render lease that
        # points into them is returned.
        self._generation: _BufferGeneration | None = None
        self._retired: list[_BufferGeneration] = []
        self._write = 0
        self._ready = -1          # newest complete slot, -1 = nothing yet
        self._read = -1           # slot pinned by reader(s), -1 = none
        self._pins = 0            # how many readers hold _read right now
        self._serial = 0          # increments per displayed frame
        self._read_serial = 0     # serial of the pinned slot
        self._frames_seen = 0
        self._frames_dropped = 0

    # --------------------------------------------------------- allocation ---
    def allocate(self, fmt: FrameFormat) -> None:
        """Switch decoding to a freshly allocated format generation.

        This must never invalidate a frame the render thread has already
        acquired.  A vout format callback and Qt's render pass run on different
        threads; replacing a ctypes buffer list while Qt copies from one of its
        addresses is a native use-after-free and terminates the process without
        a Python traceback.  Retire, rather than discard, a pinned generation.
        """
        buffers = [(ctypes.c_ubyte * fmt.frame_size)() for _ in range(SLOTS)]
        generation = _BufferGeneration(
            fmt, buffers, [ctypes.addressof(buf) for buf in buffers]
        )
        with self._lock:
            self._retire_current_locked()
            self._generation = generation
            self._fmt = fmt
            self._write = 0
            self._ready = -1
            self._read = -1
            self._pins = 0
            self._serial = 0
            self._read_serial = 0
        log.info("frame ring allocated: %s x%d slots", fmt.describe(), SLOTS)

    def _retire_current_locked(self) -> None:
        """Keep the current backing allocation if a read lease still owns it.

        Caller holds ``_lock``.  An unpinned generation has no raw addresses in
        use and can be released by dropping the last reference immediately.
        """
        generation = self._generation
        if generation is not None and generation.pins:
            self._retired.append(generation)
        self._generation = None

    def _collect_retired_locked(self) -> None:
        self._retired = [generation for generation in self._retired if generation.pins]

    def mark_stopped(self) -> None:
        """Retire the published frame without releasing the buffers.

        Called when VLC tears the video pipeline down (end of a video track) or
        when a new media is opened. The distinction from :meth:`free` matters:
        a reader may be pinned on the render thread right now, so the memory
        must stay mapped — but the *newest complete frame* must stop being
        served, otherwise the next repaint happily re-uploads the last frame of
        the file that just finished.

        That is exactly what kept ``VideoSurface.hasVideo`` latched true after a
        video ended: ``_on_video_stopped_gui`` cleared the flag and then called
        ``update()``, whose ``updatePaintNode`` pinned the stale slot, drew it
        and set the flag straight back to true. The audio-only Now Playing card
        (album art + title/artist/album) therefore never appeared for the track
        that followed a video — while a freshly started player, whose ring has
        never held a frame, showed it correctly.
        """
        with self._lock:
            self._ready = -1
            self._serial = 0
            self._read_serial = 0

    def free(self) -> None:
        with self._lock:
            # Detach the active generation from VLC, but preserve its storage
            # until any in-flight Qt copy returns its ReadClaim.
            self._retire_current_locked()
            self._collect_retired_locked()
            self._fmt = None
            self._ready = -1
            self._read = -1
            self._pins = 0
            self._serial = 0
            self._read_serial = 0

    @property
    def format(self) -> FrameFormat | None:
        return self._fmt

    # ------------------------------------------------- writer (VLC thread) ---
    def write_address(self) -> int:
        """Base address of the slot VLC should decode into.

        Called from ``lock``. Must be allocation-free — it is on the decode hot
        path at up to 60 Hz.
        """
        with self._lock:
            generation = self._generation
            if generation is None or not generation.addresses:
                return 0
            return generation.addresses[self._write]

    def publish(self) -> None:
        """Mark the written slot complete and pick the next write target.

        Called from ``display``. This is the entire handoff: no copy, no signal
        emission from the decoder thread, just index arithmetic.
        """
        with self._lock:
            generation = self._generation
            if generation is None or not generation.addresses:
                return
            if self._ready >= 0 and self._ready != self._read:
                # The previous ready frame was never consumed — Qt is rendering
                # slower than we decode. Expected and harmless; count it so the
                # spike's HUD can show it.
                self._frames_dropped += 1
            self._ready = self._write
            self._serial += 1
            self._frames_seen += 1
            # Next write target: rotate forward to the first slot that is
            # neither the newest-complete frame nor pinned by a reader.
            # Rotating (rather than always scanning from 0) matters: it keeps
            # the writer as far as possible from whatever a reader just pinned,
            # and it exercises all SLOTS evenly instead of ping-ponging between
            # the two lowest indices.
            for step in range(1, SLOTS + 1):
                candidate = (self._ready + step) % SLOTS
                if candidate != self._ready and candidate != self._read:
                    self._write = candidate
                    break

    # ------------------------------------------------- reader (Qt thread) ---
    def acquire_read(self) -> ReadClaim | None:
        """Pin the newest complete frame and return a generation-bound claim.

        ``None`` means nothing has been displayed yet.  The claim keeps its
        *own* backing generation alive until it is supplied to
        :meth:`release_read`; this remains true if VLC negotiates a new format
        before Qt finishes copying the pixels.

        Re-entrant across readers: a second surface (Phase 2 PiP, §P2.5) pinning
        while the first still holds gets the *same* slot, so one frame is never
        split between two consumers.
        """
        with self._lock:
            generation = self._generation
            if self._ready < 0 or generation is None or self._fmt is None:
                return None
            if self._pins == 0:
                self._read = self._ready
                self._read_serial = self._serial
            self._pins += 1
            generation.pins += 1
            return ReadClaim(
                self._read_serial, generation.addresses[self._read], self._fmt, generation
            )

    def release_read(self, claim: ReadClaim | None = None) -> None:
        """Release a frame lease.

        New callers must pass the claim returned by :meth:`acquire_read`.
        The optional no-argument form remains for compatibility with simple
        same-generation callers, but cannot safely span a format change.
        """
        with self._lock:
            generation = claim._generation if claim is not None else self._generation
            if generation is None or generation.pins <= 0:
                return
            generation.pins -= 1
            if generation is self._generation:
                self._pins = max(0, self._pins - 1)
                if self._pins == 0:
                    self._read = -1
            self._collect_retired_locked()

    @property
    def serial(self) -> int:
        """Frame counter — cheap way for a consumer to test 'anything new?'."""
        with self._lock:
            return self._serial

    def stats(self) -> tuple[int, int]:
        with self._lock:
            return self._frames_seen, self._frames_dropped


class VideoOutput:
    """Binds a :class:`FrameRing` to a libVLC media player.

    Usage::

        vout = VideoOutput()
        vout.attach(player)                 # before play()
        vout.frame_ready = surface.on_frame # called from the VLC thread — be quick

    ``frame_ready`` fires on the **decoder thread**. Do nothing there but request
    a repaint (``QQuickItem.update()`` is thread-safe for this purpose via a
    queued connection). Never touch Qt objects directly.
    """

    def __init__(self, chroma: str = Chroma.I420) -> None:
        self.ring = FrameRing()
        self.chroma = chroma
        #: Legacy single-slot notifications. A simple caller that sets one of
        #: these gets exactly the old behaviour; surfaces registered through
        #: :meth:`add_reader` are notified *in addition to* these, never
        #: instead of them (§P2.5).
        self.frame_ready: Callable[[], None] | None = None
        self.format_changed: Callable[[FrameFormat], None] | None = None
        #: Fired when VLC tears the video pipeline down (end of a video track,
        #: or a track with no video at all). Lets a surface drop back to its
        #: idle state instead of leaving the last frame — or a stale
        #: ``hasVideo`` — on screen.
        self.video_stopped: Callable[[], None] | None = None

        self._player = None
        self._attached = False
        self._readers = 0
        #: Multi-reader fan-out (§P2.5): every surface's callbacks. Guarded by
        #: ``_listener_lock`` because the list is mutated on the GUI thread
        #: (bind/unbind) while the decoder thread iterates a snapshot of it.
        self._listeners: list[_Reader] = []
        self._listener_lock = threading.Lock()

        # ------------------------------------------------------------------
        # HARD REFERENCES. Do not "tidy" these into locals. §9, High severity:
        # a ctypes trampoline that is garbage collected while VLC still holds
        # its address crashes the process instantly and unhelpfully.
        # ------------------------------------------------------------------
        self._cb_lock = None
        self._cb_unlock = None
        self._cb_display = None
        self._cb_format = None
        self._cb_format_cast = None
        self._cb_cleanup = None
        self._opaque = None

        #: Landing pad for a ``lock`` that arrives when the ring is not usable
        #: (mid-reallocation, or after ``free()`` while VLC winds down).
        #:
        #: A fixed-size guess is not good enough here: the decoder writes a
        #: whole plane, so anything smaller than the current frame's largest
        #: plane turns a NULL-pointer crash into a heap corruption, which is
        #: strictly worse. It is therefore sized from the real format in
        #: :meth:`_ensure_scratch` and the three planes are given *separate*
        #: regions so a planar write cannot overlap them.
        self._scratch = None
        self._scratch_plane = 0

    # ------------------------------------------------------------- attach ---
    def attach(self, player) -> None:
        """Install the callbacks on ``player``. Call before the first ``play()``."""
        import vlc  # local import: engine modules stay importable without libVLC

        if self._attached:
            return

        # NOT vlc.CallbackDecorators.VideoFormatCb — its ``chroma`` parameter is
        # c_char_p, which ctypes converts to an immutable bytes object on the
        # way in, so the chroma we request is silently discarded (module
        # docstring). Declare it with a raw pointer, then cast to the type the
        # binding will type-check against.
        @_FormatCbProto
        def _format(opaque, chroma, width, height, pitches, lines):
            return self._on_format(chroma, width, height, pitches, lines)

        @vlc.CallbackDecorators.VideoCleanupCb
        def _cleanup(opaque):
            self._on_cleanup()

        @vlc.CallbackDecorators.VideoLockCb
        def _lock(opaque, planes):
            return self._on_lock(planes)

        @vlc.CallbackDecorators.VideoUnlockCb
        def _unlock(opaque, picture, planes):
            # Deliberately empty. Any work here runs on the decode thread and
            # delays the next frame.
            return None

        @vlc.CallbackDecorators.VideoDisplayCb
        def _display(opaque, picture):
            self._on_display()

        self._cb_format = _format
        self._cb_cleanup = _cleanup
        self._cb_lock = _lock
        self._cb_unlock = _unlock
        self._cb_display = _display
        # Keep BOTH the original trampoline (above, owns the code object) and
        # the cast view (below, what we hand to libVLC) alive for the whole
        # session. Dropping either is the classic python-vlc segfault (§9).
        self._cb_format_cast = ctypes.cast(
            self._cb_format, vlc.CallbackDecorators.VideoFormatCb
        )

        player.video_set_format_callbacks(self._cb_format_cast, self._cb_cleanup)
        player.video_set_callbacks(
            self._cb_lock, self._cb_unlock, self._cb_display, None
        )
        self._player = player
        self._attached = True
        log.info("video callbacks attached (chroma=%s)", self.chroma)

    def detach(self) -> None:
        """Drop the callbacks. Only safe once the player has fully stopped."""
        self._player = None
        self._attached = False
        # Keep the trampolines alive until VLC can no longer reach them; the
        # player release path is what guarantees that, so we clear afterwards.
        self._cb_format = None
        self._cb_format_cast = None
        self._cb_cleanup = None
        self._cb_lock = None
        self._cb_unlock = None
        self._cb_display = None
        self.ring.free()

    # ------------------------------------------------ reader bookkeeping ---
    def add_reader(
        self,
        *,
        frame: Callable[[], None] | None = None,
        format: Callable[[FrameFormat], None] | None = None,
        stop: Callable[[], None] | None = None,
    ) -> _Reader | None:
        """Register a surface (§P2.5).

        Phase 2's PiP binds a second reader to the same ring — no second
        decode, no second player. Pass the surface's callbacks and the engine
        fans every notification out to **all** readers, so the main Stage
        keeps receiving frames after the PiP binds (the single-slot
        ``frame_ready``/``format_changed``/``video_stopped`` attributes stay
        independent and keep firing for simple callers).

        **A reader that binds mid-playback is told the ring's current format
        immediately.** libVLC fires the format callback once per stream, so a
        surface that binds after the video started would otherwise never learn
        the format — its ``isPlanar`` flag would stay false and the YUV
        shader would never load (black PiP until the next format event).
        Replaying the current format on registration gives every surface the
        same starting state, whenever it attaches (§P2.5).

        Returns the reader token to hand to :meth:`remove_reader` when the
        surface goes away. With no callbacks (the original contract) this is
        a refcount-only registration and returns ``None``.
        """
        self._readers += 1
        if frame is None and format is None and stop is None:
            return None
        reader = _Reader(frame, format, stop)
        with self._listener_lock:
            self._listeners.append(reader)
        # Replay the current format to *this* reader only — the other readers
        # already know it. Runs on the caller's thread (the GUI thread for
        # VideoSurface.bind), which is exactly the thread the surface's
        # format callback expects for its bookkeeping.
        current = self.ring.format
        if current is not None and reader.format is not None:
            try:
                reader.format(current)
            except Exception:
                log.exception("format_changed handler failed")
        return reader

    def remove_reader(self, reader: _Reader | None = None) -> None:
        """Unregister a surface.

        ``reader`` is the token :meth:`add_reader` returned. Passing the
        right token drops exactly that surface — every other reader and the
        legacy single-slot attributes are untouched, which is what lets the
        main Stage keep playing after the PiP window closes (§P2.5).
        """
        self._readers = max(0, self._readers - 1)
        if reader is not None:
            with self._listener_lock:
                try:
                    self._listeners.remove(reader)
                except ValueError:
                    pass

    @property
    def readers(self) -> int:
        return self._readers

    def _listener_snapshot(self) -> list[_Reader]:
        """Copy of the reader list for decoder-thread dispatch.

        The list is mutated on the GUI thread (bind/unbind); the callbacks run
        on VLC's decoder thread. Iterating a snapshot under the lock keeps the
        two from racing on the list itself — the same GIL-atomic discipline as
        the rest of the ring's bookkeeping.
        """
        with self._listener_lock:
            return list(self._listeners)

    @staticmethod
    def _callback_alive(cb: Callable) -> bool:
        """False when ``cb`` is a bound method of a QObject whose C++ half has
        been deleted — i.e. a closed PiP window.

        The engine cannot rely on surfaces unregistering themselves:
        PySide6 does not relay ``QObject.destroyed`` to Python slots for
        objects the QML engine deletes (verified: a Loader unloading the PiP
        Window destroys the ``VideoSurface`` but the Python ``destroyed``
        slot never runs). Without this check the fan-out would call
        ``frameArrived.emit()`` on the dead surface on every frame and log
        ``RuntimeError: Signal source has been deleted`` forever (§P2.5).

        Plain callables (no ``__self__``) are always considered alive; only
        shiboken-wrapped objects can be checked. A non-shiboken ``__self__``
        is treated as alive too.
        """
        try:
            self_obj = getattr(cb, "__self__", None)
        except Exception:
            # Cannot even read the bound instance — treat as dead.
            return False
        if self_obj is None or shiboken6 is None:
            return True
        try:
            return shiboken6.isValid(self_obj)
        except Exception:
            return True

    def _notify_readers(self, attr: str, label: str, *args: object) -> None:
        """Fan a notification out to every registered reader (§P2.5).

        ``attr`` is the reader callback to invoke (``frame``/``format``/
        ``stop``) and ``label`` the log tag for failures. Each callback is
        guarded individually so one broken handler can never stop the others
        — or the C callback — from completing, and a reader whose surface
        died (closed PiP window) is **pruned** here rather than left to raise
        on every subsequent frame.
        """
        dead: list[_Reader] = []
        for reader in self._listener_snapshot():
            cb = getattr(reader, attr, None)
            if cb is None:
                continue
            if not self._callback_alive(cb):
                dead.append(reader)
                continue
            try:
                cb(*args)
            except Exception:
                log.exception("%s handler failed", label)
                # The surface may have died mid-call (teardown race). Drop it
                # now so the next frame does not hit it again.
                if not self._callback_alive(cb):
                    dead.append(reader)
        if dead:
            with self._listener_lock:
                for reader in dead:
                    try:
                        self._listeners.remove(reader)
                    except ValueError:
                        pass

    # ---------------------------------------------------------- callbacks ---
    def _on_format(self, chroma_ptr, width_ptr, height_ptr, pitches, lines) -> int:
        """Choose the decode format. Runs once per stream, on a VLC thread.

        ``chroma_ptr`` is the raw address of libVLC's ``char chroma[5]``. We
        overwrite it in place; that is the whole point of :data:`_FormatCbProto`.

        Everything here must be exception-proof. A Python traceback escaping
        into a C callback unwinds through libVLC's stack frame, and returning 0
        (or nothing) makes VLC log "video format setup failure (no pictures)"
        and abandon the video pipeline.
        """
        try:
            width = int(width_ptr[0])
            height = int(height_ptr[0])
            if width <= 0 or height <= 0:
                log.warning("format callback got %dx%d — refusing", width, height)
                return 0

            if self.chroma == Chroma.I420:
                requested = b"I420"
                # --- plane geometry -----------------------------------------
                # Both pitches and line counts stay 32-aligned: VLC explicitly
                # recommends it so decoder/filter SIMD row loops keep their
                # fast path.
                #
                # The one change from the obvious formulation is that chroma is
                # *derived from* luma rather than computed independently.
                # Rounding each to 32 on its own lets them disagree:
                #     y_lines  = align32(1440)     = 1440
                #     uv_lines = align32(1440 / 2) =  736   -> 736*2 = 1472
                # which claims 1472 chroma scanlines for a 1440-line picture.
                # In I420 the chroma planes are *by definition* exactly half
                # the luma height, so that description is simply untrue, and
                # the surplus rows are memory nothing ever writes — undefined
                # bytes that decode as bright green if anything samples them.
                #
                # Deriving one from the other makes the two mathematically
                # incapable of drifting apart, at any resolution. (align32
                # always yields a multiple of 32, so the halved value is still
                # a clean multiple of 16.)
                y_pitch = _align_up(width)
                y_lines = _align_up(height)
                uv_pitch = _align_up(y_pitch // 2)
                uv_lines = y_lines // 2
                pitches[0] = y_pitch
                pitches[1] = uv_pitch
                pitches[2] = uv_pitch
                lines[0] = y_lines
                lines[1] = uv_lines
                lines[2] = uv_lines
                fmt = FrameFormat(
                    Chroma.I420, width, height, y_pitch, y_lines, uv_pitch, uv_lines
                )
            else:
                requested = b"RV32"
                pitch = _align_up(width * 4)
                rows = height
                pitches[0] = pitch
                lines[0] = rows
                fmt = FrameFormat(Chroma.RV32, width, height, pitch, rows)

            # Write the four FourCC bytes into VLC's buffer. Only four: the
            # fifth byte is the NUL terminator VLC already put there.
            ctypes.memmove(chroma_ptr, requested, 4)

            # Size the emergency landing pad for this format *before* the ring
            # exists, so a lock arriving during the reallocation below still
            # has somewhere large enough to write.
            self._ensure_scratch(max(fmt.y_size, fmt.uv_size))
            self.ring.allocate(fmt)
        except Exception:
            log.exception("video format setup failed")
            return 0

        # Fan out to every registered reader first, then the legacy slot.
        # Each is guarded separately so one broken handler can never stop the
        # other surfaces — or the C callback — from completing, and a reader
        # whose surface died (closed PiP window) is pruned on the spot
        # (§P2.5).
        self._notify_readers("format", "format_changed", fmt)
        if self.format_changed:
            try:
                self.format_changed(fmt)
            except Exception:  # never let Python raise into a C callback
                log.exception("format_changed handler failed")
        return SLOTS

    def _on_cleanup(self) -> None:
        """VLC is done with this video format — the track ended or had no
        video. Runs on a VLC thread, so the handler must only marshal."""
        log.debug("video format cleanup")
        self.notify_video_stopped()

    def notify_video_stopped(self) -> None:
        """Retire the last frame and tell the surface there is no video.

        Also called directly by the engine when new media is opened, because
        libVLC only invokes the cleanup callback when it actually tears a video
        output down. Going from a video file to an audio file within the same
        player is not guaranteed to produce one before the audio track starts,
        which left the stale final frame of the previous video on the stage and
        suppressed the Now Playing card.
        """
        self.ring.mark_stopped()
        # Every reader must drop back to idle, not just the last one that
        # attached — a PiP window and the main Stage both have a `hasVideo`
        # flag to clear (§P2.5).
        self._notify_readers("stop", "video_stopped")
        cb = self.video_stopped
        if cb is not None:
            try:
                cb()
            except Exception:
                log.exception("video_stopped handler failed")

    def _on_lock(self, planes) -> int:
        """Hand VLC the next write slot. Hot path — keep it boring.

        Returning without filling ``planes`` is not an option: libVLC does not
        check them, it passes them straight to ``picture_NewFromResource`` and
        the decoder writes to whatever address is there. A NULL plane is an
        immediate access violation on the decoder thread, which is why the
        scratch buffer below exists rather than an early ``return 0``.
        """
        try:
            base = self.ring.write_address()
            fmt = self.ring.format
            if not base or fmt is None:
                return self._fill_scratch(planes)
            planes[0] = ctypes.c_void_p(base)
            if fmt.is_planar:
                planes[1] = ctypes.c_void_p(base + fmt.y_size)
                planes[2] = ctypes.c_void_p(base + fmt.y_size + fmt.uv_size)
            return base
        except Exception:
            log.exception("lock callback failed")
            return self._fill_scratch(planes)

    def _ensure_scratch(self, plane_bytes: int) -> None:
        """Grow the scratch pad so one plane of ``plane_bytes`` always fits.

        Three separate regions of that size are allocated, so pointing all
        three planes at the pad cannot make a planar decode write over itself.
        """
        if self._scratch is not None and self._scratch_plane >= plane_bytes:
            return
        self._scratch_plane = plane_bytes
        self._scratch = (ctypes.c_ubyte * (plane_bytes * 3))()

    def _fill_scratch(self, planes) -> int:
        """Point every plane at a throwaway buffer so a decode cannot fault.

        Used only when the ring is unavailable. The frame decoded here is never
        published, so nothing ever displays it — the only job is to give the
        decoder somewhere legal to write instead of address 0.
        """
        try:
            scratch = self._scratch
            if scratch is None:
                # No format seen yet, so no safe size is known. Returning 0
                # leaves planes NULL, but VLC has not started a decode either.
                return 0
            base = ctypes.addressof(scratch)
            stride = self._scratch_plane
            planes[0] = ctypes.c_void_p(base)
            planes[1] = ctypes.c_void_p(base + stride)
            planes[2] = ctypes.c_void_p(base + 2 * stride)
            return base
        except Exception:
            return 0

    def _on_display(self) -> None:
        self.ring.publish()
        # Fan out to every registered reader, not just the last one that
        # attached (§P2.5). Before the fan-out, a second surface's bind()
        # overwrote `frame_ready` and the main Stage stopped being told that
        # new pictures existed — black PiP or frozen main window, depending on
        # which surface won the slot. Each handler is guarded so one dead
        # surface (a closed PiP window) can never starve the others — and a
        # surface that *died* (its C++ object deleted by the QML engine when
        # the PiP closed) is pruned here, on the first frame after the close,
        # instead of raising ``Signal source has been deleted`` on every
        # frame for the rest of the session.
        self._notify_readers("frame", "frame_ready")
        cb = self.frame_ready
        if cb is not None:
            try:
                cb()
            except Exception:
                log.exception("frame_ready handler failed")
