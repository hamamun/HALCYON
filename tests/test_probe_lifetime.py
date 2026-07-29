"""Probe tasks must not outlive the object they report into.

Symptom: ``pytest tests`` hard-crashed with a bare ``Fatal Python error:
Segmentation fault`` roughly one run in four, traceback pointing at
``_ProbeTask._probe`` on a thread-pool thread. No test failed — the process
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
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QThreadPool

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
    model.add_paths([str(media)])
    signals = model._probe_signals

    del model
    gc.collect()

    # Touching a freed QObject raises RuntimeError; reaching the attribute at
    # all proves the C++ side is still alive.
    assert signals.cancelled is False
    signals.done.emit(str(media), 0)      # must not crash


def test_shutdown_drains_the_pool(qt_app, tmp_path):
    """Cancelling is not enough — a task can be past the flag and inside emit."""
    for i in range(8):
        (tmp_path / f"t{i}.mp3").write_bytes(b"\0" * 32)

    model = PlaylistModel()
    model.add_paths([str(p) for p in sorted(tmp_path.glob("*.mp3"))])

    model.shutdown()

    assert model._probe_signals.cancelled is True
    assert QThreadPool.globalInstance().activeThreadCount() == 0, (
        "shutdown must return with nothing still running"
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
    qt_app, monkeypatch, tmp_path
):
    """parse_with_options returns immediately; release must not race its worker."""
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

        def get_duration(self):
            order.append("duration")
            return 12_345

        def release(self):
            order.append("media-release")

    class Instance:
        def __init__(self, _args):
            self.media = Media()

        def media_new_path(self, _path):
            return self.media

        def release(self):
            order.append("instance-release")

    fake_vlc = SimpleNamespace(
        Instance=Instance,
        MediaParseFlag=SimpleNamespace(local=1),
        EventType=SimpleNamespace(MediaParsedChanged=2),
    )
    monkeypatch.setitem(sys.modules, "vlc", fake_vlc)

    path = tmp_path / "track.mp3"
    path.write_bytes(b"media")
    seen = []
    signals = _ProbeSignals()
    signals.done.connect(lambda _path, duration: seen.append(duration))

    _ProbeTask(str(path), signals)._probe()
    qt_app.processEvents()

    assert seen == [12_345]
    assert order.index("parsed") < order.index("detach")
    assert order.index("detach") < order.index("media-release")
    assert order.index("media-release") < order.index("instance-release")
