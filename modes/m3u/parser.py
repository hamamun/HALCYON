"""M3U/M3U8 playlist parsing — Milestone 2.1 (§P2.4).

Pure Python, deliberately Qt-free, so the parser is unit-testable without a
display (and on any box): bytes in, channels out.

What this understands:

* the ``#EXTM3U`` header line
* ``#EXTINF`` with a duration and the common ``tvg-*`` attributes
  (``tvg-id``, ``tvg-name``, ``tvg-logo``, ``tvg-country``) plus ``group-title``
* ``#EXTGRP`` as a fallback group
* plain entries without an ``#EXTINF`` (the URL's file name becomes the title)
* local paths — absolute, ``~``-relative and playlist-relative — and remote
  ``http(s)://`` entries, left untouched
* UTF-8 with or without BOM, Latin-1 fallback (a lot of IPTV lists are not
  UTF-8, however loudly they claim to be)
* malformed lines: skipped and counted, never fatal
* nested playlist references (``.m3u`` / ``.m3u8`` URLs, including HLS master
  playlists): explicitly ignored and counted — a playlist is a document you
  load, not a channel you play

Remote playlists are fetched with the standard library only (§P2.4 — no new
dependency).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

#: Fetch guard rails for remote playlists (§P2.4: failure must never hang or
#: crash the panel).
FETCH_TIMEOUT_S = 20
FETCH_MAX_BYTES = 32 * 1024 * 1024  # 32 MB — generous for a text playlist
USER_AGENT = "Halcyon/0.2 (+https://github.com/hamamun/HALCYON)"

_EXTINF_RE = re.compile(r"^#EXTINF\s*:\s*(-?\d+(?:\.\d+)?)?\s*(.*?),(.*)$", re.IGNORECASE)
_ATTR_RE = re.compile(r'([a-zA-Z0-9\-_]+)\s*=\s*"([^"]*)"')
#: HLS variant directives — a master playlist's stream list, not a channel.
_HLS_VARIANT_RE = re.compile(r"^#EXT-X-(STREAM-INF|MEDIA)\b", re.IGNORECASE)
_PLAYLIST_EXT = {".m3u", ".m3u8"}


@dataclass
class Channel:
    """One playable entry. Everything except ``name`` and ``url`` is optional
    metadata — real-world playlists are stingy with it."""

    name: str
    url: str
    group: str = ""
    logo: str = ""
    tvg_id: str = ""
    country: str = ""
    duration: float = -1.0

    @property
    def is_remote(self) -> bool:
        return self.url.startswith(("http://", "https://"))


@dataclass
class ParseResult:
    channels: list[Channel]
    #: Entries dropped as malformed (bad line, EXTINF with no URL) or ignored
    #: (nested playlist references). Surfaced in the UI as "N skipped".
    skipped: int = 0


def decode_playlist(data: bytes) -> str:
    """Best-effort text decode: UTF-8 with BOM first, strict UTF-8, then the
    Latin-1 floor — which never fails, since every byte is a character."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def is_url(text: str) -> bool:
    return text.startswith(("http://", "https://"))


def looks_like_playlist_ref(url: str) -> bool:
    """True when an entry points at another playlist rather than at media."""
    path = url.split("?", 1)[0].split("#", 1)[0].lower()
    return any(path.endswith(ext) for ext in _PLAYLIST_EXT)


def _attrs(raw: str) -> dict[str, str]:
    return {m.group(1).lower(): m.group(2).strip() for m in _ATTR_RE.finditer(raw)}


def _title_from_url(url: str) -> str:
    """A human label for entries that carry no EXTINF title: the file name
    without extension; the path tail as-is when it carries no dot; the host
    when a stream URL has no path at all."""
    path = url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if is_url(url):
        after_scheme = path.split("//", 1)[-1]
        if "/" not in after_scheme:                      # host only, no path
            return after_scheme.split(":", 1)[0] or url
    tail = path.rsplit("/", 1)[-1] if "/" in path else path
    if "." in tail:
        stem = tail.rpartition(".")[0]
        if stem:
            return stem
    return tail or url


def _resolve_entry_url(url: str, base_dir: Path | None) -> str:
    """Playlist-relative local paths resolve against the playlist's own folder
    (§2.1: relative and absolute paths). Remote URLs pass through untouched."""
    if is_url(url):
        return url
    candidate = Path(url).expanduser()
    if candidate.is_absolute() or base_dir is None:
        return str(candidate)
    return str(base_dir / candidate)


def parse_m3u(text: str, base_dir: Path | None = None) -> ParseResult:
    """Parse playlist *text* into channels. ``base_dir`` is the folder a local
    playlist file lives in, used to resolve relative entry paths."""
    channels: list[Channel] = []
    skipped = 0

    pending: dict | None = None  # the last EXTINF seen, waiting for its URL
    pending_group = ""           # EXTGRP is a fallback for the next entry only

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#EXTM3U"):
            continue

        if line.startswith("#EXTINF"):
            if pending is not None:
                skipped += 1   # an EXTINF that never received its URL
                pending = None
            match = _EXTINF_RE.match(line)
            if not match:
                skipped += 1
                pending = None
                continue
            duration_s, attrs_raw, title = match.groups()
            attrs = _attrs(attrs_raw)
            try:
                duration = float(duration_s) if duration_s else -1.0
            except ValueError:
                duration = -1.0
            # EXTGRP survives until its entry's URL arrives — it is the
            # fallback for THIS next entry, cleared once the entry exists.
            pending = {
                "name": (title or "").strip()
                        or attrs.get("tvg-name", ""),
                "group": attrs.get("group-title", ""),
                "logo": attrs.get("tvg-logo", ""),
                "tvg_id": attrs.get("tvg-id", ""),
                "country": attrs.get("tvg-country", ""),
                "duration": duration,
            }
            continue

        if line.startswith("#EXTGRP"):
            pending_group = line.partition(":")[2].strip()
            continue

        if _HLS_VARIANT_RE.match(line):
            # Inside a master HLS playlist: its variant URLs are streams of one
            # video, not channels. The nested-playlist check below drops them.
            skipped += 1
            continue

        if line.startswith("#"):
            # Unknown directive (#EXT-X-*, #PLAYLIST, #EXTVLCOPT...) — harmless.
            continue

        # A URL/path line belongs to the pending EXTINF, if any.
        url = _resolve_entry_url(line, base_dir)
        # Nested-playlist skip (§2.1): LOCAL references only. A remote .m3u8
        # URL is almost always the channel itself (HLS) — dropping those would
        # erase nearly every real IPTV list.
        if not is_url(url) and looks_like_playlist_ref(url):
            skipped += 1
            pending = None
            pending_group = ""
            continue

        if pending is None:
            channel = Channel(name=_title_from_url(line), url=url)
        else:
            channel = Channel(
                name=pending["name"] or _title_from_url(line),
                url=url,
                group=pending["group"] or pending_group,
                logo=pending["logo"],
                tvg_id=pending["tvg_id"],
                country=pending["country"],
                duration=pending["duration"],
            )
        channels.append(channel)
        pending = None
        pending_group = ""

    if pending is not None:
        # File ended on an EXTINF that never got a URL — malformed.
        skipped += 1

    return ParseResult(channels=channels, skipped=skipped)


def read_playlist(path: Path) -> str:
    """Read a local playlist file as text (encoding detected)."""
    return decode_playlist(Path(path).expanduser().read_bytes())


def fetch_playlist(url: str) -> str:
    """Download a remote playlist with the standard library (§P2.4).

    Failures arrive as RuntimeError with a message fit for the panel — the
    caller never sees a traceback, the user never sees a stack dump.
    """
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=FETCH_TIMEOUT_S) as response:
            data = response.read(FETCH_MAX_BYTES + 1)
    except HTTPError as exc:
        raise RuntimeError(f"server answered {exc.code}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"could not reach the playlist ({reason})") from exc
    except TimeoutError as exc:
        raise RuntimeError("the connection timed out") from exc
    if len(data) > FETCH_MAX_BYTES:
        raise RuntimeError("playlist is larger than 32 MB — refusing to load it")
    return decode_playlist(data)


def load_playlist(location: str) -> tuple[ParseResult, Path | None]:
    """Load a playlist from a local path or a remote URL.

    Returns the parsed result and the base directory used for relative entries
    (``None`` for remote playlists — relative entries there stay as written).
    """
    if is_url(location):
        return parse_m3u(fetch_playlist(location)), None
    path = Path(location).expanduser()
    return parse_m3u(read_playlist(path), base_dir=path.parent), path.parent
