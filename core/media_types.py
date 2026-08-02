"""Shared media-file classifications.

The application controller and each playback mode may need to recognise media
and subtitle extensions. Keeping these small, mode-neutral sets in ``core``
prevents shared code from importing a particular mode and preserves the
isolation contract (§A.1).
"""

from __future__ import annotations

#: Extensions accepted by Local's Add Folder scan. libVLC supports more formats,
#: but a recursive scan should not collect unrelated files.
VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".ts", ".m2ts", ".mts", ".flv",
    ".webm", ".mpg", ".mpeg", ".m4v", ".3gp", ".ogv", ".vob", ".divx", ".rmvb",
}

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".aac", ".opus", ".ogg", ".wav", ".m4a", ".wma", ".alac",
    ".ape", ".aiff", ".dsf", ".mka", ".mpc",
}

MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

#: Sidecar subtitle formats. These are not queueable media files.
SUBTITLE_EXTENSIONS = {
    ".srt", ".ass", ".ssa", ".sub", ".vtt", ".idx", ".sup", ".smi", ".txt",
}
