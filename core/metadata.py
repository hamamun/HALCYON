"""Track metadata and album art — Milestone 1.8 (expanded).

Everything comes from libVLC's own parser, so there is no ffprobe or mutagen
dependency to bundle (§P1.5: "via libVLC (no ffprobe)").

The Info panel gets two things from here:

* ``details`` — the static rows: file facts, embedded tags, video/audio/subtitle
  track info. Built once the parse lands, retried until it does.
* ``liveStats`` — counters polled once a second while playing (input bitrate,
  decoded/dropped frames), so the panel shows real numbers instead of the
  (usually absent) header bitrate.

**Why the old build showed only File/Container/Duration for video files.**
libVLC parses asynchronously: the first ``tracks_get()`` after open is empty.
The old retry condition only re-read when *artist/artwork* were missing, so a
movie with an embedded cover (artwork present, tags absent) never retried and
its track rows never appeared. The retry now runs until track info lands too,
and every section is guarded separately so one bad track can never blank the
whole list.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from core import paths

log = logging.getLogger(__name__)

#: How many times to re-read while waiting for libVLC's async parse, and how
#: long between attempts. Bounded so a file that genuinely yields nothing does
#: not retry forever.
_MAX_RETRIES = 10
_RETRY_DELAY_MS = 400
_LIVE_POLL_MS = 1000

#: libvlc_track_type_t values as read from MediaTrack.type (audio=0, video=1,
#: text=2 — do not use TrackType members for comparison; python-vlc's enum
#: instances compare by value only inside its own helpers).
_TRACK_AUDIO = 0
_TRACK_VIDEO = 1
_TRACK_TEXT = 2

#: Friendly names for the fourccs libVLC reports. Unmapped codecs fall back to
#: the raw fourcc, which is still more readable than nothing.
#:
#: Keys are already fourcc-shaped (no trailing padding): ``_fourcc()`` strips
#: trailing NULs/spaces, so a padded lookup key could never match.
_CODEC_NAMES = {
    # video
    "H264": "H.264 / AVC", "AVC1": "H.264 / AVC", "X264": "H.264 / AVC",
    "HEVC": "H.265 / HEVC", "H265": "H.265 / HEVC",
    "AV01": "AV1",
    "VP80": "VP8", "VP90": "VP9",
    "MP4V": "MPEG-4 Visual", "XVID": "Xvid", "DIVX": "DivX",
    "MPG1": "MPEG-1", "MPG2": "MPEG-2", "MP2V": "MPEG-2",
    "WMV1": "WMV 7", "WMV2": "WMV 8", "WMV3": "WMV 9", "WVC1": "VC-1",
    "THEO": "Theora", "RV40": "RealVideo 4", "FLV1": "Sorenson H.263",
    "H263": "H.263",
    # audio
    "MP4A": "AAC", "AAC": "AAC", "FLAC": "FLAC",
    "OGGS": "Vorbis", "VORB": "Vorbis", "OPUS": "Opus",
    "MPGA": "MP3", "MP3": "MP3", "AC3": "AC-3", "A52": "AC-3",
    "EAC3": "E-AC-3", "DTS": "DTS", "MLP": "MLP",
    "WMA": "WMA", "WMAP": "WMA Pro", "ALAC": "ALAC", "AMR": "AMR",
    "S16L": "PCM 16-bit", "S24L": "PCM 24-bit", "S32L": "PCM 32-bit",
    "F32L": "PCM float", "U8": "PCM 8-bit", "S16B": "PCM 16-bit BE",
    "LPCM": "LPCM", "PCM": "PCM", "TWOS": "PCM big-endian",
    "SOWT": "PCM little-endian",
}

#: H.264 profile ids -> names. Anything else falls back to "Profile <n>".
_H264_PROFILES = {
    66: "Baseline", 77: "Main", 88: "Extended", 100: "High",
    110: "High 10", 122: "High 4:2:2", 244: "High 4:4:4",
}

#: HEVC profile ids -> names.
_HEVC_PROFILES = {1: "Main", 2: "Main 10", 3: "Main Still"}


def _fmt_duration(ms: int) -> str:
    if ms <= 0:
        return "\u2014"
    total = ms // 1000
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_size(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "\u2014"
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return "\u2014"


def _fmt_bitrate(bps: int) -> str:
    if bps <= 0:
        return "\u2014"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} Mbps"
    return f"{bps // 1000} kbps"


def _fmt_live_bitrate(bps: float) -> str:
    """Live stats bitrate is a float from MediaStats; blank when idle."""
    if bps <= 0:
        return ""
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} Mbps"
    return f"{bps / 1000:.0f} kbps"


def _fmt_aspect(width: int, height: int, sar_num: int, sar_den: int) -> str:
    """Display aspect ratio from pixel dimensions + sample aspect ratio."""
    if width <= 0 or height <= 0:
        return ""
    if sar_num <= 0 or sar_den <= 0:
        sar_num, sar_den = 1, 1
    dw, dh = width * sar_num, height * sar_den
    divisor = math.gcd(dw, dh)
    if divisor <= 0:
        return ""
    a, b = dw // divisor, dh // divisor
    # 16:9 and friends read naturally; very wide shapes collapse to "2.39:1".
    if max(a, b) <= 100:
        return f"{a}:{b}"
    return f"{dw / dh:.2f}:1"


def _fmt_profile_level(fourcc: str, profile: int, level: int) -> str:
    """\"High@L4.0\" style summary, or \"\" when VLC reported no profile."""
    if profile <= 0:
        return ""
    if fourcc in ("H264", "AVC1", "X264"):
        name = _H264_PROFILES.get(profile)
        if level > 0:
            return f"{name or profile}@L{level / 10:.1f}"
        return name or f"Profile {profile}"
    if fourcc in ("HEVC", "H265"):
        name = _HEVC_PROFILES.get(profile)
        if level > 0:
            return f"{name or profile}@L{level / 30:.1f}"
        return name or f"Profile {profile}"
    if level > 0:
        return f"Profile {profile} / Level {level}"
    return f"Profile {profile}"


def _fourcc(codec: int) -> str:
    """32-bit fourcc to a readable tag, e.g. 0x34363248 -> \"H264\"."""
    try:
        raw = int(codec).to_bytes(4, "little")
        text = raw.decode("ascii", "ignore").strip("\x00 ")
        # A fourcc is printable ASCII when it is really a tag; anything else
        # (control bytes, or a value that is not a tag at all) is reported as
        # the plain number rather than as a string of garbage.
        if text and text.isprintable():
            return text.upper()
    except Exception:
        pass
    return str(codec)


def _codec_name(codec: int) -> str:
    fourcc = _fourcc(codec)
    return _CODEC_NAMES.get(fourcc, fourcc)


def _track_type(track) -> int:
    """MediaTrack.type as a plain int, whatever python-vlc hands back.

    Reading a ctypes struct field whose type is a ctypes scalar subclass
    returns an *instance* of that subclass; comparing it to ``TrackType.video``
    with ``==`` works only inside python-vlc's own enum helpers, so we read the
    raw value and compare against the C enum numbers ourselves.
    """
    raw = getattr(track, "type", None)
    if raw is None:
        return -2
    value = getattr(raw, "value", None)
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return -2
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -2


def _text(value) -> str:
    """Decode libVLC's ``char *`` fields (may already be str)."""
    if not value:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip()
    return str(value).strip()


class Metadata(QObject):
    """Metadata for whatever is currently loaded."""

    changed = Signal()
    liveStatsChanged = Signal()

    def __init__(self, engine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._title = ""
        self._artist = ""
        self._album = ""
        self._artwork = ""
        self._details: list[dict] = []
        self._live = {"inputBitrate": "", "decodedFrames": "", "droppedFrames": ""}
        self._path = ""
        self._retries = 0
        #: True once a read saw at least one audio/video/text track — the gate
        #: that stops retrying a file whose tags/art will never arrive.
        self._has_track_info = False
        #: Keep the media wrapper alive between reads so its parse state is
        #: not garbage-collected mid-flight.
        self._media_ref = None

        self._live_timer = QTimer(self)
        self._live_timer.setInterval(_LIVE_POLL_MS)
        self._live_timer.timeout.connect(self._poll_live_stats)
        #: Always running; the poll itself is a cheap guard (no path / not
        #: playing returns immediately), so there is no start/stop choreography
        #: to get wrong when tracks change.
        self._live_timer.start()

    @Slot(str)
    def load(self, path: str) -> None:
        """Read metadata for ``path``.

        libVLC parses asynchronously, so the first read right after a track
        opens usually returns empty strings for title/artist/album/art and no
        tracks. Short bounded retries pick the values up as soon as the parse
        lands — cheap, and the alternative (subscribing to MediaParsedChanged)
        fires on a VLC thread and would need marshalling back anyway.
        """
        self._reset()
        self._retries = 0
        if not path:
            self.changed.emit()
            return
        self._path = path
        self._read(path)

    def _read(self, path: str) -> None:
        details = self._file_rows(path)
        self._has_track_info = False

        try:
            import vlc

            player = getattr(self._engine, "raw_player", None)
            media = player.get_media() if player is not None else None
            if media is None:
                self._details = details
                self.changed.emit()
                self._schedule_retry()
                return

            # Refresh the reference so the wrapper outlives this call.
            if self._media_ref is not None:
                try:
                    self._media_ref.release()
                except Exception:
                    pass
            self._media_ref = media

            # `local` alone parses the *stream* but never goes looking for
            # cover art, so ArtworkURL came back empty for every file and the
            # album-art slot was permanently blank. `fetch_local` is the flag
            # that extracts embedded covers and picks up folder.jpg / cover.jpg
            # next to the file. The two are a bitmask, so they combine.
            try:
                if self._retries == 0:
                    flags = (
                        vlc.MediaParseFlag.local.value
                        | vlc.MediaParseFlag.fetch_local.value
                    )
                    media.parse_with_options(flags, 3000)
            except Exception:
                log.debug("parse_with_options failed for %s", path, exc_info=True)

            def meta(key):
                try:
                    return media.get_meta(key) or ""
                except Exception:
                    return ""

            self._title = meta(vlc.Meta.Title) or self._title
            self._artist = meta(vlc.Meta.Artist)
            self._album = meta(vlc.Meta.Album)
            self._artwork = meta(vlc.Meta.ArtworkURL)

            duration = int(media.get_duration() or 0)
            if duration > 0:
                details.append({"label": "Duration", "value": _fmt_duration(duration)})

            self._append_tags(details, media, vlc)
            self._append_tracks(details, media)
        except Exception:
            log.debug("metadata parse failed for %s", path, exc_info=True)

        self._details = details
        self.changed.emit()
        self._schedule_retry()

    # ------------------------------------------------------------- rows ---
    @staticmethod
    def _file_rows(path: str) -> list[dict]:
        """Rows that need no VLC at all — always present, even pre-parse."""
        file_path = Path(paths.normalise_path(path))
        rows = [
            {"label": "File", "value": file_path.name},
            {"label": "Container", "value": file_path.suffix.lstrip(".").upper() or "\u2014"},
        ]
        try:
            rows.append({"label": "Size", "value": _fmt_size(file_path.stat().st_size)})
        except OSError:
            rows.append({"label": "Size", "value": "\u2014"})
        parent = file_path.parent.name
        rows.append({"label": "Folder", "value": parent or "\u2014"})
        return rows

    def _append_tags(self, details: list[dict], media, vlc) -> None:
        """Embedded tags, in a fixed order, skipping whatever is absent."""
        tag_rows = [
            ("Album", vlc.Meta.Album),
            ("Album artist", vlc.Meta.AlbumArtist),
            ("Year", vlc.Meta.Date),
            ("Genre", vlc.Meta.Genre),
            ("Director", vlc.Meta.Director),
            ("Publisher", vlc.Meta.Publisher),
            ("Language", vlc.Meta.Language),
            ("Encoded by", vlc.Meta.EncodedBy),
            ("Description", vlc.Meta.Description),
        ]
        for label, meta_key in tag_rows:
            value = self._meta_text(media, meta_key)
            if value:
                details.append({"label": label, "value": value})

        track_no = self._meta_text(media, vlc.Meta.TrackNumber)
        track_total = self._meta_text(media, vlc.Meta.TrackTotal)
        if track_no:
            value = f"{track_no} / {track_total}" if track_total else track_no
            details.append({"label": "Track", "value": value})
        disc_no = self._meta_text(media, vlc.Meta.DiscNumber)
        disc_total = self._meta_text(media, vlc.Meta.DiscTotal)
        if disc_no:
            value = f"{disc_no} / {disc_total}" if disc_total else disc_no
            details.append({"label": "Disc", "value": value})

    @staticmethod
    def _meta_text(media, meta_key) -> str:
        try:
            value = media.get_meta(meta_key)
            return _text(value)
        except Exception:
            return ""

    def _append_tracks(self, details: list[dict], media) -> None:
        """Video / audio / subtitle rows from MediaTrack data.

        Each track is wrapped separately: a NULL ``video``/``audio`` pointer or
        an odd field on one track must not wipe the rows already collected.
        """
        try:
            tracks = media.tracks_get() or []
        except Exception:
            log.debug("tracks_get failed", exc_info=True)
            return
        if not tracks:
            return
        self._has_track_info = True

        #: Reset per read — retries call _read() again and must not accumulate.
        self._subtitle_languages = []
        video_seen = audio_seen = text_seen = 0
        for track in tracks:
            ttype = _track_type(track)
            if ttype == _TRACK_VIDEO:
                video_seen += 1
                if video_seen == 1:
                    self._append_video_rows(details, track)
            elif ttype == _TRACK_AUDIO:
                audio_seen += 1
                if audio_seen == 1:
                    self._append_audio_rows(details, track)
            elif ttype == _TRACK_TEXT:
                text_seen += 1
                self._subtitle_languages.append(_track_language(track))

        if video_seen > 1:
            details.append({"label": "Video tracks", "value": str(video_seen)})
        if audio_seen > 1:
            details.append({"label": "Audio tracks", "value": str(audio_seen)})
        if text_seen:
            languages = [lang for lang in self._subtitle_languages if lang]
            value = f"{text_seen} track{'s' if text_seen != 1 else ''}"
            if languages:
                value += " \u00B7 " + ", ".join(languages[:4])
            details.append({"label": "Subtitles", "value": value})

    def _append_video_rows(self, details: list[dict], track) -> None:
        try:
            if not track.video:
                return
            video = track.video.contents
        except Exception:
            return
        width, height = int(video.width), int(video.height)
        if width > 0 and height > 0:
            details.append({"label": "Resolution", "value": f"{width}\u00D7{height}"})
            aspect = _fmt_aspect(
                width, height, int(video.sar_num), int(video.sar_den)
            )
            if aspect:
                details.append({"label": "Aspect ratio", "value": aspect})

        fps_num, fps_den = int(video.frame_rate_num), int(video.frame_rate_den)
        if fps_num > 0 and fps_den > 0:
            details.append({"label": "Frame rate", "value": f"{fps_num / fps_den:.3g} fps"})

        fourcc = _fourcc(track.codec)
        details.append({"label": "Video codec", "value": _codec_name(track.codec)})
        profile_level = _fmt_profile_level(fourcc, int(track.profile), int(track.level))
        if profile_level:
            details.append({"label": "Profile", "value": profile_level})

    def _append_audio_rows(self, details: list[dict], track) -> None:
        try:
            if not track.audio:
                return
            audio = track.audio.contents
        except Exception:
            return
        details.append({"label": "Audio codec", "value": _codec_name(track.codec)})
        channels, rate = int(audio.channels), int(audio.rate)
        if channels > 0:
            details.append({"label": "Channels", "value": f"{channels} ch"})
        if rate > 0:
            details.append({"label": "Sample rate", "value": f"{rate} Hz"})
        language = _track_language(track)
        if language:
            details.append({"label": "Language", "value": language})
        if int(track.bitrate or 0) > 0:
            details.append({"label": "Bitrate", "value": _fmt_bitrate(int(track.bitrate))})

    # ------------------------------------------------------- live stats ---
    def _poll_live_stats(self) -> None:
        """Refresh live counters once a second while playing (or buffering)."""
        if not self._path or self._engine is None:
            return
        if not getattr(self._engine, "isPlaying", False):
            return
        try:
            import vlc

            player = getattr(self._engine, "raw_player", None)
            media = player.get_media() if player is not None else None
            if media is None:
                return
            stats = vlc.MediaStats()
            if not media.get_stats(stats):
                return
            live = {
                "inputBitrate": _fmt_live_bitrate(float(stats.input_bitrate)),
                "decodedFrames": f"{int(stats.decoded_video):,}"
                if stats.decoded_video > 0 else "",
                "droppedFrames": f"{int(stats.lost_pictures):,}"
                if stats.lost_pictures > 0 else "0",
            }
        except Exception:
            log.debug("live stats unavailable", exc_info=True)
            return
        if live != self._live:
            self._live = live
            self.liveStatsChanged.emit()

    # ----------------------------------------------------------- helpers ---
    def _schedule_retry(self) -> None:
        if not self._path:
            return
        missing = not (self._artist or self._artwork or self._has_track_info)
        if self._retries < _MAX_RETRIES and missing:
            self._retries += 1
            QTimer.singleShot(_RETRY_DELAY_MS, self._retry)

    def _retry(self) -> None:
        # The user may have skipped to another track while we waited; only
        # refresh if this is still the file on air.
        if self._path:
            self._read(self._path)

    def _reset(self) -> None:
        self._title = ""
        self._artist = ""
        self._album = ""
        self._artwork = ""
        self._details = []
        self._live = {"inputBitrate": "", "decodedFrames": "", "droppedFrames": ""}
        self._path = ""
        self._has_track_info = False
        self._subtitle_languages: list[str] = []
        if self._media_ref is not None:
            try:
                self._media_ref.release()
            except Exception:
                pass
            self._media_ref = None
        self.liveStatsChanged.emit()

    # --------------------------------------------------------- properties ---
    @Property(str, notify=changed)
    def title(self) -> str:
        return self._title

    @Property(str, notify=changed)
    def artist(self) -> str:
        return self._artist

    @Property(str, notify=changed)
    def album(self) -> str:
        return self._album

    @Property(str, notify=changed)
    def artworkUrl(self) -> str:  # noqa: N802 - QML-facing
        return self._artwork

    @Property("QVariantList", notify=changed)
    def details(self) -> list:
        return self._details

    @Property("QVariantMap", notify=liveStatsChanged)
    def liveStats(self) -> dict:
        return dict(self._live)


def _track_language(track) -> str:
    """Best available language label for a track (language or description)."""
    return _text(getattr(track, "language", None)) or _text(
        getattr(track, "description", None)
    )
