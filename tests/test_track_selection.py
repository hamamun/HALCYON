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


# --------------------------------------------------- auto-select default ---
class TestAutoSelectDefaultAudio:
    """When a video loads with multiple audio tracks and none is selected,
    the first real audio track should be automatically selected."""

    def test_first_audio_track_is_selected_when_none_is_active(self, qt_app):
        """If libVLC reports -1 (disabled) but real tracks exist, select the first."""
        engine = _FakeEngine(audio=[(-1, "Disable"), (1, "English"), (2, "Japanese")])
        engine.selected_audio = -1  # VLC reports disabled
        controller = _controller(engine)

        assert controller.currentAudioId == 1, (
            "when no audio track is selected, the first real track should be "
            "auto-selected so the user hears audio immediately"
        )
        assert engine.selected_audio == 1

    def test_no_auto_selection_when_a_track_is_already_active(self, qt_app):
        """If a real track is already selected, don't override it."""
        engine = _FakeEngine(audio=[(-1, "Disable"), (1, "English"), (2, "Japanese")])
        engine.selected_audio = 2  # User already has Japanese selected
        controller = _controller(engine)

        assert controller.currentAudioId == 2, (
            "auto-selection must not override an already-selected track"
        )
        assert engine.selected_audio == 2

    def test_no_auto_selection_when_no_real_tracks_exist(self, qt_app):
        """If there are no real audio tracks, don't try to select anything."""
        engine = _FakeEngine(audio=[(-1, "Disable")])
        engine.selected_audio = -1
        controller = _controller(engine)

        assert controller.currentAudioId == -1, (
            "with no real tracks, the selection should remain disabled"
        )


# ------------------------------------------------- turning audio *off* ---
class TestAudioOffStaysOff:
    """Choosing "Off" in the audio section must stick.

    The reported failure: "subtitle section from multimedia audio channel off
    not allowing to set" — clicking the pinned Off row in the gear popover's
    Audio section did nothing, or lit up for an instant and snapped back to a
    real track.

    What actually happened
    ----------------------
    ``_auto_select_default_audio`` — the rescue for files libVLC opens with no
    audio selected — ran on *every* ``_refresh_tracks``. Turning audio off is a
    selection of id -1, and libVLC raises ``tracksChanged`` freely (ESAdded,
    ESDeleted, an attached .srt, a re-opened demuxer). Each of those refreshes
    saw "current == -1 and real tracks exist" and switched the audio straight
    back on. The rescue was overwriting the user, once per event, so Off could
    never be made to stay.

    It is now one shot per media, and never fires after an explicit choice.
    """

    def test_selecting_off_is_not_undone_by_a_track_refresh(self, qt_app):
        engine = _FakeEngine(audio=[(-1, "Disable"), (1, "English"), (2, "Japanese")])
        engine.selected_audio = 1
        controller = _controller(engine)

        controller.setAudioTrack(TRACK_OFF_ID)
        controller._refresh_tracks()          # as libVLC's ESAdded would

        assert engine.selected_audio == TRACK_OFF_ID, (
            "the auto-select rescue must never overrule an explicit choice"
        )
        assert controller.currentAudioId == TRACK_OFF_ID

    def test_off_survives_many_refreshes(self, qt_app):
        """One refresh passing is luck; the events arrive in bursts."""
        engine = _FakeEngine(audio=[(-1, "Disable"), (1, "English")])
        controller = _controller(engine)
        controller.setAudioTrack(TRACK_OFF_ID)

        for _ in range(10):
            controller._refresh_tracks()

        assert controller.currentAudioId == TRACK_OFF_ID

    def test_cycling_onto_off_also_sticks(self, qt_app):
        """`A` is as explicit as clicking the row, and can land on Off."""
        engine = _FakeEngine(audio=[(-1, "Disable"), (1, "English")])
        engine.selected_audio = 1
        controller = _controller(engine)

        controller.cycleAudioTrack()          # wraps onto Off
        controller._refresh_tracks()

        assert controller.currentAudioId == TRACK_OFF_ID

    def test_the_rescue_still_fires_once_for_a_fresh_file(self, qt_app):
        """The guard must not disable the behaviour it is guarding."""
        engine = _FakeEngine(audio=[(-1, "Disable"), (1, "English")])
        engine.selected_audio = -1
        controller = _controller(engine)

        assert controller.currentAudioId == 1, "silence on open is still rescued"

    def test_the_rescue_does_not_fire_twice(self, qt_app):
        """Having rescued once, a later -1 is the user's business."""
        engine = _FakeEngine(audio=[(-1, "Disable"), (1, "English")])
        engine.selected_audio = -1
        controller = _controller(engine)
        assert engine.selected_audio == 1

        engine.selected_audio = -1            # user turns it off elsewhere
        controller._refresh_tracks()

        assert engine.selected_audio == -1

    def test_a_new_file_gets_its_own_rescue(self, qt_app):
        """The latches are per media, not for the life of the process."""
        from unittest.mock import MagicMock

        engine = _FakeEngine(audio=[(-1, "Disable"), (1, "English")])
        controller = _controller(engine)
        # _on_media_changed reads the sidecar setting; the builder leaves the
        # store as None because most tests never reach it.
        controller._settings = MagicMock()
        controller._settings.get.return_value = False
        controller.setAudioTrack(TRACK_OFF_ID)

        engine.selected_audio = -1
        controller._on_media_changed("file:///next.mkv")

        assert controller.currentAudioId == 1, (
            "turning audio off for one film must not leave the next one silent"
        )

    def test_choosing_a_real_track_is_also_respected(self, qt_app):
        engine = _FakeEngine(audio=[(-1, "Disable"), (1, "English"), (2, "Japanese")])
        controller = _controller(engine)

        controller.setAudioTrack(2)
        controller._refresh_tracks()

        assert engine.selected_audio == 2


# ------------------------------------------- subtitles are not disturbed ---
class TestSubtitleSelectionIsUntouched:
    """The audio rescue must not have grown a subtitle equivalent.

    Subtitles default to off *on purpose*; auto-selecting one would put
    unwanted text over every video.
    """

    def test_subtitles_are_never_auto_selected(self, qt_app):
        engine = _FakeEngine(subs=[(-1, "Disable"), (4, "English")])
        engine.selected_sub = -1
        controller = _controller(engine)

        assert controller.currentSubtitleId == TRACK_OFF_ID
        assert engine.selected_sub == TRACK_OFF_ID

    def test_turning_subtitles_off_sticks(self, qt_app):
        engine = _FakeEngine(subs=[(-1, "Disable"), (4, "English")])
        engine.selected_sub = 4
        controller = _controller(engine)

        controller.setSubtitleTrack(TRACK_OFF_ID)
        controller._refresh_tracks()

        assert controller.currentSubtitleId == TRACK_OFF_ID


# ----------------------------------- re-entrant track refresh safety ---
class TestReentrantTrackRefresh:
    def test_auto_select_default_audio_does_not_recurse_infinitely(self, qt_app):
        """When set_audio_track emits tracksChanged synchronously, _refresh_tracks
        must not recurse infinitely and crash the application."""
        from tests.support import build_controller, null_library

        class _ReentrantEngine(_FakeEngine):
            def __init__(self):
                super().__init__(audio=[(-1, "Disable"), (1, "English"), (2, "Hindi")])
                self.selected_audio = -1
                self.controller = None

            def set_audio_track(self, track_id):
                self.selected_audio = int(track_id)
                if self.controller is not None:
                    # Simulate synchronous signal emission calling _refresh_tracks
                    self.controller._refresh_tracks()

        engine = _ReentrantEngine()
        controller = build_controller(engine, library=null_library())
        engine.controller = controller

        # Trigger track refresh which triggers auto_select_default_audio
        controller._refresh_tracks()

        assert controller.currentAudioId == 1
        assert engine.selected_audio == 1
