"""M3U channel favourites store.

Pure Python and M3U-only: favourites are stored per saved playlist source, not
as a global channel library.  A channel is identified by its stream URL inside
that source, which is the same stable identity the channel model already uses
when preserving the current item across reloads.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


class FavouritesStore:
    """Small JSON map: ``source_id -> [channel_url, ...]``.

    The format intentionally stays separate from ``m3u-sources.json`` so source
    management and favourite-channel state can evolve independently.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._items: dict[str, set[str]] = {}
        self.load()

    # ------------------------------------------------------------------ io --
    def load(self) -> None:
        self._items = {}
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("favourites store unreadable (%s) — starting empty", self._path)
            return
        if not isinstance(raw, dict):
            return
        for source_id, urls in raw.items():
            if not isinstance(source_id, str) or not isinstance(urls, list):
                continue
            source_id = source_id.strip()
            cleaned = {url.strip() for url in urls if isinstance(url, str) and url.strip()}
            if source_id and cleaned:
                self._items[source_id] = cleaned

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=self._path.name, dir=str(self._path.parent)
        )
        try:
            payload = {
                source_id: sorted(urls)
                for source_id, urls in sorted(self._items.items())
                if urls
            }
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_name, self._path)
        except OSError:
            log.warning("could not write favourites store %s", self._path, exc_info=True)
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    # -------------------------------------------------------------- queries --
    def list(self, source_id: str) -> set[str]:
        return set(self._items.get(source_id, set()))

    def contains(self, source_id: str, url: str) -> bool:
        return bool(source_id and url in self._items.get(source_id, set()))

    # --------------------------------------------------------------- edits --
    def set(self, source_id: str, url: str, favourite: bool) -> bool:
        """Set membership. Returns ``True`` when the store changed."""
        source_id = (source_id or "").strip()
        url = (url or "").strip()
        if not source_id or not url:
            return False
        urls = self._items.setdefault(source_id, set()) if favourite else self._items.get(source_id)
        before = bool(urls and url in urls)
        if before == favourite:
            return False
        if favourite:
            assert urls is not None
            urls.add(url)
        elif urls is not None:
            urls.discard(url)
            if not urls:
                self._items.pop(source_id, None)
        self.save()
        return True

    def toggle(self, source_id: str, url: str) -> bool | None:
        """Toggle one URL. Returns the new state, or ``None`` for bad input."""
        source_id = (source_id or "").strip()
        url = (url or "").strip()
        if not source_id or not url:
            return None
        new_state = not self.contains(source_id, url)
        self.set(source_id, url, new_state)
        return new_state

    def remove_source(self, source_id: str) -> bool:
        if source_id not in self._items:
            return False
        self._items.pop(source_id, None)
        self.save()
        return True
