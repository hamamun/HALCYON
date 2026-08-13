"""Who decides the video route, and what happens when Turbo fails — §V.2/§V.4.

``test_video_mode_policy.py`` proves the *rule*; this file proves the rule is
actually wired to the player. It drives the real :class:`core.app.AppController`
against a fake engine, because the interesting behaviour is a sequence — media
opens, metadata lands, the mode changes, Mini Mode toggles — and each step must
put the one player on the right route.

The fake engine is deliberately thin: it records the routes it was asked for and
can be told to refuse Turbo, which is exactly what a real failing ``set_hwnd``
looks like from up here (the engine's own fallback is covered in
``test_turbo_surface.py``).
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from core import video_mode as vm
from core.app import AppController


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------
class FakeEngine(QObject):
    stateChanged = Signal(int)
    mediaChanged = Signal(str)
    endReached = Signal()
    timeChanged = Signal(int)
    tracksChanged = Signal()
    videoRouteChanged = Signal(str)

    def __init__(self, *, turbo_works: bool = True) -> None:
        super().__init__()
        self.turbo_works = turbo_works
        self.videoRoute = vm.SOFT
        self.currentMedia = ""
        self.requested: list[str] = []
        self.stopped = 0
        #: What libVLC would report once it has selected tracks. Empty means
        #: "not known yet", which is the state during the first instant of
        #: every open — not the same thing as "audio only".
        self._video_track_list: list[tuple[int, str]] = []
        self._audio_track_list: list[tuple[int, str]] = []

    def video_tracks(self):
        return list(self._video_track_list)

    def audio_tracks(self):
        return list(self._audio_track_list)

    def subtitle_tracks(self):
        return []

    def current_audio_track(self):
        return self._audio_track_list[0][0] if self._audio_track_list else -1

    def current_subtitle_track(self):
        return -1

    def announce_tracks(self, *, video: bool, audio: bool = True) -> None:
        """Publish a track list the way libVLC does, a beat after the open."""
        self._video_track_list = [(0, "Video 1")] if video else []
        self._audio_track_list = [(1, "Audio 1")] if audio else []
        self.tracksChanged.emit()

    # -- the API the controller uses --------------------------------------
    def set_video_route(self, route: str) -> str:
        self.requested.append(route)
        if route == vm.TURBO and not self.turbo_works:
            self.videoRoute = vm.SOFT          # what a real fallback leaves
        else:
            self.videoRoute = route
        self.videoRouteChanged.emit(self.videoRoute)
        return self.videoRoute

    def turbo_failed(self, reason: str = "") -> None:
        self.videoRoute = vm.SOFT
        self.videoRouteChanged.emit(self.videoRoute)

    def stop(self) -> None:
        self.stopped += 1

    def __getattr__(self, name):        # everything else is a no-op
        return lambda *a, **k: None


class FakeMetadata(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.videoDetails: list[dict] = []
        # The real Metadata reports False for both "audio only" and "not read
        # yet"; hasAudio is what distinguishes them, so the double carries the
        # same pair rather than a tidier tri-state the app does not have.
        self.hasVideo = False
        self.hasAudio = False

    def load(self, path: str) -> None:
        pass

    def describe(self, width, height, fps) -> None:
        """Publish geometry the way the real Info rows do, then notify."""
        self.videoDetails = [
            {"label": "Resolution", "value": f"{width}\u00d7{height}"},
            {"label": "Frame rate", "value": f"{fps} fps"},
        ]
        self.hasVideo = True
        self.hasAudio = True
        self.changed.emit()

    def describe_audio_only(self) -> None:
        """A finished parse that found audio and no video at all."""
        self.videoDetails = []
        self.hasVideo = False
        self.hasAudio = True
        self.changed.emit()


class FakeSettings(QObject):
    def __init__(self, values: dict | None = None) -> None:
        super().__init__()
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def get_mode(self, mode_id, key, default=None):
        return default

    def set_mode(self, mode_id, key, value):
        pass


class Inert(QObject):
    def __getattr__(self, name):
        return lambda *a, **k: None


def _controller(qt_application, *, mode="local", turbo_works=True, stored="auto"):
    engine = FakeEngine(turbo_works=turbo_works)
    metadata = FakeMetadata()
    settings = FakeSettings({"ui.mode": mode, "playback.videoMode": stored})
    controller = AppController(
        engine, settings, Inert(), metadata, Inert(), Inert(), None
    )
    return controller, engine, metadata, settings


def _settle(qt_application):
    """The route switch is applied on the next event-loop turn — by design, so
    it never re-enters engine.open() from inside a mediaChanged handler."""
    from PySide6.QtCore import QCoreApplication, QEventLoop

    QCoreApplication.processEvents(QEventLoop.AllEvents, 50)


# ---------------------------------------------------------------------------
# Local
# ---------------------------------------------------------------------------
def test_local_auto_stays_soft_for_ordinary_media(qt_application):
    controller, engine, metadata, _ = _controller(qt_application)
    engine.currentMedia = "file:///film.mkv"

    controller._on_media_changed("file:///film.mkv")
    metadata.describe(1920, 1080, 24)
    _settle(qt_application)

    assert engine.videoRoute == vm.SOFT
    assert vm.TURBO not in engine.requested


def test_local_auto_upgrades_to_turbo_for_demanding_media(qt_application):
    controller, engine, metadata, _ = _controller(qt_application)
    engine.currentMedia = "file:///uhd.mkv"

    controller._on_media_changed("file:///uhd.mkv")
    _settle(qt_application)
    assert engine.videoRoute == vm.SOFT, (
        "before metadata lands the answer must be the safe one"
    )

    metadata.describe(3840, 2160, 60)
    _settle(qt_application)

    assert engine.videoRoute == vm.TURBO
    assert controller.effectiveVideoMode == "turbo"


def test_local_auto_upgrades_from_live_player_size(qt_application):
    """§V.2: Auto must not depend on the Info-panel parse alone.

    libVLC often has no container geometry on open. Once the decoder is
    up, ``video_get_size`` knows the real picture — that is enough to
    promote a 4K file to Turbo even if metadata never filled the rows.
    """
    from engine.vlc_engine import State

    controller, engine, _metadata, _ = _controller(qt_application)
    engine.currentMedia = "file:///uhd.mkv"
    size = {"wh": (0, 0), "fps": 0.0}
    engine.video_size = lambda: size["wh"]
    engine.video_fps = lambda: size["fps"]

    controller._on_media_changed("file:///uhd.mkv")
    _settle(qt_application)
    assert engine.videoRoute == vm.SOFT

    size["wh"] = (3840, 2160)
    size["fps"] = 60.0
    engine.stateChanged.emit(int(State.Playing))
    _settle(qt_application)

    assert engine.videoRoute == vm.TURBO
    assert controller.effectiveVideoMode == "turbo"


def test_local_auto_reads_ascii_x_resolution(qt_application):
    """Info rows sometimes use 'x' rather than the multiplication sign."""
    controller, engine, metadata, _ = _controller(qt_application)
    engine.currentMedia = "file:///uhd.mkv"

    controller._on_media_changed("file:///uhd.mkv")
    metadata.videoDetails = [
        {"label": "Resolution", "value": "3840x2160"},
        {"label": "Frame rate", "value": "60 fps"},
    ]
    metadata.hasVideo = True
    metadata.hasAudio = True
    metadata.changed.emit()
    _settle(qt_application)

    assert engine.videoRoute == vm.TURBO


def test_forced_turbo_needs_no_metadata(qt_application):
    controller, engine, metadata, _ = _controller(qt_application, stored="turbo")
    engine.currentMedia = "file:///anything.mp4"

    controller._on_media_changed("file:///anything.mp4")
    _settle(qt_application)

    assert engine.videoRoute == vm.TURBO


def test_forced_soft_never_upgrades(qt_application):
    controller, engine, metadata, _ = _controller(qt_application, stored="soft")
    engine.currentMedia = "file:///uhd.mkv"

    controller._on_media_changed("file:///uhd.mkv")
    metadata.describe(3840, 2160, 60)
    _settle(qt_application)

    assert engine.videoRoute == vm.SOFT
    assert vm.TURBO not in engine.requested


def test_choosing_a_mode_persists_it_without_switching_now(qt_application):
    """The dropdown only saves. A live switch would bury Settings under HWND."""
    controller, engine, _, settings = _controller(qt_application)
    engine.currentMedia = "file:///film.mkv"
    controller._on_media_changed("file:///film.mkv")
    _settle(qt_application)
    assert engine.videoRoute == vm.SOFT
    engine.requested.clear()

    controller.setVideoMode("turbo")
    _settle(qt_application)

    assert settings.values["playback.videoMode"] == "turbo"
    assert controller.videoMode == "turbo"
    assert engine.videoRoute == vm.SOFT
    assert vm.TURBO not in engine.requested


def test_choosing_turbo_applies_when_the_next_video_starts(qt_application):
    controller, engine, _, settings = _controller(qt_application)
    engine.currentMedia = "file:///film.mkv"
    controller._on_media_changed("file:///film.mkv")
    _settle(qt_application)
    controller.setVideoMode("turbo")
    _settle(qt_application)
    assert engine.videoRoute == vm.SOFT

    engine.currentMedia = "file:///next.mkv"
    controller._on_media_changed("file:///next.mkv")
    _settle(qt_application)

    assert settings.values["playback.videoMode"] == "turbo"
    assert engine.videoRoute == vm.TURBO


def test_a_nonsense_selection_falls_back_to_auto(qt_application):
    controller, _engine, _md, settings = _controller(qt_application)

    controller.setVideoMode("hardware")

    assert controller.videoMode == "auto"


# ---------------------------------------------------------------------------
# M3U and Web (§V.1 / §V.2)
# ---------------------------------------------------------------------------
def test_m3u_is_always_soft_even_with_turbo_stored(qt_application):
    controller, engine, metadata, _ = _controller(
        qt_application, mode="m3u", stored="turbo"
    )
    engine.currentMedia = "http://stream/uhd.m3u8"

    controller._on_media_changed("http://stream/uhd.m3u8")
    metadata.describe(3840, 2160, 60)
    _settle(qt_application)

    assert engine.videoRoute == vm.SOFT
    assert vm.TURBO not in engine.requested, (
        "M3U must never even attempt the native route (§V.3)"
    )


def test_m3u_shows_the_dropdown_but_cannot_change_it(qt_application):
    controller, *_ = _controller(qt_application, mode="m3u")

    assert controller.videoModeAvailable is True, "the row stays visible in M3U"
    assert controller.videoModeEnabled is False, "…and is not interactive"
    assert controller.effectiveVideoMode == "soft"


def test_web_disables_video_mode_entirely(qt_application):
    controller, *_ = _controller(qt_application, mode="web", stored="turbo")

    assert controller.videoModeAvailable is False
    assert controller.videoModeEnabled is False


def test_switching_from_local_turbo_to_m3u_drops_to_soft(qt_application):
    controller, engine, metadata, _ = _controller(qt_application, stored="turbo")
    engine.currentMedia = "file:///uhd.mkv"
    controller._on_media_changed("file:///uhd.mkv")
    _settle(qt_application)
    assert engine.videoRoute == vm.TURBO

    controller.setActiveMode("m3u")
    _settle(qt_application)

    assert engine.videoRoute == vm.SOFT


def test_switching_to_web_leaves_no_turbo_route_running(qt_application):
    """One-tuner rule (§V.4): no background Turbo player survives the switch."""
    controller, engine, _md, _ = _controller(qt_application, stored="turbo")
    engine.currentMedia = "file:///uhd.mkv"
    controller._on_media_changed("file:///uhd.mkv")
    _settle(qt_application)
    assert engine.videoRoute == vm.TURBO

    controller.setActiveMode("web")
    _settle(qt_application)

    assert engine.stopped >= 1
    assert engine.videoRoute == vm.SOFT


# ---------------------------------------------------------------------------
# Failure (§V.4)
# ---------------------------------------------------------------------------
def test_a_turbo_that_cannot_start_reports_soft(qt_application):
    controller, engine, metadata, _ = _controller(
        qt_application, stored="turbo", turbo_works=False
    )
    engine.currentMedia = "file:///uhd.mkv"

    controller._on_media_changed("file:///uhd.mkv")
    _settle(qt_application)

    assert vm.TURBO in engine.requested, "it must at least have been attempted"
    assert engine.videoRoute == vm.SOFT
    assert controller.effectiveVideoMode == "soft", (
        "the UI must show what is really happening, not the request"
    )


def test_a_late_turbo_failure_from_the_shell_falls_back(qt_application):
    controller, engine, _md, _ = _controller(qt_application, stored="turbo")
    engine.currentMedia = "file:///uhd.mkv"
    controller._on_media_changed("file:///uhd.mkv")
    _settle(qt_application)
    assert engine.videoRoute == vm.TURBO

    controller.reportTurboFailure("WindowContainer did not adopt the child")

    assert engine.videoRoute == vm.SOFT
    assert controller.effectiveVideoMode == "soft"


def test_an_engine_without_the_route_api_is_not_fatal(qt_application):
    """An older/partial engine must not take the controller down with it."""
    class Bare(FakeEngine):
        set_video_route = None

    engine = Bare()
    controller = AppController(
        engine, FakeSettings({"ui.mode": "local"}), Inert(), FakeMetadata(),
        Inert(), Inert(), None,
    )
    controller._on_media_changed("file:///film.mkv")
    _settle(qt_application)  # must not raise


# ---------------------------------------------------------------------------
# Mini Mode (§M / §V.4)
# ---------------------------------------------------------------------------
def test_mini_mode_forces_soft_without_touching_the_selection(qt_application):
    controller, engine, metadata, settings = _controller(
        qt_application, stored="turbo"
    )
    engine.currentMedia = "file:///uhd.mkv"
    controller._on_media_changed("file:///uhd.mkv")
    _settle(qt_application)
    assert engine.videoRoute == vm.TURBO

    controller.setMiniMode(True)
    _settle(qt_application)

    assert engine.videoRoute == vm.SOFT, (
        "a 460x44 bar has nowhere to embed a native child window"
    )
    assert settings.values["playback.videoMode"] == "turbo", (
        "Mini must not rewrite the user's choice — the old checkbox did, and "
        "that is exactly what §V.1 removed"
    )
    assert controller.videoMode == "turbo"


def test_leaving_mini_mode_restores_the_selected_mode(qt_application):
    controller, engine, _md, _ = _controller(qt_application, stored="turbo")
    engine.currentMedia = "file:///uhd.mkv"
    controller._on_media_changed("file:///uhd.mkv")
    _settle(qt_application)
    controller.setMiniMode(True)
    _settle(qt_application)
    assert engine.videoRoute == vm.SOFT

    controller.setMiniMode(False)
    _settle(qt_application)

    assert engine.videoRoute == vm.TURBO


def test_leaving_mini_mode_re_resolves_auto(qt_application):
    controller, engine, metadata, _ = _controller(qt_application, stored="auto")
    engine.currentMedia = "file:///uhd.mkv"
    controller._on_media_changed("file:///uhd.mkv")
    metadata.describe(3840, 2160, 60)
    _settle(qt_application)
    assert engine.videoRoute == vm.TURBO

    controller.setMiniMode(True)
    _settle(qt_application)
    assert engine.videoRoute == vm.SOFT

    controller.setMiniMode(False)
    _settle(qt_application)
    assert engine.videoRoute == vm.TURBO, "Auto must be evaluated again on return"


def test_mini_mode_falls_back_to_soft_when_turbo_cannot_restart(qt_application):
    controller, engine, _md, _ = _controller(qt_application, stored="turbo")
    engine.currentMedia = "file:///uhd.mkv"
    controller._on_media_changed("file:///uhd.mkv")
    _settle(qt_application)

    controller.setMiniMode(True)
    _settle(qt_application)
    engine.turbo_works = False          # the GPU route died while Mini was up

    controller.setMiniMode(False)
    _settle(qt_application)

    assert engine.videoRoute == vm.SOFT


# ---------------------------------------------------------------------------
# The capability flag itself
# ---------------------------------------------------------------------------
def test_only_local_declares_turbo_allowed():
    from core import modes as registry

    allowed = {spec.id: spec.turbo_allowed for spec in registry.all_modes()}
    assert allowed["local"] is True
    assert allowed["m3u"] is False
    assert allowed["web"] is False


def test_the_capability_reaches_qml():
    from core.app import ModeList

    specs = {entry["id"]: entry for entry in ModeList().list}
    assert specs["local"]["turboAllowed"] is True
    assert specs["m3u"]["turboAllowed"] is False
    assert specs["web"]["turboAllowed"] is False


# ---------------------------------------------------------------------------
# Audio-only media (§V.2)
#
# Turbo exists to put decoded pixels in a native child window. A media with no
# video track has no pixels, so every selection — including an explicit Turbo —
# must resolve to Soft: otherwise the app embeds an empty HWND, moves the
# chrome onto the overlay window and drops the QML blur for an album-art card.
# ---------------------------------------------------------------------------
def test_audio_only_stays_soft_under_explicit_turbo(qt_application):
    controller, engine, metadata, settings = _controller(
        qt_application, stored="turbo"
    )
    engine.currentMedia = "file:///song.flac"

    controller._on_media_changed("file:///song.flac")
    engine.announce_tracks(video=False)
    metadata.describe_audio_only()
    _settle(qt_application)

    assert engine.videoRoute == vm.SOFT
    assert vm.TURBO not in engine.requested, (
        "an audio file must not even attempt the native route"
    )
    assert settings.values["playback.videoMode"] == "turbo", (
        "the selection is untouched — it applies again on the next video"
    )


def test_audio_only_stays_soft_under_auto(qt_application):
    controller, engine, metadata, _ = _controller(qt_application)
    engine.currentMedia = "file:///song.mp3"

    controller._on_media_changed("file:///song.mp3")
    engine.announce_tracks(video=False)
    metadata.describe_audio_only()
    _settle(qt_application)

    assert engine.videoRoute == vm.SOFT


def test_an_audio_extension_is_soft_before_anything_is_parsed(qt_application):
    """No tracks, no metadata — the extension alone is enough to say Soft.

    This is what stops a `.flac` opening on Turbo for the fraction of a second
    before libVLC reports its (empty) video track list.
    """
    controller, engine, _md, _ = _controller(qt_application, stored="turbo")
    engine.currentMedia = "file:///song.flac"

    controller._on_media_changed("file:///song.flac")
    _settle(qt_application)

    assert engine.videoRoute == vm.SOFT
    assert vm.TURBO not in engine.requested


def test_a_video_track_arriving_late_still_reaches_turbo(qt_application):
    """The audio-only rule must not cost a real video file its Turbo route.

    An unknown track list is the normal first state of every open, so it is
    deliberately *not* read as "audio only".
    """
    controller, engine, metadata, _ = _controller(qt_application, stored="turbo")
    engine.currentMedia = "file:///film.mkv"

    controller._on_media_changed("file:///film.mkv")
    engine.announce_tracks(video=True)
    metadata.describe(1920, 1080, 24)
    _settle(qt_application)

    assert engine.videoRoute == vm.TURBO


def test_skipping_from_video_to_audio_drops_back_to_soft(qt_application):
    """The cached answer must not survive the media it described."""
    controller, engine, metadata, _ = _controller(qt_application, stored="turbo")
    engine.currentMedia = "file:///film.mkv"
    controller._on_media_changed("file:///film.mkv")
    engine.announce_tracks(video=True)
    _settle(qt_application)
    assert engine.videoRoute == vm.TURBO

    engine.currentMedia = "file:///song.flac"
    engine.announce_tracks(video=False)
    controller._on_media_changed("file:///song.flac")
    metadata.describe_audio_only()
    _settle(qt_application)

    assert engine.videoRoute == vm.SOFT


def test_skipping_from_audio_back_to_video_returns_to_turbo(qt_application):
    controller, engine, metadata, _ = _controller(qt_application, stored="turbo")
    engine.currentMedia = "file:///song.flac"
    engine.announce_tracks(video=False)
    controller._on_media_changed("file:///song.flac")
    _settle(qt_application)
    assert engine.videoRoute == vm.SOFT

    engine.currentMedia = "file:///film.mkv"
    engine.announce_tracks(video=True)
    controller._on_media_changed("file:///film.mkv")
    metadata.describe(3840, 2160, 60)
    _settle(qt_application)

    assert engine.videoRoute == vm.TURBO


def test_audio_only_does_not_thrash_the_route(qt_application):
    """One route decision per media, not one per signal.

    A single open emits tracksChanged and metadata changed several times each;
    if every one of them re-applied, the engine would be asked to switch route
    repeatedly while the media is playing.
    """
    controller, engine, metadata, _ = _controller(qt_application, stored="turbo")
    engine.currentMedia = "file:///song.flac"

    controller._on_media_changed("file:///song.flac")
    for _ in range(3):
        engine.announce_tracks(video=False)
        metadata.describe_audio_only()
    _settle(qt_application)

    assert engine.videoRoute == vm.SOFT
    assert engine.requested.count(vm.SOFT) <= 1, (
        f"route re-applied on every signal: {engine.requested}"
    )


def test_hasvideo_property_and_the_route_agree(qt_application):
    """The route reads the same track list the public hasVideo property does."""
    controller, engine, _md, _ = _controller(qt_application, stored="turbo")
    engine.currentMedia = "file:///song.flac"

    controller._on_media_changed("file:///song.flac")
    engine.announce_tracks(video=False)
    _settle(qt_application)
    assert controller.hasVideo is False
    assert controller.effectiveVideoMode == "soft"

    engine.currentMedia = "file:///film.mkv"
    engine.announce_tracks(video=True)
    controller._on_media_changed("file:///film.mkv")
    _settle(qt_application)
    assert controller.hasVideo is True
    assert controller.effectiveVideoMode == "turbo"
