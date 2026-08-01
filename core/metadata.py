"""Track metadata and album art — Milestone 1.8.

Everything comes from libVLC's own parser, so there is no ffprobe or mutagen
dependency to bundle (§P1.5: "via libVLC (no ffprobe)").
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from core import paths

log = logging.getLogger(__name__)


def _fmt_duration(ms: int) -> str:
    if ms <= 0:
        return "\u2014"
    total = ms // 1000
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_bitrate(bps: int) -> str:
    return f"{bps // 1000} kbps" if bps > 0 else "\u2014"


def _fmt_size(bytes_val: int) -> str:
    if bytes_val <= 0:
        return "\u2014"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if bytes_val < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(bytes_val)} B"
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return "\u2014"


def _clean_str(val: object) -> str:
    if val is None:
        return ""
    if isinstance(val, bytes):
        try:
            return val.decode("utf-8", "ignore").strip("\x00 ")
        except Exception:
            return str(val)
    if hasattr(val, "value"):
        val = getattr(val, "value", None)
        if val is None:
            return ""
        if isinstance(val, bytes):
            try:
                return val.decode("utf-8", "ignore").strip("\x00 ")
            except Exception:
                return str(val)
    return str(val).strip("\x00 ")


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
        self._title = file_path.stem

        file_size = 0
        try:
            if file_path.exists():
                file_size = file_path.stat().st_size
        except Exception:
            file_size = 0

        details = [
            {"label": "File", "value": file_path.name},
        ]
        if file_size > 0:
            details.append({"label": "File size", "value": _fmt_size(file_size)})
        details.append(
            {"label": "Container", "value": file_path.suffix.lstrip(".").upper() or "\u2014"}
        )

        try:
            import vlc

            player = getattr(self._engine, "raw_player", None)
            media = player.get_media() if player is not None else None
            if media is not None:
                # Parsing is performed exactly once by the engine (in open())
                # with full local+fetch_local flags *before* mediaChanged is
                # emitted. Re-invoking parse_with_options from here (even
                # guarded) while the media is attached to the player can cause
                # demuxer contention / crashes inside libVLC. Do not call it.
                def meta(key):
                    try:
                        value = media.get_meta(key)
                        return value or ""
                    except Exception:
                        return ""

                self._title = meta(vlc.Meta.Title) or self._title
                self._artist = meta(vlc.Meta.Artist)
                self._album = meta(vlc.Meta.Album)
                self._artwork = meta(vlc.Meta.ArtworkURL)

                genre = meta(vlc.Meta.Genre)
                date_str = meta(vlc.Meta.Date)
                track_num = meta(vlc.Meta.TrackNumber)
                track_total = meta(vlc.Meta.TrackTotal)

                try:
                    duration = int(media.get_duration())
                except Exception:
                    duration = 0
                details.append({"label": "Duration", "value": _fmt_duration(duration)})

                if self._album:
                    details.append({"label": "Album", "value": self._album})
                if track_num and str(track_num).strip() not in ("0", ""):
                    t_str = str(track_num).strip()
                    if track_total and str(track_total).strip() not in ("0", ""):
                        t_str = f"{t_str} of {str(track_total).strip()}"
                    details.append({"label": "Track", "value": t_str})
                if genre:
                    details.append({"label": "Genre", "value": genre})
                if date_str:
                    details.append({"label": "Year", "value": str(date_str).strip()})

                audio_count = 0
                subtitle_tracks: list[str] = []
                for track in media.tracks_get() or []:
                    try:
                        if track.type == vlc.TrackType.video:
                            codec_str = _fourcc(track.codec)
                            if track.video:
                                video = track.video.contents
                                details.append(
                                    {
                                        "label": "Resolution",
                                        "value": f"{video.width}\u00D7{video.height}",
                                    }
                                )
                                fps = (
                                    video.frame_rate_num / video.frame_rate_den
                                    if video.frame_rate_den
                                    else 0
                                )
                                if fps:
                                    details.append({"label": "Frame rate", "value": f"{fps:.3g} fps"})
                            details.append(
                                {"label": "Video codec", "value": codec_str}
                            )
                        elif track.type == vlc.TrackType.audio:
                            audio_count += 1
                            suffix = f" #{audio_count}" if audio_count > 1 else ""
                            codec_str = _fourcc(track.codec)
                            lang_str = _clean_str(getattr(track, "language", ""))
                            if lang_str and lang_str.lower() not in codec_str.lower():
                                codec_str = f"{codec_str} ({lang_str})"
                            details.append(
                                {"label": f"Audio codec{suffix}", "value": codec_str}
                            )
                            if track.audio:
                                audio = track.audio.contents
                                details.append(
                                    {
                                        "label": f"Channels{suffix}",
                                        "value": f"{audio.channels} ch @ {audio.rate} Hz",
                                    }
                                )
                            if getattr(track, "bitrate", 0):
                                details.append(
                                    {"label": f"Bitrate{suffix}", "value": _fmt_bitrate(track.bitrate)}
                                )
                        elif (
                            track.type == getattr(vlc.TrackType, "ext", getattr(vlc.TrackType, "text", 2))
                            or getattr(track.type, "value", track.type) == 2
                        ):
                            sub_lang = _clean_str(getattr(track, "language", ""))
                            sub_desc = _clean_str(getattr(track, "description", ""))
                            sub_codec = _fourcc(track.codec)
                            item = sub_lang or sub_desc or sub_codec
                            if sub_lang and sub_codec and sub_codec not in item:
                                item = f"{sub_lang} ({sub_codec})"
                            elif sub_desc and sub_codec and sub_codec not in item:
                                item = f"{sub_desc} ({sub_codec})"
                            if item and item not in subtitle_tracks:
                                subtitle_tracks.append(item)
                    except Exception:
                        log.debug("failed to inspect track %s in %s", track, path, exc_info=True)

                if subtitle_tracks:
                    details.append(
                        {
                            "label": "Subtitles" if len(subtitle_tracks) > 1 else "Subtitle",
                            "value": ", ".join(subtitle_tracks),
                        }
                    )
        except Exception:
            log.debug("metadata parse failed for %s", path, exc_info=True)

        self._details = details
        self.changed.emit()

        # If the parse has not produced tags yet, look again shortly. Bounded
        # so a file that genuinely has no tags does not retry forever.
        if self._retries < self._MAX_RETRIES and not (
            self._artist or self._artwork or self._album
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
        return self._details


def _fourcc(codec: int) -> str:
    try:
        if not codec:
            return ""
        # codec may arrive as c_uint32 / ctype wrapper or plain int depending
        # on python-vlc / track struct access.
        if hasattr(codec, "value"):
            codec = getattr(codec, "value", 0)
        if not codec:
            return ""
        ival = int(codec)
        if not ival:
            return ""
        raw = ival.to_bytes(4, "little")
        text = raw.decode("ascii", "ignore").strip("\x00 ")
        return text.upper() or str(ival)
    except Exception:
        try:
            return str(int(codec)) if codec else ""
        except Exception:
            return ""
