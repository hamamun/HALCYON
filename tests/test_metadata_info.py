"""Metadata groups used by the right-side Info tab.

The media object is fake, but the track structures are the real python-vlc
structures.  This keeps the test independent of a VLC installation while still
checking the shape and values that the application receives from libVLC.
"""

from __future__ import annotations

import ctypes

import vlc

from core.metadata import Metadata


def _codec(text: bytes) -> int:
    return int.from_bytes(text, "little")


class FakeMedia:
    def __init__(self, tracks, tags=None, duration=3723000):
        self._tracks = tracks
        self._tags = tags or {}
        self._duration = duration

    def parse_with_options(self, _flags, _timeout):
        return None

    def get_meta(self, key):
        return self._tags.get(key, "")

    def get_duration(self):
        return self._duration

    def tracks_get(self):
        return self._tracks


class FakePlayer:
    def __init__(self, media, current_audio=2):
        self._media = media
        self._current_audio = current_audio

    def get_media(self):
        return self._media

    def current_audio_track(self):
        return self._current_audio


class FakeEngine:
    def __init__(self, media, current_audio=2):
        self.raw_player = FakePlayer(media, current_audio)

    def current_audio_track(self):
        return self.raw_player.current_audio_track()


def _video_track():
    video = vlc.VideoTrack()
    video.width = 1920
    video.height = 1080
    video.sar_num = 1
    video.sar_den = 1
    video.frame_rate_num = 24
    video.frame_rate_den = 1

    track = vlc.MediaTrack()
    track.codec = _codec(b"h264")
    track.id = 1
    track.type = vlc.TrackType.video
    track.profile = 100
    track.video = ctypes.pointer(video)
    return track


def _audio_track():
    audio = vlc.AudioTrack()
    audio.channels = 6
    audio.rate = 48000

    track = vlc.MediaTrack()
    track.codec = _codec(b"mp4a")
    track.id = 2
    track.type = vlc.TrackType.audio
    track.audio = ctypes.pointer(audio)
    return track


def test_info_groups_include_requested_file_stream_and_music_data(qt_application, tmp_path):
    media = FakeMedia(
        [_video_track(), _audio_track()],
        tags={
            vlc.Meta.Title: "Tagged title",
            vlc.Meta.Artist: "Artist",
            vlc.Meta.Album: "Album",
            vlc.Meta.AlbumArtist: "Album artist",
            vlc.Meta.Genre: "Rock",
            vlc.Meta.Date: "2024-01-01",
            vlc.Meta.TrackNumber: "3",
            vlc.Meta.DiscNumber: "1",
            vlc.Meta.Publisher: "Publisher",
        },
    )
    path = tmp_path / "movie.mkv"
    path.write_bytes(b"x" * 2048)

    metadata = Metadata(FakeEngine(media))
    metadata.load(str(path))

    assert metadata.fileDetails == [
        {"label": "File name", "value": "movie.mkv"},
        {"label": "Location", "value": str(path.resolve())},
        {"label": "File size", "value": "2 KB"},
        {"label": "Extension", "value": "MKV"},
    ]
    assert {row["label"] for row in metadata.generalDetails} == {
        "Title",
        "Duration",
        "Media type",
    }
    assert {row["label"] for row in metadata.videoDetails} == {
        "Resolution",
        "Aspect ratio",
        "Frame rate",
        "Video codec",
        "Video profile",
    }
    assert {row["label"] for row in metadata.audioDetails} == {
        "Audio codec",
        "Audio tracks",
        "Channels",
        "Channel layout",
        "Sample rate",
    }
    assert {row["label"] for row in metadata.musicDetails} == {
        "Artist",
        "Album",
        "Album artist",
        "Genre",
        "Release year",
        "Track number",
        "Disc number",
        "Publisher",
    }
    assert not any(row["label"] == "Bitrate" for row in metadata.audioDetails)


def test_untagged_audio_does_not_repeat_filename_as_title(qt_application, tmp_path):
    audio = _audio_track()
    media = FakeMedia([audio], duration=60000)
    path = tmp_path / "untagged.mp3"
    path.write_bytes(b"audio")

    metadata = Metadata(FakeEngine(media))
    metadata.load(str(path))

    assert metadata.mediaType == "Audio"
    assert not any(row["label"] == "Title" for row in metadata.generalDetails)
    assert any(row["label"] == "File name" for row in metadata.fileDetails)
    assert not metadata.videoDetails
