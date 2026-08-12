"""Track metadata and album art — Milestone 1.8.

Everything comes from libVLC's own parser, so there is no ffprobe or mutagen
dependency to bundle (§P1.5: "via libVLC (no ffprobe)").

The public metadata properties in this module are shared by the title bar, the
center audio-only card, and the right Info tab.  The Info tab gets grouped
lists, while the older ``details`` list is kept for compatibility with any
existing callers.
"""

from __future__ import annotations

import logging
import re
from fractions import Fraction
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from core import paths

log = logging.getLogger(__name__)


_UNKNOWN = "\u2014"


def _fmt_duration(ms: int) -> str:
    try:
        ms = int(ms)
    except (TypeError, ValueError, OverflowError):
        return _UNKNOWN
    if ms <= 0:
        return _UNKNOWN
    total = ms // 1000
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_bitrate(bps: int) -> str:
    """Legacy formatter retained for the compatibility ``details`` list."""
    try:
        bps = int(bps)
    except (TypeError, ValueError, OverflowError):
        return _UNKNOWN
    return f"{bps // 1000} kbps" if bps > 0 else _UNKNOWN


def _fmt_size(size: int | None) -> str:
    """Format a filesystem size without adding a third-party dependency."""
    if size is None:
        return _UNKNOWN
    try:
        value = float(size)
    except (TypeError, ValueError, OverflowError):
        return _UNKNOWN
    if value < 0:
        return _UNKNOWN

    units = ("B", "KB", "MB", "GB", "TB")
    unit = 0
    while value >= 1024.0 and unit < len(units) - 1:
        value /= 1024.0
        unit += 1
    if unit == 0:
        number = str(int(value))
    else:
        number = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{number} {units[unit]}"


def _as_int(value, default: int | None = None) -> int | None:
    """Read Python ints and ctypes/enum values safely."""
    if value is None:
        return default
    inner = getattr(value, "value", None)
    if inner is not None and inner is not value:
        value = inner
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _field(obj, *names, default=None):
    """Return the first available attribute from a VLC track structure.

    python-vlc has used both short field names and C-style names across
    releases.  Keeping the compatibility lookup in one place means an older
    libVLC simply omits an optional row instead of breaking metadata loading.
    """
    if obj is None:
        return default
    for name in names:
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if value is not None:
            return value
    return default


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace").strip()
    return str(value).strip()


def _contents(track, name: str):
    """Unwrap a python-vlc pointer, or return an already-unwrapped object."""
    pointer = _field(track, name)
    if pointer is None:
        return None
    try:
        return pointer.contents
    except (AttributeError, ValueError):
        return pointer


def _fourcc(codec: int) -> str:
    try:
        number = _as_int(codec)
        if number is None:
            return _text(codec) or _UNKNOWN
        raw = (number & 0xFFFFFFFF).to_bytes(4, "little")
        text = raw.decode("ascii", "ignore").strip("\x00 ")
        return text.upper() or str(number)
    except Exception:
        return _text(codec) or _UNKNOWN


def _append(rows: list[dict], label: str, value) -> None:
    """Append a useful row, but never put a blank optional value in the UI."""
    text = _text(value)
    if text:
        rows.append({"label": label, "value": text})


def _meta_value(media, vlc, name: str) -> str:
    """Read a libVLC tag while tolerating missing enum members."""
    meta_enum = getattr(vlc, "Meta", None)
    key = getattr(meta_enum, name, None)
    if key is None:
        return ""
    try:
        return _text(media.get_meta(key))
    except Exception:
        return ""


def _optional_text(obj, names: tuple[str, ...], *, fourcc: bool = False) -> str:
    """Read an optional track field and format it for a row."""
    for name in names:
        value = _field(obj, name)
        if value is None:
            continue
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if fourcc and not isinstance(value, (str, bytes)):
            number = _as_int(value)
            if number in (None, -1, 0):
                continue
            return _fourcc(number)
        numeric = _as_int(value) if not isinstance(value, (str, bytes)) else None
        if numeric in (-1, 0):
            continue
        text = _text(value)
        if text and text not in ("-1", "0", "None"):
            return text
    return ""


def _sample_rate(value) -> str:
    rate = _as_int(value)
    if rate is None or rate <= 0:
        return ""
    if rate >= 1000:
        number = f"{rate / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{number} kHz"
    return f"{rate} Hz"


def _channel_layout(channels: int | None) -> str:
    if channels == 1:
        return "Mono"
    if channels == 2:
        return "Stereo"
    if channels == 6:
        return "5.1"
    if channels == 8:
        return "7.1"
    return ""


def _aspect_ratio(width: int | None, height: int | None, video) -> str:
    if not width or not height:
        return ""
    sar_num = _as_int(_field(video, "sar_num", "i_sar_num"), 1) or 1
    sar_den = _as_int(_field(video, "sar_den", "i_sar_den"), 1) or 1
    if sar_num <= 0 or sar_den <= 0:
        sar_num, sar_den = 1, 1
    try:
        ratio = (width * sar_num) / (height * sar_den)
        fraction = Fraction(ratio).limit_denominator(100)
        return f"{fraction.numerator}:{fraction.denominator}"
    except (TypeError, ValueError, ZeroDivisionError):
        return ""


def _release_year(value: str) -> str:
    match = re.search(r"\b(\d{4})\b", value or "")
    return match.group(1) if match else _text(value)


def _track_type(track, vlc, name: str) -> bool:
    track_type = getattr(track, "type", None)
    enum = getattr(getattr(vlc, "TrackType", None), name, None)
    return enum is not None and track_type == enum


def _video_rows(video_tracks: list) -> list[dict]:
    """Build one concise set of rows for the first video stream.

    The Info tab is a summary, not a track selector.  Showing one set of rows
    avoids repeating the same labels when a file contains several streams.
    Track selection remains in the existing transport controls where it
    belongs.
    """
    if not video_tracks:
        return []

    track = video_tracks[0]
    video = _contents(track, "video")
    rows: list[dict] = []

    width = _as_int(_field(video, "width", "i_width"))
    height = _as_int(_field(video, "height", "i_height"))
    if width and height:
        _append(rows, "Resolution", f"{width}\u00D7{height}")
        _append(rows, "Aspect ratio", _aspect_ratio(width, height, video))

    frame_num = _as_int(_field(video, "frame_rate_num", "i_frame_rate_num"))
    frame_den = _as_int(_field(video, "frame_rate_den", "i_frame_rate_den"))
    if frame_num and frame_den:
        _append(rows, "Frame rate", f"{frame_num / frame_den:.3g} fps")

    codec = _as_int(_field(track, "codec"))
    if codec:
        _append(rows, "Video codec", _fourcc(codec))

    profile = _as_int(_field(track, "profile", "i_profile"))
    if profile is not None and profile >= 0:
        _append(rows, "Video profile", profile)

    # These fields are not present in every libVLC/python-vlc structure.  Read
    # them when a build exposes them; otherwise leave the row out rather than
    # guessing a value or requiring a second parser such as ffprobe.
    _append(
        rows,
        "Pixel format",
        _optional_text(video, ("pixel_format", "chroma", "format"), fourcc=True),
    )
    bit_depth = _optional_text(
        video,
        ("bit_depth", "bits_per_component", "component_bits"),
    ) or _optional_text(track, ("bit_depth", "bits_per_component"))
    _append(rows, "Bit depth", bit_depth)

    hdr = _optional_text(video, ("hdr", "hdr_format", "hdr_metadata", "color_transfer"))
    _append(rows, "HDR", hdr)

    scan = _optional_text(video, ("scan_type", "interlace_mode"))
    if not scan:
        interlaced = _field(video, "interlaced", "is_interlaced")
        progressive = _field(video, "progressive", "is_progressive")
        if interlaced is True:
            scan = "Interlaced"
        elif progressive is True:
            scan = "Progressive"
    _append(rows, "Scan type", scan)

    return rows


def _audio_rows(audio_tracks: list, engine) -> list[dict]:
    """Build rows for the selected audio stream plus a stream count."""
    if not audio_tracks:
        return []

    selected_id = -1
    try:
        current = _as_int(engine.current_audio_track(), -1)
        selected_id = -1 if current is None else current
    except Exception:
        pass

    selected = None
    for track in audio_tracks:
        if _as_int(_field(track, "id"), -2) == selected_id:
            selected = track
            break
    selected = selected or audio_tracks[0]
    audio = _contents(selected, "audio")

    rows: list[dict] = []
    codec = _as_int(_field(selected, "codec"))
    if codec:
        _append(rows, "Audio codec", _fourcc(codec))
    _append(rows, "Audio tracks", len(audio_tracks))

    channels = _as_int(_field(audio, "channels", "i_channels"))
    if channels is not None and channels >= 0:
        _append(rows, "Channels", channels)
        _append(rows, "Channel layout", _channel_layout(channels))

    _append(rows, "Sample rate", _sample_rate(_field(audio, "rate", "i_rate")))

    bit_depth = _optional_text(
        audio,
        ("bit_depth", "bits_per_sample", "bits_per_component"),
    ) or _optional_text(selected, ("bit_depth", "bits_per_sample"))
    _append(rows, "Bit depth", bit_depth)

    return rows


class Metadata(QObject):
    """Metadata for whatever is currently loaded."""

    changed = Signal()

    #: How many times to re-read while waiting for libVLC's async parse.
    _MAX_RETRIES = 5

    def __init__(self, engine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._title = ""
        self._artist = ""
        self._album = ""
        self._artwork = ""
        self._details: list[dict] = []
        self._file_details: list[dict] = []
        self._general_details: list[dict] = []
        self._video_details: list[dict] = []
        self._audio_details: list[dict] = []
        self._music_details: list[dict] = []
        self._has_video = False
        self._has_audio = False
        self._media_type = ""
        self._path = ""
        self._retries = 0

    @Slot(str)
    def load(self, path: str) -> None:
        """Read metadata for ``path``.

        libVLC parses asynchronously, so the first read right after a track
        opens usually returns empty strings for title/artist/album/art. A
        couple of short retries pick the values up as soon as the parse lands
        — cheap, and the alternative (subscribing to MediaParsedChanged) fires
        on a VLC thread and would need marshalling back anyway.
        """
        self._reset()
        self._retries = 0
        if not path:
            self.changed.emit()
            return
        self._path = path
        self._read(path)

    def _read(self, path: str) -> None:
        file_path = Path(paths.normalise_path(path))
        try:
            display_path = file_path.expanduser().resolve()
        except (OSError, RuntimeError):
            display_path = file_path

        self._title = file_path.stem
        self._artist = ""
        self._album = ""
        self._artwork = ""

        extension = file_path.suffix.lstrip(".").upper() or _UNKNOWN
        file_rows = [
            {"label": "File name", "value": file_path.name or _UNKNOWN},
            {"label": "Location", "value": str(display_path) or _UNKNOWN},
        ]
        try:
            size = display_path.stat().st_size
        except (OSError, ValueError):
            size = None
        file_rows.append({"label": "File size", "value": _fmt_size(size)})
        file_rows.append({"label": "Extension", "value": extension})

        # Keep the old flat list populated for compatibility. The new Info tab
        # uses the grouped properties below and intentionally does not render
        # the old extension-derived Container row.
        legacy_details = [
            {"label": "File", "value": file_path.name},
            {"label": "Container", "value": extension},
        ]

        duration = 0
        video_tracks: list = []
        audio_tracks: list = []
        meta_values: dict[str, str] = {}
        media = None

        try:
            import vlc

            player = getattr(self._engine, "raw_player", None)
            media = player.get_media() if player is not None else None
            if media is not None:
                # `local` alone parses the stream but never goes looking for
                # cover art. `fetch_local` also extracts embedded covers and
                # picks up folder.jpg / cover.jpg beside the file.
                try:
                    parse_flags = getattr(vlc, "MediaParseFlag", None)
                    local_flag = getattr(parse_flags, "local", None)
                    fetch_flag = getattr(parse_flags, "fetch_local", None)
                    flags = 0
                    if local_flag is not None:
                        flags |= _as_int(getattr(local_flag, "value", local_flag), 0) or 0
                    if fetch_flag is not None:
                        flags |= _as_int(getattr(fetch_flag, "value", fetch_flag), 0) or 0
                    media.parse_with_options(flags, 3000)
                except Exception:
                    log.debug("libVLC metadata parse failed for %s", path, exc_info=True)

                for name in (
                    "Title",
                    "Artist",
                    "Album",
                    "AlbumArtist",
                    "Genre",
                    "Date",
                    "TrackNumber",
                    "DiscNumber",
                    "Composer",
                    "Publisher",
                    "ArtworkURL",
                ):
                    meta_values[name] = _meta_value(media, vlc, name)

                self._title = meta_values.get("Title", "") or self._title
                self._artist = meta_values.get("Artist", "")
                self._album = meta_values.get("Album", "")
                self._artwork = meta_values.get("ArtworkURL", "")

                try:
                    duration = _as_int(media.get_duration(), 0) or 0
                except Exception:
                    duration = 0

                try:
                    tracks = list(media.tracks_get() or [])
                except Exception:
                    tracks = []
                    log.debug("could not read tracks for %s", path, exc_info=True)

                video_tracks = [t for t in tracks if _track_type(t, vlc, "video")]
                audio_tracks = [t for t in tracks if _track_type(t, vlc, "audio")]

                # Preserve the existing flat detail behavior for callers that
                # still use it. Per-stream failures are isolated so one unusual
                # track cannot erase the rest of the metadata.
                if media is not None:
                    legacy_details.append(
                        {"label": "Duration", "value": _fmt_duration(duration)}
                    )
                for track in video_tracks:
                    video = _contents(track, "video")
                    width = _as_int(_field(video, "width", "i_width"))
                    height = _as_int(_field(video, "height", "i_height"))
                    if width and height:
                        legacy_details.append(
                            {
                                "label": "Resolution",
                                "value": f"{width}\u00D7{height}",
                            }
                        )
                    frame_num = _as_int(_field(video, "frame_rate_num", "i_frame_rate_num"))
                    frame_den = _as_int(_field(video, "frame_rate_den", "i_frame_rate_den"))
                    if frame_num and frame_den:
                        legacy_details.append(
                            {
                                "label": "Frame rate",
                                "value": f"{frame_num / frame_den:.3g} fps",
                            }
                        )
                    codec = _as_int(_field(track, "codec"))
                    if codec:
                        legacy_details.append(
                            {"label": "Video codec", "value": _fourcc(codec)}
                        )
                for track in audio_tracks:
                    audio = _contents(track, "audio")
                    codec = _as_int(_field(track, "codec"))
                    if codec:
                        legacy_details.append(
                            {"label": "Audio codec", "value": _fourcc(codec)}
                        )
                    channels = _as_int(_field(audio, "channels", "i_channels"))
                    rate = _as_int(_field(audio, "rate", "i_rate"))
                    if channels is not None or rate is not None:
                        legacy_details.append(
                            {
                                "label": "Channels",
                                "value": f"{channels or 0} ch @ {rate or 0} Hz",
                            }
                        )
                    bitrate = _as_int(_field(track, "bitrate", "i_bitrate"))
                    if bitrate:
                        legacy_details.append(
                            {"label": "Bitrate", "value": _fmt_bitrate(bitrate)}
                        )
        except Exception:
            # A missing VLC install or a media-specific metadata problem must
            # never prevent the application from playing or opening the panel.
            log.debug("metadata parse failed for %s", path, exc_info=True)

        self._has_video = bool(video_tracks)
        self._has_audio = bool(audio_tracks)
        self._media_type = "Video" if self._has_video else "Audio" if self._has_audio else "Unknown"

        general_rows: list[dict] = []
        # If the title is only the filename fallback, File already displays it.
        # This avoids showing the same text twice in the new grouped view.
        if self._title and self._title != file_path.stem:
            _append(general_rows, "Title", self._title)
        _append(general_rows, "Duration", _fmt_duration(duration))
        _append(general_rows, "Media type", self._media_type)

        music_rows: list[dict] = []
        _append(music_rows, "Artist", self._artist)
        _append(music_rows, "Album", self._album)
        _append(music_rows, "Album artist", meta_values.get("AlbumArtist", ""))
        _append(music_rows, "Genre", meta_values.get("Genre", ""))
        _append(music_rows, "Release year", _release_year(meta_values.get("Date", "")))
        _append(music_rows, "Track number", meta_values.get("TrackNumber", ""))
        _append(music_rows, "Disc number", meta_values.get("DiscNumber", ""))
        _append(music_rows, "Composer", meta_values.get("Composer", ""))
        _append(music_rows, "Publisher", meta_values.get("Publisher", ""))

        self._details = legacy_details
        self._file_details = file_rows
        self._general_details = general_rows
        self._video_details = _video_rows(video_tracks) if video_tracks else []
        self._audio_details = _audio_rows(audio_tracks, self._engine)
        self._music_details = music_rows
        self.changed.emit()

        # If the parse is still incomplete, look again shortly. Bounded so a
        # file that genuinely has no tags / no tracks does not retry forever.
        # Auto needs width×height, so a video whose tags arrived before its
        # resolution (or a file whose tracks have not been enumerated yet)
        # must keep retrying — the original "tags only" guard stopped after
        # the first artist/album hit and left Auto stuck on Soft.
        parsed_tags = bool(
            self._artist or self._album or self._artwork or self._music_details
        )
        has_tracks = bool(self._has_video or self._has_audio)
        video_sized = (not self._has_video) or any(
            str(row.get("label", "")).strip().lower() == "resolution"
            for row in self._video_details
        )
        if self._retries < self._MAX_RETRIES and not (
            parsed_tags and has_tracks and video_sized
        ):
            self._retries += 1
            QTimer.singleShot(400, self._retry)

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
        self._file_details = []
        self._general_details = []
        self._video_details = []
        self._audio_details = []
        self._music_details = []
        self._has_video = False
        self._has_audio = False
        self._media_type = ""
        self._path = ""

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
        """Legacy flat metadata list kept for compatibility."""
        return self._details

    @Property("QVariantList", notify=changed)
    def fileDetails(self) -> list:  # noqa: N802 - QML-facing
        return self._file_details

    @Property("QVariantList", notify=changed)
    def generalDetails(self) -> list:  # noqa: N802 - QML-facing
        return self._general_details

    @Property("QVariantList", notify=changed)
    def videoDetails(self) -> list:  # noqa: N802 - QML-facing
        return self._video_details

    @Property("QVariantList", notify=changed)
    def audioDetails(self) -> list:  # noqa: N802 - QML-facing
        return self._audio_details

    @Property("QVariantList", notify=changed)
    def musicDetails(self) -> list:  # noqa: N802 - QML-facing
        return self._music_details

    @Property(bool, notify=changed)
    def hasVideo(self) -> bool:  # noqa: N802 - QML-facing
        return self._has_video

    @Property(bool, notify=changed)
    def hasAudio(self) -> bool:  # noqa: N802 - QML-facing
        return self._has_audio

    @Property(str, notify=changed)
    def mediaType(self) -> str:  # noqa: N802 - QML-facing
        return self._media_type
