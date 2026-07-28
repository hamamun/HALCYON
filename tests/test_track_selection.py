"""Which track is playing, and which row is lit — they must be the same fact.

The reported failure: play a file with exactly one audio track. The popover
lists it correctly, but the highlight sits on the greyed **Disable** row, and
clicking the real track appears to do nothing — while sound is plainly coming
out of the speakers.

What actually happened
----------------------
``AppController`` published ``audioTracks`` and ``subtitleTracks`` but never
published *which* of them libVLC had selected. ``TrackPopover`` therefore kept
its declared default, ``currentAudioId: -1`` — and ``-1`` is libVLC's id for the
"Disable" entry. So the highlight landed on Disable for every file, on every
track, always. Selecting a track called ``audio_set_track`` (which worked, hence
the audible sound) but nothing re-read the selection, so the highlight never
moved.

The fix is to read the selection from the player — ``audio_get_track`` /
``video_get_spu`` — and republish it whenever the tracks change or a switch is
made. These tests pin that, plus the two list-shape rules the popover relies on:
the off row is identified by id (not by matching the localised word "Disable")
and is always first.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication

from core.app import TRACK_OFF_ID, AppController, _track_dicts


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


class _FakeEngine:
    """Stands in for VlcEngine's track surface, with libVLC's own shapes.

    libVLC always prepends a "Disable" pseudo-track with id -1 to both
    descriptions, and reports the live selection through separate getters.
    """

    def __init__(self, audio=None, subs=None):
        self._audio = audio if audio is not None else [(-1, "Disable"), (1, "English AC3 5.1")]
        self._subs = subs if subs is not None else [(-1, "Disable")]
        self.selected_audio = 1
        self.selected_sub = -1
        self.currentMedia = "file:///video.mkv"

    def audio_tracks(self):
        return list(self._audio)

    def subtitle_tracks(self):
        return list(self._subs)

    def current_audio_track(self):
        return self.selected_audio

    def current_subtitle_track(self):
        return self.selected_sub

    def set_audio_track(self, track_id):
        self.selected_audio = int(track_id)

    def set_subtitle_track(self, track_id):
        self.selected_sub = int(track_id)


def _controller(engine, library=None):
    from tests.support import build_controller, null_library

    controller = build_controller(engine, library=library or null_library())
    controller._refresh_tracks()
    return controller


# ----------------------------------------------------------- list shape ---
class TestTrackDicts:
    def test_the_off_row_is_flagged_by_id_not_by_label(self):
        tracks = _track_dicts([(-1, "Deaktivieren"), (1, "English")])

        off = [t for t in tracks if t["off"]]
        assert len(off) == 1, "exactly one off row"
        assert off[0]["id"] == TRACK_OFF_ID, (
            "the off row is libVLC's id -1 — matching the word 'Disable' breaks "
            "the moment libVLC is localised, which is why the German label here"
        )

    def test_the_off_row_is_always_first(self):
        tracks = _track_dicts([(3, "Commentary"), (-1, "Disable"), (1, "English")])

        assert tracks[0]["off"] is True, (
            "the UI pins the off row above a scrolling list, so it must be able "
            "to take it off the front without searching"
        )
        assert [t["id"] for t in tracks[1:]] == [3, 1], "real tracks keep VLC's order"

    def test_subtitles_relabel_disable_as_off(self):
        tracks = _track_dicts([(-1, "Disable")], off_label="Off")

        assert tracks[0]["label"] == "Off", "'Disable' is engine wording, not user wording"

    def test_no_off_row_when_the_engine_reports_none(self):
        tracks = _track_dicts([(1, "English"), (2, "Japanese")])

        assert all(not t["off"] for t in tracks)
        assert len(tracks) == 2


# ------------------------------------------------------ live selection ---
class TestCurrentTrack:
    def test_the_playing_audio_track_is_published(self, qt_app):
        """The bug, directly: one track, playing, and the id must not be -1."""
        engine = _FakeEngine()
        engine.selected_audio = 1
        controller = _controller(engine)

        assert controller.currentAudioId == 1, (
            "the popover binds its highlight to this; leaving it at -1 lights up "
            "the Disable row while track 1 is audible"
        )

    def test_the_highlight_does_not_default_to_the_off_row(self, qt_app):
        engine = _FakeEngine()
        controller = _controller(engine)

        assert controller.currentAudioId != TRACK_OFF_ID

    def test_selecting_a_track_moves_the_selection(self, qt_app):
        engine = _FakeEngine(
            audio=[(-1, "Disable"), (1, "English"), (2, "Japanese")]
        )
        controller = _controller(engine)

        controller.setAudioTrack(2)

        assert engine.selected_audio == 2
        assert controller.currentAudioId == 2, "the UI must see the switch it just made"

    def test_selecting_the_off_row_is_a_valid_selection(self, qt_app):
        engine = _FakeEngine(subs=[(-1, "Disable"), (4, "English")])
        engine.selected_sub = 4
        controller = _controller(engine)

        controller.setSubtitleTrack(TRACK_OFF_ID)

        assert controller.currentSubtitleId == TRACK_OFF_ID
        assert engine.selected_sub == TRACK_OFF_ID

    def test_subtitles_off_by_default_is_reported_as_off(self, qt_app):
        engine = _FakeEngine(subs=[(-1, "Disable"), (4, "English")])
        engine.selected_sub = -1
        controller = _controller(engine)

        assert controller.currentSubtitleId == TRACK_OFF_ID

    def test_the_track_signal_fires_when_the_selection_changes(self, qt_app):
        engine = _FakeEngine(audio=[(-1, "Disable"), (1, "A"), (2, "B")])
        controller = _controller(engine)
        seen = []
        controller.tracksChanged.connect(lambda: seen.append(controller.currentAudioId))

        controller.setAudioTrack(2)

        assert 2 in seen, "without a notify the QML binding never re-evaluates"


# --------------------------------------------------------------- cycle ---
class TestCycle:
    def test_cycling_advances_instead_of_re_selecting_the_first(self, qt_app):
        """`A` used to select tracks[0] every time — which is not a cycle."""
        engine = _FakeEngine(audio=[(-1, "Disable"), (1, "A"), (2, "B"), (3, "C")])
        engine.selected_audio = 1
        controller = _controller(engine)

        controller.cycleAudioTrack()
        assert controller.currentAudioId == 2
        controller.cycleAudioTrack()
        assert controller.currentAudioId == 3

    def test_cycling_wraps_through_the_off_row(self, qt_app):
        engine = _FakeEngine(audio=[(-1, "Disable"), (1, "A")])
        engine.selected_audio = 1
        controller = _controller(engine)

        controller.cycleAudioTrack()

        assert controller.currentAudioId == TRACK_OFF_ID, (
            "off is a stop on the cycle — S must be able to turn subtitles off"
        )

    def test_cycling_an_empty_list_is_a_no_op(self, qt_app):
        engine = _FakeEngine(audio=[])
        engine.selected_audio = -1          # nothing to select, as libVLC reports it
        controller = _controller(engine)

        controller.cycleAudioTrack()  # must not raise

        assert controller.currentAudioId == -1
