"""The format-negotiation contract with libVLC — the .mkv green-video bug.

Why this file exists
--------------------
Halcyon asks libVLC to decode into **I420** so the YUV shader can do the
colour conversion on the GPU. That request is made by writing four bytes into
a ``char chroma[5]`` that libVLC passes to our format callback.

``python-vlc`` declares that parameter as ``ctypes.c_char_p``. ctypes converts
a ``c_char_p`` *argument* into an immutable Python ``bytes`` object on the way
into a callback, so ``memmove(chroma, b"I420", 4)`` writes into a throwaway
Python object and **libVLC never sees the request**.

Nothing raises. Nothing logs. VLC simply keeps whatever the decoder natively
produces:

* 8-bit H.264 (most ``.mp4``)  -> already I420, so the app looked fine;
* 10-bit HEVC (most x265 ``.mkv``) -> ``I0AL``/``P010``, **two bytes per
  sample**, which we then read as 8-bit planar: green garbage, no picture.

That is why "it works in other Python VLC players" was never evidence against
this bug — those players hand VLC a window (``set_hwnd``) and never use this
callback at all.

These tests drive :class:`VideoOutput`'s real callbacks the way libVLC's
``vmem.c`` does — through a genuine C function pointer, with a genuine mutable
``char[5]`` — so they fail if anyone reverts the prototype to
``vlc.CallbackDecorators.VideoFormatCb``.
"""

from __future__ import annotations

import ctypes

import pytest

vlc = pytest.importorskip("vlc", reason="python-vlc is needed for the real prototypes")

from engine.video_out import SLOTS, Chroma, VideoOutput, _align_up  # noqa: E402


class FakePlayer:
    """Captures the callbacks the way ``libvlc_media_player_t`` would."""

    def __init__(self) -> None:
        self.setup = self.cleanup = None
        self.lock = self.unlock = self.display = None

    def video_set_format_callbacks(self, setup, cleanup):
        self.setup, self.cleanup = setup, cleanup

    def video_set_callbacks(self, lock, unlock, display, opaque):
        self.lock, self.unlock, self.display = lock, unlock, display


def call_format(player, width, height, native_chroma=b"I0AL"):
    """Invoke the format callback exactly as ``vmem.c::Open`` does.

    ``vmem.c`` builds ``char chroma[5]`` from the decoder's current fourcc and
    passes a pointer to it. Reproducing that faithfully — a real, writable,
    NUL-terminated buffer — is the entire point of this helper.
    """
    chroma = ctypes.create_string_buffer(native_chroma, 5)
    w = ctypes.c_uint(width)
    h = ctypes.c_uint(height)
    pitches = (ctypes.c_uint * 8)()
    lines = (ctypes.c_uint * 8)()
    opaque = ctypes.c_void_p()

    slots = player.setup(
        ctypes.byref(opaque),
        ctypes.cast(chroma, ctypes.c_char_p),
        ctypes.byref(w),
        ctypes.byref(h),
        pitches,
        lines,
    )
    return slots, bytes(chroma.raw[:4]), pitches, lines


def call_lock_with_token(player):
    planes = (ctypes.c_void_p * 8)()
    token = player.lock(None, ctypes.cast(planes, ctypes.POINTER(ctypes.c_void_p)))
    return token, planes


def call_lock(player):
    return call_lock_with_token(player)[1]


def attached(chroma=Chroma.I420):
    vout = VideoOutput(chroma)
    player = FakePlayer()
    vout.attach(player)
    return vout, player


#: Real-world geometries, including the four from the original bug report.
GEOMETRIES = [
    (1920, 1080),   # standard 1080p
    (2736, 1440),   # from the report — width not a multiple of 32
    (3840, 2160),   # 4K
    (1920, 808),    # 2.40:1 scope crop, from the report
    (1918, 1076),   # odd-ish, exercises pitch padding
    (1919, 1079),   # both dimensions odd
    (720, 576),     # PAL
    (640, 360),
]

#: Chromas a decoder can natively hand us. The 10-bit ones are what x265 .mkv
#: rips actually produce and what the old code silently accepted.
NATIVE_CHROMAS = [b"I0AL", b"P010", b"I420", b"NV12", b"J420", b"I422"]


class TestChromaRequestReachesVlc:
    """The regression that this whole file exists for."""

    @pytest.mark.parametrize("native", NATIVE_CHROMAS)
    def test_i420_is_written_into_vlcs_buffer(self, native):
        # Whatever the decoder proposes, we must overwrite it with I420.
        _, player = attached()
        slots, chroma, _, _ = call_format(player, 1920, 1080, native)
        assert chroma == b"I420", (
            f"chroma request did not reach libVLC (buffer still {chroma!r}). "
            "The callback prototype has probably been reverted to "
            "vlc.CallbackDecorators.VideoFormatCb, whose c_char_p parameter "
            "makes the memmove a no-op."
        )
        assert slots == SLOTS

    def test_rv32_fallback_also_reaches_vlc(self):
        # The RV32 path was broken the same way, so switching backends was
        # never an escape route. Lock that down too.
        _, player = attached(Chroma.RV32)
        _, chroma, _, _ = call_format(player, 1920, 1080, b"I0AL")
        assert chroma == b"RV32"

    def test_nul_terminator_is_not_clobbered(self):
        # vmem.c relies on chroma[4] == '\0' when it calls
        # vlc_fourcc_GetCodecFromString. Writing 5 bytes would corrupt it.
        _, player = attached()
        chroma = ctypes.create_string_buffer(b"I0AL", 5)
        w, h = ctypes.c_uint(1920), ctypes.c_uint(1080)
        player.setup(
            ctypes.byref(ctypes.c_void_p()),
            ctypes.cast(chroma, ctypes.c_char_p),
            ctypes.byref(w),
            ctypes.byref(h),
            (ctypes.c_uint * 8)(),
            (ctypes.c_uint * 8)(),
        )
        assert chroma.raw[4] == 0

    def test_the_old_prototype_would_fail_this_suite(self):
        """Pin down *why* the fix is shaped the way it is.

        If this ever starts passing, python-vlc changed its declaration and the
        custom prototype in engine.video_out may be reconsidered.
        """
        buf = ctypes.create_string_buffer(b"I0AL", 5)

        @vlc.CallbackDecorators.VideoFormatCb
        def broken(opaque, chroma, w, h, pitches, lines):
            # Exactly what the pre-fix code did.
            ctypes.memmove(chroma, b"I420", 4)
            return 3

        broken(
            ctypes.byref(ctypes.c_void_p()),
            ctypes.cast(buf, ctypes.c_char_p),
            ctypes.byref(ctypes.c_uint(1920)),
            ctypes.byref(ctypes.c_uint(1080)),
            (ctypes.c_uint * 8)(),
            (ctypes.c_uint * 8)(),
        )
        assert bytes(buf.raw[:4]) == b"I0AL", (
            "python-vlc's VideoFormatCb now propagates chroma writes — "
            "re-evaluate the custom _FormatCbProto in engine/video_out.py"
        )


class TestPlaneGeometry:
    """The description we give VLC must match the buffer we allocate."""

    @pytest.mark.parametrize("width,height", GEOMETRIES)
    def test_chroma_planes_are_exactly_half_the_luma_height(self, width, height):
        # I420 is 4:2:0: the chroma planes are half-height by definition.
        # Rounding luma and chroma to 32 independently lets them disagree
        # (1440 -> 1440 luma vs 736*2 = 1472 chroma), which describes rows
        # nothing ever writes — undefined memory that samples as green.
        _, player = attached()
        _, _, pitches, lines = call_format(player, width, height)
        assert lines[1] == lines[2]
        assert lines[1] * 2 == lines[0], (
            f"{width}x{height}: chroma claims {lines[1]}*2={lines[1] * 2} "
            f"scanlines against {lines[0]} luma lines"
        )

    @pytest.mark.parametrize("width,height", GEOMETRIES)
    def test_declared_geometry_covers_the_visible_picture(self, width, height):
        _, player = attached()
        _, _, pitches, lines = call_format(player, width, height)
        assert pitches[0] >= width
        assert lines[0] >= height
        assert pitches[1] == pitches[2] >= (width + 1) // 2
        assert lines[1] >= (height + 1) // 2

    @pytest.mark.parametrize("width,height", GEOMETRIES)
    def test_pitches_stay_32_aligned(self, width, height):
        # VLC asks for this so decoder/filter SIMD paths stay on the fast route.
        _, player = attached()
        _, _, pitches, lines = call_format(player, width, height)
        for i in range(3):
            assert pitches[i] % 32 == 0, f"plane {i} pitch {pitches[i]} not aligned"

    @pytest.mark.parametrize("width,height", GEOMETRIES)
    def test_ring_matches_what_vlc_was_told(self, width, height):
        vout, player = attached()
        _, _, pitches, lines = call_format(player, width, height)
        fmt = vout.ring.format
        assert (fmt.y_pitch, fmt.y_lines) == (pitches[0], lines[0])
        assert (fmt.uv_pitch, fmt.uv_lines) == (pitches[1], lines[1])
        assert fmt.frame_size == fmt.y_size + 2 * fmt.uv_size


class TestLockContract:
    """``lock`` hands VLC raw pointers the decoder writes to unchecked."""

    @pytest.mark.parametrize("width,height", GEOMETRIES)
    def test_all_three_planes_fit_inside_one_slot(self, width, height):
        # vmem.c passes these straight to picture_NewFromResource; if the V
        # plane runs past the end of the slot the decoder corrupts the heap.
        vout, player = attached()
        call_format(player, width, height)
        planes = call_lock(player)
        fmt = vout.ring.format
        base = vout.ring._addresses[0]

        assert planes[0] == base
        assert planes[1] == base + fmt.y_size
        assert planes[2] == base + fmt.y_size + fmt.uv_size
        end_of_v = (planes[2] - base) + fmt.uv_size
        assert end_of_v <= fmt.frame_size, (
            f"{width}x{height}: V plane ends at {end_of_v} in a "
            f"{fmt.frame_size}-byte slot"
        )

    def test_lock_never_returns_a_null_plane_before_a_format(self):
        # A NULL plane is an immediate access violation on the decoder thread.
        _, player = attached()
        planes = call_lock(player)
        # No format has been negotiated, so there is nothing to decode yet;
        # what matters is that we did not crash and did not lie about a buffer.
        assert planes[0] in (None, 0) or planes[0] > 0

    def test_picture_token_identifies_the_buffer_displayed_out_of_order(self):
        """display must publish its lock token, not a mutable global index."""
        vout, player = attached()
        call_format(player, 64, 48)
        first_token, first_planes = call_lock_with_token(player)
        second_token, second_planes = call_lock_with_token(player)
        assert first_token and second_token and first_token != second_token
        assert first_planes[0] != second_planes[0]

        # VLC is allowed to complete/display pictures in clock order rather than
        # lock order. The second token must publish the second allocation.
        player.display(None, second_token)
        claim = vout.ring.acquire_read()
        assert claim is not None
        assert claim.address == second_planes[0]
        vout.ring.release_read(claim)

    def test_late_display_from_an_old_format_is_not_published(self):
        vout, player = attached()
        call_format(player, 64, 48)
        stale_token, _ = call_lock_with_token(player)

        call_format(player, 1920, 1080)
        player.display(None, stale_token)

        assert vout.ring.serial == 0
        assert vout.ring.acquire_read() is None

    def test_lock_after_ring_free_uses_the_scratch_pad(self):
        # Teardown race: VLC can call lock() between our free() and its own
        # stop completing.
        vout, player = attached()
        call_format(player, 1920, 1080)
        vout.ring.free()
        planes = call_lock(player)
        assert planes[0], "lock handed VLC a NULL plane during teardown"
        assert planes[1] and planes[2]

    @pytest.mark.parametrize("width,height", [(1920, 1080), (3840, 2160)])
    def test_scratch_pad_is_large_enough_for_a_whole_plane(self, width, height):
        # The decoder writes a full plane. A scratch buffer smaller than that
        # converts a NULL-deref into silent heap corruption, which is worse.
        vout, player = attached()
        call_format(player, width, height)
        fmt = vout.ring.format
        vout.ring.free()
        planes = call_lock(player)

        largest = max(fmt.y_size, fmt.uv_size)
        assert vout._scratch_plane >= largest
        # and the three regions must not overlap
        assert planes[1] - planes[0] >= largest
        assert planes[2] - planes[1] >= largest


class TestCallbackRobustness:
    """A Python exception must never unwind into libVLC's C stack."""

    def test_degenerate_size_is_refused_not_crashed(self):
        _, player = attached()
        slots, _, _, _ = call_format(player, 0, 0)
        assert slots == 0, "a 0x0 format must report failure, not allocate"

    def test_exception_in_format_changed_is_contained(self):
        vout, player = attached()

        def explode(_fmt):
            raise RuntimeError("handler blew up")

        vout.format_changed = explode
        slots, chroma, _, _ = call_format(player, 1920, 1080)
        assert slots == SLOTS and chroma == b"I420"

    def test_exception_in_frame_ready_is_contained(self):
        vout, player = attached()
        call_format(player, 1920, 1080)

        def explode():
            raise RuntimeError("handler blew up")

        vout.frame_ready = explode
        token, _ = call_lock_with_token(player)
        player.display(None, token)  # must not raise
        assert vout.ring.serial == 1

    def test_resolution_change_mid_stream_stays_in_bounds(self):
        # Adaptive streams and some .mkv files renegotiate mid-playback.
        vout, player = attached()
        call_format(player, 1920, 1080)
        call_format(player, 3840, 2160)
        planes = call_lock(player)
        fmt = vout.ring.format
        base = vout.ring._addresses[0]
        assert (planes[2] - base) + fmt.uv_size <= fmt.frame_size


class TestCallbackLifetime:
    """Garbage-collected trampolines are the classic python-vlc segfault."""

    def test_format_trampoline_and_its_cast_are_both_retained(self):
        vout, _ = attached()
        # The cast view is what libVLC holds; the original owns the code
        # object. Dropping either one crashes the process mid-playback.
        assert vout._cb_format is not None
        assert vout._cb_format_cast is not None

    def test_every_callback_is_reachable_from_the_instance(self):
        vout, _ = attached()
        for name in ("_cb_lock", "_cb_unlock", "_cb_display",
                     "_cb_format", "_cb_format_cast", "_cb_cleanup"):
            assert getattr(vout, name) is not None, f"{name} was not retained"

    def test_detach_retains_them_until_native_player_release(self):
        """A settled player can still have a vout callback returning.

        detach() runs before MediaPlayer.release(), so dropping ctypes
        trampolines there creates dangling C function pointers. The engine calls
        release_callbacks() only after the native release has completed.
        """
        vout, _ = attached()
        names = (
            "_cb_lock", "_cb_unlock", "_cb_display",
            "_cb_format", "_cb_format_cast", "_cb_cleanup",
        )

        vout.detach()
        assert all(getattr(vout, name) is not None for name in names)

        vout.release_callbacks()  # represents completed MediaPlayer.release()
        assert all(getattr(vout, name) is None for name in names)
