"""Pure-Python unit tests for core.metadata — no libVLC, no QtGui.

The libVLC-touching paths (``_read``, ``_append_tracks``, ``_poll_live_stats``)
cannot run without a real libVLC build, so these cover everything that can be
tested headless: formatting helpers, the track-type normaliser and the object's
no-media lifecycle. The rest is exercised on Windows via the running app.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.metadata import (
    _CODEC_NAMES,
    _codec_name,
    _fmt_aspect,
    _fmt_bitrate,
    _fmt_duration,
    _fmt_live_bitrate,
    _fmt_profile_level,
    _fmt_size,
    _fourcc,
    _text,
    _track_type,
    Metadata,
)


# ------------------------------------------------------------ formatting ---
class TestFormatting:
    def test_duration_hours_minutes_seconds(self):
        assert _fmt_duration(0) == "\u2014"
        assert _fmt_duration(65_000) == "1:05"
        assert _fmt_duration(3_661_000) == "1:01:01"

    def test_size_human_readable(self):
        assert _fmt_size(0) == "\u2014"
        assert _fmt_size(512) == "512 B"
        assert _fmt_size(1_500) == "1.5 KB"
        assert _fmt_size(5_242_880) == "5.0 MB"
        assert _fmt_size(5_000_000_000) == "4.7 GB"

    def test_bitrate(self):
        assert _fmt_bitrate(0) == "\u2014"
        assert _fmt_bitrate(128_000) == "128 kbps"
        assert _fmt_bitrate(3_500_000) == "3.50 Mbps"

    def test_live_bitrate_blank_when_idle(self):
        assert _fmt_live_bitrate(0) == ""
        assert _fmt_live_bitrate(0.0) == ""
        assert _fmt_live_bitrate(192_000.0) == "192 kbps"
        assert _fmt_live_bitrate(2_400_000.0) == "2.40 Mbps"

    def test_aspect_ratio(self):
        assert _fmt_aspect(1920, 1080, 1, 1) == "16:9"
        assert _fmt_aspect(640, 480, 1, 1) == "4:3"
        assert _fmt_aspect(0, 1080, 1, 1) == ""
        # Anamorphic: 720x576 with a 64:45 SAR is 16:9 display aspect.
        assert _fmt_aspect(720, 576, 64, 45) == "16:9"
        # Very wide cinema shapes collapse to a decimal.
        value = _fmt_aspect(4096, 1716, 1, 1)
        assert value.endswith(":1")

    def test_profile_level(self):
        assert _fmt_profile_level("H264", 100, 40) == "High@L4.0"
        assert _fmt_profile_level("H264", 77, 51) == "Main@L5.1"
        assert _fmt_profile_level("H264", 0, 40) == ""          # no profile
        assert _fmt_profile_level("HEVC", 2, 123) == "Main 10@L4.1"
        assert _fmt_profile_level("XXXX", 7, 3) == "Profile 7 / Level 3"

    def test_fourcc_and_codec_names(self):
        assert _fourcc(0x34363248) == "H264"                    # "H264" little-endian
        assert _codec_name(0x34363248) == "H.264 / AVC"
        for fourcc, friendly in _CODEC_NAMES.items():
            as_int = int.from_bytes(fourcc.ljust(4, " ").encode("ascii"), "little")
            assert _codec_name(as_int) == friendly

    def test_fourcc_unknown_falls_back_to_codec_number(self):
        assert _fourcc(1234) == "1234"

    def test_text_decodes_bytes_and_str(self):
        assert _text(b"English") == "English"
        assert _text("English") == "English"
        assert _text(b"") == ""
        assert _text(None) == ""


# ------------------------------------------------------------ track type ---
class TestTrackType:
    def test_enum_like_instance_with_value(self):
        """python-vlc hands back ctypes instances whose value is the int."""

        class _FakeType:
            def __init__(self, value):
                self.value = value

        class _Track:
            def __init__(self, value):
                self.type = _FakeType(value)

        assert _track_type(_Track(0)) == 0     # audio
        assert _track_type(_Track(1)) == 1     # video
        assert _track_type(_Track(2)) == 2     # text/subtitle

    def test_plain_int(self):
        class _Track:
            type = 1

        assert _track_type(_Track) == 1

    def test_garbage(self):
        class _Track:
            type = None

        assert _track_type(_Track) == -2


# ------------------------------------------------------- no-media lifecycle ---
class TestMetadataLifecycle:
    def test_load_empty_clears_everything(self):
        meta = Metadata(None)
        assert meta.details == []
        assert meta.liveStats == {
            "inputBitrate": "", "decodedFrames": "", "droppedFrames": "",
        }
        meta.load("")                       # must not raise without an engine
        assert meta.title == ""
        assert meta.artist == ""
        assert meta.details == []

    def test_live_poll_is_a_no_op_without_engine(self):
        meta = Metadata(None)
        meta._path = "C:/fake.mp3"          # simulate a loaded file
        meta._poll_live_stats()             # must not raise
        assert meta.liveStats["inputBitrate"] == ""

    def test_file_rows_need_no_vlc(self, tmp_path: Path):
        sample = tmp_path / "Some Song.mp3"
        sample.write_bytes(b"\x00" * 2048)
        rows = Metadata._file_rows(str(sample))
        labels = {row["label"]: row["value"] for row in rows}
        assert labels["File"] == "Some Song.mp3"
        assert labels["Container"] == "MP3"
        assert labels["Size"] == "2.0 KB"
        assert labels["Folder"] == tmp_path.name

    def test_file_rows_missing_file_shows_dash_size(self, tmp_path: Path):
        missing = tmp_path / "nope.mkv"
        rows = Metadata._file_rows(str(missing))
        labels = {row["label"]: row["value"] for row in rows}
        assert labels["Size"] == "\u2014"
        assert labels["Container"] == "MKV"


# -------------------------------------------------- VLC-facing paths (faked) ---
# These simulate what libVLC hands back, without needing the real library.


class _FakeType:
    """Mimics python-vlc's TrackType ctypes instances."""

    def __init__(self, value):
        self.value = value


class _FakePointer:
    """Mimics a ctypes POINTER: falsy when NULL, `.contents` when set."""

    def __init__(self, contents=None):
        self._contents = contents

    @property
    def contents(self):
        if self._contents is None:
            raise ValueError("NULL pointer access")
        return self._contents

    def __bool__(self):
        return self._contents is not None


class _FakeTrack:
    def __init__(self, ttype, codec=0x34363248, profile=0, level=0, bitrate=0,
                 language=None, description=None, video=None, audio=None):
        self.type = _FakeType(ttype)
        self.codec = codec
        self.profile = profile
        self.level = level
        self.bitrate = bitrate
        self.language = language
        self.description = description
        self.video = _FakePointer(video)
        self.audio = _FakePointer(audio)


class _FakeMedia:
    def __init__(self, tracks):
        self._tracks = tracks

    def tracks_get(self):
        return self._tracks


class TestAppendTracks:
    def test_video_and_audio_rows_populate(self):
        video = _FakeTrack(
            ttype=1,
            video=type("V", (), {
                "width": 1920, "height": 1080,
                "sar_num": 1, "sar_den": 1,
                "frame_rate_num": 24000, "frame_rate_den": 1001,
            })(),
            profile=100, level=40,
        )
        audio = _FakeTrack(
            ttype=0,
            codec=int.from_bytes(b"MP4A", "little"),
            audio=type("A", (), {"channels": 2, "rate": 48000})(),
            bitrate=192_000,
            language=b"eng",
        )
        sub = _FakeTrack(ttype=2, language=b"English", description=b"")

        meta = Metadata(None)
        details = []
        meta._append_tracks(details, _FakeMedia([video, audio, sub]))

        labels = {row["label"]: row["value"] for row in details}
        assert labels["Resolution"] == "1920\u00D71080"
        assert labels["Aspect ratio"] == "16:9"
        assert labels["Frame rate"] == "24 fps"
        assert labels["Video codec"] == "H.264 / AVC"
        assert labels["Profile"] == "High@L4.0"
        assert labels["Audio codec"] == "AAC"
        assert labels["Channels"] == "2 ch"
        assert labels["Sample rate"] == "48000 Hz"
        assert labels["Language"] == "eng"
        assert labels["Bitrate"] == "192 kbps"
        assert labels["Subtitles"] == "1 track \u00B7 English"

    def test_null_video_pointer_does_not_blank_audio_rows(self):
        """A broken video track must not take the audio rows down with it."""
        broken = _FakeTrack(ttype=1)          # video pointer is NULL
        audio = _FakeTrack(
            ttype=0,
            codec=int.from_bytes(b"FLAC", "little"),
            audio=type("A", (), {"channels": 2, "rate": 44100})(),
        )
        meta = Metadata(None)
        details = []
        meta._append_tracks(details, _FakeMedia([broken, audio]))
        labels = {row["label"]: row["value"] for row in details}
        assert labels["Audio codec"] == "FLAC"
        assert labels["Channels"] == "2 ch"


class TestLiveStats:
    def test_poll_updates_live_stats(self):
        import sys
        from unittest.mock import patch

        class _FakeStats:
            input_bitrate = 2_400_000.0
            decoded_video = 12345
            lost_pictures = 0

        class _FakeMediaStats:
            def __init__(self):
                self.input_bitrate = 0.0
                self.decoded_video = 0
                self.lost_pictures = 0

        class _FakeVlc:
            MediaStats = _FakeMediaStats

        class _FakePlayer:
            def get_media(self):
                media = type("Media", (), {})()

                def get_stats(stats):
                    stats.input_bitrate = _FakeStats.input_bitrate
                    stats.decoded_video = _FakeStats.decoded_video
                    stats.lost_pictures = _FakeStats.lost_pictures
                    return True

                media.get_stats = get_stats
                return media

        class _FakeEngine:
            isPlaying = True
            raw_player = _FakePlayer()

        meta = Metadata(_FakeEngine())
        meta._path = "C:/song.mp3"
        with patch.dict(sys.modules, {"vlc": _FakeVlc()}):
            meta._poll_live_stats()

        assert meta.liveStats["inputBitrate"] == "2.40 Mbps"
        assert meta.liveStats["decodedFrames"] == "12,345"
        assert meta.liveStats["droppedFrames"] == "0"
