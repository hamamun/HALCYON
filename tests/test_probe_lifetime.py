"""Probe tasks must not outlive the object they report into.

Symptom: ``pytest tests`` hard-crashed with a bare ``Fatal Python error:
Segmentation fault`` roughly one run in four, traceback pointing at a duration
probe on a thread-pool thread. No test failed — the process
simply died, sometimes before the summary line, so a green run meant nothing.

Cause: ``_ProbeSignals`` was parented to the ``PlaylistModel``. Qt destroys a
child with its parent, so a model collected while probes were still queued left
those tasks holding a Python wrapper around a freed C++ QObject. The next
``done.emit`` wrote through a dangling pointer. That is a segfault, not a
catchable ``RuntimeError``, so the existing ``except RuntimeError`` around the
emit could not help.

Fix: leave the signals object unparented so its lifetime is Python's — each
in-flight task holds a reference — and drain the pool in ``shutdown``.

The crash is timing-dependent, so these tests pin the two structural properties
that made it possible rather than trying to race it.
"""

from __future__ import annotations

import gc
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QObject

from modes.local.playlist import PlaylistModel, _ProbeSignals, _ProbeTask


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


def test_the_signals_object_is_not_parented_to_the_model(qt_app):
    """The whole bug in one assertion."""
    model = PlaylistModel()

    assert model._probe_signals.parent() is None, (
        "parenting it to the model makes Qt free it while pool threads can "
        "still emit through it — a segfault, not an exception"
    )


def test_the_signals_object_outlives_the_model(qt_app, tmp_path):
    """A task holding the signals must still find a live object after the
    model has gone."""
    media = tmp_path / "a.mp3"
    media.write_bytes(b"\0" * 32)

    model = PlaylistModel()
    signals = model._probe_signals
    # The task, not Qt parenting, owns the signal bridge while it may emit.
    task = _ProbeTask(str(media), signals, lambda *_args: 0)

    del model
    gc.collect()

    # Touching a freed QObject raises RuntimeError; reaching the attribute at
    # all proves the C++ side is still alive.
    assert signals.cancelled is False
    signals.done.emit(str(media), 0)      # must not crash
    assert task._signals is signals


def test_shutdown_drains_the_pool(qt_app, tmp_path):
    """Cancelling is not enough — a task can be past the flag and inside emit."""
    for i in range(8):
        (tmp_path / f"t{i}.mp3").write_bytes(b"\0" * 32)

    def probe(_path, cancellation):
        # Stay alive briefly so shutdown exercises cancellation + pool drain.
        for _ in range(20):
            if cancellation.cancelled:
                return 0
            time.sleep(0.005)
        return 123

    model = PlaylistModel(duration_probe=probe)
    model.add_paths([str(p) for p in sorted(tmp_path.glob("*.mp3"))])

    model.shutdown()

    assert model._probe_signals.cancelled is True
    assert model._pool.activeThreadCount() == 0, (
        "shutdown must return with no playlist probe still running"
    )


def test_shutdown_is_safe_to_call_twice(qt_app):
    model = PlaylistModel()
    model.shutdown()
    model.shutdown()


def test_a_probe_signals_object_can_be_built_standalone(qt_app):
    """It takes no parent argument any more; nothing may pass one."""
    signals = _ProbeSignals()

    assert signals.parent() is None


def test_probe_waits_for_async_parse_before_releasing_native_objects(
    qt_app, tmp_path
):
    """The engine owns Media until the parser's completion callback."""
    from engine.vlc_engine import VlcEngine

    order = []

    class EventManager:
        def event_attach(self, event_type, callback):
            order.append("attach")
            self.callback = callback

        def event_detach(self, event_type, callback):
            assert callback is self.callback
            order.append("detach")

    class Media:
        def __init__(self):
            self.manager = EventManager()

        def event_manager(self):
            return self.manager

        def parse_with_options(self, *_args):
            order.append("parse")
            self.manager.callback(object())
            order.append("parsed")
            return 0

        def get_parsed_status(self):
            return 4

        def get_duration(self):
            order.append("duration")
            return 12_345

        def release(self):
            order.append("media-release")

    class Instance:
        def __init__(self):
            self.media = Media()

        def media_new_path(self, _path):
            order.append("media-new")
            return self.media

    engine = VlcEngine.__new__(VlcEngine)
    QObject.__init__(engine)
    engine._instance = Instance()
    engine._vlc = SimpleNamespace(
        MediaParseFlag=SimpleNamespace(local=1),
        EventType=SimpleNamespace(MediaParsedChanged=2),
    )
    engine._releasing = False
    engine._deferred_probe_media = []
    import threading
    engine._deferred_probe_lock = threading.Lock()

    path = tmp_path / "track.mp3"
    path.write_bytes(b"media")
    duration = engine.probe_duration(str(path))

    assert duration == 12_345
    assert order.index("parsed") < order.index("duration")
    assert order.index("duration") < order.index("detach")
    assert order.index("detach") < order.index("media-release")
    assert engine._deferred_probe_media == []


def test_probe_task_delegates_without_constructing_a_vlc_instance(qt_app, tmp_path):
    path = tmp_path / "queued.flac"
    path.write_bytes(b"media")
    calls = []
    signals = _ProbeSignals()
    seen = []
    signals.done.connect(lambda media, duration: seen.append((media, duration)))

    def probe(media, cancellation):
        calls.append((media, cancellation))
        return 9_876

    _ProbeTask(str(path), signals, probe).run()
    qt_app.processEvents()

    assert calls == [(str(path), signals)]
    assert seen == [(str(path), 9_876)]


def test_first_auto_played_row_is_not_probed_in_parallel(qt_app, tmp_path):
    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"
    first.write_bytes(b"media")
    second.write_bytes(b"media")
    calls = []

    model = PlaylistModel(duration_probe=lambda path, _cancel: calls.append(path) or 1)
    model.add_paths([str(first), str(second)])
    model._pool.waitForDone(1000)
    model.shutdown()

    assert calls == [str(second)]


def test_media_open_starts_one_parse_and_metadata_only_reads_it(qt_app, tmp_path):
    """Metadata retries must not launch overlapping parses during decoder start."""
    from core.metadata import Metadata
    from engine.vlc_engine import VlcEngine

    parse_calls = []

    class Media:
        def parse_with_options(self, flags, timeout):
            parse_calls.append((flags, timeout))
            return 0

        def get_meta(self, _key):
            return None

        def get_duration(self):
            return 0

        def release(self):
            pass

    media = Media()

    class Instance:
        def media_new(self, _mrl):
            return media

    class Player:
        def set_media(self, value):
            self.media = value

        def get_media(self):
            return self.media

        def play(self):
            pass

    class Vout:
        def notify_video_stopped(self):
            pass

    engine = VlcEngine.__new__(VlcEngine)
    QObject.__init__(engine)
    engine._instance = Instance()
    engine._player = Player()
    engine._vlc = SimpleNamespace(
        MediaParseFlag=SimpleNamespace(
            local=SimpleNamespace(value=1),
            fetch_local=SimpleNamespace(value=2),
        )
    )
    engine.video_output = Vout()
    engine._media = None
    engine._time = 0
    engine._position = 0.0
    engine._duration = 0
    engine._current_mrl = ""
    engine._scrubbing = False
    engine._external_subtitle_names = {}
    engine._pending_external_subtitles = []
    engine._known_spu_ids = set()

    metadata = Metadata(engine)
    engine.mediaChanged.connect(metadata.load)
    path = tmp_path / "one.flac"
    path.write_bytes(b"media")

    engine.open(str(path))

    assert parse_calls == [(3, 3000)]
    # Invalidate the bounded retry timers before another test processes events.
    metadata.load("")
