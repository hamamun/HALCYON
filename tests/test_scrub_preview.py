"""§S — Scrub preview: settings default, hidden decoder, engine wiring.

The hidden decoder's libVLC side is exercised with fakes, exactly like
``test_video_teardown.py``: the media objects are stand-ins, but the state
machine (coalescing, serve-on-ready, retry, shutdown order) is the real code.
The only test that needs the real python-vlc module is the settings one's
import path — and even that uses the module for constants, not a running
libVLC.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from core.settings import Settings

vlc = pytest.importorskip(
    "vlc", reason="python-vlc is needed for the engine module import"
)


# --------------------------------------------------------------------------
# Fakes — the shape of libVLC objects the decoder talks to
# --------------------------------------------------------------------------
class FakeMedia:
    def __init__(self, mrl: str):
        self.mrl = mrl
        self.released = False

    def parse_with_options(self, *_args) -> None:
        pass

    def release(self) -> None:
        self.released = True


class FakeEventManager:
    def __init__(self):
        self.attached: list = []
        self.detached: list = []

    def event_attach(self, event_type, _handler) -> None:
        self.attached.append(event_type)

    def event_detach(self, event_type) -> None:
        self.detached.append(event_type)


class FakeInstance:
    def __init__(self):
        self.created_media: list[FakeMedia] = []
        self.released = False

    def media_new(self, mrl: str) -> FakeMedia:
        media = FakeMedia(mrl)
        self.created_media.append(media)
        return media

    def release(self) -> None:
        self.released = True


class FakePlayer:
    def __init__(self, has_vout: int = 1):
        self.em = FakeEventManager()
        self.has_vout_value = has_vout
        self.seeks: list[int] = []
        self.snapshot_paths: list[str] = []
        self.snapshot_rc = 0
        self.play_calls = 0
        self.pause_calls = 0
        self.stop_calls = 0
        self.set_media_calls: list = []
        self.media = None
        self.released = False

    def event_manager(self):
        return self.em

    def set_media(self, media) -> None:
        self.media = media
        self.set_media_calls.append(media)

    def play(self) -> None:
        self.play_calls += 1

    def pause(self) -> None:
        self.pause_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    def set_time(self, ms: int) -> None:
        self.seeks.append(int(ms))

    def video_take_snapshot(self, _num, path, _width, _height) -> int:
        self.snapshot_paths.append(str(path))
        return self.snapshot_rc

    def has_vout(self) -> int:
        return self.has_vout_value

    def get_state(self):
        # Shape of python-vlc's ctypes State: an object with a `.value`
        # (VlcEngine._enum_int and the shutdown settle loop both read it).
        return types.SimpleNamespace(value=5)  # Stopped — settles immediately

    def release(self) -> None:
        self.released = True


def _preview_with_fakes(has_vout: int = 1) -> tuple:
    """A real ScrubPreview with a fake libVLC layer installed."""
    from engine.scrub_preview import ScrubPreview

    preview = ScrubPreview()
    instance = FakeInstance()
    player = FakePlayer(has_vout=has_vout)
    preview._instance = instance
    preview._player = player
    preview._vlc = vlc
    preview._tmp_dir = Path(__import__("tempfile").gettempdir()) / "halcyon-scrub-test"
    return preview, instance, player


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def test_the_default_is_on(tmp_path) -> None:
    settings = Settings(tmp_path / "settings.json")
    assert settings.get("ui.scrubPreviewEnabled", None) is True


def test_turning_it_off_persists(tmp_path) -> None:
    settings = Settings(tmp_path / "settings.json")
    settings.set("ui.scrubPreviewEnabled", False)
    assert settings.get("ui.scrubPreviewEnabled", None) is False
    settings.flush()  # writes are debounced; flush before reloading
    reloaded = Settings(tmp_path / "settings.json")
    assert reloaded.get("ui.scrubPreviewEnabled", None) is False


# --------------------------------------------------------------------------
# The hidden decoder
# --------------------------------------------------------------------------
def test_network_urls_never_create_a_decoder() -> None:
    from engine.scrub_preview import ScrubPreview

    preview = ScrubPreview()  # no fakes installed: instance must stay None
    seen: list[str] = []
    preview.snapshotReady.connect(seen.append)

    preview.set_source("http://example.com/live.m3u8")

    assert preview._instance is None, "a network URL must not spin up libVLC"
    assert preview.ready is False
    assert preview.available is False
    assert seen == [], "no frame existed, so nothing to clear"


def test_audio_only_media_never_becomes_ready(qt_application) -> None:
    preview, _instance, player = _preview_with_fakes(has_vout=0)
    preview.set_source("file:///tmp/only-audio.mp3")
    preview._on_playing_gui()
    assert preview.ready is False
    assert player.pause_calls == 0


def test_request_parks_until_ready_then_is_served(qt_application) -> None:
    preview, _instance, player = _preview_with_fakes()
    seen: list[str] = []
    preview.snapshotReady.connect(seen.append)

    preview.set_source("file:///tmp/clip.mp4")
    preview.request(5000)  # before the decoder reports Playing

    assert player.seeks == [], "no seek before the vout exists"
    preview._on_playing_gui()  # Playing event lands → chain starts

    assert player.pause_calls == 1, "decoder pauses to idle at the first frame"
    assert player.seeks == [5000], "the parked request is served on ready"
    preview._on_step()
    assert player.snapshot_paths, "snapshot taken after the settle delay"
    preview._on_shot_taken_gui(str(player.snapshot_paths[-1]))

    assert len(seen) == 1 and seen[0].startswith("file://"), seen


def test_rapid_requests_coalesce_to_the_newest_position(qt_application) -> None:
    preview, _instance, player = _preview_with_fakes()
    preview.set_source("file:///tmp/clip.mp4")
    preview._on_playing_gui()

    preview.request(1000)  # starts the chain
    preview.request(2000)  # arrives while the chain is in flight
    preview.request(3000)  # and again

    assert player.seeks == [1000], "only the first request seeks immediately"
    preview._on_step()
    preview._on_shot_taken_gui(str(player.snapshot_paths[-1]))

    # The chain adopted the newest request — one extra seek, no queue.
    assert player.seeks == [1000, 3000], player.seeks
    preview._on_step()  # the adopted chain's settle elapses
    preview._on_shot_taken_gui(str(player.snapshot_paths[-1]))
    assert len(player.snapshot_paths) == 2
    assert player.seeks == [1000, 3000], "the chain rests — no third seek"


def test_requests_after_the_chain_rests_seek_again(qt_application) -> None:
    preview, _instance, player = _preview_with_fakes()
    preview.set_source("file:///tmp/clip.mp4")
    preview._on_playing_gui()

    preview.request(1000)
    preview._on_step()
    preview._on_shot_taken_gui(str(player.snapshot_paths[-1]))
    assert player.seeks == [1000]

    preview.request(4000)
    assert player.seeks == [1000, 4000], "an idle decoder seeks immediately"


def test_a_too_early_snapshot_gets_one_retry(qt_application) -> None:
    preview, _instance, player = _preview_with_fakes()
    preview.set_source("file:///tmp/clip.mp4")
    preview._on_playing_gui()

    player.snapshot_rc = -1  # frame not decoded yet
    preview.request(2000)
    preview._on_step()

    player.snapshot_rc = 0  # retry succeeds
    preview._on_step()

    assert len(player.snapshot_paths) == 2, "first attempt + one retry"


def test_new_source_clears_the_previous_frame_and_seeks(qt_application) -> None:
    preview, _instance, player = _preview_with_fakes()
    seen: list[str] = []
    preview.snapshotReady.connect(seen.append)

    preview.set_source("file:///tmp/one.mp4")
    preview._on_playing_gui()
    preview.set_source("file:///tmp/two.mp4")

    assert seen == [""], "switching media clears the stale frame"
    assert player.set_media_calls[-1].mrl == "file:///tmp/two.mp4"
    assert preview.ready is False, "new media starts not-ready until Playing"


def test_set_source_with_the_same_mrl_is_a_no_op(qt_application) -> None:
    preview, _instance, player = _preview_with_fakes()
    preview.set_source("file:///tmp/clip.mp4")
    calls_before = len(player.set_media_calls)
    preview.set_source("file:///tmp/clip.mp4")
    assert len(player.set_media_calls) == calls_before


def test_shutdown_releases_in_safe_order_and_cleans_temp() -> None:
    from engine.scrub_preview import ScrubPreview

    preview, instance, player = _preview_with_fakes()
    order: list[str] = []

    class _Player(FakePlayer):
        def stop(self) -> None:
            order.append("stop")
            super().stop()

        def release(self) -> None:
            order.append("release-player")
            super().release()

    class _Instance(FakeInstance):
        def release(self) -> None:
            order.append("release-instance")
            super().release()

    player = _Player()
    instance = _Instance()
    preview._player = player
    preview._instance = instance

    # A stray snapshot file from a previous run must be cleaned up.
    preview._tmp_dir.mkdir(parents=True, exist_ok=True)
    stray = preview._tmp_dir / "scrub_0.png"
    stray.write_bytes(b"png")
    preview.shutdown()

    assert order == ["stop", "release-player", "release-instance"], order
    assert not stray.exists(), "temp snapshots removed at shutdown"
    assert preview.ready is False and preview.available is False


def test_module_level_imports_do_not_need_libvlc() -> None:
    """§S.3 — the module imports cleanly without libVLC present."""
    import ast

    import engine.scrub_preview as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    for node in tree.body:  # top-level statements only
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            if name == "vlc" or name.startswith("vlc."):
                raise AssertionError(
                    f"module-level vlc import at line {node.lineno}: {name}"
                )


# --------------------------------------------------------------------------
# Engine wiring — VlcEngine.open/stop/shutdown feed the decoder (§S.1)
# --------------------------------------------------------------------------
class _FakeEngineVout:
    def __init__(self):
        self.retired = 0

    def notify_video_stopped(self):
        self.retired += 1


class _EngineFakePlayer(FakePlayer):
    def __init__(self):
        super().__init__()
        self.media_set = None

    def set_media(self, media) -> None:
        self.media_set = media
        self.set_media_calls.append(media)


class _EngineFakeInstance(FakeInstance):
    def media_new(self, mrl: str) -> FakeMedia:
        media = FakeMedia(mrl)
        self.created_media.append(media)
        return media


class _RecordingPreview:
    def __init__(self):
        self.sources: list[str] = []
        self.shutdown_calls = 0

    def set_source(self, mrl: str) -> None:
        self.sources.append(mrl)

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _bare_engine() -> tuple:
    """A VlcEngine shell with fake libVLC, as in test_video_teardown."""
    from PySide6.QtCore import QObject

    from engine.vlc_engine import VlcEngine

    engine = VlcEngine.__new__(VlcEngine)
    QObject.__init__(engine)
    engine._vlc = vlc
    engine._instance = _EngineFakeInstance()
    engine._player = _EngineFakePlayer()
    engine._media = None
    engine._time = 0
    engine._position = 0.0
    engine._duration = 0
    engine._current_mrl = ""
    engine._scrubbing = False
    engine._pending_resume_ms = 0
    engine._pending_turbo_play = False
    engine._user_paused = False
    engine._releasing = False
    engine._video_width = 0
    engine._video_height = 0
    engine.video_output = _FakeEngineVout()
    # shutdown() stops the poll timer; a bare engine needs one to exist.
    from PySide6.QtCore import QTimer

    engine._poll = QTimer(engine)
    return engine


def test_engine_open_feeds_the_preview_decoder(tmp_path) -> None:
    engine = _bare_engine()
    preview = _RecordingPreview()
    engine._scrub_preview = preview

    media_file = tmp_path / "clip.mp4"
    media_file.write_bytes(b"")
    engine.open(str(media_file))

    assert preview.sources == [media_file.resolve().as_uri()], (
        "the hidden decoder must be pointed at every opened media"
    )


def test_engine_open_does_not_require_a_preview_decoder(tmp_path) -> None:
    """Teardown-style engines (no __init__) must still open cleanly."""
    engine = _bare_engine()  # no _scrub_preview attribute at all

    media_file = tmp_path / "clip.mp4"
    media_file.write_bytes(b"")
    engine.open(str(media_file))  # must not raise AttributeError


def test_engine_stop_clears_the_preview_decoder() -> None:
    engine = _bare_engine()
    preview = _RecordingPreview()
    engine._scrub_preview = preview
    engine._current_mrl = "file:///tmp/clip.mp4"

    engine.stop()

    assert preview.sources == [""], "a full stop releases the hidden decoder"


def test_engine_shutdown_tears_down_the_preview_decoder() -> None:
    engine = _bare_engine()
    preview = _RecordingPreview()
    engine._scrub_preview = preview

    engine.shutdown()

    assert preview.shutdown_calls == 1, "the hidden decoder must not outlive the engine"
