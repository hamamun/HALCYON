"""Remembering which channel logos are not worth asking for again.

Why this exists
---------------
A public IPTV playlist is a list of *someone else's* URLs. A large fraction of
its ``tvg-logo`` entries are dead: the Wikipedia file was renamed (404), the
host blocks hot-linking (403), the CDN has gone away (timeout), or the URL
points at an image *page* rather than an image.

Qt caches images it successfully downloaded; it does **not** cache failures.
Without a memory of our own, every visit to M3U re-requests every dead logo,
in full, forever — which is both slow and the fastest way to convince a server
that Halcyon is misbehaving.

So this module keeps two, deliberately separate, kinds of knowledge:

* :func:`is_loadable_logo` — URLs that *cannot* work, decided by inspection and
  without a request. No network, no state, no persistence.
* :class:`LogoFailureStore` — URLs that *did not* work when we tried. Learned at
  runtime, capped, and persisted next to the other M3U stores.

Pure Python (json + pathlib) so it is testable without Qt, in keeping with the
rest of ``modes/m3u`` (§A.1: nothing here reaches outside M3U).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

#: Upper bound on remembered failures. A 15k-channel playlist can contribute a
#: few thousand dead logos on its own, and a user may hold seven of them; the
#: cap keeps the file small and the load fast, and evicting the oldest entry is
#: harmless — the worst case is that one logo is retried once.
MAX_ENTRIES = 4000

#: Written after this many new failures, so a panel full of dead logos costs
#: one write rather than one per row. The rest is flushed by :meth:`save` on
#: shutdown.
SAVE_EVERY = 25

#: Qt's image reader has no SVG support unless the SVG imageformat plugin is
#: deployed, and Halcyon does not ship it. Requesting these downloads bytes
#: that can only ever end in "Unsupported image format".
_UNSUPPORTED_SUFFIXES = (".svg", ".svgz")

#: Image *hosting pages*, not images. ``https://ibb.co/BH6CZx3K`` is an HTML
#: page; the image lives on ``i.ibb.co``. Playlist authors paste the share link
#: constantly, and it can never decode as a picture.
_PAGE_ONLY_HOSTS = frozenset({"ibb.co", "imgbb.com", "postimg.cc", "imgur.com"})

#: Suffixes that make a URL unambiguously a file, used to let through the rare
#: correct ``imgur.com/xyz.png`` style link while still blocking share pages.
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico")


def is_loadable_logo(url: str) -> bool:
    """Could ``url`` *possibly* produce a picture in this build?

    Conservative on purpose: anything not positively known to be hopeless gets
    a chance, because plenty of perfectly good logo URLs carry no file
    extension at all (CDN and image-proxy links especially). Only two cases are
    refused, and both are refused without a request.
    """
    url = (url or "").strip()
    if not url:
        return False
    if url.startswith("data:"):
        return True
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    path = (parts.path or "").lower()
    if path.endswith(_UNSUPPORTED_SUFFIXES):
        return False
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host in _PAGE_ONLY_HOSTS and not path.endswith(_IMAGE_SUFFIXES):
        return False
    return True


class LogoFailureStore:
    """URLs that failed to load, remembered across sessions.

    Insertion-ordered so the cap can evict the oldest entry rather than an
    arbitrary one. Writes are batched (see :data:`SAVE_EVERY`) because the
    caller adds entries one image error at a time, and a panel scrolling past
    two hundred dead logos must not mean two hundred atomic file writes.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._urls: OrderedDict[str, None] = OrderedDict()
        self._unsaved = 0
        self.load()

    # ------------------------------------------------------------------ io --
    def load(self) -> None:
        """Read the store. Missing is normal; corrupt is not fatal."""
        self._urls = OrderedDict()
        self._unsaved = 0
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("logo failure store unreadable (%s) — starting empty", self._path)
            return
        for item in raw if isinstance(raw, list) else []:
            if isinstance(item, str) and item.strip():
                self._urls[item.strip()] = None
        while len(self._urls) > MAX_ENTRIES:
            self._urls.popitem(last=False)

    def save(self) -> None:
        """Write atomically. A no-op when nothing has changed."""
        if not self._unsaved:
            return
        self._unsaved = 0
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=self._path.name, dir=str(self._path.parent)
            )
        except OSError:
            log.debug("could not create a temp file for %s", self._path, exc_info=True)
            return
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(list(self._urls), handle, ensure_ascii=False, indent=0)
            os.replace(tmp_name, self._path)
        except OSError:
            log.warning("could not write logo failure store %s", self._path, exc_info=True)
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    # -------------------------------------------------------------- queries --
    def contains(self, url: str) -> bool:
        return (url or "").strip() in self._urls

    def __len__(self) -> int:
        return len(self._urls)

    # --------------------------------------------------------------- edits --
    def add(self, url: str) -> bool:
        """Remember one dead URL. Returns ``True`` when it was new."""
        url = (url or "").strip()
        if not url or url in self._urls:
            return False
        self._urls[url] = None
        while len(self._urls) > MAX_ENTRIES:
            self._urls.popitem(last=False)
        self._unsaved += 1
        if self._unsaved >= SAVE_EVERY:
            self.save()
        return True

    def clear(self) -> None:
        """Forget every failure — a user asking to retry the logos."""
        if not self._urls:
            return
        self._urls.clear()
        self._unsaved += 1
        self.save()
