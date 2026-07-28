"""Remembering the chosen audio/subtitle track per file — CHECKLIST §1.6.

Switch a film to Japanese, close the player, come back tomorrow: it should still
be Japanese, not whatever libVLC picks by default.

The design decision worth pinning down is **remember by label, not by id**.
libVLC assigns track ids per demuxer run and they are not stable across
sessions — id 2 might be Japanese today and the director's commentary tomorrow.
Restoring by id would silently play the wrong audio, which is worse than not
restoring at all. A label either matches or it cleanly does not.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication

from core.library import Library
from tests.support import build_controller

FILM = "/media/films/Andor.S02E01.mkv"


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def library(qt_app, tmp_path, monkeypatch):
    monkeypatch.setenv("HALCYON_DATA_DIR", str(tmp_path))
    lib = Library()
    lib._path = tmp_path / "recent.json"
    lib._entries = {}
    return lib


class _Engine:
    """libVLC's track surface, with its usual Disable pseudo-track."""

    def __init__(self, audio=None, subs=None):
        self._audio = audio if audio is not None else [
            (-1, "Disable"), (1, "English AC3 5.1"), (2, "Japanese AAC 2.0")
        ]
        self._subs = subs if subs is not None else [(-1, "Disable"), (4, "English")]
        self.selected_audio = 1
        self.selected_sub = -1
        self.currentMedia = "file://" + FILM

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


def _controller(engine, library, path=FILM):
    settings = MagicMock()
    settings.get.return_value = True
    controller = build_controller(engine, settings=settings, library=library)
    controller._resume_path = path
    controller._refresh_tracks()
    return controller


# ------------------------------------------------------------- the store ---
class TestLibraryStore:
    def test_a_choice_round_trips(self, library):
        library.remember_audio_track(FILM, "Japanese AAC 2.0")

        assert library.remembered_audio_track(FILM) == "Japanese AAC 2.0"

    def test_audio_and_subtitles_are_stored_separately(self, library):
        library.remember_audio_track(FILM, "Japanese AAC 2.0")
        library.remember_subtitle_track(FILM, "English")

        assert library.remembered_audio_track(FILM) == "Japanese AAC 2.0"
        assert library.remembered_subtitle_track(FILM) == "English"

    def test_an_unknown_file_remembers_nothing(self, library):
        assert library.remembered_audio_track("/m/other.mkv") == ""

    def test_it_shares_the_key_with_the_resume_position(self, library):
        """Same question, same entry — not a second store to keep in sync."""
        library.record_position(FILM, 60_000, 3_600_000)
        library.remember_audio_track("file://" + FILM, "Japanese AAC 2.0")

        assert len(library._entries) == 1
        assert library.remembered_audio_track(FILM) == "Japanese AAC 2.0"

    def test_it_survives_a_restart(self, library):
        library.remember_audio_track(FILM, "Japanese AAC 2.0")
        library.save()

        reopened = Library()
        reopened._path = library._path
        reopened._entries = {}
        reopened.load()

        assert reopened.remembered_audio_track(FILM) == "Japanese AAC 2.0"


# ------------------------------------------------------------- capturing ---
class TestRemembering:
    def test_selecting_a_track_files_its_label(self, library, qt_app):
        engine = _Engine()
        controller = _controller(engine, library)

        controller.setAudioTrack(2)

        assert library.remembered_audio_track(FILM) == "Japanese AAC 2.0", (
            "the label is stable across sessions; the id is not"
        )

    def test_the_hotkey_remembers_too(self, library, qt_app):
        """`A` is as explicit a choice as clicking the row (§4.1)."""
        engine = _Engine()
        controller = _controller(engine, library)

        controller.cycleAudioTrack()

        assert library.remembered_audio_track(FILM) == "Japanese AAC 2.0"

    def test_choosing_subtitles_is_remembered(self, library, qt_app):
        engine = _Engine()
        controller = _controller(engine, library)

        controller.setSubtitleTrack(4)

        assert library.remembered_subtitle_track(FILM) == "English"

    def test_turning_subtitles_off_is_a_choice_worth_remembering(self, library, qt_app):
        engine = _Engine()
        engine.selected_sub = 4
        controller = _controller(engine, library)

        controller.setSubtitleTrack(-1)

        assert library.remembered_subtitle_track(FILM) == "Off", (
            "'I do not want subtitles on this film' must survive too"
        )


# ------------------------------------------------------------- restoring ---
class TestRestoring:
    def test_the_remembered_track_is_re_selected(self, library, qt_app):
        library.remember_audio_track(FILM, "Japanese AAC 2.0")
        engine = _Engine()

        _controller(engine, library)

        assert engine.selected_audio == 2, "reopening should still be Japanese"

    def test_a_remembered_subtitle_is_re_selected(self, library, qt_app):
        library.remember_subtitle_track(FILM, "English")
        engine = _Engine()

        _controller(engine, library)

        assert engine.selected_sub == 4

    def test_nothing_remembered_leaves_the_default_alone(self, library, qt_app):
        engine = _Engine()

        _controller(engine, library)

        assert engine.selected_audio == 1, "libVLC's own default stands"

    def test_a_track_that_no_longer_exists_is_a_clean_miss(self, library, qt_app):
        """A different release of the same film may not have that dub."""
        library.remember_audio_track(FILM, "Japanese AAC 2.0")
        engine = _Engine(audio=[(-1, "Disable"), (1, "English AC3 5.1")])

        _controller(engine, library)

        assert engine.selected_audio == 1, "fall back, do not pick something random"

    def test_restoring_does_not_count_as_choosing(self, library, qt_app):
        """Restoring must not overwrite the memory it just read — otherwise a
        miss would erase the user's real preference."""
        library.remember_audio_track(FILM, "Japanese AAC 2.0")
        engine = _Engine(audio=[(-1, "Disable"), (1, "English AC3 5.1")])

        _controller(engine, library)

        assert library.remembered_audio_track(FILM) == "Japanese AAC 2.0", (
            "the preference survives a file that happens not to have that track"
        )

    def test_a_later_refresh_does_not_undo_an_in_session_switch(self, library, qt_app):
        """Attaching an external subtitle fires ESAdded, which refreshes tracks.
        That must not yank audio back to the remembered value."""
        library.remember_audio_track(FILM, "Japanese AAC 2.0")
        engine = _Engine()
        controller = _controller(engine, library)
        assert engine.selected_audio == 2

        controller.setAudioTrack(1)          # user switches to English
        controller._refresh_tracks()         # an ESAdded arrives

        assert engine.selected_audio == 1, "the in-session choice wins"

    def test_a_new_file_gets_its_own_restore(self, library, qt_app):
        library.remember_audio_track(FILM, "Japanese AAC 2.0")
        engine = _Engine()
        controller = _controller(engine, library)
        controller.setAudioTrack(1)

        # A different film starts; the latch must reset.
        other = "/media/films/Other.mkv"
        library.remember_audio_track(other, "Japanese AAC 2.0")
        engine.selected_audio = 1
        controller._on_media_changed("file://" + other)

        assert engine.selected_audio == 2
