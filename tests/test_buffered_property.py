"""The engine's ``buffered`` Q_PROPERTY (§M.4).

MiniBar binds ``player.buffered`` for the buffer fill on the seek hairline.
Before the property existed, QML read ``undefined`` and Qt logged
"Unable to assign [undefined] to double" with a dead binding. These tests pin
the contract QML depends on: a real 0..1 float, published from libVLC's cache
events, clamped, reset when the timeline resets, and present even on engines
built with ``VlcEngine.__new__`` (the teardown-test construction).
"""

from types import SimpleNamespace

from PySide6.QtCore import QObject

from engine.vlc_engine import VlcEngine


def _engine():
    """A VlcEngine with only the timeline machinery — no libVLC, no window."""
    engine = VlcEngine.__new__(VlcEngine)
    QObject.__init__(engine)
    engine._time = 0
    engine._position = 0.0
    engine._duration = 0
    engine._buffered = 0.0
    return engine


def _cache_event(percent: float) -> SimpleNamespace:
    return SimpleNamespace(u=SimpleNamespace(new_cache=percent))


def test_buffered_starts_at_zero():
    engine = _engine()
    assert engine.buffered == 0.0


def test_buffering_event_publishes_a_fraction():
    engine = _engine()
    seen = []
    engine.bufferedChanged.connect(seen.append)

    engine._on_buffering(_cache_event(50.0))

    assert engine.buffered == 0.5
    assert seen == [0.5]


def test_buffering_is_clamped_to_the_unit_interval():
    engine = _engine()
    engine._on_buffering(_cache_event(250.0))
    assert engine.buffered == 1.0

    engine._on_buffering(_cache_event(-10.0))
    assert engine.buffered == 0.0


def test_repeated_same_value_does_not_reemit():
    engine = _engine()
    seen = []
    engine.bufferedChanged.connect(seen.append)

    engine._on_buffering(_cache_event(50.0))
    engine._on_buffering(_cache_event(50.0))

    assert seen == [0.5], "the same value must not re-emit"


def test_buffering_signal_still_emits_percent():
    engine = _engine()
    seen = []
    engine.buffering.connect(seen.append)

    engine._on_buffering(_cache_event(75.0))

    assert seen == [75.0], "M3U's buffering hairline consumes the 0..100 value"


def test_a_garbage_cache_event_is_silently_ignored():
    engine = _engine()
    engine._on_buffering(SimpleNamespace(u=SimpleNamespace(new_cache=None)))
    assert engine.buffered == 0.0


def test_reset_timeline_zeroes_buffered():
    engine = _engine()
    engine._on_buffering(_cache_event(80.0))
    seen = []
    engine.bufferedChanged.connect(seen.append)

    engine._reset_timeline()

    assert engine.buffered == 0.0
    assert seen == [0.0]


def test_buffered_is_a_qml_visible_property():
    """The QML-facing contract: a float Property with a change signal."""
    prop = VlcEngine.staticMetaObject.property(
        VlcEngine.staticMetaObject.indexOfProperty("buffered")
    )
    assert prop.isValid()
    assert prop.typeName() == "double"
    assert prop.hasNotifySignal()


def test_class_level_default_survives_new_without_init():
    """Teardown tests build engines via ``__new__``; open() resets the
    timeline, so the class default must exist even without __init__."""
    engine = VlcEngine.__new__(VlcEngine)
    QObject.__init__(engine)
    engine._time = 0
    engine._position = 0.0
    engine._duration = 0

    engine._reset_timeline()  # must not raise AttributeError

    assert engine.buffered == 0.0
