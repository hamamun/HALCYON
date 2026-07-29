"""What counts as video, audio and a subtitle — the one home (§A.3).

This used to live in ``modes/local/playlist.py``, which made the chassis depend
on a mode: ``core/app.py`` had to reach into Local to ask "is this a subtitle?"
before it could route a dropped file. It softened that with a lazy import, but
the dependency was real and ``tools/check_isolation.py`` reported it on every
run — rule 2, *nothing shared imports a mode*.

The dependency was also backwards. "``.mkv`` is video" is not a fact about
Local's playlist; it is a fact about media, and Phase 2's M3U and Phase 3's Web
need the same answer. Delete ``modes/local`` and this must still be true. So the
knowledge moves down into ``core`` and the mode borrows it, which is the
direction the architecture already specifies.

``modes.local.playlist`` re-exports these names, so existing imports keep
working and the mode reads no differently.
"""

from __future__ import annotations

from pathlib import Path

#: Extensions Add Folder will pick up (§P1.5). Deliberately generous — libVLC
#: plays far more than this, but a recursive scan should not hoover up .txt.
VIDEO_EXTENSIONS = frozenset({
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".asf", ".ts", ".m2ts", ".mts",
    ".mxf", ".flv", ".f4v", ".webm", ".mpg", ".mpeg", ".m4v", ".3gp",
    ".ogv", ".vob", ".divx", ".rmvb", ".m2v", ".h264", ".264", ".hevc",
})

AUDIO_EXTENSIONS = frozenset({
    ".mp3", ".flac", ".aac", ".opus", ".ogg", ".oga", ".wav", ".m4a", ".wma",
    ".alac", ".ape", ".aiff", ".aif", ".aifc", ".dsf", ".dff", ".mka", ".mpc",
    ".m4b", ".m4p", ".mpga", ".caf", ".amr", ".3ga", ".mid", ".midi",
})

MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

#: Sidecar subtitle formats. These are **not** media and must never enter the
#: queue: libVLC will happily "open" a .srt as a media item, produce a track
#: with no video and no audio, tear the video pipeline down and leave the UI
#: showing a track that can never play. Dropping one is a request to subtitle
#: the *current* video — core.app routes them there instead (§P1.5).
SUBTITLE_EXTENSIONS = frozenset({
    ".srt", ".ass", ".ssa", ".sub", ".vtt", ".idx", ".sup", ".smi", ".txt",
})


def _suffix(path: str | Path) -> str:
    return Path(str(path)).suffix.lower()


def is_video(path: str | Path) -> bool:
    """True for a moving picture.

    Resume is video-only (§P1.5), so this is the gate that decides whether a
    file gets a resume prompt. An album track you were 40 seconds into does not
    want a modal dialog on every play.
    """
    return _suffix(path) in VIDEO_EXTENSIONS


def is_audio(path: str | Path) -> bool:
    return _suffix(path) in AUDIO_EXTENSIONS


def is_media(path: str | Path) -> bool:
    return _suffix(path) in MEDIA_EXTENSIONS


def is_subtitle(path: str | Path) -> bool:
    return _suffix(path) in SUBTITLE_EXTENSIONS
