"""The display must not blank during a film.

Windows' "turn off the display after N minutes" timer is driven by *user input*,
not by what is on screen. An hour into a film the user has, by definition, not
touched anything — so the monitor goes dark mid-scene. Drawing frames does not
help: Qt Quick rendering is invisible to the idle timer. A media player has to
call ``SetThreadExecutionState`` and say so.

These tests never touch the real Win32 API. They drive :class:`PowerGuard`
against a fake engine and assert on the *flags it decides to request*, which is
the part with the logic in it and the part that is wrong if the bug comes back.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from core.power import (
    ES_CONTINUOUS,
    ES_DISPLAY_REQUIRED,
    ES_SYSTEM_REQUIRED,
    PowerGuard,
)
from engine.vlc_engine import State


class FakeRawPlayer:
    def __init__(self, vouts: int = 0) -> None:
        self.vouts = vouts

    def has_vout(self) -> int:
        return self.vouts


class FakeEngine(QObject):
    """Just enough VlcEngine for the guard: three signals and two readings."""

    stateChanged = Signal(int)
    mediaChanged = Signal(str)
    tracksChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.state = int(State.Idle)
        self.raw_player = FakeRawPlayer()

    def set(self, state: State, vouts: int = 0) -> None:
        self.state = int(state)
        self.raw_player.vouts = vouts
        self.stateChanged.emit(self.state)


@pytest.fixture()
def guard(monkeypatch):
    """A guard whose Win32 call is replaced by a recorder.

    ``_supported`` is forced on so the decision logic is exercised on every
    platform — the tests are about which flags are chosen, and that code is
    identical everywhere.
    """
    engine = FakeEngine()
    g = PowerGuard(engine)
    g._supported = True
    calls: list[int] = []

    def fake_set_state(flags: int) -> int:
        calls.append(flags)
        return 1  # non-zero = success

    g._set_state = fake_set_state
    g._current = 0
    g.calls = calls
    g.engine = engine
    return g


# ---------------------------------------------------------------- video ---
def test_video_playback_keeps_the_display_on(guard):
    guard.engine.set(State.Playing, vouts=1)

    assert guard.calls, "playing a video must make a power request"
    flags = guard.calls[-1]
    assert flags & ES_DISPLAY_REQUIRED, "the monitor must not be allowed to blank"
    assert flags & ES_SYSTEM_REQUIRED, "nor may the machine suspend"
    assert flags & ES_CONTINUOUS, (
        "without ES_CONTINUOUS the call only nudges the idle timer once, which "
        "loses the race an hour later — the exact reported symptom"
    )


def test_the_request_is_dropped_when_playback_stops(guard):
    guard.engine.set(State.Playing, vouts=1)
    guard.calls.clear()

    guard.engine.set(State.Paused, vouts=1)

    assert guard.calls[-1] == ES_CONTINUOUS, (
        "releasing is ES_CONTINUOUS on its own; leaving the display request set "
        "means the machine never sleeps again"
    )
    assert not guard.active


def test_ended_media_releases_the_request(guard):
    guard.engine.set(State.Playing, vouts=1)
    guard.engine.set(State.Ended, vouts=0)

    assert not guard.active
    assert not guard.keeping_display_on


# ---------------------------------------------------------------- audio ---
def test_audio_keeps_the_machine_awake_but_lets_the_screen_sleep(guard):
    """An album is not a film.

    Suspending mid-track is wrong, so ES_SYSTEM_REQUIRED stands. Holding a
    1000-nit panel on for an hour of music is also wrong, and users notice the
    difference — so the display request is deliberately withheld.
    """
    guard.engine.set(State.Playing, vouts=0)

    flags = guard.calls[-1]
    assert flags & ES_SYSTEM_REQUIRED
    assert not (flags & ES_DISPLAY_REQUIRED)
    assert guard.active
    assert not guard.keeping_display_on


def test_moving_from_video_to_audio_downgrades_the_request(guard):
    guard.engine.set(State.Playing, vouts=1)
    assert guard.keeping_display_on

    guard.engine.set(State.Playing, vouts=0)   # next track is audio

    assert guard.active, "still playing, so still no suspend"
    assert not guard.keeping_display_on, "but the screen may sleep again"


def test_moving_from_audio_to_video_upgrades_the_request(guard):
    guard.engine.set(State.Playing, vouts=0)
    assert not guard.keeping_display_on

    guard.engine.set(State.Playing, vouts=1)

    assert guard.keeping_display_on


# ------------------------------------------------------------ mechanics ---
def test_an_unchanged_state_is_not_re_asserted(guard):
    """The API is sticky, so repeating the call is pure syscall noise.

    The guard is refreshed from a timer as well as from signals, so without
    this it would call into the kernel every few seconds for the whole film.
    """
    guard.engine.set(State.Playing, vouts=1)
    guard.calls.clear()

    for _ in range(5):
        guard._refresh()

    assert guard.calls == [], "no change means no call"


def test_a_failed_call_does_not_poison_the_tracked_state(guard):
    """SetThreadExecutionState returns 0 on failure.

    Recording the request anyway would leave the guard believing the display is
    protected when it is not, and — because unchanged states are skipped — it
    would never try again.
    """
    guard._set_state = lambda flags: 0

    guard.engine.set(State.Playing, vouts=1)

    assert not guard.active, "a failed request must not be remembered as held"


def test_release_drops_everything_and_stops_polling(guard):
    guard.engine.set(State.Playing, vouts=1)

    guard.release()

    assert not guard.active
    assert not guard._recheck.isActive(), "a quitting app must not keep a timer alive"


def test_release_is_idempotent(guard):
    guard.release()
    guard.calls.clear()
    guard.release()

    assert guard.calls == []


def test_a_missing_raw_player_is_not_a_crash(guard):
    """Shutdown clears the player out from under everything else."""
    guard.engine.raw_player = None

    guard._refresh()  # must not raise

    assert not guard.keeping_display_on


def test_a_throwing_has_vout_degrades_to_audio(guard):
    """Never let a libVLC hiccup take the app down from a timer callback."""

    class Angry:
        def has_vout(self):
            raise RuntimeError("player released")

    guard.engine.raw_player = Angry()
    guard.engine.set(State.Playing, vouts=0)

    assert guard.active, "still keeps the machine awake"
    assert not guard.keeping_display_on


# ------------------------------------------------- late-arriving picture ---
class SizeAwareEngine(FakeEngine):
    """A VlcEngine that also reports the decoded picture size, like the real one.

    Reproduces the real startup order: the state goes Playing before libVLC has
    a video output, and the picture (and therefore ``has_vout()``) appears a
    moment later, announced by ``videoSizeChanged``.
    """

    videoSizeChanged = Signal()

    def picture_appeared(self) -> None:
        self.raw_player.vouts = 1
        self.videoSizeChanged.emit()


def _recording_guard(engine, monkeypatch):
    g = PowerGuard(engine)
    g._supported = True
    g._current = 0
    g._set_state = lambda flags: 1
    return g


def test_the_display_request_follows_the_first_picture(monkeypatch):
    """A film must not spend its opening seconds without a display request.

    ``has_vout()`` is false for the moment between "playing" and "there is a
    picture", so a video used to start with the audio-only flags and wait for
    the 5 s re-check to upgrade them. That is a window in which Windows is
    still free to blank the screen.
    """
    engine = SizeAwareEngine()
    guard = _recording_guard(engine, monkeypatch)

    engine.set(State.Playing, vouts=0)       # decoder is up, no picture yet
    assert guard.active
    assert not guard.keeping_display_on

    engine.picture_appeared()                # ...and now there is one

    assert guard.keeping_display_on, (
        "the display request must be raised as soon as the picture exists, "
        "not up to five seconds later"
    )


def test_an_engine_without_the_size_signal_still_works(monkeypatch):
    """Older/fake engines have no ``videoSizeChanged``; that is not fatal."""
    engine = FakeEngine()
    assert not hasattr(engine, "videoSizeChanged")

    guard = _recording_guard(engine, monkeypatch)
    engine.set(State.Playing, vouts=1)

    assert guard.keeping_display_on
