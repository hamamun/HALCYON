"""Bookmark store for Web mode (§P3.5).

Permanent JSON store under ``%APPDATA%\\Halcyon\\bookmarks.json`` (or non-Windows
app data equivalent). Starts completely blank — no default bookmarks.
Owned by Web mode alone (§A.1); deleted with the mode.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

logger = logging.getLogger("modes.web.bookmarks")


def _get_bookmarks_path() -> Path:
    """Return permanent storage path for bookmarks.json."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    else:
        base = Path.home() / ".config"
    dir_path = base / "Halcyon"
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path / "bookmarks.json"


class BookmarksStore(QObject):
    """Permanent bookmark manager and QML context bridge (§P3.5)."""

    bookmarksChanged = Signal()

    def __init__(self, path: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = path or _get_bookmarks_path()
        self._items: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._items = []
            return
        try:
            content = self._path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, list):
                self._items = data
            else:
                self._items = []
        except Exception as exc:
            logger.warning("Failed loading bookmarks.json: %s", exc)
            self._items = []

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._items, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("Failed saving bookmarks.json: %s", exc)

    @Property(int, notify=bookmarksChanged)
    def count(self) -> int:
        return len(self._items)

    @Slot(str, result=bool)
    def isBookmarked(self, url: str) -> bool:
        """Return True if URL is currently bookmarked (§P3.5 quick star)."""
        clean_url = (url or "").strip()
        if not clean_url:
            return False
        return any(b.get("url") == clean_url for b in self._items)

    @Slot(str, result="QVariantMap")
    def getByUrl(self, url: str) -> dict[str, Any]:
        """Return bookmark dict for URL or empty map if not bookmarked."""
        clean_url = (url or "").strip()
        for b in self._items:
            if b.get("url") == clean_url:
                return dict(b)
        return {}

    @Slot(result="QVariantList")
    def getAll(self) -> list[dict[str, Any]]:
        """Return all saved bookmarks as a list of dictionaries."""
        return [dict(b) for b in self._items]

    @Slot(str, result="QVariantList")
    def search(self, query: str) -> list[dict[str, Any]]:
        """Filter bookmarks by title or URL as user types (§P3.5)."""
        q = (query or "").strip().lower()
        if not q:
            return self.getAll()
        return [
            dict(b)
            for b in self._items
            if q in str(b.get("title", "")).lower()
            or q in str(b.get("url", "")).lower()
        ]

    @Slot(str, str, result=bool)
    def addBookmark(self, title: str, url: str) -> bool:
        """Add a new bookmark (§P3.5)."""
        clean_url = (url or "").strip()
        if not clean_url:
            return False
        clean_title = (title or clean_url).strip()
        # Avoid duplicate URL entries: update title if exists
        for b in self._items:
            if b.get("url") == clean_url:
                b["title"] = clean_title
                self._save()
                self.bookmarksChanged.emit()
                return True
        item = {
            "id": uuid.uuid4().hex,
            "title": clean_title,
            "url": clean_url,
            "added_at": int(time.time()),
        }
        self._items.append(item)
        self._save()
        self.bookmarksChanged.emit()
        return True

    @Slot(str, str, str, result=bool)
    def updateBookmark(self, old_url: str, new_title: str, new_url: str) -> bool:
        """Edit an existing bookmark's title or URL (§P3.5)."""
        old_url_clean = (old_url or "").strip()
        new_url_clean = (new_url or "").strip()
        if not old_url_clean or not new_url_clean:
            return False
        new_title_clean = (new_title or new_url_clean).strip()
        for b in self._items:
            if b.get("url") == old_url_clean:
                b["title"] = new_title_clean
                b["url"] = new_url_clean
                self._save()
                self.bookmarksChanged.emit()
                return True
        return False

    @Slot(str, result=bool)
    def removeBookmark(self, url: str) -> bool:
        """Remove bookmark by URL (§P3.5)."""
        clean_url = (url or "").strip()
        before = len(self._items)
        self._items = [b for b in self._items if b.get("url") != clean_url]
        if len(self._items) != before:
            self._save()
            self.bookmarksChanged.emit()
            return True
        return False

    @Slot(str, result=bool)
    def removeById(self, bookmark_id: str) -> bool:
        """Remove bookmark by unique ID."""
        before = len(self._items)
        self._items = [b for b in self._items if b.get("id") != bookmark_id]
        if len(self._items) != before:
            self._save()
            self.bookmarksChanged.emit()
            return True
        return False

    @Slot(int, int, result=bool)
    def reorder(self, from_idx: int, to_idx: int) -> bool:
        """Reorder bookmark items by moving item from from_idx to to_idx (§P3.5)."""
        if (
            from_idx < 0
            or from_idx >= len(self._items)
            or to_idx < 0
            or to_idx >= len(self._items)
            or from_idx == to_idx
        ):
            return False
        item = self._items.pop(from_idx)
        self._items.insert(to_idx, item)
        self._save()
        self.bookmarksChanged.emit()
        return True
