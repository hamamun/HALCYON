"""Tests for Metadata parsing and details formatting in core/metadata.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

vlc = pytest.importorskip("vlc", reason="python-vlc is needed for metadata enums")

from core.metadata import Metadata, _clean_str, _fmt_bitrate, _fmt_duration, _fmt_size, _fourcc


def test_fmt_size():
    assert _fmt_size(0) == "\u2014"
    assert _fmt_size(-100) == "\u2014"
    assert _fmt_size(500) == "500 B"
    assert _fmt_size(1024) == "1.0 KB"
    assert _fmt_size(1500000) == "1.4 MB"
    assert _fmt_size(1500000000) == "1.4 GB"


def test_clean_str():
    assert _clean_str(None) == ""
    assert _clean_str("") == ""
    assert _clean_str(b"eng") == "eng"
    assert _clean_str("English") == "English"


def test_fourcc():
    assert _fourcc(0) == ""
    codec_mp3 = int.from_bytes(b"MP3 ", "little")
    assert _fourcc(codec_mp3) == "MP3"


def test_audio_metadata_details(tmp_path):
    file_path = tmp_path / "song.mp3"
    file_path.write_bytes(b"0" * 1024 * 500)  # 500 KB file

    media = MagicMock()
    media.get_duration.return_value = 180000  # 3 minutes
    meta_dict = {
        vlc.Meta.Title: "Test Title",
        vlc.Meta.Artist: "Test Artist",
        vlc.Meta.Album: "Test Album",
        vlc.Meta.Genre: "Rock",
        vlc.Meta.Date: "2024",
        vlc.Meta.TrackNumber: "4",
        vlc.Meta.TrackTotal: "12",
        vlc.Meta.ArtworkURL: "file:///tmp/art.jpg",
    }
    media.get_meta.side_effect = lambda k: meta_dict.get(k, "")

    audio_track = MagicMock()
    audio_track.type = vlc.TrackType.audio
    audio_track.codec = int.from_bytes(b"MP3 ", "little")
    audio_track.bitrate = 320000
    audio_track.audio = MagicMock()
    audio_track.audio.contents.channels = 2
    audio_track.audio.contents.rate = 44100
    audio_track.language = b"eng"

    media.tracks_get.return_value = [audio_track]

    engine = MagicMock()
    engine.raw_player.get_media.return_value = media

    metadata = Metadata(engine)
    metadata.load(str(file_path))

    details = metadata.details
    labels = [d["label"] for d in details]
    assert "File" in labels
    assert "File size" in labels
    assert "Container" in labels
    assert "Duration" in labels
    assert "Album" in labels
    assert "Track" in labels
    assert "Genre" in labels
    assert "Year" in labels
    assert "Audio codec" in labels
    assert "Channels" in labels
    assert "Bitrate" in labels

    # Audio files should not have video or subtitle labels
    assert "Resolution" not in labels
    assert "Video codec" not in labels
    assert "Subtitles" not in labels
    assert "Subtitle" not in labels


def test_video_metadata_details(tmp_path):
    file_path = tmp_path / "movie.mkv"
    file_path.write_bytes(b"0" * 1024 * 1024 * 5)  # 5 MB file

    media = MagicMock()
    media.get_duration.return_value = 7200000  # 2 hours
    meta_dict = {
        vlc.Meta.Title: "Test Movie",
        vlc.Meta.Artist: "",
        vlc.Meta.Album: "",
        vlc.Meta.Genre: "",
        vlc.Meta.Date: "",
        vlc.Meta.TrackNumber: "",
        vlc.Meta.TrackTotal: "",
        vlc.Meta.ArtworkURL: "",
    }
    media.get_meta.side_effect = lambda k: meta_dict.get(k, "")

    video_track = MagicMock()
    video_track.type = vlc.TrackType.video
    video_track.codec = int.from_bytes(b"h264", "little")
    video_track.video = MagicMock()
    video_track.video.contents.width = 1920
    video_track.video.contents.height = 1080
    video_track.video.contents.frame_rate_num = 24
    video_track.video.contents.frame_rate_den = 1

    audio_track1 = MagicMock()
    audio_track1.type = vlc.TrackType.audio
    audio_track1.codec = int.from_bytes(b"mp4a", "little")
    audio_track1.bitrate = 192000
    audio_track1.audio = MagicMock()
    audio_track1.audio.contents.channels = 2
    audio_track1.audio.contents.rate = 48000
    audio_track1.language = b"eng"

    audio_track2 = MagicMock()
    audio_track2.type = vlc.TrackType.audio
    audio_track2.codec = int.from_bytes(b"mp4a", "little")
    audio_track2.bitrate = 192000
    audio_track2.audio = MagicMock()
    audio_track2.audio.contents.channels = 6
    audio_track2.audio.contents.rate = 48000
    audio_track2.language = b"jpn"

    sub_track1 = MagicMock()
    sub_track1.type = getattr(vlc.TrackType, "ext", getattr(vlc.TrackType, "text", 2))
    sub_track1.codec = int.from_bytes(b"subt", "little")
    sub_track1.language = b"eng"
    sub_track1.description = b"English"

    sub_track2 = MagicMock()
    sub_track2.type = getattr(vlc.TrackType, "ext", getattr(vlc.TrackType, "text", 2))
    sub_track2.codec = int.from_bytes(b"subt", "little")
    sub_track2.language = b"spa"
    sub_track2.description = b"Spanish"

    media.tracks_get.return_value = [video_track, audio_track1, audio_track2, sub_track1, sub_track2]

    engine = MagicMock()
    engine.raw_player.get_media.return_value = media

    metadata = Metadata(engine)
    metadata.load(str(file_path))

    details = metadata.details
    labels = [d["label"] for d in details]
    assert "Resolution" in labels
    assert "Frame rate" in labels
    assert "Video codec" in labels
    assert "Audio codec" in labels
    assert "Audio codec #2" in labels
    assert "Subtitles" in labels

    # Check value formatting
    sub_row = next(d for d in details if d["label"] == "Subtitles")
    assert "eng (SUBT)" in sub_row["value"] or "English (SUBT)" in sub_row["value"]
    assert "spa (SUBT)" in sub_row["value"] or "Spanish (SUBT)" in sub_row["value"]

    # Since Album/Genre/Year are empty for video, they should be omitted
    assert "Album" not in labels
    assert "Genre" not in labels
    assert "Year" not in labels
