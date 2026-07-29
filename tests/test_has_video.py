"""Test the has_video property to ensure subtitle features are properly disabled for audio-only content."""

from pathlib import Path
import pytest


def test_has_video_property_exists():
    """Verify the hasVideo property is exposed in VlcEngine."""
    source = (Path(__file__).parent.parent / "engine" / "vlc_engine.py").read_text()
    
    assert "def has_video(self)" in source, "has_video method must exist"
    assert "@Property(bool, notify=tracksChanged)" in source, "hasVideo must be a QML property"
    assert "def hasVideo(self)" in source, "hasVideo QML property must exist"


def test_is_video_normalises_vlc_file_uris_without_core_app_helper():
    """The engine is imported before/without core.app in several entry paths."""
    source = (Path(__file__).parent.parent / "engine" / "vlc_engine.py").read_text()

    is_video_property = source.split("def isVideo(self)", 1)[1].split("def hasVideo(self)", 1)[0]
    assert "paths.normalise_path(self._current_mrl)" in is_video_property
    assert "_from_uri" not in is_video_property


def test_has_video_checks_video_tracks():
    """Verify has_video checks for video tracks correctly."""
    source = (Path(__file__).parent.parent / "engine" / "vlc_engine.py").read_text()
    
    # Should use video_get_track_description
    assert "video_get_track_description" in source, "Must check video tracks"
    
    # Should filter out disable track (id=-1)
    assert "tid != -1" in source or "tid == -1" in source, "Must filter disable track"


def test_popover_disables_subtitle_buttons_without_video():
    """Verify TrackPopover disables subtitle buttons when there's no video."""
    source = (Path(__file__).parent.parent / "ui" / "transport" / "TrackPopover.qml").read_text()
    
    # Should have hasVideo property
    assert "readonly property bool hasVideo" in source, "Must define hasVideo property"
    
    # Should check Player.hasVideo
    assert "Player.hasVideo" in source, "Must check Player.hasVideo"
    
    # "From file" button should be disabled without video
    from_file_section = source.split('"From file')[1].split("}")[0]
    assert "enabled: root.hasVideo" in from_file_section, "From file button must check hasVideo"
    
    # "Search online" button should be disabled without video
    search_section = source.split('"Search online')[1].split("}")[0]
    assert "root.hasVideo" in search_section, "Search online button must check hasVideo"
