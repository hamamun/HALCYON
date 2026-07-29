"""What happens to the stage when a video ends and audio follows it.

The reported bug
----------------
Play a video, let it run to the end, let the playlist advance to an audio file.
The audio plays perfectly, but the stage stays black: no album art, no title,
no artist, no album. Close the player, start it again, play the *same* audio
file first, and the Now Playing card appears exactly as it should.

That asymmetry is the whole diagnosis. A freshly started player has never had a
frame in its ring; the one that just finished a video has. So the state that
breaks the card is state left behind by the previous video, and it is read on
the path that decides ``hasVideo``.

Two independent things kept it true:

1. :class:`FrameRing` still advertised the video's final frame as the newest
   complete slot, so the very next repaint pinned it, uploaded it and set
   ``hasVideo`` back to true a moment after the teardown handler had cleared it.
2. libVLC does not reliably fire its video *cleanup* callback when the same
   player moves from a video file to an audio file — the vout is torn down
   whenever it gets round to it, sometimes after the audio is already playing.

These tests pin both halves: the ring must retire the frame, and the engine must
retire it at ``open()`` rather than waiting to be told.
"""

from __future__ import annotations

import ctypes

import pytest

from engine.video_out import Chroma, FrameFormat, FrameRing, VideoOutput


def _fmt() -> FrameFormat:
    return FrameFormat(Chroma.I420, 64, 64, 64, 64, 32, 32)


def _publish(ring: FrameRing) -> None:
    """Pretend VLC decoded and displayed one frame."""
    address = ring.write_address()
    assert address, "ring must hand out a writable slot"
    ring.publish()


# --------------------------------------------------------------------------
# 1. The ring stops serving the last frame
# --------------------------------------------------------------------------
def test_mark_stopped_retires_the_published_frame():
    ring = FrameRing()
    ring.allocate(_fmt())
    _publish(ring)

    assert ring.acquire_read() is not None, "sanity: a published frame is readable"
    ring.release_read()

    ring.mark_stopped()

    # This is the fix. Before it, the surface's next updatePaintNode pinned the
    # dead video's final frame and set hasVideo straight back to true.
    assert ring.acquire_read() is None, (
        "after the video ends the ring must serve nothing, or the stage keeps "
        "painting the last frame over the Now Playing card"
    )


def test_mark_stopped_keeps_the_buffers_mapped():
    """Retiring the frame must not be a free().

    A reader can be pinned on the render thread at this exact moment, so the
    memory has to stay valid; only the *index* is retired. Dropping the buffers
    here would be a use-after-free on the render thread rather than a missing
    album cover.
    """
    ring = FrameRing()
    ring.allocate(_fmt())
    _publish(ring)

    ring.mark_stopped()

    assert ring.format is not None, "format must survive; only the frame is retired"
    assert ring.write_address(), "buffers must stay allocated for an in-flight reader"


def test_a_new_frame_after_mark_stopped_is_served_again():
    """Retiring is not a latch — the next file's first frame must display."""
    ring = FrameRing()
    ring.allocate(_fmt())
    _publish(ring)
    ring.mark_stopped()

    _publish(ring)

    claim = ring.acquire_read()
    assert claim is not None, "the next video must still be able to show a picture"
    ring.release_read()


def test_serial_restarts_so_the_surface_does_not_skip_the_first_new_frame():
    """VideoSurface ignores a claim whose serial equals the last one it drew.

    If the serial kept counting across a teardown the numbers would still
    differ, so this is belt and braces — but a ring that reports frame 87 when
    nothing has been decoded yet is lying, and the surface is not the only
    consumer of ``serial``.
    """
    ring = FrameRing()
    ring.allocate(_fmt())
    _publish(ring)
    assert ring.serial == 1

    ring.mark_stopped()
    assert ring.serial == 0, "no frames have been published since the teardown"


# --------------------------------------------------------------------------
# 2. The teardown is actually announced
# --------------------------------------------------------------------------
def test_notify_video_stopped_retires_the_frame_and_calls_back():
    vout = VideoOutput(Chroma.I420)
    vout.ring.allocate(_fmt())
    _publish(vout.ring)

    seen: list[bool] = []
    vout.video_stopped = lambda: seen.append(True)

    vout.notify_video_stopped()

    assert seen == [True], "the surface must be told to drop back to idle"
    assert vout.ring.acquire_read() is None, "and the frame must be retired with it"


def test_notify_video_stopped_survives_a_throwing_handler():
    """The handler runs from a VLC thread on the cleanup path.

    An exception escaping into a C callback unwinds through libVLC's stack
    frame, so it is swallowed — but the ring must be retired regardless of
    which side threw.
    """
    vout = VideoOutput(Chroma.I420)
    vout.ring.allocate(_fmt())
    _publish(vout.ring)

    def boom():
        raise RuntimeError("surface already destroyed")

    vout.video_stopped = boom

    vout.notify_video_stopped()  # must not raise

    assert vout.ring.acquire_read() is None


def test_notify_video_stopped_with_no_handler_is_a_noop():
    """Nothing is bound before a surface attaches; teardown can still happen."""
    vout = VideoOutput(Chroma.I420)
    vout.ring.allocate(_fmt())
    _publish(vout.ring)

    vout.notify_video_stopped()

    assert vout.ring.acquire_read() is None


def test_cleanup_callback_routes_through_notify():
    """libVLC's own cleanup path must retire the frame too.

    This is the case that *does* fire — a video track ending cleanly. It went
    through a handler that only called back into the surface, which is why
    clearing ``hasVideo`` there was not enough on its own.
    """
    vout = VideoOutput(Chroma.I420)
    vout.ring.allocate(_fmt())
    _publish(vout.ring)

    seen: list[bool] = []
    vout.video_stopped = lambda: seen.append(True)

    vout._on_cleanup()

    assert seen == [True]
    assert vout.ring.acquire_read() is None


# --------------------------------------------------------------------------
# 3. The engine announces it when new media is opened
# --------------------------------------------------------------------------
vlc = pytest.importorskip("vlc", reason="python-vlc is needed for the engine module")


def test_engine_open_retires_the_previous_video(monkeypatch, tmp_path):
    """``open()`` must not wait for libVLC to get round to the cleanup callback.

    The whole bug is a timing one: the audio track starts, the Now Playing card
    is asked whether there is video, and libVLC has not yet torn the old vout
    down. Retiring at open() removes the race entirely — by the time any of the
    new media's state is visible, the previous picture is already gone.
    """
    from engine.vlc_engine import VlcEngine

    calls: list[str] = []

    class FakeMedia:
        def parse_with_options(self, *_a):
            pass

        def release(self):
            pass

    class FakeInstance:
        def media_new(self, _mrl):
            return FakeMedia()

    class FakePlayer:
        def set_media(self, _m):
            pass

        def play(self):
            calls.append("play")

    engine = VlcEngine.__new__(VlcEngine)  # no libVLC instance, no window
    from PySide6.QtCore import QObject

    QObject.__init__(engine)
    engine._vlc = vlc
    engine._instance = FakeInstance()
    engine._player = FakePlayer()
    engine._media = None
    engine._time = 0
    engine._position = 0.0
    engine._duration = 0
    engine._current_mrl = ""
    engine._scrubbing = False
    engine._external_subtitle_names = {}
    engine._pending_external_subtitles = []
    engine._known_spu_ids = set()

    class FakeVout:
        def notify_video_stopped(self):
            calls.append("retire")

    engine.video_output = FakeVout()

    media_file = tmp_path / "track.mp3"
    media_file.write_bytes(b"")
    engine.open(str(media_file))

    assert "retire" in calls, "the previous video must be retired when media opens"
    assert calls.index("retire") < calls.index("play"), (
        "retire before play, or the new track can start against a stale picture"
    )


def test_engine_keeps_video_trampolines_until_player_release():
    """Native callbacks may still be returning after state becomes Stopped."""
    from PySide6.QtCore import QObject

    from engine.vlc_engine import VlcEngine

    calls = []

    class Poll:
        def stop(self):
            calls.append("poll-stop")

    class Player:
        def stop(self):
            calls.append("player-stop")

        def get_state(self):
            return 5  # Stopped

        def release(self):
            calls.append("player-release")

    class Vout:
        def detach(self):
            calls.append("vout-detach")

        def release_callbacks(self):
            calls.append("callbacks-release")

    class Instance:
        def release(self):
            calls.append("instance-release")

    engine = VlcEngine.__new__(VlcEngine)
    QObject.__init__(engine)
    engine._releasing = False
    engine._poll = Poll()
    engine._player = Player()
    engine._media = None
    engine._instance = Instance()
    engine._event_manager = None
    engine.video_output = Vout()

    engine.shutdown()

    assert calls.index("vout-detach") < calls.index("player-release")
    assert calls.index("player-release") < calls.index("callbacks-release")
