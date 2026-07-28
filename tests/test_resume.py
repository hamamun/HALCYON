"""Resume — why it never appeared, and the rules it should follow.

The report: "my player is supposed to have save and resume/start over, only for
video, working across sessions — but I have never seen it."

Three independent faults, each sufficient on its own to make the feature
invisible:

1. **The save key and the lookup key were different strings.** A position was
   recorded under the path derived from libVLC's MRL and looked up under the
   path the playlist holds. On Windows those differ by path separator
   (``E:\\x\\a.mkv`` vs ``E:/x/a.mkv``), so the dict lookup missed every time
   and ``resume_position`` returned 0 forever. Nothing errored.
2. **Nothing listened to the signal.** ``AppController.resumePrompted`` was
   emitted from the day it was written, and no QML ever connected to it. Even a
   working lookup would have restored the position in silence, with no notice
   and no way to decline.
3. **There was no "start over".** The plan calls for it; there was no code path
   that discarded a saved position.

Plus the rule that was never enforced: resume is **video only**. An album track
does not want a prompt.
"""

from __future__ import annotations

import json
import sys

import pytest
from PySide6.QtCore import QCoreApplication

from core.library import (
    RESUME_MIN_POSITION_MS,
    Library,
    entry_key,
)


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


FILM = "/media/films/Arrival.mkv"
SONG = "/media/music/Weightless.flac"
HOUR = 3_600_000


# ------------------------------------------------------------------ keys ---
class TestEntryKey:
    """Fault 1. One file, one key, whichever direction it arrived from."""

    def test_a_windows_path_and_its_mrl_form_agree(self):
        from_playlist = entry_key(r"E:\drvie personal\Andor.mkv")
        from_mrl = entry_key("file:///E:/drvie%20personal/Andor.mkv")

        assert from_playlist == from_mrl, (
            "positions were saved under one and looked up under the other, so "
            "resume silently never fired on Windows"
        )

    def test_a_posix_path_and_its_file_url_agree(self):
        assert entry_key(FILM) == entry_key("file://" + FILM)

    def test_percent_encoding_is_decoded(self):
        assert entry_key("file:///m/A%20Film.mkv") == entry_key("/m/A Film.mkv")

    def test_separators_are_normalised(self):
        assert entry_key(r"C:\a\b\c.mkv") == entry_key("C:/a/b/c.mkv")

    def test_a_trailing_slash_does_not_make_a_second_entry(self):
        assert entry_key("/m/dir/") == entry_key("/m/dir")

    def test_empty_input_is_empty(self):
        assert entry_key("") == ""

    @pytest.mark.skipif(sys.platform != "win32", reason="NTFS is case-insensitive")
    def test_case_is_folded_on_windows(self):
        assert entry_key(r"E:\M\Andor.mkv") == entry_key(r"e:\m\andor.mkv")

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX is case-sensitive")
    def test_case_is_significant_on_posix(self):
        assert entry_key("/m/Andor.mkv") != entry_key("/m/andor.mkv")


# --------------------------------------------------------------- round trip ---
class TestResumeRoundTrip:
    def test_a_position_saved_by_mrl_is_found_by_playlist_path(self, library):
        """The exact failure, end to end."""
        library.record_position("file://" + FILM, 24 * 60_000, HOUR)

        assert library.resume_position(FILM) == 24 * 60_000

    def test_nothing_is_offered_for_an_unknown_file(self, library):
        assert library.resume_position("/media/films/Never.mkv") == 0

    def test_below_the_threshold_nothing_is_offered(self, library):
        library.record_position(FILM, RESUME_MIN_POSITION_MS - 1, HOUR)

        assert library.resume_position(FILM) == 0, "§P1.5 — more than 30 s in"

    def test_at_the_threshold_a_resume_is_offered(self, library):
        library.record_position(FILM, RESUME_MIN_POSITION_MS + 1, HOUR)

        assert library.resume_position(FILM) > 0

    def test_a_nearly_finished_film_is_not_offered(self, library):
        library.record_position(FILM, int(HOUR * 0.99), HOUR)

        assert library.resume_position(FILM) == 0, "§P1.5 — more than 5% remaining"

    def test_start_over_discards_the_position(self, library):
        library.record_position(FILM, 24 * 60_000, HOUR)
        library.clear_position(FILM)

        assert library.resume_position(FILM) == 0, (
            "otherwise the next open re-offers the point the user just rejected"
        )

    def test_start_over_accepts_the_other_path_form(self, library):
        library.record_position(FILM, 24 * 60_000, HOUR)
        library.clear_position("file://" + FILM)

        assert library.resume_position(FILM) == 0


# --------------------------------------------------------------- video only ---
class TestVideoOnly:
    def test_audio_is_never_offered_a_resume(self, library):
        library.record_position(SONG, 40_000, 300_000)

        assert library.resume_position(SONG) == 0, (
            "an album track 40 s in does not want a prompt on every play"
        )

    def test_video_is(self, library):
        library.record_position(FILM, 40_000, HOUR)

        assert library.resume_position(FILM) == 40_000

    def test_the_position_is_still_recorded_for_audio(self, library):
        """Only the *prompt* is video-only; the recent list still wants it."""
        library.record_position(SONG, 40_000, 300_000)

        assert library._entries[entry_key(SONG)]["position"] == 40_000


# -------------------------------------------------------------- persistence ---
class TestAcrossSessions:
    def test_a_position_survives_a_restart(self, library, tmp_path):
        library.record_position(FILM, 24 * 60_000, HOUR)
        library.save()

        reopened = Library()
        reopened._path = library._path
        reopened._entries = {}
        reopened.load()

        assert reopened.resume_position(FILM) == 24 * 60_000, (
            "'across sessions' is the whole feature"
        )

    def test_a_file_written_by_an_older_build_is_re_keyed_on_load(
        self, library, tmp_path
    ):
        """An existing recent.json must keep working, not be silently ignored."""
        legacy = {
            "entries": [
                {
                    "path": "file://" + FILM,
                    "title": "Arrival",
                    "position": 24 * 60_000,
                    "duration": HOUR,
                }
            ]
        }
        library._path.write_text(json.dumps(legacy), encoding="utf-8")
        library._entries = {}
        library.load()

        assert library.resume_position(FILM) == 24 * 60_000


# ------------------------------------------------------------- controller ---
class TestControllerWiring:
    def _controller(self, library, settings=None):
        from unittest.mock import MagicMock

        from tests.support import build_controller

        settings = settings or MagicMock()
        settings.get.return_value = True
        engine = MagicMock()
        engine.audio_tracks.return_value = []
        engine.subtitle_tracks.return_value = []
        engine.current_audio_track.return_value = -1
        engine.current_subtitle_track.return_value = -1
        controller = build_controller(engine, settings=settings, library=library)
        return controller, engine

    def test_opening_a_resumable_film_announces_it(self, library, qt_app):
        library.record_position(FILM, 24 * 60_000, HOUR)
        controller, engine = self._controller(library)
        seen = []
        controller.resumePrompted.connect(lambda p, ms: seen.append((p, ms)))

        controller.openPath(FILM)

        assert seen == [(FILM, 24 * 60_000)]
        engine.open.assert_called_once_with(FILM, 24 * 60_000)

    def test_the_file_opens_at_the_resume_point_not_at_zero(self, library, qt_app):
        """No restart-then-jump: the prompt is an undo, not a gate."""
        library.record_position(FILM, 24 * 60_000, HOUR)
        controller, engine = self._controller(library)

        controller.openPath(FILM)

        assert engine.open.call_args[0][1] == 24 * 60_000

    def test_a_song_is_opened_from_the_start_with_no_prompt(self, library, qt_app):
        library.record_position(SONG, 40_000, 300_000)
        controller, engine = self._controller(library)
        seen = []
        controller.resumePrompted.connect(lambda p, ms: seen.append(p))

        controller.openPath(SONG)

        assert seen == []
        assert engine.open.call_args[0][1] == 0

    def test_the_settings_toggle_suppresses_the_resume(self, library, qt_app):
        from unittest.mock import MagicMock

        library.record_position(FILM, 24 * 60_000, HOUR)
        settings = MagicMock()
        settings.get.side_effect = lambda key, default=None: (
            False if key == "playback.resumeEnabled" else default
        )
        controller, engine = self._controller(library, settings=settings)

        controller.openPath(FILM)

        assert engine.open.call_args[0][1] == 0

    def test_start_over_seeks_to_zero_and_forgets(self, library, qt_app):
        library.record_position(FILM, 24 * 60_000, HOUR)
        controller, engine = self._controller(library)
        controller.openPath(FILM)

        controller.startOver()

        engine.seek.assert_called_once_with(0)
        assert library.resume_position(FILM) == 0
