"""Dropping a subtitle file must subtitle the video, not crash the player.

The reported failure: drag a ``.srt`` onto the window, the player dies.

What actually happened
----------------------
``DropArea`` routes every dropped URL through the one append path,
``App.addPaths`` -> ``PlaylistModel.add_paths``. The model's extension check
had an "unknown extension, trust the user" fallback, so a ``.srt`` was queued
as a **playable track** (the log line ``adding ... .srt despite unknown
extension`` is this happening).

Because the drop also auto-started playback, libVLC was then asked to open a
subtitle file as media. It opens fine — as a track with no video and no audio —
which tears the video pipeline down mid-playback and leaves the UI holding a
row that can never play.

A subtitle is not media. Dropping one means "subtitle what is playing", so it
is now split out before the queue ever sees it and routed to ``add_slave``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from PySide6.QtCore import QCoreApplication

from modes.local.playlist import (
    MEDIA_EXTENSIONS,
    SUBTITLE_EXTENSIONS,
    PlaylistModel,
)


@pytest.fixture(scope="module")
def qt_app():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


@pytest.fixture
def media_file(tmp_path):
    p = tmp_path / "Andor S02E01 1080p HEVC.mkv"
    p.write_bytes(b"\x1a\x45\xdf\xa3not-really-matroska")
    return p


@pytest.fixture
def subtitle_file(tmp_path):
    p = tmp_path / "Andor S02E01 1080p HEVC.srt"
    p.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nHello there.\n", encoding="utf-8"
    )
    return p


class TestExtensionSets:
    def test_subtitles_are_not_classed_as_media(self):
        assert not (SUBTITLE_EXTENSIONS & MEDIA_EXTENSIONS), (
            "an extension in both sets would make routing order-dependent"
        )

    @pytest.mark.parametrize("ext", [".srt", ".ass", ".ssa", ".sub", ".vtt"])
    def test_the_common_sidecar_formats_are_covered(self, ext):
        assert ext in SUBTITLE_EXTENSIONS

    def test_mkv_and_mka_are_still_media(self):
        # .mka is audio-in-matroska and must not be caught by any subtitle rule.
        assert ".mkv" in MEDIA_EXTENSIONS
        assert ".mka" in MEDIA_EXTENSIONS


class TestPlaylistRejectsSubtitles:
    """The queue is the last line of defence, so test it directly."""

    @pytest.mark.parametrize("ext", sorted(SUBTITLE_EXTENSIONS))
    def test_subtitle_is_never_queued(self, qt_app, tmp_path, ext):
        sub = tmp_path / f"movie{ext}"
        sub.write_text("x", encoding="utf-8")
        model = PlaylistModel()
        added = model.add_paths([str(sub)])
        assert added == 0, f"{ext} was queued as a playable track"
        assert model.count == 0

    def test_media_still_gets_queued(self, qt_app, media_file):
        model = PlaylistModel()
        assert model.add_paths([str(media_file)]) == 1
        assert model.count == 1

    def test_mixed_drop_keeps_only_the_media(self, qt_app, media_file, subtitle_file):
        # Selecting a video and its sidecar together is a normal thing to do.
        model = PlaylistModel()
        added = model.add_paths([str(media_file), str(subtitle_file)])
        assert added == 1
        assert model.count == 1
        assert Path(model.path_at(0)).suffix == ".mkv"

    def test_folder_scan_skips_sidecars(self, qt_app, tmp_path):
        (tmp_path / "ep1.mkv").write_bytes(b"v")
        (tmp_path / "ep1.srt").write_text("s", encoding="utf-8")
        (tmp_path / "ep2.mp4").write_bytes(b"v")
        (tmp_path / "notes.txt").write_text("t", encoding="utf-8")
        model = PlaylistModel()
        added = model.add_paths([str(tmp_path)])
        assert added == 2
        suffixes = {Path(model.path_at(i)).suffix for i in range(model.count)}
        assert suffixes == {".mkv", ".mp4"}

    def test_unknown_extensions_are_still_trusted(self, qt_app, tmp_path):
        # The "user picked it explicitly" fallback must survive — only
        # subtitles are special-cased.
        odd = tmp_path / "recording.m2v"
        odd.write_bytes(b"v")
        model = PlaylistModel()
        assert model.add_paths([str(odd)]) == 1


class _FakeEngine:
    """Minimal stand-in for VlcEngine's subtitle surface."""

    def __init__(self, current="file:///video.mkv"):
        self.currentMedia = current
        self.slaves: list[str] = []
        self.opened: list[str] = []

    def add_subtitle_file(self, path):
        self.slaves.append(path)
        return True


class TestSubtitleRouting:
    """``core.app`` must send a lone subtitle to add_slave, not to the queue."""

    def _controller(self, engine, playlist):
        """A real AppController wired to fakes.

        ``QObject.__init__`` must run — skipping it via ``__new__`` leaves the
        signals unusable ("Signal source has been deleted"). So the base class
        is initialised and only the collaborators are stubbed.
        """
        from core.app import AppController

        controller = AppController.__new__(AppController)
        AppController.__bases__[0].__init__(controller)  # QObject.__init__
        controller._engine = engine
        controller._settings = None
        controller._library = None
        controller._metadata = None
        controller._lyrics = None
        controller._equalizer = None
        controller._active_mode = "local"
        controller._contexts = {"local": playlist}
        controller._subtitle_delay = 0
        controller._audio_tracks = []
        controller._subtitle_tracks = []
        controller._embedded_subtitle_tracks = []
        controller._local_subtitle_tracks = []
        controller._current_audio_id = -1
        controller._current_subtitle_id = -1
        controller._external_sub_files = []
        return controller

    def test_lone_subtitle_is_attached_not_queued(self, qt_app, subtitle_file):
        engine = _FakeEngine()
        playlist = PlaylistModel()
        controller = self._controller(engine, playlist)

        controller.addPaths([str(subtitle_file)])

        assert playlist.count == 0, "subtitle leaked into the queue"
        assert len(engine.slaves) == 1
        assert Path(engine.slaves[0]).name == subtitle_file.name

    def test_subtitle_with_nothing_playing_is_ignored(self, qt_app, subtitle_file):
        engine = _FakeEngine(current="")
        playlist = PlaylistModel()
        controller = self._controller(engine, playlist)

        controller.addPaths([str(subtitle_file)])

        assert playlist.count == 0
        assert engine.slaves == []

    def test_dropping_a_video_still_queues_it(self, qt_app, media_file):
        engine = _FakeEngine()
        playlist = PlaylistModel()
        controller = self._controller(engine, playlist)

        controller.addPaths([str(media_file)])

        assert playlist.count == 1
        assert engine.slaves == []

    def test_file_url_form_is_handled(self, qt_app, subtitle_file):
        # Drops arrive as percent-encoded file:// URLs, not plain paths.
        engine = _FakeEngine()
        playlist = PlaylistModel()
        controller = self._controller(engine, playlist)

        controller.addPaths([subtitle_file.as_uri()])

        assert playlist.count == 0
        assert len(engine.slaves) == 1
