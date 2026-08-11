"""The "subtitles start off" contract and the clear-path track reset.

Two behaviours this file pins down:

1. **Issue 2 — subtitles start off.** When a media reaches Playing, the
   controller forces the current subtitle to off once (``_on_state_changed``),
   so the popover's "Disable" highlight and the on-screen result agree instead
   of racing libVLC's auto-picked default. The force happens only for the
   first Playing of a media, so a later pause/resume never wipes a subtitle the
   user turned on.

2. **Issue 1 — track state resets on clear.** When the queue empties
   (``_reset_track_state``), every cached track list, the active ids and the CC
   dot flag are emptied — the track-state mirror of the lyrics reset — so the
   dot and the popover's lists don't linger after the playlist is cleared.

3. **Auto-load lists every sidecar without activating it.** Media-start
   auto-load attaches each matching sidecar with ``select=False`` so it shows
   up under Local subtitles but is not turned on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from PySide6.QtCore import QCoreApplication

from core.app import AppController


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


class _FakeEngine:
    """A VlcEngine surface enough for _refresh_tracks + set_subtitle_track."""

    def __init__(self, audio=(), video=(), subs=(), current_audio=-1, current_sub=-1):
        self._audio = list(audio)
        self._video = list(video)
        self._subs = list(subs)
        self._current_audio = current_audio
        self._current_sub = current_sub
        self.set_spu_calls: list[int] = []
        self.slaves: list[tuple[str, bool]] = []
        self.currentMedia = ""

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

    def set_subtitle_track(self, track_id):
        self.set_spu_calls.append(int(track_id))
        self._current_sub = int(track_id)

    def add_subtitle_file(self, path, select=True):
        self.slaves.append((path, select))
        return True


VIDEO = [(0, "Video 1")]
SUB_OFF = (-1, "Disable")
SUB_EN = (3, "English")


def _controller(engine):
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
    controller._force_subs_off_pending = False
    return controller


class TestSubtitlesStartOff:
    def test_first_playing_forces_subtitles_off_and_refreshes(self, qt_app):
        # VLC has already auto-picked English (current_sub=3) by the time the
        # state turns Playing — the exact race the old code lost.
        engine = _FakeEngine(video=VIDEO, subs=[SUB_OFF, SUB_EN], current_sub=3)
        controller = _controller(engine)
        controller._force_subs_off_pending = True

        controller._on_state_changed(3)  # State.Playing

        assert engine.set_spu_calls == [-1], "must turn the default subtitle off"
        assert controller._force_subs_off_pending is False, "flag consumed"
        assert controller.currentSubtitleId == -1
        # Subtitles exist and none is active -> the CC dot is back on.
        assert controller.subtitlesAvailable is True

    def test_later_playing_does_not_force_off_a_chosen_subtitle(self, qt_app):
        # After the start-off moment, a pause/resume back to Playing must not
        # wipe a subtitle the user picked.
        engine = _FakeEngine(video=VIDEO, subs=[SUB_OFF, SUB_EN], current_sub=3)
        controller = _controller(engine)
        controller._refresh_tracks()                  # cached id now reflects the pick
        controller._force_subs_off_pending = False    # already consumed at media start

        controller._on_state_changed(3)

        assert engine.set_spu_calls == [], "user's subtitle must survive resume"
        assert controller.currentSubtitleId == 3      # unchanged

    def test_non_playing_state_does_nothing(self, qt_app):
        engine = _FakeEngine(video=VIDEO, subs=[SUB_OFF, SUB_EN], current_sub=3)
        controller = _controller(engine)
        controller._force_subs_off_pending = True

        controller._on_state_changed(5)  # State.Stopped

        assert engine.set_spu_calls == []
        assert controller._force_subs_off_pending is True, "still pending"


class TestResetTrackState:
    def _populated(self, engine):
        controller = _controller(engine)
        controller._refresh_tracks()  # fills every list from the engine
        controller._force_subs_off_pending = True
        return controller

    def test_clear_resets_lists_ids_and_dot(self, qt_app):
        controller = self._populated(
            _FakeEngine(video=VIDEO, subs=[SUB_OFF, SUB_EN], current_sub=-1)
        )
        assert controller.embeddedSubtitleTracks  # something to reset
        assert controller.subtitlesAvailable is True

        controller._reset_track_state()

        assert controller.audioTracks == []
        assert controller.videoTracks == []
        assert controller.subtitleTracks == []
        assert controller.embeddedSubtitleTracks == []
        assert controller.localSubtitleTracks == []
        assert controller.currentAudioId == -1
        assert controller.currentSubtitleId == -1
        assert controller.subtitlesAvailable is False
        assert controller._force_subs_off_pending is False


class TestAutoLoadListsSidecarsInactive:
    def test_all_sidecars_are_loaded_with_select_false(self, qt_app, tmp_path):
        media = tmp_path / "movie.mkv"
        media.write_bytes(b"m")
        (tmp_path / "movie.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n")
        (tmp_path / "movie.ass").write_text("[Script Info]", encoding="utf-8")

        engine = _FakeEngine(video=VIDEO, subs=[SUB_OFF])
        controller = _controller(engine)

        controller._auto_load_subtitle(str(media))

        names = {Path(p).name for p, _sel in engine.slaves}
        assert names == {"movie.srt", "movie.ass"}, "every matching sidecar is listed"
        assert all(sel is False for _p, sel in engine.slaves), "none is activated"
