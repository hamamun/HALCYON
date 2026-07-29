"""External subtitle naming — show actual filenames, not generic track numbers.

The reported failure: load a local subtitle file alongside a video. The subtitle
works fine, but the track list shows "Track 1", "Track 2" instead of the actual
filename. The user has no way to tell which subtitle is which.

What actually happened
----------------------
libVLC's video_get_spu_description() returns generic names like "Subtitle Track 1"
for external subtitles loaded via add_slave. The engine was passing these names
through unchanged, so the UI showed whatever VLC reported.

The fix is to track the filenames when add_subtitle_file is called, then match
them to tracks with generic names when subtitle_tracks() is called.
"""

from __future__ import annotations

import pytest


class TestGenericNameDetection:
    """The engine must recognize VLC's generic naming patterns."""

    def test_subtitle_track_number_is_generic(self):
        from engine.vlc_engine import VlcEngine

        assert VlcEngine._is_generic_subtitle_name("Subtitle Track 1")
        assert VlcEngine._is_generic_subtitle_name("Subtitle Track 23")

    def test_track_number_is_generic(self):
        from engine.vlc_engine import VlcEngine

        assert VlcEngine._is_generic_subtitle_name("Track 1")
        assert VlcEngine._is_generic_subtitle_name("Track 99")

    def test_subtitle_number_is_generic(self):
        from engine.vlc_engine import VlcEngine

        assert VlcEngine._is_generic_subtitle_name("Subtitle 1")

    def test_bracketed_number_is_generic(self):
        from engine.vlc_engine import VlcEngine

        assert VlcEngine._is_generic_subtitle_name("[0]")
        assert VlcEngine._is_generic_subtitle_name("[1]")

    def test_plain_number_is_generic(self):
        from engine.vlc_engine import VlcEngine

        assert VlcEngine._is_generic_subtitle_name("1")
        assert VlcEngine._is_generic_subtitle_name("42")

    def test_named_tracks_are_not_generic(self):
        from engine.vlc_engine import VlcEngine

        assert not VlcEngine._is_generic_subtitle_name("English")
        assert not VlcEngine._is_generic_subtitle_name("Japanese SDH")
        assert not VlcEngine._is_generic_subtitle_name("Director's Commentary")
        assert not VlcEngine._is_generic_subtitle_name("Forced")


class TestExternalSubtitleTracking:
    """The engine must store a real name when a subtitle is attached.

    These used to grep the source for one exact line, which passed happily
    while the *behaviour* was broken and then failed the moment the line was
    improved. ``subtitle_tracks`` is pure enough to call directly on an
    instance built with ``__new__`` — no libVLC, no window — so it is called.
    """

    def _engine(self, spu):
        """A VlcEngine with only the track-naming state, and a fake player."""
        from engine.vlc_engine import VlcEngine

        engine = VlcEngine.__new__(VlcEngine)
        engine._external_subtitle_names = {}
        engine._pending_external_subtitles = []
        engine._known_spu_ids = set()

        class _Player:
            def __init__(self, tracks):
                self.tracks = tracks

            def video_get_spu_description(self):
                return list(self.tracks)

        engine._player = _Player(spu)
        return engine

    def test_state_is_initialised(self):
        engine = self._engine([])

        assert engine._pending_external_subtitles == []
        assert engine._external_subtitle_names == {}

    def test_a_new_track_takes_the_pending_name(self):
        """The core of the bug: a fresh track must not stay "Track 3"."""
        engine = self._engine([(-1, "Disable"), (1, "English")])
        engine.subtitle_tracks()                       # establish what existed

        engine._player.tracks.append((3, "Track 3"))
        engine._pending_external_subtitles.append("Spanish")

        assert engine.subtitle_tracks() == [
            (-1, "Disable"),
            (1, "English"),
            (3, "Spanish"),
        ]

    def test_the_name_sticks_across_refreshes(self):
        engine = self._engine([(-1, "Disable")])
        engine.subtitle_tracks()
        engine._player.tracks.append((2, "Track 2"))
        engine._pending_external_subtitles.append("English SDH")
        engine.subtitle_tracks()

        assert engine.subtitle_tracks()[-1] == (2, "English SDH")

    def test_an_embedded_track_keeps_its_own_name(self):
        """A pending name must not be stapled to a track it did not create."""
        engine = self._engine([(-1, "Disable"), (1, "Japanese"), (2, "Track 2")])

        got = dict(engine.subtitle_tracks())

        assert got[1] == "Japanese"
        assert got[2] == "Track 2", "no slave was attached, so nothing to rename"

    def test_a_name_waits_for_a_track_that_has_not_appeared_yet(self):
        """ESAdded is asynchronous; the refresh can beat the track."""
        engine = self._engine([(-1, "Disable"), (1, "English")])
        engine.subtitle_tracks()
        engine._pending_external_subtitles.append("French")

        engine.subtitle_tracks()                       # track not published yet
        assert engine._pending_external_subtitles == ["French"], "the name is kept"

        engine._player.tracks.append((7, "Track 7"))
        assert engine.subtitle_tracks()[-1] == (7, "French")

    def test_a_slave_arriving_with_late_embedded_tracks_is_named(self):
        """Auto-load can beat libVLC's own subtitle discovery.

        Three tracks appear at once — two embedded, one the sidecar. libVLC
        appends slaves last, so the *last* fresh id is the sidecar. Claiming
        from the front named an embedded track instead and left the sidecar
        showing its number, which is the reported bug in another guise.
        """
        engine = self._engine([(-1, "Disable")])
        engine.subtitle_tracks()
        engine._player.tracks.extend([(1, "English"), (2, "Japanese"), (3, "Track 3")])
        engine._pending_external_subtitles.append("Spanish")

        got = dict(engine.subtitle_tracks())

        assert got[1] == "English"
        assert got[2] == "Japanese"
        assert got[3] == "Spanish"

    def test_an_unnamed_track_never_renders_blank(self):
        engine = self._engine([(-1, "Disable"), (4, "   ")])

        assert dict(engine.subtitle_tracks())[4] == "Track 4"


class TestSubtitleLabel:
    """What an attached subtitle file is *called* in the track list.

    The stem alone was the other half of the report: a downloaded subtitle is
    saved as ``<media stem>.<lang>.srt``, so the row read
    ``Andor.S02E01.1080p.WEB-DL.x265-GROUP.en`` — which elides, in a 340px
    popover, to something that identifies nothing.
    """

    def _label(self, name, media_stem):
        from pathlib import Path

        from engine.vlc_engine import _subtitle_label

        return _subtitle_label(Path(name), media_stem)

    def test_a_language_suffix_becomes_the_language(self):
        assert self._label("Andor.S02E01.en.srt", "Andor.S02E01") == "English"

    def test_a_three_letter_code_works_too(self):
        assert self._label("Movie.jpn.srt", "Movie") == "Japanese"

    def test_a_regional_tag_is_read_whole(self):
        """`pt-BR` must not split on the hyphen into "pt" and a stray "BR"."""
        assert self._label("Movie.pt-BR.srt", "Movie") == "Portuguese (BR)"

    def test_a_qualifier_is_kept_alongside_the_language(self):
        assert self._label("Movie.en.sdh.srt", "Movie") == "English SDH"
        assert self._label("Movie.eng.forced.srt", "Movie") == "English forced"

    def test_hi_is_hindi_alone_and_hearing_impaired_after_a_language(self):
        assert self._label("Movie.hi.srt", "Movie") == "Hindi"
        assert self._label("Movie.en.hi.srt", "Movie") == "English SDH"

    def test_a_users_own_name_is_shown_verbatim(self):
        assert self._label("my-custom-subs.srt", "Movie") == "my-custom-subs"

    def test_a_bare_sidecar_falls_back_to_the_filename(self):
        """`Movie.srt` beside `Movie.mkv` adds nothing — but must not be blank."""
        assert self._label("Movie.srt", "Movie") == "Movie"

    def test_an_unrelated_file_keeps_its_whole_name(self):
        assert self._label("Something.Else.srt", "Movie") == "Something.Else"


class TestQualifiedSidecarAutoLoad:
    """A downloaded subtitle must come back the next time the film is opened.

    ``core/subtitles._save`` writes ``<media stem>.<lang><ext>`` so two
    languages can sit side by side, and the Settings row promises the file
    lands "beside the media file so they auto-load next time". Auto-load only
    ever tried ``Path.with_suffix`` — ``Movie.srt`` — so ``Movie.en.srt`` was
    on disk, correct, and never looked for. The subtitle worked for the session
    it was downloaded in and then vanished.
    """

    def _controller(self, tmp_path, media_name="Movie.mkv"):
        from unittest.mock import MagicMock

        from tests.support import build_controller, null_library

        engine = MagicMock()
        engine.audio_tracks.return_value = []
        engine.subtitle_tracks.return_value = []
        controller = build_controller(engine, library=null_library())
        media = tmp_path / media_name
        media.write_bytes(b"video")
        return controller, engine, media

    def test_a_plain_sidecar_is_still_preferred(self, tmp_path):
        controller, engine, media = self._controller(tmp_path)
        (tmp_path / "Movie.srt").write_text("1\n")
        (tmp_path / "Movie.en.srt").write_text("1\n")

        controller._auto_load_subtitle(str(media))

        engine.add_subtitle_file.assert_called_once_with(str(tmp_path / "Movie.srt"))

    def test_a_language_qualified_sidecar_is_found(self, tmp_path):
        """The reported gap, directly."""
        controller, engine, media = self._controller(tmp_path)
        (tmp_path / "Movie.en.srt").write_text("1\n")

        controller._auto_load_subtitle(str(media))

        engine.add_subtitle_file.assert_called_once_with(str(tmp_path / "Movie.en.srt"))

    def test_only_one_subtitle_is_attached(self, tmp_path):
        """Several languages of the same film must not all load at once."""
        controller, engine, media = self._controller(tmp_path)
        for tag in ("en", "fr", "de"):
            (tmp_path / f"Movie.{tag}.srt").write_text("1\n")

        controller._auto_load_subtitle(str(media))

        assert engine.add_subtitle_file.call_count == 1

    def test_another_films_subtitle_is_not_picked_up(self, tmp_path):
        controller, engine, media = self._controller(tmp_path)
        (tmp_path / "Other.en.srt").write_text("1\n")

        controller._auto_load_subtitle(str(media))

        engine.add_subtitle_file.assert_not_called()

    def test_a_sibling_video_is_never_attached_as_a_subtitle(self, tmp_path):
        """The glob is by stem, so it sees every extension — filter properly."""
        controller, engine, media = self._controller(tmp_path)
        (tmp_path / "Movie.en.mkv").write_bytes(b"video")

        controller._auto_load_subtitle(str(media))

        engine.add_subtitle_file.assert_not_called()

    def test_nothing_on_disk_is_a_quiet_no_op(self, tmp_path):
        controller, engine, media = self._controller(tmp_path)

        controller._auto_load_subtitle(str(media))

        engine.add_subtitle_file.assert_not_called()

    def test_a_stem_with_glob_characters_is_escaped(self, tmp_path):
        """`Movie [2021].mkv` must not be read as a character class."""
        controller, engine, media = self._controller(tmp_path, "Movie [2021].mkv")
        (tmp_path / "Movie [2021].en.srt").write_text("1\n")

        controller._auto_load_subtitle(str(media))

        engine.add_subtitle_file.assert_called_once_with(
            str(tmp_path / "Movie [2021].en.srt")
        )


class TestAudioTrackNaming:
    """Audio tracks must read "English"/"Hindi", not "Track 1"/"Track 2".

    The earlier naming work fixed *subtitles* only; audio was never touched, so
    a dual-audio file still showed two meaningless rows and the only way to
    tell the dubs apart was to play each in turn.

    ``audio_get_track_description()`` returns the muxer's *title* field, which
    most releases leave empty — libVLC then synthesises "Track 1". The language
    is not missing, it is on the media's elementary-stream list
    (``media.tracks_get()``), so the two are joined by track id.
    """

    def _engine(self, description, languages):
        from engine.vlc_engine import VlcEngine

        class _Track:
            def __init__(self, tid, language):
                self.id = tid
                self.language = language

        class _Media:
            def __init__(self, tracks):
                self._tracks = tracks

            def tracks_get(self):
                return self._tracks

        class _Player:
            def __init__(self, description):
                self._description = description

            def audio_get_track_description(self):
                return list(self._description)

        class _Vlc:
            def libvlc_media_tracks_release(self, *args):
                pass

        engine = VlcEngine.__new__(VlcEngine)
        engine._player = _Player(description)
        engine._media = (
            _Media([_Track(tid, code) for tid, code in languages])
            if languages is not None
            else None
        )
        engine._vlc = _Vlc()
        return engine

    def test_placeholder_names_become_languages(self):
        """The reported case, directly."""
        engine = self._engine(
            [(-1, "Disable"), (1, "Track 1"), (2, "Track 2")],
            [(1, "eng"), (2, "hin")],
        )

        assert engine.audio_tracks() == [
            (-1, "Disable"),
            (1, "English"),
            (2, "Hindi"),
        ]

    def test_three_letter_and_two_letter_codes_both_work(self):
        engine = self._engine(
            [(-1, "Disable"), (1, "Track 1"), (2, "Track 2"), (3, "Track 3")],
            [(1, "eng"), (2, "ar"), (3, "jpn")],
        )

        assert [label for _, label in engine.audio_tracks()][1:] == [
            "English",
            "Arabic",
            "Japanese",
        ]

    def test_a_real_title_beats_the_language_code(self):
        """Someone who typed "Director's Commentary" said more than "eng"."""
        engine = self._engine(
            [(-1, "Disable"), (1, "Track 1"), (2, "Director's Commentary")],
            [(1, "eng"), (2, "eng")],
        )

        assert engine.audio_tracks()[2] == (2, "Director's Commentary")

    def test_two_tracks_of_one_language_stay_distinguishable(self):
        """"English" twice is no better than "Track 1" twice."""
        engine = self._engine(
            [(-1, "Disable"), (1, "Track 1"), (2, "Track 2")],
            [(1, "eng"), (2, "eng")],
        )

        labels = [label for _, label in engine.audio_tracks()]
        assert labels == ["Disable", "English 1", "English 2"]
        assert len(set(labels)) == len(labels), "every row must be unique"

    def test_the_off_row_is_never_renamed(self):
        engine = self._engine(
            [(-1, "Disable"), (1, "Track 1")], [(-1, "eng"), (1, "eng")]
        )

        assert engine.audio_tracks()[0] == (-1, "Disable")

    def test_no_language_information_leaves_the_list_alone(self):
        """Old behaviour must survive where there is nothing to improve on."""
        engine = self._engine([(-1, "Disable"), (1, "Track 1")], [])

        assert engine.audio_tracks() == [(-1, "Disable"), (1, "Track 1")]

    def test_an_unknown_language_code_is_not_invented(self):
        engine = self._engine([(-1, "Disable"), (1, "Track 1")], [(1, "qqq")])

        assert engine.audio_tracks() == [(-1, "Disable"), (1, "Track 1")]

    def test_nothing_open_is_safe(self):
        engine = self._engine([(-1, "Disable"), (1, "Track 1")], None)

        assert engine.audio_tracks() == [(-1, "Disable"), (1, "Track 1")]

    def test_a_failing_media_never_costs_the_track_list(self):
        """A nicer label is never worth losing the ability to pick a track."""
        engine = self._engine([(-1, "Disable"), (1, "Track 1")], [])

        class _Boom:
            def tracks_get(self):
                raise RuntimeError("libVLC said no")

        engine._media = _Boom()

        assert engine.audio_tracks() == [(-1, "Disable"), (1, "Track 1")]


class TestGenericTrackNameDetection:
    """Which labels are placeholders worth replacing."""

    def test_the_shapes_libvlc_synthesises_are_generic(self):
        from engine.vlc_engine import _is_generic_track_name

        for name in (
            "Track 1", "Track 12", "track 3", "Audio Track 2",
            "Subtitle Track 1", "Audio #2", "[0]", "7", "  Track 4  ", "", "-",
        ):
            assert _is_generic_track_name(name), name

    def test_a_chosen_title_is_not_generic(self):
        from engine.vlc_engine import _is_generic_track_name

        for name in (
            "English", "Hindi 5.1", "Director's Commentary",
            "Forced", "Track of the Cat", "Soundtrack 2",
        ):
            assert not _is_generic_track_name(name), name


class TestDownloadedSubtitleEndToEnd:
    """Download → save → attach → what the row actually reads.

    Point 2 and point 4 meet here: the click has to work on the first press,
    the file has to land somewhere that auto-loads next time, and the row has
    to say something a person can act on.
    """

    def test_a_bare_dedup_counter_is_not_a_label(self):
        """`_save` appends ".2" when it refuses to clobber an existing file.

        A download whose language tag the server omitted therefore lands as
        `Movie.2.srt`, and the row read "2" — the meaningless-number symptom
        arriving by a different route than the original "Track 2".
        """
        from pathlib import Path

        from engine.vlc_engine import _subtitle_label

        assert _subtitle_label(Path("Movie.2.srt"), "Movie") == "Movie.2"
        assert _subtitle_label(Path("Movie.3.srt"), "Movie") == "Movie.3"

    def test_a_counter_after_a_language_keeps_the_language(self):
        from pathlib import Path

        from engine.vlc_engine import _subtitle_label

        assert _subtitle_label(Path("Movie.en.2.srt"), "Movie") == "English 2"

    def test_a_downloaded_language_that_duplicates_an_embedded_one(self):
        """The realistic case, and the one that still read badly.

        A film ships an embedded English track; the user downloads English
        anyway (the embedded one is out of sync, say). Both resolve to
        "English", which is exactly as useless as two rows called "Track n".
        """
        from engine.vlc_engine import VlcEngine

        engine = VlcEngine.__new__(VlcEngine)
        engine._external_subtitle_names = {}
        engine._pending_external_subtitles = []
        engine._known_spu_ids = set()

        class _Player:
            def __init__(self):
                self.tracks = [(-1, "Disable"), (1, "English")]

            def video_get_spu_description(self):
                return list(self.tracks)

        engine._player = _Player()
        engine.subtitle_tracks()                      # establish what existed

        engine._player.tracks.append((2, "Track 2"))
        engine._pending_external_subtitles.append("English")

        labels = [label for _, label in engine.subtitle_tracks()]

        assert labels == ["Disable", "English 1", "English 2"]
        assert len(set(labels)) == len(labels), "every row must be tellable apart"

    def test_two_different_languages_are_left_alone(self):
        """Only duplicates get an ordinal; distinct names must not gain one."""
        from engine.vlc_engine import VlcEngine

        engine = VlcEngine.__new__(VlcEngine)
        engine._external_subtitle_names = {}
        engine._pending_external_subtitles = []
        engine._known_spu_ids = set()

        class _Player:
            def __init__(self):
                self.tracks = [(-1, "Disable"), (1, "English")]

            def video_get_spu_description(self):
                return list(self.tracks)

        engine._player = _Player()
        engine.subtitle_tracks()
        engine._player.tracks.append((2, "Track 2"))
        engine._pending_external_subtitles.append("Bengali")

        assert [label for _, label in engine.subtitle_tracks()] == [
            "Disable",
            "English",
            "Bengali",
        ]


class TestDownloadedSubtitleFilename:
    """Where a downloaded subtitle lands, and why it is not the server's name.

    OpenSubtitles returns names like
    ``Andor.S02E01.WEBRip.x264-ION10.English-WWW.MY-SUBS.CO.srt`` — a different
    release, plus a site advert. Saved verbatim, the stem would not match the
    video, so neither Halcyon nor VLC nor any other player would auto-load it
    next time. The extension and the language are taken from the server; the
    stem is taken from the media.
    """

    @pytest.fixture
    def service(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HALCYON_DATA_DIR", str(tmp_path / "profile"))
        from PySide6.QtCore import QCoreApplication

        from core.settings import Settings
        from core.subtitles import SubtitleService

        QCoreApplication.instance() or QCoreApplication([])
        settings = Settings(path=tmp_path / "profile" / "settings.json")
        return SubtitleService(settings)

    @pytest.fixture
    def media(self, tmp_path):
        target = tmp_path / "media" / "Andor.S02E01.1080p.WEB-DL.x265-GROUP.mkv"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"video")
        return target

    def test_the_saved_stem_matches_the_video(self, service, media):
        service.set_media(str(media))
        service._pending_download = {"fileId": 1, "language": "en"}

        saved = service._save(
            b"x", "Andor.S02E01.WEBRip.x264-ION10.English-WWW.MY-SUBS.CO.srt"
        )

        assert saved.stem.startswith(media.stem), (
            "the stem must match the video or nothing will auto-load it"
        )
        assert saved.name == f"{media.stem}.en.srt"
        assert saved.parent == media.parent

    def test_the_server_extension_is_honoured(self, service, media):
        """The *format* is the server's to decide; the stem is not."""
        service.set_media(str(media))
        service._pending_download = {"fileId": 1, "language": "en"}

        saved = service._save(b"x", "whatever.ass")

        assert saved.suffix == ".ass"

    def test_the_saved_file_is_what_auto_load_finds(self, service, media):
        """The round trip: what _save writes, _auto_load_subtitle must find."""
        from unittest.mock import MagicMock

        from tests.support import build_controller, null_library

        service.set_media(str(media))
        service._pending_download = {"fileId": 1, "language": "en"}
        saved = service._save(b"x", "server-name.srt")

        controller = build_controller(MagicMock(), library=null_library())
        controller._auto_load_subtitle(str(media))

        controller._engine.add_subtitle_file.assert_called_once_with(str(saved))
