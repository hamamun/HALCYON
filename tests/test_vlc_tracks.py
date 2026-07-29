"""Native media-track arrays are released exactly once after inspection."""

from __future__ import annotations

import ctypes

from engine.vlc_tracks import media_tracks


class _Track(ctypes.Structure):
    _fields_ = [("id", ctypes.c_int), ("language", ctypes.c_char_p)]


class _RawVlc:
    MediaTrack = _Track

    def __init__(self, rows):
        self._tracks = [_Track(track_id, language) for track_id, language in rows]
        self._pointers = (ctypes.POINTER(_Track) * len(self._tracks))(
            *(ctypes.pointer(track) for track in self._tracks)
        )
        self.releases = []

    def libvlc_media_tracks_get(self, _media, output):
        # python-vlc's generated wrapper stores the native Track** in a
        # POINTER(Track) variable and casts it back to an array of pointers.
        value = ctypes.cast(self._pointers, ctypes.POINTER(_Track))
        ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(_Track)))[0] = value
        return len(self._tracks)

    def libvlc_media_tracks_release(self, pointer, count):
        self.releases.append((bool(pointer), int(count)))


def test_raw_track_array_is_valid_inside_block_and_released_afterwards():
    vlc = _RawVlc([(1, b"eng"), (2, b"hin")])

    with media_tracks(vlc, object()) as tracks:
        assert [(track.id, track.language) for track in tracks] == [
            (1, b"eng"),
            (2, b"hin"),
        ]
        assert vlc.releases == []

    assert vlc.releases == [(True, 2)]


def test_release_still_happens_when_track_processing_raises():
    vlc = _RawVlc([(7, b"eng")])

    try:
        with media_tracks(vlc, object()):
            raise RuntimeError("consumer failed")
    except RuntimeError:
        pass

    assert vlc.releases == [(True, 1)]


def test_empty_native_result_needs_no_release():
    vlc = _RawVlc([])

    with media_tracks(vlc, object()) as tracks:
        assert tracks == ()

    assert vlc.releases == []


def test_tracks_get_fallback_keeps_test_doubles_supported():
    class Media:
        def tracks_get(self):
            return ["audio", "video"]

    class VlcWithoutRawApi:
        pass

    with media_tracks(VlcWithoutRawApi(), Media()) as tracks:
        assert tracks == ("audio", "video")
