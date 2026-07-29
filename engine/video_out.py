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
"""

from __future__ import annotations

import ctypes
import logging
import threading
from dataclasses import dataclass
from typing import Callable

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


@dataclass(frozen=True, slots=True)
class FrameReadClaim:
    """A stable read lease for one published frame.

    ``_buffer`` is intentionally part of the claim even though consumers only
    unpack ``serial, address, format``.  A format renegotiation can replace the
    ring while Qt is copying the previous frame.  Keeping the concrete ctypes
    allocation reachable from the claim prevents that old address becoming a
    use-after-free in the render thread.
    """

    serial: int
    address: int
    format: FrameFormat
    generation: int
    _buffer: ctypes.Array

    def __iter__(self):
        # Preserve the original three-value API used by surfaces and callers.
        yield self.serial
        yield self.address
        yield self.format

    def __getitem__(self, index: int):
        return (self.serial, self.address, self.format)[index]


@dataclass(frozen=True, slots=True)
class FrameWriteClaim:
    """One buffer handed to a libVLC lock callback.

    libVLC returns the lock callback's private token to ``display``.  Carrying
    the slot and generation in that token is what lets us publish the buffer
    that was actually decoded, rather than whichever slot happens to be the
    ring's current write hint by the time display runs.
    """

    address: int
    format: FrameFormat
    index: int
    generation: int
    _buffer: ctypes.Array


class FrameRing:
    """Triple-buffered frame store, written by VLC, read by Qt.

    Thread-safety contract:

    * every mutable field, including the active format and allocation, is read
      under ``_lock``;
    * a :class:`FrameReadClaim` owns a strong reference to the exact allocation
      behind its address, so reallocation cannot invalidate an in-flight copy;
    * write claims identify the actual slot returned by ``lock`` and are
      published only if they still belong to the active ring generation;
    * pixel memory is never copied while ``_lock`` is held.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fmt: FrameFormat | None = None
        self._buffers: list[ctypes.Array] = []
        self._addresses: list[int] = []
        self._write = 0
        self._ready = -1          # newest complete slot, -1 = nothing yet
        self._read = -1           # slot pinned by reader(s), -1 = none
        self._pins = 0            # readers holding the active generation
        self._writing: set[int] = set()
        self._write_slots: list[FrameWriteClaim] = []
        self._legacy_write: FrameWriteClaim | None = None
        self._generation = 0      # increments whenever allocations are replaced
        self._serial = 0          # increments per displayed frame
        self._read_serial = 0     # serial of the pinned slot
        self._frames_seen = 0
        self._frames_dropped = 0

    # --------------------------------------------------------- allocation ---
    def allocate(self, fmt: FrameFormat) -> None:
        """Atomically replace the ring with storage for ``fmt``.

        Allocation happens before taking the bookkeeping lock.  More
        importantly, readers and VLC write callbacks receive claim objects that
        retain their old ctypes buffer.  A mid-stream format renegotiation can
        therefore swap generations immediately without freeing memory another
        thread is still reading or decoding into.
        """
        buffers = [(ctypes.c_ubyte * fmt.frame_size)() for _ in range(SLOTS)]
        addresses = [ctypes.addressof(buf) for buf in buffers]
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._fmt = fmt
            self._buffers = buffers
            self._addresses = addresses
            # Reused on every lock callback in this generation: no per-frame
            # Python claim allocation on the decode hot path.
            self._write_slots = [
                FrameWriteClaim(address, fmt, index, generation, buffers[index])
                for index, address in enumerate(addresses)
            ]
            self._write = 0
            self._ready = -1
            self._read = -1
            self._pins = 0
            self._writing.clear()
            self._legacy_write = None
            self._serial = 0
            self._read_serial = 0
        log.info("frame ring allocated: %s x%d slots", fmt.describe(), SLOTS)

    def mark_stopped(self) -> None:
        """Retire the old picture while keeping in-flight memory valid.

        Merely clearing ``_ready`` is not sufficient: an old display callback
        can arrive just after the clear and publish the dead media again.  Swap
        to a fresh generation of the same format instead.  Old read/write claim
        objects keep only the buffers they still need alive; their generation no
        longer matches, so late callbacks are harmless.  The next video can
        still produce a frame even when libVLC reuses the vout without another
        format callback.
        """
        with self._lock:
            fmt = self._fmt
        if fmt is not None:
            self.allocate(fmt)
            return
        with self._lock:
            self._generation += 1
            self._ready = -1
            self._read = -1
            self._pins = 0
            self._writing.clear()
            self._write_slots = []
            self._legacy_write = None
            self._serial = 0
            self._read_serial = 0

    def free(self) -> None:
        """Detach active storage without invalidating outstanding claims."""
        with self._lock:
            self._generation += 1
            self._buffers = []
            self._addresses = []
            self._fmt = None
            self._ready = -1
            self._read = -1
            self._pins = 0
            self._writing.clear()
            self._write_slots = []
            self._legacy_write = None
            self._serial = 0
            self._read_serial = 0

    @property
    def format(self) -> FrameFormat | None:
        with self._lock:
            return self._fmt

    # ------------------------------------------------- writer (VLC thread) ---
    def acquire_write(self) -> FrameWriteClaim | None:
        """Reserve a free slot for one libVLC ``lock`` callback.

        Address and format are captured under one lock.  The old implementation
        fetched them separately, allowing reallocation between the two reads:
        an old, smaller address could then be paired with new, larger plane
        offsets and VLC would write past the allocation.
        """
        with self._lock:
            return self._acquire_write_locked()

    def _acquire_write_locked(self) -> FrameWriteClaim | None:
        if not self._addresses or self._fmt is None:
            return None
        for step in range(SLOTS):
            candidate = (self._write + step) % SLOTS
            if candidate in self._writing:
                continue
            if candidate == self._ready:
                continue
            if self._pins and candidate == self._read:
                continue
            self._writing.add(candidate)
            self._write = (candidate + 1) % SLOTS
            return self._write_slots[candidate]
        return None

    def publish_write(self, claim: FrameWriteClaim) -> bool:
        """Publish the slot identified by ``claim`` if it is still current."""
        with self._lock:
            if claim.generation != self._generation:
                return False
            self._writing.discard(claim.index)
            if not (0 <= claim.index < len(self._addresses)):
                return False
            if self._addresses[claim.index] != claim.address:
                return False
            self._publish_index_locked(claim.index)
            return True

    def discard_write(self, claim: FrameWriteClaim) -> None:
        """Release a reservation that libVLC abandoned without displaying."""
        with self._lock:
            if claim.generation == self._generation:
                self._writing.discard(claim.index)

    # Compatibility helpers used by the pure ring tests and diagnostics.  The
    # real callback path uses acquire_write()/publish_write() so picture identity
    # is never lost between lock and display.
    def write_address(self) -> int:
        with self._lock:
            claim = self._acquire_write_locked()
            self._legacy_write = claim
            return claim.address if claim is not None else 0

    def publish(self) -> None:
        with self._lock:
            claim = self._legacy_write
            self._legacy_write = None
            # Preserve the original diagnostic shorthand: publish() by itself
            # means VLC completed the current write slot.
            if claim is None:
                claim = self._acquire_write_locked()
            if claim is None or claim.generation != self._generation:
                return
            self._writing.discard(claim.index)
            self._publish_index_locked(claim.index)

    def _publish_index_locked(self, index: int) -> None:
        if self._ready >= 0 and self._ready != self._read:
            # The previous ready frame was never consumed — Qt is rendering
            # slower than decode. Expected and harmless.
            self._frames_dropped += 1
        self._ready = index
        self._serial += 1
        self._frames_seen += 1

    # ------------------------------------------------- reader (Qt thread) ---
    def acquire_read(self) -> FrameReadClaim | None:
        """Pin and return the newest complete frame.

        The returned claim owns the concrete ctypes slot.  It remains valid even
        if a format callback replaces ``self._buffers`` before the caller has
        finished copying pixels.
        """
        with self._lock:
            if self._ready < 0 or not self._addresses or self._fmt is None:
                return None
            if self._pins == 0:
                self._read = self._ready
                self._read_serial = self._serial
            self._pins += 1
            return FrameReadClaim(
                self._read_serial,
                self._addresses[self._read],
                self._fmt,
                self._generation,
                self._buffers[self._read],
            )

    def release_read(self, claim: FrameReadClaim | None = None) -> None:
        with self._lock:
            # A reallocation resets the current generation's pin bookkeeping.
            # Releasing an old claim must not decrement a new reader's pin.
            if claim is not None and claim.generation != self._generation:
                return
            self._pins = max(0, self._pins - 1)
            if self._pins == 0:
                self._read = -1

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

    ``frame_ready`` fires on the **decoder thread**. A surface must only emit its
    queued bridge signal there; ``QQuickItem.update()`` itself is GUI-thread-only.
    Never touch Qt item state directly from this callback.
    """

    def __init__(self, chroma: str = Chroma.I420) -> None:
        self.ring = FrameRing()
        self.chroma = chroma
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

        # One private token per VLC lock callback.  libVLC passes the token back
        # to display; retaining the claim here keeps that exact allocation alive
        # through format renegotiation and lets display publish the right slot.
        self._claim_lock = threading.Lock()
        self._write_claims: dict[int, FrameWriteClaim] = {}

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
            # Deliberately empty. The write claim remains alive until display;
            # unlock only says decoding completed, not that VLC is finished
            # referring to the picture token.
            return None

        @vlc.CallbackDecorators.VideoDisplayCb
        def _display(opaque, picture):
            self._on_display(picture)

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
        """Stop serving frames, but retain C trampolines until player release.

        A stopped player state does not prove that every vout callback stack has
        returned.  Clearing a ``ctypes`` callback here used to create exactly the
        dangling C function pointer the module warns about.  The owning engine
        calls :meth:`release_callbacks` only *after* ``MediaPlayer.release()``.
        """
        self._player = None
        self._attached = False
        self.ring.free()

    def release_callbacks(self) -> None:
        """Forget callback trampolines after the native player is gone."""
        with self._claim_lock:
            claims = list(self._write_claims.values())
            self._write_claims.clear()
        for claim in claims:
            self.ring.discard_write(claim)
        self._cb_format = None
        self._cb_format_cast = None
        self._cb_cleanup = None
        self._cb_lock = None
        self._cb_unlock = None
        self._cb_display = None

    # ------------------------------------------------ reader bookkeeping ---
    def add_reader(self) -> None:
        """Register a surface. Phase 2's PiP binds a second one to the same ring
        — no second decode, no second player (§P2.5)."""
        self._readers += 1

    def remove_reader(self) -> None:
        self._readers = max(0, self._readers - 1)

    @property
    def readers(self) -> int:
        return self._readers

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
        # Cleanup is VLC's guarantee that this vout generation is no longer in
        # use. Any picture that was locked but never displayed can now be
        # released; doing this earlier would free memory a decoder still owns.
        with self._claim_lock:
            claims = list(self._write_claims.values())
            self._write_claims.clear()
        for claim in claims:
            self.ring.discard_write(claim)
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
        cb = self.video_stopped
        if cb is not None:
            try:
                cb()
            except Exception:
                log.exception("video_stopped handler failed")

    def _on_lock(self, planes) -> int:
        """Reserve a frame and return its private picture token to libVLC.

        The planes point at the reserved allocation; the return value is *not*
        a pixel pointer.  It identifies the :class:`FrameWriteClaim` and comes
        back in the display callback.  Conflating those two roles was why the
        old code published a mutable global write index rather than the frame
        VLC had actually completed.
        """
        try:
            claim = self.ring.acquire_write()
            if claim is None:
                return self._fill_scratch(planes)
            base = claim.address
            fmt = claim.format
            planes[0] = ctypes.c_void_p(base)
            if fmt.is_planar:
                planes[1] = ctypes.c_void_p(base + fmt.y_size)
                planes[2] = ctypes.c_void_p(base + fmt.y_size + fmt.uv_size)
            return self._register_write_claim(claim)
        except Exception:
            log.exception("lock callback failed")
            return self._fill_scratch(planes)

    def _register_write_claim(self, claim: FrameWriteClaim) -> int:
        # The allocation address is a valid opaque token and is unique while the
        # claim keeps that allocation alive. Reusing it avoids an extra Python
        # token allocation on every decoded frame.
        token = claim.address
        with self._claim_lock:
            self._write_claims[token] = claim
        return token

    @staticmethod
    def _picture_token(picture) -> int:
        value = getattr(picture, "value", picture)
        try:
            return int(value or 0)
        except (TypeError, ValueError, OverflowError):
            return 0

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
            # The scratch frame is deliberately never published. Its base is a
            # valid opaque token and the buffer is retained on self.
            return base
        except Exception:
            return 0

    def _on_display(self, picture=None) -> None:
        # ``None`` keeps the direct, pure-Python diagnostic path compatible;
        # native callbacks always return the private token created in _on_lock.
        if picture is None:
            self.ring.publish()
            published = True
        else:
            token = self._picture_token(picture)
            with self._claim_lock:
                found = token in self._write_claims
                claim = self._write_claims.pop(token, None)
            published = bool(found and claim is not None and self.ring.publish_write(claim))
        if not published:
            return
        cb = self.frame_ready
        if cb is not None:
            try:
                cb()
            except Exception:
                log.exception("frame_ready handler failed")
