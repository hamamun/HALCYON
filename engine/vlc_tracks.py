"""Safe access to libVLC 3 media-track descriptors.

``python-vlc==3.0.21203`` exposes :meth:`Media.tracks_get` as a generator over a
native allocation, but the generated binding leaves its matching release call
commented out.  Converting that generator to a list does not transfer ownership;
every call leaks the complete native track array.  Halcyon refreshes tracks on
ESAdded/ESDeleted and metadata retries, so the leak sits directly on media load.

This context manager uses the same raw API as the generated method, preserves the
native allocation while callers inspect nested audio/video/language pointers,
and releases it exactly once afterwards.  A small fallback supports test doubles
that only implement ``tracks_get``; real python-vlc modules always take the raw
path.
"""

from __future__ import annotations

import ctypes
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def media_tracks(vlc_module, media) -> Iterator[tuple]:
    """Yield media-track structs whose native backing remains valid in the block."""
    get_tracks = getattr(vlc_module, "libvlc_media_tracks_get", None)
    release_tracks = getattr(vlc_module, "libvlc_media_tracks_release", None)
    media_track_type = getattr(vlc_module, "MediaTrack", None)

    if callable(get_tracks) and callable(release_tracks) and media_track_type is not None:
        # This mirrors python-vlc's generated Media.tracks_get() pointer layout.
        # The release binding expects MediaTrack**, hence the explicit cast in
        # finally rather than passing the generated method's MediaTrack* value.
        native = ctypes.POINTER(media_track_type)()
        count = int(get_tracks(media, ctypes.byref(native)))
        if count <= 0 or not native:
            yield ()
            return

        pointer_array = ctypes.cast(
            native, ctypes.POINTER(ctypes.POINTER(media_track_type) * count)
        )
        try:
            contents = pointer_array.contents
            tracks = tuple(
                contents[index].contents
                for index in range(count)
                if bool(contents[index])
            )
            yield tracks
        finally:
            release_tracks(
                ctypes.cast(native, ctypes.POINTER(ctypes.POINTER(media_track_type))),
                count,
            )
        return

    # Test-double compatibility. There is no C allocation to release here.
    fallback = getattr(media, "tracks_get", None)
    yield tuple(fallback() or ()) if callable(fallback) else ()
