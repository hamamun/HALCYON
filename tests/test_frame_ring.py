"""The ring buffer is the one piece of Halcyon that is genuinely concurrent, so
it is the one piece worth testing hard. These run without libVLC or a GPU.

What we are defending against:
  * a reader ever seeing a slot the writer is currently decoding into
  * torn frames (half of frame N, half of frame N+1)
  * the pin refcount leaking so the writer runs out of slots
"""

from __future__ import annotations

import ctypes
import threading

import pytest

from engine.video_out import (
    ALIGN,
    SLOTS,
    Chroma,
    FrameFormat,
    FrameRing,
    _align_up,
)


def make_format(width=64, height=48, chroma=Chroma.I420) -> FrameFormat:
    if chroma == Chroma.I420:
        return FrameFormat(
            chroma,
            width,
            height,
            _align_up(width),
            _align_up(height),
            _align_up((width + 1) // 2),
            _align_up((height + 1) // 2),
        )
    return FrameFormat(chroma, width, height, _align_up(width * 4), _align_up(height))


class TestFrameFormat:
    def test_i420_is_one_and_a_half_bytes_per_pixel(self):
        # The whole reason for choosing I420 over RV32 (§0.4).
        fmt = FrameFormat(Chroma.I420, 1920, 1080, 1920, 1080, 960, 540)
        assert fmt.frame_size == 1920 * 1080 + 2 * (960 * 540)
        assert fmt.frame_size / (1920 * 1080) == pytest.approx(1.5)

    def test_rv32_is_four_bytes_per_pixel(self):
        fmt = FrameFormat(Chroma.RV32, 1920, 1080, 1920 * 4, 1080)
        assert fmt.frame_size / (1920 * 1080) == pytest.approx(4.0)

    def test_pitches_align_to_32(self):
        # VLC asks for multiples of 32 so optimised decoder paths stay on the
        # fast route.
        fmt = make_format(1918, 1076)
        assert fmt.y_pitch % ALIGN == 0
        assert fmt.y_lines % ALIGN == 0
        assert fmt.uv_pitch % ALIGN == 0
        assert fmt.y_pitch >= 1918

    def test_aspect(self):
        assert make_format(1920, 1080).aspect == pytest.approx(16 / 9)


class TestRingBasics:
    def test_no_frame_before_first_publish(self):
        ring = FrameRing()
        ring.allocate(make_format())
        assert ring.acquire_read() is None

    def test_publish_then_read(self):
        ring = FrameRing()
        ring.allocate(make_format())
        addr = ring.write_address()
        assert addr != 0
        ring.publish()
        claim = ring.acquire_read()
        assert claim is not None
        serial, read_addr, fmt = claim
        assert serial == 1
        assert read_addr == addr
        ring.release_read()

    def test_writer_never_hands_out_the_pinned_slot(self):
        """The core safety property: while Qt is uploading slot X, VLC must be
        given some other slot to decode into."""
        ring = FrameRing()
        ring.allocate(make_format())
        ring.publish()
        _, pinned, _ = ring.acquire_read()
        for _ in range(20):
            write_addr = ring.write_address()
            assert write_addr != pinned, "writer was handed the slot being read"
            ring.publish()
        ring.release_read()

    def test_serial_increments_per_frame(self):
        ring = FrameRing()
        ring.allocate(make_format())
        for expected in range(1, 6):
            ring.write_address()
            ring.publish()
            claim = ring.acquire_read()
            assert claim[0] == expected
            ring.release_read()

    def test_second_reader_sees_the_same_slot(self):
        """Phase 2's PiP pins the same ring; both surfaces must agree on which
        frame they are showing (§P2.5)."""
        ring = FrameRing()
        ring.allocate(make_format())
        ring.publish()
        first = ring.acquire_read()
        ring.publish()  # a newer frame lands while reader 1 still holds
        second = ring.acquire_read()
        assert first[0] == second[0]
        assert first[1] == second[1]
        ring.release_read()
        ring.release_read()

    def test_pin_released_only_when_all_readers_release(self):
        ring = FrameRing()
        ring.allocate(make_format())
        ring.publish()
        _, pinned, _ = ring.acquire_read()
        ring.acquire_read()
        ring.release_read()
        # one reader still holds it
        for _ in range(6):
            assert ring.write_address() != pinned
            ring.publish()
        ring.release_read()

    def test_free_then_read_is_safe(self):
        ring = FrameRing()
        ring.allocate(make_format())
        ring.publish()
        ring.free()
        assert ring.acquire_read() is None
        assert ring.write_address() == 0

    def test_reallocate_resets_state(self):
        """Resolution change mid-stream (Milestone 1.1)."""
        ring = FrameRing()
        ring.allocate(make_format(640, 480))
        ring.publish()
        ring.allocate(make_format(1920, 1080))
        assert ring.acquire_read() is None
        assert ring.format.width == 1920

    def test_slot_addresses_are_distinct(self):
        ring = FrameRing()
        fmt = make_format()
        ring.allocate(fmt)
        seen = set()
        for _ in range(SLOTS):
            seen.add(ring.write_address())
            ring.publish()
        assert len(seen) == SLOTS


class TestConcurrency:
    def test_no_torn_frames_under_load(self):
        """Writer stamps every byte of its slot with a frame id; reader checks
        the whole plane carries a single id. A torn read means the pin logic is
        broken."""
        ring = FrameRing()
        fmt = make_format(32, 32)
        ring.allocate(fmt)

        stop = threading.Event()
        errors: list[str] = []
        frames_checked = 0

        def writer():
            frame_id = 0
            while not stop.is_set():
                frame_id = (frame_id + 1) % 251
                addr = ring.write_address()
                if addr:
                    ctypes.memset(addr, frame_id, fmt.frame_size)
                ring.publish()

        def reader():
            nonlocal frames_checked
            while not stop.is_set():
                claim = ring.acquire_read()
                if claim is None:
                    continue
                try:
                    _, addr, f = claim
                    buf = (ctypes.c_ubyte * f.frame_size).from_address(addr)
                    first = buf[0]
                    # sample across the frame rather than every byte, for speed
                    step = max(1, f.frame_size // 512)
                    for i in range(0, f.frame_size, step):
                        if buf[i] != first:
                            errors.append(f"torn frame at byte {i}")
                            return
                    frames_checked += 1
                finally:
                    ring.release_read()

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.daemon = True
            t.start()
        stop.wait(2.0)
        stop.set()
        for t in threads:
            t.join(timeout=2.0)

        assert not errors, errors[:3]
        assert frames_checked > 10, f"reader only saw {frames_checked} frames"

    def test_many_readers_do_not_deadlock(self):
        ring = FrameRing()
        ring.allocate(make_format(16, 16))
        stop = threading.Event()

        def writer():
            while not stop.is_set():
                ring.write_address()
                ring.publish()

        def reader():
            while not stop.is_set():
                if ring.acquire_read() is not None:
                    ring.release_read()

        threads = [threading.Thread(target=writer, daemon=True)]
        threads += [threading.Thread(target=reader, daemon=True) for _ in range(4)]
        for t in threads:
            t.start()
        stop.wait(1.0)
        stop.set()
        for t in threads:
            t.join(timeout=2.0)
            assert not t.is_alive(), "thread did not finish — probable deadlock"

        seen, _dropped = ring.stats()
        assert seen > 100
