"""The Turbo boundary in the engine — §V.3 / §V.4.

The rules under test are the ones that cost the user something when they break:

* there is **one** player. Turbo re-points the existing one; it never creates a
  second player, a second decoder or an outside video window;
* the Soft path is *restored*, not merely abandoned — the vmem callbacks go back
  on and the hardware-decode option comes back off;
* every failure — unsupported platform, no handle, ``set_hwnd`` refusing, a late
  failure reported by the shell — ends with the same media playing on Soft, at
  the position it had reached;
* nothing ever leaves a native child window behind.

**Platform note.** ``set_hwnd`` is Win32. On Linux/macOS the real surface
refuses to start, which is itself one of the behaviours under test; the
lifecycle tests use ``HALCYON_TURBO_FORCE=1`` and a fake player to exercise
create/attach/tear-down without a Win32 handle. Nothing here proves that a real
HWND embeds correctly on Windows — that cannot be executed off Windows, and no
test in this repository claims otherwise.
"""

from __future__ import annotations

import sys

import pytest

from core import video_mode as vm
from engine import turbo_surface
from engine.turbo_surface import TurboSurface, is_supported
from engine.vlc_engine import VlcEngine


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------
class FakePlayer:
    """Just enough libVLC media player for the route logic."""

    def __init__(self, *, hwnd_works: bool = True) -> None:
        self.hwnd_works = hwnd_works
        self.hwnd_calls: list[int] = []
        self.stops = 0
        self.plays = 0
        self.media = None

    def set_hwnd(self, handle):
        if not self.hwnd_works:
            raise RuntimeError("libVLC was built without Win32 output support")
        self.hwnd_calls.append(int(handle))

    def stop(self):
        self.stops += 1

    def play(self):
        self.plays += 1

    def set_media(self, media):
        self.media = media

    def get_time(self):
        return 61_000

    def get_state(self):
        return 3

    def get_media(self):
        return self.media


class FakeMedia:
    def __init__(self, mrl: str) -> None:
        self.mrl = mrl
        self.options: list[str] = []

    def add_option(self, option):
        self.options.append(option)

    def parse_with_options(self, *a, **k):
        pass

    def release(self):
        pass


class FakeInstance:
    def __init__(self) -> None:
        self.created: list[FakeMedia] = []

    def media_new(self, mrl):
        media = FakeMedia(mrl)
        self.created.append(media)
        return media


class FakeVideoOutput:
    """Tracks whether the Soft callbacks are installed."""

    def __init__(self) -> None:
        self.attached = True
        self.attach_calls = 0
        self.detach_calls = 0

    def attach(self, player):
        self.attached = True
        self.attach_calls += 1

    def detach(self):
        self.attached = False
        self.detach_calls += 1

    def notify_video_stopped(self):
        pass


def _engine(*, hwnd_works=True, playing=True):
    """A VlcEngine with libVLC replaced, built without running __init__.

    Same technique as tests/test_video_teardown.py: the interesting code is the
    ordering in open()/stop()/set_video_route(), and running the real __init__
    would need a libVLC install and a window.
    """
    from PySide6.QtCore import QObject
    from engine.vlc_engine import State

    engine = VlcEngine.__new__(VlcEngine)
    # The engine emits Qt signals and parents the Turbo surface to itself, so
    # unlike test_video_teardown.py's pure open()/stop() checks this one needs
    # the QObject half constructed. Everything above it is still a fake.
    QObject.__init__(engine)
    engine._player = FakePlayer(hwnd_works=hwnd_works)
    engine._instance = FakeInstance()
    engine._media = None
    engine._vlc = None
    engine.video_output = FakeVideoOutput()
    engine._state = State.Playing if playing else State.Paused
    engine._duration = 7_200_000
    engine._position = 0.1
    engine._time = 61_000
    engine._current_mrl = "file:///uhd.mkv"
    engine._releasing = False
    engine._scrubbing = False
    engine._pending_resume_ms = 0
    engine._video_route = vm.SOFT
    engine._turbo_surface = None
    engine._media_options = []
    return engine


@pytest.fixture
def forced_turbo(monkeypatch):
    """Pretend the platform can host a native child (see the module docstring)."""
    monkeypatch.setenv("HALCYON_TURBO_FORCE", "1")
    yield


# ---------------------------------------------------------------------------
# Platform gate
# ---------------------------------------------------------------------------
def test_turbo_is_windows_only_by_default(monkeypatch):
    monkeypatch.delenv("HALCYON_TURBO_FORCE", raising=False)
    assert is_supported() is (sys.platform == "win32")


@pytest.mark.skipif(sys.platform == "win32", reason="the non-Windows refusal path")
def test_starting_turbo_off_windows_simply_refuses(monkeypatch):
    monkeypatch.delenv("HALCYON_TURBO_FORCE", raising=False)
    surface = TurboSurface()

    assert surface.start(FakePlayer()) is False
    assert surface.window is None
    assert surface.active is False


# ---------------------------------------------------------------------------
# The surface's own lifecycle
# ---------------------------------------------------------------------------
def test_the_child_window_is_opaque_black(qt_application, forced_turbo):
    """A transparent child inside Halcyon's layered shell is the desktop hole."""
    player = FakePlayer()
    surface = TurboSurface()

    assert surface.start(player) is True
    try:
        color = surface.window.color
        if callable(color):
            color = color()
        assert color.alpha() == 255
        assert color.red() == 0 and color.green() == 0 and color.blue() == 0
        opacity = surface.window.opacity
        if callable(opacity):
            opacity = opacity()
        assert opacity == 1.0
    finally:
        surface.stop(player)


def test_the_surface_creates_one_hidden_child_and_binds_it(qt_application, forced_turbo):
    player = FakePlayer()
    surface = TurboSurface()

    assert surface.start(player) is True
    try:
        assert surface.window is not None
        assert surface.handle != 0
        assert player.hwnd_calls == [surface.handle], (
            "libVLC must be pointed at exactly the window we created"
        )
        assert surface.window.isVisible() is False, (
            "the child must not be shown before WindowContainer adopts it — a "
            "visible unparented QWindow IS the outside video window §V.3 forbids"
        )
    finally:
        surface.stop(player)


def test_starting_twice_does_not_create_a_second_window(qt_application, forced_turbo):
    player = FakePlayer()
    surface = TurboSurface()
    surface.start(player)
    first = surface.window

    assert surface.start(player) is True
    try:
        assert surface.window is first
        assert len(player.hwnd_calls) == 1
    finally:
        surface.stop(player)


def test_a_refused_set_hwnd_leaves_nothing_behind(qt_application, forced_turbo):
    player = FakePlayer(hwnd_works=False)
    surface = TurboSurface()

    assert surface.start(player) is False
    assert surface.window is None, "the partially-created child must be destroyed"
    assert surface.handle == 0
    assert surface.active is False


def test_stop_unbinds_libvlc_and_destroys_the_child(qt_application, forced_turbo):
    player = FakePlayer()
    surface = TurboSurface()
    surface.start(player)

    surface.stop(player)

    assert surface.window is None
    assert player.hwnd_calls[-1] == 0, "libVLC must be told the window is gone"
    assert surface.active is False


def test_stop_is_safe_when_nothing_was_started(qt_application):
    surface = TurboSurface()
    surface.stop(FakePlayer())      # must not raise
    surface.stop()                  # …twice, and with no player at all


def test_adopting_a_foreign_handle_is_guarded(qt_application):
    assert TurboSurface.adopt(0) is None


# ---------------------------------------------------------------------------
# The engine's route switch
# ---------------------------------------------------------------------------
def test_the_engine_starts_on_soft():
    engine = _engine()
    assert engine.videoRoute == vm.SOFT


def test_switching_to_turbo_takes_the_soft_callbacks_off(qt_application, forced_turbo):
    engine = _engine()

    assert engine.set_video_route(vm.TURBO) == vm.TURBO
    try:
        assert engine.video_output.attached is False, (
            "vmem callbacks and a native window are incompatible — the green "
            "picture in BASE_VLC_ARGS' comment is what leaving both on looks like"
        )
        assert engine._turbo_surface is not None
    finally:
        engine.set_video_route(vm.SOFT)


def test_turbo_asks_for_hardware_decoding_on_this_media_only(qt_application, forced_turbo):
    engine = _engine()
    engine.set_video_route(vm.TURBO)
    try:
        media = engine._instance.created[-1]
        assert ":avcodec-hw=d3d11va" in media.options
    finally:
        engine.set_video_route(vm.SOFT)


def test_returning_to_soft_reinstalls_the_callbacks_and_drops_the_option(
    qt_application, forced_turbo
):
    engine = _engine()
    engine.set_video_route(vm.TURBO)

    assert engine.set_video_route(vm.SOFT) == vm.SOFT
    assert engine.video_output.attached is True
    assert engine._turbo_surface is None
    media = engine._instance.created[-1]
    assert not any(o.startswith(":avcodec-hw=") for o in media.options), (
        "Soft must not inherit Turbo's hardware-decode override"
    )


def test_the_switch_reuses_the_one_player(qt_application, forced_turbo):
    """§V.2: one VLC engine/player. No second player, no second decoder."""
    engine = _engine()
    player = engine._player

    engine.set_video_route(vm.TURBO)
    engine.set_video_route(vm.SOFT)

    assert engine._player is player


def test_the_switch_continues_the_same_media_where_it_was(qt_application, forced_turbo):
    engine = _engine()
    mrl = engine._current_mrl

    engine.set_video_route(vm.TURBO)

    assert engine._current_mrl == mrl, "the same media, not a new one"
    assert engine._pending_resume_ms == 61_000, (
        "playback must resume at the position it had reached (§V.4)"
    )
    engine.set_video_route(vm.SOFT)


def test_switching_route_does_not_announce_a_media_change(qt_application, forced_turbo):
    """A route switch is not a new track: no Now Playing toast, no metadata
    reload, no recent-files entry."""
    engine = _engine()
    seen: list[str] = []
    engine.mediaChanged.connect(seen.append)

    engine.set_video_route(vm.TURBO)
    engine.set_video_route(vm.SOFT)

    assert seen == []


def test_switching_to_the_route_already_in_force_does_nothing(qt_application):
    engine = _engine()
    before = engine._instance.created[:]

    assert engine.set_video_route(vm.SOFT) == vm.SOFT

    assert engine._instance.created == before, "no needless re-open"


# ---------------------------------------------------------------------------
# Failure -> Soft, playback continues (§V.4)
# ---------------------------------------------------------------------------
def test_a_failed_turbo_start_keeps_playing_on_soft(qt_application, forced_turbo):
    engine = _engine(hwnd_works=False)
    mrl = engine._current_mrl

    assert engine.set_video_route(vm.TURBO) == vm.SOFT, (
        "the engine must report the route it achieved, not the one requested"
    )
    assert engine.videoRoute == vm.SOFT
    assert engine._turbo_surface is None, "no half-built native child survives"
    assert engine.video_output.attached is True, "the Soft path is back"
    assert engine._current_mrl == mrl, "the same media is still loaded"
    assert engine._pending_resume_ms == 61_000, "…at the same position"
    assert engine._player.plays >= 1, "…and playing"


def test_an_impossible_turbo_costs_the_user_nothing(qt_application, monkeypatch):
    """No platform support is knowable *before* touching the player, so the
    request must not stop playback or re-open the media to find that out."""
    monkeypatch.delenv("HALCYON_TURBO_FORCE", raising=False)
    monkeypatch.setattr(turbo_surface, "is_supported", lambda: False)
    engine = _engine()
    opened_before = len(engine._instance.created)

    assert engine.set_video_route(vm.TURBO) == vm.SOFT
    assert engine.video_output.attached is True
    assert engine._player.stops == 0, "the player must not be stopped for nothing"
    assert len(engine._instance.created) == opened_before, "…nor the media re-opened"


def test_a_late_failure_tears_the_native_route_down(qt_application, forced_turbo):
    engine = _engine()
    engine.set_video_route(vm.TURBO)
    assert engine.videoRoute == vm.TURBO

    engine.turbo_failed("WindowContainer did not adopt the child")

    assert engine.videoRoute == vm.SOFT
    assert engine._turbo_surface is None
    assert engine.video_output.attached is True
    assert engine._current_mrl == "file:///uhd.mkv"


def test_a_late_failure_while_on_soft_is_a_no_op(qt_application):
    engine = _engine()
    engine.turbo_failed("spurious")
    assert engine.videoRoute == vm.SOFT


def test_the_route_change_is_published(qt_application, forced_turbo):
    engine = _engine()
    seen: list[str] = []
    engine.videoRouteChanged.connect(seen.append)

    engine.set_video_route(vm.TURBO)
    engine.set_video_route(vm.SOFT)

    assert seen == [vm.TURBO, vm.SOFT]


def test_a_failed_start_publishes_soft_not_turbo(qt_application, forced_turbo):
    engine = _engine(hwnd_works=False)
    seen: list[str] = []
    engine.videoRouteChanged.connect(seen.append)

    engine.set_video_route(vm.TURBO)

    assert seen == [vm.SOFT]


# ---------------------------------------------------------------------------
# No orphans (§V.4)
# ---------------------------------------------------------------------------
def test_stop_releases_the_native_child(qt_application, forced_turbo):
    """The one-tuner rule: switching to a mode that does not use the player
    calls stop(), and that must not leave a Turbo child alive."""
    engine = _engine()
    engine.set_video_route(vm.TURBO)

    engine.stop()

    assert engine._turbo_surface is None
    assert engine.videoRoute == vm.SOFT
    assert engine.video_output.attached is True


def test_a_new_media_after_a_stop_starts_from_soft(qt_application, forced_turbo):
    engine = _engine()
    engine.set_video_route(vm.TURBO)
    engine.stop()

    engine.open("file:///next.mp4")

    media = engine._instance.created[-1]
    assert not any(o.startswith(":avcodec-hw=") for o in media.options)
