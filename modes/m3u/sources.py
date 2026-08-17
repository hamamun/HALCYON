"""The saved-sources store — up to 7 playlists (§P2.4, owner decision).

Each source is a name plus either a remote URL or a local ``.m3u`` /
``.m3u8`` / ``.pls`` file. This file is pure Python (json + pathlib) so it is testable
without Qt; the Qt-facing wrapper lives in :mod:`modes.m3u.playlist`.

The store belongs to M3U alone (§A.1): it lives at ``m3u-sources.json`` in the
app's data directory, and deleting ``modes/m3u/`` leaves nothing dangling.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: Owner's cap — at seven, Add disables with "Remove one to add another" (§P2.4).
MAX_SOURCES = 7

KIND_URL = "url"
KIND_FILE = "file"


@dataclass
class Source:
    id: str
    name: str
    kind: str          # KIND_URL | KIND_FILE
    location: str      # the URL, or the playlist's path on disk

    def as_dict(self) -> dict:
        return asdict(self)


class SourcesStore:
    """A tiny JSON list with a size cap. Load once, edit, save atomically."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._sources: list[Source] = []
        self.load()

    # ------------------------------------------------------------------ io --
    def load(self) -> None:
        """Read the store. A missing file is normal; a corrupt one is not
        fatal — start empty rather than crash a mode over a damaged JSON file."""
        self._sources = []
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("sources store unreadable (%s) — starting empty", self._path)
            return
        for item in raw if isinstance(raw, list) else []:
            try:
                source = Source(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    kind=str(item["kind"]),
                    location=str(item["location"]),
                )
            except (KeyError, TypeError):
                continue
            if source.kind in (KIND_URL, KIND_FILE) and source.location:
                self._sources.append(source)

    def save(self) -> None:
        """Write atomically: a half-written JSON file is a corrupt store."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=self._path.name, dir=str(self._path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump([s.as_dict() for s in self._sources], handle,
                          ensure_ascii=False, indent=2)
            os.replace(tmp_name, self._path)
        except OSError:
            log.warning("could not write sources store %s", self._path,
                        exc_info=True)
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    # -------------------------------------------------------------- queries --
    def list(self) -> list[Source]:
        return list(self._sources)

    def get(self, source_id: str) -> Source | None:
        for source in self._sources:
            if source.id == source_id:
                return source
        return None

    @property
    def full(self) -> bool:
        return len(self._sources) >= MAX_SOURCES

    # --------------------------------------------------------------- edits --
    def add(self, name: str, kind: str, location: str) -> Source | None:
        """Append a source; returns ``None`` when the store is full — the cap
        is the owner's rule, and the dialog shows the hint (§P2.4)."""
        if self.full or kind not in (KIND_URL, KIND_FILE) or not location.strip():
            return None
        name = name.strip() or Path(location.split("?", 1)[0]).stem or location
        source = Source(
            id=uuid.uuid4().hex[:12],
            name=name,
            kind=kind,
            location=location.strip(),
        )
        self._sources.append(source)
        self.save()
        return source

    def update(self, source_id: str, name: str, location: str) -> bool:
        source = self.get(source_id)
        if source is None:
            return False
        if name.strip():
            source.name = name.strip()
        if location.strip():
            source.location = location.strip()
        self.save()
        return True

    def remove(self, source_id: str) -> bool:
        source = self.get(source_id)
        if source is None:
            return False
        self._sources.remove(source)
        self.save()
        return True
