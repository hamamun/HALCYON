"""Per-media hardware-decode policy — Turbo's codec brain (§V.2).

Turbo is *two* independent things and only reads as one from the outside:

* the **output route** — libVLC renders into the native child window
  (``engine/turbo_surface.py``) instead of the vmem callbacks. This works for
  every file and is what the user-facing "Turbo" badge reports;
* the **decode method** — ``:avcodec-hw=d3d11va`` asks the GPU driver to
  decompress the frames. This is great for modern codecs and a black screen
  for old ones.

The bug this module exists for: forcing ``d3d11va`` on *everything* the Turbo
route opens. Modern drivers advertise VC-1 (WMV3) and DivX-era MPEG-4 decode
and then reject the actual work — the visible symptom is FFmpeg spamming
``Failed to execute: 0x80070057`` (E_INVALIDARG) once per frame while the user
stares at a black picture. VLC's own desktop player never does this: it keeps
the native window for every file and quietly decodes legacy codecs on the
CPU. This module gives Halcyon the same judgement.

Two verdict sources, in order of trust:

:func:`media_gpu_safe`
    The real codec fourccs from a *parsed* media's track list. Authoritative,
    but only available once libVLC has parsed the container — which is after
    ``open()`` has already had to choose the media options
    (``parse_with_options`` is asynchronous). The engine therefore consults it
    from the playback poll, where a known-bad codec triggers the CPU fallback
    within a tick or two of the tracks landing.

:func:`path_gpu_safe`
    The container extension. Available synchronously at ``open()`` time, and
    right in practice: ``.wmv``/``.asf`` is VC-1 or WMV3, ``.avi`` is DivX-era
    MPEG-4, and none of those are worth a GPU decoder anybody still tests.
    Wrong only for exotica (H.264 in ``.avi``), and being wrong is cheap —
    the cost is CPU-decoding a file the GPU could have handled, which for
    every legacy container in the list is a rounding error on a modern CPU.

Every verdict is three-valued: ``True`` (GPU is a good bet), ``False`` (known
bad — decode on the CPU), ``None`` (no opinion — keep the current behaviour).
Unknown deliberately resolves to "allow": most files are modern, a wrongly
allowed file is rescued by the engine's runtime watchdog
(``VlcEngine._check_hw_decode_health``), and a wrongly *blocked* file would
have no rescue at all.

Deliberately pure Python — no ``vlc`` import, no Qt — so it stays importable
and testable anywhere, like :mod:`core.video_mode` (§A.3 rule 2).
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import unquote, urlparse

log = logging.getLogger(__name__)

#: The per-media libVLC options used to make the decoder choice explicit.
#:
#: ``CPU_DECODE_OPTION`` is deliberately not represented by merely omitting
#: ``HW_DECODE_OPTION``.  In libVLC 3, ``libvlc_media_player_set_hwnd()`` sets
#: the player's ``avcodec-hw`` variable to an empty string (automatic).  That
#: player-level value is closer than the instance's ``--avcodec-hw=none``, so
#: an option-less legacy media still enters hardware decode.  An explicit
#: per-media ``none`` overrides the HWND reset while retaining the same player
#: and Turbo's native output window.
HW_DECODE_OPTION = ":avcodec-hw=d3d11va"
CPU_DECODE_OPTION = ":avcodec-hw=none"

#: ``libvlc_track_type_t``: unknown=-1, audio=0, video=1, text=2.
_TRACK_TYPE_VIDEO = 1

#: Codecs D3D11VA decoders are actually built and tested for. H.264/HEVC are
#: universal; VP9 and AV1 are present on anything recent. A fourcc in this set
#: is what the GPU vendors mean when they say "hardware video decode".
GPU_SAFE_CODECS = frozenset({
    "H264", "X264", "AVC1", "DAVC", "VSSH",           # H.264 / AVC
    "H265", "X265", "HEVC", "HVC1", "HEV1",           # H.265 / HEVC
    "VP90", "VP09",                                   # VP9
    "AV01",                                           # AV1
})

#: Codecs where the hardware path is abandoned, broken, or never existed.
#: VC-1/WMV3 is the headline case: drivers still *advertise* it, create the
#: decoder, then fail every ``Execute`` call (0x80070057) — a black screen
#: with perfect audio. The rest are DivX-era MPEG-4 variants, RealVideo,
#: Theora, H.263 and friends: all trivial for a CPU, all pointless to risk
#: on a driver path nobody has tested this decade.
GPU_UNSAFE_CODECS = frozenset({
    "WMV1", "WMV2", "WMV3", "WMVA", "WMVP", "WVP2", "WVC1", "VC-1", "WMVR",
    "DIV1", "DIV2", "DIV3", "DIV4", "DIV5", "DIV6", "DIVX", "DX50",
    "XVID", "3IV2", "3IVX", "FMP4", "MP4V", "MP4S", "MP42", "MP43",
    "MPG1", "MPG2", "MPGV", "MPEG", "MP2V", "M2V1",
    "H261", "H263", "I263", "U263", "FLV1",
    "VP30", "VP31", "VP40", "VP50", "VP60", "VP61", "VP62",
    "RV10", "RV13", "RV20", "RV30", "RV40",
    "THEO", "MJPG", "MSVC", "CRAM", "CVID", "SVQ1", "SVQ3",
    "IV31", "IV32", "IV41", "IV50",
})

#: Containers whose video is, in practice, always a legacy codec. The engine
#: replaces the GPU request with an explicit CPU request for these at
#: ``open()`` time, before the driver gets a chance to lie.
GPU_UNSAFE_EXTENSIONS = frozenset({
    ".wmv", ".asf", ".wm",                 # Windows Media → WMV3 / VC-1
    ".avi", ".divx",                       # DivX/XviD-era MPEG-4
    ".flv", ".f4v",                        # Flash video → H.263 / VP6
    ".rm", ".rmvb", ".ram",                # RealVideo
    ".vob", ".mpg", ".mpeg", ".mpe",       # MPEG-1/2
    ".m1v", ".m2v", ".dat",
    ".3gp", ".3g2",                        # mobile H.263 / MPEG-4
    ".ogm", ".ogv",                        # Theora
    ".dv",
})

#: Containers that overwhelmingly carry modern codecs. Not load-bearing —
#: an unknown extension resolves to "allow" anyway — but an explicit ``True``
#: documents the common case and keeps the tests honest.
GPU_SAFE_EXTENSIONS = frozenset({
    ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".ts", ".m2ts", ".mts",
})


def _as_int(value) -> int | None:
    """Read Python ints and ctypes/enum values safely (``.value`` unwrap)."""
    if value is None:
        return None
    inner = getattr(value, "value", None)
    if inner is not None and inner is not value:
        value = inner
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def fourcc_text(codec) -> str:
    """A libVLC ``codec`` field as its four-character tag, uppercased.

    libVLC stores fourccs as little-endian ``uint32`` — the same reading
    ``core.metadata`` uses for the Info panel, so the string compared here is
    the string the user sees under "Video codec". Accepts a ready-made string
    too (tests, future callers). Unreadable input yields ``""``, which every
    classifier below treats as "no opinion".
    """
    if isinstance(codec, str):
        return codec.strip().upper()
    if isinstance(codec, bytes):
        return codec.decode("ascii", "ignore").strip("\x00 ").upper()
    number = _as_int(codec)
    if number is None or number <= 0:
        return ""
    try:
        raw = (number & 0xFFFFFFFF).to_bytes(4, "little")
        return raw.decode("ascii", "ignore").strip("\x00 ").upper()
    except Exception:
        return ""


def codec_gpu_safe(fourcc) -> bool | None:
    """Is this video codec worth handing to a D3D11 decoder?

    ``True``/``False`` for codecs with a known track record, ``None`` for
    anything unrecognised — the caller keeps its current behaviour rather
    than guessing.
    """
    tag = fourcc_text(fourcc)
    if not tag:
        return None
    if tag in GPU_SAFE_CODECS:
        return True
    if tag in GPU_UNSAFE_CODECS:
        return False
    return None


def media_gpu_safe(media) -> bool | None:
    """Verdict from a media's actual video track codecs, or ``None``.

    ``None`` covers every "cannot know" case in one answer: no media, a build
    without ``tracks_get``, an unparsed container (``tracks_get`` empty —
    normal at ``open()`` time, since ``parse_with_options`` is asynchronous),
    no video track at all, or only unrecognised codecs.

    ``False`` wins over ``True`` when tracks disagree: one legacy track is
    enough to make the GPU request a bad bet for this media.
    """
    if media is None:
        return None
    getter = getattr(media, "tracks_get", None)
    if not callable(getter):
        return None
    try:
        tracks = list(getter() or [])
    except Exception:
        log.debug("tracks_get failed while classifying codecs", exc_info=True)
        return None

    verdicts: list[bool | None] = []
    for track in tracks:
        if _as_int(getattr(track, "type", None)) != _TRACK_TYPE_VIDEO:
            continue
        verdicts.append(codec_gpu_safe(getattr(track, "codec", None)))
    if not verdicts:
        return None
    if any(verdict is False for verdict in verdicts):
        return False
    if all(verdict is True for verdict in verdicts):
        return True
    return None


def _extension(path_or_mrl) -> str:
    """Lower-case file extension from a path or an MRL (``file://...``)."""
    text = str(path_or_mrl or "").strip()
    if not text:
        return ""
    if "://" in text:
        try:
            text = unquote(urlparse(text).path or "")
        except Exception:
            return ""
    try:
        return Path(text).suffix.lower()
    except Exception:
        return ""


def path_gpu_safe(path_or_mrl) -> bool | None:
    """Verdict from the container extension alone.

    The synchronous gate for ``open()``: codec truth is not available yet
    (see the module docstring), and the extension is right for every file
    that actually produced the black-screen reports. ``None`` for anything
    not listed — unknown containers keep the GPU request and rely on the
    runtime watchdog.
    """
    extension = _extension(path_or_mrl)
    if not extension:
        return None
    if extension in GPU_UNSAFE_EXTENSIONS:
        return False
    if extension in GPU_SAFE_EXTENSIONS:
        return True
    return None
