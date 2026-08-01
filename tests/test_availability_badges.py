"""The transport-bar "available" dots — §P1.6.

The CC button shows a dot when the current video has subtitles the user could
switch on. That decision lives in ``AppController.subtitlesAvailable`` and is
recomputed on every ``tracksChanged`` (the same signal the subtitle popover
reads), so it tracks the asynchronous arrival of tracks and the user toggling a
subtitle on or off.

These tests drive a real ``AppController`` against a minimal engine stand-in
that only knows how to report tracks and the active ids — the same shape the
GUI thread queries, minus libVLC.
"""

from __future__ import annotations

import pytest

from PySide6.QtCore import QCoreApplication

from core.app import AppController


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


class _FakeEngine:
    """A VlcEngine surface limited to the track getters _refresh_tracks uses."""

    def __init__(self, audio=(), video=(), subs=(), current_audio=-1, current_sub=-1):
        self._audio = list(audio)
        self._video = list(video)
        self._subs = list(subs)
        self._current_audio = current_audio
        self._current_sub = current_sub

    def audio_tracks(self):
        return list(self._audio)

    def video_tracks(self):
        return list(self._video)

    def subtitle_tracks(self):
        return list(self._subs)

    def current_audio_track(self):
        return self._current_audio

    def current_subtitle_track(self):
        return self._current_sub


def _controller(engine):
    """A real AppController wired to a fake engine.

    ``QObject.__init__`` must run or the signals are unusable, so the base class
    is initialised and only the track state is stubbed — the same approach as
    tests/test_subtitle_drop.py. ``_refresh_tracks`` assigns every attribute it
    reads after this point, so the stub only seeds the ones it reads first.
    """
    controller = AppController.__new__(AppController)
    AppController.__bases__[0].__init__(controller)  # QObject.__init__
    controller._engine = engine
    controller._audio_tracks = []
    controller._video_tracks = []
    controller._subtitle_tracks = []
    controller._embedded_subtitle_tracks = []
    controller._local_subtitle_tracks = []
    controller._current_audio_id = -1
    controller._current_subtitle_id = -1
    controller._subtitle_delay = 0
    controller._external_sub_files = []
    controller._local_subtitle_map = {}
    controller._subtitles_available = False
    return controller


VIDEO = [(0, "Track 1")]
SUB_OFF = (-1, "Disable")          # VLC's pseudo-track — must never count
SUB_EN = (3, "English")
SUB_FR = (4, "French")


class TestSubtitlesAvailable:
    def test_video_with_subs_off_shows_the_dot(self, qt_app):
        engine = _FakeEngine(video=VIDEO, subs=[SUB_OFF, SUB_EN], current_sub=-1)
        controller = _controller(engine)
        controller._refresh_tracks()
        assert controller.subtitlesAvailable is True

    def test_a_subtitle_already_on_hides_the_dot(self, qt_app):
        # The badge promises "something you could switch on"; once one is on
        # there is nothing to advertise.
        engine = _FakeEngine(video=VIDEO, subs=[SUB_OFF, SUB_EN], current_sub=3)
        controller = _controller(engine)
        controller._refresh_tracks()
        assert controller.subtitlesAvailable is False

    def test_video_with_no_subtitles_hides_the_dot(self, qt_app):
        engine = _FakeEngine(video=VIDEO, subs=[SUB_OFF], current_sub=-1)
        controller = _controller(engine)
        controller._refresh_tracks()
        assert controller.subtitlesAvailable is False

    def test_audio_only_never_shows_the_subtitle_dot(self, qt_app):
        # Subtitles are a video concept; an audio file's dot would be noise.
        engine = _FakeEngine(audio=[(0, "Track 1")], subs=[SUB_EN], current_sub=-1)
        controller = _controller(engine)
        controller._refresh_tracks()
        assert controller.subtitlesAvailable is False

    def test_a_loaded_subtitle_file_also_counts(self, qt_app):
        # A .srt attached via add_slave appears as a local track, not embedded,
        # and is just as much "available to switch on".
        engine = _FakeEngine(video=VIDEO, subs=[SUB_OFF, (5, "movie.srt")], current_sub=-1)
        controller = _controller(engine)
        controller._local_subtitle_map = {5: "movie.srt"}  # id -> attached file
        controller._refresh_tracks()
        assert controller.localSubtitleTracks        # classified as local...
        assert controller.subtitlesAvailable is True  # ...and still advertised

    def test_switching_a_subtitle_off_reshows_the_dot(self, qt_app):
        # The same media, played twice: first with a subtitle active (no dot),
        # then with it disabled (dot back). One source of truth, both directions.
        controller = _controller(
            _FakeEngine(video=VIDEO, subs=[SUB_OFF, SUB_EN], current_sub=3)
        )
        controller._refresh_tracks()
        assert controller.subtitlesAvailable is False

        controller._engine = _FakeEngine(video=VIDEO, subs=[SUB_OFF, SUB_EN], current_sub=-1)
        controller._refresh_tracks()
        assert controller.subtitlesAvailable is True
