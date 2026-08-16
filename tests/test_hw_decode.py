"""Turbo's per-media hardware-decode policy — §V.2.

The bug under test: Turbo used to force ``:avcodec-hw=d3d11va`` onto *every*
media it opened. Modern GPU drivers advertise VC-1 (WMV3) and DivX-era MPEG-4
decoders and then reject the actual frames (``Failed to execute: 0x80070057``
once per frame), so a 720p ``.wmv`` that plays perfectly on Soft became a
black screen with perfect audio on Turbo — while the badge claimed everything
was fine.

The fix keeps Turbo's *output* (the native child window) for every file and
moves only the *decode* to the CPU when the GPU is a known or proven bad bet,
which is what VLC's own desktop player does. Three layers, three test groups:

* the pure policy (``engine/hw_decode.py``): codec fourccs and container
  extensions classify as safe / unsafe / unknown;
* the ``open()`` gate: a legacy container opened on the Turbo route carries
  an explicit CPU-decode option, while modern/unknown media keep the GPU one;
* the runtime watchdog: a media that was given the GPU and produced zero
  decoded pictures is silently re-opened with CPU decode at the same
  position — and never handed to the GPU again.

Engine construction mirrors ``tests/test_turbo_surface.py``: ``VlcEngine``
built with ``__new__`` and fakes, because the interesting logic is pure
sequencing and must not need a native libVLC.
"""

from __future__ import annotations

import time

import pytest

from core import video_mode as vm
from engine import hw_decode
from engine.vlc_engine import State, VlcEngine, _HW_DECODE_GRACE_S


# ---------------------------------------------------------------------------
# The pure policy: codecs
# ---------------------------------------------------------------------------
class TestCodecPolicy:
    def test_modern_codecs_are_gpu_safe(self):
        for fourcc in ("h264", "HEVC", "hvc1", "VP90", "av01"):
            assert hw_decode.codec_gpu_safe(fourcc) is True, fourcc

    def test_legacy_codecs_are_gpu_unsafe(self):
        # WMV3/VC-1 is the black-screen headline; the rest are the DivX era.
        for fourcc in ("WMV3", "WVC1", "DIV3", "XVID", "MP4V", "RV40", "FLV1"):
            assert hw_decode.codec_gpu_safe(fourcc) is False, fourcc

    def test_unknown_codec_has_no_opinion(self):
        assert hw_decode.codec_gpu_safe("ZZZZ") is None
        assert hw_decode.codec_gpu_safe("") is None
        assert hw_decode.codec_gpu_safe(None) is None

    def test_fourcc_numbers_decode_like_the_info_panel(self):
        # libVLC stores fourccs little-endian; "WMV3" = 0x33564D57.
        assert hw_decode.fourcc_text(0x33564D57) == "WMV3"
        assert hw_decode.codec_gpu_safe(0x33564D57) is False
        # "h264" = 0x34363268 — case-normalised on the way in.
        assert hw_decode.fourcc_text(0x34363268) == "H264"
        assert hw_decode.codec_gpu_safe(0x34363268) is True

    def test_garbage_numbers_are_no_opinion_not_a_crash(self):
        assert hw_decode.codec_gpu_safe(0) is None
        assert hw_decode.codec_gpu_safe(-1) is None
        assert hw_decode.codec_gpu_safe(object()) is None


# ---------------------------------------------------------------------------
# The pure policy: containers
# ---------------------------------------------------------------------------
class TestPathPolicy:
    @pytest.mark.parametrize(
        "name",
        [
            "Maula - Jism 2.wmv",
            "clip.WMV",                      # case-insensitive
            "old.asf",
            "Bachna AeHaseeno.avi",
            "flash.flv",
            "real.rmvb",
            "disc.vob",
            "phone.3gp",
        ],
    )
    def test_legacy_containers_are_gpu_unsafe(self, name):
        assert hw_decode.path_gpu_safe(name) is False

    @pytest.mark.parametrize(
        "name",
        ["film.mkv", "clip.mp4", "web.webm", "trailer.mov", "cam.m2ts"],
    )
    def test_modern_containers_are_gpu_safe(self, name):
        assert hw_decode.path_gpu_safe(name) is True

    def test_unknown_or_missing_extension_has_no_opinion(self):
        assert hw_decode.path_gpu_safe("mystery.xyz") is None
        assert hw_decode.path_gpu_safe("no_extension") is None
        assert hw_decode.path_gpu_safe("") is None
        assert hw_decode.path_gpu_safe(None) is None

    def test_file_uris_are_classified_like_paths(self):
        # open() hands the policy the resolved MRL, not the original path.
        assert hw_decode.path_gpu_safe("file:///C:/Videos/Maula.wmv") is False
        assert hw_decode.path_gpu_safe("file:///C:/Videos/film.mkv") is True
        # Percent-encoded spaces must not hide the extension.
        assert (
            hw_decode.path_gpu_safe("file:///C:/V/Tumse%20Hi%20Tumse.wmv") is False
        )

    def test_network_streams_have_no_opinion(self):
        assert hw_decode.path_gpu_safe("http://example.com/live/stream") is None


# ---------------------------------------------------------------------------
# The pure policy: parsed media tracks
# ---------------------------------------------------------------------------
class _Track:
    """The two MediaTrack fields the classifier reads."""

    def __init__(self, type_: int, codec) -> None:
        self.type = type_
        self.codec = codec


class _ParsedMedia:
    def __init__(self, tracks) -> None:
        self._tracks = tracks

    def tracks_get(self):
        return list(self._tracks)


VIDEO = 1
AUDIO = 0


class TestMediaPolicy:
    def test_wmv3_video_track_is_unsafe(self):
        media = _ParsedMedia([_Track(VIDEO, "WMV3"), _Track(AUDIO, "WMA2")])
        assert hw_decode.media_gpu_safe(media) is False

    def test_h264_video_track_is_safe(self):
        media = _ParsedMedia([_Track(VIDEO, "h264"), _Track(AUDIO, "mp4a")])
        assert hw_decode.media_gpu_safe(media) is True

    def test_audio_codecs_never_decide(self):
        # Only video tracks matter; a legacy *audio* codec is irrelevant.
        media = _ParsedMedia([_Track(VIDEO, "h264"), _Track(AUDIO, "WMA2")])
        assert hw_decode.media_gpu_safe(media) is True

    def test_one_legacy_track_outvotes_a_modern_one(self):
        media = _ParsedMedia([_Track(VIDEO, "h264"), _Track(VIDEO, "WMV3")])
        assert hw_decode.media_gpu_safe(media) is False

    def test_unparsed_media_has_no_opinion(self):
        # tracks_get() is empty until the asynchronous parse lands — the
        # normal state at open() time. Must be None, not False: unknown keeps
        # current behaviour instead of stripping the GPU from modern files.
        assert hw_decode.media_gpu_safe(_ParsedMedia([])) is None

    def test_no_media_and_broken_media_have_no_opinion(self):
        assert hw_decode.media_gpu_safe(None) is None

        class Broken:
            def tracks_get(self):
                raise RuntimeError("libVLC said no")

        assert hw_decode.media_gpu_safe(Broken()) is None


# ---------------------------------------------------------------------------
# Engine doubles (the test_turbo_surface.py construction)
# ---------------------------------------------------------------------------
class FakePlayer:
    def __init__(self) -> None:
        self.media = None
        self.stops = 0
        self.plays = 0

    def stop(self):
        self.stops += 1

    def play(self):
        self.plays += 1

    def set_media(self, media):
        self.media = media

    def get_media(self):
        return self.media

    def get_time(self):
        return 61_000

    def get_state(self):
        return 3


class FakeMedia:
    def __init__(self, mrl: str) -> None:
        self.mrl = mrl
        self.options: list[str] = []
        self.released = False

    def add_option(self, option):
        self.options.append(option)

    def parse_with_options(self, *a, **k):
        pass

    def release(self):
        self.released = True


class FakeInstance:
    def __init__(self) -> None:
        self.created: list[FakeMedia] = []

    def media_new(self, mrl):
        media = FakeMedia(mrl)
        self.created.append(media)
        return media


class FakeVideoOutput:
    def __init__(self) -> None:
        self.attached = True

    def attach(self, player):
        self.attached = True

    def detach(self):
        self.attached = False

    def notify_video_stopped(self):
        pass


def _engine(*, route=vm.TURBO, hw_option=True):
    from PySide6.QtCore import QObject

    engine = VlcEngine.__new__(VlcEngine)
    QObject.__init__(engine)
    engine._player = FakePlayer()
    engine._instance = FakeInstance()
    engine._media = None
    engine._vlc = None
    engine.video_output = FakeVideoOutput()
    engine._state = State.Playing
    engine._duration = 7_200_000
    engine._position = 0.1
    engine._time = 61_000
    engine._current_mrl = ""
    engine._releasing = False
    engine._scrubbing = False
    engine._pending_resume_ms = 0
    engine._video_route = route
    engine._turbo_surface = None
    engine._media_options = (
        [hw_decode.HW_DECODE_OPTION] if hw_option else []
    )
    engine._user_paused = False
    engine._pending_turbo_play = False
    engine._hw_decode_pending = False
    engine._hw_watch_started = None
    engine._cpu_decode_override = ""
    return engine


# ---------------------------------------------------------------------------
# The open() gate
# ---------------------------------------------------------------------------
class TestOpenGate:
    def test_wmv_on_turbo_explicitly_forces_cpu_decode(self, qt_application):
        engine = _engine()
        engine.open("file:///C:/Videos/Maula%20-%20Jism%202.wmv")
        media = engine._instance.created[-1]
        assert hw_decode.HW_DECODE_OPTION not in media.options, (
            "a legacy container must never carry the d3d11va request — "
            "the driver advertises the decoder and then rejects every frame"
        )
        assert hw_decode.CPU_DECODE_OPTION in media.options, (
            "omitting d3d11va is not a CPU override: libVLC 3 set_hwnd resets "
            "the player-level decoder choice to automatic"
        )

    def test_mkv_on_turbo_keeps_the_gpu_option(self, qt_application):
        engine = _engine()
        engine.open("file:///C:/Videos/film.mkv")
        media = engine._instance.created[-1]
        assert hw_decode.HW_DECODE_OPTION in media.options

    def test_unknown_extension_keeps_the_gpu_option(self, qt_application):
        # Unknown resolves to "allow": the watchdog rescues a wrong allow,
        # nothing rescues a wrong block.
        engine = _engine()
        engine.open("file:///C:/Videos/mystery.xyz")
        media = engine._instance.created[-1]
        assert hw_decode.HW_DECODE_OPTION in media.options

    def test_soft_route_is_untouched(self, qt_application):
        # Soft never records the option; the gate must not add one.
        engine = _engine(route=vm.SOFT, hw_option=False)
        engine.open("file:///C:/Videos/Maula.wmv")
        media = engine._instance.created[-1]
        assert not any(o.startswith(":avcodec-hw=") for o in media.options)
        assert engine._hw_decode_pending is False

    def test_watchdog_armed_only_when_gpu_requested(self, qt_application):
        engine = _engine()
        engine.open("file:///C:/Videos/film.mkv")
        assert engine._hw_decode_pending is True

        engine2 = _engine()
        engine2.open("file:///C:/Videos/Maula.wmv")
        assert engine2._hw_decode_pending is False

    def test_a_failed_media_is_never_given_to_the_gpu_again(self, qt_application):
        engine = _engine()
        engine._cpu_decode_override = "file:///C:/Videos/odd.mkv"
        engine.open("file:///C:/Videos/odd.mkv")
        media = engine._instance.created[-1]
        assert hw_decode.HW_DECODE_OPTION not in media.options
        assert hw_decode.CPU_DECODE_OPTION in media.options

    def test_gpu_then_legacy_media_overrides_hwnd_player_state(self, qt_application):
        """Regression for the Windows log that exposed the first attempted fix.

        Merely stripping d3d11va produced an option-less WMV.  libVLC 3's
        set_hwnd had reset the closer player-level value to automatic, so it
        overrode the instance's ``none`` and WMV3 still entered D3D11VA.
        """
        engine = _engine()
        engine.open("file:///C:/Videos/modern.mp4")
        assert hw_decode.HW_DECODE_OPTION in engine._instance.created[-1].options

        engine.open("file:///C:/Videos/legacy.wmv")
        legacy = engine._instance.created[-1]
        assert legacy.options == [hw_decode.CPU_DECODE_OPTION]
        assert engine._hw_decode_pending is False

    def test_the_override_names_one_mrl_not_all(self, qt_application):
        engine = _engine()
        engine._cpu_decode_override = "file:///C:/Videos/odd.mkv"
        engine.open("file:///C:/Videos/fine.mkv")
        media = engine._instance.created[-1]
        assert hw_decode.HW_DECODE_OPTION in media.options


# ---------------------------------------------------------------------------
# The runtime watchdog
# ---------------------------------------------------------------------------
class _StatsMedia(FakeMedia):
    """A media whose statistics the watchdog can read."""

    def __init__(self, mrl: str, decoded_video: int, tracks=()) -> None:
        super().__init__(mrl)
        self._decoded = decoded_video
        self._tracks = list(tracks)

    def get_stats(self, stats) -> bool:
        stats.decoded_video = self._decoded
        return True

    def tracks_get(self):
        return list(self._tracks)


class _StatsVlc:
    """Just the MediaStats constructor the watchdog needs."""

    class MediaStats:
        def __init__(self) -> None:
            self.decoded_video = 0


def _playing_with(engine, media) -> None:
    engine._vlc = _StatsVlc()
    engine._player.media = media
    engine._current_mrl = media.mrl
    engine._hw_decode_pending = True
    engine._hw_watch_started = None


class TestWatchdog:
    def test_zero_pictures_after_grace_falls_back_to_cpu(self, qt_application):
        engine = _engine()
        media = _StatsMedia("file:///C:/V/odd.mkv", decoded_video=0)
        _playing_with(engine, media)
        engine._player.video_get_track_description = lambda: [(0, b"Video 1")]

        engine._check_hw_decode_health(State.Playing)     # arms the clock
        engine._hw_watch_started -= _HW_DECODE_GRACE_S + 1  # grace elapsed
        engine._check_hw_decode_health(State.Playing)

        assert engine._cpu_decode_override == "file:///C:/V/odd.mkv"
        # The fallback re-opened the same MRL...
        reopened = engine._instance.created[-1]
        assert reopened.mrl == "file:///C:/V/odd.mkv"
        # ...with an explicit CPU request this time.  Absence alone falls back
        # to the automatic player value installed by set_hwnd on libVLC 3.
        assert hw_decode.HW_DECODE_OPTION not in reopened.options
        assert hw_decode.CPU_DECODE_OPTION in reopened.options
        # And the Turbo route/window was never torn down.
        assert engine._video_route == vm.TURBO

    def test_flowing_pictures_disarm_the_watchdog(self, qt_application):
        engine = _engine()
        media = _StatsMedia("file:///C:/V/fine.mkv", decoded_video=120)
        _playing_with(engine, media)
        engine._player.video_get_track_description = lambda: [(0, b"Video 1")]

        engine._check_hw_decode_health(State.Playing)
        engine._hw_watch_started -= _HW_DECODE_GRACE_S + 1
        engine._check_hw_decode_health(State.Playing)

        assert engine._hw_decode_pending is False
        assert engine._cpu_decode_override == ""
        assert engine._instance.created == []          # no reopen

    def test_audio_only_media_is_not_a_failure(self, qt_application):
        # Zero decoded pictures is the *correct* result for an audio file.
        engine = _engine()
        media = _StatsMedia("file:///C:/V/song.mkv", decoded_video=0)
        _playing_with(engine, media)
        engine._player.video_get_track_description = lambda: []

        engine._check_hw_decode_health(State.Playing)
        engine._hw_watch_started -= _HW_DECODE_GRACE_S + 1
        engine._check_hw_decode_health(State.Playing)

        assert engine._cpu_decode_override == ""
        assert engine._instance.created == []

    def test_a_parsed_legacy_codec_falls_back_without_waiting(self, qt_application):
        # The tracks landed and named WMV3 — no reason to stare at a black
        # screen for the rest of the grace period.
        engine = _engine()
        media = _StatsMedia(
            "file:///C:/V/wmv_in_mkv.mkv",
            decoded_video=0,
            tracks=[_Track(VIDEO, "WMV3")],
        )
        _playing_with(engine, media)

        engine._check_hw_decode_health(State.Playing)     # arms the clock
        engine._check_hw_decode_health(State.Playing)     # sees the codec

        assert engine._cpu_decode_override == "file:///C:/V/wmv_in_mkv.mkv"
        reopened = engine._instance.created[-1]
        assert hw_decode.HW_DECODE_OPTION not in reopened.options
        assert hw_decode.CPU_DECODE_OPTION in reopened.options

    def test_watchdog_is_a_noop_on_soft(self, qt_application):
        engine = _engine(route=vm.SOFT, hw_option=False)
        engine._hw_decode_pending = True   # stale flag, e.g. after a fallback
        engine._check_hw_decode_health(State.Playing)
        assert engine._hw_decode_pending is False
        assert engine._instance.created == []

    def test_watchdog_waits_for_playing(self, qt_application):
        engine = _engine()
        media = _StatsMedia("file:///C:/V/odd.mkv", decoded_video=0)
        _playing_with(engine, media)

        engine._check_hw_decode_health(State.Opening)
        assert engine._hw_watch_started is None, (
            "the grace clock must not run while the media is still opening"
        )

    def test_resume_position_survives_the_fallback(self, qt_application):
        engine = _engine()
        media = _StatsMedia("file:///C:/V/odd.mkv", decoded_video=0)
        _playing_with(engine, media)
        engine._player.video_get_track_description = lambda: [(0, b"Video 1")]

        engine._check_hw_decode_health(State.Playing)
        engine._hw_watch_started -= _HW_DECODE_GRACE_S + 1
        engine._check_hw_decode_health(State.Playing)

        # FakePlayer.get_time() says 61 000 ms; the reopen must resume there.
        assert engine._pending_resume_ms == 61_000
