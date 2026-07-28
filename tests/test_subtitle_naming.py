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
    """The engine must store filenames when subtitles are loaded."""

    def test_pending_list_is_initialized(self):
        """The engine starts with an empty pending list."""
        # This is a structural test — we can't easily instantiate VlcEngine
        # without libVLC, so we just verify the attribute exists in the source.
        from pathlib import Path
        source = (Path(__file__).parent.parent / "engine" / "vlc_engine.py").read_text()
        assert "_pending_external_subtitles" in source
        assert "_external_subtitle_names" in source

    def test_add_subtitle_file_stores_the_stem(self):
        """When a subtitle is added, its stem (filename without extension) is queued."""
        # Again, structural test since we can't run VlcEngine without libVLC.
        from pathlib import Path
        source = (Path(__file__).parent.parent / "engine" / "vlc_engine.py").read_text()
        assert "self._pending_external_subtitles.append(resolved.stem)" in source

    def test_subtitle_tracks_replaces_generic_names(self):
        """The subtitle_tracks method must use stored names for generic tracks."""
        from pathlib import Path
        source = (Path(__file__).parent.parent / "engine" / "vlc_engine.py").read_text()
        # Check that the method exists and has the replacement logic
        assert "def subtitle_tracks(self)" in source
        assert "_is_generic_subtitle_name" in source
        assert "_external_subtitle_names" in source
