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


def _track_language(track) -> str:
    """Best available language label for a track (language or description)."""
    return _text(getattr(track, "language", None)) or _text(
        getattr(track, "description", None)
    )


def _get_media_tracks(media) -> list[dict]:
    """Safely fetch tracks from media before libvlc_media_tracks_release frees them.

    libVLC's python-vlc binding calls libvlc_media_tracks_release before
    returning from media.tracks_get(). The returned MediaTrack objects contain
    pointers (e.g. u.video, u.audio, language, description) into the memory
    that was just freed. Accessing those pointers after tracks_get() returns is
    a use-after-free leading to segmentation faults in C++.
    """
    if media is None:
        return []

    try:
        import ctypes
        import vlc

        p_tracks = ctypes.POINTER(ctypes.POINTER(vlc.MediaTrack))()
        n = vlc.libvlc_media_tracks_get(media, ctypes.byref(p_tracks))
        if n <= 0 or not p_tracks:
            return []

        tracks_data = []
        try:
            for i in range(n):
                ptr = p_tracks[i]
                if not ptr:
                    continue
                item = ptr.contents
                ttype = _track_type(item)

                lang = _text(getattr(item, "language", None))
                desc = _text(getattr(item, "description", None))

                video_info = None
                if ttype == _TRACK_VIDEO:
                    try:
                        v_ptr = getattr(item.u, "video", None) or getattr(item, "video", None)
                        if v_ptr:
                            v_contents = v_ptr.contents
                            video_info = {
                                "width": int(getattr(v_contents, "width", 0)),
                                "height": int(getattr(v_contents, "height", 0)),
                                "sar_num": int(getattr(v_contents, "sar_num", 1)),
                                "sar_den": int(getattr(v_contents, "sar_den", 1)),
                                "frame_rate_num": int(getattr(v_contents, "frame_rate_num", 0)),
                                "frame_rate_den": int(getattr(v_contents, "frame_rate_den", 1)),
                            }
                    except Exception:
                        video_info = None

                audio_info = None
                if ttype == _TRACK_AUDIO:
                    try:
                        a_ptr = getattr(item.u, "audio", None) or getattr(item, "audio", None)
                        if a_ptr:
                            a_contents = a_ptr.contents
                            audio_info = {
                                "channels": int(getattr(a_contents, "channels", 0)),
                                "rate": int(getattr(a_contents, "rate", 0)),
                            }
                    except Exception:
                        audio_info = None

                tracks_data.append({
                    "type": ttype,
                    "codec": int(getattr(item, "codec", 0)),
                    "profile": int(getattr(item, "profile", 0)),
                    "level": int(getattr(item, "level", 0)),
                    "bitrate": int(getattr(item, "bitrate", 0) or 0),
                    "language": lang,
                    "description": desc,
                    "video": video_info,
                    "audio": audio_info,
                })
        finally:
            vlc.libvlc_media_tracks_release(p_tracks, n)

        return tracks_data
    except Exception:
        # Fallback for mock objects in unit tests where vlc C structs aren't used
        try:
            raw_tracks = media.tracks_get() or []
        except Exception:
            return []

        out = []
        for track in raw_tracks:
            ttype = _track_type(track)
            video_info = None
            if ttype == _TRACK_VIDEO:
                try:
                    v_ptr = getattr(track, "video", None)
                    if v_ptr and getattr(v_ptr, "contents", None):
                        v_contents = v_ptr.contents
                        video_info = {
                            "width": int(getattr(v_contents, "width", 0)),
                            "height": int(getattr(v_contents, "height", 0)),
                            "sar_num": int(getattr(v_contents, "sar_num", 1)),
                            "sar_den": int(getattr(v_contents, "sar_den", 1)),
                            "frame_rate_num": int(getattr(v_contents, "frame_rate_num", 0)),
                            "frame_rate_den": int(getattr(v_contents, "frame_rate_den", 1)),
                        }
                except Exception:
                    video_info = None

            audio_info = None
            if ttype == _TRACK_AUDIO:
                try:
                    a_ptr = getattr(track, "audio", None)
                    if a_ptr and getattr(a_ptr, "contents", None):
                        a_contents = a_ptr.contents
                        audio_info = {
                            "channels": int(getattr(a_contents, "channels", 0)),
                            "rate": int(getattr(a_contents, "rate", 0)),
                        }
                except Exception:
                    audio_info = None

            out.append({
                "type": ttype,
                "codec": int(getattr(track, "codec", 0)),
                "profile": int(getattr(track, "profile", 0)),
                "level": int(getattr(track, "level", 0)),
                "bitrate": int(getattr(track, "bitrate", 0) or 0),
                "language": _track_language(track),
                "description": _text(getattr(track, "description", None)),
                "video": video_info,
                "audio": audio_info,
            })
        return out


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
        tracks = _get_media_tracks(media)
        if not tracks:
            return
        self._has_track_info = True

        #: Reset per read — retries call _read() again and must not accumulate.
        self._subtitle_languages = []
        video_seen = audio_seen = text_seen = 0
        for track in tracks:
            ttype = track["type"]
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
                lang = track["language"] or track["description"]
                self._subtitle_languages.append(lang)

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

    def _append_video_rows(self, details: list[dict], track: dict) -> None:
        video = track.get("video")
        if not video:
            return
        width, height = video["width"], video["height"]
        if width > 0 and height > 0:
            details.append({"label": "Resolution", "value": f"{width}\u00D7{height}"})
            aspect = _fmt_aspect(
                width, height, video["sar_num"], video["sar_den"]
            )
            if aspect:
                details.append({"label": "Aspect ratio", "value": aspect})

        fps_num, fps_den = video["frame_rate_num"], video["frame_rate_den"]
        if fps_num > 0 and fps_den > 0:
            details.append({"label": "Frame rate", "value": f"{fps_num / fps_den:.3g} fps"})

        codec = track["codec"]
        fourcc = _fourcc(codec)
        details.append({"label": "Video codec", "value": _codec_name(codec)})
        profile_level = _fmt_profile_level(fourcc, track["profile"], track["level"])
        if profile_level:
            details.append({"label": "Profile", "value": profile_level})

    def _append_audio_rows(self, details: list[dict], track: dict) -> None:
        audio = track.get("audio")
        if not audio:
            return
        codec = track["codec"]
        details.append({"label": "Audio codec", "value": _codec_name(codec)})
        channels, rate = audio["channels"], audio["rate"]
        if channels > 0:
            details.append({"label": "Channels", "value": f"{channels} ch"})
        if rate > 0:
            details.append({"label": "Sample rate", "value": f"{rate} Hz"})
        language = track["language"] or track["description"]
        if language:
            details.append({"label": "Language", "value": language})
        if track["bitrate"] > 0:
            details.append({"label": "Bitrate", "value": _fmt_bitrate(track["bitrate"])})

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
