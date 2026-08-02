"""The Phase-2 PiP notification contract — §P2.5, the black-PiP bug.

Why this file exists
--------------------
Two surfaces can bind to the same :class:`VideoOutput` (the main Stage, which
never unbinds, and the PiP window). Sharing the *pictures* was always safe —
the ring pins the same slot for every reader. But the engine originally had
only ONE slot per notification: ``frame_ready``, ``format_changed`` and
``video_stopped`` were plain attributes, so a second surface's ``bind()``
silently overwrote the main Stage's handler.

The symptoms depended on which surface won the slot:

* PiP wins  -> the main window freezes on its last frame while audio continues;
* PiP loses -> the PiP window is permanently black;
* PiP closes with its handler still registered -> the slot points at a dead
  object and *nobody* is notified for the rest of the session.

These tests pin the fan-out contract: every reader registered through
``add_reader()`` is notified on every frame/format/stop, removing one reader
leaves the others untouched, and the legacy single-slot attributes keep their
exact old behaviour. Qt-free — plain callables, no surface, no GPU.
"""

from __future__ import annotations

from engine.video_out import Chroma, FrameFormat, VideoOutput, _align_up


def make_format(width=64, height=48) -> FrameFormat:
    return FrameFormat(
        Chroma.I420,
        width,
        height,
        _align_up(width),
        _align_up(height),
        _align_up((width + 1) // 2),
        _align_up((height + 1) // 2),
    )


def make_vout() -> VideoOutput:
    vout = VideoOutput()
    vout.ring.allocate(make_format())
    return vout


def publish(vout: VideoOutput, frames: int = 1) -> None:
    """Drive the engine exactly as libVLC's ``display`` callback does."""
    for _ in range(frames):
        vout._on_display()


class Counter:
    """A callable that counts invocations — the Qt-free stand-in for a
    surface's ``frameArrived``/``formatArrived``/``videoStopped`` hops."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *_args) -> None:
        self.calls += 1


class TestFrameFanOut:
    def test_second_reader_does_not_steal_notifications(self):
        """The core of the black-PiP bug: binding a second surface must not
        disconnect the first."""
        vout = make_vout()
        stage = Counter()
        pip = Counter()

        vout.add_reader(frame=stage)
        publish(vout, 3)
        assert stage.calls == 3

        # The PiP window binds mid-playback (PipWindow.onCompleted).
        vout.add_reader(frame=pip)
        publish(vout, 3)

        assert stage.calls == 6, "main Stage must keep receiving frames"
        assert pip.calls == 3, "PiP must receive the same frames"

    def test_removing_one_reader_leaves_the_others_notified(self):
        """Closing the PiP must not freeze the main window — the bug's
        nastiest flavour: the notification slot left pointing at a dead
        surface, so nobody was told anything ever again."""
        vout = make_vout()
        stage = Counter()
        pip = Counter()

        vout.add_reader(frame=stage)
        pip_token = vout.add_reader(frame=pip)
        publish(vout, 2)

        vout.remove_reader(pip_token)      # user closes the PiP window
        publish(vout, 3)

        assert pip.calls == 2, "closed surface must not be called again"
        assert stage.calls == 5, "main Stage keeps getting every new frame"

    def test_refcount_only_registration_still_works(self):
        """The original add_reader() contract (no callbacks) stays valid."""
        vout = make_vout()
        assert vout.add_reader() is None
        vout.remove_reader()
        assert vout.readers == 0

    def test_reader_count_tracks_registered_surfaces(self):
        vout = make_vout()
        a = vout.add_reader(frame=Counter())
        b = vout.add_reader(frame=Counter())
        assert vout.readers == 2
        vout.remove_reader(a)
        assert vout.readers == 1
        vout.remove_reader(b)
        assert vout.readers == 0

    def test_legacy_single_slot_still_fires(self):
        """The attribute API the callback-robustness tests rely on is
        unchanged: it fires in addition to the readers, never instead."""
        vout = make_vout()
        legacy = Counter()
        reader = Counter()
        vout.frame_ready = legacy
        vout.add_reader(frame=reader)

        publish(vout, 2)

        assert legacy.calls == 2
        assert reader.calls == 2


class TestFormatFanOut:
    def test_all_readers_are_told_the_format_changed(self):
        vout = make_vout()
        stage = Counter()
        pip = Counter()
        vout.add_reader(format=stage)
        vout.add_reader(format=pip)

        # Drive the format callback the way libVLC's vmem.c does: a writable
        # char[5], real width/height, and pitch/line arrays to fill.
        import ctypes
        chroma = ctypes.create_string_buffer(b"I420", 5)
        w = ctypes.c_uint(1280)
        h = ctypes.c_uint(720)
        pitches = (ctypes.c_uint * 3)()
        lines = (ctypes.c_uint * 3)()
        vout._on_format(chroma, ctypes.pointer(w), ctypes.pointer(h), pitches, lines)

        assert stage.calls == 1
        assert pip.calls == 1


class TestStopFanOut:
    def test_all_readers_are_told_video_stopped(self):
        vout = make_vout()
        stage = Counter()
        pip = Counter()
        vout.add_reader(stop=stage)
        vout.add_reader(stop=pip)

        vout.notify_video_stopped()

        assert stage.calls == 1
        assert pip.calls == 1

    def test_removed_reader_is_not_told_video_stopped(self):
        vout = make_vout()
        stage = Counter()
        pip = Counter()
        vout.add_reader(stop=stage)
        token = vout.add_reader(stop=pip)
        vout.remove_reader(token)

        vout.notify_video_stopped()

        assert pip.calls == 0
        assert stage.calls == 1


class TestBrokenReaderIsolation:
    """One dead handler (a closed PiP window) must never starve the others —
    the whole reason each fan-out call is guarded individually."""

    def test_throwing_frame_handler_does_not_stop_other_readers(self):
        vout = make_vout()
        stage = Counter()
        vout.add_reader(frame=stage)

        def dead():
            raise RuntimeError("surface already deleted")

        vout.add_reader(frame=dead)

        publish(vout, 2)  # must not raise

        assert stage.calls == 2

    def test_throwing_format_handler_does_not_stop_other_readers(self):
        vout = make_vout()
        stage = Counter()
        vout.add_reader(format=stage)

        def dead(_fmt):
            raise RuntimeError("surface already deleted")

        vout.add_reader(format=dead)

        import ctypes
        chroma = ctypes.create_string_buffer(b"I420", 5)
        w = ctypes.c_uint(64)
        h = ctypes.c_uint(48)
        pitches = (ctypes.c_uint * 3)()
        lines = (ctypes.c_uint * 3)()
        vout._on_format(chroma, ctypes.pointer(w), ctypes.pointer(h), pitches, lines)

        assert stage.calls == 1

    def test_throwing_stop_handler_does_not_stop_other_readers(self):
        vout = make_vout()
        stage = Counter()
        vout.add_reader(stop=stage)

        def dead():
            raise RuntimeError("surface already deleted")

        vout.add_reader(stop=dead)

        vout.notify_video_stopped()  # must not raise

        assert stage.calls == 1
