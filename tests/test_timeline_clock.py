"""Resilient Local playback timeline.

libVLC's demuxer-facing time/position values are not a continuous clock. A
particular damaged/non-standard file can play pictures and sound while get_time
stays -1 or zero until the first seek. These tests pin the small fallback in
VlcEngine: prefer sane backend samples, but keep the one public timeline moving
from a monotonic clock while state is Playing.
"""

from __future__ import annotations

from PySide6.QtCore import QObject

import engine.vlc_engine as vlc_engine
from engine.vlc_engine import State, VlcEngine


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakePlayer:
    def __init__(self) -> None:
        self.state = State.Playing
        self.length = 100_000
        self.time = 0
        self.position = 0.0

    def get_state(self):
        return int(self.state)

    def get_length(self):
        return self.length

    def get_time(self):
        return self.time

    def get_position(self):
        return self.position


class FakeVideoOutput:
    pass


def _engine(clock: Clock) -> tuple[VlcEngine, FakePlayer]:
    """Build only the QObject/timeline half; no native VLC or window needed."""
    engine = VlcEngine.__new__(VlcEngine)
    QObject.__init__(engine)
    player = FakePlayer()
    engine._player = player
    engine._state = State.Playing
    engine._duration = player.length
    engine._position = 0.0
    engine._time = 0
    engine._rate = 1.0
    engine._releasing = False
    engine._scrubbing = False
    engine._pending_resume_ms = 0
    engine._timeline_tick = clock()
    engine._last_vlc_time = None
    engine._last_vlc_position = None
    engine._video_width = 0
    engine._video_height = 0
    engine.video_output = FakeVideoOutput()
    return engine, player


def _seed(engine: VlcEngine) -> None:
    """Publish the backend's initial zero samples without advancing time."""
    engine._poll_state()
    assert engine.time == 0


def test_invalid_vlc_time_no_longer_freezes_the_clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(vlc_engine.time, "monotonic", clock)
    engine, player = _engine(clock)
    player.time = -1
    player.position = -1.0

    _seed(engine)
    clock.advance(1.2)
    engine._poll_state()

    assert engine.time == 1_200
    assert abs(engine.position - 0.012) < 1e-6


def test_valid_but_stuck_zero_no_longer_freezes_the_clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(vlc_engine.time, "monotonic", clock)
    engine, _player = _engine(clock)

    _seed(engine)
    clock.advance(1.0)
    engine._poll_state()

    assert engine.time == 1_000
    assert engine.position == 0.01


def test_sane_vlc_time_takes_over_when_it_recovers(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(vlc_engine.time, "monotonic", clock)
    engine, player = _engine(clock)
    player.time = -1
    player.position = -1.0

    _seed(engine)
    clock.advance(1.0)
    engine._poll_state()
    assert engine.time == 1_000

    player.time = 1_250
    clock.advance(0.2)
    engine._poll_state()

    assert engine.time == 1_250


def test_advancing_position_is_a_safe_secondary_source(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(vlc_engine.time, "monotonic", clock)
    engine, player = _engine(clock)
    player.time = -1

    _seed(engine)
    player.position = 0.015
    clock.advance(0.2)
    engine._poll_state()

    assert engine.time == 1_500
    assert engine.position == 0.015


def test_false_end_position_from_malformed_file_is_rejected(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(vlc_engine.time, "monotonic", clock)
    engine, player = _engine(clock)
    player.time = -1

    _seed(engine)
    player.position = 1.0
    clock.advance(0.2)
    engine._poll_state()

    assert engine.time == 200
    assert engine.position == 0.002


def test_stale_pre_seek_position_cannot_yank_the_clock_back(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(vlc_engine.time, "monotonic", clock)
    engine, player = _engine(clock)
    engine._time = 80_000
    engine._position = 0.8
    player.time = -1
    player.position = 0.2

    clock.advance(0.2)
    engine._poll_state()

    assert engine.time == 80_200
    assert abs(engine.position - 0.802) < 1e-6


def test_paused_and_buffering_states_do_not_interpolate(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(vlc_engine.time, "monotonic", clock)
    engine, player = _engine(clock)
    player.time = -1
    player.position = -1.0

    for state in (State.Paused, State.Buffering):
        player.state = state
        clock.advance(2.0)
        engine._poll_state()
        assert engine.time == 0


def test_interpolation_honours_playback_rate(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(vlc_engine.time, "monotonic", clock)
    engine, player = _engine(clock)
    engine._rate = 1.5
    player.time = -1
    player.position = -1.0

    _seed(engine)
    clock.advance(1.0)
    engine._poll_state()

    assert engine.time == 1_500


def test_reset_discards_old_samples_and_wall_clock_gap(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(vlc_engine.time, "monotonic", clock)
    engine, player = _engine(clock)
    engine._time = 12_000
    engine._position = 0.12
    engine._last_vlc_time = 12_000
    engine._last_vlc_position = 0.12
    engine._buffered = 0.0

    clock.advance(30.0)
    engine._reset_timeline()
    player.time = -1
    player.position = -1.0
    engine._poll_state()

    assert engine.time == 0
    assert engine.position == 0.0
    assert engine._last_vlc_time is None
    assert engine._last_vlc_position is None
